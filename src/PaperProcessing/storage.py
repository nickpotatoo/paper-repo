"""任务文件读写及安全路径管理。"""

import os
import re
import shutil
import tempfile
from pathlib import Path

from .models import Task


class TaskStorage:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str, path: str = "") -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
            raise ValueError("无效任务 ID")
        base = (self.root / task_id).resolve()
        target = (base / path).resolve()
        if not target.is_relative_to(base):
            raise ValueError("路径超出任务目录")
        return target

    def find_by_source_hash(self, sha256: str) -> list[str]:
        matches = []
        for path in self.root.glob("*/task.json"):
            task = Task.model_validate_json(path.read_text(encoding="utf-8"))
            if task.source.sha256 == sha256:
                matches.append(task.task_id)
        return matches

    def create(self, task: Task, source: Path) -> None:
        base = self._path(task.task_id)
        base.mkdir(exist_ok=False)
        target = self._path(task.task_id, task.source.copy_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        self.save(task)

    def load(self, task_id: str) -> Task:
        return Task.model_validate_json(self._path(task_id, "task.json").read_text(encoding="utf-8"))

    def save(self, task: Task) -> None:
        staged = self.stage_artifact(task.task_id, "task.json", task.model_dump_json(indent=2).encode("utf-8"))
        self.publish_artifact(task.task_id, staged, "task.json")

    def read_artifact(self, task_id: str, path: str) -> bytes:
        return self._path(task_id, path).read_bytes()

    def stage_artifact(self, task_id: str, path: str, data: bytes) -> str:
        target = self._path(task_id, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".stage-", delete=False) as stream:
            stream.write(data)
            name = Path(stream.name)
        return name.relative_to(self._path(task_id)).as_posix()

    def publish_artifact(self, task_id: str, staged: str, target: str) -> None:
        os.replace(self._path(task_id, staged), self._path(task_id, target))

    def archive_artifact(self, task_id: str, path: str, attempt: int) -> str:
        source = self._path(task_id, path)
        target = self._path(task_id, f"history/{attempt}/{path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(target)
        shutil.copyfile(source, target)
        return target.relative_to(self._path(task_id)).as_posix()
