# PaperProcessing

论文处理流水线将原始 PDF 转成可审阅的草稿。用户确认后，任务入库并自动继续到向量生成阶段。论文写作、命名和分类准则见 [AGENTS.md](../../AGENTS.md)，正式库接口见 [RepoManager](../RepoManager/README.md)。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `task_manager.py` | 创建、查询和归档任务；提交动作并循环执行阶段，保存任务状态和产物，提交正式入库并同步分类缓冲。 |
| `workflow.py` | 判断动作资格、计算和应用状态转移；每次执行一个阶段，返回更新的任务和阶段结果。 |
| `stages.py` | 执行查重、提取、草稿生成与校验，准备入库草稿，生成、保存并检查向量。 |
| `models.py` | 定义 `TaskAction`、任务状态、阶段状态、转移和阶段结果，以及任务、状态快照和校验报告模型。 |
| `validation.py` | 校验 PDF、草稿元数据、分类引用及总结。分类规则由 RepoManager 提供。 |
| `taxonomy_buffer.py` | 合并正式和临时定义、分配临时 ID、转换入库候选和替换临时引用。 |
| `interfaces.py` | 定义 PDF 提取、内容生成、向量生成和状态回调协议，可为测试注入实现。 |
| `llm_content_generator.py`、`prompts.py` | 通过 `LLMClient` 生成元数据、分类、粗略总结和精细总结，集中管理提示模板。 |

## 阶段与状态

```text
prepare → deduplicate → extract → metadata → classify
        → rough_summary → detailed_summary → validate → review (action_required)
                                                          ↓ 确认入库
                                   ingest (pending → running → completed)
                                                          ↓
                                     vectorize (pending → running → completed)
```

| 阶段 | 输入与结果 |
| --- | --- |
| `prepare` | 比对任务 PDF 副本和来源 SHA-256。 |
| `deduplicate` | 按哈希查询正式论文库。命中则记录 `duplicate_of`，任务状态变为 `finished`，结果为 `duplicate`。 |
| `extract` | 调用 PDFProcessing 检查 PDF、提取内容并导出 Markdown，记录检查信息和质量报告。 |
| `metadata` | 根据提取原文生成题名、作者、年份和规范文件名，补上来源文件名。 |
| `classify` | 将提取原文、正式索引和共享缓冲交给模型，生成主分类、标签和文献类型。 |
| `rough_summary` | 生成中文粗略总结，入库后写入论文记录的 `summary`。 |
| `detailed_summary` | 生成支持 LaTeX 的中文 Markdown，入库后保存为 `<paper_id>.md`。 |
| `validate` | 校验 PDF 哈希、元数据、分类和两份总结。报告含 `error` 时停在失败阶段，`warning` 可继续审阅。 |
| `review` | 用户预览并确认入库，或按项重新生成。确认后审阅完成，任务进入 `ingest/pending`。 |
| `ingest` | 保存正式论文、附件及分类定义，同步其他任务的临时引用，并写回正式论文编号。失败时任务标记为 `action_required`、入库阶段标记为 `failed`，可重试。成功后进入 `vectorize/pending`。 |
| `vectorize` | 确认入库后由管理器继续执行。失败时任务标记为 `action_required`、向量阶段标记为 `failed`，可重试。成功后进入 `finished`，结果为 `completed`。 |
| `retry_vectorize` | 用户重试失败的向量生成时进入。单独记录尝试次数和结果，保留首次生成的记录。重试失败时停在此阶段，成功时任务完成。 |

HTTP 调用链为 `route → TaskManager → PaperWorkflow → StageHandlers`。路由负责认证、响应和后台调度。工作流只在内存中更新任务；管理器负责保存状态和发布产物。HTTP 入库先返回论文编号，再在后台生成向量。

`PaperWorkflow.submit_action(task, action, *, retry_stage=None)` 计算动作产生的状态变化，不执行阶段。`PaperWorkflow.run()` 每次执行一个阶段；`TaskManager.run_task()` 循环执行并保存，直到需要操作、失败、结束或到达指定暂停点。

### 动作、失败与中断

| 动作 | 可用时机与结果 |
| --- | --- |
| `accept` | 确认审阅，进入 `ingest/pending`。 |
| `regenerate_*` | 待审阅时重生成指定草稿，成功或失败后回到审阅。 |
| `generate_vector` | 正式入库完成后启动向量阶段，也可用于重试向量。 |
| `retry` | 对 `retryable_stages` 中的失败阶段执行重试。分析和入库从所选阶段继续；向量走 `retry_vectorize`，保留首次失败记录；重生成失败后可在审阅时重试该项。 |
| `resume`、`cancel` | 可通过脚本提交，分别用于恢复可继续的阶段、取消待审阅任务。没有独立的 HTTP 入口。 |
| `restart`、`archive` | 由管理器处理。未入库任务可归档旧版本后从原始 PDF 重新执行，沿用任务 ID；删除任务只归档任务目录。 |

分析阶段失败时，任务和阶段均为 `failed`。入库或向量失败时，任务为 `action_required`，对应阶段仍为 `failed`。如果运行记录显示上次执行中断，管理器先通过工作流标记中断并停下；再次运行不会自动重试失败阶段。界面根据 `allowed_actions` 和 `retryable_stages` 显示「重试：阶段名」。重生成的 HTTP 重试按默认提示执行，需要附加要求时可从审阅界面重新提交该项。

### 单项重新生成

仅在未入库且处于 `review/action_required` 时可执行。重生成复用提取原文和对应的生成阶段，校验完整草稿后发布新产物和报告。成功时归档旧产物，失败时保留原稿。两种结果均返回待审阅。任务通过重生成阶段的记录展示执行结果。

| 操作 ID | 更新内容 |
| --- | --- |
| `regenerate_metadata` | 论文元数据 |
| `regenerate_classification` | 主分类、标签及文献类型 |
| `regenerate_rough_summary` | 粗略总结 |
| `regenerate_detailed_summary` | 精细总结 |

前端允许在确认前填写可选的 `additional_prompt`。它作为当前请求的附加要求与原文一同传给模型，仍使用对应阶段的系统提示模板和草稿校验。留空时按默认规则生成。HTTP 层当前限制为 2000 字符，请求体最多 32768 字节，设置见 `src/config.py`。

## 任务目录与数据

默认根目录为 `TASKS_DIR`。新任务按源 PDF 的 SHA-256 复用匹配任务，首次创建时分配 `task-<uuid>`。下面只会出现已经生成的产物。

```text
task/
  taxonomy_buffer.json                 # 任务间共享，首次登记候选时创建
  <task_id>/
    task.json
    input/source.pdf
    duplicate/result.json
    extraction/
      pdf_info.json
      extraction.json
      quality.json
      extracted.md
    analysis/
      metadata.json
      classification.json
      rough_summary.txt
      detailed_summary.md
    validation/report.json
    history/<attempt>/                 # 单项重生成保留的旧产物
  .task-archive/<task_id>-<uuid>/       # 删除任务或重新执行时的整目录归档
```

| `task.json` 字段 | 内容 |
| --- | --- |
| `task_id` | 稳定任务编号，与任务目录名一致。 |
| `status`、`current_stage` | 初始为 `pending` 和 `prepare`。阶段结束后按流程更新，无当前阶段时为 `null`。 |
| `outcome` | 任务结束时区分 `completed`、`duplicate` 和 `cancelled`；未结束时为 `null`。 |
| `created_at`、`updated_at` | 创建及更新时间，使用带 `+08:00` 的 ISO 8601 时间。 |
| `source` | `original_filename`、`copy_path`、`sha256`，正常创建时写入实际 PDF 的 SHA-256。 |
| `duplicate_of`、`paper_id` | 分别是查重命中的正式论文 ID 与任务入库后关联的正式 ID，初始均为 `null`。 |
| `stages` | 按阶段名存放 `StageRecord`，每项含 `status`、`attempts`、`started_at`、`finished_at`、`artifacts`、`error`、`wait_reason`。产物路径相对任务目录。 |

任务状态为 `pending`、`running`、`action_required`、`failed`、`finished`。阶段状态为 `pending`、`running`、`action_required`、`failed`、`completed`、`skipped`。

`metadata.json` 保存题名、作者、年份、正式文件名和来源文件名，可包含提取到的 DOI 与 arXiv ID。`classification.json` 保存 `primary_category`、`tags`、`document_type`；无适用的正式文献类型时保留 `proposed_document_types`。`validation/report.json` 的 `issues` 列表记录 `code`、`message`、`severity` 和 `field`。

### 全局分类缓冲

```json
{
  "category_index": {
    "T-C001": {"name": "图相关检索", "description": "图结构上的检索与排序方法", "reason": "现有主分类未覆盖"}
  },
  "tag_index": {
    "T-T001": {"name": "结构化检索", "reason": "现有标签无法表达"}
  },
  "counters": {"C": 1, "T": 1}
}
```

分类阶段把正式索引和临时条目合并后传给模型。模型可按 ID 复用两者。模型提出的 `proposed_categories` 和 `proposed_tags` 通过校验后登记进共享缓冲，并在任务产物中转换为 `T-C…`、`T-T…` 引用。草稿的 `pending_categories` 和 `pending_tags` 提供预览所需的定义快照。入库时从共享缓冲读取定义，文献类型候选由各任务独立保存。

任务入库时，`RepoManager.ingest_paper()` 分配正式编号并写入正式库。随后 `TaskManager` 按已登记定义更新当前及其他活动任务的分类产物，全部改写成功后移除相应缓冲条目，最后写回当前任务的 `paper_id`。若跨任务改写中途失败，缓冲仍可用于重试，正式库按 PDF 哈希复用已经入库的论文。历史产物和归档目录保留当时的引用。

## 调用接口

```python
from pathlib import Path

from src.PaperProcessing import TaskAction, TaskManager
from src.config import TASKS_DIR

tasks = TaskManager(TASKS_DIR)
task = tasks.create_task(Path("new_papers/example.pdf"))
task = tasks.run_task(task.task_id)
```

核对草稿后，用 `tasks.submit_action_to_task(task.task_id, TaskAction.ACCEPT)` 确认入库；需要暂缓向量时传入 `stop_before="vectorize"`，之后调用 `run_task()` 或提交 `TaskAction.GENERATE_VECTOR`。失败时先查 `tasks.retryable_stages(task)`，再用 `tasks.submit_action_to_task(task.task_id, TaskAction.RETRY, retry_stage=stage)` 重试选定阶段。

运行工作流会将提取原文发送给配置的大模型服务。生成向量会将论文概述、精细总结和标签等上下文发送给配置的嵌入服务。

| `TaskManager` 接口 | 行为 |
| --- | --- |
| `create_task(source, original_filename=...)` | 保存原件副本和初始状态，返回新建或复用的任务。 |
| `run_task(task_id, *, additional_prompt="", stop_before=None)` | 连续执行已排队阶段。遇到待操作、失败、结束或指定阶段时停下。 |
| `submit_action_to_task(task_id, action, *, additional_prompt="", stop_before=None, retry_stage=None)` | 保存动作转移，再调用 `run_task()`。只存在一个可重试阶段时，`RETRY` 可省略 `retry_stage`。 |
| `allowed_actions(task)`、`retryable_stages(task)` | 查询可用动作和可重试阶段。 |
| `get_task(task_id)`、`list_tasks()` | 读取完整任务或活动任务列表。 |
| `restart_task(task_id)`、`archive_task(task_id)` | 归档任务。重新执行仅允许未入库任务，调用方随后调度运行。删除任务保留正式论文和向量。 |

任务分析、重生成和缓冲更新在单进程内加锁。任务状态和文本产物按文件替换写入。跨任务同步及正式入库涉及多个文件，部署时应协调同一资料目录的多进程写入。

## HTTP 入口

任务和上传接口使用 `X-Service-Password`，值为 UTF-8 密码的 Base64 编码。

| 方法与路径 | 输入或结果 |
| --- | --- |
| `POST /api/upload-paper` | PDF 原始字节，`X-Filename` 为 URI 编码文件名。设置 `X-Process-Paper: true` 时创建或复用任务，并后台调度新任务。未设置时只保存文件。 |
| `GET /api/tasks` | 返回 `tasks` 数组，包含任务和阶段状态、`outcome`、`allowed_actions` 与 `retryable_stages`。 |
| `GET /api/tasks/{task_id}/contents` | 返回已有可阅读产物的 `key` 和 `title`。 |
| `GET /api/tasks/{task_id}/contents/{key}` | 返回白名单产物文件，例如 `pdf`、`classification`、`detailed-summary`。 |
| `POST /api/tasks/{task_id}/regenerate/{action}` | 可选请求体 `{"additional_prompt":"请补充实验设置"}`，返回执行结果。 |
| `POST /api/tasks/{task_id}/ingest` | 确认入库并返回 `paper_id`，在后台继续执行向量阶段。 |
| `POST /api/tasks/{task_id}/retry?stage=...` | 重试 `stage` 指定的失败阶段，返回 `stage_status` 和 `paper_id`。阶段不可重试时返回 409；重试再次失败时返回 503。入库重试成功后，在后台继续生成向量。 |
| `POST /api/tasks/{task_id}/vector` | 手动启动或重试向量阶段，返回 `stage_status`。 |
| `POST /api/tasks/{task_id}/restart` | 重新执行未入库任务并在后台调度。 |
| `DELETE /api/tasks/{task_id}` | 将任务目录移入归档。 |
