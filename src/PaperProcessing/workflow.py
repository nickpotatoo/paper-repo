"""内存中的任务状态机。"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .models import (
    ANALYSIS_STAGES, FINISHED_STAGE, REGENERATION_STAGES, STAGES, USER_TASK_ACTIONS,
    StageRecord, StageResult, StateTransition, Task, TaskAction, TaskStatus, WorkflowEvent,
)

if TYPE_CHECKING:
    from .stages import StageHandlers

RECOVERABLE_STAGES = ("ingest", "vectorize")
RUNNABLE_STAGES = tuple(stage for stage in STAGES if stage not in ("review", FINISHED_STAGE))


def _workflow_transitions() -> dict[tuple[str | None, TaskStatus, WorkflowEvent], StateTransition]:
    accept = StateTransition("ingest", "pending", {"review": "completed", "ingest": "pending"})
    finished = StateTransition(FINISHED_STAGE, "finished", outcome="completed")
    rules: dict[tuple[str | None, TaskStatus, WorkflowEvent], StateTransition] = {
        ("review", "action_required", TaskAction.ACCEPT): accept,
        ("review", "action_required", TaskAction.CANCEL): StateTransition(
            None, "finished", {"review": "skipped"}, outcome="cancelled",
        ),
        ("deduplicate", "running", "duplicate"): StateTransition(
            None, "finished", {"deduplicate": "completed"}, outcome="duplicate",
        ),
        ("ingest", "running", "success"): StateTransition(
            "vectorize", "pending", {"ingest": "completed", "vectorize": "pending"},
        ),
        (FINISHED_STAGE, "finished", TaskAction.ACCEPT): finished,
        (FINISHED_STAGE, "finished", TaskAction.GENERATE_VECTOR): finished,
    }
    for stage, following in zip(ANALYSIS_STAGES, (*ANALYSIS_STAGES[1:], "review")):
        status = "action_required" if following == "review" else "pending"
        rules[stage, "running", "success"] = StateTransition(
            following, status, {stage: "completed", following: status},
            "等待用户审阅" if following == "review" else None,
        )
    for stage in RUNNABLE_STAGES:
        pending = StateTransition(stage, "pending", {stage: "pending"})
        failed = StateTransition(stage, "failed", {stage: "failed"})
        rules[stage, "pending", "start"] = StateTransition(stage, "running", {stage: "running"})
        rules[stage, "failed", TaskAction.RETRY] = pending
        if stage in RECOVERABLE_STAGES:
            rules[stage, "running", "interrupted"] = StateTransition(
                stage, "failed", {stage: "failed"}, error={
                    "code": "interrupted", "message": f"The {stage} stage was interrupted and can be retried.",
                },
            )
        else:
            rules[stage, "running", "interrupted"] = StateTransition(
                stage, "action_required", {stage: "action_required"}, "上次执行中断，请先核对产物",
            )
            rules[stage, "action_required", TaskAction.RESUME] = pending
        if stage in REGENERATION_STAGES:
            rules["review", "action_required", TaskAction(stage)] = pending
            rules[stage, "running", "success"] = StateTransition(
                "review", "action_required", {stage: "completed", "review": "action_required"}, "等待用户审阅",
            )
        if stage == "vectorize":
            rules[stage, "running", "success"] = StateTransition(
                FINISHED_STAGE, "finished", {stage: "completed", FINISHED_STAGE: "completed"},
                outcome="completed",
            )
            rules[stage, "pending", TaskAction.GENERATE_VECTOR] = pending
            for status in ("pending", "running", "failed"):
                rules[stage, status, TaskAction.ACCEPT] = StateTransition(stage, status)
        if stage == "ingest":
            rules[stage, "pending", TaskAction.ACCEPT] = pending
            rules[stage, "running", TaskAction.ACCEPT] = pending
        for status in ("pending", "failed", "action_required"):
            rules[stage, status, "startup_failure"] = failed
        rules[stage, "running", "failure"] = failed
    return rules


WORKFLOW_TRANSITIONS = _workflow_transitions()



class PaperWorkflow:
    def __init__(self, handlers: "StageHandlers"):
        self.handlers = handlers

    @staticmethod
    def next_state(stage: str | None, status: TaskStatus, event: WorkflowEvent) -> StateTransition:
        """按当前状态和事件查询下一状态。"""
        try:
            return WORKFLOW_TRANSITIONS[stage, status, event]
        except KeyError:
            raise ValueError(f"非法状态转移: {stage!r}, {status!r}, {event!r}") from None

    @staticmethod
    def can_restart(task: Task) -> bool:
        return task.paper_id is None

    @classmethod
    def allowed_actions(cls, task: Task) -> list[TaskAction]:
        """列出界面已有入口可执行的操作。"""
        actions: list[TaskAction] = []
        for action in USER_TASK_ACTIONS:
            if action == TaskAction.ARCHIVE:
                actions.append(action)
                continue
            if action == TaskAction.RESTART:
                if cls.can_restart(task):
                    actions.append(action)
                continue
            transition = WORKFLOW_TRANSITIONS.get((task.current_stage, task.status, action))
            if task.status != "running" and transition is not None and transition.stage_statuses:
                actions.append(action)
        return actions

    @staticmethod
    def apply_transition(task: Task, transition: StateTransition, *, error: Exception | None = None) -> None:
        """只更新内存中的任务及各阶段记录。"""
        task.current_stage, task.status, task.outcome = transition.stage, transition.status, transition.outcome
        now = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
        failure = transition.error if error is None else {"code": type(error).__name__, "message": str(error)}
        for stage, status in transition.stage_statuses.items():
            record = task.stages.setdefault(stage, StageRecord())
            record.status = status
            record.wait_reason = transition.wait_reason if status == "action_required" else None
            record.error = failure.copy() if status == "failed" and failure is not None else None
            if status == "pending":
                record.started_at = record.finished_at = None
            elif status == "running":
                record.attempts += 1
                record.started_at, record.finished_at = now, None
            elif status in ("completed", "failed", "skipped"):
                record.finished_at = (record.finished_at or now) if stage == "review" else now

    def run(self, task: Task, *, additional_prompt: str = "") -> tuple[Task, StageResult | None]:
        """执行一个阶段，返回转移后的任务和阶段产物。"""
        stage = task.current_stage
        if stage not in RUNNABLE_STAGES or task.status not in ("pending", "running"):
            return task, None

        updated = task.model_copy(deep=True)
        if updated.status == "pending":
            self.apply_transition(updated, self.next_state(stage, updated.status, "start"))
        try:
            result = self.handlers.execute(stage, updated, additional_prompt=additional_prompt)
            if any(not isinstance(content, str) or not content.strip() for content in result.artifacts.values()):
                raise ValueError("阶段产物为空或格式不正确")
        except Exception as error:
            result = StageResult(error=error)

        event: WorkflowEvent = "success"
        if result.error is not None:
            event = "failure"
        elif result.duplicate_of:
            updated.duplicate_of = result.duplicate_of
            event = "duplicate"
        self.apply_transition(updated, self.next_state(stage, updated.status, event), error=result.error)
        return updated, result
