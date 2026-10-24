# 论文资料库维护指南

本项目维护论文 PDF、中文检索资料、精细总结 Markdown 和向量检索数据。整理资料前重新阅读当前 `AGENTS.md`；完成后说明本次修改的论文编号、文件重命名情况、资料核对及向量生成结果。用户当次的明确要求优先。

## 当前目录与职责

```text
launch.py                    # 启动入口
paper_viewer.html            # 页面布局
src/
  config.py                  # 统一路径、环境变量、向量参数
  load_data.py               # 数据读取与可选校验
  template.py                # 空资料库、论文记录模板及 Paper 数据类
  hash_duplicate.py          # SHA-256 工具与已收录论文哈希比较
  server.py                  # 端口绑定、Uvicorn 启动与浏览器打开
  routes.py                  # 应用创建、生命周期、路由与请求转发
  semantic_search/
    paper_vector_service.py  # PaperVectorService 接口、嵌入文本构建
    lifecycle.py             # 服务延迟创建、生命周期锁与退出清理
    embed_client.py           # 嵌入服务调用
    chunking.py              # 纯文本分块与上下文前缀
    jsonl_storage.py         # JSONL 分片发现、签名、读取与追加
    store.py                 # 保存检索协调、操作锁、缓存与相似度
data/
  papers.json                # 论文对象数组
  taxonomy.json              # 分类、标签与文献类型定义
  repo_state.json            # 编号计数器
  pdfs/<分类ID>/<filename>   # 例如 pdfs/C002/example.pdf
  detailed_summaries/<paper_id>.md      # 例如 detailed_summaries/P000020.md
  vectors/                   # 向量分片目录
    vectors_1.jsonl          # 首个分片
    vectors_2.jsonl          # 后续分片按数字递增
viewer/                      # 原生 JavaScript 模块、样式和已有测试
vendor/                      # 本地 Marked、KaTeX 依赖
new_paper/                   # 待整理论文；以实际文件为准
```

`src` 下通用模块直接位于该目录，导入使用 `src.config`、`src.load_data`、`src.server` 等；向量模块使用 `src.semantic_search`。历史迁移脚本已移除，不调用或重新生成这些脚本。

资料仅维护上述三个 JSON 文件，不生成 `paper_index.json`，也不拆成逐篇 JSON。前端分别加载论文与分类标签，调用 `createRepo(papers, taxonomy)`。

## 数据格式与路径规则

JSON 使用 UTF-8、英文 snake_case 字段名。论文概述、分类名称和描述、标签及文献类型的规范名称使用中文；RAG、AR 等通用缩写可保留。分类、标签与文献类型的引用使用稳定英文编号，提取状态等状态值使用英文。

### papers.json

顶层为数组，每篇记录使用以下结构。示例的编号、时间、文件名和文献信息均需替换；哈希必须计算真实 PDF 内容。

```json
[
  {
    "paper_id": "P000020",
    "added_at": "2026-10-07T21:27:38+08:00",
    "metadata": {
      "title": "Paper title as printed on the PDF",
      "original_filename": "Paper title.pdf",
      "filename": "paper-title-2026.pdf",
      "sha256": "<实际 PDF 的 64 位小写十六进制 SHA-256>",
      "document_type": "D004",
      "authors": "Author Name; Author Name",
      "year": 2026
    },
    "classification": {
      "primary_category": "C002",
      "tags": ["T017"]
    },
    "summary": "用一至三句中文说明研究问题、主要贡献和应用范围。"
  }
]
```

- `paper_id` 是唯一、稳定的论文标识，查询和关联均使用它，不能依赖数组下标、标题或文件名。
- `metadata.document_type` 只保存 `taxonomy.json` 中 `document_type_index` 定义的单个类型 ID，例如 `D004`；不保存自由文本名称。
- `filename` 只保存当前 PDF 文件名，不包含目录、路径分隔符或绝对路径。`original_filename` 保留收到文件时的来源名称，后续重命名时不改写。
- PDF 实际路径为 `PDFS_DIR / classification.primary_category / metadata.filename`。
- 精细总结实际路径为 `DETAILED_SUMMARIES_DIR / (paper_id + ".md")`，文件名保留大写 `P`。
- 不保存 `relative_path`、`method_document`、`method_summary`、`detailed_summary_document`、`reading_notes`、`paper_count` 等已移除或可推导字段。精细总结路径统一按论文编号推导，不从记录读取自定义路径。
- `authors`、`year` 无法从论文可靠确认时填 JSON `null`，不要填字符串 `"null"` 或猜测。
- 阅读依据、提取限制和实验前提写入对应 Markdown 的“资料整理说明”；通用整理套话无需逐篇保存。
- 约定缺少 `extraction_status` 表示 `text_extractable`；只有确实无法提取时记录 `text_unextractable`，详细限制写入 Markdown。该字段是资料记录约定，当前查看器不展示它。

### taxonomy.json

顶层包含 `category_index`、`tag_index`、`document_type_index`：

```json
{
  "category_index": {
    "C002": {
      "name": "智能体记忆机制",
      "description": "通用对话与 LLM 智能体的长期记忆组织、检索、治理及推理方法。"
    }
  },
  "tag_index": {
    "T017": "图记忆"
  },
  "document_type_index": {
    "D004": "方法与实验"
  }
}
```

分类 ID 是对象的键，例如 `C002`；它同时作为 PDF 分类目录名。分类条目只保存中文显示名称 `name` 和主题定义 `description`，不保存 `folder`。修改中文名称不改变分类 ID，也不重命名 PDF 目录。

论文只引用一个主分类 ID；跨主题信息通过标签表达。标签在 `tag_index` 中只保存一份规范名称，论文的 `classification.tags` 仅引用 ID，且同篇不重复。

### repo_state.json

```json
{
  "paper_id_counter": 20
}
```

`paper_id_counter` 保存已分配论文编号的最大数字，只增不减，即使删除论文或入库中断也不能降低。

## 新增论文的顺序

1. **核对来源与重复项。** 检查标题、作者、年份、DOI/arXiv 编号及现有记录；用 `src.hash_duplicate.hash_file()` 计算原始 PDF 的 SHA-256，并与 `metadata.sha256` 比较。重复导入或更新同一论文时保留原编号，不新建重复记录，也不覆盖同名但内容不同的 PDF。
2. **阅读原文。** 至少阅读标题页、摘要、引言、方法或系统设计，以及实验或讨论。数值与结论以原文为准。扫描或提取失败时记录限制，不凭文件名推测内容；不需要为代码或文档维护任务重新阅读全部论文。
3. **确定分类、标签、文献类型和文件名。** 先复用现有分类、近义标签与文献类型；确需新增时按下文扩充。新 PDF 使用稳定、可检索的英文小写短横线文件名。记录来源文件名，必要时先重命名，再放入 `PDFS_DIR/<分类ID>/`。
4. **一次性预留论文编号。** 读取状态计数器与现存论文编号最大数字，取较大者加一，生成 `P` 加至少六位数字的 ID。先保存递增后的计数器，再用这个编号创建精细总结文档和论文记录；后续步骤不重新分配。中断允许留下空号，已经预留的编号不复用。
5. **编写精细总结 Markdown。** 创建 `DETAILED_SUMMARIES_DIR/<paper_id>.md`，按实际内容说明研究问题、输入、核心流程、关键模块、输出和评估。具体程度应明显高于索引概述，不推测论文未给出的细节。
6. **保存论文记录。** 在 `papers.json` 数组加入记录，写入真实哈希、主分类 ID、标签 ID、文献类型 ID 和简短概述。`added_at` 使用实际当前北京时间的带时区 ISO 8601 值，不复制示例时间。新增定义同步保存到 taxonomy。
7. **核对关联。** 确认编号唯一、计数器有效、分类和标签均已定义，生成的 PDF 与 Markdown 路径存在。检查校验返回的描述列表；不能只因没有异常就认定资料完整。
8. **生成向量。** 全部资料保存后，逐篇调用 `PaperVectorService.create_vector(index=paper_id)`，核对返回值并记录结果。失败时保留已整理资料，明确报告失败原因和未生成向量的编号。

重命名新加入的 PDF 时，在交付说明中列出“原文件名 → 新文件名”和论文编号。不要为了命名统一而批量重命名历史论文，除非用户明确要求。重命名或移动文件不改变内容哈希；替换 PDF 内容后必须重新计算。

哈希接口位于 `src.hash_duplicate`：`hash_file(path)`、`hash_text(text)`、`hash_bytes(data)` 返回 64 位小写十六进制 SHA-256。`compare_hash(path=pdf_path)` 计算并查询已收录哈希，或传入 `compare_hash(digest=digest)` 复用已计算的值，返回布尔值。两者均提供时使用 `digest`；均未提供时抛出异常。哈希相同只能确认字节内容相同，不代替标题和来源核对。

## 分类、标签和编号维护

- 分类使用 `C` 加至少三位数字，例如 `C001`；新主题无法准确归入已有类别时可扩充，不强行归入近似类别。新增前检查同义主题，按现存最大分类数字加一分配，并创建同名 PDF 目录。已有分类 ID 保持稳定。
- 调整论文主分类时修改 `classification.primary_category` 并移动 PDF；`filename` 只在文件本身改名时更新。合并分类前改完所有引用、移动文件并核对同名冲突，再移除旧定义。
- 标签使用 `T` 加至少三位数字；新增概念按现存最大标签数字加一分配。复用近义名称，例如“第一视角视频”归入“第一视角”，“可穿戴”归入“可穿戴设备”，“多模态”归入“多模态记忆”。
- 标签改名只改 `tag_index`；合并标签先修改全部引用，再移除旧定义，不留下未定义 ID。
- 文献类型集中保存在 `document_type_index`，结构为类型 ID 到中文规范名称的映射。ID 使用 `D` 加至少三位数字，例如 `D004`；新增前检查同义和近义类型，优先复用，确需新增时使用现存最大数字加一。类型不表示论文主题，不能替代主分类或标签；同篇只引用一个类型 ID。
- 类型改名仅修改 `document_type_index` 名称，保留 ID。合并类型或调整论文类型时更新论文引用；向量 metadata 不保存文献类型，但嵌入上下文包含类型中文名称。若需检索反映名称或类型变化，应按向量更新说明重建，不能以 metadata 未变或 `saved=False` 认定向量已更新。删除类型前确认没有剩余引用，不复用已使用的 ID。
- 论文 ID 使用规范形式 `P000001`，数字大于零，超过六位后自然扩展，不增加多余前导零。删除、重命名、分类调整、数组重排均不改变已分配 ID。
- `added_at` 保存首次入库时间，更新已有记录时保留。部分历史记录的 `2026-10-07T21:27:38+08:00` 是补录时间，不代表真实历史入库时间。
- 修改资料时保留既有内容；保存 JSON 可先写同目录临时文件再替换，避免写入中断留下半个文件。涉及多个文件时先保存被引用的定义或预留状态，再保存论文记录。

## 精细总结文档要求

建议结构：研究问题与设定、方法流程、关键设计、评估方式与结论、局限与适用范围。综述可改写为文献筛选和分类框架；概念论文按系统模块说明，不强行套用训练流程。

关键事实尽量标注节号或 PDF 页码。区分作者明确陈述与自己的分析，实验条件、指标和数值必须可回查。未说明的实现细节写“文中未说明”或略去。支持常见 Markdown、行内 `$...$`/`\(...\)` 和独立 `$$...$$`/`\[...\]` 公式，复杂公式使用 KaTeX 支持的命令。详见 `data/detailed_summaries/README.md`。

## 读取和校验接口

`src/load_data.py` 不写文件、不生成缓存或聚合索引：

- `load_papers()`、`load_taxonomy()`、`load_state()` 均返回二元组 `(data, errors)`，默认校验单文件结构；调用示例为 `papers, errors = load_papers()`。不接受 `errors` 参数，必须检查返回的问题列表。
- `validate_data(papers, taxonomy, state, ...)` 校验结构与关联，返回描述列表，无问题返回 `[]`。
- `load_data()` 返回包含 `papers`、`taxonomy`、`repo_state`、`errors` 的字典，默认执行关联校验。
- `validate=False` 跳过校验，但文件读取和 JSON 解析错误仍会抛出；此时 `load_data()` 的 `errors` 为 `[]`。
- `validate_data()` 始终检查分类目录、PDF 和 Markdown 是否存在；`load_data(validate=True)` 同样执行该检查，不提供 `check_files` 参数。默认使用配置中的附件目录；显式传入 `root` 时检查该根目录下的 `data/pdfs/` 和 `data/detailed_summaries/`。校验不重新计算 PDF 哈希。

不可处理的结构、无效或重复编号、无效或落后的计数器、不安全文件名或路径属于致命错误。标题、概述、来源文件名、文献类型、作者和年份类型、入库时间、哈希格式、未定义引用、空名称、重复标签、附件缺失等问题收集到列表。`added_at` 必须为真实有效、含秒且带 `+08:00` 的 ISO 8601 时间。应查看列表并处理问题，不把非致命结果等同于校验全部通过。前端 `createRepo` 对未定义分类或标签等仍有严格检查，服务端继续运行不保证页面能加载异常记录。

## 启动、接口和配置

在项目根目录运行 `python launch.py`；加 `--no-open-viewer` 只启动服务。Python 需要 3.10 或更新版本，首次运行先用 `python -m pip install -r requirements.txt` 安装依赖。前端使用原生 ES Modules 和本地 vendor 依赖，无需 npm 构建，通过 HTTP 访问。

启动器仅在没有既有资料的空目录初始化三个 JSON；部分缺失或已有资料但配置缺失时会报错。随后创建附件目录并由 `src.server.launch()` 读取、校验资料。服务保留当前监听地址 `0.0.0.0`，浏览器自动打开 `127.0.0.1`；`launch.py` 默认端口为 `5000`，可用 `--port <端口>` 指定，`--port 0` 自动分配空闲端口。致命错误阻止启动，非致命描述输出到 stderr。默认连续约十分钟无请求后退出，页面通过心跳维持活动；沿用现有参数行为，`-s` 或 `--auto-shutdown` 关闭自动退出。开发实现见 `viewer/README.md`。

| 路由 | 内容 |
| --- | --- |
| `GET /papers.json` | 论文数组 |
| `GET /taxonomy.json` | 分类、标签与文献类型定义 |
| `GET /repo_state.json` | 编号状态 |
| `GET /files/pdfs/<分类ID>/<filename>` | 映射到 `PDFS_DIR` |
| `GET /files/detailed_summaries/<paper_id>.md` | 映射到 `DETAILED_SUMMARIES_DIR` |
| `POST /api/semantic-search` | 接收 `query`、`top_k`，返回 `paper_ids` |
| `GET /heartbeat` | 页面心跳 |

前端不读取状态文件，论文与 taxonomy 分别加载；Markdown 在打开详情时才读取。单击看详情，双击打开 PDF。关键词搜索覆盖编号、标题、文献类型、分类名称和描述、标签名称及概述，不搜索 Markdown 全文。语义搜索结果通过稳定编号关联论文。

修改 JSON 或 Markdown 后刷新页面；前端会缓存已打开的精细总结正文，因此刷新后再打开详情。修改 Python、配置或环境变量后重启服务。`src.server.launch()` 的所有资料及查看器路径统一读取 `src/config.py`，不再接受路径参数；需要更换资料位置时修改配置或相应环境变量，附件根目录同样以配置为准。

配置统一位于 `src/config.py`，路径值为 `Path`：

- 默认 `DATA_DIR` 为项目根目录下的 `data/`，`PDFS_DIR` 为其下的 `pdfs/`，`DETAILED_SUMMARIES_DIR` 为其下的 `detailed_summaries/`。
- `PAPERS_PATH` 环境变量覆盖论文文件；`DETAILED_SUMMARIES_DIR` 覆盖精细总结目录。taxonomy 和状态文件默认位置不随这两个变量改变。
- 默认向量目录为 `data/vectors/`，由 `src.config.VECTOR_DATA_DIR` 配置；`SEMANTIC_SEARCH_DATA_DIR` 可直接覆盖该目录，也可通过 `PaperVectorService(vectors_dir=...)` 显式指定。首个分片为 `vectors_1.jsonl`，后续依次为 `vectors_2.jsonl`、`vectors_3.jsonl` 等；读取仅匹配该命名规则，按数字顺序处理。向量目录覆盖不改变 repo 元数据和 PDF 所在目录。
- `VECTOR_MAX_ROWS` 位于 `src/config.py`，默认 `500`，必须为正整数，表示每个向量文件最多保存的物理行数（一条分块向量占一行）。写满后才创建下一个数字分片；一篇论文的分块可跨文件。重启后根据已有最大分片编号和该文件行数继续追加，检索和保存去重均扫描所有分片，不会因换文件而遗漏已有论文。降低上限不会自动重分已有文件，下一次写入会在需要时创建新分片。不要由多个进程同时写入同一组分片。
- 系统环境变量优先；安装 `python-dotenv` 后按 `ENV_FILES` 顺序加载项目根目录 `.env`、`src/semantic_search/.env`，不覆盖已设置的值。未安装时只读取系统环境变量。不要输出、提交或改写用户的 API Key。
- 现有 `.gitignore` 使用白名单，代码、查看器和说明文档可跟踪；论文 PDF、精细总结正文、资料 JSON、向量与 `.env` 默认忽略。不要擅自把私人资料纳入 Git。

## 向量生成与更新

向量功能需要 `numpy`、`httpx`、`BGE_M3_API_KEY`；仅浏览资料不需要调用嵌入服务。模型、服务地址、分块参数和默认检索数量以统一配置为准。服务端在首次语义搜索时才初始化嵌入客户端，搜索读取已有向量，不自动创建向量。

新增论文保存全部资料后，在项目根目录按稳定编号调用：

```python
from src.config import PAPERS_PATH, DETAILED_SUMMARIES_DIR, VECTOR_DATA_DIR
from src.semantic_search.paper_vector_service import PaperVectorService

with PaperVectorService(
    papers_path=PAPERS_PATH,
    detailed_summaries_dir=DETAILED_SUMMARIES_DIR,
    vectors_dir=VECTOR_DATA_DIR,
) as service:
    result = service.create_vector(index="P000020")
```

service 将 `summary` 和精细总结 Markdown 作为正文分块，再为每个分块附加相同的论文标题、文献类型中文名称和标签中文名称作为上下文。概述和精细总结正文必须为非空文本，精细总结文件必须存在且可读取，否则抛出异常，不静默生成仅含概述的向量。分块正文和上下文只用于调用嵌入服务，不写入向量文件。每条 JSONL 记录只保存 `vector` 和 `metadata`，其中 metadata 仅含 `title` 和 `index`；`index` 保存稳定的 `paper_id`（例如 `P000020`），不是数组下标。`PaperVectorService` 默认从配置中的 `TAXONOMY_PATH` 读取类型定义，自定义资料库时可传入 `taxonomy_path`，类型引用必须存在。返回列表必须包含目标编号：`saved=True` 表示保存调用完成，`saved=False` 表示存在相同精简 metadata 而跳过；当前尚无事务完整性保证，空列表不表示成功。依赖、网络、密钥或服务失败时保留资料，并明确报告原因与未生成向量的论文编号，不宣称已可向量检索。

优先使用 `with PaperVectorService(...) as service`；也可在 `finally` 中调用 `service.close()`。关闭为终止操作，重复关闭安全，关闭后必须新建实例才能再生成或检索，不会隐式重建 HTTP 客户端。分块配置、缓存机制和未实现的中断恢复方案见 `src/semantic_search/README.md`。

向量 metadata 由 `PaperVectorService._build_metadata()` 构造，再传给 `VectorStore.save()`；`src.template.Paper` 只保存数据，不负责向量记录格式。store 不解释论文编号、不筛选或转换 metadata 字段，只按调用方传入的内容保存、比较。已有 metadata 的索引逻辑集中在 `_load_metadata_keys()`，文件读取委托给 JsonlStorage，由 `save()` 统一进行保存去重，service 不重复扫描向量文件。store 检索返回原始 metadata 与分数，不返回正文。

仅支持 metadata 包含 `title` 和 `index` 的新向量格式，不兼容旧 `paper_id` 字段。保存前直接比较 metadata 检查重复，`PaperVectorService.retrieve()` 直接读取 `metadata["index"]` 并去重论文编号。现有旧向量文件暂不迁移或重建；不得直接用于新格式流程。

保存逻辑按精简后的 `title` 和 `index` 去重，正文变化并不会自动触发更新；标签、文献类型、PDF 移动或纯路径结构调整不影响该比较。相同论文的标题变化时可能留下多个结果，页面还会按论文编号去重，最终数量可能少于 `top_k`。HTTP 接口当前接受 `top_k` 为 1 至 100。

当前没有自动更新、删除或事务恢复接口。需要更新旧正文或清理已删除论文的向量时，先备份整组分片，以新的 `vectors_dir` 建立完整新库，核对后切换配置，不能只替换首个分片。不要在原库直接追加同一论文的新旧向量；不能用 `saved=False` 证明正文已经更新。

## 代码与文档维护

改动数据字段、目录或接口时，同步检查 `src/config.py`、`src/load_data.py`、`src/template.py`、相关后端调用、前端 `repo.js`/`utils.js`、已有测试文件和说明文档；避免重新引入已删除的派生字段或旧模块路径。前端开发说明见 `viewer/README.md`。

按用户要求决定是否运行测试；用户要求不测试时，不启动测试脚本或额外调用嵌入服务，并在交付说明中如实说明。修改本文档只需核对现有实现，无需修改业务代码、论文内容或向量。
