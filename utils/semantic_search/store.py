import json
import os
import numpy as np
if __package__:
    from .transformer import Transformer
    from .config import VECTORS_PATH, CHUNK_SIZE, CHUNK_OVERLAP, TOP_K
else:
    from transformer import Transformer
    from config import VECTORS_PATH, CHUNK_SIZE, CHUNK_OVERLAP, TOP_K


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
    def __init__(self, transformer: Transformer, vectors_path=None):
        self.transformer = transformer
        self.vectors_path = os.fspath(vectors_path or VECTORS_PATH)

    def _load_metadata_keys(self) -> set[str]:
        if not os.path.exists(self.vectors_path):
            return set()
        keys = set()
        with open(self.vectors_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    record = json.loads(line)
                    keys.add(json.dumps(record["metadata"], sort_keys=True, ensure_ascii=False))
        return keys

    def save(self, text: str, metadata: dict) -> bool:
        meta_key = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
        existing = self._load_metadata_keys()
        if meta_key in existing:
            return False

        chunks = chunk_text(text)
        vectors = self.transformer.embed(chunks)
        os.makedirs(os.path.dirname(os.path.abspath(self.vectors_path)), exist_ok=True)
        with open(self.vectors_path, "a", encoding="utf-8") as f:
            for chunk, vector in zip(chunks, vectors):
                record = {"text": chunk, "vector": vector, "metadata": metadata}
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True

    def retrieve(self, query: str, top_k: int = TOP_K) -> list[dict]:
        if not os.path.exists(self.vectors_path):
            return []

        query_vector = self.transformer.embed_one(query)

        records = []
        with open(self.vectors_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        if not records:
            return []

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
            meta_key = json.dumps(records[idx]["metadata"], sort_keys=True, ensure_ascii=False)
            if meta_key in seen:
                continue
            seen.add(meta_key)
            result = records[idx].copy()
            result["score"] = float(similarities[idx])
            del result["vector"]
            results.append(result)
        return results
