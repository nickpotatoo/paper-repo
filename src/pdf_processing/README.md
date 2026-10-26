# PDF 处理模块

为新论文 workflow 提供独立的 PDF 检查、结构化提取、来源定位、质量报告和原文 Markdown 导出。开发与测试均在本目录；不接入现有路由，也不修改论文资料、文件名、分类、编号或向量。

## 职责

```text
PdfProcessingService
  ├─ PdfInspector → PyMuPDFBackend
  ├─ PdfExtractor → DoclingBackend
  ├─ PdfRenderer  → PyMuPDFBackend
  ├─ assess_extraction → QualityReport
  └─ export_markdown  → str
```

| 文件 | 职责 |
| --- | --- |
| `models.py` | Pydantic 输入/输出及引用完整性校验 |
| `interfaces.py` | 可替换的检查、解析、渲染 Protocol |
| `service.py` | 检查本地源文件、校验已提供的 SHA-256、能力转发及质量报告合并 |
| `backends/docling_backend.py` | Docling → 自有模型的转换，其他模块不接触第三方对象 |
| `backends/pymupdf_backend.py` | 文件内 metadata、页面文本层检查、整页/区域 PNG 渲染 |
| `quality.py` | 无内容、缺少位置、乱码替换字符、未识别表格/公式等启发式报告 |
| `markdown.py` | 导出提取原文；保留来源注释、LaTeX、表格跨度与代码块 |
| `tests/` | 独立单元测试及临时 PDF 集成测试 |

文件内 title/author 等只是候选信息，不能自动覆盖正式论文记录。导出的 Markdown 是原文转写，不是中文精细总结；摘要、分类和总结由后续论文理解模块负责，编号、时间与 JSON 入库由资料模块负责。

## 依赖

Python 3.10+，使用 Pydantic 2.12+、Docling 和 PyMuPDF。依赖统一在项目根目录的 `requirements.txt` 管理，在项目根目录执行：

```powershell
python -m pip install -r requirements.txt
```

Docling 和 PyMuPDF 按已安装的项目依赖使用，不检查模块是否存在、不捕获缺少依赖的导入错误，也不自动跳过测试。PyMuPDF 直接导入；Docling 在创建实际转换器时普通导入，避免创建 service 就加载解析器。也可注入符合 Protocol 的替代后端，不会静默切换解析器。

Docling 模型统一保存在 `data/models/docling/`，由 `src/config.py` 的 `DOCLING_MODELS_DIR` 配置，可用同名环境变量覆盖。创建实际转换器时，先通过 Docling 的下载接口将布局及已启用的表格、OCR、公式模型下载到该目录，再通过 pipeline 的 `artifacts_path` 从同一目录加载。重复使用时由下载接口复用已有模型；关闭的功能不主动下载对应模型。OCR 显式使用 RapidOCR，确保下载和加载路径一致。

模型目录已排除出 Git；旧用户目录中的缓存不自动搬迁或删除，新目录缺少模型时按需下载。初始化 service 本身不下载模型，实际提取时才准备模型。适配器关闭远程服务，输入只接受本地 PDF；模型下载不会将论文上传到模型托管服务。

PyMuPDF 的 AGPL/商业许可见其官方说明，项目引入时需按实际用途选择许可。依赖文件给出可用版本范围，Docling 实际集成验证后再锁定部署版本。

## 接口

```python
from src.pdf_processing import PdfProcessingService, PdfSource, ExtractOptions, PageRenderOptions

service = PdfProcessingService()
source = PdfSource(path="incoming/paper.pdf")
info = service.inspect_pdf(source)
result = service.extract_document(source, ExtractOptions(
    page_start=1, page_end=None, ocr="auto", extract_tables=True,
    recognize_formulas=False,
))
if result.document is not None:
    markdown = service.export_markdown(result.document)
    quality = result.quality
image = service.render_page(source, PageRenderOptions(page_number=1, dpi=144))
```

- `inspect_pdf(source) -> PdfInfo`：页数、页面尺寸、文本层和候选 metadata；`has_text_layer=None` 表示后端未报告，不等同于没有文本。
- `extract_document(source, options) -> ExtractionResult`：`success` / `partial` / `failed`，统一文档、后端信息、结构化问题列表及质量报告。应同时检查 status 和 issues，成功并不保证内容语义完整。
- `render_page(source, options) -> PageImage`：返回 PNG 字节和尺寸，不写图片文件；`region` 使用归一化坐标。
- `export_markdown(document, include_locations=True) -> str`：纯导出，不写文件。表格使用 HTML 保留合并单元格；无 LaTeX 的公式保留后端文本，不编造公式。
- `assess_extraction(document) -> QualityReport`：可独立调用，仅作启发式检查，不保证识别质量。

`PdfSource.sha256` 可由现有哈希接口计算后传入；传入时服务校验真实文件内容，不自动创建新的论文 ID。密码使用 SecretStr，不写入模型 JSON；PyMuPDF 支持加密 PDF 的检查和渲染，当前 Docling 适配器明确拒绝密码输入，要求先提供解密副本。

## 数据约定与范围

- PDF 实际页码从 1 开始，选取部分页面后仍保留原始页码，不重新编号；印刷页码另存 `printed_page_label`。
- 区域统一为左上角原点，范围 `[0, 1]`。无法转换的区域保留页码并报告问题，不猜测位置。
- 内容按阅读顺序排列，包括标题、段落、列表、表格、公式、图片、题注及代码；标题父关系仅使用后端提供的层级，缺少层级时标题默认 2 级，不依赖数字章节名称推断。
- 表格保存行列、跨度和单元格文本。只有启用公式识别时，才将 Docling 的公式输出视为 LaTeX。
- 图像目前只保存资源编号和来源位置，并报告未导出；不生成描述、不自动落盘图像。可以通过渲染接口核对原页。
- 文档模型 JSON 通过 `model_dump_json()` / `model_validate_json()` 往返，不保存 Docling 原生类型。图片字节使用 base64 JSON 表示；源文件密码始终排除。
- 损坏文件、缺失源文件、错误哈希或不支持的能力通过异常报告；缺少依赖时保留 Python 原始导入错误。可继续处理的块缺失或部分解析失败通过结果及 issues 报告，不补写不存在的原文。
- 服务不保存解析产物、不实现缓存、不进行 agent 调用、论文入库或任何向量操作。解析过程中源文件应保持不变。

## 测试

在项目根目录执行：

```powershell
python -B -m unittest discover -s src/pdf_processing/tests -p "test_*.py" -v
```

模型、导出、服务边界和 Docling 适配测试不下载模型；Docling 使用模拟转换结果及版本信息。PyMuPDF 集成测试在系统临时目录创建 PDF，验证页信息、文本层、整页/区域渲染及密码处理，不按依赖存在性跳过。所有测试均不访问真实论文或向量库。

本环境已完成真实临时 PDF 的 PyMuPDF 检查/渲染测试，并使用 Docling 2.142.1 对本地样本 `samples/P000002/P000002.pdf` 完成真实提取，得到 7 页、137 个内容块。原文 Markdown 为 `samples/P000002/P000002.md`，完整结构和问题报告分别为 `extraction.json`、`report.json`；2 处图像仅保留位置，未导出图片。该次提取关闭 OCR 和公式识别，这两项能力仍待真实样本验证。样本和解析产物由 samples/.gitignore 排除，不纳入 Git。

参考：[Docling](https://github.com/docling-project/docling)、[提取配置](https://docling-project.github.io/docling/reference/pipeline_options/)、[PyMuPDF](https://pymupdf.readthedocs.io/en/latest/)、[Pydantic](https://docs.pydantic.dev/latest/concepts/models/)。
