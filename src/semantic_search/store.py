"""Coordinate embedding, cached vector search and storage under one operation lock."""

import json
import threading
from copy import deepcopy
from dataclasses import dataclass

import numpy as np

from src.config import TOP_K, VECTOR_DTYPE, COSINE_EPSILON
from .chunking import build_embedding_inputs
from .embed_client import EmbedClient
from .jsonl_storage import JsonlStorage, FileSignature, ShardFiles


def _metadata_key(metadata: dict) -> str:
    return json.dumps(metadata, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class _SearchSnapshot:
    signature: FileSignature
    vectors: np.ndarray
    norms: np.ndarray
    metadata: tuple[dict, ...]
    metadata_keys: tuple[str, ...]


class VectorStore:
    def __init__(self, vectors_dir=None):
        self._storage = JsonlStorage(vectors_dir)
        self._lock = threading.RLock()
        self._closed = False
        self._metadata_keys: set[str] | None = None
        self._metadata_signature: FileSignature | None = None
        self._search_snapshot: _SearchSnapshot | None = None
        # Create the client last, after all other initialization can succeed.
        self._embed_client = EmbedClient()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("VectorStore 已关闭，请创建新的实例")

    def close(self) -> None:
        """Wait for operations, clear caches and close the owned EmbedClient."""
        with self._lock:
            self._closed = True
            self._invalidate_caches()
            self._embed_client.close()

    # Private cache helpers run under the public save/retrieve/close operation lock.
    def _invalidate_caches(self) -> None:
        self._metadata_keys = None
        self._metadata_signature = None
        self._search_snapshot = None

    def _storage_state(self) -> tuple[ShardFiles, FileSignature]:
        """Use one policy to invalidate both caches when files change."""
        try:
            files = self._storage.files()
            signature = self._storage.signature(files)
        except Exception:
            self._invalidate_caches()
            raise
        if self._metadata_signature is not None and self._metadata_signature != signature:
            self._metadata_keys = None
            self._metadata_signature = None
        if self._search_snapshot is not None and self._search_snapshot.signature != signature:
            self._search_snapshot = None
        return files, signature

    def _read_consistent_records(self, files: ShardFiles, signature: FileSignature):
        """Caller holds _lock; parsing and signature failures invalidate once."""
        try:
            yield from self._storage.read_records(files)
            if self._storage.signature() != signature:
                raise RuntimeError("向量文件在读取期间发生变化，请重试")
        except Exception:
            self._invalidate_caches()
            raise

    def _load_metadata_keys(self) -> set[str]:
        """Caller holds _lock; keep metadata loading separate from matrix loading."""
        files, signature = self._storage_state()
        if self._metadata_keys is None:
            self._metadata_keys = {
                _metadata_key(record["metadata"])
                for record in self._read_consistent_records(files, signature)
            }
            self._metadata_signature = signature
        return self._metadata_keys

    def _get_search_snapshot(self) -> _SearchSnapshot:
        """Caller holds _lock; build or reuse a complete read-only snapshot."""
        files, signature = self._storage_state()
        if self._search_snapshot is not None:
            return self._search_snapshot
        records = list(self._read_consistent_records(files, signature))
        vectors = (
            np.array([record["vector"] for record in records], dtype=VECTOR_DTYPE)
            if records else np.empty((0, 0), dtype=VECTOR_DTYPE)
        )
        if vectors.ndim != 2 or (records and vectors.shape[1] == 0) or not np.isfinite(vectors).all():
            raise ValueError("向量必须为维度一致的非空有限数值数组")
        norms = np.linalg.norm(vectors, axis=1)
        if not np.isfinite(norms).all():
            raise ValueError("本地向量范数溢出，请检查数值或计算精度")
        vectors.setflags(write=False)
        norms.setflags(write=False)
        metadata = tuple(record["metadata"] for record in records)
        keys = tuple(_metadata_key(item) for item in metadata)
        snapshot = _SearchSnapshot(signature, vectors, norms, metadata, keys)
        self._metadata_keys = set(keys)
        self._metadata_signature = signature
        self._search_snapshot = snapshot
        return snapshot

    def save(self, text: str, metadata: dict, *, context: str = "") -> bool:
        """Store only vectors and caller-supplied metadata, never embedding text."""
        if not isinstance(context, str):
            raise TypeError("context 必须为字符串")
        with self._lock:
            self._ensure_open()
            metadata = deepcopy(metadata)
            meta_key = _metadata_key(metadata)
            if meta_key in self._load_metadata_keys():
                return False
            inputs = build_embedding_inputs(text, context=context)
            # EmbedClient validates the response before any disk write.
            vectors = self._embed_client.embed(inputs)
            if self._storage.signature() != self._metadata_signature:
                if meta_key in self._load_metadata_keys():
                    return False
            # Cache maintenance is not a transaction or crash recovery mechanism.
            try:
                self._storage.append(vectors, metadata)
                signature = self._storage.signature()
            except Exception:
                self._invalidate_caches()
                raise
            self._metadata_keys.add(meta_key)
            self._metadata_signature = signature
            self._search_snapshot = None
        return True

    def retrieve(self, query: str, top_k: int = TOP_K) -> list[dict]:
        with self._lock:
            self._ensure_open()
            return self._retrieve(query, top_k)

    def _retrieve(self, query: str, top_k: int) -> list[dict]:
        snapshot = self._get_search_snapshot()
        if not snapshot.metadata:
            return []
        query_vec = np.asarray(self._embed_client.embed_one(query), dtype=VECTOR_DTYPE)
        if query_vec.ndim != 1 or query_vec.shape[0] != snapshot.vectors.shape[1] or not np.isfinite(query_vec).all():
            raise ValueError("查询向量与本地向量维度不一致或包含无效数值")
        query_norm = np.linalg.norm(query_vec)
        if not np.isfinite(query_norm):
            raise ValueError("查询向量范数溢出，请检查数值或计算精度")
        norms = snapshot.norms * query_norm
        similarities = np.dot(snapshot.vectors, query_vec) / np.where(norms == 0, COSINE_EPSILON, norms)
        top_indices = np.argsort(similarities)[::-1]
        seen = set()
        results = []
        for idx in top_indices:
            if len(results) >= top_k:
                break
            meta_key = snapshot.metadata_keys[idx]
            if meta_key in seen:
                continue
            seen.add(meta_key)
            results.append({"metadata": deepcopy(snapshot.metadata[idx]), "score": float(similarities[idx])})
        return results
