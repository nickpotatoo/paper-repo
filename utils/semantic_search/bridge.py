import os
import json
if __package__:
    from .store import VectorStore
    from .transformer import Transformer
    from .config import PAPER_METHOD_DIR, PAPER_INDEX_PATH
else:
    from store import VectorStore
    from transformer import Transformer
    from config import PAPER_METHOD_DIR, PAPER_INDEX_PATH

class Paper:
    """保存论文基本信息的数据结构"""
    def __init__(self, paper_id: str, title: str, document_type: str, tags: list[str], summary: str, method_document: str):
        self.paper_id = paper_id
        self.title = title
        self.document_type = document_type
        self.tags = tags
        self.summary = summary
        self.method_document = method_document

    def get_metadata(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "document_type": self.document_type,
            "tags": self.tags,
        }

class SSBridge:
    """agent使用论文向量库的接口"""
    def __init__(self, paper_index_path=None, paper_method_dir=None, vectors_path=None):
        paper_method_dir = paper_method_dir or PAPER_METHOD_DIR
        paper_index_path = paper_index_path or PAPER_INDEX_PATH
        if not paper_method_dir:
            raise RuntimeError("PAPER_METHOD_DIR is not set")
        if not paper_index_path:
            raise RuntimeError("PAPER_INDEX_PATH is not set")
        self._store = VectorStore(transformer=Transformer(), vectors_path=vectors_path)
        self._paper_method_dir = os.fspath(paper_method_dir)
        self._paper_index_path = os.fspath(paper_index_path)

    def _load_paper(self, index: str = None) -> list[Paper]:
        with open(self._paper_index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        papers_data = data.get("papers", [])

        if index is not None:
            papers_data = [p for p in papers_data if p.get("paper_id") == index]

        result = []
        for p in papers_data:
            meta = p.get("metadata", {})
            cls = p.get("classification", {})
            result.append(Paper(
                paper_id=p.get("paper_id"),
                title=meta.get("title"),
                document_type=meta.get("document_type"),
                tags=cls.get("tags", []),
                summary=p.get("summary"),
                method_document=p.get("method_document"),
            ))
        return result

    def _build_text(self, paper: Paper) -> str:
        parts = [paper.summary]
        method_doc = paper.method_document
        if method_doc:
            method_path = os.path.join(self._paper_method_dir, os.path.basename(method_doc))
            if os.path.exists(method_path):
                with open(method_path, "r", encoding="utf-8") as f:
                    parts.append(f.read())
        return "\n\n".join(p for p in parts if p)

    def create_vector(self, index: str = None):
        """创建论文对应嵌入向量，若index为None，则无视text，创建所有论文的向量，若index不为None，则创建index对应论文的向量"""
        papers = self._load_paper(index)

        results = []
        for paper in papers:
            content = self._build_text(paper)
            if not content:
                continue
            metadata = paper.get_metadata()
            saved = self._store.save(content, metadata)
            results.append({"paper_id": paper.paper_id, "saved": saved})
        return results
    
    def retrieve(self, query:str, top_k:int = 5) -> list[str]:
        """在论文向量库中根据query进行检索\nquery：检索内容，会被自动处理成向量\ntop_k"""
        retrieve_result = self._store.retrieve(query, top_k)

        result = []
        if retrieve_result:
            result = [r.get("metadata", {}).get("paper_id") for r in retrieve_result if r.get("metadata", {}).get("paper_id")]

        return result
