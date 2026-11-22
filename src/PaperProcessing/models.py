"""论文处理任务、审阅及校验模型。"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ANALYSIS_STAGES = (
    "prepare", "deduplicate", "extract", "metadata", "classify",
    "rough_summary", "detailed_summary", "validate",
)
class TaskAction(str, Enum):
    """任务入口接受的动作。内部阶段事件另见 WorkflowEvent。"""

    # 待审阅时进入对应的重生成阶段，成功后回到审阅。
    REGENERATE_METADATA = "regenerate_metadata"
    REGENERATE_CLASSIFICATION = "regenerate_classification"
    REGENERATE_ROUGH_SUMMARY = "regenerate_rough_summary"
    REGENERATE_DETAILED_SUMMARY = "regenerate_detailed_summary"

    # 完成审阅并进入入库。
    ACCEPT = "accept"
    # 正式入库完成后启动向量生成。
    GENERATE_VECTOR = "generate_vector"
    # 工作流内部入口：取消待审阅任务，或恢复等待核对的中断阶段。
    CANCEL = "cancel"
    RESUME = "resume"
    # 用户入口：重试当前失败阶段。
    RETRY = "retry"
    # 任务管理入口：从头重跑，或归档并移出任务列表。
    RESTART = "restart"
    ARCHIVE = "archive"


REGENERATION_ACTIONS = (
    TaskAction.REGENERATE_METADATA, TaskAction.REGENERATE_CLASSIFICATION,
    TaskAction.REGENERATE_ROUGH_SUMMARY, TaskAction.REGENERATE_DETAILED_SUMMARY,
)
REGENERATION_STAGES = tuple(action.value for action in REGENERATION_ACTIONS)
USER_TASK_ACTIONS = (
    TaskAction.ACCEPT, *REGENERATION_ACTIONS, TaskAction.GENERATE_VECTOR,
    TaskAction.RETRY, TaskAction.RESTART, TaskAction.ARCHIVE,
)
WorkflowEvent = TaskAction | Literal["start", "success", "failure", "startup_failure", "interrupted", "duplicate"]
FINISHED_STAGE = "finished"
STAGES = (*ANALYSIS_STAGES, "review", "ingest", "vectorize", *REGENERATION_STAGES, FINISHED_STAGE)
TaskStatus = Literal["pending", "running", "action_required", "failed", "finished"]
TaskOutcome = Literal["completed", "duplicate", "cancelled"]
StageStatus = Literal["pending", "running", "action_required", "failed", "completed", "skipped"]


@dataclass(frozen=True)
class StateTransition:
    stage: str | None
    status: TaskStatus
    stage_statuses: dict[str, StageStatus] = field(default_factory=dict)
    wait_reason: str | None = None
    error: dict[str, str] | None = None
    outcome: TaskOutcome | None = None


@dataclass(frozen=True)
class IngestDraft:
    source: Path
    sha256: str
    original_filename: str
    metadata: dict
    classification: dict
    summary: str
    detailed_summary: str
    extracted_markdown: str


@dataclass
class StageResult:
    artifacts: dict[str, str] = field(default_factory=dict)
    duplicate_of: str | None = None
    pending_taxonomy: dict | None = None
    ingest: IngestDraft | None = None
    error: Exception | None = None


class StageRecord(BaseModel):
    status: StageStatus = "pending"
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    artifacts: list[str] = Field(default_factory=list)
    error: dict[str, str] | None = None
    wait_reason: str | None = None


class TaskSource(BaseModel):
    original_filename: str
    copy_path: str = "input/source.pdf"
    sha256: str | None = None


class Task(BaseModel):
    task_id: str
    status: TaskStatus = "pending"
    outcome: TaskOutcome | None = None
    current_stage: str | None = "prepare"
    created_at: datetime
    updated_at: datetime
    source: TaskSource
    duplicate_of: str | None = None
    paper_id: str | None = None
    stages: dict[str, StageRecord] = Field(default_factory=lambda: {name: StageRecord() for name in STAGES})

    @field_validator("paper_id", mode="before")
    @classmethod
    def normalize_paper_id(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class TaskStatusUpdate(BaseModel):
    task_id: str
    status: TaskStatus
    current_stage: str | None
    outcome: TaskOutcome | None = None
    stage_status: StageStatus | None = None
    updated_at: datetime
    message: str | None = None
    error: dict[str, str] | None = None
    wait_reason: str | None = None

    @classmethod
    def from_task(cls, task: Task) -> "TaskStatusUpdate":
        stage = task.stages.get(task.current_stage) if task.current_stage is not None else None
        return cls(
            task_id=task.task_id, status=task.status, outcome=task.outcome, current_stage=task.current_stage,
            stage_status=stage.status if stage else None, updated_at=task.updated_at,
            error=stage.error if stage else None, wait_reason=stage.wait_reason if stage else None,
        )


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "error"
    field: str | None = None


class ValidationReport(BaseModel):
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def has_blocking_issues(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)
