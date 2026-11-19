"""校验分类草稿，注册和删除分类、标签与文献类型定义。"""

_TAXONOMY_KINDS = {
    "category": ("category_index", "C"),
    "tag": ("tag_index", "T"),
    "document_type": ("document_type_index", "D"),
}
_DRAFT_FIELDS = (
    ("category", "primary_category", "proposed_categories"),
    ("tag", "tags", "proposed_tags"),
    ("document_type", "document_type", "proposed_document_types"),
)


def _name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _ids_by_name(entries: dict) -> dict[str, str]:
    ids = {}
    for entry_id, value in entries.items():
        name = value["name"] if isinstance(value, dict) else value
        ids.setdefault(_name_key(name), entry_id)
    return ids


def _current_id_number(entries: dict, counters: dict, prefix: str) -> int:
    return max(counters.get(prefix, 0), max((int(key[1:]) for key in entries), default=0))


def _classification_issues(draft: dict, taxonomy: dict, *, reviewing: bool) -> list[dict]:
    issues = []

    def report(field, message, *, warning=False):
        issues.append({
            "code": "pending_candidate" if warning else "invalid",
            "message": message,
            "severity": "warning" if warning else "error",
            "field": field,
        })

    if not isinstance(draft, dict):
        report("classification", "classification 必须为对象")
        return issues

    for kind, reference_field, candidate_field in _DRAFT_FIELDS:
        index, _ = _TAXONOMY_KINDS[kind]
        entries = taxonomy.get(index, {})
        references = draft.get(reference_field)
        candidates = draft.get(candidate_field, [])
        if not isinstance(candidates, list):
            report(candidate_field, f"{candidate_field} 必须为数组")
            candidates = []

        if kind == "tag":
            if not isinstance(references, list) or not all(
                isinstance(tag, str) and tag in entries for tag in references
            ) or len(set(references)) != len(references):
                report(reference_field, "标签必须是已定义且不重复的 ID")
        elif references is None:
            if reference_field not in draft or len(candidates) != 1:
                report(reference_field, f"{reference_field} 为 null 时须提供一个对应候选")
        else:
            if not isinstance(references, str) or references not in entries:
                report(reference_field, f"{reference_field} 必须引用已定义的 ID 或为 null")
            if candidates:
                report(candidate_field, f"已有 {reference_field} 时不能同时提出对应候选")

        existing_names = _ids_by_name(entries) if reviewing and candidates else {}
        candidate_names = set()
        required_fields = ["name"]
        if kind == "category":
            required_fields.append("description")
        if reviewing:
            required_fields.append("reason")

        for number, candidate in enumerate(candidates):
            location = f"{candidate_field}[{number}]"
            if not isinstance(candidate, dict):
                report(location, "候选项必须为对象")
                continue
            for key in required_fields:
                value = candidate.get(key)
                if not isinstance(value, str) or not value.strip():
                    report(f"{location}.{key}", f"{key} 必须为非空字符串")
            if "id" in candidate:
                report(f"{location}.id", "候选项不能包含正式 ID")
            if kind != "category" and candidate.get("description") is not None:
                report(f"{location}.description", "描述仅适用于分类")
            name = candidate.get("name")
            if isinstance(name, str) and name.strip():
                key = _name_key(name)
                if key in candidate_names:
                    report(f"{location}.name", "候选名称不能重复")
                if key in existing_names:
                    report(f"{location}.name", "候选名称已存在于 taxonomy")
                candidate_names.add(key)

        if reviewing and candidates:
            report(candidate_field, f"{candidate_field} 包含待审核的新定义，入库前须确认并分配正式 ID", warning=True)
    return issues


def validate_classification_draft(draft: dict, taxonomy: dict) -> list[dict]:
    """检查待审阅草稿，返回阻断错误及候选提示。"""
    return _classification_issues(draft, taxonomy, reviewing=True)


def register_classification(draft: dict, taxonomy: dict, state: dict) -> dict:
    """返回正式引用，并在入库的 taxonomy 和 state 工作副本中登记新定义。"""
    issues = _classification_issues(draft, taxonomy, reviewing=False)
    if issues:
        raise ValueError("；".join(issue["message"] for issue in issues))

    references = {}
    for kind, reference_field, candidate_field in _DRAFT_FIELDS:
        index, prefix = _TAXONOMY_KINDS[kind]
        entries = taxonomy[index]
        selected = draft[reference_field]
        candidates = draft.get(candidate_field, [])
        if not candidates:
            references[reference_field] = selected
            continue

        ids_by_name = _ids_by_name(entries)
        candidate_ids = []
        for candidate in candidates:
            name = candidate["name"].strip()
            entry_id = ids_by_name.get(_name_key(name))
            if entry_id is None:
                counters = state.setdefault("taxonomy_id_counters", {})
                number = _current_id_number(entries, counters, prefix) + 1
                counters[prefix] = number
                entry_id = f"{prefix}{number:03d}"
                entries[entry_id] = (
                    {"name": name, "description": candidate["description"].strip()}
                    if kind == "category" else name
                )
            candidate_ids.append(entry_id)

        references[reference_field] = (
            list(dict.fromkeys([*selected, *candidate_ids])) if kind == "tag" else candidate_ids[0]
        )
    return references


def delete_taxonomy_entry(
    kind: str, entry_id: str, *, papers: list[dict], taxonomy: dict, state: dict,
) -> None:
    """从工作副本删除未被引用的定义，并保留编号上限。"""
    index, prefix = _TAXONOMY_KINDS[kind]
    entries = taxonomy[index]
    if entry_id not in entries:
        raise KeyError(entry_id)

    for paper in papers:
        classification = paper["classification"]
        references = {
            "category": [classification["primary_category"]],
            "tag": classification["tags"],
            "document_type": [paper["metadata"]["document_type"]],
        }
        if entry_id in references[kind]:
            raise ValueError(f"{entry_id} 仍被论文 {paper['paper_id']} 引用")

    counters = state.setdefault("taxonomy_id_counters", {})
    counters[prefix] = _current_id_number(entries, counters, prefix)
    del entries[entry_id]
