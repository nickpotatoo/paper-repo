# RepoManager

`src.RepoManager` 提供资料初始化、读取、校验和管理接口。调用方可以为实例指定独立的资料与附件路径。

```python
from src.RepoManager import RepoManager, load_data

repo = RepoManager()
data = load_data()
tag_id = repo.add_taxonomy_entry("tag", "图检索")
repo.update_taxonomy_entry("tag", tag_id, "图结构检索")
repo.delete_taxonomy_entry("tag", tag_id)
```

- `get_paper(paper_id)` 与 `get_taxonomy()` 读取已校验的记录和索引。
- `validate_classification(draft, taxonomy)` 校验任务中的分类、标签和文献类型引用及候选定义。候选只提交内容，正式编号由 RepoManager 在新增定义或确认入库时分配。
- 分类索引接口接受 `category`、`tag` 或 `document_type`。新增分类须提供 `description`，并自动创建 PDF 目录。改名保留编号。仍被论文引用的定义不能删除。删除分类定义会保留磁盘上的目录。
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

`create_task()` 按源 PDF 的 SHA-256 复用已有任务。`run_task()` 执行指定任务，`run_pending()` 用于后台调度尚未开始的新任务，`regenerate_task()` 执行待审阅任务的单项重生成，`get_status()` 读取状态快照。TaskManager 创建所需的工作流并持久化结果，`PaperWorkflow` 负责阶段推进和审阅规则。

任务列表中的「删除任务」对应 `DELETE /api/tasks/{task_id}`，将任务移至 `task/.task-archive/`。正式论文和向量留在资料库。「重新执行」对应 `POST /api/tasks/{task_id}/restart`，将未入库任务的旧产物归档，保留任务编号和原始 PDF，随后在后台从准备阶段重跑。两项操作均要求服务密码。

`task.json` 在 `stages.vectorize` 中记录向量阶段的状态、尝试次数、时间和错误。审阅完成且入库后，`current_stage` 切换为 `vectorize`，任务与阶段状态都为 `pending`。触发生成后变为 `running`。失败时停在该阶段，可重试。成功后任务与阶段都为 `completed`，清除 `current_stage`。

任务列表通过 `TaskManager.generate_vector(task_id, vector_service=service)` 调度「生成向量」或「重试生成向量」。`StageHandlers` 校验正式论文与任务原件是否一致，调用向量服务并检查保存结果。向量服务会将论文的概述和精细总结发送给配置的嵌入服务。任务管理器记录阶段状态和尝试次数，并防止同一进程内重复提交正在生成的任务。服务中断后可重试。

`TaskManager.ingest_task(task_id)` 将到达审阅的任务交给 `StageHandlers`，由阶段处理器读取草稿并调用 `RepoManager.ingest_paper()`。成功后任务管理器写回正式论文编号，将审阅阶段标为 `completed`，推进到向量阶段。确认入库会同时采纳候选 taxonomy 定义，已存在的同名定义会复用编号。同一 PDF 按哈希复用已有论文编号。正式索引最后写入，普通写入错误会清理本次产生的附件与分类定义，序号仍保留。入库接口只保存本地资料，向量生成由上层另行触发。
