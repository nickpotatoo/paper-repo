import json
from os import PathLike
from pathlib import Path

from utils import hash

def _load_hash() -> list[str]:
    """读取索引中所有已收录论文的 SHA-256；缺失字段时保留异常。"""
    root = Path(__file__).resolve().parents[1]
    with (root / "paper_index.json").open(encoding="utf-8") as source:
        index = json.load(source)
    return [
        paper["metadata"]["sha256"]
        for paper in index["papers"]
    ]

def compare(path: str | PathLike[str]) -> bool:
    """比对path下文件和已有论文SHA-256"""
    return compare(hash.hash_file(path))

def compare(hash: str) -> bool:
    """比对hash和已有论文的SHA-256"""
    hashes = _load_hash()
    for h in hashes:
        if hash == hashes:
            return True
    return False
