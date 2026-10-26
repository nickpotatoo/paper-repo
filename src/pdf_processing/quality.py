"""提取质量启发式检查，不填补缺失内容、不声称验证语义正确性。"""

from .models import ExtractedDocument, ProcessingIssue, QualityReport


def assess_extraction(document: ExtractedDocument) -> QualityReport:
    issues = []
    covered_pages = set()
    characters = 0
    for block in document.blocks:
        characters += len(block.text.strip())
        covered_pages.update(location.page_number for location in block.locations)
        if not block.locations:
            issues.append(ProcessingIssue(code="missing_location", message="内容块缺少原文位置", block_id=block.block_id))
        if "\ufffd" in block.text:
            issues.append(ProcessingIssue(code="replacement_character", message="文本包含替换字符，需核对乱码", block_id=block.block_id))
        if block.kind == "formula" and not block.latex:
            issues.append(ProcessingIssue(code="formula_unresolved", message="公式未恢复为 LaTeX，需查看原页", block_id=block.block_id))
        if block.kind == "table" and block.table is None:
            issues.append(ProcessingIssue(code="table_unresolved", message="表格未恢复行列结构", block_id=block.block_id))
    for page in document.pages:
        if page.page_number not in covered_pages:
            issues.append(ProcessingIssue(code="page_without_content", message="页面未提取到有来源位置的内容", page_number=page.page_number))
    if not document.blocks:
        issues.append(ProcessingIssue(code="empty_document", message="未提取到任何内容块", severity="error"))
    return QualityReport(issues=issues, text_characters=characters, pages_with_content=len(covered_pages))
