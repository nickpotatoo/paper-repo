"""Docling 适配器：第三方对象只在此模块内转为项目自有模型。"""

from collections.abc import Callable
from importlib.metadata import version

from pydantic import ValidationError

from src.config import DOCLING_MODELS_DIR

from ..errors import UnsupportedFeatureError
from ..models import (
    AssetReference, BoundingBox, ContentBlock, ExtractedDocument, ExtractOptions, ExtractionResult,
    PageInfo, PdfSource, ProcessingIssue, SourceLocation, TableCell, TableData,
)


def _value(value) -> str:
    return str(getattr(value, "value", value)).lower()


def _converter(options: ExtractOptions):
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.utils.model_downloader import download_models

    artifacts_path = DOCLING_MODELS_DIR.resolve()
    download_models(
        output_dir=artifacts_path,
        with_layout=True,
        with_tableformer=options.extract_tables,
        with_code_formula=options.recognize_formulas,
        with_picture_classifier=False,
        with_rapidocr=options.ocr != "off",
    )
    pipeline = PdfPipelineOptions(
        artifacts_path=artifacts_path,
        do_ocr=options.ocr != "off", do_table_structure=options.extract_tables,
        do_formula_enrichment=options.recognize_formulas, enable_remote_services=False,
        ocr_options=RapidOcrOptions(force_full_page_ocr=options.ocr == "force"),
    )
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)},
    )


def _locations(item, pages: dict[int, PageInfo], issues: list[ProcessingIssue], block_id: str, options: ExtractOptions):
    locations = []
    for provenance in getattr(item, "prov", []):
        page_number = int(provenance.page_no)
        if page_number < options.page_start or (options.page_end is not None and page_number > options.page_end):
            continue
        if page_number not in pages:
            issues.append(ProcessingIssue(code="unknown_page", message="后端来源位置引用了缺失页面", block_id=block_id, severity="error"))
            continue
        page = pages[page_number]
        box = getattr(provenance, "bbox", None)
        bbox = None
        if box is not None:
            top, bottom = float(box.t), float(box.b)
            origin = _value(box.coord_origin).replace("_", "")
            if origin == "bottomleft":
                top, bottom = page.height - top, page.height - bottom
            elif origin != "topleft":
                raise ValueError("不支持的坐标原点")
            try:
                bbox = BoundingBox(
                    x0=float(box.l) / page.width, x1=float(box.r) / page.width,
                    y0=min(top, bottom) / page.height, y1=max(top, bottom) / page.height,
                )
            except ValidationError:
                issues.append(ProcessingIssue(code="invalid_bbox", message="区域坐标无效，保留页码供核对", block_id=block_id))
        locations.append(SourceLocation(page_number=page_number, printed_page_label=page.printed_page_label, bbox=bbox))
    return locations


def _table(item) -> TableData | None:
    data = getattr(item, "data", None)
    if data is None or not getattr(data, "num_rows", 0) or not getattr(data, "num_cols", 0):
        return None
    return TableData(
        rows=data.num_rows, columns=data.num_cols,
        cells=[TableCell(
            row=cell.start_row_offset_idx, column=cell.start_col_offset_idx,
            row_span=cell.end_row_offset_idx - cell.start_row_offset_idx,
            column_span=cell.end_col_offset_idx - cell.start_col_offset_idx,
            text=cell.text, is_header=bool(getattr(cell, "column_header", False) or getattr(cell, "row_header", False)),
        ) for cell in data.table_cells],
    )


class DoclingBackend:
    def __init__(self, converter_factory: Callable | None = None):
        self._converter_factory = converter_factory or _converter

    def extract_document(self, source: PdfSource, options: ExtractOptions) -> ExtractionResult:
        if source.password is not None:
            raise UnsupportedFeatureError("当前 Docling 适配器不处理加密 PDF；请先提供解密后的副本")
        converter = self._converter_factory(options)
        kwargs = {"raises_on_error": False}
        if options.page_end is not None or options.page_start != 1:
            kwargs["page_range"] = (options.page_start, options.page_end or 2**63 - 1)
        result = converter.convert(source.path, **kwargs)
        status = _value(result.status)
        backend_version = version("docling")
        issues = []
        if status not in ("success", "partial_success"):
            return ExtractionResult(status="failed", backend="docling", backend_version=backend_version, issues=[
                ProcessingIssue(code="conversion_failed", message=f"Docling 转换状态：{status}", severity="error"),
            ])
        original = result.document
        pages = {
            int(number): PageInfo(page_number=int(number), width=page.size.width, height=page.size.height)
            for number, page in original.pages.items()
            if int(number) >= options.page_start and (options.page_end is None or int(number) <= options.page_end)
        }
        blocks = []
        assets = []
        headings = []
        labels = {
            "title": "heading", "section_header": "heading", "text": "paragraph", "paragraph": "paragraph",
            "list_item": "list_item", "table": "table", "formula": "formula", "picture": "figure",
            "caption": "caption", "code": "code",
        }
        for item, _ in original.iterate_items():
            label = _value(item.label)
            block_id = f"B{len(blocks) + 1:06d}"
            try:
                locations = _locations(item, pages, issues, block_id, options)
                if getattr(item, "prov", []) and not locations:
                    continue
                kind = labels.get(label, "other")
                text = getattr(item, "text", "") or ""
                heading_level = (1 if label == "title" else int(getattr(item, "level", 2))) if kind == "heading" else None
                parent_headings = headings.copy() if heading_level is not None else headings
                if heading_level is not None:
                    heading_level = max(1, min(heading_level, 6))
                    while parent_headings and parent_headings[-1][0] >= heading_level:
                        parent_headings.pop()
                asset_id = f"A{len(assets) + 1:06d}" if kind == "figure" else None
                block = ContentBlock(
                    block_id=block_id, kind=kind, text=text, order=len(blocks), locations=locations,
                    parent_id=parent_headings[-1][1] if parent_headings else None, heading_level=heading_level,
                    latex=text if kind == "formula" and options.recognize_formulas and text.strip() else None,
                    table=_table(item) if kind == "table" else None, asset_id=asset_id,
                )
                blocks.append(block)
                if kind == "heading":
                    headings = [*parent_headings, (heading_level, block_id)]
                if asset_id:
                    assets.append(AssetReference(asset_id=asset_id, location=locations[0] if locations else None))
                    issues.append(ProcessingIssue(code="figure_not_exported", message="保留图像位置，未导出图片文件", block_id=block_id))
            except (AttributeError, TypeError, ValueError) as error:
                issues.append(ProcessingIssue(
                    code="block_conversion_failed", message=f"内容块转换失败：{type(error).__name__}",
                    severity="error", block_id=block_id,
                ))
        if getattr(result, "errors", []):
            issues.append(ProcessingIssue(code="backend_errors", message="Docling 报告了提取错误，需核对原文", severity="error"))
        document = ExtractedDocument(source=source, pages=sorted(pages.values(), key=lambda page: page.page_number), blocks=blocks, assets=assets)
        return ExtractionResult(
            status="partial" if status == "partial_success" or any(issue.severity == "error" for issue in issues) else "success",
            document=document, backend="docling", backend_version=backend_version, issues=issues,
        )
