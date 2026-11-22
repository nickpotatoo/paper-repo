"""PyMuPDF 检查、文本层提取与渲染。"""

from contextlib import contextmanager

import pymupdf

from ..errors import PasswordRequiredError, PdfReadError, UnsupportedFeatureError
from ..models import (
    BoundingBox, ContentBlock, ExtractedDocument, ExtractOptions, ExtractionResult,
    PageImage, PageInfo, PageRenderOptions, PdfInfo, PdfSource, ProcessingIssue, SourceLocation,
)


class PyMuPDFBackend:
    @contextmanager
    def _open(self, source: PdfSource):
        try:
            pdf = pymupdf.open(source.path)
        except Exception as error:
            raise PdfReadError("无法打开 PDF，请检查文件是否损坏") from error
        try:
            encrypted = bool(pdf.is_encrypted or pdf.needs_pass)
            if pdf.needs_pass:
                password = source.password.get_secret_value() if source.password else ""
                if not password or not pdf.authenticate(password):
                    raise PasswordRequiredError("PDF 需要有效密码")
            yield pdf, encrypted
        finally:
            pdf.close()

    def inspect_pdf(self, source: PdfSource) -> PdfInfo:
        with self._open(source) as (pdf, encrypted):
            pages = [
                PageInfo(
                    page_number=number + 1, width=page.rect.width, height=page.rect.height,
                    has_text_layer=bool(page.get_text().strip()), printed_page_label=page.get_label() or None,
                )
                for number, page in enumerate(pdf)
            ]
            return PdfInfo(
                source=source, page_count=len(pdf), encrypted=encrypted, pages=pages,
                metadata={key: str(value) for key, value in (pdf.metadata or {}).items() if value},
            )

    def render_page(self, source: PdfSource, options: PageRenderOptions) -> PageImage:
        with self._open(source) as (pdf, _):
            if options.page_number > len(pdf):
                raise PdfReadError("渲染页码超出 PDF 范围")
            page = pdf[options.page_number - 1]
            rect = page.rect
            region = options.region
            clip = pymupdf.Rect(
                rect.x0 + region.x0 * rect.width, rect.y0 + region.y0 * rect.height,
                rect.x0 + region.x1 * rect.width, rect.y0 + region.y1 * rect.height,
            ) if region else rect
            image = page.get_pixmap(matrix=pymupdf.Matrix(options.dpi / 72, options.dpi / 72), clip=clip, alpha=False)
            return PageImage(
                page_number=options.page_number, width=image.width, height=image.height, data=image.tobytes("png"),
            )

    def extract_document(self, source: PdfSource, options: ExtractOptions) -> ExtractionResult:
        if options.ocr == "force":
            raise UnsupportedFeatureError("强制 OCR 需要启用 Docling 模型")
        pages, blocks, issues = [], [], []
        with self._open(source) as (pdf, _):
            last_page = min(options.page_end or len(pdf), len(pdf))
            for page_index in range(options.page_start - 1, last_page):
                page = pdf[page_index]
                rect = page.rect
                number = page_index + 1
                printed_label = page.get_label() or None
                text_blocks = [block for block in page.get_text("blocks", sort=True) if block[6] == 0 and block[4].strip()]
                pages.append(PageInfo(
                    page_number=number, width=rect.width, height=rect.height,
                    has_text_layer=bool(text_blocks), printed_page_label=printed_label,
                ))
                if not text_blocks and page.get_images():
                    issues.append(ProcessingIssue(
                        code="ocr_required", severity="error", page_number=number,
                        message=f"第 {number} 页没有文本层，需要启用 Docling 模型进行 OCR",
                    ))
                for block in text_blocks:
                    region = (pymupdf.Rect(block[:4]) * page.rotation_matrix) & rect
                    bbox = None if region.is_empty else BoundingBox(
                        x0=(region.x0 - rect.x0) / rect.width, y0=(region.y0 - rect.y0) / rect.height,
                        x1=(region.x1 - rect.x0) / rect.width, y1=(region.y1 - rect.y0) / rect.height,
                    )
                    blocks.append(ContentBlock(
                        block_id=f"B{len(blocks) + 1:06d}", order=len(blocks), kind="paragraph", text=block[4].strip(),
                        locations=[SourceLocation(page_number=number, printed_page_label=printed_label, bbox=bbox)],
                    ))
        if not blocks and not issues:
            issues.append(ProcessingIssue(code="empty_document", severity="error", message="所选页面没有可提取的 PDF 文本层"))
        status = "failed" if not blocks else "partial" if issues else "success"
        return ExtractionResult(
            status=status, document=ExtractedDocument(source=source, pages=pages, blocks=blocks),
            backend="pymupdf", backend_version=pymupdf.VersionBind, issues=issues,
        )
