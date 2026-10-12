"""Assign stable paper IDs; preserve existing IDs and never reuse issued numbers."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "paper_index.json"


def main() -> None:
    data = json.loads(INDEX.read_text(encoding="utf-8-sig"))
    counter = data.get("paper_id_counter", 0)
    if type(counter) is not int or counter < 0:
        raise ValueError("论文编号计数器必须是非负整数")
    used = set()
    for paper in data["papers"]:
        if "paper_id" not in paper:
            continue
        paper_id = paper["paper_id"]
        if not isinstance(paper_id, str) or not re.fullmatch(r"P[0-9]{6,}", paper_id) or int(paper_id[1:]) < 1:
            raise ValueError(f"无效论文编号：{paper_id}")
        if paper_id in used or paper_id != f"P{int(paper_id[1:]):06d}":
            raise ValueError(f"重复或非规范论文编号：{paper_id}")
        used.add(paper_id)
        counter = max(counter, int(paper_id[1:]))
    assigned = 0
    for position, paper in enumerate(data["papers"]):
        if "paper_id" not in paper:
            counter += 1
            data["papers"][position] = {"paper_id": f"P{counter:06d}", **paper}
            assigned += 1
    data["paper_id_counter"] = counter
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"论文：{len(data['papers'])} 篇；新增编号：{assigned} 个；编号计数器：{counter}")


if __name__ == "__main__":
    main()
