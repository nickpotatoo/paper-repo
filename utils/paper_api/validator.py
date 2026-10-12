"""结构化草稿和正式索引的类型与引用校验。"""
import re
from .task_store import APIError

FIELDS = {
    "metadata.title", "metadata.document_type", "metadata.authors", "metadata.year",
    "classification.primary_category", "summary", "reading_notes", "extraction_status",
}


def get_field(draft, path):
    node = draft
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def set_field(draft, path, value, delete=False):
    parts = path.split(".")
    node = draft
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    if delete:
        node.pop(parts[-1], None)
    else:
        node[parts[-1]] = value


def field_error(path, value, index):
    if path == "metadata.authors":
        valid = value is None or isinstance(value, str) and bool(value.strip())
    elif path == "metadata.year":
        valid = value is None or type(value) is int and 1 <= value <= 9999
    elif path == "classification.primary_category":
        valid = isinstance(value, str) and value in index["category_index"]
    elif path == "extraction_status":
        valid = value in ("text_extractable", "text_unextractable")
    else:
        valid = isinstance(value, str) and bool(value.strip())
        if path == "metadata.document_type" and valid:
            valid = value.isascii()
    return None if valid else {"field": path, "message": "字段类型、值或引用无效"}


def validate_draft(draft, index):
    missing, errors = [], []
    for field in sorted(FIELDS):
        exists, value = get_field(draft, field)
        if not exists:
            missing.append(field)
        else:
            error = field_error(field, value, index)
            if error:
                errors.append(error)
    exists, tags = get_field(draft, "classification.tags")
    if not exists:
        missing.append("classification.tags")
    elif not isinstance(tags, list) or any(not isinstance(t, str) or t not in index["tag_index"] for t in tags):
        errors.append({"field": "classification.tags", "message": "标签必须为已定义 ID 列表"})
    elif len(set(tags)) != len(tags):
        errors.append({"field": "classification.tags", "message": "标签不能重复"})
    return missing, errors


def validate_index(index):
    if not isinstance(index, dict) or not all(k in index for k in (
        "description", "category_index", "tag_index", "papers", "paper_count", "paper_id_counter")):
        raise APIError("invalid_index", "正式索引缺少必要字段")
    ids = [p.get("paper_id") for p in index["papers"]]
    if any(not isinstance(i, str) or not re.fullmatch(r"P\d{6,}", i) for i in ids) or len(set(ids)) != len(ids):
        raise APIError("invalid_index", "论文编号缺失、格式错误或重复")
    if type(index["paper_id_counter"]) is not int or index["paper_id_counter"] < max([int(i[1:]) for i in ids] + [0]):
        raise APIError("invalid_index", "论文编号计数器错误")
    if index["paper_count"] != len(ids):
        raise APIError("invalid_index", "paper_count 与论文数量不一致")
