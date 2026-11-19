"""执行论文分析阶段；不负责状态转移。"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from src.hash_duplicate import hash_file
from src.config import PAPERS_PATH, TAXONOMY_PATH
from src.RepoManager import RepoManager, load_papers
from src.SemanticSearch.paper_vector_service import PaperVectorService
from .models import Task
from .validation import validate_draft

if TYPE_CHECKING:
    from .task_manager import TaskManager
    from .interfaces import ContentGenerator, PaperExtractor, PaperVectorGenerator

logger = logging.getLogger(__name__)

_DRAFT_ARTIFACTS = {
    "metadata": "analysis/metadata.json",
    "classification": "analysis/classification.json",
    "rough_summary": "analysis/rough_summary.txt",
    "detailed_summary": "analysis/detailed_summary.md",
}


class VectorGenerationError(RuntimeError):
    """向量服务未能保存本次任务的向量。"""


class StageHandlers:
    def __init__(
        self, storage: TaskManager, extractor: PaperExtractor | None = None,
        generator: ContentGenerator | None = None, *, papers_path=None, taxonomy_path=None,
        vector_service: PaperVectorGenerator | None = None,
    ):
        self.storage = storage
        self._extractor = extractor
        self._generator = generator
        self.papers_path = papers_path
        self.repo = RepoManager(
            papers_path=PAPERS_PATH if papers_path is None else papers_path,
            taxonomy_path=TAXONOMY_PATH if taxonomy_path is None else taxonomy_path,
        )
        self._vector_service = PaperVectorService(self.papers_path, taxonomy_path=taxonomy_path) if vector_service is None else vector_service

    @property
    def extractor(self) -> PaperExtractor:
        if self._extractor is None:
            from src.PDFProcessing.service import PdfProcessingService

            self._extractor = PdfProcessingService()
        return self._extractor

    @property
    def generator(self) -> ContentGenerator:
        if self._generator is None:
            from .llm_content_generator import LLMContentGenerator

            self._generator = LLMContentGenerator()
        return self._generator

    def taxonomy(self):
        return self.repo.get_taxonomy()

    def execute(self, stage: str, task: Task):
        if stage == "vectorize":
            self._execute_vector(task)
            return {}

        source = self.storage.artifact_path(task.task_id, task.source.copy_path)
        if stage == 'prepare':
            if hash_file(source) != task.source.sha256:
                raise ValueError('PDF 副本哈希不一致')
            return {}
        if stage == 'deduplicate':
            papers, errors = load_papers(self.papers_path)
            if errors:
                raise ValueError('；'.join(errors))
            match = next((p['paper_id'] for p in papers if p['metadata']['sha256'] == task.source.sha256), None)
            return {'duplicate/result.json': json.dumps({'sha256': task.source.sha256, 'duplicate_of': match}, ensure_ascii=False), '_duplicate': match}
        if stage == 'extract':
            from src.PDFProcessing.models import ExtractOptions, PdfSource

            pdf = PdfSource(path=source, sha256=task.source.sha256)
            info = self.extractor.inspect_pdf(pdf)
            result = self.extractor.extract_document(pdf, ExtractOptions())
            if result.status != 'success' or result.document is None or any(i.severity == 'error' for i in result.issues):
                raise ValueError('PDF 提取失败或不完整，需要人工处理')
            text = self.extractor.export_markdown(result.document)
            if not text.strip():
                raise ValueError('PDF 提取文本为空')
            return {'extraction/pdf_info.json': info.model_dump_json(), 'extraction/extraction.json': result.model_dump_json(), 'extraction/quality.json': result.quality.model_dump_json() if result.quality else '{}', 'extraction/extracted.md': text}
        text = self.storage.read_artifact(task.task_id, 'extraction/extracted.md').decode('utf-8')
        if stage == 'metadata':
            data = dict(self.generator.generate_metadata(text))
            data['original_filename'] = task.source.original_filename
            return {'analysis/metadata.json': json.dumps(data, ensure_ascii=False)}
        if stage == 'classify':
            return {'analysis/classification.json': json.dumps(self.generator.generate_classification(text, self.taxonomy()), ensure_ascii=False)}
        if stage == 'rough_summary':
            return {'analysis/rough_summary.txt': self.generator.generate_rough_summary(text)}
        if stage == 'detailed_summary':
            return {'analysis/detailed_summary.md': self.generator.generate_detailed_summary(text)}
        if stage == 'vectorize':
            self._execute_vector(task)
            return {}
        raise ValueError(f'未知阶段: {stage}')

    def _read_draft(self, task, *, replacements: dict[str, str] | None = None):
        replacements = replacements or {}
        draft = {}
        for field, path in _DRAFT_ARTIFACTS.items():
            content = replacements[path] if path in replacements else self.storage.read_artifact(task.task_id, path).decode("utf-8")
            draft[field] = json.loads(content) if path.endswith(".json") else content
        return draft

    def draft(self, task, *, replacements: dict[str, str] | None = None):
        source = self.storage.artifact_path(task.task_id, task.source.copy_path)
        draft = self._read_draft(task, replacements=replacements)
        draft["pdf_valid"] = source.is_file() and hash_file(source) == task.source.sha256
        return draft

    def validate(self, task, *, replacements: dict[str, str] | None = None):
        return validate_draft(self.draft(task, replacements=replacements), self.taxonomy())

    def ingest(self, task: Task, manager: RepoManager) -> str:
        if task.paper_id is not None:
            try:
                manager.get_paper(task.paper_id)
            except KeyError:
                raise ValueError("该任务关联的论文已从资料库移除") from None
            return task.paper_id

        if task.source.sha256 is None:
            raise ValueError("任务缺少原始 PDF 哈希")
        try:
            draft = self._read_draft(task)
            source = self.storage.artifact_path(task.task_id, task.source.copy_path)
            if not source.is_file():
                raise FileNotFoundError(source)
        except FileNotFoundError:
            raise ValueError("任务缺少入库所需的 PDF、元数据、分类或总结") from None
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("任务产物不是有效的 UTF-8 文本或 JSON") from None

        return manager.ingest_paper(
            source, sha256=task.source.sha256, original_filename=task.source.original_filename,
            metadata=draft["metadata"], classification=draft["classification"],
            summary=draft["rough_summary"], detailed_summary=draft["detailed_summary"],
        )

    def _execute_vector(self, task: Task) -> None:
        if self._vector_service is None:
            raise VectorGenerationError("论文向量服务尚未启动或已关闭")
        paper_id = task.paper_id
        if paper_id is None:
            raise ValueError("论文尚未入库")
        try:
            paper = self.repo.get_paper(paper_id)
        except KeyError:
            raise ValueError("任务关联的论文已不在资料库") from None
        if paper["metadata"]["sha256"] != task.source.sha256:
            raise ValueError("入库编号对应的论文与任务原件不一致")

        try:
            results = self._vector_service.create_vector(paper_id)
            saved = any(result["paper_id"] == paper_id and result["saved"] is True for result in results)
        except Exception as error:
            logger.warning("任务向量生成失败：%s", type(error).__name__)
            raise VectorGenerationError("向量生成失败，可以重试") from error
        if not saved:
            raise VectorGenerationError("向量生成失败，可以重试")
