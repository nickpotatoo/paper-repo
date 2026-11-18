"""论文处理任务及状态快照的数据模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


STAGES = ("prepare", "deduplicate", "extract", "metadata", "classify", "rough_summary", "detailed_summary", "validate", "review", "regenerate_classification", "regenerate_rough_summary", "regenerate_detailed_summary")
TaskStatus = Literal["pending", "running", "waiting", "failed", "completed", "duplicate", "cancelled"]
StageStatus = Literal["pending", "running", "waiting", "failed", "completed", "skipped"]
ReviewAction = Literal["accept", "regenerate_classification", "regenerate_rough_summary", "regenerate_detailed_summary", "cancel"]


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
    stages: dict[str, StageRecord] = Field(default_factory=lambda: {name: StageRecord() for name in STAGES})


class TaskStatusUpdate(BaseModel):
    task_id: str
    status: TaskStatus
    current_stage: str | None
    stage_status: StageStatus | None = None
    updated_at: datetime
    message: str | None = None
    error: dict[str, str] | None = None
    wait_reason: str | None = None


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
