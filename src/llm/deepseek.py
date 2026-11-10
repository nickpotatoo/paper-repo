import json
from typing import Literal

from openai import OpenAI

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_TYPE
from .interfaces import LLMClient
from .model import LLMResult


class DeepSeekClient(LLMClient):
    def __init__(self):
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL
        )

    def completion(
        self, sys_prompt: str, user_prompt: str, *,
        reasoning_effort: Literal["high", "medium", "low"] = "high",
        max_tokens: int | None = None,
    ) -> LLMResult:
        """生成文本结果。"""
        return self._completion(sys_prompt, user_prompt, reasoning_effort, max_tokens, False)

    def completion_json(
        self, sys_prompt: str, user_prompt: str, *,
        reasoning_effort: Literal["high", "medium", "low"] = "high",
        max_tokens: int | None = None,
    ) -> LLMResult:
        """生成 JSON 对象；提示词须含 json，建议提供期望格式示例。"""
        if "json" not in sys_prompt.lower() and "json" not in user_prompt.lower():
            raise ValueError("JSON 模式要求提示词包含 json 并描述期望格式")
        return self._completion(sys_prompt, user_prompt, reasoning_effort, max_tokens, True)

    def _completion(
        self, sys_prompt: str, user_prompt: str,
        reasoning_effort: Literal["high", "medium", "low"],
        max_tokens: int | None, json_output: bool,
    ) -> LLMResult:
        response = self.client.chat.completions.create(
            model=DEEPSEEK_MODEL_TYPE,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
            reasoning_effort=reasoning_effort,
            extra_body={"thinking": {"type": "enabled"}},
            response_format={"type": "json_object"} if json_output else {"type": "text"},
            max_tokens=max_tokens,
        )

        if not response.choices:
            raise ValueError("模型响应未包含候选结果")
        choice = response.choices[0]
        content = choice.message.content
        if not content or not content.strip():
            raise ValueError("模型响应未包含文本内容")
        if json_output:
            if choice.finish_reason == "length":
                raise ValueError("JSON 输出被截断，请调整 max_tokens 或输入长度")
            content = json.loads(content)
            if not isinstance(content, dict):
                raise ValueError("JSON 输出必须是对象")
        usage = response.usage
        return LLMResult(
            content=content, model=response.model, finish_reason=choice.finish_reason,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
        )
