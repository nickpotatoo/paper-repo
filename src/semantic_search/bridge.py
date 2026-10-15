import os
import json

from src.config import DETAILED_SUMMARIES_DIR, PAPERS_PATH, TAXONOMY_PATH
from .store import VectorStore
from .transformer import Transformer

class Paper:
    """保存论文基本信息的数据结构"""
    def __init__(self, paper_id: str, title: str, document_type: str, tags: list[str], summary: str, detailed_summary_document: str):
        self.paper_id = paper_id
        self.title = title
        self.document_type = document_type
        self.tags = tags
        self.summary = summary
        self.detailed_summary_document = detailed_summary_document

    def get_metadata(self) -> dict:
        return {
            "title": self.title,
            "index": self.paper_id,
        }

class SSBridge:
    """agent使用论文向量库的接口"""
    def __init__(self, papers_path=None, detailed_summaries_dir=None, vectors_dir=None, taxonomy_path=None):
        detailed_summaries_dir = detailed_summaries_dir or DETAILED_SUMMARIES_DIR
        papers_path = papers_path or PAPERS_PATH
        if not detailed_summaries_dir:
            raise RuntimeError("DETAILED_SUMMARIES_DIR is not set")
        if not papers_path:
            raise RuntimeError("PAPERS_PATH is not set")
        self._store = VectorStore(transformer=Transformer(), vectors_dir=vectors_dir)
        self._detailed_summaries_dir = os.fspath(detailed_summaries_dir)
        self._papers_path = os.fspath(papers_path)
        self._taxonomy_path = os.fspath(taxonomy_path or TAXONOMY_PATH)

    def _load_paper(self, index: str = None) -> list[Paper]:
        with open(self._papers_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("papers.json 必须为论文数组")
        papers_data = data
        with open(self._taxonomy_path, "r", encoding="utf-8") as f:
            taxonomy = json.load(f)
            document_types = taxonomy["document_type_index"]
            tag_index = taxonomy["tag_index"]

        if index is not None:
            papers_data = [p for p in papers_data if p.get("paper_id") == index]

        result = []
        for p in papers_data:
            meta = p.get("metadata", {})
            cls = p.get("classification", {})
            if meta.get("document_type") not in document_types:
                raise ValueError(f"未知文献类型：{p.get('paper_id')} / {meta.get('document_type')}")
            result.append(Paper(
                paper_id=p.get("paper_id"),
                title=meta.get("title"),
                document_type=document_types[meta["document_type"]],
                tags=[tag_index.get(tag) for tag in cls.get("tags", []) if tag in tag_index],
                summary=p.get("summary"),
                detailed_summary_document=f"detailed_summaries/{p['paper_id']}.md",
            ))
        return result

    def _build_text(self, paper: Paper) -> str:
        detailed_summary_doc = paper.detailed_summary_document
        if not isinstance(paper.summary, str) or not paper.summary.strip():
            raise ValueError(f"论文概述为空或格式错误：{paper.paper_id}")
        if not detailed_summary_doc:
            raise ValueError(f"缺少精细总结文档路径：{paper.paper_id}")
        detailed_summary_path = os.path.join(self._detailed_summaries_dir, os.path.basename(detailed_summary_doc))
        with open(detailed_summary_path, "r", encoding="utf-8") as f:
            detailed_summary_text = f.read()
        if not detailed_summary_text.strip():
            raise ValueError(f"精细总结文档为空：{paper.paper_id}")

        tags = ""
        for t in paper.tags:
            tags += f"{t} "
        return "\n\n".join([paper.summary, detailed_summary_text, f"文献类型：{paper.document_type}", f"标签：{tags.strip()}"])

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
            result = list(dict.fromkeys(
                r["metadata"]["index"] for r in retrieve_result
            ))

        return result
