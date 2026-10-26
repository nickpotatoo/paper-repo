"""负责嵌入服务的 HTTP 请求、响应校验及连接管理。"""

import math

import httpx

from src.config import BGE_M3_API_KEY, BGE_M3_BASE_URL, BGE_M3_MODEL, EMBED_REQUEST_TIMEOUT_SECONDS


class EmbedClient:
    def __init__(self):
        if not BGE_M3_API_KEY:
            raise RuntimeError("BGE_M3_API_KEY is not set")
        self.client = httpx.Client(
            base_url=BGE_M3_BASE_URL,
            headers={"Authorization": f"Bearer {BGE_M3_API_KEY}"},
            timeout=EMBED_REQUEST_TIMEOUT_SECONDS,
        )
        self.model = BGE_M3_MODEL

    @property
    def is_closed(self) -> bool:
        return self.client.is_closed

    def _ensure_open(self) -> None:
        if self.is_closed:
            raise RuntimeError("EmbedClient 已关闭，请创建新的实例")

    def close(self) -> None:
        """关闭是终止操作；重复关闭安全，不隐式重新连接。"""
        if not self.is_closed:
            self.client.close()

    def __enter__(self) -> "EmbedClient":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._ensure_open()
        if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
            raise TypeError("texts 必须为字符串数组")
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("嵌入文本不能为空")
        resp = self.client.post(
            "/embeddings",
            json={"model": self.model, "input": texts},
        )
        resp.raise_for_status()
        return self._parse_embeddings(resp.json(), expected_count=len(texts))

    @staticmethod
    def _parse_embeddings(payload: dict, *, expected_count: int) -> list[list[float]]:
        """校验远程响应，并在存在索引时恢复输入顺序。"""
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("嵌入响应必须包含 data 数组")
        items = payload["data"]
        if len(items) != expected_count:
            raise ValueError("嵌入返回数量与输入数量不一致")
        if any(not isinstance(item, dict) for item in items):
            raise ValueError("嵌入响应条目必须为对象")
        has_indexes = ["index" in item for item in items]
        if any(has_indexes):
            if not all(has_indexes):
                raise ValueError("嵌入响应的 index 字段不完整")
            ordered = [None] * expected_count
            for item in items:
                index = item["index"]
                if type(index) is not int or not 0 <= index < expected_count or ordered[index] is not None:
                    raise ValueError("嵌入响应的 index 无效或重复")
                ordered[index] = item
            items = ordered
        vectors = []
        dimensions = None
        for item in items:
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise ValueError("embedding 必须为非空数值数组")
            values = []
            for value in vector:
                if type(value) not in (int, float):
                    raise ValueError("embedding 中存在非数值或布尔值")
                try:
                    number = float(value)
                except (ValueError, OverflowError) as error:
                    raise ValueError("embedding 中存在无法表示的数值") from error
                if not math.isfinite(number):
                    raise ValueError("embedding 中存在非有限数值")
                values.append(number)
            if dimensions is None:
                dimensions = len(values)
            elif len(values) != dimensions:
                raise ValueError("嵌入响应中向量维度不一致")
            vectors.append(values)
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
