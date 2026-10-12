"""内容哈希接口：用于文件去重和内容变更检测，仅依赖 Python 标准库。

统一返回 SHA-256 的 64 位小写十六进制字符串，不写入索引或向量库。
"""

from __future__ import annotations

import hashlib
from os import PathLike
from pathlib import Path

__all__ = ["hash_bytes", "hash_text", "hash_file"]


def hash_bytes(data: bytes) -> str:
    """计算原始字节的 SHA-256；空字节也有确定的哈希值。"""
    if not isinstance(data, bytes):
        raise TypeError("data 必须是 bytes")
    return hashlib.sha256(data).hexdigest()


def hash_text(text: str, *, encoding: str = "utf-8") -> str:
    """先编码再计算哈希；不自动去除空白、转换换行或规范化 Unicode。

    比较文本时应使用相同的 encoding；默认使用 UTF-8。
    """
    if not isinstance(text, str):
        raise TypeError("text 必须是 str")
    return hash_bytes(text.encode(encoding))


def hash_file(
    path: str | PathLike[str], *, chunk_size: int = 1024 * 1024
) -> str:
    """按块读取文件并计算原始内容的 SHA-256，默认每块 1 MiB。

    文件名、路径、修改时间不参与计算；重命名不会改变结果。
    相对路径以调用进程的当前工作目录为基准。读取期间文件应保持不变。
    文件不存在、权限不足等情况保留原始文件系统异常，不返回空值。
    """
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
        raise TypeError("chunk_size 必须是整数")
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
