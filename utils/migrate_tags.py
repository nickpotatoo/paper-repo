"""Create a shared tag index and replace paper tag names with stable IDs.

Run with: python migrate_tags.py
The migration is safe to run again: existing IDs are preserved.
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "paper_index.json"

# Existing near-duplicate names use one canonical label.
ALIASES = {
    "第一视角视频": "第一视角",
    "可穿戴": "可穿戴设备",
    "个性化": "个性化助理",
    "多模态": "多模态记忆",
    "事件图": "图记忆",
}


def main() -> None:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    registry = dict(data.get("tag_index", {}))
    is_initial_migration = not registry
    if len(registry.values()) != len(set(registry.values())):
        raise ValueError("标签索引中存在重复名称，请先合并。")

    name_to_id = {name: tag_id for tag_id, name in registry.items()}
    next_number = max(
        (int(tag_id[1:]) for tag_id in registry if tag_id.startswith("T") and tag_id[1:].isdigit()),
        default=0,
    ) + 1

    for paper in data["papers"]:
        resolved = []
        for value in paper["classification"].get("tags", []):
            if value in registry:
                tag_id = value
            else:
                if not is_initial_migration:
                    raise ValueError(
                        f"论文标签必须使用标签索引 ID：{paper['metadata']['title']} / {value}"
                    )
                name = ALIASES.get(value.strip(), value.strip())
                if not name:
                    raise ValueError(f"空标签：{paper['metadata']['title']}")
                if name not in name_to_id:
                    tag_id = f"T{next_number:03d}"
                    next_number += 1
                    registry[tag_id] = name
                    name_to_id[name] = tag_id
                tag_id = name_to_id[name]
            if tag_id not in resolved:
                resolved.append(tag_id)
        paper["classification"]["tags"] = resolved

    ordered = {}
    for key, value in data.items():
        if key == "paper_count":
            ordered["tag_index"] = registry
        if key != "tag_index":
            ordered[key] = value
    if "tag_index" not in ordered:
        ordered["tag_index"] = registry

    INDEX.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"标签索引：{len(registry)} 个；论文：{len(data['papers'])} 篇。")


if __name__ == "__main__":
    main()
