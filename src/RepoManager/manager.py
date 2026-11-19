"""管理正式论文记录及分类索引。"""

import json
import os
import re
import shutil
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import (
    DETAILED_SUMMARIES_DIR, PAPERS_PATH, PDFS_DIR, REPO_STATE_PATH,
    TAXONOMY_PATH, VECTOR_DATA_DIR,
)
from src.hash_duplicate import hash_file
from .reader import _validate_papers, load_papers, load_state, load_taxonomy
from .taxonomy import normalized_name, validate_classification

_WRITE_LOCK = threading.RLock()
_KINDS = {"category": ("category_index", "C"), "tag": ("tag_index", "T"),
          "document_type": ("document_type_index", "D")}
_PDF_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.pdf")
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                     *(f"lpt{i}" for i in range(1, 10))}


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

    validate_classification = staticmethod(validate_classification)

    def ingest_paper(
        self, source: Path, *, sha256: str, original_filename: str, metadata: dict,
        classification: dict, summary: str, detailed_summary: str,
    ) -> str:
        """将已确认的任务草稿入库。同一 PDF 重复提交时返回已有编号。"""
        source = Path(source)
        with _WRITE_LOCK:
            with source.open("rb") as stream:
                if b"%PDF-" not in stream.read(1024):
                    raise ValueError("任务原件不是 PDF")
            if hash_file(source) != sha256:
                raise ValueError("任务原件的哈希与任务记录不符")
            papers = _checked(load_papers, self.papers_path)
            for existing in papers:
                if existing["metadata"]["sha256"] == sha256:
                    return existing["paper_id"]

            if not isinstance(metadata, dict) or not isinstance(classification, dict):
                raise ValueError("元数据和分类必须是对象")
            if not isinstance(detailed_summary, str) or not detailed_summary.strip():
                raise ValueError("精细总结不能为空")
            filename = metadata.get("filename")
            if (not isinstance(filename, str) or len(filename) > 180
                    or not _PDF_NAME.fullmatch(filename) or filename[:-4] in _WINDOWS_RESERVED):
                raise ValueError("PDF 文件名须为英文小写短横线名称，长度不超过 180 字符")
            if any(field not in metadata for field in ("authors", "year")):
                raise ValueError("元数据必须包含作者和年份，未知时使用 null")

            taxonomy = self.get_taxonomy()
            old_taxonomy = deepcopy(taxonomy)
            state = _checked(load_state, self.state_path)
            category, tags, document_type = self._resolve_classification(classification, taxonomy, state)
            number = max(
                state["paper_id_counter"],
                max((int(paper["paper_id"][1:]) for paper in papers), default=0),
            ) + 1
            paper_id = f"P{number:06d}"
            record = {
                "paper_id": paper_id,
                "added_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
                "metadata": {
                    "title": metadata.get("title"), "original_filename": original_filename,
                    "filename": filename, "sha256": sha256, "document_type": document_type,
                    "authors": metadata["authors"], "year": metadata["year"],
                },
                "classification": {"primary_category": category, "tags": tags},
                "summary": summary,
            }
            errors = _validate_papers([record])
            if errors:
                raise ValueError("；".join(errors))
            if any(
                paper["classification"]["primary_category"] == category
                and os.path.normcase(paper["metadata"]["filename"]) == os.path.normcase(filename)
                for paper in papers
            ):
                raise FileExistsError("同一分类下已有同名论文")
            pdf_path = _inside(self.pdfs_dir, f"{category}/{filename}")
            summary_path = _inside(self.summaries_dir, f"{paper_id}.md")
            if any(path.exists() or path.is_symlink() for path in (pdf_path, summary_path)):
                raise FileExistsError("目标 PDF 或精细总结已存在")

            state["paper_id_counter"] = number
            _write_json(self.state_path, state)
            published = []
            taxonomy_saved = False
            try:
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                summary_path.parent.mkdir(parents=True, exist_ok=True)
                with source.open("rb") as original, pdf_path.open("xb") as output:
                    published.append(pdf_path)
                    shutil.copyfileobj(original, output)
                if hash_file(pdf_path) != sha256:
                    raise ValueError("复制的 PDF 与任务原件哈希不符")
                with summary_path.open("x", encoding="utf-8", newline="\n") as output:
                    published.append(summary_path)
                    output.write(detailed_summary)
                if taxonomy != old_taxonomy:
                    _write_json(self.taxonomy_path, taxonomy)
                    taxonomy_saved = True
                _write_json(self.papers_path, [*papers, record])
            except Exception:
                for path in reversed(published):
                    path.unlink()
                if taxonomy_saved:
                    _write_json(self.taxonomy_path, old_taxonomy)
                raise
            return paper_id

    def _resolve_classification(self, draft: dict, taxonomy: dict, state: dict):
        issues = self.validate_classification(draft, taxonomy, for_ingest=True)
        if issues:
            raise ValueError("；".join(issue["message"] for issue in issues))

        def resolve_one(field, kind, proposed):
            if draft[field] is None:
                return self._resolve_candidate(kind, draft[proposed][0], taxonomy, state)
            return draft[field]

        category = resolve_one("primary_category", "category", "proposed_categories")
        document_type = resolve_one("document_type", "document_type", "proposed_document_types")
        proposed_tags = [
            self._resolve_candidate("tag", item, taxonomy, state)
            for item in draft.get("proposed_tags", [])
        ]
        return category, list(dict.fromkeys([*draft["tags"], *proposed_tags])), document_type

    def _resolve_candidate(self, kind, item, taxonomy, state):
        index, prefix = _KINDS[kind]
        entries = taxonomy[index]
        value = self._entry(kind, item.get("name"), item.get("description"))
        name = value["name"] if kind == "category" else value
        normalized = normalized_name(name)
        for entry_id, existing in entries.items():
            existing_name = existing["name"] if kind == "category" else existing
            if normalized_name(existing_name) == normalized:
                return entry_id
        entry_id = self._reserve_taxonomy_id(entries, prefix, state)
        entries[entry_id] = value
        return entry_id

    @staticmethod
    def _reserve_taxonomy_id(entries, prefix, state):
        counters = state.setdefault("taxonomy_id_counters", {})
        number = max(counters.get(prefix, 0), max((int(key[1:]) for key in entries), default=0)) + 1
        counters[prefix] = number
        return f"{prefix}{number:03d}"

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
            entry_id = self._reserve_taxonomy_id(entries, prefix, state)
            if kind == "category":
                _inside(self.pdfs_dir, entry_id).mkdir(parents=True, exist_ok=True)
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
        normalized = normalized_name(name)
        for key, value in entries.items():
            existing = value["name"] if isinstance(value, dict) else value
            if key != exclude and normalized_name(existing) == normalized:
                raise ValueError(f"名称已存在：{existing}")
