import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

BGE_M3_API_KEY = os.environ.get("BGE_M3_API_KEY", "")
BGE_M3_BASE_URL = os.environ.get("BGE_M3_BASE_URL", "https://api.siliconflow.cn/v1")
BGE_M3_MODEL = "BAAI/bge-m3"

DATA_DIR = os.environ.get("SEMANTIC_SEARCH_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))
VECTORS_PATH = os.environ.get("VECTORS_PATH", os.path.join(DATA_DIR, "vectors.jsonl"))

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
TOP_K = 5

PAPER_INDEX_PATH = os.environ.get("PAPER_INDEX_PATH", "")
PAPER_METHOD_DIR = os.environ.get("PAPER_METHOD_DIR", "")
