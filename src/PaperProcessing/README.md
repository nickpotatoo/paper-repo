# 新论文处理流水线设计

本文是待实现的设计；正式资料格式和维护规则以项目根目录 `AGENTS.md` 为准。一个任务处理一份 PDF，task ID 与论文 ID 独立。

类似一个自动状态机，在上个状态完成后，完成校验，才可进入下一个状态

运行一个循环，完成后退出循环
最好能进行断点续跑，这就要求后一个状态不会污染前一个状态，能够简单的进行状态的回退
说白了就是各种资源分开保存，不可叠加

每个阶段遵循同一顺序：执行 → 保存产物 → 校验产物 → 更新 task 状态

需要建模一个状态数据结构，用于传递给回调函数，向前端更新任务状态

由用户自行决定是否入库，入库与向量生成不由本workflow进行，交由更上层的代码进行
分类、粗略总结、精细总结可被重新生成，即新增三个状态，只有在 review 状态下才可进入，它们执行完后也直接进入 review 状态

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
（以下不为workflow状态）
- 入库
- 入向量库

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
| `review` | 展示草稿与校验结果，用户可选择接受、重新生成分类、概述或精细总结，或暂停。接受后流水线完成并返回草稿；是否入库由上层另行决定。 |
| `regenerate_classification` | 仅从 `review` 进入；重新生成并校验分类候选，成功后更新分类产物与草稿校验报告，直接返回 `review`。 |
| `regenerate_rough_summary` | 仅从 `review` 进入；重新生成并校验粗略总结，成功后更新对应产物与草稿校验报告，直接返回 `review`。 |
| `regenerate_detailed_summary` | 仅从 `review` 进入；重新生成并校验精细总结，成功后更新对应产物与草稿校验报告，直接返回 `review`。 |

初次处理按 `prepare → deduplicate → extract → metadata → classify → rough_summary → detailed_summary → validate → review` 顺序执行。`review` 接受对应用户操作后转入三个重新生成状态之一；这些状态执行完成直接返回 `review`，不会重新运行初次生成阶段，也不会进入独立的 `validate` 状态。更新校验报告作为重新生成状态内部步骤执行；如有阻断问题，返回 `review` 展示问题并禁止接受草稿，用户可再次重新生成或暂停。

分类、标签和文献类型 ID 均来自正式 taxonomy；候选新增定义先确认、分配 ID 并保存后才能被正式记录引用。LLM 输出需校验字段、引用与截断，不编造信息。外发内容遵循用户授权；不将 API 密钥或 PDF 密码写入任务。

草稿中 `primary_category` 和 `document_type` 分别填写已有 ID；无法复用时填写 `null`，并在相应的 `proposed_categories` 或 `proposed_document_types` 中恰好提供一项候选。分类候选包含非空 `name`、`description` 和 `reason`，文献类型候选包含非空 `name` 和 `reason`。`tags` 只包含已有 ID，新增标签候选保存在 `proposed_tags`，每项包含非空 `name` 和 `reason`。候选不携带正式 ID，名称不得重复或与同类现有定义同名；无候选时数组为空（校验兼容缺省数组）。有效候选产生非阻断警告，可以提交审阅和接受草稿，但接受不代表候选已入库：上层入库前必须经用户确认，分配正式 ID、保存 taxonomy 并将草稿中的候选转换为正式引用。

## 任务目录

路径为 task 目录内的相对路径，任务根目录待配置；未运行的阶段文件可以不存在。

```text
tasks/<task_id>/
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

`metadata.json` 包含 `title`、`authors`、`year`、`original_filename`、`filename`、`doi`、`arxiv_id`；后两项为可空的辅助字段。`classification.json` 包含 `primary_category`、`tags`、`document_type`，以及 `proposed_categories`、`proposed_tags`、`proposed_document_types` 候选数组；候选项记录名称、分类描述和审核状态，不将未分配 ID 当作正式引用。PDF 检查和提取 JSON 使用现有模块模型；不存在的内容不伪造。task 中不复制完整正文到状态文件，正式资料和向量仍按配置保存。

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
- 用户在 `review` 发起的三个重新生成操作仅更新目标产物，不触发线性阶段回退；旧版本保存在 history。其他阶段如需回退，需另行设计入口及依赖失效规则。
- 单个 task 同时只允许一个执行者。流水线完成后输出经审阅的草稿和产物路径；入库及向量生成由上层单独管理。上层入库前需重新检查重复、分类引用和文件冲突，按照 `AGENTS.md` 预留编号、写入及校验；向量失败由上层记录和重试，不改变流水线完成状态。

## 代码模块设计

以下为建议的最小划分，尚未实现；沿用现有 `src/PaperProcessing` 目录名称。

```text
src/PaperProcessing/
  __init__.py        # 暴露上层使用的入口和数据类型
  models.py          # 任务、阶段、产物索引及回调数据结构
  workflow.py        # 状态循环、状态转移和审阅命令
  storage.py         # task 目录和产物的读取、暂存及原子发布
  stages.py          # 阶段处理函数，调用 PDF、查重和内容生成能力
  validation.py      # 待入库草稿及生成结果校验
  interfaces.py      # PDF 提取、内容生成器与状态回调的协议
```

| 模块 | 职责 |
| --- | --- |
| `models.py` | 定义阶段与任务状态、`Task`、阶段记录、`TaskStatusUpdate` 和草稿校验结果；与 `task.json` 一一对应，区分任务状态和当前阶段。 |
| `workflow.py` | 向上提供创建、运行或恢复任务、获取状态及提交审阅操作的入口；检查合法转移，驱动对应阶段，持久化状态后调用回调。审阅等待和失败时结束本次循环。 |
| `storage.py` | 管理单个 task 的路径、JSON 和阶段产物，提供暂存、发布、归档和读取；负责路径边界和文件写入，不决定状态转移或调用模型。 |
| `stages.py` | 实现查重、PDF 提取、元数据、分类、粗略总结、精细总结等阶段；依赖现有哈希、资料读取、PDF 服务以及注入的内容生成器。初次生成和重新生成共享生成函数，由 workflow 决定下一状态。 |
| `validation.py` | 校验尚未入库的草稿、分类引用及候选定义，产生结构化问题列表；重新生成后复用同一校验能力更新报告。 |
| `interfaces.py` | 定义 PDF 内容提取、内容生成器及状态回调的接口，使 workflow 不依赖特定 PDF 后端、LLM 或前端推送方式。 |

调用方向为：上层 → `workflow` → 阶段处理 / 校验 / 任务存储；阶段处理通过现有模块或注入的接口获取能力。上层负责用户交互与回调转发；流水线不调用路由、正式入库或向量服务。状态转移集中在 `workflow.py`，阶段函数返回结果和问题，不自行切换状态；`storage.py` 不承担业务校验。

入口可先设计为 `create_task(source)`、`run(task_id)`、`get_status(task_id)` 和 `submit_review(task_id, action)`；其中 `action` 限制为接受、重新生成分类、概述、精细总结或取消。`run` 执行到审阅等待、失败或终态即返回；审阅命令仅在 `review` 等待时接受，重新生成完成后返回等待。具体参数、异常和锁实现待开发时确定。

## 模块内部接口草案

以下签名用于说明职责，均为待实现接口；`Path` 表示本地路径，`ArtifactPath` 表示经校验的 task 内相对路径，领域类型定义在 `models.py`。调用出错时抛出明确异常，由 workflow 记录并确定任务状态；可预期的重复或等待使用结果类型表达。

### `models.py`

- `Task`：对应 `task.json`，包含来源、阶段记录及状态；`StageRecord` 保存状态、次数、时间、产物和问题。
- `TaskStatusUpdate`：供回调使用的已持久化状态快照；`ReviewAction` 限定接受、三种重新生成和取消。
- `StageResult`：阶段执行结果，包含 `outcome`（`completed`、`waiting` 或 `duplicate`）、已暂存产物、问题及可选的重复论文 ID；不包含下一状态。
- `ValidationReport`：结构化问题列表，每项包含代码、说明、严重程度和可选字段或来源；提供 `has_blocking_issues`，表示存在阻断问题。
- `PaperDraft`：待审阅的元数据、分类、概述、精细总结及 PDF 引用；允许新增分类等候选定义，不能当作已入库记录。

### `workflow.py`

```python
class PaperWorkflow:
    def create_task(self, source: Path) -> Task: ...
    def run(self, task_id: str) -> Task: ...
    def get_status(self, task_id: str) -> TaskStatusUpdate: ...
    def submit_review(self, task_id: str, action: ReviewAction) -> Task: ...
```

构造时注入任务存储、阶段处理器和可选状态回调。`create_task` 先按源文件哈希检查已有任务，有匹配时返回该任务，不再创建；否则建立任务并复制 PDF。`run` 从持久化状态恢复，运行至等待、失败、重复或完成后返回。`submit_review` 只接受处于 `review` 等待状态的任务：接受时检查当前报告无阻断问题；重新生成时持久化转移并执行至返回审阅；取消进入终态。任务不存在、状态不允许操作或并发执行冲突时报告明确错误。状态持久化成功后才发回调。

### `storage.py`

```python
class TaskStorage:
    def find_by_source_hash(self, sha256: str) -> list[str]: ...
    def create(self, task: Task, source: Path) -> None: ...
    def load(self, task_id: str) -> Task: ...
    def save(self, task: Task) -> None: ...
    def read_artifact(self, task_id: str, path: ArtifactPath) -> bytes: ...
    def stage_artifact(self, task_id: str, path: ArtifactPath, data: bytes) -> ArtifactPath: ...
    def publish_artifact(self, task_id: str, staged: ArtifactPath, target: ArtifactPath) -> None: ...
    def archive_artifact(self, task_id: str, path: ArtifactPath, attempt: int) -> ArtifactPath: ...
```

`find_by_source_hash` 返回匹配任务 ID，调用方处理多个匹配；`create` 不覆盖现有任务。`stage_artifact` 写入任务内临时位置，`publish_artifact` 原子替换单个文件，`archive_artifact` 保存旧版本。所有读写均限制在任务目录内，状态文件通过 `save` 原子写入；这些接口不保证多个文件整体原子提交，恢复和协调由 workflow 负责。

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

处理器读取必要输入、调用依赖并暂存产物，将结果交给 workflow；不修改 `task.json` 或自行推进阶段。三个重新生成状态分别复用 `classify`、`rough_summary`、`detailed_summary`，由 workflow 保留旧版本、协调发布和刷新报告后直接返回 `review`。`validate` 和 `review` 分别由校验模块与 workflow 处理，不需要额外生成函数。

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
    def generate_metadata(self, text: str) -> dict: ...
    def generate_classification(self, text: str, taxonomy: dict) -> dict: ...
    def generate_rough_summary(self, text: str) -> str: ...
    def generate_detailed_summary(self, text: str) -> str: ...

class StatusCallback(Protocol):
    def __call__(self, update: TaskStatusUpdate) -> None: ...
```

`PaperExtractor` 使用 `src.PDFProcessing` 的数据模型，由现有 `PdfProcessingService` 提供相应能力；`extract_document` 返回状态、文档、问题和质量报告，阶段处理器检查结果后再调用 `export_markdown` 并保存产物。具体适配时以现有方法签名为准，接口本身不写文件或管理任务状态。

生成器只产生候选内容；模型调用、提示词和响应解析由具体实现负责，阶段和校验模块不得假设内容一定正确。回调只接收状态快照，不负责状态持久化；失败时不回滚任务，通知重试由上层处理。
