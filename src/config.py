"""项目统一配置。

修改后需重启服务。前端不读取本文件，重复写死在页面或 JavaScript 中的值须另行同步。
路径统一使用 Path。系统环境变量优先于下列 .env 文件，未提供环境变量时使用默认值。
本模块不创建 HTTP 客户端，也不导入 NumPy 或向量模块。
"""

import os
from pathlib import Path

# ── 项目位置与环境文件 ─────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
# 按顺序加载，均不覆盖已有变量；保留向量模块旧 .env 的加载位置。
ENV_FILES = (ROOT / ".env", ROOT / "src" / "semantic_search" / ".env")
try:
    from dotenv import load_dotenv
except ModuleNotFoundError as error:
    if error.name != "dotenv":
        raise
else:
    for env_file in ENV_FILES:
        load_dotenv(env_file, override=False)

# ── 资料与界面路径 ─────────────────────────────────────────────
DATA_DIR = ROOT / "data"
PAPERS_PATH = Path(os.environ.get("PAPERS_PATH") or DATA_DIR / "papers.json")
TAXONOMY_PATH = DATA_DIR / "taxonomy.json"
REPO_STATE_PATH = DATA_DIR / "repo_state.json"
PDFS_DIR = DATA_DIR / "pdfs"
DETAILED_SUMMARIES_DIR = Path(
    os.environ.get("DETAILED_SUMMARIES_DIR") or DATA_DIR / "detailed_summaries"
)
VIEWER_DIR = ROOT

# ── HTTP 服务与应用默认行为 ────────────────────────────────────
APP_TITLE = "Paper repo"            # FastAPI 应用名称，不控制 HTML 页面的标题。
SERVER_HOST = "0.0.0.0"             # 监听全部 IPv4 网卡；仅本机使用可改为 127.0.0.1。
SERVER_PORT = 5000                  # launch.py 的默认端口；命令行 --port 优先，0 为随机端口。
BROWSER_HOST = "127.0.0.1"          # 监听 0.0.0.0 时，浏览器使用的本机地址。
OPEN_BROWSER = True
AUTO_SHUTDOWN = True                # 默认启用无请求自动退出；保留 -s 参数关闭它的行为。
VALIDATE_REQUEST_DATA = True        # 请求时校验 JSON；启动时的关联校验始终执行。
IDLE_TIMEOUT_SECONDS = 600          # 无请求超时（秒）；前端心跳在 app.js 中独立写死为 30000 ms。
IDLE_CHECK_INTERVAL_SECONDS = 30    # 空闲检查周期；实际检查间隔不大于超时时长。
UVICORN_LOG_LEVEL = "warning"
UVICORN_ACCESS_LOG = False
HTTP_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}

# ── 语义检索请求限制 ────────────────────────────────────────────
SEARCH_MAX_REQUEST_BYTES = 32768    # JSON 请求正文上限，单位为字节。
# 前端 semantic-search.js 与 paper_viewer.html 的对应限制分别写死为 4000、1、100。
# 修改这些后端值不会自动更新前端，若需要界面一致，须同时调整这两个文件。
SEARCH_MAX_QUERY_CHARS = 4000       # 查询字符串上限，按 Python 字符数计算。
SEARCH_MIN_TOP_K = 1
SEARCH_MAX_TOP_K = 100
TOP_K = 5                          # 后端共用默认值；前端 HTML 的默认数量独立写死为 5。

# ── 嵌入服务 ───────────────────────────────────────────────────
BGE_M3_API_KEY = os.environ.get("BGE_M3_API_KEY", "")  # 留空不影响普通浏览，检索时才要求。
BGE_M3_BASE_URL = os.environ.get("BGE_M3_BASE_URL", "https://api.siliconflow.cn/v1")
BGE_M3_MODEL = "BAAI/bge-m3"
EMBED_REQUEST_TIMEOUT_SECONDS = 30.0  # HTTPX 超时时长，单位为秒。

# ── 向量分块、存储与计算 ────────────────────────────────────────
VECTOR_DATA_DIR = Path(os.environ.get("SEMANTIC_SEARCH_DATA_DIR") or DATA_DIR / "vectors")
# 每篇论文保存为 <paper_id>.json，包含 metadata 和各分块 text、vector，不再按行数分片。
CHUNK_SIZE = 512                    # 正文块的字符数，不含上下文前缀，也不是 token 数。
CHUNK_OVERLAP = 64                  # 相邻正文块重叠字符数；必须小于 CHUNK_SIZE。
VECTOR_DTYPE = "float64"            # 内存矩阵与查询向量的数据类型，保持原计算精度。
COSINE_EPSILON = 1e-10              # 余弦分母为零时的替代值；不改变非零分母。

# ── 文件哈希 ───────────────────────────────────────────────────
HASH_CHUNK_SIZE = 1024 * 1024       # 文件哈希每次读取 1 MiB，避免整份 PDF 进入内存。
