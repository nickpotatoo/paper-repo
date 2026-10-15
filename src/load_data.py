"""读取 repo 数据；致命错误抛异常，其余校验结果返回为描述列表。

致命错误：读取/解析失败、不可处理的结构、编号无效或重复、
无效计数器及不安全路径。内容、引用及附件缺失等问题收集后继续校验。
validate=False 跳过校验；不缓存、不写入、不生成聚合索引。
"""

import json
import re
from datetime import datetime, timedelta
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Any

from src.config import PAPERS_PATH, TAXONOMY_PATH, REPO_STATE_PATH, PDFS_DIR, DETAILED_SUMMARIES_DIR

__all__ = ["load_papers", "load_taxonomy", "load_state", "validate_data", "load_data"]
JsonPath = str | PathLike[str]


def _read_json(path: JsonPath) -> Any:
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def _relative_path(value: Any, label: str) -> PurePosixPath:
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ValueError(f"{label} 必须为使用 / 分隔的安全相对路径")
    return PurePosixPath(value)


def _validate_papers(papers: Any) -> list[str]:
    if not isinstance(papers, list):
        raise ValueError("papers.json 必须为论文数组")
    errors = []
    used = set()
    for paper in papers:
        if not isinstance(paper, dict):
            raise ValueError("论文记录必须为对象")
        pid = paper.get("paper_id")
        if (not isinstance(pid, str) or not re.fullmatch(r"P[0-9]{6,}", pid)
                or int(pid[1:]) < 1 or pid != f"P{int(pid[1:]):06d}"):
            raise ValueError(f"无效论文编号：{pid}")
        if pid in used:
            raise ValueError(f"重复论文编号：{pid}")
        used.add(pid)
        added_at = paper.get("added_at")
        try:
            if not isinstance(added_at, str) or not re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?\+08:00", added_at
            ):
                raise ValueError
            if datetime.fromisoformat(added_at).utcoffset() != timedelta(hours=8):
                raise ValueError
        except ValueError:
            errors.append(f"added_at 必须为有效的北京时间 ISO 8601（+08:00）：{pid}")
        if not isinstance(paper.get("summary"), str) or not paper["summary"].strip():
            errors.append(f"summary 必须为非空字符串：{pid}")
        meta = paper.get("metadata")
        if not isinstance(meta, dict):
            raise ValueError(f"metadata 必须为对象：{pid}")
        if not isinstance(meta.get("title"), str) or not meta["title"].strip():
            errors.append(f"论文标题不能为空：{pid}")
        for key in ("original_filename",):
            if not isinstance(meta.get(key), str) or not meta[key].strip():
                errors.append(f"metadata.{key} 必须为非空字符串：{pid}")
        if not isinstance(meta.get("document_type"), str) or not re.fullmatch(r"D[0-9]{3,}", meta["document_type"]):
            errors.append(f"document_type 必须为文献类型 ID：{pid}")
        if "authors" not in meta or (meta["authors"] is not None and
                (not isinstance(meta["authors"], str) or not meta["authors"].strip())):
            errors.append(f"authors 必须为非空字符串或 null：{pid}")
        if "year" not in meta or (meta["year"] is not None and
                (type(meta["year"]) is not int or not 1 <= meta["year"] <= 9999)):
            errors.append(f"year 必须为 1 至 9999 的整数或 null：{pid}")
        filename = _relative_path(meta.get("filename"), f"PDF 文件名（{pid}）")
        if len(filename.parts) != 1:
            raise ValueError(f"filename 只能保存文件名，不能包含目录：{pid}")
        if filename.suffix.lower() != ".pdf":
            errors.append(f"filename 必须为 PDF 文件名：{pid}")
        if not isinstance(meta.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", meta["sha256"]):
            errors.append(f"SHA-256 必须为 64 位小写十六进制：{pid}")
        classification = paper.get("classification")
        if not isinstance(classification, dict):
            raise ValueError(f"classification 必须为对象：{pid}")
        if not isinstance(classification.get("primary_category"), str):
            errors.append(f"classification 必须包含主分类 ID：{pid}")
        tags = classification.get("tags")
        if not isinstance(tags, list):
            raise ValueError(f"tags 必须为数组：{pid}")
        if any(not isinstance(tag, str) for tag in tags):
            errors.append(f"tags 中的每项必须为标签 ID 字符串：{pid}")
        string_tags = [tag for tag in tags if isinstance(tag, str)]
        if len(string_tags) != len(set(string_tags)):
            errors.append(f"论文内标签重复：{pid}")
    return errors


def _validate_taxonomy(taxonomy: Any) -> list[str]:
    if not isinstance(taxonomy, dict):
        raise ValueError("taxonomy.json 必须为对象")
    categories, tags = taxonomy.get("category_index"), taxonomy.get("tag_index")
    document_types = taxonomy.get("document_type_index")
    if not all(isinstance(value, dict) for value in (categories, tags, document_types)):
        raise ValueError("taxonomy.json 必须包含分类、标签与文献类型字典")
    errors = []
    for did, name in document_types.items():
        if not isinstance(did, str) or not re.fullmatch(r"D[0-9]{3,}", did) or int(did[1:]) < 1:
            raise ValueError(f"无效文献类型编号：{did}")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"文献类型名称不能为空：{did}")
    for cid, category in categories.items():
        if not isinstance(cid, str) or not re.fullmatch(r"C[0-9]{3,}", cid) or int(cid[1:]) < 1:
            raise ValueError(f"无效分类编号：{cid}")
        if not isinstance(category, dict):
            raise ValueError(f"分类定义必须为对象：{cid}")
        for key in ("name", "description"):
            if not isinstance(category.get(key), str) or not category[key].strip():
                errors.append(f"分类 {key} 不能为空：{cid}")
    for tid, name in tags.items():
        if not isinstance(tid, str) or not re.fullmatch(r"T[0-9]{3,}", tid) or int(tid[1:]) < 1:
            raise ValueError(f"无效标签编号：{tid}")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"标签名称不能为空：{tid}")
    return errors


def _validate_state(state: Any) -> list[str]:
    if not isinstance(state, dict):
        raise ValueError("repo_state.json 必须为对象")
    if type(state.get("paper_id_counter")) is not int or state["paper_id_counter"] < 0:
        raise ValueError("paper_id_counter 必须为非负整数")
    return []


def load_papers(path: JsonPath | None = None, *, validate: bool = True) -> tuple[list[dict[str, Any]], list[str]]:
    """返回 (论文数组, 非致命问题列表)，或用 load_data 获取全部结果。"""
    papers = _read_json(PAPERS_PATH if path is None else path)
    errors = []
    if validate:
        errors = _validate_papers(papers)
    return papers, errors


def load_taxonomy(path: JsonPath | None = None, *, validate: bool = True) -> tuple[dict[str, Any], list[str]]:
    """返回 (分类标签字典, 非致命问题列表)。"""
    taxonomy = _read_json(TAXONOMY_PATH if path is None else path)
    errors = []
    if validate:
        errors = _validate_taxonomy(taxonomy)
    return taxonomy, errors


def load_state(path: JsonPath | None = None, *, validate: bool = True) -> tuple[dict[str, Any], list[str]]:
    """返回 (状态字典, 非致命问题列表)。"""
    state = _read_json(REPO_STATE_PATH if path is None else path)
    errors = []
    if validate:
        errors = _validate_state(state)
    return state, errors


def validate_data(
    papers: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    state: dict[str, Any],
    *,
    root: JsonPath | None = None,
) -> list[str]:
    """返回全部非致命问题描述；无问题返回 []，致命错误仍抛异常。

    编号计数器落后会导致编号复用，视为致命错误。
    会检查附件存在性，缺失附件计入列表；
    PDF 路径由 PDFS_DIR/classification.primary_category/metadata.filename 生成。
    精细总结正文位于 DETAILED_SUMMARIES_DIR/<paper_id>.md。
    root 可覆盖项目根目录，此时检查 root/data/pdfs 和 root/data/detailed_summaries。
    附件解析后越过各自目录或文件系统访问失败仍抛异常。不重新计算 PDF 哈希。
    """
    errors = _validate_papers(papers)
    errors.extend(_validate_taxonomy(taxonomy))
    errors.extend(_validate_state(state))

    pdf_base = Path(PDFS_DIR if root is None else Path(root) / "data" / "pdfs").resolve()
    detailed_summaries_base = Path(DETAILED_SUMMARIES_DIR if root is None else Path(root) / "data" / "detailed_summaries").resolve()

    def require_path(base: Path, relative: str, *, directory: bool = False) -> None:
        target = (base / relative).resolve()
        if not target.is_relative_to(base):
            raise ValueError(f"文件路径超出附件目录：{relative}")
        if not (target.is_dir() if directory else target.is_file()):
            errors.append(f"{'目录' if directory else '文件'}不存在或类型不符：{relative}")

    for cid in taxonomy["category_index"]:
        require_path(pdf_base, cid, directory=True)
    for paper in papers:
        pid = paper["paper_id"]
        if int(pid[1:]) > state["paper_id_counter"]:
            raise ValueError(f"paper_id_counter 小于已有编号：{pid}")
        classification = paper["classification"]
        document_type = paper["metadata"].get("document_type")
        if not isinstance(document_type, str) or document_type not in taxonomy["document_type_index"]:
            errors.append(f"论文引用未定义文献类型：{pid} / {document_type}")
        cid = classification.get("primary_category")
        category = taxonomy["category_index"].get(cid) if isinstance(cid, str) else None
        if isinstance(cid, str) and category is None:
            errors.append(f"论文引用未定义分类：{pid} / {cid}")
        for tid in classification["tags"]:
            if isinstance(tid, str) and tid not in taxonomy["tag_index"]:
                errors.append(f"论文引用未定义标签：{pid} / {tid}")
        if category is not None:
            relative = str(PurePosixPath(cid) / paper["metadata"]["filename"])
            require_path(pdf_base, relative)
        require_path(detailed_summaries_base, f"{pid}.md")
    return errors


def load_data(
    papers_path: JsonPath | None = None,
    taxonomy_path: JsonPath | None = None,
    state_path: JsonPath | None = None,
    *,
    validate: bool = True,
    root: JsonPath | None = None,
) -> dict[str, Any]:
    """返回 papers、taxonomy、repo_state、errors 四个键。

    errors 是非致命问题描述列表；validate=False 时不校验，errors 为 []。
    启用 validate 时同时检查附件存在性；自定义附件位置可传入 root。
    """
    papers, _ = load_papers(papers_path, validate=False)
    taxonomy, _ = load_taxonomy(taxonomy_path, validate=False)
    state, _ = load_state(state_path, validate=False)
    errors = validate_data(papers, taxonomy, state, root=root) if validate else []
    return {"papers": papers, "taxonomy": taxonomy, "repo_state": state, "errors": errors}
