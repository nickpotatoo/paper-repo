"""大语言模型调用结果。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMResult:
    content: str | dict[str, Any]
    model: str
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
