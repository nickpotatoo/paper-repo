"""Coordinate embedding, direct vector search and storage under one operation lock."""

import logging
import math
import threading
from copy import deepcopy

import numpy as np

from src.config import TOP_K, VECTOR_DTYPE, COSINE_EPSILON
from src.hash_duplicate import hash_text
from .chunking import build_embedding_inputs
from .embed_client import EmbedClient
from .json_storage import JsonStorage

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, vectors_dir=None):
        self._storage = JsonStorage(vectors_dir)
        self._lock = threading.RLock()
        self._closed = False
        # Create the client last, after all other initialization can succeed.
        self._embed_client = EmbedClient()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("VectorStore 已关闭，请创建新的实例")

    def close(self) -> None:
        """Wait for operations and close the owned EmbedClient."""
        with self._lock:
            self._closed = True
            self._embed_client.close()

    @staticmethod
    def _validate_document(document: dict, document_id: str) -> None:
        if (not isinstance(document, dict) or not isinstance(document.get("metadata"), dict)
                or not isinstance(document.get("chunks"), list) or not document["chunks"]):
            raise ValueError(f"向量文档必须包含 metadata 对象和非空 chunks 数组：{document_id}")
        revision = document.get("revision")
        if type(revision) is not int or revision < 1:
            raise ValueError(f"向量文档 revision 必须为正整数：{document_id}")
        dimensions = None
        for number, chunk in enumerate(document["chunks"], 1):
            if (not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str)
                    or not chunk["text"].strip() or not isinstance(chunk.get("vector"), list)
                    or not chunk["vector"]):
                raise ValueError(f"分块必须包含非空 text 和 vector：{document_id} / chunk {number}")
            if type(chunk.get("revision")) is not int or not 1 <= chunk["revision"] <= revision:
                raise ValueError(f"分块 revision 必须为不超过主 revision 的正整数：{document_id} / chunk {number}")
            if chunk.get("text_hash") != hash_text(chunk["text"]):
                raise ValueError(f"分块 text_hash 与文本 SHA-256 不一致：{document_id} / chunk {number}")
            vector = chunk["vector"]
            try:
                valid = all(type(value) in (int, float) and math.isfinite(value) for value in vector)
            except OverflowError:
                valid = False
            if not valid or (dimensions is not None and len(vector) != dimensions):
                raise ValueError(f"分块向量必须为维度一致的有限数值数组：{document_id} / chunk {number}")
            dimensions = len(vector)

    def _read_document(self, document_id: str) -> dict | None:
        try:
            document = self._storage.read_document(document_id)
        except FileNotFoundError:
            return None
        self._validate_document(document, document_id)
        return document

    def save(
        self, text: str, metadata: dict, *, document_id: str, context: str = "",
        remove_stale_chunks: bool = True,
    ) -> bool:
        """Synchronize chunks by text hash, embedding only newly encountered text."""
        if type(remove_stale_chunks) is not bool:
            raise TypeError("remove_stale_chunks 必须为布尔值")
        with self._lock:
            self._ensure_open()
            metadata = deepcopy(metadata)
            existing = self._read_document(document_id)
            inputs = {
                hash_text(chunk): chunk
                for chunk in build_embedding_inputs(text, context=context)
            }
            stored_chunks = {
                chunk["text_hash"]: chunk for chunk in existing["chunks"]
            } if existing is not None else {}
            target_hashes = (
                list(inputs) if remove_stale_chunks
                else list(dict.fromkeys([*stored_chunks, *inputs]))
            )
            if (existing is not None and metadata == existing["metadata"]
                    and target_hashes == [chunk["text_hash"] for chunk in existing["chunks"]]):
                return True
            revision = existing["revision"] + 1 if existing is not None else 1
            missing_hashes = [text_hash for text_hash in inputs if text_hash not in stored_chunks]
            generated_vectors = {}
            if missing_hashes:
                # Generate everything before replacing the file or removing stale chunks.
                new_vectors = self._embed_client.embed([inputs[text_hash] for text_hash in missing_hashes])
                generated_vectors = dict(zip(missing_hashes, new_vectors))
            document = {
                "revision": revision,
                "metadata": metadata,
                "chunks": [
                    stored_chunks[text_hash] if text_hash in stored_chunks else {
                        "text": inputs[text_hash],
                        "text_hash": text_hash,
                        "revision": revision,
                        "vector": generated_vectors[text_hash],
                    }
                    for text_hash in target_hashes
                ],
            }
            self._validate_document(document, document_id)
            try:
                self._storage.write(document_id, document)
            except Exception as error:
                self._storage.delete(document_id)
                logger.warning("向量 JSON 写入失败：%s（%s）", document_id, type(error).__name__)
                return False
        return True

    def _search(self, query: str, top_k: int) -> tuple[list[dict], np.ndarray]:
        """Caller holds _lock; load current JSON files and score their chunks."""
        self._ensure_open()
        if type(top_k) is not int or top_k < 1:
            raise ValueError("top_k 必须为正整数")
        records = []
        vector_rows = []
        for path in self._storage.files():
            document = self._read_document(path.stem)
            if document is None:
                raise FileNotFoundError(f"向量文件在读取期间被删除：{path.name}")
            for chunk in document["chunks"]:
                records.append({
                    "document_id": path.stem, "metadata": document["metadata"], "text": chunk["text"],
                })
                vector_rows.append(chunk["vector"])
        if not records:
            return [], np.empty(0, dtype=VECTOR_DTYPE)
        vectors = np.array(vector_rows, dtype=VECTOR_DTYPE)
        if vectors.ndim != 2 or vectors.shape[1] == 0 or not np.isfinite(vectors).all():
            raise ValueError("向量必须为维度一致的非空有限数值数组")
        vector_norms = np.linalg.norm(vectors, axis=1)
        if not np.isfinite(vector_norms).all():
            raise ValueError("本地向量范数溢出，请检查数值或计算精度")
        query_vec = np.asarray(self._embed_client.embed_one(query), dtype=VECTOR_DTYPE)
        if query_vec.ndim != 1 or query_vec.shape[0] != vectors.shape[1] or not np.isfinite(query_vec).all():
            raise ValueError("查询向量与本地向量维度不一致或包含无效数值")
        query_norm = np.linalg.norm(query_vec)
        if not np.isfinite(query_norm):
            raise ValueError("查询向量范数溢出，请检查数值或计算精度")
        norms = vector_norms * query_norm
        similarities = np.dot(vectors, query_vec) / np.where(norms == 0, COSINE_EPSILON, norms)
        return records, similarities

    def retrieve_document(self, query: str, top_k: int = TOP_K) -> list[dict]:
        """Return document metadata and the highest matching chunk score per document."""
        with self._lock:
            records, similarities = self._search(query, top_k)
            top_indices = np.argsort(similarities)[::-1]
            seen = set()
            results = []
            for idx in top_indices:
                if len(results) >= top_k:
                    break
                record = records[idx]
                if record["document_id"] in seen:
                    continue
                seen.add(record["document_id"])
                results.append({
                    "metadata": deepcopy(record["metadata"]),
                    "score": float(similarities[idx]),
                })
            return results

    def retrieve_chunk(self, query: str, top_k: int = TOP_K) -> list[dict]:
        """Return the highest scoring chunks without merging hits from one document."""
        with self._lock:
            records, similarities = self._search(query, top_k)
            return [
                {
                    "text": records[idx]["text"],
                    "metadata": deepcopy(records[idx]["metadata"]),
                    "score": float(similarities[idx]),
                }
                for idx in np.argsort(similarities)[::-1][:top_k]
            ]
