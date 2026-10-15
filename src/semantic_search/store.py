import json
import os
import re
import threading
from pathlib import Path
import numpy as np

from src.config import VECTOR_DATA_DIR, VECTOR_MAX_ROWS, CHUNK_SIZE, CHUNK_OVERLAP, TOP_K
from .transformer import Transformer


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


class VectorStore:
    def __init__(self, transformer: Transformer, vectors_dir=None):
        self.transformer = transformer
        self.vectors_dir = os.fspath(vectors_dir or VECTOR_DATA_DIR)
        if type(VECTOR_MAX_ROWS) is not int or VECTOR_MAX_ROWS <= 0:
            raise ValueError("VECTOR_MAX_ROWS 必须为正整数")
        self.max_rows = VECTOR_MAX_ROWS
        self._write_lock = threading.Lock()

    def _vector_files(self) -> list[tuple[int, Path]]:
        """按编号列出 vectors_1.jsonl 起的分片，不读取其他文件。"""
        base = Path(self.vectors_dir)
        pattern = re.compile(r"vectors_([1-9][0-9]*)\.jsonl")
        if not base.exists():
            return []
        files = []
        for path in base.iterdir():
            match = pattern.fullmatch(path.name)
            if match and path.is_file():
                files.append((int(match.group(1)), path))
        return sorted(files, key=lambda item: item[0])

    def _read_records(self):
        for _, path in self._vector_files():
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)

    def _load_metadata_keys(self) -> set[str]:
        """逐行读取已有记录，返回用于去重的 metadata 键集合。"""
        return {
            json.dumps(record["metadata"], sort_keys=True, ensure_ascii=False)
            for record in self._read_records()
        }

    def _append_vectors(self, vectors: list[list[float]], metadata: dict) -> None:
        base = Path(self.vectors_dir)
        base.mkdir(parents=True, exist_ok=True)
        files = self._vector_files()
        file_index, path = files[-1] if files else (1, base / "vectors_1.jsonl")
        rows = 0
        if path.exists():
            with path.open("rb") as source:
                rows = sum(1 for _ in source)
        offset = 0
        while offset < len(vectors):
            if rows >= self.max_rows:
                file_index += 1
                path = base / f"vectors_{file_index}.jsonl"
                rows = 0
            batch = vectors[offset:offset + self.max_rows - rows]
            # 已有末行没有换行符时，先补齐，避免两条 JSON 粘在同一行。
            needs_newline = False
            if rows:
                with path.open("rb") as source:
                    source.seek(-1, os.SEEK_END)
                    needs_newline = source.read(1) != b"\n"
            with path.open("a", encoding="utf-8", newline="\n") as target:
                if needs_newline:
                    target.write("\n")
                for vector in batch:
                    record = {"vector": vector, "metadata": metadata}
                    target.write(json.dumps(record, ensure_ascii=False) + "\n")
            offset += len(batch)
            rows += len(batch)

    def save(self, text: str, metadata: dict) -> bool:
        """文本仅用于嵌入；保存 vector 和调用方传入的原始 metadata。"""
        with self._write_lock:
            meta_key = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
            if meta_key in self._load_metadata_keys():
                return False
            chunks = chunk_text(text)
            vectors = self.transformer.embed(chunks)
            if len(vectors) != len(chunks):
                raise ValueError("嵌入返回数量与文本分块数量不一致，未写入向量")
            self._append_vectors(vectors, metadata)
        return True

    def retrieve(self, query: str, top_k: int = TOP_K) -> list[dict]:
        records = list(self._read_records())
        if not records:
            return []
        query_vector = self.transformer.embed_one(query)

        vectors = np.array([r["vector"] for r in records])
        query_vec = np.array(query_vector)

        norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query_vec)
        similarities = np.dot(vectors, query_vec) / np.where(norms == 0, 1e-10, norms)

        top_indices = np.argsort(similarities)[::-1]

        seen = set()
        results = []
        for idx in top_indices:
            if len(results) >= top_k:
                break
            metadata = records[idx]["metadata"]
            meta_key = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
            if meta_key in seen:
                continue
            seen.add(meta_key)
            results.append({"metadata": metadata, "score": float(similarities[idx])})
        return results
