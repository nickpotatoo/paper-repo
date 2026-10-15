import argparse
import json

from src import server, template
from src.config import DATA_DIR, PAPERS_PATH, TAXONOMY_PATH, REPO_STATE_PATH, PDFS_DIR, DETAILED_SUMMARIES_DIR


def _create_json(path, content):
    with path.open("x", encoding="utf-8", newline="\n") as target:
        json.dump(content, target, ensure_ascii=False, indent=2)
        target.write("\n")


def check_repo_data():
    files = (PAPERS_PATH, TAXONOMY_PATH, REPO_STATE_PATH)
    existing = [path.exists() for path in files]
    if not any(existing):
        if (DATA_DIR.exists() and any(DATA_DIR.iterdir())) or any(DETAILED_SUMMARIES_DIR.glob("P*.md")):
            raise ValueError("已有资料但缺少 repo 数据文件，请先恢复配置，不能创建空资料库")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _create_json(PAPERS_PATH, template._papers_template)
        _create_json(TAXONOMY_PATH, template._taxonomy_template)
        _create_json(REPO_STATE_PATH, template._repo_state_template)
    elif not all(existing):
        missing = ", ".join(path.name for path in files if not path.exists())
        raise ValueError(f"repo 数据文件不完整，缺少：{missing}")


def check_attachment_dirs():
    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    DETAILED_SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="论文资料库查看器")
    parser.add_argument("--no-open-viewer", action="store_true", help="启动服务但不自动打开浏览器")
    parser.add_argument("--without-check", action="store_true", help="跳过 repo 数据和附件目录检查")
    parser.add_argument("--port", type=int, default=5000, help="指定服务端口，默认 5000")
    args = parser.parse_args()
    if not args.without_check:
        check_repo_data()
        check_attachment_dirs()
    server.launch(open_browser=not args.no_open_viewer, port=args.port)
