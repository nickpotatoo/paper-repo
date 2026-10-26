"""PDF 模块的数据契约；不暴露第三方解析器对象。"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class PdfSource(Model):
    path: Path
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    password: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @field_validator("path")
    @classmethod
    def pdf_extension(cls, path: Path) -> Path:
        if path.suffix.lower() != ".pdf":
            raise ValueError("源文件必须为 PDF")
        return path


class BoundingBox(Model):
    """左上角原点，坐标归一化至 [0, 1]。"""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("区域必须具有正宽度和正高度")
        return self


class SourceLocation(Model):
    page_number: int = Field(ge=1, strict=True)
    printed_page_label: str | None = None
    bbox: BoundingBox | None = None


class PageInfo(Model):
    page_number: int = Field(ge=1, strict=True)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    has_text_layer: bool | None = None
    printed_page_label: str | None = None


class ProcessingIssue(Model):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"
    page_number: int | None = Field(default=None, ge=1, strict=True)
    block_id: str | None = None


class PdfInfo(Model):
    source: PdfSource
    page_count: int = Field(ge=0, strict=True)
    encrypted: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)
    pages: list[PageInfo] = Field(default_factory=list)
    issues: list[ProcessingIssue] = Field(default_factory=list)


class TableCell(Model):
    row: int = Field(ge=0, strict=True)
    column: int = Field(ge=0, strict=True)
    row_span: int = Field(default=1, ge=1, strict=True)
    column_span: int = Field(default=1, ge=1, strict=True)
    text: str = ""
    is_header: bool = False


class TableData(Model):
    rows: int = Field(ge=1, strict=True)
    columns: int = Field(ge=1, strict=True)
    cells: list[TableCell] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_cells(self):
        occupied = set()
        for cell in self.cells:
            if cell.row + cell.row_span > self.rows or cell.column + cell.column_span > self.columns:
                raise ValueError("单元格超出表格范围")
            for row in range(cell.row, cell.row + cell.row_span):
                for column in range(cell.column, cell.column + cell.column_span):
                    if (row, column) in occupied:
                        raise ValueError("表格单元格重叠")
                    occupied.add((row, column))
        return self


BlockType = Literal["heading", "paragraph", "list_item", "table", "formula", "figure", "caption", "code", "other"]


class ContentBlock(Model):
    block_id: str = Field(min_length=1)
    kind: BlockType
    order: int = Field(ge=0, strict=True)
    text: str = ""
    locations: list[SourceLocation] = Field(default_factory=list)
    parent_id: str | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6, strict=True)
    latex: str | None = None
    table: TableData | None = None
    asset_id: str | None = None

    @model_validator(mode="after")
    def matching_payload(self):
        if self.heading_level is not None and self.kind != "heading":
            raise ValueError("heading_level 仅用于标题")
        if self.table is not None and self.kind != "table":
            raise ValueError("table 仅用于表格")
        if self.latex is not None and self.kind != "formula":
            raise ValueError("latex 仅用于公式")
        return self


class AssetReference(Model):
    asset_id: str = Field(min_length=1)
    kind: Literal["image"] = "image"
    location: SourceLocation | None = None
    path: Path | None = None
    media_type: str | None = None


class ExtractedDocument(Model):
    source: PdfSource
    pages: list[PageInfo]
    blocks: list[ContentBlock]
    assets: list[AssetReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_references(self):
        page_numbers = [page.page_number for page in self.pages]
        if len(page_numbers) != len(set(page_numbers)) or page_numbers != sorted(page_numbers):
            raise ValueError("页码必须唯一且升序排列")
        asset_ids = [asset.asset_id for asset in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("资源编号重复")
        if any(asset.location is not None and asset.location.page_number not in page_numbers for asset in self.assets):
            raise ValueError("资源引用了未定义页面")
        seen = set()
        previous_order = -1
        for block in self.blocks:
            if block.block_id in seen or block.order <= previous_order:
                raise ValueError("内容块编号必须唯一，阅读顺序必须递增")
            if block.parent_id is not None and block.parent_id not in seen:
                raise ValueError("父内容块必须已出现，不能前向引用或成环")
            if any(location.page_number not in page_numbers for location in block.locations):
                raise ValueError("内容块引用了未定义页面")
            if block.asset_id is not None and block.asset_id not in asset_ids:
                raise ValueError("内容块引用了未定义资源")
            seen.add(block.block_id)
            previous_order = block.order
        return self


class ExtractOptions(Model):
    page_start: int = Field(default=1, ge=1, strict=True)
    page_end: int | None = Field(default=None, ge=1, strict=True)
    ocr: Literal["auto", "off", "force"] = "auto"
    extract_tables: bool = True
    recognize_formulas: bool = False

    @model_validator(mode="after")
    def page_range(self):
        if self.page_end is not None and self.page_end < self.page_start:
            raise ValueError("结束页不能小于起始页")
        return self


class PageRenderOptions(Model):
    page_number: int = Field(ge=1, strict=True)
    dpi: int = Field(default=144, ge=36, le=600, strict=True)
    region: BoundingBox | None = None


class PageImage(Model):
    model_config = ConfigDict(extra="forbid", ser_json_bytes="base64", val_json_bytes="base64")
    page_number: int = Field(ge=1, strict=True)
    width: int = Field(gt=0, strict=True)
    height: int = Field(gt=0, strict=True)
    media_type: Literal["image/png"] = "image/png"
    data: bytes


class QualityReport(Model):
    issues: list[ProcessingIssue] = Field(default_factory=list)
    text_characters: int = 0
    pages_with_content: int = 0


class ExtractionResult(Model):
    status: Literal["success", "partial", "failed"]
    document: ExtractedDocument | None = None
    backend: str
    backend_version: str | None = None
    issues: list[ProcessingIssue] = Field(default_factory=list)
    quality: QualityReport | None = None

    @model_validator(mode="after")
    def completed_has_document(self):
        if self.status != "failed" and self.document is None:
            raise ValueError("成功或部分成功的结果必须包含文档")
        return self
