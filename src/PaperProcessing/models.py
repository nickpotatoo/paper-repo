"""论文处理任务、审阅及校验模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


STAGES = (
    "prepare", "deduplicate", "extract", "metadata", "classify", "rough_summary",
    "detailed_summary", "validate", "review", "vectorize",
    "regenerate_metadata", "regenerate_classification",
    "regenerate_rough_summary", "regenerate_detailed_summary",
)
TaskStatus = Literal["pending", "running", "waiting", "failed", "completed", "duplicate", "cancelled"]
StageStatus = Literal["pending", "running", "waiting", "failed", "completed", "skipped"]


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

    @property
    def can_ingest(self) -> bool:
        return self.paper_id is None and (
            self.status == "completed" or (self.status == "waiting" and self.current_stage == "review")
        )


class TaskStatusUpdate(BaseModel):
    task_id: str
    status: TaskStatus
    current_stage: str | None
    stage_status: StageStatus | None = None
    updated_at: datetime
    message: str | None = None
    error: dict[str, str] | None = None
    wait_reason: str | None = None

    @classmethod
    def from_task(cls, task: Task) -> "TaskStatusUpdate":
        stage = task.stages.get(task.current_stage) if task.current_stage is not None else None
        return cls(
            task_id=task.task_id, status=task.status, current_stage=task.current_stage,
            stage_status=stage.status if stage else None, updated_at=task.updated_at,
            error=stage.error if stage else None, wait_reason=stage.wait_reason if stage else None,
        )


ReviewAction = Literal[
    "accept", "cancel", "regenerate_metadata",
    "regenerate_classification", "regenerate_rough_summary", "regenerate_detailed_summary",
]


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
