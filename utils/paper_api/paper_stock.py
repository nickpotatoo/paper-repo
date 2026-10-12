"""正式入库及可恢复提交；调用方持有任务锁，再获取资料库锁。"""
import os
import re
import shutil
import tempfile
import unicodedata
from copy import deepcopy
from utils.hash import hash_file
from .config import now
from .task_store import APIError, read_json, write_json
from .validator import validate_index, validate_draft
from .duplicate_service import normalize_title


def install(source, target, digest):
    """先写完整临时文件，再以 hard link 原子安装；永不覆盖目标。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if hash_file(target) != digest:
            raise APIError("file_conflict", "正式文件已存在且内容不同", path=str(target))
        return
    fd, name = tempfile.mkstemp(prefix=".paper-api-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output, open(source, "rb") as input_stream:
            shutil.copyfileobj(input_stream, output)
            output.flush()
            os.fsync(output.fileno())
        if hash_file(name) != digest:
            raise APIError("source_changed", "源文件内容发生变化")
        try:
            os.link(name, target)
        except FileExistsError:
            if hash_file(target) != digest:
                raise APIError("file_conflict", "正式文件冲突", path=str(target))
    finally:
        if os.path.exists(name):
            os.unlink(name)


class PaperStock:
    def __init__(self, config, store, duplicates):
        self.config, self.store, self.duplicates = config, store, duplicates

    def decision_valid(self, task, candidates, decision):
        if not isinstance(decision, dict):
            return False
        return (decision.get("action") == "distinct"
                and sorted(decision.get("candidate_ids", [])) == sorted(c["paper_id"] for c in candidates)
                and decision.get("revision") == task["revision"]
                and decision.get("source_sha256") == task["source"]["sha256"]
                and decision.get("normalized_title") == normalize_title(task["draft"].get("metadata", {}).get("title"))
                and isinstance(decision.get("reason"), str) and bool(decision["reason"].strip()))

    def commit(self, task, decision=None):
        directory = self.store.directory(task["task_id"])
        journal_path = directory / "commit.json"
        with self.store.library_lock():
            index = read_json(self.config.index)
            validate_index(index)
            if task.get("paper_id"):
                paper = next((p for p in index["papers"] if p["paper_id"] == task["paper_id"]), None)
                if paper is None:
                    raise APIError("recovery_required", "任务关联的论文不在正式索引中")
                return paper, task.get("duplicate", False)
            if hash_file(directory / "source.pdf") != task["source"]["sha256"]:
                raise APIError("source_changed", "暂存 PDF 哈希不一致")
            if journal_path.exists():
                journal = read_json(journal_path)
                record = journal["paper"]
                if journal["revision"] != task["revision"]:
                    raise APIError("recovery_required", "提交记录与草稿版本不一致")
                method_hash = journal["method_hash"]
            else:
                candidates = self.duplicates.candidates(task, index)
                hashes = [c for c in candidates if "hash" in c["reasons"]]
                if hashes:
                    paper = next(p for p in index["papers"] if p["paper_id"] == hashes[0]["paper_id"])
                    task.update(status="committed", paper_id=paper["paper_id"], duplicate=True)
                    self.store.save(task)
                    return paper, True
                missing, errors = validate_draft(task["draft"], index)
                method = self.store.method_path(task)
                if method is None or not method.exists():
                    missing.append("method")
                elif hash_file(method) != task["method"]["content_hash"]:
                    errors.append({"field": "method", "message": "方法正文哈希不一致"})
                if missing or errors:
                    raise APIError("validation_failed", "草稿尚不满足入库条件", missing_fields=missing, errors=errors)
                if candidates and not self.decision_valid(task, candidates, decision):
                    raise APIError("duplicates_unresolved", "标题重复候选尚未核对", candidates=candidates)
                # 其他任务可能在计划写入后、计数器更新前中断；预留编号仍不能复用。
                reserved = [int(read_json(path)["paper"]["paper_id"][1:])
                            for path in self.config.tasks_dir.glob("task_*/commit.json")]
                number = max([index["paper_id_counter"]] + reserved + [int(p["paper_id"][1:]) for p in index["papers"]]) + 1
                paper_id = f"P{number:06d}"
                record = deepcopy(task["draft"])
                title = unicodedata.normalize("NFKD", record["metadata"]["title"]).encode("ascii", "ignore").decode().lower()
                slug = re.sub(r"[^a-z0-9]+", "-", title).strip("-")[:100].rstrip("-") or "paper"
                category = index["category_index"][record["classification"]["primary_category"]]
                record.update(paper_id=paper_id, added_at=now(), method_document=f"methods/{paper_id}.md")
                record["metadata"].update(original_filename=task["source"]["original_filename"],
                                          relative_path=f"{category['folder']}/{slug}-{paper_id.lower()}.pdf",
                                          sha256=task["source"]["sha256"])
                method_hash = task["method"]["content_hash"]
                journal = {"revision": task["revision"], "paper": record, "method_hash": method_hash, "stage": "planned"}
                # 先持久化计划；恢复时必须优先完成此计划，不再分配编号。
                write_json(journal_path, journal)
                task["status"] = "committing"
                self.store.save(task)
            index["paper_id_counter"] = max(index["paper_id_counter"], int(record["paper_id"][1:]))
            missing, errors = validate_draft(record, index)
            category = index["category_index"].get(record["classification"]["primary_category"])
            if missing or errors or category is None or record["metadata"]["relative_path"].rsplit("/", 1)[0] != category["folder"]:
                raise APIError("recovery_required", "预定记录的分类、标签或字段已失效")
            existing = next((p for p in index["papers"] if p["paper_id"] == record["paper_id"]), None)
            if existing is not None and existing != record:
                raise APIError("recovery_required", "预留编号与正式记录冲突")
            # 预留编号先写入索引，后续失败允许空号且永不复用。
            write_json(self.config.index, index)
            install(directory / "source.pdf", self.config.inside(record["metadata"]["relative_path"]), task["source"]["sha256"])
            install(self.store.method_path(task), self.config.inside(record["method_document"]), method_hash)
            if existing is None:
                index["papers"].append(record)
            index["paper_count"] = len(index["papers"])
            validate_index(index)
            write_json(self.config.index, index)
            journal["stage"] = "indexed"
            write_json(journal_path, journal)
            self.duplicates.build(index)
            task.update(status="committed", paper_id=record["paper_id"], duplicate=False)
            self.store.save(task)
            return record, False
