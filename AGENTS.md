# 论文资料库维护指南

本文指导 agent 整理论文和维护资料。每次开始前重新阅读当前 `AGENTS.md`，确认规则是否更新；用户当次明确要求优先。代码或文档维护任务不要求重新阅读全部论文，也不自动生成向量。

## 1. 资料位置与基本约定

实际路径以 `src/config.py` 为准，不依赖固定的项目绝对路径。默认结构如下：

```text
new_paper/                              # 待整理论文，以实际来源位置为准
data/
  papers.json                           # 全部论文记录，顶层数组
  taxonomy.json                         # 分类、标签、文献类型索引
  repo_state.json                       # 论文编号计数器
  pdfs/<category_id>/<filename>.pdf      # PDF 按主分类编号存放
  detailed_summaries/<paper_id>.md       # 每篇论文独立的中文精细总结
  vectors/<paper_id>.json                # 每篇论文的 metadata、分块文本和向量
```

- JSON 和 Markdown 使用 UTF-8。JSON 字段使用英文 snake_case；概述、精细总结、分类名称与描述、标签和文献类型名称使用中文，通用专业缩写可保留。
- 只维护上述三个资料 JSON，不生成 `paper_index.json` 或逐篇论文 JSON，不添加 `schema_version`。
- 论文关联使用稳定的 `paper_id`，不能依赖数组下标、标题、文件名或分类顺序。
- 新加入且尚未规范命名的 PDF 必须重命名为便于检索的英文小写短横线文件名。保留来源文件名；不要仅为统一命名而批量重命名历史论文。
- 保留已有资料，不覆盖同名但内容不同的 PDF。PDF 移动或重命名不改变内容哈希；替换文件内容后必须重新计算哈希。
- `.gitignore` 默认忽略资料 JSON、PDF、精细总结正文、向量和 `.env`。不要擅自将私人资料纳入 Git，不输出、提交或改写 API Key。

## 2. 新论文入库流程

1. **读取现有资料。** 阅读当前指南，加载三个 JSON，确认分类定义、编号状态和附件实际位置。
2. **检查重复。** 核对标题、作者、年份、DOI/arXiv 编号等来源信息，计算原始 PDF 的 SHA-256 并查询现有哈希。重复导入或更新同一论文时保留原编号，不新建重复记录。
3. **阅读原文。** 至少阅读标题页、摘要、引言、方法或系统设计，以及实验或讨论。扫描件或提取失败时记录限制，不凭文件名推断内容，不编造作者、年份、方法或结果。
4. **确定分类和命名。** 优先复用已有分类、标签和文献类型。必要时扩充 taxonomy；规范 PDF 文件名，记录原名，并放入对应分类编号目录。
5. **预留唯一编号。** 取 `paper_id_counter` 与现有论文编号最大数字的较大者加一，生成新编号；先保存递增后的计数器，再创建论文记录和 Markdown。一个入库任务只分配一次，预留后中断允许留空号，不能回收重用。
6. **编写精细总结。** 保存到 `DETAILED_SUMMARIES_DIR/<paper_id>.md`，内容应明显比 JSON 概述详细，符合第 5 节要求。
7. **保存记录。** 写入真实哈希、来源信息、分类/标签/文献类型 ID、概述和当前北京时间；新增 taxonomy 定义应先于引用它们的论文记录保存。
8. **核对资料。** 检查编号、引用、计数器、PDF 和 Markdown；处理校验函数返回的问题列表，不能只因没有异常便认定完整。
9. **生成向量。** 新论文资料保存并核对后，按论文编号调用 `PaperVectorService.create_vector(index=paper_id)`，批量任务复用同一个 service。用户要求暂不生成时遵从并报告未生成编号；依赖、权限、网络或服务失败时保留已整理资料并报告原因。
10. **交付说明。** 列出论文编号、分类及新增定义、`原文件名 → 新文件名`、校验结果、向量生成或跳过情况，以及尚未解决的提取限制。

不要由多个任务并发分配编号或修改同一组资料文件；当前没有跨文件事务或编号分配接口。保存 JSON 可先写同目录临时文件再替换，避免留下半个 JSON；这不保证多个文件同时提交。

## 3. JSON 格式

### 3.1 papers.json

顶层为论文数组。以下为结构示例，编号、时间、文献信息和哈希均需替换：

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
    "summary": "用一至三句中文概述研究问题、主要贡献和应用范围。"
  }
]
```

| 字段 | 要求 |
| --- | --- |
| `paper_id` | `P` 加至少六位数字，例如 `P000001`；数字大于零，超过六位自然扩展，不增加多余前导零。 |
| `added_at` | 首次入库的北京时间，ISO 8601 格式，包含秒和 `+08:00`，例如 `2026-10-24T15:30:00+08:00`；必须取实际当前时间，更新已有记录时保留。 |
| `metadata.title` | 原论文标题，不用中文概述替换。 |
| `metadata.original_filename` | 收到文件时的来源名称，后续重命名不改写。 |
| `metadata.filename` | 当前 PDF 文件名，包含 `.pdf`，不含目录、路径分隔符或绝对路径。 |
| `metadata.sha256` | 实际 PDF 内容的 SHA-256，64 位小写十六进制。 |
| `metadata.document_type` | `document_type_index` 中已定义的单个类型 ID，不保存自由文本名称。 |
| `metadata.authors` / `year` | 作者使用非空字符串，年份使用 1–9999 的整数；无法可靠确认时使用 JSON `null`，不猜测，不写字符串 `"null"`。 |
| `classification.primary_category` | 一个已定义的分类 ID；跨主题信息用标签表达。 |
| `classification.tags` | 已定义标签 ID 的数组，同篇不重复，不保存标签名称。 |
| `summary` | 非空中文概述，详细内容独立写入 Markdown。 |

PDF 路径推导为 `PDFS_DIR / primary_category / filename`；精细总结路径推导为 `DETAILED_SUMMARIES_DIR / (paper_id + ".md")`，文件名保留大写 `P`。

不保存 `relative_path`、`method_document`、`method_summary`、`detailed_summary_document`、`reading_notes`、`paper_count` 等已移除或可推导字段。阅读依据、实验前提和提取限制写入 Markdown 的“资料整理说明”。缺少 `extraction_status` 约定为 `text_extractable`；确实无法提取文本时才记录 `text_unextractable`，并在 Markdown 说明限制。

部分历史记录的 `2026-10-07T21:27:38+08:00` 是统一补录时间，不代表真实历史入库时间；新论文不得沿用该时间。

### 3.2 taxonomy.json

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

分类条目只保存中文 `name` 和 `description`，不保存 `folder`。分类 ID 同时作为 PDF 目录名，显示名称修改不改变 ID 或目录名。标签与文献类型均为 ID 到中文规范名称的映射。

### 3.3 repo_state.json

```json
{
  "paper_id_counter": 20
}
```

计数器记录已分配论文编号的最大数字，只增不减。删除论文、入库中断或数组重排都不能降低计数器或改变已分配编号。

## 4. 分类、标签和文献类型维护

- 分类使用 `C`、标签使用 `T`、文献类型使用 `D`，各加至少三位数字，例如 `C001`、`T017`、`D004`。新增时使用对应索引现存最大数字加一；不复用已使用的 ID。
- 分类允许随新主题扩充。先核对已有定义，不能准确归类时新增中文名称及清晰的主题描述，并创建同编号 PDF 目录，不强行归入近似类别。
- 标签优先复用规范名称，避免近义重复。例如“第一视角视频”归入“第一视角”，“可穿戴”归入“可穿戴设备”，“多模态”归入“多模态记忆”。
- 文献类型描述论文形式，例如综述或方法与实验，不代替主题分类；同篇只引用一个类型。
- 改名只改索引名称并保留 ID。合并前先更新全部论文引用；分类合并还需移动 PDF 并核对同名冲突，完成后再移除旧定义，不留下未定义引用。
- 调整主分类时同步移动 PDF；仅文件本身改名时才修改 `filename`。标签或文献类型名称/引用变化会改变嵌入上下文，但不会自动更新已有向量，按第 7 节处理。

## 5. 精细总结 Markdown

精细总结围绕论文实际内容展开，不能仅扩写摘要或填充通用套话。建议包含：

1. 研究问题、应用场景、假设和输入输出。
2. 方法的完整流程、关键模块、数据结构及模块之间的信息传递。
3. 核心算法、公式、训练或推理过程，以及关键设计的动机。
4. 实验设定、数据集、基线、指标、主要结果和消融结论。
5. 局限、适用条件和资料整理说明。

综述按文献筛选、分类框架与研究脉络展开；概念论文按系统模块与论证展开，不强行套用训练流程。区分作者陈述、论文实验证据与整理者分析；数值、结论和关键事实尽量注明节号或 PDF 页码，未给出的细节写“文中未说明”或略去。

使用标准 Markdown，可包含表格和代码块。LaTeX 支持行内 `$...$`、`\(...\)`，以及独立 `$$...$$`、`\[...\]`；复杂公式使用 KaTeX 支持的命令。更多编辑说明见 [data/detailed_summaries/README.md](data/detailed_summaries/README.md)。

## 6. 哈希与校验接口

在项目根目录使用现有 Python 接口，不重新实现哈希或另造数据格式：

```python
from src.hash_duplicate import hash_file, compare_hash
from src.load_data import load_data

pdf_hash = hash_file(pdf_path)
is_duplicate = compare_hash(digest=pdf_hash)
repo = load_data()
errors = repo["errors"]
```

`hash_file()`、`hash_text()`、`hash_bytes()` 返回 SHA-256。`compare_hash(path=...)` 可直接计算并查询；同时传入 `digest` 和 `path` 时优先使用 `digest`。哈希相同只能证明字节相同，不能代替来源核对。

- `load_papers()`、`load_taxonomy()`、`load_state()` 返回 `(data, errors)`，默认只校验单文件结构；不接受 `errors` 参数。
- `init_data()` 按配置显式初始化空资料库：仅在三个 JSON 均不存在且资料目录中没有任何文件时创建空模板及附件目录，允许空目录存在；部分 JSON 缺失时报错，不覆盖已有文件。启动器默认调用它，读取接口不会自动初始化；不要用它修复丢失的资料。
- `validate_data(papers, taxonomy, state, root=None)` 返回关联及附件问题列表；`load_data()` 返回含 `papers`、`taxonomy`、`repo_state`、`errors` 的字典，默认执行完整校验。
- 无问题返回空列表。无法读取/解析、不可处理的结构、无效或重复 ID、落后的计数器、不安全路径等会抛异常；内容、引用、时间、哈希格式或附件缺失等可能仅返回问题描述。两种情况都必须处理。
- 完整校验检查所有分类目录、PDF、Markdown 是否存在，但不重新计算 PDF 哈希，也不能代替原文和总结质量检查。不提供 `check_files` 参数。
- 默认附件路径使用配置值；显式传入 `root` 时检查该根目录下的 `data/pdfs/` 和 `data/detailed_summaries/`。读取自定义 JSON 不会自动推导自定义附件位置。
- `validate=False` 仅跳过校验，读取和解析错误仍会抛出。不要用它绕过入库问题，也不要将读取成功视为入库核对完成。

## 7. 向量生成与更新

### 新论文生成

新增论文必须在资料完整后调用公开的论文向量服务；不要直接调用 VectorStore、EmbedClient 或手工写入向量 JSON。通常使用默认配置，批量任务共用一个上下文：

```python
from src.semantic_search.paper_vector_service import PaperVectorService

paper_ids = ["P000020"]  # 替换为本次实际入库编号
with PaperVectorService() as service:
    for paper_id in paper_ids:
        result = service.create_vector(index=paper_id)
        # 检查 result 中的 paper_id 和 saved，并记入交付说明。
```

`index` 是稳定论文编号；省略或传 `None` 会处理全部论文，新增任务不要误用全库生成。自定义资料位置时，可传 `papers_path`、`taxonomy_path`、`detailed_summaries_dir`、`vectors_dir`，确保属于同一资料库。

检索通过 `service.retrieve_document(query, top_k=...)` 返回论文编号列表，原 `retrieve()` 已改名；需要检索具体片段时调用 `service.retrieve_chunk(query, top_k=...)`，返回按相似度降序排列的分块列表，每项包含 `text`、对应论文 `metadata` 和 `score`。分块检索不按论文合并，同篇可返回多个分块；text 包含嵌入时的上下文前缀。两种检索都要求 top_k 为正整数，不自动生成资料向量。

生成会读取概述与精细总结正文，并为每个分块附加标题、中文文献类型和中文标签上下文，然后发送给配置的嵌入服务。默认服务为 SiliconFlow，具体地址、模型、密钥和分块参数以 `src/config.py` 及环境变量为准；用户要求不外发或暂不生成时不能调用。缺少密钥、资料校验失败、总结缺失或为空时明确报错，不退化为只嵌入概述。

返回值是结果列表，必须包含目标编号：`saved=True` 表示创建、同步保存成功，或内容完全相同而无需写入；内容未变时不生成向量、不写文件、不递增 revision。`saved=False` 表示 JSON 写入失败，应结合日志核对；空列表不表示成功。失败时记录具体编号与原因，不宣称已经可检索。

### 文件格式与更新限制

- 每篇论文保存到 `data/vectors/<paper_id>.json`，顶层为 `revision`、`metadata` 和非空 `chunks` 数组；metadata 仅含 `title`、`index`，其中 `index` 为稳定的 `paper_id`。每个 chunk 保存 `text`、`text_hash`、`revision` 和 `vector`，`text` 是实际送入模型的完整文本，包含论文上下文前缀。
- `text_hash` 为完整 text 的 UTF-8 SHA-256，使用现有哈希接口，不规范化空白或换行。新文档主 `revision` 初始为 `1`，后续每批 JSON 实际修改前加一；本批新增或变化的 chunk 使用当前主 revision，复用 chunk 保留原版本。仅修改 metadata、删除分块或调整顺序也递增主版本，完全不变则不写入、不递增。由 VectorStore 组装文档、计算哈希、管理版本、校验内容及展开分块，JsonStorage 仅负责安全文件定位与 JSON 读写、原子替换。不手工伪造哈希，也不兼容缺少这些字段的向量文件。
- 不再使用按行数分片的配置；只读取新格式 `.json` 文件，不兼容、转换或读取旧 JSONL。修改存储代码不代表已生成新向量，旧文件可保留备份，但不会出现在新检索结果中。
- 保存时按论文编号定位文件，按当前完整嵌入文本的 `text_hash` 复用已有向量，只生成新增哈希的向量，移除当前已不存在的分块。同次保存内重复哈希只生成并保留一份，按文本首次出现顺序排列；不跨论文判重。修改概述、总结、标签、文献类型或分块参数后，再次按编号调用生成即可同步；metadata 相同也必须检查文本哈希。
- `VectorStore.save(..., remove_stale_chunks=True)` 可配置旧分块清理，默认开启以保持上述同步行为；设为 False 时保留全部旧分块及其顺序，只追加新增哈希分块，旧分块仍参与检索。没有实际修改时不写入、不递增 revision；论文服务当前使用默认值，整理任务不要绕过论文服务直接调用 store。
- 新增分块生成并与复用分块一起校验后写入同目录临时文件，通过替换一次发布整篇 JSON；失败不会提前删除旧分块或将半篇 JSON 当作完成。当前没有跨进程写锁、多论文事务、后台自动同步或整篇删除接口，不要多个进程同时写同一资料库。
- JsonStorage 提供 `delete(document_id)` 文件删除接口。JSON 写入异常时，store 统一调用删除接口清理对应 JSON，包括原有同名文件；清理完成后返回 False 并记录警告。删除失败继续抛异常；嵌入或内容校验失败不删除旧文件。这里没有提供论文服务级删除接口。
- 切换嵌入模型或清理已删除论文时，先明确重建范围并备份，在新的 `vectors_dir` 建立完整新库，核对后切换配置；文本哈希不包含模型标识，不能用哈希相同或 `saved=True` 证明模型已更新。用户未授权重建时先报告待更新项。

使用 `with PaperVectorService(...)` 或在 `finally` 调用 `close()` 释放资源。生命周期逐层管理：路由 → lifecycle 代理 → PaperVectorService → VectorStore → EmbedClient / JsonStorage；VectorStore 在操作锁内关闭自己持有的客户端，上层不跨层访问。关闭后需新建实例，不自动重连。实现说明见 [src/semantic_search/README.md](src/semantic_search/README.md)。

## 8. 环境与交付边界

Python 需要 3.10 或更新版本，依赖见 `requirements.txt`。项目根目录运行 `python launch.py`，仅启动服务可加 `--no-open-viewer`。修改资料后刷新查看器，修改 Python、配置或环境变量后重启服务；查看器与 HTTP 开发细节见 [viewer/README.md](viewer/README.md)。

配置路径为 `Path`。`PAPERS_PATH`、`DETAILED_SUMMARIES_DIR`、`SEMANTIC_SEARCH_DATA_DIR` 环境变量可分别覆盖论文 JSON、总结目录和向量目录，彼此不会自动联动，也不改变 taxonomy、状态和 PDF 位置。环境变量优先于项目根目录及向量模块目录下的 `.env`；不要通过重新初始化空资料库覆盖既有数据。

改动资料格式、路径或公开接口时，同步核对 `src/config.py`、`src/load_data.py`、`src/template.py`、向量服务、相关前端和说明文档。本文保留论文维护约定，具体服务实现、前端交互和故障恢复设计放入对应 README。

按任务需要和用户要求决定是否测试；用户要求不测试时不运行测试。修改本指南本身无需改变论文、业务代码或向量，也不额外调用嵌入服务。交付时如实区分资料校验、测试和向量生成结果。
