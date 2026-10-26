"""资料库数据文件模板及 Paper 数据容器。"""


class Paper:
    """向量处理使用的论文数据；文献类型和标签为已解析的名称。"""

    def __init__(
        self, paper_id: str, title: str, document_type: str, tags: list[str],
        summary: str,
    ):
        self.paper_id = paper_id
        self.title = title
        self.document_type = document_type
        self.tags = tags
        self.summary = summary


_papers_template = []
_taxonomy_template = {"category_index": {}, "tag_index": {}, "document_type_index": {}}
_repo_state_template = {"paper_id_counter": 0}
_paper_template = {
    "paper_id": "",
    "metadata": {
        "title": "", "original_filename": "", "filename": "", "sha256": "",
        "document_type": "", "authors": None, "year": None,
    },
    "classification": {"primary_category": "", "tags": []},
    "summary": "",
    "added_at": "",
}
