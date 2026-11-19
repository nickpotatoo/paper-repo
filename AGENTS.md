# 论文库整理指南

每次开始整理论文前，重新阅读本文件，确认规则是否更新。用户在当前任务中的要求优先。以下约定用于阅读、整理、入库和检索新论文。

## 1. 确认资料位置与范围

路径以 `src/config.py` 为准。默认位置如下。

| 位置 | 用途 |
| --- | --- |
| `new_papers/` | 待处理的原始 PDF |
| `task/<task_id>/` | `task.json`、原件副本、分析草稿和校验报告 |
| `task/.task-archive/` | 已移出列表的任务及重新执行前的旧版本 |
| `task/taxonomy_buffer.json` | 所有任务共享的待入库分类和标签 |
| `data/papers.json` | 正式论文记录，顶层为数组 |
| `data/taxonomy.json` | 正式分类、标签和文献类型索引 |
| `data/repo_state.json` | 论文和索引编号计数器 |
| `data/pdfs/<category_id>/<filename>.pdf` | 正式 PDF |
| `data/detailed_summaries/<paper_id>.md` | 中文精细总结 |
| `data/vectors/<paper_id>.json` | 每篇论文独立的向量文件 |

JSON 和 Markdown 使用 UTF-8。JSON 字段使用英文 snake_case。保留原文标题，概述、精细总结、分类名称及描述、标签和文献类型使用中文，可保留专业术语及缩写。资料文件、任务内容和密钥按仓库已有忽略规则管理。

## 2. 整理和入库

1. **查重并核对来源。** 用 `src.hash_duplicate.hash_file(pdf_path)` 对实际文件计算 SHA-256，查看正式库和已有任务。相同哈希应复用既有记录或任务。不同哈希的版本还需核对标题、作者、年份和 DOI／arXiv 编号。
2. **阅读论文。** 至少核对标题页、摘要、引言、方法或系统设计，以及实验或讨论。遇到扫描件、公式丢失或提取不全时，在精细总结中写明影响。以能确认的原文为依据。
3. **准备元数据。** 新加入的 PDF 如果尚未按规范命名，入库时将其重命名为便于检索的英文小写短横线文件名，例如 `paper-title-2026.pdf`。在 `original_filename` 中保留来源文件名。作者或年份无法确认时填 `null`。
4. **确定分类并撰写总结。** 按第 3 节复用或提出定义。粗略总结用一至三句中文概括研究问题、主要方法或贡献和代表性结论。精细总结按第 4 节单独撰写。
5. **确认并入库。** 走任务流水线时，通过任务「入库」或调用 `TaskManager.submit_action_to_task(task_id, TaskAction.ACCEPT)`，由系统同步任务状态和临时分类引用。独立整理的草稿可用 `RepoManager.ingest_paper(...)`，提交原件、SHA-256、来源文件名、元数据、分类草稿、概述和精细总结。该入口接收正式 ID 和候选定义。返回值是稳定的正式论文编号。
6. **核对并生成向量。** 用 `src.RepoManager.load_data()` 核对论文记录、索引和附件，并处理返回的 `errors` 与抛出的异常。必要时重新计算 PDF 哈希并与记录比对。按第 6 节生成本次入库论文的向量。
7. **交付。** 汇报论文编号、主分类及新增定义、文件名变化、校验结果、向量生成状态和原文提取限制。

### 流水线操作

- 脚本先调用 `TaskManager.create_task(pdf_path)` 创建或复用任务，再调用 `run_task(task_id)`。运行会逐阶段保存产物，在待审阅、失败或终态停下。查询完整记录用 `get_task(task_id)`。
- 到达 `review/action_required` 后，预览并核对草稿。元数据、分类与标签、粗略总结、精细总结可以分别重生成。附加提示词只用于本次生成。确认入库用 `submit_action_to_task(task_id, TaskAction.ACCEPT)`。
- 阶段失败时，先看阶段的错误或校验报告，再用界面的「重试：阶段名」，或调用 `submit_action_to_task(task_id, TaskAction.RETRY)`。重试始终执行当前失败阶段。单项重生成成功后回到审阅。
- 「重新执行」只适用于未入库的任务，会归档旧产物并从原始 PDF 开始。「删除任务」会归档任务目录，正式入库的论文、附件和向量仍保留。

### 维护流水线代码

维持 `route → TaskManager → PaperWorkflow` 的调用边界。路由负责认证、HTTP 响应和后台调度；管理器负责创建任务、运行阶段、提交动作以及保存状态和产物；工作流负责动作资格与状态转移；阶段处理器负责具体处理、内容校验和向量生成。

任务状态是 `pending`、`running`、`action_required`、`failed` 和 `finished`。结束结果通过 `outcome` 区分完成、重复与取消。执行失败时，任务与当前阶段均记为 `failed`。前端根据 `allowed_actions` 显示操作。修改动作或状态时，同步核对工作流、管理器接口、路由和前端。

## 3. 分类、标签和文献类型

- 优先复用 `taxonomy.json` 的正式定义。每篇论文选一个能覆盖核心主题的主分类，相关的细粒度检索主题用标签表示。文献类型描述论文形式，例如综述或方法与实验。
- 正式分类不足以覆盖时，可以提出新分类。名称和描述应覆盖可容纳多篇论文的研究方向，避免用单篇论文的方法、模型、数据集或特定应用命名。新增标签前检查现有同义、近义和上位标签。
- 流水线还会读取共享缓冲。可复用临时主分类 `T-C001` 和临时标签 `T-T001`。任务入库后，系统登记正式 ID，更新所有活动任务中的对应引用，并清理已登记的缓冲条目。临时 ID 只出现在任务草稿中。
- 需要新增主分类时，在草稿中将 `primary_category` 设为 `null` 并在 `proposed_categories` 放入一项候选，包含中文 `name`、`description`、`reason`。新增标签填 `proposed_tags`，每项包含中文 `name` 和 `reason`。无适用文献类型时，将 `document_type` 设为 `null`，在 `proposed_document_types` 提出一项候选，包含中文 `name` 和 `reason`。有定义可复用时填写已有 ID，候选留空。
- 正式 ID 由入库接口分配。主分类、标签、文献类型分别使用 `C`、`T`、`D` 加至少三位数字。维护既有定义时保留 ID。调整主分类要同步论文引用和 PDF 位置。删定义前核对全部论文引用，使用 `RepoManager.delete_taxonomy_entry(kind, entry_id)` 删除未引用定义。

## 4. 精细总结 Markdown

以论文原文标题为一级标题，根据论文内容组织章节。

1. **研究问题与设定**。说明研究动机、任务、输入输出、场景和关键假设。
2. **方法流程与关键设计**。从输入到输出解释处理顺序、模块职责、数据结构、信息传递、算法步骤及设计动机。原文给出关键公式或参数时保留并解释。
3. **评估与结论**。说明数据集或样本、基线、指标、设置、主要结果、消融和重要例外。数字应注明比较对象和实验条件。综述侧重文献组织与研究脉络，概念论文侧重组件与论证。
4. **局限与适用范围**。区分作者陈述、实验观察和整理者判断，指出证据适用的条件。
5. **资料整理说明**。记录实际阅读的章节、图表或页码，并说明提取限制。关键事实和公式尽量标注原文位置。

使用标准 Markdown。LaTeX 可用行内 `$...$` 或 `\(...\)`，独立公式用 `$$...$$` 或 `\[...\]`，复杂公式选用 KaTeX 支持的命令。

## 5. 正式数据约定

| 文件 | 结构与要求 |
| --- | --- |
| `papers.json` | 每条记录包含 `paper_id`、`added_at`、`metadata`、`classification`、`summary`。 |
| `metadata` | `title`、`original_filename`、`filename`、`sha256`、`document_type`、`authors`、`year`。`document_type` 引用正式类型 ID。`authors` 是字符串或 `null`，`year` 是 1–9999 的整数或 `null`。 |
| `classification` | `primary_category` 是一个正式分类 ID，`tags` 是不重复的正式标签 ID 数组。 |
| `taxonomy.json` | `category_index` 将分类 ID 映射到 `{name, description}`，`tag_index` 和 `document_type_index` 将 ID 映射到中文名称。 |
| `repo_state.json` | `paper_id_counter` 记录论文编号上限，可选的 `taxonomy_id_counters` 分别保存 `C`、`T`、`D` 编号上限。只增不减，已预留的空号不可复用。 |

`paper_id` 格式为 `P` 加至少六位数字，例如 `P000001`。附件和索引通过编号关联。`added_at` 是首次入库的实际北京时间，格式为 ISO 8601，包含秒和 `+08:00`，例如 `2026-11-19T14:30:00+08:00`。更新已有记录时保留首次入库时间。PDF 路径由主分类 ID 和文件名推导，精细总结路径由论文 ID 推导。数据模板见 [src/template.py](src/template.py)。

## 6. 向量与检索

查看器确认入库后返回论文编号，再在后台执行 `vectorize`。入库成功后核对向量阶段是否完成，失败时重试当前 `vectorize` 阶段。用户要求暂缓生成时，使用 `TaskManager.submit_action_to_task(task_id, TaskAction.ACCEPT, stop_before="vectorize")`。独立整理时复用同一个 `PaperVectorService`，逐篇调用 `create_vector(index=paper_id)` 并检查返回项中的 `paper_id` 和 `saved`。省略 `index` 会处理全库。

向量请求会将概述、精细总结及题名、文献类型、标签等上下文发送给配置的嵌入服务。按用户授权执行。用户要求暂不生成时，报告跳过的编号。服务失败时保留已入库资料并记录失败原因。`saved=True` 可表示成功保存或已有向量无需改写。概述、精细总结或嵌入上下文更新后，按对应编号刷新向量。

按论文检索使用 `retrieve_document(query, top_k=...)`，按分块检索使用 `retrieve_chunk(query, top_k=...)`。存储结构和更新规则见 [SemanticSearch](src/SemanticSearch/README.md)。
