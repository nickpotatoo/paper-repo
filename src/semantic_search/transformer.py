import httpx

from src.config import BGE_M3_API_KEY, BGE_M3_BASE_URL, BGE_M3_MODEL


class Transformer:
    def __init__(self):
        if not BGE_M3_API_KEY:
            raise RuntimeError("BGE_M3_API_KEY is not set")
        self.client = httpx.Client(
            base_url=BGE_M3_BASE_URL,
            headers={"Authorization": f"Bearer {BGE_M3_API_KEY}"},
            timeout=30.0,
        )
        self.model = BGE_M3_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.post(
            "/embeddings",
            json={"model": self.model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
