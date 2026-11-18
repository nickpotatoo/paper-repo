"""PDF 能力入口；不处理摘要生成、分类、编号、入库或向量。"""

from src.hash_duplicate import hash_file

from .backends.docling_backend import DoclingBackend
from .backends.pymupdf_backend import PyMuPDFBackend
from .errors import PdfReadError
from .interfaces import PdfExtractor, PdfInspector, PdfRenderer
from .markdown import export_markdown
from .models import ExtractedDocument, ExtractOptions, ExtractionResult, PageImage, PageRenderOptions, PdfInfo, PdfSource, QualityReport
from .quality import assess_extraction


class PdfProcessingService:
    def __init__(
        self, *, extractor: PdfExtractor | None = None,
        inspector: PdfInspector | None = None, renderer: PdfRenderer | None = None,
    ):
        basic = PyMuPDFBackend()
        self._extractor = extractor if extractor is not None else DoclingBackend()
        self._inspector = inspector if inspector is not None else basic
        self._renderer = renderer if renderer is not None else basic

    @staticmethod
    def _check_source(source: PdfSource) -> None:
        if not source.path.is_file():
            raise FileNotFoundError(source.path)
        with source.path.open("rb") as stream:
            if b"%PDF-" not in stream.read(1024):
                raise PdfReadError("文件头中没有 PDF 标记")
        if source.sha256 is not None and hash_file(source.path) != source.sha256:
            raise PdfReadError("源 PDF 哈希与提供的 sha256 不一致")

    def inspect_pdf(self, source: PdfSource) -> PdfInfo:
        self._check_source(source)
        return self._inspector.inspect_pdf(source)

    def extract_document(self, source: PdfSource, options: ExtractOptions | None = None) -> ExtractionResult:
        self._check_source(source)
        result = self._extractor.extract_document(source, options or ExtractOptions()).model_copy(deep=True)
        if result.document is not None:
            result.quality = assess_extraction(result.document)
            result.issues.extend(result.quality.issues)
            if result.status != "failed" and any(issue.severity == "error" for issue in result.issues):
                result.status = "partial" if result.document.blocks else "failed"
        return result

    def render_page(self, source: PdfSource, options: PageRenderOptions) -> PageImage:
        self._check_source(source)
        return self._renderer.render_page(source, options)

    @staticmethod
    def export_markdown(document: ExtractedDocument, *, include_locations: bool = True) -> str:
        return export_markdown(document, include_locations=include_locations)

    @staticmethod
    def assess_extraction(document: ExtractedDocument) -> QualityReport:
        return assess_extraction(document)
