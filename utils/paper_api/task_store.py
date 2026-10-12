"""原子文件操作、跨进程锁及任务存储。"""
import json
import os
import re
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class APIError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def as_dict(self):
        return {"code": self.code, "message": self.message, **self.details}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".paper-api-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


_guard = threading.Lock()
_locks = {}


@contextmanager
def file_lock(path, timeout=120):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _guard:
        local = _locks.setdefault(str(path), threading.RLock())
    if not local.acquire(timeout=timeout):
        raise APIError("lock_timeout", "等待锁超时")
    stream = None
    acquired = False
    try:
        stream = open(path, "a+b")
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise APIError("lock_timeout", "等待锁超时")
                time.sleep(0.05)
        yield
    finally:
        if stream is not None:
            if acquired:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_UN)
            stream.close()
        local.release()


class TaskStore:
    def __init__(self, config):
        self.config = config

    def directory(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r"task_[0-9a-f]{32}", task_id):
            raise APIError("invalid_task_id", "task_id 格式错误")
        path = (self.config.tasks_dir / task_id).resolve()
        if path.parent != self.config.tasks_dir.resolve():
            raise APIError("invalid_path", "任务路径超出目录")
        return path

    def lock(self, task_id):
        self.directory(task_id)
        return file_lock(self.config.data / "locks" / (task_id + ".lock"))

    def library_lock(self):
        return file_lock(self.config.data / "locks" / "library.lock")

    def load(self, task_id):
        path = self.directory(task_id) / "task.json"
        if not path.exists():
            raise APIError("task_not_found", "任务不存在或已经完成删除", task_id=task_id)
        return read_json(path)

    def save(self, task):
        write_json(self.directory(task["task_id"]) / "task.json", task)

    def method_path(self, task):
        reference = task.get("method")
        if not reference:
            return None
        digest = reference.get("content_hash", "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise APIError("invalid_method", "方法文档引用错误")
        return self.directory(task["task_id"]) / "methods" / (digest + ".md")

    def remove(self, task_id):
        # 已验证 UUID，且解析后的目标必须直接位于任务目录内。
        path = self.directory(task_id)
        if path.exists():
            shutil.rmtree(path)
