"""从统一模型导出原文 Markdown；不生成精细总结、不写文件。"""

from html import escape

from .models import ExtractedDocument, TableData


def _table_html(table: TableData) -> str:
    cells = {(cell.row, cell.column): cell for cell in table.cells}
    covered = {
        (row, column)
        for cell in table.cells
        for row in range(cell.row, cell.row + cell.row_span)
        for column in range(cell.column, cell.column + cell.column_span)
        if (row, column) != (cell.row, cell.column)
    }
    rows = []
    for row in range(table.rows):
        values = []
        for column in range(table.columns):
            if (row, column) in covered:
                continue
            cell = cells.get((row, column))
            tag = "th" if cell and cell.is_header else "td"
            spans = f' rowspan="{cell.row_span}" colspan="{cell.column_span}"' if cell else ""
            text = escape(cell.text).replace("\n", "<br>") if cell else ""
            values.append(f"<{tag}{spans}>{text}</{tag}>")
        rows.append("<tr>" + "".join(values) + "</tr>")
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def export_markdown(document: ExtractedDocument, *, include_locations: bool = True) -> str:
    parts = []
    for block in document.blocks:
        if include_locations:
            pages = ",".join(str(number) for number in sorted({loc.page_number for loc in block.locations}))
            # IDs are parser-owned, but escape user-created models as well.
            block_id = escape(block.block_id).replace("--", "&#45;&#45;")
            parts.append(f"<!-- block:{block_id}; pdf_pages:{pages or 'unknown'} -->")
        if block.kind == "heading":
            parts.append("#" * (block.heading_level or 2) + " " + block.text)
        elif block.kind == "formula" and block.latex:
            parts.append("$$\n" + block.latex + "\n$$")
        elif block.kind == "table" and block.table is not None:
            parts.append(_table_html(block.table))
        elif block.kind == "code":
            fence = "```"
            while fence in block.text:
                fence += "`"
            parts.append(f"{fence}\n{block.text}\n{fence}")
        elif block.kind == "list_item":
            parts.append("- " + block.text)
        elif block.kind == "figure":
            parts.append(block.text or "[图像：请按来源位置查阅原 PDF]")
        else:
            parts.append(block.text)
    return "\n\n".join(part for part in parts if part).rstrip() + ("\n" if parts else "")
