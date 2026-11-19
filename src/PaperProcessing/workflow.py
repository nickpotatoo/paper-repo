"""任务状态流转与审阅入口。"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from .models import ReviewAction, Task
from .task_manager import TaskManager

_ORDER = ('prepare', 'deduplicate', 'extract', 'metadata', 'classify', 'rough_summary', 'detailed_summary', 'validate', 'review')
_REGEN = {
    'regenerate_metadata': 'metadata',
    'regenerate_classification': 'classify',
    'regenerate_rough_summary': 'rough_summary',
    'regenerate_detailed_summary': 'detailed_summary',
}
REGENERATION_ACTIONS = frozenset(_REGEN)


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
    def __init__(self, storage: TaskManager, handlers, *, on_transition: Callable[[Task], None]):
        self.storage = storage
        self.handlers = handlers
        self.on_transition = on_transition

    def _report(self, task):
        report = self.handlers.validate(task)
        self.storage.publish_artifacts(task.task_id, {'validation/report.json': report.model_dump_json(indent=2)})
        return report

    def run(self, task: Task, *, additional_prompt: str = "") -> Task:
        can_run = (
            task.status not in ('completed', 'duplicate', 'cancelled', 'waiting')
            and task.current_stage not in ('review', 'vectorize')
        )
        if can_run and task.status == 'running':
            task.current_stage, task.status = next_state(task.current_stage, task.status, 'interrupted')
            task.stages[task.current_stage].status = 'waiting'
            task.stages[task.current_stage].wait_reason = '上次执行中断，请先核对产物'
            self.on_transition(task)
            can_run = False
        while can_run and task.current_stage:
            stage = task.current_stage
            record = task.stages[stage]
            # 正常阶段衔接时任务已处于 running，阶段本身尚未启动。
            task.current_stage, task.status = next_state(stage, 'pending' if task.status == 'running' else task.status, 'start')
            record.status = 'running'
            record.attempts += 1
            record.started_at, record.finished_at, record.error, record.wait_reason = _now(), None, None, None
            self.on_transition(task)
            duplicate = None
            try:
                if stage == 'validate':
                    report = self._report(task)
                    record.artifacts = ['validation/report.json']
                    if report.has_blocking_issues:
                        raise ValueError('草稿校验未通过')
                else:
                    actual = _REGEN.get(stage, stage)
                    if stage in _REGEN and additional_prompt:
                        outputs = self.handlers.execute(actual, task, additional_prompt=additional_prompt)
                    else:
                        outputs = self.handlers.execute(actual, task)
                    duplicate = outputs.pop('_duplicate', None)
                    for path, content in outputs.items():
                        if not isinstance(content, str) or not content.strip():
                            raise ValueError(f'阶段产物为空: {path}')
                    if stage in _REGEN:
                        report = self.handlers.validate(task, replacements=outputs)
                        if report.has_blocking_issues:
                            raise ValueError('重新生成的草稿校验未通过')
                        self.storage.publish_regeneration(
                            task.task_id, outputs, record.attempts, report.model_dump_json(indent=2),
                        )
                    else:
                        self.storage.publish_artifacts(task.task_id, outputs)
                    record.artifacts = list(outputs)
            except Exception as exc:
                record.status, record.finished_at = 'failed', _now()
                record.error = {'code': type(exc).__name__, 'message': str(exc)}
                task.current_stage, task.status = next_state(stage, task.status, 'failure')
                if stage in _REGEN:
                    task.stages['review'].status = 'waiting'
                    task.stages['review'].wait_reason = '重新生成失败，请检查结果'
                self.on_transition(task)
                break
            record.status, record.finished_at = 'completed', _now()
            if duplicate:
                task.duplicate_of = duplicate
            event = 'duplicate' if duplicate else 'success'
            task.current_stage, task.status = next_state(stage, task.status, event)
            if task.current_stage == 'review':
                task.stages['review'].status = 'waiting'
                task.stages['review'].wait_reason = '等待用户审阅'
            self.on_transition(task)
            if duplicate or task.current_stage == 'review':
                break
        return task

    def submit_review(self, task: Task, action: ReviewAction, *, additional_prompt: str = "") -> Task:
        if task.paper_id is not None or task.status != 'waiting' or task.current_stage != 'review':
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
        self.on_transition(task)
        return self.run(task, additional_prompt=additional_prompt) if action in _REGEN else task
