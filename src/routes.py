"""构建 FastAPI 应用，并将请求转发给资料库和检索模块。"""

import asyncio
import base64
import binascii
import hmac
import json
import logging
import mimetypes
import time
import tempfile
import uuid
from urllib.parse import unquote
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from html import escape
from http import HTTPStatus
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from src.config import (
    PAPERS_PATH, TAXONOMY_PATH, REPO_STATE_PATH, PDFS_DIR,
    DETAILED_SUMMARIES_DIR, VIEWER_DIR, VECTOR_DATA_DIR,
    HTTP_RESPONSE_HEADERS, SEARCH_MAX_REQUEST_BYTES, SEARCH_MAX_QUERY_CHARS,
    SEARCH_MIN_TOP_K, SEARCH_MAX_TOP_K, TOP_K,
    IDLE_TIMEOUT_SECONDS, IDLE_CHECK_INTERVAL_SECONDS,
    VALIDATE_REQUEST_DATA, AUTO_SHUTDOWN, APP_TITLE,
    SERVICE_PASSWORD, NEW_PAPERS_DIR, TASKS_DIR, UPLOAD_MAX_BYTES,
)
from src.PaperProcessing import TaskManager, UnsupportedRegenerationAction
from src.RepoManager import (
    validate_data, load_papers, load_taxonomy, load_state,
)
from src.SemanticSearch.lifecycle import paper_vector_service_lifespan

logger = logging.getLogger(__name__)

_TASK_CONTENTS = {
    "pdf": ("原始 PDF", "input/source.pdf", "application/pdf"),
    "metadata": ("论文元数据", "analysis/metadata.json", "application/json"),
    "classification": ("分类", "analysis/classification.json", "application/json"),
    "rough-summary": ("粗略总结", "analysis/rough_summary.txt", "text/plain"),
    "detailed-summary": ("精细总结（Markdown）", "analysis/detailed_summary.md", "text/plain"),
    "extracted-text": ("提取文本（Markdown）", "extraction/extracted.md", "text/plain"),
    "validation": ("校验报告", "validation/report.json", "application/json"),
    "duplicate-check": ("查重结果", "duplicate/result.json", "application/json"),
    "pdf-info": ("PDF 信息", "extraction/pdf_info.json", "application/json"),
    "quality": ("提取质量报告", "extraction/quality.json", "application/json"),
}


def _task_content_path(storage: TaskManager, task_id: str, relative: str) -> Path:
    path = storage.artifact_path(task_id, relative)
    if path != storage.root / task_id / relative or not path.is_file():
        raise FileNotFoundError(relative)
    return path


def inside(root: Path, relative: str) -> Path | None:
    """拒绝目录穿越及指向指定根目录之外的符号链接。"""
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
    """读取最新资料库数据，并统一转换文件系统及 JSON 错误。"""
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


def _serve_file(
    root: Path, relative_path: str, *,
    media_type: str | None = None, filename: str | None = None,
) -> Response:
    """校验文件路径，并交由 FileResponse 传输文件。"""
    file = inside(root, relative_path)
    try:
        if file is None or not file.is_file():
            return _file_error(404)
    except FileNotFoundError:
        return _file_error(404)
    except OSError:
        return _file_error(500)
    if media_type is None:
        suffix = file.suffix.lower()
        media_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        if suffix == ".js":
            media_type = "text/javascript"
        if suffix in (".html", ".json", ".md", ".js", ".css"):
            media_type += "; charset=utf-8"
    return FileResponse(file, media_type=media_type, filename=filename, headers=HTTP_RESPONSE_HEADERS)


async def _parse_search_request(request: Request) -> tuple[str, int]:
    """解析前限制请求体大小，并保持严格类型校验及 400 错误响应约定。"""
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


def _verify_service_password(password: str, *, expected: str = SERVICE_PASSWORD) -> bool:
    """验证服务密码。"""
    if not expected:
        return True
    if not password or not isinstance(password, str):
        return False
    return hmac.compare_digest(password.encode('utf-8'), expected.encode('utf-8'))


def _require_service_password(request: Request) -> Response | None:
    if not SERVICE_PASSWORD:
        return _json_response(503, {"error": "服务端尚未设置服务密码"})
    try:
        password = base64.b64decode(
            request.headers.get("x-service-password", ""), validate=True,
        ).decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error):
        return _json_response(401, {"error": "密码错误"})
    if not _verify_service_password(password, expected=SERVICE_PASSWORD):
        return _json_response(401, {"error": "密码错误"})
    return None


def create_router(
    *,
    papers_path: Path,
    taxonomy_path: Path,
    state_path: Path,
    viewer_dir: Path,
    validate: bool,
    semantic_search: Callable[[str, int], list[str]],
    report_data_validate_errors: Callable[[list[str]], None],
    tasks_dir: Path = TASKS_DIR,
) -> APIRouter:
    """先注册明确的接口，再注册未知路径的兜底路由。"""
    router = APIRouter()
    tasks_manager = TaskManager(
        tasks_dir, create_root=False, papers_path=papers_path, taxonomy_path=taxonomy_path,
    )

    @router.get("/api/tasks")
    def task_statuses(request: Request) -> Response:
        auth_error = _require_service_password(request)
        if auth_error is not None:
            return auth_error
        try:
            tasks = tasks_manager.list_tasks()
        except (OSError, ValueError, RuntimeError) as error:
            logger.warning("读取论文处理任务失败：%s", type(error).__name__)
            return _json_response(500, {"error": "无法读取任务状态，请检查服务端任务目录"})
        return _json_response(200, {"tasks": [
            {
                "task_id": task.task_id,
                "status": task.status,
                "current_stage": task.current_stage,
                "updated_at": task.updated_at.isoformat(),
                "source": {"original_filename": task.source.original_filename},
                "duplicate_of": task.duplicate_of,
                "paper_id": task.paper_id,
                "can_ingest": task.can_ingest,
                "stages": {
                    name: {
                        "status": stage.status,
                        "wait_reason": stage.wait_reason,
                        "error": {"message": "阶段执行失败，详情请查看服务端任务记录。"}
                        if stage.error or stage.status == "failed" else None,
                    }
                    for name, stage in task.stages.items()
                },
            }
            for task in tasks
        ]})

    @router.post("/api/tasks/{task_id}/ingest")
    def ingest_task(request: Request, task_id: str) -> Response:
        auth_error = _require_service_password(request)
        if auth_error is not None:
            return auth_error
        try:
            paper_id = tasks_manager.ingest_task(task_id)
        except FileExistsError as error:
            return _json_response(409, {"error": str(error)})
        except ValueError as error:
            return _json_response(409, {"error": str(error)})
        except OSError as error:
            if isinstance(error, FileNotFoundError):
                return _json_response(404, {"error": "任务或资料库文件不存在"})
            logger.warning("论文入库失败：%s", type(error).__name__)
            return _json_response(500, {"error": "写入资料库失败，请检查服务端文件"})
        return _json_response(200, {"paper_id": paper_id})

    @router.post("/api/tasks/{task_id}/vector")
    def generate_task_vector(request: Request, task_id: str) -> Response:
        auth_error = _require_service_password(request)
        if auth_error is not None:
            return auth_error
        try:
            status = tasks_manager.generate_vector(task_id)
        except FileNotFoundError:
            return _json_response(404, {"error": "任务或资料库文件不存在"})
        except ValueError as error:
            return _json_response(409, {"error": str(error)})
        except OSError as error:
            logger.warning("保存向量生成状态失败：%s", type(error).__name__)
            return _json_response(500, {"error": "无法保存向量生成状态"})
        if status == "failed":
            return _json_response(503, {"error": "向量生成失败，请检查嵌入服务配置后重试", "stage_status": status})
        return _json_response(202 if status == "running" else 200, {"stage_status": status})

    @router.post("/api/tasks/{task_id}/regenerate/{action}")
    def regenerate_task(request: Request, task_id: str, action: str) -> Response:
        auth_error = _require_service_password(request)
        if auth_error is not None:
            return auth_error
        try:
            task = tasks_manager.regenerate_task(task_id, action)
        except UnsupportedRegenerationAction:
            return _json_response(404, {"error": "该任务内容不支持重新生成"})
        except FileNotFoundError:
            return _json_response(404, {"error": "任务不存在"})
        except ValueError as error:
            return _json_response(409, {"error": str(error)})
        except (ImportError, OSError, RuntimeError) as error:
            logger.warning("任务内容重新生成失败：%s", type(error).__name__)
            return _json_response(503, {"error": "无法重新生成任务内容，请检查服务端配置"})
        stage = task.stages[action]
        if stage.status != "completed":
            return _json_response(503, {"error": "重新生成失败，请检查任务阶段或服务端日志", "stage_status": stage.status})
        return _json_response(200, {
            "stage_status": stage.status,
            "updated_at": task.updated_at.isoformat(),
        })

    @router.get("/api/tasks/{task_id}/contents")
    @router.get("/api/tasks/{task_id}/contents/{key}")
    def task_contents(request: Request, task_id: str, key: str | None = None) -> Response:
        auth_error = _require_service_password(request)
        if auth_error is not None:
            return auth_error
        if key is not None and key not in _TASK_CONTENTS:
            return _json_response(404, {"error": "找不到该任务内容"})
        try:
            task = tasks_manager.load(task_id)
            if key is not None:
                _, relative, media_type = _TASK_CONTENTS[key]
                path = _task_content_path(tasks_manager, task_id, relative)
                filename = task.source.original_filename if key == "pdf" else None
                if key != "pdf":
                    media_type += "; charset=utf-8"
                return _serve_file(path.parent, path.name, media_type=media_type, filename=filename)

            contents = []
            for content_key, (title, relative, _) in _TASK_CONTENTS.items():
                try:
                    _task_content_path(tasks_manager, task_id, relative)
                except (FileNotFoundError, ValueError):
                    continue
                contents.append({"key": content_key, "title": title})
            return _json_response(200, {"contents": contents})
        except (FileNotFoundError, ValueError):
            return _json_response(404, {"error": "任务不存在或内容尚未生成"})
        except (OSError, RuntimeError) as error:
            logger.warning("读取任务内容失败：%s", type(error).__name__)
            return _json_response(500, {"error": "无法读取任务内容"})

    @router.delete("/api/tasks/{task_id}")
    def delete_task(request: Request, task_id: str) -> Response:
        auth_error = _require_service_password(request)
        if auth_error is not None:
            return auth_error
        try:
            tasks_manager.archive_task(task_id)
        except FileNotFoundError:
            return _json_response(404, {"error": "任务不存在"})
        except ValueError as error:
            return _json_response(409, {"error": str(error)})
        except OSError as error:
            logger.warning("归档任务失败：%s", type(error).__name__)
            return _json_response(500, {"error": "无法归档任务"})
        return _json_response(200, {"task_id": task_id})

    @router.post("/api/tasks/{task_id}/restart")
    def restart_task(request: Request, task_id: str, background_tasks: BackgroundTasks) -> Response:
        auth_error = _require_service_password(request)
        if auth_error is not None:
            return auth_error
        try:
            task = tasks_manager.restart_task(task_id)
        except FileNotFoundError:
            return _json_response(404, {"error": "任务或原始 PDF 不存在"})
        except ValueError as error:
            return _json_response(409, {"error": str(error)})
        except (OSError, ImportError, RuntimeError) as error:
            logger.warning("重启任务失败：%s", type(error).__name__)
            return _json_response(503, {"error": "无法启动任务，请检查服务端配置或文件"})
        background_tasks.add_task(tasks_manager.run_pending, task.task_id)
        return _json_response(202, task.model_dump(
            mode="json", include={"task_id", "status", "current_stage", "updated_at"},
        ))

    @router.post('/api/upload-paper')
    async def upload_paper(request: Request, background_tasks: BackgroundTasks) -> Response:
        auth_error = _require_service_password(request)
        if auth_error is not None:
            return auth_error
        try:
            name = unquote(request.headers.get('x-filename', ''), encoding='utf-8', errors='strict')
        except (UnicodeError, ValueError):
            return _json_response(400, {'error': '文件名无效'})
        if (not name or len(name) > 180 or name in ('.', '..') or
                any(c in name for c in '\\/:*?"<>|') or any(ord(c) < 32 for c in name) or
                not name.lower().endswith('.pdf')):
            return _json_response(400, {'error': '请选择有效的 PDF 文件'})
        temporary = None
        try:
            NEW_PAPERS_DIR.mkdir(parents=True, exist_ok=True)
            size = 0
            prefix = bytearray()
            with tempfile.NamedTemporaryFile(dir=NEW_PAPERS_DIR, prefix='.upload-', delete=False) as output:
                temporary = Path(output.name)
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > UPLOAD_MAX_BYTES:
                        return _json_response(413, {'error': '文件超过大小限制'})
                    if len(prefix) < 1024:
                        prefix.extend(chunk[:1024 - len(prefix)])
                    output.write(chunk)
            if b'%PDF-' not in prefix:
                return _json_response(400, {'error': '文件不是有效的 PDF'})
            saved_name = f'{uuid.uuid4().hex}-{name}'
            saved_path = NEW_PAPERS_DIR / saved_name
            temporary.replace(saved_path)
            temporary = None
        except OSError:
            logger.exception('保存上传文件失败')
            return _json_response(500, {'error': '保存文件失败'})
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

        payload = {"filename": saved_name}
        if request.headers.get("x-process-paper") == "true":
            try:
                task = await run_in_threadpool(tasks_manager.create_task, saved_path, original_filename=name)
            except (ImportError, OSError, ValueError, RuntimeError) as error:
                logger.warning("为上传论文创建任务失败：%s", type(error).__name__)
                return _json_response(503, {
                    **payload, "error": "PDF 已保存，但无法启动论文处理任务",
                })
            payload.update(task_id=task.task_id, status=task.status, current_stage=task.current_stage)
            if task.status == "pending" and task.current_stage == "prepare":
                background_tasks.add_task(tasks_manager.run_pending, task.task_id)
        return _json_response(201, payload)

    @router.post("/api/semantic-search")
    async def search(request: Request) -> Response:
        try:
            query, top_k = await _parse_search_request(request)
        except ValueError as error:
            return _json_response(400, {"error": str(error)})
        try:
            ids = await run_in_threadpool(semantic_search, query, top_k)
        except Exception as error:
            # 不记录请求正文、API 密钥或上游原始响应。
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
    """跟踪 HTTP 请求活动；向量服务的生命周期由 semantic_search 管理。"""
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
    """统计尚未完成响应的请求，文件下载也计入其中。"""
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
    """组装校验、运行状态、生命周期及路由，不启动 Uvicorn。

    启动时始终执行关联校验。validate 仅控制每次请求的校验；
    每次请求仍会重新读取 JSON 源文件。
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
        return service.retrieve_document(query, top_k=top_k)

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
