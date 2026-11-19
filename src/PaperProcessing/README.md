# 新论文处理流水线设计

本文是待实现的设计；正式资料格式和维护规则以项目根目录 `AGENTS.md` 为准。一个任务处理一份 PDF，task ID 与论文 ID 独立。

类似一个自动状态机，在上个状态完成后，完成校验，才可进入下一个状态

运行一个循环，完成后退出循环
最好能进行断点续跑，这就要求后一个状态不会污染前一个状态，能够简单的进行状态的回退
说白了就是各种资源分开保存，不可叠加

每个阶段遵循同一顺序：执行 → 保存产物 → 校验产物 → 更新 task 状态

需要建模一个状态数据结构，用于传递给回调函数，向前端更新任务状态

由用户分别触发正式入库和向量生成。阶段处理器读取待入库草稿，并负责向量生成及结果校验。任务管理器记录阶段状态，正式库由 RepoManager 写入。
元数据、分类、粗略总结和精细总结可在待审阅时重新生成，执行完毕后返回审阅。

新论文处理分以下几个阶段
- 检查论文是否有对应task
- 创建task（在task子文件夹下，包含论文副本与task.json，记录数据与阶段）
- 生成hash，检查是否有重，有重则终止task
- 处理pdf，读取pdf内容，保存在task子文件夹下
- 生成或确认论文标题、作者、年份、来源文件名和英文规范文件名
- 读取已有 taxonomy，生成主分类、标签和文献类型，优先复用现有 ID
- 生成粗略总结
- 生成精细总结
- 校验待入库的论文草稿、分类候选、PDF 和精细总结
- 由用户自行决定是否入库，确定是否要重新生成某个内容
- 用户确认入库后由 RepoManager 标记审阅完成，进入 `vectorize` 阶段，等待用户生成向量

## 阶段细节

| 阶段 ID | 处理内容与推进条件 |
| --- | --- |
| `prepare` | 检查已有任务，创建目录并复制 PDF，记录来源文件名；按内容哈希识别已有任务，文件名仅作辅助。副本可读且内容一致后继续。 |
| `deduplicate` | 计算副本 SHA-256 并查正式论文库；完全重复时记录匹配编号并终止。哈希不同不能排除不同版本的同一论文，疑似重复时等待确认。 |
| `extract` | 检查 PDF，提取结构化内容和原文 Markdown，保存质量报告。检查状态、issues 和内容；扫描件可尝试 OCR，加密或内容不足时等待处理。 |
| `metadata` | 确认原文标题 `title`、作者 `authors`、年份 `year`，保留 `original_filename`，生成英文小写短横线 `filename`；DOI 和 arXiv ID 可作为查重辅助。无法确认作者或年份时为 null。检查安全文件名及冲突。 |
| `classify` | 读取 taxonomy，确定主分类 `primary_category`、标签 `tags`、文献类型 `document_type`。优先复用 ID；不适用时提出新增中文名称、分类描述及候选定义。校验引用及标签不重复。 |
| `rough_summary` | 基于原文生成非空中文粗略总结，说明问题、贡献和范围，记录内容缺失限制；最终对应论文记录的 `summary` 字段。 |
| `detailed_summary` | 生成独立中文精细总结 Markdown，覆盖方法流程、实验和局限等，支持 LaTeX，尽量注明页码或章节；内容必须基于论文。 |
| `validate` | 校验任务草稿的元数据、分类引用或候选定义、PDF 哈希与精细总结；生成问题列表。全部阻断问题解决后提交用户审阅。此时尚无正式论文编号和入库时间，不能直接把现有正式库完整校验当作草稿校验。 |
| `review` | 展示草稿与校验结果，用户可接受、重新生成指定内容或暂停。接受后返回草稿，是否入库由上层决定。 |
| `regenerate_metadata` | 基于当前提取文本重新生成标题、作者、年份等元数据并校验。 |
| `regenerate_classification` | 仅从 `review` 进入；重新生成并校验分类候选，成功后更新分类产物与草稿校验报告，直接返回 `review`。 |
| `regenerate_rough_summary` | 仅从 `review` 进入；重新生成并校验粗略总结，成功后更新对应产物与草稿校验报告，直接返回 `review`。 |
| `regenerate_detailed_summary` | 仅从 `review` 进入；重新生成并校验精细总结，成功后更新对应产物与草稿校验报告，直接返回 `review`。 |

初次处理按 `prepare → deduplicate → extract → metadata → classify → rough_summary → detailed_summary → validate → review` 顺序执行。重新生成由待审阅任务发起，更新该阶段产物与校验报告，随后返回 `review`。任务内容列表为元数据、分类、粗略总结和精细总结分别提供重生成按钮。

分类生成使用正式 taxonomy 和任务共享缓冲。模型可以直接引用正式或临时分类、标签 ID，文献类型仍使用正式 ID 或单任务候选。LLM 输出需校验字段、引用与截断，不编造信息。外发内容遵循用户授权；不将 API 密钥或 PDF 密码写入任务。

模型可以用 `proposed_categories` 和 `proposed_tags` 提交新定义。分类候选包含 `name`、`description` 和 `reason`，标签候选包含 `name` 和 `reason`。候选校验通过后，任务管理器写入共享缓冲，并在草稿中使用 `T-C001` 或 `T-T001` 形式的临时 ID。临时编号按类型独立递增。无合适文献类型时，模型将 `document_type` 设为 `null`，在 `proposed_document_types` 提交一个包含 `name` 和 `reason` 的候选。

任务入库时，其引用的临时定义作为候选交给正式库。正式记录保存后，任务管理器替换当前任务和其他活动任务中的临时引用，然后从缓冲移除已注册条目。同步失败时保留缓冲，重试入库可继续同步。历史快照保留当时的引用。

## 任务目录

路径为 task 目录内的相对路径，任务根目录待配置；未运行的阶段文件可以不存在。

```text
task/taxonomy_buffer.json        # 全部任务共用，首次登记候选时创建
task/<task_id>/
  task.json                      # 状态和产物索引
  input/source.pdf               # 保持不变的输入副本
  duplicate/result.json          # 哈希和查重结果
  extraction/
    pdf_info.json                # PDF 检查结果
    extraction.json              # ExtractionResult，含文档和问题
    extracted.md                 # 提取原文
    quality.json                 # 质量报告
  analysis/
    metadata.json                # 元数据及文件名
    classification.json          # 分类引用和新增定义候选
    rough_summary.txt            # 中文粗略总结，对应正式记录的 summary
    detailed_summary.md          # 中文精细总结
  validation/report.json          # 草稿校验问题及结果
  history/                       # 回退后保留的旧产物，按运行编号分目录
```

`metadata.json` 包含 `title`、`authors`、`year`、`original_filename`、`filename`、`doi`、`arxiv_id`，后两项为可空的辅助字段。`classification.json` 包含 `primary_category`、`tags`、`document_type` 和可选的 `proposed_document_types`。若引用临时 ID，`pending_categories` 和 `pending_tags` 会附上相应定义，供任务预览。共享缓冲 JSON 包含 `category_index`、`tag_index` 和 `counters`，入库时以其中的条目为准。PDF 检查和提取 JSON 使用现有模块模型。

## task.json 模型

以下为初始状态示例；时间为北京时间 ISO 8601，未发生时为 null。所有产物路径均为 task 内安全相对路径。

```json
{
  "task_id": "task-20261111-0001",
  "status": "pending",
  "current_stage": "prepare",
  "created_at": "2026-11-11T10:00:00+08:00",
  "updated_at": "2026-11-11T10:00:00+08:00",
  "source": {"original_filename": "source.pdf", "copy_path": "input/source.pdf", "sha256": null},
  "duplicate_of": null,
  "stages": {
    "prepare": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "deduplicate": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "extract": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "metadata": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "classify": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "rough_summary": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "detailed_summary": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "validate": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "review": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "vectorize": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "regenerate_classification": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "regenerate_rough_summary": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null},
    "regenerate_detailed_summary": {"status": "pending", "attempts": 0, "started_at": null, "finished_at": null, "artifacts": [], "error": null, "wait_reason": null}
  }
}
```

任务 `status` 取 `pending`、`running`、`waiting`、`failed`、`completed`、`duplicate`、`cancelled`。阶段状态取 `pending`、`running`、`waiting`、`failed`、`completed`、`skipped`；只有完成或有理由跳过才能推进。`current_stage` 为当前或下一阶段，终态为 null；`duplicate_of` 保存匹配论文 ID。`attempts` 记录启动次数，`artifacts` 是当前有效产物路径数组；`error` 为 null 或 `{ "code": "...", "message": "..." }`，`wait_reason` 为可空说明。任务创建前检查已有任务，创建 task 后 `prepare` 完成副本校验；查重时将哈希持久化。

## 状态回调模型

定义独立的 `TaskStatusUpdate` 数据结构传给回调，用于通知上层和前端；它是已持久化状态的快照，不替代 `task.json`，回调不直接修改任务。建议字段：`task_id`、`status`、`current_stage`、`stage_status`、`updated_at`、`message`、`error` 和 `wait_reason`；无当前阶段或错误时对应字段为 null。每次状态保存成功后发送快照；回调失败不撤销已保存状态，由上层记录或重试通知，前端重新连接时从持久化状态获取最新快照。回调执行、推送及重试方式由上层实现。

用户审阅时任务和 `review` 均为 `waiting`，循环退出；接受有效草稿后将阶段及任务标记 `completed`。用户请求重新生成时，仅允许从 `review` 的等待状态进入对应重新生成状态，将任务和该状态设为 `running`；保存、校验并发布新产物后，将该状态设为 `completed`，`current_stage` 设为 `review`，任务与 `review` 设为 `waiting` 并退出循环。每次同类请求重新启动对应状态并递增 `attempts`，重复次数不限。用户选择暂不处理时保持等待，取消则标记 `cancelled`。

重新生成前保留当前有效版本，新版本先暂存并校验，成功后再替换目标产物、归档旧版本并刷新草稿校验报告；不重置其他生成阶段或自动改写其产物。报告须检查其他产物与新结果的关联；无法确认一致时标记待审阅，不自动认定有效。失败或中断时保留原有效产物，记录本次错误并返回 `review` 等待用户重试或处理；恢复时先核对是否已发布新版本，避免重复调用。状态和报告发布的中断恢复细节需在实现时确保一致性。

## 断点与回退

- 阶段产物先写临时文件、校验并发布，再原子更新 task 状态；失败或等待时退出循环，不无限重试。异常退出遗留的 `running` 阶段须核对，不能自动视为成功。
- 用户在 `review` 发起的重新生成操作仅更新目标产物与校验报告，旧版本保存在 history。
- 单个 task 同时只允许一个执行者。`PaperWorkflow.run()` 执行到审阅。正式入库成功后，任务进入 `vectorize`。用户触发时，任务管理器调用 `StageHandlers.execute("vectorize", task)` 并记录结果。阶段处理器读取对应资料库，复用应用提供的向量服务。向量失败时任务停在该阶段，成功后任务完成。

## 代码模块设计

网页的「上传并处理」调用 `POST /api/upload-paper`，带服务密码和 `X-Process-Paper: true`。上传成功后，服务按 PDF 哈希创建或复用任务，返回 `task_id`、`status` 和 `current_stage`。尚未启动的任务在响应后执行，可在「任务状态」中刷新查看。后台执行由当前服务进程负责。请求未指定处理时沿用单纯保存 PDF 的上传行为。

流水线按以下职责划分。PaperProcessing 管理任务模型和任务文件，RepoManager 管理正式资料库。

```text
src/PaperProcessing/
  __init__.py        # 暴露上层使用的入口和数据类型
  models.py          # 任务、审阅操作及草稿校验模型
  task_manager.py    # 任务调度、状态持久化和产物读写
  workflow.py        # 状态循环、状态转移和审阅命令
  stages.py          # 阶段处理函数，调用 PDF、查重和内容生成能力
  validation.py      # 待入库草稿及生成结果校验
  interfaces.py      # PDF 提取、内容生成器与状态回调的协议
```

| 模块 | 职责 |
| --- | --- |
| `models.py` | 定义任务与阶段记录、状态快照、审阅操作及草稿校验结果。 |
| `workflow.py` | 检查状态转移并执行阶段，将状态变化交给 TaskManager。审阅等待和失败时结束本次循环。 |
| `task_manager.py` | 对外提供任务创建、运行、状态读取、重新生成及归档入口，管理任务文件。 |
| `stages.py` | 实现查重、PDF 提取、元数据、分类、粗略总结、精细总结等阶段；依赖现有哈希、资料读取、PDF 服务以及注入的内容生成器。初次生成和重新生成共享生成函数，由 workflow 决定下一状态。 |
| `validation.py` | 校验尚未入库的草稿、分类引用及候选定义，产生结构化问题列表；重新生成后复用同一校验能力更新报告。 |
| `interfaces.py` | 定义 PDF 内容提取、内容生成器及状态回调的接口，使 workflow 不依赖特定 PDF 后端、LLM 或前端推送方式。 |

调用路径为上层 → `TaskManager` → `PaperWorkflow` → 阶段处理与校验。工作流通过 TaskManager 读写任务文件。

调用方通过 `TaskManager.create_task(source)` 创建任务，通过 `run_task(task_id)` 执行，通过 `get_status(task_id)` 查询。待审阅且未入库时可调用 `regenerate_task(task_id, action, additional_prompt="")`，完成后返回待审阅。重新生成接口 `POST /api/tasks/{task_id}/regenerate/{action}` 接受可选的 JSON 字段 `additional_prompt`。提示词仅随当前操作传给模型，最大长度见 `REGENERATION_MAX_PROMPT_CHARS`。

## 模块内部接口草案

以下签名用于说明职责，均为待实现接口；`Path` 表示本地路径，`ArtifactPath` 表示经校验的 task 内相对路径，领域类型定义在 `models.py`。调用出错时抛出明确异常，由 workflow 记录并确定任务状态；可预期的重复或等待使用结果类型表达。

### `models.py`

- `ReviewAction` 限定接受、重新生成元数据、分类、粗略总结、精细总结和取消。`Task`、阶段记录及回调快照由 `RepoManager` 定义。
- `StageResult`：阶段执行结果，包含 `outcome`（`completed`、`waiting` 或 `duplicate`）、已暂存产物、问题及可选的重复论文 ID；不包含下一状态。
- `ValidationReport`：结构化问题列表，每项包含代码、说明、严重程度和可选字段或来源；提供 `has_blocking_issues`，表示存在阻断问题。
- `PaperDraft`：待审阅的元数据、分类、概述、精细总结及 PDF 引用；允许新增分类等候选定义，不能当作已入库记录。

### `workflow.py`

```python
class PaperWorkflow:
    def run(self, task: Task, *, additional_prompt: str = "") -> Task: ...
    def submit_review(self, task: Task, action: ReviewAction, *, additional_prompt: str = "") -> Task: ...
```

TaskManager 加载任务并将其交给工作流，通过同步的 `on_transition` 处理每次状态变化。TaskManager 更新时间并保存 `task.json`，保存成功后才发送状态快照。`run` 运行至等待、失败、重复或完成后返回，`submit_review` 执行待审阅任务的操作。

### `PaperProcessing.TaskManager`

```python
class TaskManager:
    def create_task(self, source: Path) -> Task: ...
    def artifact_path(self, task_id: str, path: str = "") -> Path: ...
    def find_by_source_hash(self, sha256: str) -> list[str]: ...
    def create(self, task: Task, source: Path) -> None: ...
    def load(self, task_id: str) -> Task: ...
    def save(self, task: Task) -> None: ...
    def read_artifact(self, task_id: str, path: ArtifactPath) -> bytes: ...
    def publish_artifacts(self, task_id: str, outputs: dict[str, str]) -> None: ...
    def publish_regeneration(self, task_id: str, outputs: dict[str, str], attempt: int, report_text: str) -> None: ...
```

`find_by_source_hash` 返回匹配任务 ID，调用方处理多个匹配。`create` 不覆盖现有任务。工作流决定何时发布，TaskManager 写入临时文件并原子替换单个文件。`publish_regeneration` 先归档旧产物，再发布新产物与校验报告，发布异常时恢复已替换的草稿。所有读写均限制在任务目录内。多文件发布仍可能在进程中断时部分完成。

### `stages.py`

```python
class StageHandlers:
    def prepare(self, task: Task) -> StageResult: ...
    def deduplicate(self, task: Task) -> StageResult: ...
    def extract(self, task: Task) -> StageResult: ...
    def metadata(self, task: Task) -> StageResult: ...
    def classify(self, task: Task) -> StageResult: ...
    def rough_summary(self, task: Task) -> StageResult: ...
    def detailed_summary(self, task: Task) -> StageResult: ...
```

处理器读取必要输入、调用依赖并将结果交给 workflow。重新生成状态分别复用 `metadata`、`classify`、`rough_summary` 和 `detailed_summary`。workflow 归档旧版本、协调发布和刷新报告，之后返回 `review`。

### `validation.py`

```python
def validate_draft(draft: PaperDraft, taxonomy: dict) -> ValidationReport: ...
def validate_artifact(stage: str, data: bytes) -> ValidationReport: ...
```

前者检查草稿完整性、引用与跨产物一致性；后者检查单阶段候选产物的格式和必需内容。重新生成时先检查候选，再基于候选和其他当前产物检查整份草稿；阻断问题在审阅时展示。草稿校验不要求正式 `paper_id` 和 `added_at`，也不替代入库后的正式资料校验。

### `interfaces.py`

```python
class PaperExtractor(Protocol):
    def inspect_pdf(self, source: PdfSource) -> PdfInfo: ...
    def extract_document(self, source: PdfSource, options: ExtractOptions) -> ExtractionResult: ...
    def export_markdown(self, document: ExtractedDocument, *, include_locations: bool = True) -> str: ...

class ContentGenerator(Protocol):
    def generate_metadata(self, text: str, *, additional_prompt: str = "") -> dict: ...
    def generate_classification(self, text: str, taxonomy: dict, *, additional_prompt: str = "") -> dict: ...
    def generate_rough_summary(self, text: str, *, additional_prompt: str = "") -> str: ...
    def generate_detailed_summary(self, text: str, *, additional_prompt: str = "") -> str: ...

class StatusCallback(Protocol):
    def __call__(self, update: TaskStatusUpdate) -> None: ...
```

`PaperExtractor` 使用 `src.PDFProcessing` 的数据模型，由现有 `PdfProcessingService` 提供相应能力；`extract_document` 返回状态、文档、问题和质量报告，阶段处理器检查结果后再调用 `export_markdown` 并保存产物。具体适配时以现有方法签名为准，接口本身不写文件或管理任务状态。

生成器只产生候选内容；模型调用、提示词和响应解析由具体实现负责，阶段和校验模块不得假设内容一定正确。回调只接收状态快照，不负责状态持久化；失败时不回滚任务，通知重试由上层处理。
