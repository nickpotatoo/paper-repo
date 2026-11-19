# PaperProcessing

论文处理流水线将原始 PDF 转成可审阅的草稿。用户确认后，任务入库并进入待生成向量阶段。论文写作、命名和分类准则见 [AGENTS.md](../../AGENTS.md)，正式库接口见 [RepoManager](../RepoManager/README.md)。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `task_manager.py` | 任务入口。创建和加载任务、调度工作流、保存状态和产物、维护共享分类缓冲、发起入库和向量生成。 |
| `workflow.py` | `next_state(stage, status, event)` 定义分析和审阅阶段的状态转移。`PaperWorkflow` 执行阶段、安排草稿校验并记录结果。 |
| `stages.py` | `StageHandlers` 执行查重、提取、生成、校验、入库和向量操作，调用相应服务。 |
| `models.py` | `Task`、`TaskSource`、`StageRecord`、状态快照和校验报告的 Pydantic 模型。 |
| `validation.py` | 校验 PDF、草稿元数据、分类引用及总结。分类规则由 RepoManager 提供。 |
| `taxonomy_buffer.py` | 合并正式和临时定义、分配临时 ID、转换入库候选和替换临时引用。 |
| `interfaces.py` | 定义 PDF 提取、内容生成、向量生成和状态回调协议，可为测试注入实现。 |
| `llm_content_generator.py`、`prompts.py` | 通过 `LLMClient` 生成元数据、分类、粗略总结和精细总结，集中管理提示模板。 |

## 阶段与状态

```text
prepare → deduplicate → extract → metadata → classify
        → rough_summary → detailed_summary → validate → review (waiting)
                                                          ↓ 确认入库
                                                vectorize (pending)
                                                          ↓ 生成向量
                                                     completed
```

| 阶段 | 输入与结果 |
| --- | --- |
| `prepare` | 比对任务 PDF 副本和来源 SHA-256。 |
| `deduplicate` | 按哈希查询正式论文库。命中则记录 `duplicate_of`，任务状态变为 `duplicate`，结束分析。 |
| `extract` | 调用 PDFProcessing 检查 PDF、提取内容并导出 Markdown，记录检查信息和质量报告。 |
| `metadata` | 根据提取原文生成题名、作者、年份和规范文件名，补上来源文件名。 |
| `classify` | 将提取原文、正式索引和共享缓冲交给模型，生成主分类、标签和文献类型。 |
| `rough_summary` | 生成中文粗略总结，入库后写入论文记录的 `summary`。 |
| `detailed_summary` | 生成支持 LaTeX 的中文 Markdown，入库后保存为 `<paper_id>.md`。 |
| `validate` | 校验 PDF 哈希、元数据、分类和两份总结。报告含 `error` 时停在失败阶段，`warning` 可继续审阅。 |
| `review` | 用户预览并确认入库，或按项重新生成。内部审阅动作 `accept` 只结束审阅，正式保存由 `TaskManager.ingest_task()` 完成。 |
| `vectorize` | 入库后由用户单独触发。失败可重试，成功后任务变为 `completed`，`current_stage` 置为 `null`。 |

普通分析阶段发生异常时，任务停在当前阶段，状态为 `failed`。再次调用 `run_task()` 可重试该阶段。工作流遇到上次中断留下的 `running` 分析任务时会标记为 `waiting`，以便核对产物。未入库任务可通过「重新执行」归档旧产物并从 `prepare` 开始，任务编号和来源 PDF 保持一致。

### 单项重新生成

仅在未入库且处于 `review/waiting` 时可执行。重生成复用提取原文和对应的生成阶段，校验完整草稿后发布新产物和报告。成功时归档旧产物，失败时保留原稿。两种结果均返回待审阅。任务通过重生成阶段的记录展示执行结果。

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
| `created_at`、`updated_at` | 创建及更新时间，使用带 `+08:00` 的 ISO 8601 时间。 |
| `source` | `original_filename`、`copy_path`、`sha256`，正常创建时写入实际 PDF 的 SHA-256。 |
| `duplicate_of`、`paper_id` | 分别是查重命中的正式论文 ID 与任务入库后关联的正式 ID，初始均为 `null`。 |
| `stages` | 按阶段名存放 `StageRecord`，每项含 `status`、`attempts`、`started_at`、`finished_at`、`artifacts`、`error`、`wait_reason`。产物路径相对任务目录。 |

任务状态取值为 `pending`、`running`、`waiting`、`failed`、`completed`、`duplicate`、`cancelled`。阶段状态取值为 `pending`、`running`、`waiting`、`failed`、`completed`、`skipped`。列表接口返回计算字段 `can_ingest`。尚无 `paper_id` 且处于 `review/waiting` 或内部审阅已接受的 `completed` 状态时，该字段为真。

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

from src.PaperProcessing import TaskManager
from src.config import TASKS_DIR

tasks = TaskManager(TASKS_DIR)
task = tasks.create_task(Path("new_papers/example.pdf"))
task = tasks.run_task(task.task_id)
```

运行工作流会将提取原文发送给配置的大模型服务。生成向量会将论文概述、精细总结和标签等上下文发送给配置的嵌入服务。

| `TaskManager` 接口 | 行为 |
| --- | --- |
| `create_task(source, original_filename=...)` | 保存原件副本和初始状态，返回新建或复用的任务。 |
| `run_task(task_id)`、`run_pending(task_id)` | 执行分析工作流。后者仅调度尚在 `prepare/pending` 的新任务。 |
| `load(task_id)`、`get_status(task_id)`、`list_tasks()` | 读取完整任务、单任务状态快照或当前任务列表。 |
| `read_artifact(task_id, path)` | 从任务目录读取指定相对路径的产物字节。 |
| `regenerate_task(task_id, action, additional_prompt="")` | 重新生成指定内容，返回更新后的任务。 |
| `ingest_task(task_id)` | 保存正式论文和附件并返回论文编号，任务进入 `vectorize/pending`。 |
| `generate_vector(task_id)` | 对已入库且完成审阅的任务生成向量，返回 `running`、`completed` 或 `failed`。 |
| `restart_task(task_id)`、`archive_task(task_id)` | 归档任务。重新执行仅允许未入库任务，调用方随后调度运行。删除任务保留正式论文和向量。 |

任务分析、重生成和缓冲更新在单进程内加锁。任务状态和文本产物按文件替换写入。跨任务同步及正式入库涉及多个文件，部署时应协调同一资料目录的多进程写入。

## HTTP 入口

任务和上传接口使用 `X-Service-Password`，值为 UTF-8 密码的 Base64 编码。

| 方法与路径 | 输入或结果 |
| --- | --- |
| `POST /api/upload-paper` | PDF 原始字节，`X-Filename` 为 URI 编码文件名。设置 `X-Process-Paper: true` 时创建或复用任务，并后台调度新任务。未设置时只保存文件。 |
| `GET /api/tasks` | 返回 `tasks` 数组，包含状态、来源文件名、阶段记录和入库资格。 |
| `GET /api/tasks/{task_id}/contents` | 返回已有可阅读产物的 `key` 和 `title`。 |
| `GET /api/tasks/{task_id}/contents/{key}` | 返回白名单产物文件，例如 `pdf`、`classification`、`detailed-summary`。 |
| `POST /api/tasks/{task_id}/regenerate/{action}` | 可选请求体 `{"additional_prompt":"请补充实验设置"}`，返回执行结果。 |
| `POST /api/tasks/{task_id}/ingest` | 确认入库并返回 `paper_id`。 |
| `POST /api/tasks/{task_id}/vector` | 触发向量生成，返回 `stage_status`。 |
| `POST /api/tasks/{task_id}/restart` | 重新执行未入库任务并在后台调度。 |
| `DELETE /api/tasks/{task_id}` | 将任务目录移入归档。 |
