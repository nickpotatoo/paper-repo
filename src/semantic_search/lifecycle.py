"""Own lazy paper-vector service creation and cleanup without eager dependencies."""

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
        # This lock only guards creation/closure. Store owns operation locking.
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
    """Yield a lazy service handle and close it in a worker thread on exit.

    Each lifespan owns an independent handle. Entering it requires neither
    embedding dependencies nor an API key; the first operation initializes them.
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
