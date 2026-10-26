"""管理论文向量服务的延迟创建与清理，不提前加载依赖。"""

import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from src.config import TOP_K

if TYPE_CHECKING:
    from .paper_vector_service import PaperVectorService


class _LazyPaperVectorService:
    def __init__(self, options: dict) -> None:
        self._options = options
        self._service = None
        self._lifecycle_lock = threading.Lock()
        self._closed = False

    def _get_service(self) -> "PaperVectorService":
        # 此锁仅保护创建和关闭；具体操作的加锁由存储层负责。
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("论文向量服务已关闭")
            if self._service is None:
                from .paper_vector_service import PaperVectorService
                self._service = PaperVectorService(**self._options)
            return self._service

    def retrieve_document(self, query: str, top_k: int = TOP_K) -> list[str]:
        return self._get_service().retrieve_document(query, top_k=top_k)

    def retrieve_chunk(self, query: str, top_k: int = TOP_K) -> list[dict]:
        return self._get_service().retrieve_chunk(query, top_k=top_k)

    def create_vector(self, index: str | None = None):
        return self._get_service().create_vector(index=index)

    def close(self) -> None:
        with self._lifecycle_lock:
            self._closed = True
            if self._service is not None:
                self._service.close()
                self._service = None


@asynccontextmanager
async def paper_vector_service_lifespan(
    *,
    papers_path: Path | None = None,
    taxonomy_path: Path | None = None,
    detailed_summaries_dir: Path | None = None,
    vectors_dir: Path | None = None,
):
    """提供延迟初始化的服务句柄，并在退出时通过工作线程关闭。

    每个生命周期持有独立句柄。进入时不要求嵌入服务依赖或 API 密钥；
    首次操作时才执行服务初始化。
    """
    service = _LazyPaperVectorService({
        "papers_path": papers_path,
        "taxonomy_path": taxonomy_path,
        "detailed_summaries_dir": detailed_summaries_dir,
        "vectors_dir": vectors_dir,
    })
    try:
        yield service
    finally:
        await asyncio.to_thread(service.close)
