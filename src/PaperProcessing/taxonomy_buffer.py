"""任务共享的待入库分类和标签。"""

from src.RepoManager import validate_classification_draft
from src.RepoManager.taxonomy import taxonomy_ids_by_name, taxonomy_name_key

CLASSIFICATION_ARTIFACT = "analysis/classification.json"
BUFFER_FILENAME = "taxonomy_buffer.json"
_INDEXES = (
    ("category_index", "C", "proposed_categories", "pending_categories"),
    ("tag_index", "T", "proposed_tags", "pending_tags"),
)


def empty_buffer() -> dict:
    return {"category_index": {}, "tag_index": {}, "counters": {}}


def taxonomy_with_pending(taxonomy: dict, pending: dict) -> dict:
    return {
        **taxonomy,
        "category_index": {**taxonomy["category_index"], **pending["category_index"]},
        "tag_index": {
            **taxonomy["tag_index"],
            **{entry_id: entry["name"] for entry_id, entry in pending["tag_index"].items()},
        },
    }


def buffer_classification(draft: dict, taxonomy: dict, pending: dict) -> dict:
    issues = validate_classification_draft(draft, taxonomy_with_pending(taxonomy, pending))
    errors = [issue["message"] for issue in issues if issue["severity"] == "error"]
    if errors:
        raise ValueError("；".join(errors))

    draft = dict(draft)
    for index, prefix, proposals, _ in _INDEXES:
        new_ids = []
        for proposal in draft.pop(proposals, []):
            number = pending["counters"].get(prefix, 0) + 1
            pending["counters"][prefix] = number
            entry_id = f"T-{prefix}{number:03d}"
            fields = ("name", "description", "reason") if prefix == "C" else ("name", "reason")
            pending[index][entry_id] = {key: proposal[key].strip() for key in fields}
            new_ids.append(entry_id)
        if prefix == "C" and new_ids:
            draft["primary_category"] = new_ids[0]
        elif prefix == "T":
            draft["tags"] = [*draft["tags"], *new_ids]
    return _with_pending_details(draft, pending)


def pending_as_proposals(draft: dict, pending: dict) -> dict:
    """将所引用的临时定义转回正式库入库接口接受的候选。"""
    if not isinstance(draft, dict):
        raise ValueError("classification 必须为对象")
    result = dict(draft)
    for _, _, _, details in _INDEXES:
        result.pop(details, None)

    def proposal(index, entry_id):
        try:
            return pending[index][entry_id]
        except KeyError:
            raise ValueError(f"未找到临时分类或标签：{entry_id}") from None

    primary = draft.get("primary_category")
    if _is_temporary(primary):
        result["primary_category"] = None
        result["proposed_categories"] = [proposal("category_index", primary)]
    tags = draft.get("tags")
    if isinstance(tags, list) and any(_is_temporary(tag) for tag in tags):
        result["tags"] = [tag for tag in tags if not _is_temporary(tag)]
        result["proposed_tags"] = [proposal("tag_index", tag) for tag in tags if _is_temporary(tag)]
    return result


def partition_registered_ids(pending: dict, taxonomy: dict) -> tuple[dict[str, str], dict]:
    promoted = {}
    remaining = {"counters": pending["counters"]}
    for index, _, _, _ in _INDEXES:
        remaining[index] = {}
        official_ids = taxonomy_ids_by_name(taxonomy[index]) if pending[index] else {}
        for entry_id, candidate in pending[index].items():
            official_id = official_ids.get(taxonomy_name_key(candidate["name"]))
            if official_id is None:
                remaining[index][entry_id] = candidate
            else:
                promoted[entry_id] = official_id
    return promoted, remaining


def replace_registered_ids(draft: dict, promoted: dict[str, str], pending: dict) -> dict:
    if not isinstance(draft, dict):
        return draft
    primary = draft.get("primary_category")
    tags = draft.get("tags")
    primary_changed = isinstance(primary, str) and primary in promoted
    tags_changed = isinstance(tags, list) and all(isinstance(tag, str) for tag in tags) and any(
        tag in promoted for tag in tags
    )
    if not primary_changed and not tags_changed:
        return draft
    result = dict(draft)
    if primary_changed:
        result["primary_category"] = promoted[primary]
    if tags_changed:
        result["tags"] = list(dict.fromkeys(promoted.get(tag, tag) for tag in tags))
    return _with_pending_details(result, pending)


def _is_temporary(value) -> bool:
    return isinstance(value, str) and value.startswith("T-")


def _with_pending_details(draft: dict, pending: dict) -> dict:
    """为任务预览附上所引用的待入库定义。"""
    result = dict(draft)
    primary = draft.get("primary_category")
    tags = draft.get("tags")
    references_by_index = {
        "category_index": [primary],
        "tag_index": tags if isinstance(tags, list) else [],
    }
    for index, _, _, details in _INDEXES:
        result.pop(details, None)
        referenced = {
            ref: pending[index][ref] for ref in references_by_index[index]
            if _is_temporary(ref) and ref in pending[index]
        }
        if referenced:
            result[details] = referenced
    return result
