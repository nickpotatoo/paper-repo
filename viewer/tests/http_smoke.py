"""Check local viewer routes without calling embedding services."""

import json
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
process = subprocess.Popen(
    [sys.executable, "-u", str(ROOT / "paper_server.py"), "--index", str(ROOT / "paper_index.json"), "--viewer-dir", str(ROOT)],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
)
try:
    url = process.stdout.readline().strip()
    if not url.startswith("http://127.0.0.1:"):
        raise RuntimeError(process.stderr.read())
    for file in (ROOT / "viewer").rglob("*"):
        if not file.is_file() or file.suffix not in (".js", ".css"):
            continue
        relative = file.relative_to(ROOT).as_posix()
        with urlopen(url + relative, timeout=5) as response:
            assert response.status == 200 and response.read() == file.read_bytes(), relative
            if file.suffix == ".js":
                assert response.headers.get_content_type() == "text/javascript", relative
    with urlopen(url, timeout=5) as response:
        html = response.read().decode("utf-8")
        assert 'type="module" src="./viewer/js/app.js"' in html and "<style>" not in html
    with urlopen(url + "paper_index.json", timeout=5) as response:
        assert "papers" in json.load(response)
    try:
        urlopen(url + "viewer/../paper_server.py", timeout=5)
    except HTTPError as error:
        assert error.code == 404
    else:
        raise AssertionError("Traversal not rejected")
    print("PASS: local HTTP module/CSS routes, JavaScript MIME, HTML/index, traversal rejection.")
finally:
    process.terminate()
    process.wait(timeout=5)
