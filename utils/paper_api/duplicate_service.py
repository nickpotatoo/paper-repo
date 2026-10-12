"""哈希与规范化标题查重，复用 utils.hash。"""
import unicodedata
from utils.hash import hash_file
from .task_store import write_json


def normalize_title(title):
    value = unicodedata.normalize("NFKC", title or "").casefold()
    value = "".join(" " if unicodedata.category(c).startswith("P") else c for c in value)
    return " ".join(value.split())


class DuplicateService:
    def __init__(self, config):
        self.config = config

    def build(self, index):
        records = []
        for paper in index["papers"]:
            meta = paper["metadata"]
            # 使用原始文件重建，避免依赖陈旧缓存导致漏检。
            records.append({"paper_id": paper["paper_id"], "title": meta["title"],
                            "normalized_title": normalize_title(meta["title"]),
                            "sha256": hash_file(self.config.inside(meta["relative_path"]))})
        write_json(self.config.data / "duplicate_index.json", records)
        return records

    def candidates(self, task, index):
        title = normalize_title(task.get("draft", {}).get("metadata", {}).get("title"))
        result = []
        for record in self.build(index):
            reasons = []
            if record["sha256"] == task["source"]["sha256"]:
                reasons.append("hash")
            if title and title == record["normalized_title"]:
                reasons.append("title")
            if reasons:
                result.append({**record, "reasons": reasons})
        return result
