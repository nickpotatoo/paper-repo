"""PyMuPDF 仅用于检查和渲染，不参与论文理解或入库。"""

from contextlib import contextmanager

import pymupdf

from ..errors import PasswordRequiredError, PdfReadError
from ..models import PageImage, PageInfo, PageRenderOptions, PdfInfo, PdfSource


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
