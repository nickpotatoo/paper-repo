"""能力契约，不依赖解析后端、服务框架或工作流。"""

from typing import Protocol

from .models import ExtractOptions, ExtractionResult, PageImage, PageRenderOptions, PdfInfo, PdfSource


class PdfInspector(Protocol):
    def inspect_pdf(self, source: PdfSource) -> PdfInfo: ...


class PdfExtractor(Protocol):
    def extract_document(self, source: PdfSource, options: ExtractOptions) -> ExtractionResult: ...


class PdfRenderer(Protocol):
    def render_page(self, source: PdfSource, options: PageRenderOptions) -> PageImage: ...
