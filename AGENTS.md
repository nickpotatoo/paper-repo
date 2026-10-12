# 论文资料库维护指南

本目录保存论文 PDF、中文检索索引和逐篇方法文档。新增或更新论文时，先阅读论文，再同步维护 PDF、`paper_index.json` 和 `methods/*.md`。索引负责快速检索；Markdown 负责较长的方法说明。

## 目录与职责

- `01_personal-and-wearable-lifelogging/` 等分类文件夹：存放 PDF。当前有五类，后续可按论文主题扩充；分类定义以 `paper_index.json` 的 `category_index` 为准。
- `paper_index.json`：论文基本信息、主分类、内容概述、统一标签表，以及方法文档路径。
- `methods/`：每篇论文一份独立 Markdown 方法文档。文件名与索引中的 `paper_id` 完全一致（保留大写 P），例如 `P000001.md`。
- `start_viewer.bat`、`launch_viewer.ps1`、`paper_server.py`、`paper_viewer.html`：本地查看器。启动器默认读取同目录的 `paper_index.json` 并启动仅监听 `127.0.0.1` 的服务；点开卡片后，页面才请求该篇 Markdown。
- `migrate_methods.py`、`migrate_tags.py`：历史数据迁移工具。日常新增论文可以直接按下述格式编辑，不必运行迁移工具。

## 新增论文的顺序

0. **先阅读本指南。** 每次开始整理论文前，重新阅读当前 `AGENTS.md`，确认规则是否有更新，并以最新版本为准；不能只依赖之前任务中的记忆或旧说明。完成整理后，在交付说明中提醒用户已先核对 `AGENTS.md`。
1. **核对来源与重复项。** 检查标题、作者、年份、DOI 或 arXiv 编号及现有文件，避免重复收录。不要覆盖同名但内容不同的 PDF。
2. **检查并规范文件名。** 新加入的 PDF 使用稳定、易检索的英文小写短横线文件名（例如 `paper-title-2026.pdf`），不要保留下载站随机名、`最终版`、重复标题后缀等临时命名。若原文件尚未按此规则重命名，应先重命名；在交付说明中提醒用户该文件已重命名，并同步填写 `metadata.original_filename`（重命名前的来源文件名）和 `metadata.relative_path`（当前规范文件名）。如文件名可能冲突，先核对论文身份，不得覆盖其他文件。
3. **阅读论文。** 至少读标题页、摘要、引言、方法/系统设计和实验或讨论部分。图表可用于理解流程，但数值和结论应以论文原文为准。扫描版如无法可靠提取文字，先标明提取限制，不要凭文件名补写细节。
4. **选择一个主分类并移动 PDF。** 先阅读 `category_index` 中各分类的中文名称和描述，选择一个主分类 ID，并将 PDF 移至该条目 `folder` 指定的目录；跨主题信息通过标签表达。若新主题无法准确归入已有分类，可以新增分类，按下方规则同步更新目录和索引。
5. **写方法 Markdown。** 先按下方编号规则为新论文分配 `paper_id`，再在 `methods/` 创建同名文档（例如 `methods/P000020.md`），先写清研究问题、输入、核心流程、模块或算法、输出和评估方式。篇幅以论文实际信息为准，目标是比索引概述具体得多，不要为了凑长度推测未给出的实现细节。
6. **维护标签索引。** 先在 `paper_index.json` 的 `tag_index` 中寻找同义或近义标签，复用现有 ID。确需新标签时增加下一个未使用的 `TNNN` ID，并在论文记录中只引用 ID。
7. **分配编号并新增论文记录。** 使用前面已分配的稳定 `paper_id`，按示例结构加入 `papers` 数组，并填写 `added_at` 入库时间，同步更新顶层 `paper_count` 和 `paper_id_counter`。JSON 保存为 UTF-8，路径使用相对于本目录的 `/` 分隔形式。
8. **核对关联。** 确认 PDF 与 Markdown 路径存在、每个分类 ID 在 `category_index` 中有定义、PDF 路径的分类目录与该条目 `folder` 一致、每个标签 ID 在 `tag_index` 中有定义、Markdown 文件名不与其他论文共用。重新运行 `start_viewer.bat`，或刷新已打开的查看器页面，即可查看新内容。
9. **生成新论文向量。** PDF、JSON 和方法 Markdown 全部保存并核对关联后，必须调用 `SSBridge.create_vector(index=paper_id)` 为本次新增的每篇论文生成向量；批量新增时逐篇调用，使用稳定的论文编号。检查返回结果，并在交付说明中报告各论文的向量生成状态。具体调用方式见下方“新论文向量生成要求”。

### 新论文文件重命名提醒

后续处理新论文时，必须检查 PDF 是否已使用规范文件名。若尚未重命名，先按上述命名规则重命名，再更新索引中的 PDF 路径；完成后在回复中明确提示“原文件名 → 新文件名”。`metadata.original_filename` 记录收到时的原始名称，`metadata.relative_path` 则始终填写重命名后的实际路径。不要为了统一而批量改动已收录论文的文件名，除非本次任务明确要求整理历史文件。

## 分类扩充规则

当前五类只是现有论文的组织方式，不是固定或封闭的分类表。出现新的明确研究主题时，可新增主分类，无需强行放入相近但不准确的旧类别。

分类统一定义在顶层 `category_index`，分类 ID 使用稳定的 `C` 加至少三位补零数字（例如 `C001`），与论文编号 `P000001`、标签编号 `T001` 分开维护。论文的 `classification.primary_category` 只保存一个分类 ID 字符串，不能保存名称、描述或文件夹，也不能重新使用旧的 `category_descriptions` 结构。

每个分类条目必须包含以下三个字段，字段名保持英文：

- `name`：简明的中文分类名称，例如“智能体记忆机制”；新增前检查同义或近义名称，避免重复分类。
- `folder`：本目录下实际分类文件夹的英文名称，例如 `02_agent-memory-mechanisms`，不包含绝对路径或末尾 `/`。PDF 的 `metadata.relative_path` 使用 `folder/文件名.pdf`。
- `description`：中文主题定义，说明该分类收录哪些研究，供 Agent 判断归类。

新增前检查现有分类并复用相同主题的 ID；确需新增时，使用当前分类 ID 最大数字加一，不得修改或复用已分配 ID。分类文件夹仍使用下一个未使用的两位数字编号和英文小写短横线名称，例如 `06_new-research-topic`，创建后在 `category_index` 中登记对应 `folder`。文件夹编号与分类 ID 是独立字段，不能靠截取 ID 推算文件路径。`metadata.relative_path` 必须指向该分类 `folder` 中的 PDF。

修改分类的中文名称或描述时保留 ID。重命名分类文件夹时，同步更新条目的 `folder`、实际目录以及所有受影响论文的 `metadata.relative_path`。调整论文分类时更新其 `classification.primary_category`，移动 PDF 后同步更新路径。合并分类前将所有论文引用改到保留 ID，并按保留分类的目录移动 PDF、更新路径，再移除旧条目。每次整理后确认所有分类引用均有定义、每个分类目录存在且 PDF 路径与对应 `folder` 一致。


## JSON 结构

所有 JSON 字段统一使用下方示例中的英文 snake_case 名称，代码与文档必须使用相同字段名。`description`、`category_index` 中的 `description`、`summary` 和 `reading_notes` 保留中文描述，`category_index` 中的 `name` 和 `tag_index` 中的规范标签名称使用中文（如 RAG、AR 等通用缩写可保留）；文献类型、提取状态等其他值使用英文。`extraction_status` 当前使用 `text_extractable`；无法提取时使用 `text_unextractable`，详细限制写入中文 `reading_notes`。新增规范标签使用中文名称，先检查现有 `tag_index` 并复用同义标签 ID。

顶层保留 `description`、`category_index`、`tag_index`、`paper_count`、`paper_id_counter`、`papers`。`category_index` 和 `tag_index` 分别集中保存分类定义与规范标签。分类示例：

```json
"category_index": {
  "C002": {
    "name": "智能体记忆机制",
    "folder": "02_agent-memory-mechanisms",
    "description": "通用对话/LLM 智能体的长期记忆组织、检索、治理及推理方法。"
  }
}
```

`tag_index` 只存一份规范名称：

```json
"tag_index": {
  "T001": "个人知识图谱",
  "T017": "图记忆"
}
```

每篇论文使用如下结构；示例中的路径和 ID 应替换为实际值：

```json
{
  "paper_id": "P000020",
  "added_at": "2026-10-07T21:27:38+08:00",
  "metadata": {
    "title": "Paper title as printed on the PDF",
    "original_filename": "Paper title.pdf",
    "relative_path": "02_agent-memory-mechanisms/Paper title.pdf",
    "sha256": "<PDF 原始内容的 64 位小写十六进制 SHA-256>",
    "document_type": "Method and experiments",
    "authors": "Author Name; Author Name",
    "year": 2026
  },
  "classification": {
    "primary_category": "C002",
    "tags": ["T017"]
  },
  "summary": "用一至三句中文说明论文解决什么问题、主要贡献和应用范围。",
  "reading_notes": "根据论文摘要、引言及方法部分整理；为中文概述，不是逐字翻译。",
  "extraction_status": "text_extractable",
  "method_document": "methods/P000020.md"
}
```

`authors`、`year` 无法从论文可靠确认时填 `null`，不要猜测。`classification.tags` 只填 ID，不能写中文标签名称；不要在论文记录中重新加入长篇 `method_summary`。索引的 `summary` 应简短，具体方法写入 Markdown。

`metadata.sha256` 保存实际 PDF 原始字节的 SHA-256，使用 `utils.hash.hash_file()` 计算，不得根据标题或文件名生成。新增论文时一并填写；替换 PDF 内容后重新计算，单纯重命名或移动文件不改变哈希。

## 论文唯一编号规则

每篇论文记录顶层的 `added_at` 保存首次入库时间，使用带时区偏移的 ISO 8601 格式，例如 `2026-10-07T21:27:38+08:00`。新增论文时读取实际当前时间，按北京时间 Asia/Shanghai（UTC+08:00）填写，不得复制示例时间。更新已有论文、重命名或调整分类时保留原入库时间。本次历史数据统一补录为 `2026-10-07T21:27:38+08:00`，这是补录时间，不代表真实的历史入库时间。

- 每篇论文必须在记录顶层保存唯一的 `paper_id`，格式为 `P` 加至少六位十进制数字，例如 `P000001`、`P000020`。数字从 1 开始，使用六位补零；超过六位后自然扩展，不添加多余前导零。
- 新增前先核对是否为已收录论文；重复导入或更新同一论文时保留原编号。标题、文件名、分类、文档路径和数组顺序变化时也不得改变编号。
- 顶层 `paper_id_counter` 保存已分配编号的最大数字，首次分配后只增不减。新增时取计数器与现存编号数字最大值中的较大者加一，并更新计数器。删除论文后保留计数器，已使用编号永不复用。
- 代码以 `paper_id` 作为论文标识，通过编号映射查询记录；不得用数组下标、标题或文件路径作为稳定标识。PDF 和 Markdown 路径仍从该记录读取。
- 方法文档必须命名为 `methods/<paper_id>.md`，例如 `methods/P000020.md`；文件名严格对应论文编号，不能使用数组序号或标题作为文件名。`method_document` 必须记录同一相对路径。
- 完成新增或更新后，检查所有论文编号存在、格式正确、互不重复，且计数器不小于现有编号的最大值。交付说明中列出本次新增论文的编号。
- 历史记录缺少编号时，可运行 `python utils/migrate_paper_ids.py` 补齐；工具保留已有编号并检查格式与重复项，重复运行不会重新分配编号。

## 标签维护规则

- ID 是稳定引用。已有标签改名时，只改 `tag_index` 中的名称；论文记录中的 ID 保持不变。
- 添加标签前检查当前 `tag_index` 中的规范标签。不同措辞若表达相同概念，复用原 ID。例如“第一视角视频”归入 `第一视角`，“可穿戴”归入 `可穿戴设备`，“多模态”归入 `多模态记忆`。
- 新概念使用当前最大编号加一，例如 `T053`。一个论文内不要重复引用同一个 ID。
- 合并既有标签时，先把所有论文引用改到保留的 ID，再移除废弃 ID；不能让索引留下未定义引用。
- `migrate_tags.py` 现在会拒绝论文记录中的自由文本标签，可用于检查是否误写了名称。它不会替你判断新的语义近义词。

## 方法 Markdown 建议格式

```markdown
# Paper title

## 研究问题与设定
说明任务、输入数据、使用场景和作者要解决的限制。

## 方法流程
按实际步骤描述数据如何进入系统、经过哪些模块、如何检索或推理、最后产生什么输出。

## 关键设计
解释论文特有的表示方法、算法、训练或更新策略，以及这些设计的作用。

## 评估方式与结论
说明所用数据集/基准、对比对象和最重要的观察；数值必须与原文一致。

## 局限与适用范围
仅记录论文明确说明或由方法条件直接推得的限制，并区分原文陈述与自己的分析。
```

综述或概念框架论文可将“方法流程”换成文献筛选、分类框架或系统模块，不必强行套用训练流程。若论文没有说明某个细节，写“文中未说明”或略去。建议在关键事实后标出论文节号或页码，便于日后回查。

查看器支持常见 Markdown，以及 `$...$`、`\(...\)` 行内公式和 `$$...$$`、`\[...\]` 独立 LaTeX 公式。复杂公式请使用 KaTeX 支持的命令。详细编辑示例见 `methods/README.md`。

## 本地查看器与更新行为

双击 `start_viewer.bat`，启动器自动使用同目录的 `paper_index.json`，启动本地 HTTP 服务并在服务就绪后打开浏览器，不弹出文件选择窗口。若需使用其他索引，可从命令行运行 `launch_viewer.ps1 -IndexPath <JSON 路径>`。页面先读取索引，打开论文卡片时才从原始 Markdown 文件读取该篇方法正文，不生成临时 JS 缓存。单击卡片看详情，双击打开 PDF。搜索范围为编号、标题、内容概述和标签，不包含尚未打开的 Markdown 全文。运行查看器需要 Python 3.10 或更新版本。

修改 Markdown 或 JSON 后，刷新浏览器页面即可读取最新内容；已经打开的卡片需要重新打开。持久内容只维护本目录中的 PDF、JSON 和 Markdown。

## 向量检索

页面“向量检索”按钮打开搜索框，通过 `POST /api/semantic-search` 将查询交给 HTTP 服务，再调用 `utils/semantic_search/bridge.py` 中的 `SSBridge.retrieve()`。返回值为 `paper_id` 列表，页面按检索顺序显示论文，不使用数组下标匹配。向量检索需要 `numpy`、`httpx`、`BGE_M3_API_KEY` 和预先创建的向量文件；默认位于索引目录的 `data/vectors.jsonl`。新增或更新论文时还需维护向量，详细配置与当前轮子的更新限制见 `utils/semantic_search/README.md`。

### 新论文向量生成要求

Agent 处理完新论文后，生成向量是收录流程的必要步骤。必须先保存最新 `paper_index.json` 和 `methods/<paper_id>.md`，再调用 `SSBridge`，确保嵌入包含已整理的内容概述和方法正文。在项目根目录使用以下方式，替换示例编号；向量文件路径必须与查看器 HTTP 服务使用的配置一致：

```python
import os
from pathlib import Path
from utils.semantic_search.bridge import SSBridge

root = Path.cwd().resolve()
vectors_path = os.environ.get("VECTORS_PATH") or (
    Path(os.environ.get("SEMANTIC_SEARCH_DATA_DIR", str(root / "data"))) / "vectors.jsonl"
)
bridge = SSBridge(
    paper_index_path=root / "paper_index.json",
    paper_method_dir=root / "methods",
    vectors_path=vectors_path,
)
result = bridge.create_vector(index="P000020")
```

`index` 参数传入论文的 `paper_id`，不是数组下标。返回列表应包含该编号：`saved=True` 表示新向量已保存，`saved=False` 表示相同 metadata 已存在而跳过，空列表不能视为成功。依赖、API Key、网络或嵌入服务导致生成失败时，保留已完成的论文资料，在交付说明中明确报告失败原因和未生成向量的编号，不得宣称该论文已可向量检索。不得在日志或回复中输出 API Key。

更新已收录论文的正文时，当前轮子可能因 metadata 相同而跳过；`saved=False` 不代表向量已反映正文更新，应按 `utils/semantic_search/README.md` 的限制处理。
