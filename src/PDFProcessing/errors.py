"""业务输入/依赖错误；可恢复的提取缺失通过 ExtractionResult.issues 报告。"""


class PdfProcessingError(Exception):
    pass


class PdfReadError(PdfProcessingError):
    pass


class PasswordRequiredError(PdfReadError):
    pass


class UnsupportedFeatureError(PdfProcessingError):
    pass
