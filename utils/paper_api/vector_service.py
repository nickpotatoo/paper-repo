"""延迟调用 SSBridge；验证全部文本块，防止部分向量被误认为成功。"""
import json
import math
from .task_store import APIError, file_lock


class VectorService:
    def __init__(self, config):
        self.config = config

    def generate(self, paper):
        # 导入只发生在提交/重试时；创建和修改任务无需向量依赖。
        from utils.semantic_search.bridge import SSBridge
        from utils.semantic_search.store import chunk_text
        path = self.config.vector_path()
        metadata = {"paper_id": paper["paper_id"], "title": paper["metadata"]["title"],
                    "document_type": paper["metadata"]["document_type"], "tags": paper["classification"]["tags"]}
        method = self.config.inside(paper["method_document"]).read_text(encoding="utf-8")
        chunks = chunk_text("\n\n".join(p for p in (paper["summary"], method) if p))
        # 使用向量路径旁的锁，各自定义 root 的调用也会共用锁。
        with file_lock(path.with_suffix(path.suffix + ".lock"), timeout=600):
            bridge = SSBridge(paper_index_path=self.config.index, paper_method_dir=self.config.root / "methods", vectors_path=path)
            result = bridge.create_vector(index=paper["paper_id"])
            if not result or not any(r.get("paper_id") == paper["paper_id"] and type(r.get("saved")) is bool for r in result):
                raise APIError("vector_empty", "SSBridge 未返回有效论文结果")
            records = []
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        record = json.loads(line)
                        if record.get("metadata") == metadata:
                            records.append(record)
            # 检查文本、顺序、维度、数值；saved=False 同样需要通过检查。
            dimensions = {len(r.get("vector", [])) for r in records if isinstance(r.get("vector"), list)}
            valid = (len(records) == len(chunks) and [r.get("text") for r in records] == chunks
                     and len(dimensions) == 1 and 0 not in dimensions)
            for record in records:
                vector = record.get("vector")
                valid = valid and isinstance(vector, list) and all(type(v) in (int, float) and math.isfinite(v) for v in vector) and any(v != 0 for v in vector)
            if not valid:
                raise APIError("vector_incomplete", "现有向量不完整或与正文不同；需要人工修复向量后重试")
            return {"status": "ready", "results": result, "chunk_count": len(chunks)}
