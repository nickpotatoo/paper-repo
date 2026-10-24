"""JSONL shard IO only. The calling VectorStore owns locks and caches."""

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path

from src.config import VECTOR_DATA_DIR, VECTOR_MAX_ROWS, VECTOR_FILE_PREFIX, VECTOR_FILE_SUFFIX

ShardFiles = list[tuple[int, Path]]
FileSignature = tuple[tuple[str, int, int, int, int], ...]


class JsonlStorage:
    def __init__(self, vectors_dir=None, *, max_rows: int = VECTOR_MAX_ROWS):
        if type(max_rows) is not int or max_rows <= 0:
            raise ValueError("max_rows 必须为正整数")
        self.directory = Path(vectors_dir or VECTOR_DATA_DIR)
        self.max_rows = max_rows
        self._pattern = re.compile(
            re.escape(VECTOR_FILE_PREFIX) + r"_([1-9][0-9]*)" + re.escape(VECTOR_FILE_SUFFIX)
        )

    def files(self) -> ShardFiles:
        if not self.directory.exists():
            return []
        files = []
        for path in self.directory.iterdir():
            match = self._pattern.fullmatch(path.name)
            if match and path.is_file():
                files.append((int(match.group(1)), path))
        return sorted(files, key=lambda item: item[0])

    def signature(self, files: ShardFiles | None = None) -> FileSignature:
        signature = []
        for _, path in self.files() if files is None else files:
            stat = path.stat()
            signature.append((path.name, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino))
        return tuple(signature)

    def read_records(self, files: ShardFiles | None = None) -> Iterator[dict]:
        for _, path in self.files() if files is None else files:
            with path.open("r", encoding="utf-8") as source:
                for line_number, line in enumerate(source, 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError as error:
                        raise ValueError(f"向量文件 JSON 错误：{path.name}:{line_number}") from error
                    if (not isinstance(record, dict) or not isinstance(record.get("metadata"), dict)
                            or not isinstance(record.get("vector"), list)):
                        raise ValueError(f"向量记录格式错误：{path.name}:{line_number}")
                    yield record

    def append(self, vectors: list[list[float]], metadata: dict) -> None:
        """Append without transaction guarantees; caller serializes all operations."""
        self.directory.mkdir(parents=True, exist_ok=True)
        files = self.files()
        file_index, path = files[-1] if files else (1, self._shard_path(1))
        rows = self._count_rows(path)
        offset = 0
        while offset < len(vectors):
            if rows >= self.max_rows:
                file_index += 1
                path = self._shard_path(file_index)
                rows = 0
            batch = vectors[offset:offset + self.max_rows - rows]
            needs_newline = False
            if rows:
                with path.open("rb") as source:
                    source.seek(-1, os.SEEK_END)
                    needs_newline = source.read(1) != b"\n"
            with path.open("a", encoding="utf-8", newline="\n") as target:
                if needs_newline:
                    target.write("\n")
                for vector in batch:
                    record = {"vector": vector, "metadata": metadata}
                    target.write(json.dumps(record, ensure_ascii=False) + "\n")
            offset += len(batch)
            rows += len(batch)

    def _shard_path(self, index: int) -> Path:
        return self.directory / f"{VECTOR_FILE_PREFIX}_{index}{VECTOR_FILE_SUFFIX}"

    @staticmethod
    def _count_rows(path: Path) -> int:
        if not path.exists():
            return 0
        with path.open("rb") as source:
            return sum(1 for _ in source)
