"""Pure text splitting and context attachment; no IO or paper-specific fields."""

from src.config import CHUNK_SIZE, CHUNK_OVERLAP


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if not isinstance(text, str):
        raise TypeError("text 必须为字符串")
    if type(size) is not int or type(overlap) is not int:
        raise TypeError("size 和 overlap 必须为整数，不能是布尔值")
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("分块参数必须满足 size > 0 且 0 <= overlap < size")
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def build_embedding_inputs(
    text: str, *, context: str = "",
    size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Split the body first, then prepend the same opaque context to each chunk."""
    if not isinstance(context, str):
        raise TypeError("context 必须为字符串")
    chunks = chunk_text(text, size=size, overlap=overlap)
    return [f"{context}\n\n{chunk}" for chunk in chunks] if context else chunks
