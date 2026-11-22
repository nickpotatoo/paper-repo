"""读取阶段输入，执行分析并返回结果，由任务管理器发布。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from src.RepoManager import load_papers
from src.hash_duplicate import hash_file
from . import taxonomy_buffer
from .models import IngestDraft, StageResult, Task, ValidationReport
from .validation import VALIDATION_ARTIFACT, validate_draft

if TYPE_CHECKING:
    from src.RepoManager import RepoManager
    from .interfaces import ContentGenerator, PaperExtractor

logger = logging.getLogger(__name__)

_DRAFT_ARTIFACTS = {
    "metadata": "analysis/metadata.json",
    "classification": taxonomy_buffer.CLASSIFICATION_ARTIFACT,
    "rough_summary": "analysis/rough_summary.txt",
    "detailed_summary": "analysis/detailed_summary.md",
}
_REGENERATION_INPUTS = {
    "regenerate_metadata": "metadata", "regenerate_classification": "classify",
    "regenerate_rough_summary": "rough_summary", "regenerate_detailed_summary": "detailed_summary",
}


class TaskInputs(Protocol):
    def artifact_path(self, task_id: str, path: str) -> Path: ...
    def read_artifact(self, task_id: str, path: str) -> bytes: ...
    def read_classification_buffer(self) -> dict: ...


class StageHandlers:
    def __init__(
        self, inputs: TaskInputs, repo: RepoManager, *,
        extractor: PaperExtractor | None = None, generator: ContentGenerator | None = None,
    ):
        self.inputs = inputs
        self.repo = repo
        self._extractor = extractor
        self._generator = generator

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

    def execute(self, stage: str, task: Task, *, additional_prompt: str = "") -> StageResult:
        if stage in _REGENERATION_INPUTS:
            result = self._generate(_REGENERATION_INPUTS[stage], task, additional_prompt)
            report = self._validate(task, result.artifacts, result.pending_taxonomy)
            if report.has_blocking_issues:
                raise ValueError("重新生成的草稿校验未通过")
            result.artifacts[VALIDATION_ARTIFACT] = report.model_dump_json(indent=2)
            return result
        if stage == "validate":
            report = self._validate(task)
            return StageResult(
                artifacts={VALIDATION_ARTIFACT: report.model_dump_json(indent=2)},
                error=ValueError("草稿校验未通过") if report.has_blocking_issues else None,
            )
        if stage == "ingest":
            return StageResult(ingest=self._prepare_ingest(task))
        if stage == "vectorize":
            self._execute_vector(task)
            return StageResult()

        source = self.inputs.artifact_path(task.task_id, task.source.copy_path)
        if stage == "prepare":
            if hash_file(source) != task.source.sha256:
                raise ValueError("PDF 副本哈希不一致")
            return StageResult()
        if stage == "deduplicate":
            papers, errors = load_papers(self.repo.papers_path)
            if errors:
                raise ValueError("；".join(errors))
            match = next((p["paper_id"] for p in papers if p["metadata"]["sha256"] == task.source.sha256), None)
            return StageResult(
                artifacts={"duplicate/result.json": json.dumps({"sha256": task.source.sha256, "duplicate_of": match})},
                duplicate_of=match,
            )
        if stage == "extract":
            return self._extract(task, source)
        return self._generate(stage, task)

    def _extract(self, task: Task, source: Path) -> StageResult:
        from src.PDFProcessing.models import ExtractOptions, PdfSource

        pdf = PdfSource(path=source, sha256=task.source.sha256)
        info = self.extractor.inspect_pdf(pdf)
        result = self.extractor.extract_document(pdf, ExtractOptions())
        if result.status != "success" or result.document is None or any(i.severity == "error" for i in result.issues):
            issues = [issue.message for issue in result.issues if issue.severity == "error"]
            detail = "；".join(issues[:3]) or f"{result.backend} 返回 {result.status}"
            raise ValueError(f"PDF 提取失败或不完整：{detail}")
        text = self.extractor.export_markdown(result.document)
        if not text.strip():
            raise ValueError("PDF 提取文本为空")
        return StageResult(artifacts={
            "extraction/pdf_info.json": info.model_dump_json(),
            "extraction/extraction.json": result.model_dump_json(),
            "extraction/quality.json": result.quality.model_dump_json() if result.quality else "{}",
            "extraction/extracted.md": text,
        })

    def _generate(self, stage: str, task: Task, additional_prompt: str = "") -> StageResult:
        text = self.inputs.read_artifact(task.task_id, "extraction/extracted.md").decode("utf-8")
        options = {"additional_prompt": additional_prompt} if additional_prompt else {}
        if stage == "metadata":
            data = dict(self.generator.generate_metadata(text, **options))
            data["original_filename"] = task.source.original_filename
            return StageResult(artifacts={_DRAFT_ARTIFACTS["metadata"]: json.dumps(data, ensure_ascii=False)})
        if stage == "classify":
            taxonomy = self.repo.get_taxonomy()
            pending = self.inputs.read_classification_buffer()
            counters = dict(pending["counters"])
            context = taxonomy_buffer.taxonomy_with_pending(taxonomy, pending)
            generated = self.generator.generate_classification(text, context, **options)
            draft = taxonomy_buffer.buffer_classification(generated, taxonomy, pending)
            return StageResult(
                artifacts={_DRAFT_ARTIFACTS["classification"]: json.dumps(draft, ensure_ascii=False, indent=2)},
                pending_taxonomy=pending if pending["counters"] != counters else None,
            )
        if stage == "rough_summary":
            return StageResult(artifacts={_DRAFT_ARTIFACTS[stage]: self.generator.generate_rough_summary(text, **options)})
        if stage == "detailed_summary":
            return StageResult(artifacts={_DRAFT_ARTIFACTS[stage]: self.generator.generate_detailed_summary(text, **options)})
        raise ValueError(f"未知阶段: {stage}")

    def _read_draft(self, task: Task, replacements: dict[str, str] | None = None) -> dict:
        replacements = replacements or {}
        draft = {}
        for field, path in _DRAFT_ARTIFACTS.items():
            content = replacements.get(path)
            if content is None:
                content = self.inputs.read_artifact(task.task_id, path).decode("utf-8")
            draft[field] = json.loads(content) if path.endswith(".json") else content
        return draft

    def _validate(
        self, task: Task, replacements: dict[str, str] | None = None, pending: dict | None = None,
    ) -> ValidationReport:
        source = self.inputs.artifact_path(task.task_id, task.source.copy_path)
        draft = self._read_draft(task, replacements)
        draft["pdf_valid"] = source.is_file() and hash_file(source) == task.source.sha256
        if pending is None:
            pending = self.inputs.read_classification_buffer()
        return validate_draft(draft, taxonomy_buffer.taxonomy_with_pending(self.repo.get_taxonomy(), pending))

    def _prepare_ingest(self, task: Task) -> IngestDraft:
        if task.source.sha256 is None:
            raise ValueError("任务缺少原始 PDF 哈希")
        try:
            draft = self._read_draft(task)
            source = self.inputs.artifact_path(task.task_id, task.source.copy_path)
            if not source.is_file():
                raise FileNotFoundError(source)
        except FileNotFoundError:
            raise ValueError("任务缺少入库所需的 PDF、元数据、分类或总结") from None
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("任务产物不是有效的 UTF-8 文本或 JSON") from None

        classification = taxonomy_buffer.pending_as_proposals(
            draft["classification"], self.inputs.read_classification_buffer(),
        )
        return IngestDraft(
            source=source, sha256=task.source.sha256, original_filename=task.source.original_filename,
            metadata=draft["metadata"], classification=classification,
            summary=draft["rough_summary"], detailed_summary=draft["detailed_summary"],
        )

    def _execute_vector(self, task: Task) -> None:
        paper_id = self._vector_paper_id(task)
        from src.SemanticSearch.paper_vector_service import PaperVectorService

        try:
            with PaperVectorService(
                papers_path=self.repo.papers_path, taxonomy_path=self.repo.taxonomy_path,
                detailed_summaries_dir=self.repo.summaries_dir, vectors_dir=self.repo.vectors_dir,
            ) as service:
                results = service.create_vector(paper_id)
            if any(result["paper_id"] == paper_id and result["saved"] is True for result in results):
                return
        except Exception as error:
            logger.warning("任务向量生成失败：%s", type(error).__name__)
            raise RuntimeError("向量生成失败，可以重试") from error
        raise RuntimeError("向量生成失败，可以重试")

    def _vector_paper_id(self, task: Task) -> str:
        paper_id = task.paper_id
        if paper_id is None:
            raise ValueError("论文尚未入库")
        try:
            paper = self.repo.get_paper(paper_id)
        except KeyError:
            raise ValueError("任务关联的论文已不在资料库") from None
        if paper["metadata"]["sha256"] != task.source.sha256:
            raise ValueError("入库编号对应的论文与任务原件不一致")
        return paper_id
