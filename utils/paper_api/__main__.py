"""python -m utils.paper_api --request request.json；也支持 stdin。"""
import argparse
import json
import sys
from pathlib import Path
from .api import PaperAPI


def main():
    parser = argparse.ArgumentParser(description="论文任务接口 JSON 调用入口")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--vectors-path", type=Path)
    parser.add_argument("--request", type=Path, help="UTF-8 JSON 请求文件；省略则读取 stdin")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        text = args.request.read_text(encoding="utf-8-sig") if args.request else sys.stdin.read()
        request = json.loads(text)
        result = PaperAPI(args.root, args.vectors_path).call(request["operation"], request.get("arguments"))
    except Exception as error:
        result = {"ok": False, "error": {"code": "invalid_request", "message": "无法读取 JSON 请求",
                                         "exception_type": type(error).__name__}}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
