"""任务运行入口及任务文件管理。"""

import logging
import os
import re
import shutil
import tempfile
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from src.hash_duplicate import hash_file
from .models import StageRecord, Task, TaskSource, TaskStatusUpdate


TASK_OPERATION_LOCK = threading.RLock()
_TASK_CREATION_LOCK = threading.RLock()
_ACTIVE_VECTOR_TASKS: set[tuple[Path, str]] = set()
logger = logging.getLogger(__name__)


class UnsupportedRegenerationAction(ValueError):
    """请求的操作不属于重生成阶段。"""


class TaskManager:
    def __init__(
        self, root: Path, *, create_root: bool = True,
        papers_path: Path | None = None, taxonomy_path: Path | None = None,
        callback: Callable[[TaskStatusUpdate], None] | None = None,
    ):
        self.root = Path(root).resolve()
        self.papers_path = papers_path
        self.taxonomy_path = taxonomy_path
        self.callback = callback
        if create_root:
            self.root.mkdir(parents=True, exist_ok=True)

    def _workflow(self):
        from .stages import StageHandlers
        from .workflow import PaperWorkflow

        handlers = StageHandlers(self, papers_path=self.papers_path, taxonomy_path=self.taxonomy_path)
        return PaperWorkflow(self, handlers, on_transition=self._record_workflow_transition)

    def _record_workflow_transition(self, task: Task) -> None:
        task.updated_at = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
        self.save(task)
        if self.callback is not None:
            try:
                self.callback(TaskStatusUpdate.from_task(task))
            except Exception:
                logger.exception("任务状态回调失败")

    def run_task(self, task_id: str) -> Task:
        with TASK_OPERATION_LOCK:
            task = self.load(task_id)
            try:
                workflow = self._workflow()
            except (ImportError, OSError, RuntimeError) as error:
                if task.status in ("pending", "failed") and task.current_stage in task.stages and task.current_stage != "vectorize":
                    logger.warning("任务工作流启动失败：%s", type(error).__name__)
                    now = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
                    stage = task.stages[task.current_stage]
                    stage.status = "failed"
                    stage.finished_at = now
                    stage.error = {"code": type(error).__name__, "message": "无法启动论文处理工作流"}
                    task.status = "failed"
                    task.updated_at = now
                    self.save(task)
                    return task
                raise
            return workflow.run(task)

    def run_pending(self, task_id: str) -> Task | None:
        """执行排队中的新任务。对已执行或已归档的任务跳过调度。"""
        with TASK_OPERATION_LOCK:
            try:
                task = self.load(task_id)
            except FileNotFoundError:
                return None
            if task.status == "pending" and task.current_stage == "prepare":
                return self.run_task(task_id)
            return task

    def get_status(self, task_id: str) -> TaskStatusUpdate:
        return TaskStatusUpdate.from_task(self.load(task_id))

    def regenerate_task(self, task_id: str, action: str) -> Task:
        from .workflow import REGENERATION_ACTIONS

        if action not in REGENERATION_ACTIONS:
            raise UnsupportedRegenerationAction(action)
        with TASK_OPERATION_LOCK:
            task = self.load(task_id)
            return self._workflow().submit_review(task, action)

    def artifact_path(self, task_id: str, path: str = "") -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
            raise ValueError("无效任务 ID")
        base = self.root / task_id
        if base.resolve() != base:
            raise ValueError("任务目录不能指向其他位置")
        relative = Path(path)
        if relative.anchor or ".." in relative.parts:
            raise ValueError("产物路径必须是任务内相对路径")
        target = (base / relative).resolve()
        if not target.is_relative_to(base):
            raise ValueError("路径超出任务目录")
        return target

    def find_by_source_hash(self, sha256: str) -> list[str]:
        matches = []
        for path in sorted(self.root.glob("*/task.json")):
            task = self.load(path.parent.name)
            if task.source.sha256 == sha256:
                matches.append(task.task_id)
        return matches

    def list_tasks(self) -> list[Task]:
        """读取已经发布的任务。"""
        try:
            entries = sorted(self.root.iterdir())
        except FileNotFoundError:
            return []
        tasks = []
        for entry in entries:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", entry.name) or not entry.is_dir():
                continue
            try:
                task = self.load(entry.name)
                # 状态读取不能等待正在执行的流水线释放锁。
                if task.current_stage == "vectorize" and task.status == "running" and TASK_OPERATION_LOCK.acquire(blocking=False):
                    try:
                        task = self.load(entry.name)
                        if (
                            task.current_stage == "vectorize" and task.status == "running"
                            and (self.root, task.task_id) not in _ACTIVE_VECTOR_TASKS
                        ):
                            self._set_vector_stage(task, "failed", "上次向量生成已中断，可以重试")
                    finally:
                        TASK_OPERATION_LOCK.release()
                tasks.append(task)
            except FileNotFoundError:
                continue
        return tasks

    def create_task(self, source: Path, *, original_filename: str | None = None) -> Task:
        """按 PDF 内容创建任务，或返回已有任务。"""
        source = Path(source)
        if source.suffix.lower() != ".pdf":
            raise ValueError("输入必须为 PDF")
        digest = hash_file(source)
        with _TASK_CREATION_LOCK:
            matches = self.find_by_source_hash(digest)
            if len(matches) > 1:
                raise ValueError("存在多个相同来源的任务")
            if matches:
                return self.load(matches[0])
            now = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
            task = Task(
                task_id=f"task-{uuid.uuid4().hex}", created_at=now, updated_at=now,
                source=TaskSource(original_filename=original_filename or source.name, sha256=digest),
            )
            self._create(task, source)
            return task

    def _create(self, task: Task, source: Path) -> None:
        """在调用方持有创建锁时发布新任务目录。"""
        self.root.mkdir(parents=True, exist_ok=True)
        base = self.artifact_path(task.task_id)
        relative = self.artifact_path(task.task_id, task.source.copy_path).relative_to(base)
        if base.exists():
            raise FileExistsError(base)
        with tempfile.TemporaryDirectory(dir=self.root, prefix=".task-") as temporary:
            staged = Path(temporary) / "task"
            target = staged / relative
            target.parent.mkdir(parents=True)
            shutil.copyfile(source, target)
            if task.source.sha256 is not None and hash_file(target) != task.source.sha256:
                raise ValueError("源文件在复制时发生变化")
            (staged / "task.json").write_text(task.model_dump_json(indent=2), encoding="utf-8")
            staged.rename(base)

    def load(self, task_id: str) -> Task:
        task = Task.model_validate_json(self.read_artifact(task_id, "task.json"))
        if task.task_id != task_id:
            raise ValueError("任务文件 ID 与目录名称不一致")
        return task

    def save(self, task: Task) -> None:
        self._write_artifact(task.task_id, "task.json", task.model_dump_json(indent=2).encode("utf-8"))

    def archive_task(self, task_id: str) -> None:
        """从任务列表移除任务，保留任务目录供恢复。"""
        self._archive_task(task_id, restart=False)

    def restart_task(self, task_id: str) -> Task:
        """归档旧版本，使用同一个任务编号和原始 PDF 开始新一轮处理。"""
        return self._archive_task(task_id, restart=True)

    def _archive_task(self, task_id: str, *, restart: bool) -> Task:
        if not TASK_OPERATION_LOCK.acquire(blocking=False):
            raise ValueError("流水线正在处理任务，请稍后再试")
        try:
            with _TASK_CREATION_LOCK:
                task = self.load(task_id)
                if (self.root, task_id) in _ACTIVE_VECTOR_TASKS:
                    raise ValueError("任务正在生成向量，请稍后再试")
                if restart and task.paper_id is not None:
                    raise ValueError("已入库的任务不能重新执行")

                task_dir = self.artifact_path(task_id)
                source_path = self.artifact_path(task_id, task.source.copy_path).relative_to(task_dir)
                archive_root = self.root / ".task-archive"
                if archive_root.resolve() != archive_root:
                    raise ValueError("任务归档目录不能指向其他位置")
                archive_root.mkdir(exist_ok=True)
                archive = archive_root / f"{task_id}-{uuid.uuid4().hex}"
                task_dir.rename(archive)
                if restart:
                    try:
                        task = Task(
                            task_id=task_id, source=task.source, created_at=task.created_at,
                            updated_at=datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0),
                        )
                        self._create(task, archive / source_path)
                    except Exception:
                        if not task_dir.exists():
                            archive.rename(task_dir)
                        raise
                return task
        finally:
            TASK_OPERATION_LOCK.release()

    def ingest_task(self, task_id: str) -> str:
        """将已到审阅的任务产物交给正式库，保存编号及完成状态。"""
        from .stages import StageHandlers

        with TASK_OPERATION_LOCK:
            task = self.load(task_id)
            if task.paper_id is None and not task.can_ingest:
                raise ValueError("任务须到达审阅阶段才能入库")
            handlers = StageHandlers(self, papers_path=self.papers_path, taxonomy_path=self.taxonomy_path)
            paper_id = handlers.ingest(task, handlers.repo)
            if task.paper_id is None:
                task.paper_id = paper_id
                self._set_vector_stage(task, "pending")
                review = task.stages.setdefault("review", StageRecord())
                review.status = "completed"
                review.finished_at = review.finished_at or task.updated_at
                review.wait_reason = None
                review.error = None
                self.save(task)
            return paper_id

    def generate_vector(self, task_id: str) -> str:
        """调度向量阶段，并持久化任务状态。"""
        from .stages import StageHandlers, VectorGenerationError

        key = (self.root, task_id)
        with TASK_OPERATION_LOCK:
            task = self.load(task_id)
            if task.paper_id is None:
                raise ValueError("论文尚未入库")
            review = task.stages.get("review")
            if review is None or review.status != "completed":
                raise ValueError("审阅完成后才能生成向量")
            stage = task.stages.get("vectorize")
            if stage is None or (stage.status != "completed" and task.current_stage != "vectorize"):
                raise ValueError("任务尚未进入向量生成阶段")
            if key in _ACTIVE_VECTOR_TASKS:
                return "running"
            if stage.status == "completed":
                return "completed"
            self._set_vector_stage(task, "running")
            self.save(task)
            _ACTIVE_VECTOR_TASKS.add(key)

        status = "failed"
        failure_message = "向量生成失败，可以重试"
        try:
            handlers = StageHandlers(
                self, papers_path=self.papers_path, taxonomy_path=self.taxonomy_path,
            )
            handlers.execute("vectorize", task)
            status = "completed"
        except VectorGenerationError:
            pass
        except ValueError as error:
            failure_message = str(error)
            raise
        finally:
            with TASK_OPERATION_LOCK:
                try:
                    task = self.load(task_id)
                    self._set_vector_stage(task, status, failure_message)
                    self.save(task)
                finally:
                    _ACTIVE_VECTOR_TASKS.discard(key)
        return status

    @staticmethod
    def _set_vector_stage(task: Task, status: str, message: str | None = None) -> None:
        now = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
        stage = task.stages.setdefault("vectorize", StageRecord())
        task.current_stage = None if status == "completed" else "vectorize"
        task.status = status
        task.updated_at = now
        stage.status = status
        stage.error = {"code": "vector_failed", "message": message or "向量生成失败"} if status == "failed" else None
        if status == "running":
            stage.attempts += 1
            stage.started_at = now
            stage.finished_at = None
        elif status in ("completed", "failed"):
            stage.finished_at = now

    def read_artifact(self, task_id: str, path: str) -> bytes:
        """读取任务产物的原始字节。"""
        return self.artifact_path(task_id, path).read_bytes()

    def publish_artifacts(self, task_id: str, outputs: dict[str, str]) -> None:
        """逐个发布 UTF-8 文本产物。"""
        for path, content in outputs.items():
            self._write_artifact(task_id, path, content.encode("utf-8"))

    def publish_regeneration(
        self, task_id: str, outputs: dict[str, str], attempt: int, report_text: str,
    ) -> None:
        """归档旧草稿，发布新产物和校验报告，发布失败时恢复草稿。"""
        backups = {path: self._archive_artifact(task_id, path, attempt) for path in outputs}
        published = []
        try:
            for path, content in outputs.items():
                self._write_artifact(task_id, path, content.encode("utf-8"))
                published.append(path)
            self._write_artifact(task_id, "validation/report.json", report_text.encode("utf-8"))
        except Exception:
            for path in reversed(published):
                self._write_artifact(task_id, path, self.read_artifact(task_id, backups[path]))
            raise

    def _write_artifact(self, task_id: str, path: str, data: bytes) -> None:
        target = self.artifact_path(task_id, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".stage-", delete=False) as stream:
                staged = Path(stream.name)
                stream.write(data)
            os.replace(staged, target)
        except BaseException:
            if staged is not None:
                try:
                    staged.unlink(missing_ok=True)
                except OSError:
                    logger.warning("无法清理任务产物的临时文件", exc_info=True)
            raise

    def _archive_artifact(self, task_id: str, path: str, attempt: int) -> str:
        source = self.artifact_path(task_id, path)
        target = self.artifact_path(task_id, f"history/{attempt}/{path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(target)
        shutil.copyfile(source, target)
        return target.relative_to(self.artifact_path(task_id)).as_posix()
