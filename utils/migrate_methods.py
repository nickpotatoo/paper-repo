"""Move method summaries from paper_index.json into one Markdown file per paper.

Run with: python migrate_methods.py
Existing Markdown files are never overwritten, so later edits are preserved.
"""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "paper_index.json"
METHODS = ROOT / "methods"


def main() -> None:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    METHODS.mkdir(exist_ok=True)
    used_paths: set[str] = set()

    used_ids: set[str] = set()
    for paper in data["papers"]:
        paper_id = paper.get("paper_id")
        if not isinstance(paper_id, str) or not re.fullmatch(r"P[0-9]{6,}", paper_id) or paper_id in used_ids:
            raise ValueError("论文编号缺失、无效或重复，请先运行 utils/migrate_paper_ids.py")
        used_ids.add(paper_id)
        title = paper["metadata"]["title"]
        relative = paper.get("method_document") or f"methods/{paper_id}.md"
        if relative in used_paths:
            raise ValueError(f"重复的方法文档路径：{relative}")
        used_paths.add(relative)

        destination = (ROOT / relative).resolve()
        if not destination.is_relative_to(METHODS.resolve()):
            raise ValueError(f"方法文档必须位于 methods 文件夹：{relative}")

        summary = paper.get("method_summary", "").strip()
        if not destination.exists():
            if not summary:
                raise ValueError(f"缺少方法内容：{title}")
            destination.write_text(
                f"# {title}\n\n## 方法概述\n\n{summary}\n",
                encoding="utf-8",
            )

        paper["method_document"] = relative.replace("\\", "/")
        paper.pop("method_summary", None)

    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已关联 {len(data['papers'])} 个方法文档；已有 Markdown 文件未被覆盖。")


if __name__ == "__main__":
    main()
