"""Paper-specific loading, text construction, metadata and vector operations."""

from pathlib import Path

from src.config import DETAILED_SUMMARIES_DIR, PAPERS_PATH, TAXONOMY_PATH, TOP_K
from src.template import Paper
from src.load_data import load_papers, load_taxonomy
from .store import VectorStore

class PaperVectorService:
    """agent使用论文向量库的接口"""
    def __init__(self, papers_path=None, detailed_summaries_dir=None, vectors_dir=None, taxonomy_path=None):
        self._detailed_summaries_dir = Path(detailed_summaries_dir or DETAILED_SUMMARIES_DIR)
        self._papers_path = Path(papers_path or PAPERS_PATH)
        self._taxonomy_path = Path(taxonomy_path or TAXONOMY_PATH)
        self._store = VectorStore(vectors_dir=vectors_dir)
        self._closed = False

    def close(self) -> None:
        """通过 VectorStore 逐层释放资源；关闭后需要新建实例。"""
        if not self._closed:
            self._store.close()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("PaperVectorService 已关闭，请创建新的实例")

    def __enter__(self) -> "PaperVectorService":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _load_paper(self, index: str = None) -> list[Paper]:
        if index is not None and not isinstance(index, str):
            raise TypeError("index 必须为论文编号字符串或 None")
        papers_data, paper_errors = load_papers(self._papers_path)
        taxonomy, taxonomy_errors = load_taxonomy(self._taxonomy_path)
        if paper_errors or taxonomy_errors:
            raise ValueError("论文资料校验失败：" + "；".join(paper_errors + taxonomy_errors))
        document_types = taxonomy["document_type_index"]
        tag_index = taxonomy["tag_index"]

        if index is not None:
            papers_data = [p for p in papers_data if p["paper_id"] == index]
            if not papers_data:
                raise ValueError(f"论文编号不存在：{index}")

        result = []
        for p in papers_data:
            meta = p["metadata"]
            cls = p["classification"]
            if meta["document_type"] not in document_types:
                raise ValueError(f"未知文献类型：{p['paper_id']} / {meta['document_type']}")
            if cls["primary_category"] not in taxonomy["category_index"]:
                raise ValueError(f"未知主分类：{p['paper_id']} / {cls['primary_category']}")
            unknown_tags = [tag for tag in cls["tags"] if tag not in tag_index]
            if unknown_tags:
                raise ValueError(f"未知标签：{p['paper_id']} / {', '.join(unknown_tags)}")
            result.append(Paper(
                paper_id=p["paper_id"],
                title=meta["title"],
                document_type=document_types[meta["document_type"]],
                tags=[tag_index[tag] for tag in cls["tags"]],
                summary=p["summary"],
            ))
        return result

    def _build_text(self, paper: Paper) -> str:
        """Paper fields have already passed _load_paper validation."""
        detailed_summary_path = self._detailed_summaries_dir / f"{paper.paper_id}.md"
        detailed_summary_text = detailed_summary_path.read_text(encoding="utf-8")
        if not detailed_summary_text.strip():
            raise ValueError(f"精细总结文档为空：{paper.paper_id}")

        return "\n\n".join([paper.summary, detailed_summary_text])

    def _build_context(self, paper: Paper) -> str:
        """由业务层解释论文信息；store 仅将该文本附加到每个分块前。"""
        return "\n".join([
            f"论文：{paper.title}",
            f"文献类型：{paper.document_type}",
            f"标签：{' '.join(paper.tags)}",
        ])

    @staticmethod
    def _build_metadata(paper: Paper) -> dict:
        """The vector-specific metadata contract belongs to this service."""
        return {"title": paper.title, "index": paper.paper_id}

    def create_vector(self, index: str = None):
        """index 为稳定论文编号；None 表示为所有论文创建向量。"""
        self._ensure_open()
        papers = self._load_paper(index)

        results = []
        for paper in papers:
            content = self._build_text(paper)
            metadata = self._build_metadata(paper)
            saved = self._store.save(content, metadata, context=self._build_context(paper))
            results.append({"paper_id": paper.paper_id, "saved": saved})
        return results
    
    def retrieve(self, query:str, top_k:int = TOP_K) -> list[str]:
        """在论文向量库中根据query进行检索\nquery：检索内容，会被自动处理成向量\ntop_k"""
        self._ensure_open()
        return list(dict.fromkeys(
            result["metadata"]["index"] for result in self._store.retrieve(query, top_k)
        ))
