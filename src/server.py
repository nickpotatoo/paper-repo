"""Serve the paper repo's split data and viewer on the loopback interface."""

import http.server
import json
import mimetypes
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from src.config import PAPERS_PATH, TAXONOMY_PATH, REPO_STATE_PATH, PDFS_DIR, DETAILED_SUMMARIES_DIR, VIEWER_DIR
from src.load_data import validate_data, load_papers, load_taxonomy, load_state


def inside(root: Path, relative: str) -> Path | None:
    """Resolve a requested file while rejecting traversal and escaping symlinks."""
    try:
        root = root.resolve()
        target = (root / relative).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    return target if target.is_relative_to(root) else None


def launch(
    papers_path: Path | None = None,
    taxonomy_path: Path | None = None,
    state_path: Path | None = None,
    viewer_dir: Path | None = None,
    open_browser: bool = True,
    auto_shutdown: bool = True,
    *,
    validate: bool = True,
    port: int | None = None,
) -> None:
    """Serve three JSON sources directly; no aggregate index is created.

    Fatal loading/validation errors prevent startup. Other findings go to stderr.
    validate=False skips data validation during runtime, but validation is enforced when launching.
    PDF paths are relative to PDFS_DIR; detailed summary files are served from DETAILED_SUMMARIES_DIR.
    """
    papers_path = Path(PAPERS_PATH if papers_path is None else papers_path).resolve(strict=True)
    taxonomy_path = Path(TAXONOMY_PATH if taxonomy_path is None else taxonomy_path).resolve(strict=True)
    state_path = Path(REPO_STATE_PATH if state_path is None else state_path).resolve(strict=True)
    viewer_dir = Path(VIEWER_DIR if viewer_dir is None else viewer_dir).resolve(strict=True)

    def report_errors(errors: list[str]) -> None:
        for error in errors:
            print(f"数据校验：{error}", file=sys.stderr)

    errors = validate_data(
        load_papers(papers_path, validate=False)[0],
        load_taxonomy(taxonomy_path, validate=False)[0],
        load_state(state_path, validate=False)[0],
        root=None
    )
    report_errors(errors)

    data_routes = {
        "/papers.json": (load_papers, papers_path),
        "/taxonomy.json": (load_taxonomy, taxonomy_path),
        "/repo_state.json": (load_state, state_path),
    }
    last_request = time.monotonic()
    bridge = None
    bridge_lock = threading.Lock()

    def semantic_search(query: str, top_k: int) -> list[str]:
        nonlocal bridge
        # Initialize lazily so browsing works without embedding dependencies or keys.
        with bridge_lock:
            if bridge is None:
                from src.semantic_search.bridge import SSBridge
                from src.config import VECTOR_DATA_DIR
                bridge = SSBridge(
                    papers_path=papers_path,
                    taxonomy_path=taxonomy_path,
                    detailed_summaries_dir=DETAILED_SUMMARIES_DIR,
                    vectors_dir=VECTOR_DATA_DIR,
                )
            return bridge.retrieve(query, top_k=top_k)

    class Handler(http.server.BaseHTTPRequestHandler):
        def send_json(self, status: int, payload: dict | list) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

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
                ids = list(dict.fromkeys(ids))
            except Exception as error:
                message = str(error) if isinstance(error, (ImportError, RuntimeError)) else "检索失败，请检查向量文件及嵌入服务配置"
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
            if path in data_routes:
                reader, source = data_routes[path]
                errors = []
                try:
                    payload, errors = reader(source, validate=validate)
                except FileNotFoundError:
                    self.send_json(404, {"error": "资料文件不存在"})
                    return
                except (ValueError, UnicodeError):
                    self.send_json(500, {"error": "资料文件格式错误，请检查服务端数据"})
                    return
                except OSError:
                    self.send_json(500, {"error": "无法读取资料文件"})
                    return
                report_errors(errors)
                self.send_json(200, payload)
                return
            if path in ("/", "/paper_viewer.html"):
                file = inside(viewer_dir, "paper_viewer.html")
            elif path.startswith("/vendor/"):
                file = inside(viewer_dir / "vendor", path[len("/vendor/"):])
            elif path.startswith("/viewer/"):
                file = inside(viewer_dir / "viewer", path[len("/viewer/"):])
            elif path.startswith("/files/pdfs/"):
                file = inside(PDFS_DIR, path[len("/files/pdfs/"):])
            elif path.startswith("/files/detailed_summaries/"):
                file = inside(DETAILED_SUMMARIES_DIR, path[len("/files/detailed_summaries/"):])
            else:
                self.send_error(404)
                return
            try:
                if file is None or not file.is_file():
                    self.send_error(404)
                    return
                content = file.read_bytes()
            except FileNotFoundError:
                self.send_error(404)
                return
            except OSError:
                self.send_error(500)
                return
            content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if file.suffix.lower() == ".js":
                content_type = "text/javascript"
            if file.suffix.lower() in (".html", ".json", ".md", ".js", ".css"):
                content_type += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port or 0), Handler)
    server.timeout = 30
    server.daemon_threads = True
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(url, flush=True)
        if open_browser:
            webbrowser.open(url)
        # Heartbeats keep the service alive; stop after ten minutes without requests.
        while time.monotonic() - last_request < 600 or not auto_shutdown:
            server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    launch()
