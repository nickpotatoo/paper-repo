from typing import Literal, Protocol

from .model import LLMResult


class LLMClient(Protocol):
    def completion(
        self, sys_prompt: str, user_prompt: str, *,
        reasoning_effort: Literal["high", "medium", "low"] = "high",
        max_tokens: int | None = None,
    ) -> LLMResult:
        ...

    def completion_json(
        self, sys_prompt: str, user_prompt: str, *,
        reasoning_effort: Literal["high", "medium", "low"] = "high",
        max_tokens: int | None = None,
    ) -> LLMResult:
        ...
