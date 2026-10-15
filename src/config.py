"""Repo 路径和向量检索的统一配置；路径配置均为 Path。"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 系统环境变量优先，其次为统一配置旁的 .env，最后兼容原向量模块的 .env。
# 未安装 python-dotenv 时仍可通过系统环境变量配置，不影响普通资料浏览。
try:
    from dotenv import load_dotenv
except ModuleNotFoundError as error:
    if error.name != "dotenv":
        raise
else:
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    load_dotenv(Path(__file__).parent / "semantic_search" / ".env", override=False)

DATA_DIR = ROOT / "data"
PAPERS_PATH = Path(os.environ.get("PAPERS_PATH") or DATA_DIR / "papers.json")
TAXONOMY_PATH = DATA_DIR / "taxonomy.json"
REPO_STATE_PATH = DATA_DIR / "repo_state.json"
PDFS_DIR = DATA_DIR / "pdfs"
DETAILED_SUMMARIES_DIR = Path(os.environ.get("DETAILED_SUMMARIES_DIR") or DATA_DIR / "detailed_summaries")
VIEWER_DIR = ROOT

VECTOR_DATA_DIR = Path(os.environ.get("SEMANTIC_SEARCH_DATA_DIR") or DATA_DIR / "vectors")
VECTOR_MAX_ROWS = 500

BGE_M3_API_KEY = os.environ.get("BGE_M3_API_KEY", "")
BGE_M3_BASE_URL = os.environ.get("BGE_M3_BASE_URL", "https://api.siliconflow.cn/v1")
BGE_M3_MODEL = "BAAI/bge-m3"

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
TOP_K = 5
