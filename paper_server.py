"""Serve one selected paper index and its files on the loopback interface."""

import argparse
import http.server
import json
import mimetypes
import os
import time
import threading
from pathlib import Path
from urllib.parse import unquote, urlsplit


def inside(root: Path, relative: str) -> Path | None:
    target = (root / relative).resolve()
    return target if os.path.commonpath((str(root), str(target))) == str(root) else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--viewer-dir", type=Path, required=True)
    args = parser.parse_args()
    index = args.index.resolve(strict=True)
    root = index.parent
    viewer_dir = args.viewer_dir.resolve(strict=True)
    last_request = time.monotonic()
    bridge = None
    bridge_lock = threading.Lock()

    def semantic_search(query: str, top_k: int) -> list[str]:
        nonlocal bridge
        # Serialize access to the shared bridge and initialize only on first search.
        with bridge_lock:
            if bridge is None:
                from utils.semantic_search.bridge import SSBridge
                bridge = SSBridge(
                    paper_index_path=index,
                    paper_method_dir=root / "methods",
                    vectors_path=os.environ.get("VECTORS_PATH") or (
                        Path(os.environ.get("SEMANTIC_SEARCH_DATA_DIR", str(root / "data"))) / "vectors.jsonl"
                    ),
                )
            return bridge.retrieve(query, top_k=top_k)

    class Handler(http.server.BaseHTTPRequestHandler):
        def send_json(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            nonlocal last_request
            last_request = time.monotonic()
            if urlsplit(self.path).path != "/api/semantic-search":
                self.send_json(404, {"error": "接口不存在"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32768:
                    raise ValueError("请求内容为空或过长")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("请求必须是 JSON 对象")
                query = payload.get("query")
                top_k = payload.get("top_k", 5)
                if not isinstance(query, str) or not query.strip() or len(query) > 4000:
                    raise ValueError("请输入 1 至 4000 字的搜索内容")
                if type(top_k) is not int or not 1 <= top_k <= 100:
                    raise ValueError("结果数量必须是 1 至 100 的整数")
            except (ValueError, UnicodeError) as error:
                self.send_json(400, {"error": str(error)})
                return
            try:
                ids = semantic_search(query.strip(), top_k)
                # One paper may match several vector chunks; preserve the first rank.
                ids = list(dict.fromkeys(ids))
            except Exception as error:
                if isinstance(error, (ImportError, RuntimeError)):
                    message = str(error)
                else:
                    message = "检索失败，请检查向量文件及嵌入服务配置"
                self.send_json(503, {"error": message})
                return
            finally:
                last_request = time.monotonic()
            self.send_json(200, {"paper_ids": ids})

        def do_GET(self) -> None:
            nonlocal last_request
            last_request = time.monotonic()
            path = unquote(urlsplit(self.path).path)
            if path == "/heartbeat":
                self.send_response(204)
                self.end_headers()
                return
            if path in ("/", "/paper_viewer.html"):
                file = viewer_dir / "paper_viewer.html"
            elif path == "/paper_index.json":
                file = index
            elif path.startswith("/vendor/"):
                file = inside(viewer_dir, path.lstrip("/"))
            elif path.startswith("/viewer/"):
                file = inside(viewer_dir / "viewer", path[len("/viewer/"):])
            elif path.startswith("/files/"):
                file = inside(root, path[len("/files/"):])
            else:
                self.send_error(404)
                return
            if file is None or not file.is_file():
                self.send_error(404)
                return
            try:
                data = file.read_bytes()
            except OSError:
                self.send_error(500)
                return
            content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if file.suffix.lower() == ".js":
                content_type = "text/javascript"
            if file.suffix.lower() in (".html", ".json", ".md", ".js"):
                content_type += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 30
    server.daemon_threads = True
    print(f"http://127.0.0.1:{server.server_port}/", flush=True)
    # The page keeps the service alive. It exits after the browser closes or stops responding.
    while time.monotonic() - last_request < 600:
        server.handle_request()
    server.server_close()


if __name__ == "__main__":
    main()
