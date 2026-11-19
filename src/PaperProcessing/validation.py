"""待审阅草稿的结构与引用校验。"""

import re
from src.RepoManager import validate_classification_draft
from .models import ValidationIssue, ValidationReport

VALIDATION_ARTIFACT = "validation/report.json"


def validate_draft(draft: dict, taxonomy: dict) -> ValidationReport:
    issues = []
    def require(condition, field, message):
        if not condition:
            issues.append(ValidationIssue(code="invalid", message=message, field=field))

    meta = draft.get("metadata") or {}
    cls = draft.get("classification")
    if not isinstance(meta, dict):
        require(False, "metadata", "metadata 必须为对象")
        meta = {}
    for key in ("title", "original_filename"):
        require(isinstance(meta.get(key), str) and bool(meta[key].strip()), key, f"{key} 不能为空")
    filename = meta.get("filename")
    require(isinstance(filename, str) and bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.pdf", filename)), "filename", "文件名须为英文小写短横线 PDF 名称")
    require("authors" in meta and (meta["authors"] is None or isinstance(meta["authors"], str) and bool(meta["authors"].strip())), "authors", "作者须为非空字符串或 null")
    require("year" in meta and (meta["year"] is None or type(meta["year"]) is int and 1 <= meta["year"] <= 9999), "year", "年份须为 1 至 9999 或 null")
    issues.extend(ValidationIssue(**issue) for issue in validate_classification_draft(cls, taxonomy))
    for key in ("rough_summary", "detailed_summary"):
        value = draft.get(key)
        require(isinstance(value, str) and bool(value.strip()), key, f"{key} 不能为空")
    require(bool(draft.get("pdf_valid")), "pdf", "PDF 不存在或哈希不匹配")
    return ValidationReport(issues=issues)
