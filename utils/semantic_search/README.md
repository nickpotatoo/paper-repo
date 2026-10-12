# 论文库向量检索接入

查看器的“向量检索”按钮打开搜索框，提交后由 `paper_server.py` 调用 `SSBridge.retrieve(query, top_k)`。返回的 `paper_id` 列表用于按检索顺序展示论文卡片；重复编号只保留第一次出现。结果仍支持单击查看方法文档、双击打开 PDF，以及按关键词和分类进一步筛选。“返回全部论文”退出检索结果。

## 环境与向量文件

运行检索的 Python 环境需要 `numpy` 和 `httpx`，并通过环境变量配置 `BGE_M3_API_KEY`。可选配置包括 `BGE_M3_BASE_URL`、`VECTORS_PATH` 和 `SEMANTIC_SEARCH_DATA_DIR`。默认向量文件为当前索引目录下的 `data/vectors.jsonl`。

服务端首次搜索时才初始化 SSBridge，并传入当前 JSON 与 methods 目录。检索读取已有向量，不会自动创建向量；没有向量文件时返回空结果。需要预先使用 SSBridge 的 `create_vector()` 建立向量，例如在项目根目录运行自己的 Python 脚本：

```python
from pathlib import Path
from utils.semantic_search.bridge import SSBridge

root = Path.cwd()
bridge = SSBridge(
    paper_index_path=root / "paper_index.json",
    paper_method_dir=root / "methods",
    # 未指定时使用 config.py 中的 VECTORS_PATH 配置。
)
bridge.create_vector()
```

当前轮子的 `top_k` 是匹配文本块数，多个块可能对应同一论文，因此最终显示的论文数可能小于填写的返回数量。现有保存逻辑按 metadata 去重；正文更新或论文删除后的向量更新仍需自行维护。

## HTTP 接口

`POST /api/semantic-search`，请求正文：

```json
{"query": "支持长期记忆和遗忘的端侧智能体", "top_k": 5}
```

成功响应：

```json
{"paper_ids": ["P000006", "P000013"]}
```

参数错误返回 HTTP 400，依赖、配置或检索异常返回 HTTP 503，错误正文为 `{"error": "错误说明"}`。查询限制为 1 至 4000 字，`top_k` 范围为 1 至 100。
