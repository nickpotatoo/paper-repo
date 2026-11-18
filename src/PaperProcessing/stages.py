"""执行论文分析阶段；不负责状态转移。"""

import json
from pathlib import Path

from src.hash_duplicate import hash_file
from src.RepoManager import load_papers, load_taxonomy
from src.PDFProcessing.models import PdfSource, ExtractOptions
from src.PDFProcessing.service import PdfProcessingService
from src.PaperProcessing.interfaces import PaperExtractor, ContentGenerator
from src.PaperProcessing.llm_content_generator import LLMContentGenerator
from src.PaperProcessing.storage import TaskStorage


class StageHandlers:
    def __init__(self, storage: TaskStorage, extractor: PaperExtractor | None = None, 
                 generator: ContentGenerator | None = None, *, papers_path=None, taxonomy_path=None):
        self.storage = storage
        self.extractor = extractor if extractor is not None else PdfProcessingService()
        self.generator = generator if generator is not None else LLMContentGenerator()
        self.papers_path, self.taxonomy_path = papers_path, taxonomy_path

    def taxonomy(self):
        value, errors = load_taxonomy(self.taxonomy_path)
        if errors:
            raise ValueError('；'.join(errors))
        return value

    def read(self, task, path):
        return self.storage.read_artifact(task.task_id, path).decode('utf-8')

    def execute(self, stage, task):
        source = self.storage._path(task.task_id, task.source.copy_path)
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
            pdf = PdfSource(path=source, sha256=task.source.sha256)
            info = self.extractor.inspect_pdf(pdf)
            result = self.extractor.extract_document(pdf, ExtractOptions())
            if result.status != 'success' or result.document is None or any(i.severity == 'error' for i in result.issues):
                raise ValueError('PDF 提取失败或不完整，需要人工处理')
            text = self.extractor.export_markdown(result.document)
            if not text.strip():
                raise ValueError('PDF 提取文本为空')
            return {'extraction/pdf_info.json': info.model_dump_json(), 'extraction/extraction.json': result.model_dump_json(), 'extraction/quality.json': result.quality.model_dump_json() if result.quality else '{}', 'extraction/extracted.md': text}
        text = self.read(task, 'extraction/extracted.md')
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
        raise ValueError(f'未知阶段: {stage}')

    def draft(self, task):
        source = self.storage._path(task.task_id, task.source.copy_path)
        return {'metadata': json.loads(self.read(task, 'analysis/metadata.json')), 'classification': json.loads(self.read(task, 'analysis/classification.json')), 'rough_summary': self.read(task, 'analysis/rough_summary.txt'), 'detailed_summary': self.read(task, 'analysis/detailed_summary.md'), 'pdf_valid': source.is_file() and hash_file(source) == task.source.sha256}
