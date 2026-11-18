"""基于大模型的论文内容生成。"""

import json

from src.LLMClient.interfaces import LLMClient
from src.LLMClient.deepseek import DeepSeekClient
from . import prompts


class LLMContentGenerator:
    """将论文内容交给注入的 LLM 客户端，返回阶段所需内容。"""

    def __init__(self, client: LLMClient | None = None):
        self.client = client if client is not None else DeepSeekClient()

    @staticmethod
    def _content(result, expected):
        if result.finish_reason != "stop":
            raise ValueError(f"模型输出未正常结束: {result.finish_reason}")
        content = result.content
        if not isinstance(content, expected) or not content:
            raise ValueError("模型输出为空或格式不正确")
        if isinstance(content, str) and not content.strip():
            raise ValueError("模型输出为空")
        return content

    @staticmethod
    def _text(text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("论文原文不能为空")
        return text

    def generate_metadata(self, text: str) -> dict:
        result = self.client.completion_json(prompts.METADATA, self._text(text))
        return self._content(result, dict)

    def generate_classification(self, text: str, taxonomy: dict) -> dict:
        if not isinstance(taxonomy, dict):
            raise TypeError("taxonomy 必须为字典")
        user_prompt = "现有 taxonomy JSON：\n" + json.dumps(taxonomy, ensure_ascii=False) + "\n\n论文原文：\n" + self._text(text)
        result = self.client.completion_json(prompts.CLASSIFICATION, user_prompt)
        return self._content(result, dict)

    def generate_rough_summary(self, text: str) -> str:
        return self._content(self.client.completion(prompts.ROUGH_SUMMARY, self._text(text)), str)

    def generate_detailed_summary(self, text: str) -> str:
        return self._content(self.client.completion(prompts.DETAILED_SUMMARY, self._text(text)), str)
