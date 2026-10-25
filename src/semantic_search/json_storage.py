"""Per-document JSON IO; VectorStore owns operation locks and content logic."""

import json
import os
import re
import tempfile
from pathlib import Path

from src.config import VECTOR_DATA_DIR

class JsonStorage:
    def __init__(self, vectors_dir=None):
        self.directory = Path(vectors_dir or VECTOR_DATA_DIR)

    def _document_path(self, document_id: str) -> Path:
        if not isinstance(document_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", document_id):
            raise ValueError("document_id 必须为只包含英文字母、数字、短横线或下划线的非空字符串")
        path = self.directory / f"{document_id}.json"
        if not path.resolve().is_relative_to(self.directory.resolve()):
            raise ValueError("向量文件路径超出存储目录")
        return path

    def files(self) -> list[Path]:
        if not self.directory.exists():
            return []
        files = sorted(self.directory.glob("*.json"), key=lambda path: path.name)
        for path in files:
            self._document_path(path.stem)
            if not path.is_file():
                raise ValueError(f"向量文件不是普通文件：{path.name}")
        return files

    def read_document(self, document_id: str) -> object:
        path = self._document_path(document_id)
        try:
            with path.open(encoding="utf-8") as source:
                document = json.load(source)
        except ValueError as error:
            raise ValueError(f"向量文件 JSON 错误：{path.name}") from error
        return document

    def delete(self, document_id: str) -> None:
        """Delete the target JSON; a missing file is already deleted."""
        self._document_path(document_id).unlink(missing_ok=True)

    def write(self, document_id: str, document: dict) -> None:
        """Serialize caller-provided JSON and atomically replace the target file."""
        path = self._document_path(document_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=self.directory,
                prefix=f".{document_id}.", suffix=".tmp", delete=False,
            ) as target:
                temporary_path = Path(target.name)
                json.dump(document, target, ensure_ascii=False, indent=2, allow_nan=False)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
