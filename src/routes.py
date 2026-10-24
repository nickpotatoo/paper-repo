"""Build the FastAPI app and forward requests to repo and search modules."""

import asyncio
import json
import logging
import mimetypes
import time
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from html import escape
from http import HTTPStatus
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from src.config import (
    PAPERS_PATH, TAXONOMY_PATH, REPO_STATE_PATH, PDFS_DIR,
    DETAILED_SUMMARIES_DIR, VIEWER_DIR, VECTOR_DATA_DIR,
    HTTP_RESPONSE_HEADERS, SEARCH_MAX_REQUEST_BYTES, SEARCH_MAX_QUERY_CHARS,
    SEARCH_MIN_TOP_K, SEARCH_MAX_TOP_K, TOP_K,
    IDLE_TIMEOUT_SECONDS, IDLE_CHECK_INTERVAL_SECONDS,
    VALIDATE_REQUEST_DATA, AUTO_SHUTDOWN, APP_TITLE,
)
from src.load_data import validate_data, load_papers, load_taxonomy, load_state
from src.semantic_search.lifecycle import paper_vector_service_lifespan

logger = logging.getLogger(__name__)


def inside(root: Path, relative: str) -> Path | None:
    """Reject traversal and symlinks escaping the requested root."""
    try:
        root = root.resolve()
        target = (root / relative).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    return target if target.is_relative_to(root) else None


def _json_response(status: int, payload: dict | list) -> JSONResponse:
    return JSONResponse(
        payload, status_code=status, media_type="application/json; charset=utf-8",
        headers=HTTP_RESPONSE_HEADERS,
    )


def _file_error(status: int) -> Response:
    reason = HTTPStatus(status)
    body = (
        "<!doctype html><html><head><title>Error response</title></head><body>"
        f"<h1>Error response</h1><p>Error code: {status}</p>"
        f"<p>Message: {escape(reason.phrase)}.</p>"
        f"<p>Error code explanation: {status} - {escape(reason.description)}.</p>"
        "</body></html>"
    )
    return Response(body, status_code=status, media_type="text/html")


def _report_data_validate_errors(errors: list[str]) -> None:
    for error in errors:
        logger.warning("数据校验：%s", error)


def _read_repo_json(
    reader: Callable, source: Path, *,
    validate: bool, report_data_validate_errors: Callable[[list[str]], None],
) -> Response:
    """Read fresh repo data and consistently translate filesystem/JSON errors."""
    try:
        payload, errors = reader(source, validate=validate)
    except FileNotFoundError:
        return _json_response(404, {"error": "资料文件不存在"})
    except ValueError:
        return _json_response(500, {"error": "资料文件格式错误，请检查服务端数据"})
    except OSError:
        return _json_response(500, {"error": "无法读取资料文件"})
    report_data_validate_errors(errors)
    return _json_response(200, payload)


def _serve_file(root: Path, relative_path: str) -> Response:
    """Apply the same path, MIME, cache and error policy to every file route."""
    file = inside(root, relative_path)
    try:
        if file is None or not file.is_file():
            return _file_error(404)
        content = file.read_bytes()
    except FileNotFoundError:
        return _file_error(404)
    except OSError:
        return _file_error(500)
    content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    if file.suffix.lower() == ".js":
        content_type = "text/javascript"
    if file.suffix.lower() in (".html", ".json", ".md", ".js", ".css"):
        content_type += "; charset=utf-8"
    return Response(content, headers={"Content-Type": content_type, **HTTP_RESPONSE_HEADERS})


async def _parse_search_request(request: Request) -> tuple[str, int]:
    """Bound the body before parsing; preserve strict types and the 400 contract."""
    length = int(request.headers.get("Content-Length", "0"))
    if not 0 < length <= SEARCH_MAX_REQUEST_BYTES:
        raise ValueError("请求内容为空或过长")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > SEARCH_MAX_REQUEST_BYTES:
            raise ValueError("请求内容为空或过长")
        body.extend(chunk)
    if len(body) != length:
        raise ValueError("请求内容长度不匹配")
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("请求必须是 JSON 对象")
    query = payload.get("query")
    top_k = payload.get("top_k", TOP_K)
    if not isinstance(query, str) or not query.strip() or len(query) > SEARCH_MAX_QUERY_CHARS:
        raise ValueError(f"请输入 1 至 {SEARCH_MAX_QUERY_CHARS} 字的搜索内容")
    if type(top_k) is not int or not SEARCH_MIN_TOP_K <= top_k <= SEARCH_MAX_TOP_K:
        raise ValueError(f"结果数量必须是 {SEARCH_MIN_TOP_K} 至 {SEARCH_MAX_TOP_K} 的整数")
    return query.strip(), top_k


def create_router(
    *,
    papers_path: Path,
    taxonomy_path: Path,
    state_path: Path,
    viewer_dir: Path,
    validate: bool,
    semantic_search: Callable[[str, int], list[str]],
    report_data_validate_errors: Callable[[list[str]], None],
) -> APIRouter:
    """Register explicit endpoints before the unknown-path fallbacks."""
    router = APIRouter()

    @router.post("/api/semantic-search")
    async def search(request: Request) -> Response:
        try:
            query, top_k = await _parse_search_request(request)
        except ValueError as error:
            return _json_response(400, {"error": str(error)})
        try:
            ids = await run_in_threadpool(semantic_search, query, top_k)
        except Exception as error:
            # Do not log request text, API keys, or raw upstream responses.
            logger.warning("语义检索失败：%s", type(error).__name__)
            message = str(error) if isinstance(error, (ImportError, RuntimeError)) else "检索失败，请检查向量文件及嵌入服务配置"
            return _json_response(503, {"error": message})
        return _json_response(200, {"paper_ids": ids})

    @router.get("/heartbeat")
    def heartbeat() -> Response:
        return Response(status_code=204)

    @router.get("/papers.json")
    def papers() -> Response:
        return _read_repo_json(load_papers, papers_path, validate=validate, report_data_validate_errors=report_data_validate_errors)

    @router.get("/taxonomy.json")
    def taxonomy() -> Response:
        return _read_repo_json(load_taxonomy, taxonomy_path, validate=validate, report_data_validate_errors=report_data_validate_errors)

    @router.get("/repo_state.json")
    def repo_state() -> Response:
        return _read_repo_json(load_state, state_path, validate=validate, report_data_validate_errors=report_data_validate_errors)

    @router.get("/")
    @router.get("/paper_viewer.html")
    def viewer() -> Response:
        return _serve_file(viewer_dir, "paper_viewer.html")

    @router.get("/vendor/{relative_path:path}")
    def vendor_file(relative_path: str) -> Response:
        return _serve_file(viewer_dir / "vendor", relative_path)

    @router.get("/viewer/{relative_path:path}")
    def viewer_file(relative_path: str) -> Response:
        return _serve_file(viewer_dir / "viewer", relative_path)

    @router.get("/files/pdfs/{relative_path:path}")
    def pdf_file(relative_path: str) -> Response:
        return _serve_file(PDFS_DIR, relative_path)

    @router.get("/files/detailed_summaries/{relative_path:path}")
    def detailed_summary_file(relative_path: str) -> Response:
        return _serve_file(DETAILED_SUMMARIES_DIR, relative_path)

    @router.post("/{path:path}")
    def unknown_post(path: str) -> Response:
        return _json_response(404, {"error": "接口不存在"})

    @router.get("/{path:path}")
    def unknown_get(path: str) -> Response:
        return _file_error(404)

    return router


class _AppRuntime:
    """Track HTTP request activity; vector lifecycle belongs to semantic_search."""
    def __init__(self) -> None:
        self.last_request = time.monotonic()
        self.active_requests = 0

    async def watch_idle(self, timeout: float, on_idle: Callable[[], None]) -> None:
        while True:
            await asyncio.sleep(min(IDLE_CHECK_INTERVAL_SECONDS, timeout))
            if not self.active_requests and time.monotonic() - self.last_request >= timeout:
                on_idle()
                return


class _ActivityMiddleware:
    """Count requests through response completion, including file downloads."""
    def __init__(self, app: ASGIApp, runtime: _AppRuntime) -> None:
        self.app = app
        self.runtime = runtime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        self.runtime.active_requests += 1
        self.runtime.last_request = time.monotonic()
        try:
            await self.app(scope, receive, send)
        finally:
            self.runtime.active_requests -= 1
            self.runtime.last_request = time.monotonic()


def create_app(
    papers_path: Path | None = None,
    taxonomy_path: Path | None = None,
    state_path: Path | None = None,
    viewer_dir: Path | None = None,
    *,
    validate: bool = VALIDATE_REQUEST_DATA,
    auto_shutdown: bool = AUTO_SHUTDOWN,
    on_idle: Callable[[], None] | None = None,
    idle_timeout: float = IDLE_TIMEOUT_SECONDS,
) -> FastAPI:
    """Assemble validation, runtime, lifecycle and routes without starting Uvicorn.

    Startup association validation is always enforced. validate only controls
    per-request validation; JSON sources are still reread for every request.
    """
    papers_path = Path(PAPERS_PATH if papers_path is None else papers_path).resolve(strict=True)
    taxonomy_path = Path(TAXONOMY_PATH if taxonomy_path is None else taxonomy_path).resolve(strict=True)
    state_path = Path(REPO_STATE_PATH if state_path is None else state_path).resolve(strict=True)
    viewer_dir = Path(VIEWER_DIR if viewer_dir is None else viewer_dir).resolve(strict=True)
    if idle_timeout <= 0:
        raise ValueError("idle_timeout 必须大于 0")
    _report_data_validate_errors(validate_data(
        load_papers(papers_path, validate=False)[0],
        load_taxonomy(taxonomy_path, validate=False)[0],
        load_state(state_path, validate=False)[0],
        root=None,
    ))
    runtime = _AppRuntime()

    def forward_search(query: str, top_k: int) -> list[str]:
        service = app.state.paper_vector_service
        if service is None:
            raise RuntimeError("论文向量服务尚未启动或已关闭")
        return service.retrieve(query, top_k=top_k)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.last_request = time.monotonic()
        async with paper_vector_service_lifespan(
            papers_path=papers_path, taxonomy_path=taxonomy_path,
            detailed_summaries_dir=DETAILED_SUMMARIES_DIR,
            vectors_dir=VECTOR_DATA_DIR,
        ) as service:
            app.state.paper_vector_service = service
            watcher = None
            try:
                watcher = (
                    asyncio.create_task(runtime.watch_idle(idle_timeout, on_idle))
                    if auto_shutdown and on_idle is not None else None
                )
                yield
            finally:
                app.state.paper_vector_service = None
                if watcher is not None:
                    watcher.cancel()
                    with suppress(asyncio.CancelledError):
                        await watcher

    app = FastAPI(
        title=APP_TITLE, lifespan=lifespan, redirect_slashes=False,
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.state.runtime = runtime
    app.state.paper_vector_service = None
    app.add_middleware(_ActivityMiddleware, runtime=runtime)
    app.include_router(create_router(
        papers_path=papers_path, taxonomy_path=taxonomy_path,
        state_path=state_path, viewer_dir=viewer_dir, validate=validate,
        semantic_search=forward_search, report_data_validate_errors=_report_data_validate_errors,
    ))
    return app
