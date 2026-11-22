"""任务运行入口及任务文件管理。"""

import json
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

from src.config import PAPERS_PATH, REPO_STATE_PATH, TAXONOMY_PATH
from src.RepoManager import RepoManager
from src.hash_duplicate import hash_file
from . import taxonomy_buffer
from .models import (
    REGENERATION_STAGES,
    StageResult, Task, TaskAction, TaskSource, TaskStatusUpdate,
)
from .validation import VALIDATION_ARTIFACT
from .workflow import RUNNABLE_STAGES, PaperWorkflow


_TASK_OPERATION_LOCK = threading.RLock()
_TASK_CREATION_LOCK = threading.RLock()
logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(
        self, root: Path, *, create_root: bool = True,
        papers_path: Path | None = None, taxonomy_path: Path | None = None,
        state_path: Path | None = None,
        callback: Callable[[TaskStatusUpdate], None] | None = None,
    ):
        self.root = Path(root).resolve()
        self.repo = RepoManager(
            papers_path=PAPERS_PATH if papers_path is None else papers_path,
            taxonomy_path=TAXONOMY_PATH if taxonomy_path is None else taxonomy_path,
            state_path=REPO_STATE_PATH if state_path is None else state_path,
        )
        self.callback = callback
        if create_root:
            self.root.mkdir(parents=True, exist_ok=True)

    def create_task(self, source: Path, *, original_filename: str | None = None) -> Task:
        """按 PDF 内容创建任务，或返回已有任务。"""
        source = Path(source)
        if source.suffix.lower() != ".pdf":
            raise ValueError("输入必须为 PDF")
        digest = hash_file(source)
        with _TASK_CREATION_LOCK:
            matches = [
                task for path in sorted(self.root.glob("*/task.json"))
                if re.fullmatch(r"[A-Za-z0-9_-]+", path.parent.name)
                and (task := self.get_task(path.parent.name)).source.sha256 == digest
            ]
            if len(matches) > 1:
                raise ValueError("存在多个相同来源的任务")
            if matches:
                return matches[0]
            now = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
            task = Task(
                task_id=f"task-{uuid.uuid4().hex}", created_at=now, updated_at=now,
                source=TaskSource(original_filename=original_filename or source.name, sha256=digest),
            )
            self._create(task, source)
            return task

    def run_task(
        self, task_id: str, *, additional_prompt: str = "",
        stop_before: str | None = None, raise_on_error_at: str | None = None,
    ) -> Task:
        """执行已排队的阶段，直到需要操作、失败、结束或到达指定阶段。"""
        with _TASK_OPERATION_LOCK:
            task = self.get_task(task_id)
            if task.current_stage not in RUNNABLE_STAGES:
                return task
            if task.status == "running":
                transition = PaperWorkflow.next_state(task.current_stage, task.status, "interrupted")
                PaperWorkflow.apply_transition(task, transition)
                self._save_task(task)
                return task
            if task.status != "pending" or task.current_stage == stop_before:
                return task

            try:
                from .stages import StageHandlers

                workflow = PaperWorkflow(StageHandlers(self, self.repo))
            except (ImportError, OSError, RuntimeError) as error:
                logger.warning("任务工作流启动失败：%s", type(error).__name__)
                stage = task.current_stage
                transition = PaperWorkflow.next_state(stage, task.status, "startup_failure")
                PaperWorkflow.apply_transition(task, transition, error=error)
                self._save_task(task)
                if stage == raise_on_error_at:
                    raise
                return task

            while task.status == "pending" and task.current_stage in RUNNABLE_STAGES:
                stage = task.current_stage
                if stage == stop_before:
                    break
                workflow.apply_transition(task, workflow.next_state(stage, task.status, "start"))
                self._save_task(task)
                updated, result = workflow.run(task, additional_prompt=additional_prompt)
                if result is None:
                    raise RuntimeError(f"阶段未返回结果: {stage}")
                error = result.error
                try:
                    self._publish_stage_result(updated, stage, result)
                except Exception as publish_error:
                    error = publish_error
                    workflow.apply_transition(task, workflow.next_state(stage, task.status, "failure"), error=error)
                else:
                    task = updated
                self._save_task(task)
                if error is not None:
                    if stage == raise_on_error_at:
                        raise error
                    break
            return task

    def submit_action_to_task(
        self, task_id: str, action: TaskAction | str, *,
        additional_prompt: str = "", stop_before: str | None = None,
    ) -> Task:
        """提交工作流动作，保存状态，再接着运行任务。"""
        action = TaskAction(action)
        with _TASK_OPERATION_LOCK:
            task = self.get_task(task_id)
            if action == TaskAction.ACCEPT and task.paper_id is not None:
                try:
                    self.repo.get_paper(task.paper_id)
                except KeyError:
                    raise ValueError("该任务关联的论文已从资料库移除") from None
            transition = PaperWorkflow.next_state(task.current_stage, task.status, action)
            if not transition.stage_statuses:
                return task
            PaperWorkflow.apply_transition(task, transition)
            self._save_task(task)
            return self.run_task(
                task_id, additional_prompt=additional_prompt, stop_before=stop_before,
                raise_on_error_at="ingest" if action == TaskAction.ACCEPT else None,
            )

    def _publish_stage_result(self, task: Task, stage: str, result: StageResult) -> None:
        if result.error is not None and stage != "validate":
            return
        if result.ingest is not None:
            draft = result.ingest
            task.paper_id = self.repo.ingest_paper(
                draft.source, sha256=draft.sha256, original_filename=draft.original_filename,
                metadata=draft.metadata, classification=draft.classification,
                summary=draft.summary, detailed_summary=draft.detailed_summary,
                extracted_markdown=draft.extracted_markdown,
            )
            self._promote_classification_ids(self.repo.get_taxonomy())
        if result.pending_taxonomy is not None:
            self._write_classification_buffer(result.pending_taxonomy)
        if not result.artifacts:
            return
        record = task.stages[stage]
        if stage in REGENERATION_STAGES:
            outputs = dict(result.artifacts)
            report = outputs.pop(VALIDATION_ARTIFACT)
            self._publish_regeneration(task.task_id, outputs, record.attempts, report)
            record.artifacts = list(outputs)
        else:
            for path, content in result.artifacts.items():
                self._write_artifact(task.task_id, path, content.encode("utf-8"))
            record.artifacts = list(result.artifacts)

    @staticmethod
    def allowed_actions(task: Task) -> list[TaskAction]:
        return PaperWorkflow.allowed_actions(task)

    def retry_task(self, task_id: str) -> tuple[Task, str]:
        with _TASK_OPERATION_LOCK:
            task = self.get_task(task_id)
            if task.status == "running":
                task = self.run_task(task_id)
            stage = task.current_stage
            if stage is None:
                raise ValueError("当前任务没有可重试阶段")
            task = self.submit_action_to_task(
                task_id, TaskAction.RETRY, stop_before="vectorize" if stage == "ingest" else None,
            )
            return task, stage

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
                task = self.get_task(entry.name)
                # 状态读取不能等待正在执行的流水线释放锁。
                if (
                    task.current_stage in RUNNABLE_STAGES
                    and task.status == "running"
                    and _TASK_OPERATION_LOCK.acquire(blocking=False)
                ):
                    try:
                        task = self.get_task(entry.name)
                        if task.current_stage in RUNNABLE_STAGES and task.status == "running":
                            transition = PaperWorkflow.next_state(task.current_stage, task.status, "interrupted")
                            PaperWorkflow.apply_transition(task, transition)
                    finally:
                        _TASK_OPERATION_LOCK.release()
                tasks.append(task)
            except FileNotFoundError:
                continue
        return tasks

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

    def get_task(self, task_id: str) -> Task:
        task = Task.model_validate_json(self.read_artifact(task_id, "task.json"))
        if task.task_id != task_id:
            raise ValueError("任务文件 ID 与目录名称不一致")
        return task

    def _save_task(self, task: Task) -> None:
        task.updated_at = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
        self._write_artifact(task.task_id, "task.json", task.model_dump_json(indent=2).encode("utf-8"))
        if self.callback is not None:
            try:
                self.callback(TaskStatusUpdate.from_task(task))
            except Exception:
                logger.exception("任务状态回调失败")

    def archive_task(self, task_id: str) -> None:
        """从任务列表移除任务，保留任务目录供恢复。"""
        self._archive_task(task_id, restart=False)

    def restart_task(self, task_id: str) -> Task:
        """归档旧版本，使用同一个任务编号和原始 PDF 开始新一轮处理。"""
        return self._archive_task(task_id, restart=True)

    def _archive_task(self, task_id: str, *, restart: bool) -> Task:
        if not _TASK_OPERATION_LOCK.acquire(blocking=False):
            raise ValueError("流水线正在处理任务，请稍后再试")
        try:
            with _TASK_CREATION_LOCK:
                task = self.get_task(task_id)
                if restart and not PaperWorkflow.can_restart(task):
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
            _TASK_OPERATION_LOCK.release()

    def read_classification_buffer(self) -> dict:
        path = self.root / taxonomy_buffer.BUFFER_FILENAME
        if path.resolve() != path:
            raise ValueError("分类缓冲文件不能指向其他位置")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return taxonomy_buffer.empty_buffer()

    def _promote_classification_ids(self, taxonomy: dict) -> None:
        pending = self.read_classification_buffer()
        promoted, remaining = taxonomy_buffer.partition_registered_ids(pending, taxonomy)
        if not promoted:
            return

        for path in sorted(self.root.glob("*/task.json")):
            task_id = path.parent.name
            if not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
                continue
            artifact = taxonomy_buffer.CLASSIFICATION_ARTIFACT
            try:
                draft = json.loads(self.read_artifact(task_id, artifact))
            except (FileNotFoundError, UnicodeError, json.JSONDecodeError):
                continue
            updated = taxonomy_buffer.replace_registered_ids(draft, promoted, remaining)
            if updated != draft:
                self._write_artifact(task_id, artifact, self._json_bytes(updated))

        # 保留映射来源直到全部任务都改写成功，供入库重试。
        self._write_classification_buffer(remaining)

    def _write_classification_buffer(self, pending: dict) -> None:
        self._write_file(self.root / taxonomy_buffer.BUFFER_FILENAME, self._json_bytes(pending))

    @staticmethod
    def _json_bytes(data: dict) -> bytes:
        return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    def read_artifact(self, task_id: str, path: str) -> bytes:
        """读取任务产物的原始字节。"""
        return self.artifact_path(task_id, path).read_bytes()

    def _publish_regeneration(
        self, task_id: str, outputs: dict[str, str], attempt: int, report_text: str,
    ) -> None:
        """归档旧草稿，发布新产物和校验报告，发布失败时恢复草稿。"""
        backups = {path: self._archive_artifact(task_id, path, attempt) for path in outputs}
        published = []
        try:
            for path, content in outputs.items():
                self._write_artifact(task_id, path, content.encode("utf-8"))
                published.append(path)
            self._write_artifact(task_id, VALIDATION_ARTIFACT, report_text.encode("utf-8"))
        except Exception:
            for path in reversed(published):
                self._write_artifact(task_id, path, self.read_artifact(task_id, backups[path]))
            raise

    def _write_artifact(self, task_id: str, path: str, data: bytes) -> None:
        self._write_file(self.artifact_path(task_id, path), data)

    @staticmethod
    def _write_file(target: Path, data: bytes) -> None:
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
