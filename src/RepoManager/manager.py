"""管理正式论文记录及分类索引。"""

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from src.config import (
    DETAILED_SUMMARIES_DIR, PAPERS_PATH, PDFS_DIR, REPO_STATE_PATH,
    TAXONOMY_PATH, VECTOR_DATA_DIR,
)
from .reader import load_papers, load_state, load_taxonomy

_WRITE_LOCK = threading.RLock()
_KINDS = {"category": ("category_index", "C"), "tag": ("tag_index", "T"),
          "document_type": ("document_type_index", "D")}


def _write_json(path: Path, data) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _checked(reader, path):
    data, errors = reader(path)
    if errors:
        raise ValueError("；".join(errors))
    return data


def _inside(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"路径超出资料目录：{relative}")
    return path


class RepoManager:
    def __init__(
        self, *, papers_path=PAPERS_PATH, taxonomy_path=TAXONOMY_PATH,
        state_path=REPO_STATE_PATH, pdfs_dir=PDFS_DIR,
        summaries_dir=DETAILED_SUMMARIES_DIR, vectors_dir=VECTOR_DATA_DIR,
    ):
        self.papers_path = Path(papers_path)
        self.taxonomy_path = Path(taxonomy_path)
        self.state_path = Path(state_path)
        self.pdfs_dir = Path(pdfs_dir)
        self.summaries_dir = Path(summaries_dir)
        self.vectors_dir = Path(vectors_dir)

    def get_paper(self, paper_id: str) -> dict:
        papers = _checked(load_papers, self.papers_path)
        return self._find_paper(papers, paper_id)

    @staticmethod
    def _find_paper(papers, paper_id):
        for paper in papers:
            if paper["paper_id"] == paper_id:
                return paper
        raise KeyError(paper_id)

    def get_taxonomy(self) -> dict:
        return _checked(load_taxonomy, self.taxonomy_path)

    def delete_paper(self, paper_id: str) -> Path:
        """从正式库删除论文，返回保留记录及附件的归档目录。"""
        with _WRITE_LOCK:
            papers = _checked(load_papers, self.papers_path)
            paper = self._find_paper(papers, paper_id)
            category = paper["classification"]["primary_category"]
            if category not in self.get_taxonomy()["category_index"]:
                raise ValueError("论文引用了未定义的主分类")
            filename = paper["metadata"]["filename"]
            if any(p is not paper and p["classification"]["primary_category"] == category
                   and os.path.normcase(p["metadata"]["filename"]) == os.path.normcase(filename)
                   for p in papers):
                raise ValueError("PDF 被其他论文记录引用")
            files = {
                "pdf": _inside(self.pdfs_dir, f"{category}/{filename}"),
                "summary": _inside(self.summaries_dir, f"{paper_id}.md"),
                "vector": _inside(self.vectors_dir, f"{paper_id}.json"),
            }
            archive_root = self.papers_path.parent / ".deleted_papers"
            archive_root.mkdir(exist_ok=True)
            archive = Path(tempfile.mkdtemp(prefix=f"{paper_id}-", dir=archive_root))
            _write_json(archive / "paper.json", paper)
            copies = {}
            for kind, source in files.items():
                if source.is_symlink():
                    raise ValueError(f"附件不能是符号链接：{source.name}")
                if source.exists():
                    backup = archive / f"{kind}{source.suffix}"
                    shutil.copy2(source, backup)
                    copies[source] = backup
            removed = []
            try:
                for source in copies:
                    source.unlink()
                    removed.append(source)
                _write_json(self.papers_path, [p for p in papers if p is not paper])
            except Exception:
                for source in removed:
                    shutil.copy2(copies[source], source)
                raise
            return archive

    def add_taxonomy_entry(self, kind: str, name: str, *, description: str | None = None) -> str:
        """添加分类、标签或文献类型，返回新编号。"""
        index, prefix = _KINDS[kind]
        with _WRITE_LOCK:
            taxonomy = self.get_taxonomy()
            entries = taxonomy[index]
            value = self._entry(kind, name, description)
            self._check_name(entries, name)
            state = _checked(load_state, self.state_path)
            counters = state.setdefault("taxonomy_id_counters", {})
            previous = counters.get(prefix, 0)
            if type(previous) is not int or previous < 0:
                raise ValueError(f"无效 taxonomy 计数器：{prefix}")
            number = max(previous, max((int(key[1:]) for key in entries), default=0)) + 1
            entry_id = f"{prefix}{number:03d}"
            if kind == "category":
                _inside(self.pdfs_dir, entry_id).mkdir(parents=True, exist_ok=True)
            counters[prefix] = number
            _write_json(self.state_path, state)
            entries[entry_id] = value
            _write_json(self.taxonomy_path, taxonomy)
            return entry_id

    def update_taxonomy_entry(
        self, kind: str, entry_id: str, name: str, *, description: str | None = None,
    ) -> None:
        index, _ = _KINDS[kind]
        with _WRITE_LOCK:
            taxonomy = self.get_taxonomy()
            entries = taxonomy[index]
            old = entries[entry_id]
            if kind == "category" and description is None:
                description = old["description"]
            value = self._entry(kind, name, description)
            self._check_name(entries, name, exclude=entry_id)
            entries[entry_id] = value
            _write_json(self.taxonomy_path, taxonomy)

    def delete_taxonomy_entry(self, kind: str, entry_id: str) -> None:
        """删除未被论文引用的定义，保留已分配编号。"""
        index, prefix = _KINDS[kind]
        with _WRITE_LOCK:
            taxonomy = self.get_taxonomy()
            entries = taxonomy[index]
            if entry_id not in entries:
                raise KeyError(entry_id)
            for paper in _checked(load_papers, self.papers_path):
                classification = paper["classification"]
                references = {
                    "category": [classification["primary_category"]],
                    "tag": classification["tags"],
                    "document_type": [paper["metadata"]["document_type"]],
                }
                if entry_id in references[kind]:
                    raise ValueError(f"{entry_id} 仍被论文 {paper['paper_id']} 引用")
            state = _checked(load_state, self.state_path)
            counters = state.setdefault("taxonomy_id_counters", {})
            previous = counters.get(prefix, 0)
            if type(previous) is not int or previous < 0:
                raise ValueError(f"无效 taxonomy 计数器：{prefix}")
            counters[prefix] = max(previous, max(int(key[1:]) for key in entries))
            _write_json(self.state_path, state)
            del entries[entry_id]
            _write_json(self.taxonomy_path, taxonomy)

    @staticmethod
    def _entry(kind, name, description):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("名称不能为空")
        if kind == "category":
            if not isinstance(description, str) or not description.strip():
                raise ValueError("分类描述不能为空")
            return {"name": name.strip(), "description": description.strip()}
        if description is not None:
            raise ValueError("描述仅适用于分类")
        return name.strip()

    @staticmethod
    def _check_name(entries, name, *, exclude=None):
        normalized = " ".join(name.split()).casefold()
        for key, value in entries.items():
            existing = value["name"] if isinstance(value, dict) else value
            if key != exclude and " ".join(existing.split()).casefold() == normalized:
                raise ValueError(f"名称已存在：{existing}")
