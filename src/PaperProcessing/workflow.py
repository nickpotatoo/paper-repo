"""任务状态流转与审阅入口。"""

import logging
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.hash_duplicate import hash_file
from .models import Task, TaskSource, TaskStatusUpdate
from .validation import validate_draft

_LOCK = threading.RLock()
_ORDER = ('prepare', 'deduplicate', 'extract', 'metadata', 'classify', 'rough_summary', 'detailed_summary', 'validate', 'review')
_REGEN = {'regenerate_classification': 'classify', 'regenerate_rough_summary': 'rough_summary', 'regenerate_detailed_summary': 'detailed_summary'}


def next_state(stage, status, event):
    """根据当前阶段、任务状态和事件返回 (下一阶段, 下一任务状态)。"""
    if event == 'interrupted' and status == 'running' and stage:
        return stage, 'waiting'
    if event == 'start' and status in ('pending', 'failed') and stage in _ORDER[:-1] + tuple(_REGEN):
        return stage, 'running'
    if event == 'duplicate' and status == 'running' and stage == 'deduplicate':
        return None, 'duplicate'
    if event == 'success' and status == 'running':
        if stage in _REGEN:
            return 'review', 'waiting'
        if stage in _ORDER[:-1]:
            following = _ORDER[_ORDER.index(stage) + 1]
            return following, 'waiting' if following == 'review' else 'running'
    if event == 'failure' and status == 'running':
        return ('review', 'waiting') if stage in _REGEN else (stage, 'failed')
    if stage == 'review' and status == 'waiting':
        if event == 'accept':
            return None, 'completed'
        if event == 'cancel':
            return None, 'cancelled'
        if event in _REGEN:
            return event, 'pending'
    raise ValueError(f'非法状态转移: {stage!r}, {status!r}, {event!r}')


def _now():
    return datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)


class PaperWorkflow:
    def __init__(self, storage, handlers, callback=None):
        self.storage, self.handlers, self.callback = storage, handlers, callback

    def _save(self, task):
        task.updated_at = _now()
        self.storage.save(task)
        if self.callback:
            try:
                self.callback(self._status(task))
            except Exception:
                logging.exception('任务状态回调失败')

    @staticmethod
    def _status(task):
        record = task.stages.get(task.current_stage)
        return TaskStatusUpdate(task_id=task.task_id, status=task.status, current_stage=task.current_stage, stage_status=record.status if record else None, updated_at=task.updated_at, error=record.error if record else None, wait_reason=record.wait_reason if record else None)

    def create_task(self, source: Path) -> Task:
        with _LOCK:
            source = Path(source)
            if source.suffix.lower() != '.pdf':
                raise ValueError('输入必须为 PDF')
            digest = hash_file(source)
            matches = self.storage.find_by_source_hash(digest)
            if len(matches) > 1:
                raise ValueError('存在多个相同来源的任务')
            if matches:
                return self.storage.load(matches[0])
            now = _now()
            task = Task(task_id='task-' + uuid.uuid4().hex, created_at=now, updated_at=now, source=TaskSource(original_filename=source.name, sha256=digest))
            self.storage.create(task, source)
            if hash_file(self.storage._path(task.task_id, task.source.copy_path)) != digest:
                raise ValueError('源文件在复制时发生变化')
            return task

    def get_status(self, task_id: str) -> TaskStatusUpdate:
        return self._status(self.storage.load(task_id))

    def _publish(self, task, path, text):
        staged = self.storage.stage_artifact(task.task_id, path, text.encode('utf-8'))
        self.storage.publish_artifact(task.task_id, staged, path)

    def _report(self, task):
        report = validate_draft(self.handlers.draft(task), self.handlers.taxonomy())
        self._publish(task, 'validation/report.json', report.model_dump_json(indent=2))
        return report

    def run(self, task_id: str) -> Task:
        with _LOCK:
            task = self.storage.load(task_id)
            print(f"Running task {task_id}, status: {task.status}, current_stage: {task.current_stage}")
            can_run = task.status not in ('completed', 'duplicate', 'cancelled', 'waiting') and task.current_stage != 'review'
            if can_run and task.status == 'running':
                task.current_stage, task.status = next_state(task.current_stage, task.status, 'interrupted')
                task.stages[task.current_stage].status = 'waiting'
                task.stages[task.current_stage].wait_reason = '上次执行中断，请先核对产物'
                self._save(task)
                can_run = False
            while can_run and task.current_stage:
                print(f"Running task {task_id}, status: {task.status}, current_stage: {task.current_stage}")
                stage = task.current_stage
                record = task.stages[stage]
                # 正常阶段衔接时任务已处于 running，阶段本身尚未启动。
                task.current_stage, task.status = next_state(stage, 'pending' if task.status == 'running' else task.status, 'start')
                record.status = 'running'
                record.attempts += 1
                record.started_at, record.finished_at, record.error, record.wait_reason = _now(), None, None, None
                self._save(task)
                try:
                    if stage == 'validate':
                        report = self._report(task)
                        record.artifacts = ['validation/report.json']
                        if report.has_blocking_issues:
                            raise ValueError('草稿校验未通过')
                    else:
                        actual = _REGEN.get(stage, stage)
                        outputs = self.handlers.execute(actual, task)
                        duplicate = outputs.pop('_duplicate', None)
                        if stage in _REGEN:
                            draft = self.handlers.draft(task)
                            key = {'classify': 'classification', 'rough_summary': 'rough_summary', 'detailed_summary': 'detailed_summary'}[actual]
                            content = next(iter(outputs.values()))
                            draft[key] = json.loads(content) if actual == 'classify' else content
                            report = validate_draft(draft, self.handlers.taxonomy())
                            if report.has_blocking_issues:
                                raise ValueError('重新生成的草稿校验未通过')
                        for path, content in outputs.items():
                            if not isinstance(content, str) or not content.strip():
                                raise ValueError(f'阶段产物为空: {path}')
                            if stage in _REGEN:
                                self.storage.archive_artifact(task_id, path, record.attempts)
                            self._publish(task, path, content)
                        record.artifacts = list(outputs)
                        if duplicate:
                            task.duplicate_of = duplicate
                            task.current_stage, task.status = next_state(stage, task.status, 'duplicate')
                            record.status, record.finished_at = 'completed', _now()
                            self._save(task)
                            break
                        if stage in _REGEN:
                            self._publish(task, 'validation/report.json', report.model_dump_json(indent=2))
                    record.status, record.finished_at = 'completed', _now()
                    task.current_stage, task.status = next_state(stage, task.status, 'success')
                    if task.current_stage == 'review':
                        task.stages['review'].status = 'waiting'
                        task.stages['review'].wait_reason = '等待用户审阅'
                        self._save(task)
                        break
                    self._save(task)
                except Exception as exc:
                    record.status, record.finished_at = 'failed', _now()
                    record.error = {'code': type(exc).__name__, 'message': str(exc)}
                    task.current_stage, task.status = next_state(stage, task.status, 'failure')
                    if stage in _REGEN:
                        task.stages['review'].status = 'waiting'
                        task.stages['review'].wait_reason = '重新生成失败，请检查结果'
                    self._save(task)
                    break
            return task

    def submit_review(self, task_id: str, action: str) -> Task:
        with _LOCK:
            task = self.storage.load(task_id)
            if task.status != 'waiting' or task.current_stage != 'review':
                raise ValueError('任务未处于审阅状态')
            if action == 'cancel':
                task.current_stage, task.status = next_state(task.current_stage, task.status, action)
            elif action == 'accept':
                if self._report(task).has_blocking_issues:
                    raise ValueError('草稿校验未通过')
                task.stages['review'].status, task.stages['review'].finished_at = 'completed', _now()
                task.current_stage, task.status = next_state(task.current_stage, task.status, action)
            elif action in _REGEN:
                task.current_stage, task.status = next_state(task.current_stage, task.status, action)
            else:
                raise ValueError('未知审阅操作')
            self._save(task)
            return self.run(task_id) if action in _REGEN else task
