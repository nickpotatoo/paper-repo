# RepoManager

`src.RepoManager` 提供资料初始化、读取、校验和管理接口。调用方可以为实例指定独立的资料与附件路径。

```python
from src.RepoManager import RepoManager, load_data

repo = RepoManager()
data = load_data()
taxonomy = repo.get_taxonomy()
```

- `get_paper(paper_id)` 与 `get_taxonomy()` 读取已校验的记录和索引。
- `validate_classification_draft(draft, taxonomy)` 校验待审阅的分类草稿，返回错误和候选提示。
- `ingest_paper(..., classification=draft)` 是候选转为正式定义的入口。入库时核对已有引用、复用同名定义，再为剩余候选分配编号。新分类须提供 `description`，PDF 保存到该分类编号目录。
- `delete_taxonomy_entry(kind, entry_id)` 删除未被论文引用的定义。类型接受 `category`、`tag` 或 `document_type`。编号分配记录与分类目录会保留。
- `delete_paper(paper_id)` 从索引及正式附件目录移除论文记录、PDF、精细总结和向量文件，返回位于论文索引同目录下 `.deleted_papers/` 的归档路径。归档保存原记录及当时存在的附件。论文计数器保持原值。
- 管理方法在进程内串行写入，JSON 使用原子替换。论文删除涉及多个文件，遇到普通写入错误时尝试恢复附件。多进程写入和进程崩溃恢复由调用方协调。

## 论文处理任务

```python
from pathlib import Path
from src.PaperProcessing import TaskManager

tasks = TaskManager(Path("task"))
task = tasks.create_task(Path("new_papers/example.pdf"))
tasks.run_task(task.task_id)
```

`create_task()` 按源 PDF 的 SHA-256 复用已有任务。`run_task()` 连续执行已排队的阶段，`submit_action_to_task()` 提交动作后继续执行，`get_task()` 读取任务。TaskManager 持久化状态和产物，PaperWorkflow 负责状态转移。

任务列表中的「删除任务」对应 `DELETE /api/tasks/{task_id}`，将任务移至 `task/.task-archive/`。正式论文和向量留在资料库。「重新执行」对应 `POST /api/tasks/{task_id}/restart`，将未入库任务的旧产物归档，保留任务编号和原始 PDF，随后在后台从准备阶段重跑。两项操作均要求服务密码。

`task.json` 使用 `stages.vectorize` 记录首次生成，使用 `stages.retry_vectorize` 记录重试。审阅完成且入库后，任务通过 `run_task()` 执行首次生成。失败后可进入重试阶段，尝试次数和错误独立记录。失败时任务为 `action_required`，向量阶段为 `failed`。成功后任务进入 `finished`，结果为 `completed`。

任务列表通过 `TaskManager.submit_action_to_task(task_id, TaskAction.GENERATE_VECTOR)` 手动启动或重试向量阶段。该入口复用工作流。`StageHandlers` 校验正式论文与任务原件是否一致，调用向量服务并检查保存结果。向量服务会将论文的概述和精细总结发送给配置的嵌入服务。服务中断后可重试。

`TaskManager.submit_action_to_task(task_id, TaskAction.ACCEPT)` 确认审阅后启动独立的 `ingest` 阶段。阶段处理器读取草稿，管理器调用 `RepoManager.ingest_paper()`。成功后工作流将入库标为 `completed`，写回正式论文编号并推进到向量阶段。确认入库会同时采纳候选 taxonomy 定义，已存在的同名定义会复用编号。同一 PDF 按哈希复用已有论文编号。正式索引最后写入，普通写入错误会清理本次产生的附件与分类定义，序号仍保留。向量默认随工作流继续执行。HTTP 入口在返回入库结果后后台调度。
