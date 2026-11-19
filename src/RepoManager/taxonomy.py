"""分类、标签和文献类型的候选校验。"""


def normalized_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def validate_classification(cls: dict, taxonomy: dict, *, for_ingest: bool = False) -> list[dict]:
    """校验任务分类。入库时允许复用审阅期间新增的同名定义。"""
    issues = []

    def require(condition, field, message):
        if not condition:
            issues.append({"code": "invalid", "message": message, "severity": "error", "field": field})

    if not isinstance(cls, dict):
        require(False, "classification", "classification 必须为对象")
        return issues

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
            normalized_name(value.get("name") if isinstance(value, dict) else value)
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
                if for_ingest and key == "reason":
                    continue
                value = item.get(key)
                require(isinstance(value, str) and bool(value.strip()), f"{location}.{key}", f"{key} 必须为非空字符串")
            require("id" not in item, f"{location}.id", "候选项不能包含正式 ID")
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                normalized = normalized_name(name)
                require(normalized not in names, f"{location}.name", "候选名称不能重复")
                require(for_ingest or normalized not in existing_names, f"{location}.name", "候选名称已存在于 taxonomy")
                names.add(normalized)
        if items and not for_ingest:
            issues.append({"code": "pending_candidate", "message": f"{field} 包含待审核的新定义，入库前须确认并分配正式 ID", "severity": "warning", "field": field})

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
    return issues
