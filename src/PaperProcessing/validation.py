"""待审阅草稿的结构与引用校验。"""

import re
from .models import ValidationIssue, ValidationReport


def validate_draft(draft: dict, taxonomy: dict) -> ValidationReport:
    issues = []
    def require(condition, field, message):
        if not condition:
            issues.append(ValidationIssue(code="invalid", message=message, field=field))

    meta = draft.get("metadata") or {}
    cls = draft.get("classification") or {}
    if not isinstance(meta, dict):
        require(False, "metadata", "metadata 必须为对象")
        meta = {}
    if not isinstance(cls, dict):
        require(False, "classification", "classification 必须为对象")
        cls = {}
    for key in ("title", "original_filename"):
        require(isinstance(meta.get(key), str) and bool(meta[key].strip()), key, f"{key} 不能为空")
    filename = meta.get("filename")
    require(isinstance(filename, str) and bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.pdf", filename)), "filename", "文件名须为英文小写短横线 PDF 名称")
    require("authors" in meta and (meta["authors"] is None or isinstance(meta["authors"], str) and bool(meta["authors"].strip())), "authors", "作者须为非空字符串或 null")
    require("year" in meta and (meta["year"] is None or type(meta["year"]) is int and 1 <= meta["year"] <= 9999), "year", "年份须为 1 至 9999 或 null")
    candidate_specs = (
        ("proposed_categories", "category_index", ("name", "description", "reason")),
        ("proposed_tags", "tag_index", ("name", "reason")),
        ("proposed_document_types", "document_type_index", ("name", "reason")),
    )
    candidates = {}
    for field, index, required in candidate_specs:
        items = cls.get(field, [])
        if not isinstance(items, list):
            require(False, field, f"{field} 必须为数组")
            candidates[field] = []
            continue
        candidates[field] = items
        existing = taxonomy.get(index, {})
        existing_names = {
            (value.get("name") if isinstance(value, dict) else value).strip().casefold()
            for value in existing.values()
            if isinstance(value.get("name") if isinstance(value, dict) else value, str)
        }
        names = set()
        for number, item in enumerate(items):
            location = f"{field}[{number}]"
            if not isinstance(item, dict):
                require(False, location, "候选项必须为对象")
                continue
            for key in required:
                value = item.get(key)
                require(isinstance(value, str) and bool(value.strip()), f"{location}.{key}", f"{key} 必须为非空字符串")
            require("id" not in item, f"{location}.id", "候选项不能包含正式 ID")
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                normalized = name.strip().casefold()
                require(normalized not in names, f"{location}.name", "候选名称不能重复")
                require(normalized not in existing_names, f"{location}.name", "候选名称已存在于 taxonomy")
                names.add(normalized)
        if items:
            issues.append(ValidationIssue(code="pending_candidate", message=f"{field} 包含待审核的新定义，入库前须确认并分配正式 ID", severity="warning", field=field))

    for key, index, proposed in (("primary_category", "category_index", "proposed_categories"), ("document_type", "document_type_index", "proposed_document_types")):
        value = cls.get(key)
        items = candidates[proposed]
        if value is None:
            require(key in cls and len(items) == 1, key, f"{key} 为 null 时须提供一个对应候选")
        else:
            require(isinstance(value, str) and value in taxonomy.get(index, {}), key, f"{key} 必须引用已定义的 ID 或为 null")
            require(not items, proposed, f"已有 {key} 时不能同时提出对应候选")
    tags = cls.get("tags")
    require(isinstance(tags, list) and all(isinstance(t, str) and t in taxonomy.get("tag_index", {}) for t in tags) and len(set(tags)) == len(tags), "tags", "标签必须是已定义且不重复的 ID")
    for key in ("rough_summary", "detailed_summary"):
        value = draft.get(key)
        require(isinstance(value, str) and bool(value.strip()), key, f"{key} 不能为空")
    require(bool(draft.get("pdf_valid")), "pdf", "PDF 不存在或哈希不匹配")
    return ValidationReport(issues=issues)
