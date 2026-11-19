"""内存中的任务状态机。"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .models import (
    ANALYSIS_STAGES, FINISHED_STAGE, REGENERATION_STAGES, STAGES, USER_TASK_ACTIONS, VECTOR_STAGES,
    StageRecord, StageResult, StateTransition, Task, TaskAction, TaskStatus, WorkflowEvent,
)

if TYPE_CHECKING:
    from .stages import StageHandlers

RECOVERABLE_STAGES = ("ingest", *VECTOR_STAGES)
RUNNABLE_STAGES = tuple(stage for stage in STAGES if stage not in ("review", FINISHED_STAGE))


def _workflow_transitions() -> dict[tuple[str | None, TaskStatus, WorkflowEvent], StateTransition]:
    accept = StateTransition("ingest", "pending", {"review": "completed", "ingest": "pending"})
    retry_vector = StateTransition("retry_vectorize", "pending", {"retry_vectorize": "pending"})
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
    }
    for stage, following in zip(ANALYSIS_STAGES, (*ANALYSIS_STAGES[1:], "review")):
        status = "action_required" if following == "review" else "pending"
        rules[stage, "running", "success"] = StateTransition(
            following, status, {stage: "completed", following: status},
            "等待用户审阅" if following == "review" else None,
        )
    for stage in RUNNABLE_STAGES:
        pending = StateTransition(stage, "pending", {stage: "pending"})
        failure_status = "action_required" if stage in RECOVERABLE_STAGES else "failed"
        failed = StateTransition(stage, failure_status, {stage: "failed"})
        rules[stage, "pending", "start"] = StateTransition(stage, "running", {stage: "running"})
        retry = retry_vector if stage in VECTOR_STAGES else pending
        rules[stage, failure_status, TaskAction.RESUME] = retry
        rules[stage, failure_status, TaskAction.RETRY] = retry
        if stage in RECOVERABLE_STAGES:
            rules[stage, "running", "interrupted"] = StateTransition(
                stage, "action_required", {stage: "failed"}, error={
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
            failed = StateTransition(
                "review", "action_required", {stage: "failed", "review": "action_required"}, "重新生成失败，请检查结果",
            )
        if stage in VECTOR_STAGES:
            rules[stage, "running", "success"] = StateTransition(
                FINISHED_STAGE, "finished", {stage: "completed", FINISHED_STAGE: "completed"},
                outcome="completed",
            )
            rules[stage, "pending", TaskAction.GENERATE_VECTOR] = pending
            rules[stage, "action_required", TaskAction.GENERATE_VECTOR] = retry_vector
        if stage == "ingest":
            rules[stage, "pending", TaskAction.ACCEPT] = pending
            rules[stage, "action_required", TaskAction.ACCEPT] = pending
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

    @classmethod
    def can_ingest(cls, task: Task) -> bool:
        return TaskAction.ACCEPT in cls.allowed_actions(task)

    @staticmethod
    def can_restart(task: Task) -> bool:
        return task.paper_id is None

    @staticmethod
    def _vector_block_reason(task: Task) -> str | None:
        if task.paper_id is None:
            return "论文尚未入库"
        review = task.stages.get("review")
        if review is None or review.status != "completed":
            return "审阅完成后才能生成向量"
        ingest = task.stages.get("ingest")
        if ingest is None or ingest.status != "completed":
            return "入库完成后才能生成向量"
        return None

    @classmethod
    def retryable_stages(cls, task: Task) -> list[str]:
        stage = task.current_stage
        record = task.stages.get(stage) if stage is not None else None
        if stage is not None and record is not None and record.status == "failed" and (
            stage, task.status, TaskAction.RETRY
        ) in WORKFLOW_TRANSITIONS:
            if stage in VECTOR_STAGES and cls._vector_block_reason(task) is not None:
                return []
            if stage == "ingest" and task.paper_id is not None:
                return []
            return [stage]
        if stage == "review" and task.status == "action_required" and task.paper_id is None:
            return [
                name for name in REGENERATION_STAGES
                if (record := task.stages.get(name)) is not None and record.status == "failed"
            ]
        return []

    @classmethod
    def allowed_actions(cls, task: Task) -> list[TaskAction]:
        """列出界面已有入口可执行的操作。"""
        actions: list[TaskAction] = []
        for action in USER_TASK_ACTIONS:
            if action == TaskAction.RETRY:
                if cls.retryable_stages(task):
                    actions.append(action)
                continue
            if action == TaskAction.ARCHIVE:
                actions.append(action)
                continue
            if action == TaskAction.RESTART:
                if cls.can_restart(task):
                    actions.append(action)
                continue
            if (task.current_stage, task.status, action) not in WORKFLOW_TRANSITIONS:
                continue
            if action == TaskAction.GENERATE_VECTOR:
                if cls._vector_block_reason(task) is not None:
                    continue
            elif task.paper_id is not None:
                continue
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

    @classmethod
    def submit_action(cls, task: Task, action: TaskAction, *, retry_stage: str | None = None) -> Task:
        """计算外部操作后的任务状态，留待调用方执行。"""
        if action == TaskAction.RETRY:
            stages = cls.retryable_stages(task)
            if retry_stage is None and len(stages) == 1:
                retry_stage = stages[0]
            if retry_stage not in stages:
                raise ValueError("请选择可重试的失败阶段")
            if task.current_stage == "review":
                action = TaskAction(retry_stage)
        if action == TaskAction.ACCEPT and task.paper_id is not None:
            return task
        if action == TaskAction.GENERATE_VECTOR:
            reason = cls._vector_block_reason(task)
            if reason is not None:
                raise ValueError(reason)
            if task.status == "finished" and task.outcome == "completed":
                return task

        updated = task.model_copy(deep=True)
        if updated.status == "running" and (
            (action == TaskAction.ACCEPT and updated.current_stage == "ingest")
            or (action == TaskAction.GENERATE_VECTOR and updated.current_stage in VECTOR_STAGES)
        ):
            cls.apply_transition(updated, cls.next_state(updated.current_stage, updated.status, "interrupted"))
        cls.apply_transition(updated, cls.next_state(updated.current_stage, updated.status, action))
        return updated

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
