import shutil
import uuid
from copy import deepcopy
from utils.hash import hash_file, hash_text
from .config import now
from .task_store import APIError, atomic_text, read_json, write_json
from .request_store import fingerprint, replay, remember, request_key
from .validator import FIELDS, field_error, get_field, set_field, validate_draft, validate_index


class TaskService:
    def __init__(self, config, store, receipts, duplicates, stock, vectors):
        self.config, self.store, self.receipts = config, store, receipts
        self.duplicates, self.stock, self.vectors = duplicates, stock, vectors

    def tasks(self):
        result = {}
        markers = self.config.data / "request_receipts" / "cleanup"
        if markers.exists():
            for marker in sorted(markers.glob("task_*.json")):
                task_id = marker.stem
                with self.store.lock(task_id):
                    self._cleanup(task_id)
        if not self.config.tasks_dir.exists():
            return result
        for path in sorted(self.config.tasks_dir.glob("task_*/task.json")):
            task_id = path.parent.name
            with self.store.lock(task_id):
                if not path.exists():
                    continue
                task = self.store.load(task_id)
                if task.get("vector_status") == "ready":
                    self._export_and_cleanup(task)
                    if not path.exists():
                        continue
                result[task_id] = task["draft"].get("metadata", {}).get("title") or task["source"]["original_filename"]
        return result

    def create_task(self, source_path):
        from pathlib import Path
        if not isinstance(source_path, (str, Path)):
            raise APIError("invalid_source", "source_path 必须为文件路径")
        source = Path(source_path).resolve()
        if not source.is_file():
            raise APIError("invalid_source", "来源文件不存在")
        with source.open("rb") as stream:
            if b"%PDF-" not in stream.read(1024):
                raise APIError("invalid_pdf", "来源文件没有 PDF 标识")
        task_id = "task_" + uuid.uuid4().hex
        directory = self.store.directory(task_id)
        with self.store.lock(task_id):
            directory.mkdir(parents=True, exist_ok=False)
            try:
                shutil.copyfile(source, directory / "source.pdf")
                digest = hash_file(directory / "source.pdf")
                if hash_file(source) != digest:
                    raise APIError("source_changed", "复制期间来源 PDF 发生变化")
                task = {"task_id": task_id, "revision": 0, "status": "draft", "created_at": now(),
                        "updated_at": now(), "source": {"original_filename": source.name, "sha256": digest},
                        "draft": {}, "method": None, "paper_id": None, "vector_status": "not_started", "requests": {}}
                with self.store.library_lock():
                    index = read_json(self.config.index)
                    validate_index(index)
                    candidates = self.duplicates.candidates(task, index)
                self.store.save(task)
                return {"task_id": task_id, "sha256": digest, "duplicate_candidates": candidates,
                        "source_path": str(directory / "source.pdf"), "task_path": str(directory / "task.json")}
            except Exception:
                self.store.remove(task_id)
                raise

    def _validation(self, task, index):
        missing, errors = validate_draft(task["draft"], index)
        method = self.store.method_path(task)
        if method is None or not method.exists():
            missing.append("method")
        elif hash_file(method) != task["method"]["content_hash"]:
            errors.append({"field": "method", "message": "正文哈希不一致"})
        if hash_file(self.store.directory(task["task_id"]) / "source.pdf") != task["source"]["sha256"]:
            errors.append({"field": "source", "message": "PDF 哈希不一致"})
        candidates = self.duplicates.candidates(task, index)
        exact = any("hash" in c["reasons"] for c in candidates)
        ready = task["status"] == "draft" and not errors and (exact or not missing and not candidates)
        return {"task_id": task["task_id"], "revision": task["revision"], "missing_fields": missing,
                "errors": errors, "ready_to_commit": ready, "duplicate_candidates": candidates,
                "requires_duplicate_decision": bool(candidates) and not exact,
                "status": task["status"], "paper_id": task.get("paper_id"),
                "vector_status": task["vector_status"], "vector_error": task.get("vector_error")}

    def validate_task(self, task_id):
        with self.store.lock(task_id):
            task = self.store.load(task_id)
            with self.store.library_lock():
                return self._validation(task, read_json(self.config.index))

    def check_task_duplicates(self, task_id):
        with self.store.lock(task_id):
            task = self.store.load(task_id)
            if hash_file(self.store.directory(task_id) / "source.pdf") != task["source"]["sha256"]:
                raise APIError("source_changed", "暂存 PDF 已改变")
            with self.store.library_lock():
                return bool(self.duplicates.candidates(task, read_json(self.config.index)))

    def _begin(self, task_id, request_id, operation, payload):
        digest = fingerprint(operation, {"task_id": task_id, **payload})
        old = self.receipts.read(task_id, request_id, digest)
        if old is not None:
            path = self.store.directory(task_id) / "task.json"
            if path.exists():
                remaining = self.store.load(task_id)
                if remaining.get("vector_status") == "ready":
                    self._export_and_cleanup(remaining)
            else:
                self._cleanup(task_id)
            return None, digest, old
        task = self.store.load(task_id)
        old = replay(task.get("requests", {}), request_id, digest)
        if old is not None and task.get("vector_status") == "ready":
            self._export_and_cleanup(task)
        return task, digest, old

    def _revision(self, task, expected):
        if type(expected) is not int or expected != task["revision"]:
            raise APIError("revision_conflict", "草稿版本不一致", revision=task["revision"])

    def _editable(self, task):
        if task["status"] != "draft" or (self.store.directory(task["task_id"]) / "commit.json").exists():
            raise APIError("task_not_editable", "任务已提交或正在恢复提交")

    def update_task(self, task_id, expected_revision, request_id, fields, tags=None, clear_fields=None):
        payload = {"expected_revision": expected_revision, "fields": fields, "tags": tags, "clear_fields": clear_fields}
        with self.store.lock(task_id):
            task, digest, old = self._begin(task_id, request_id, "update_task", payload)
            if old is not None:
                return old
            self._revision(task, expected_revision)
            self._editable(task)
            clear = [] if clear_fields is None else clear_fields
            if not isinstance(fields, dict) or not isinstance(clear, list) or any(not isinstance(f, str) for f in clear):
                raise APIError("invalid_fields", "fields 应为字典，clear_fields 应为字段路径列表")
            if (set(fields) | set(clear)) - FIELDS or set(fields) & set(clear):
                raise APIError("invalid_fields", "字段不在白名单或同时被填写和清除")
            before = deepcopy(task["draft"])
            draft = deepcopy(before)
            with self.store.library_lock():
                index = read_json(self.config.index)
                for path, value in fields.items():
                    error = field_error(path, value, index)
                    if error:
                        raise APIError("invalid_field", "字段校验失败", errors=[error])
                    set_field(draft, path, value)
                for path in clear:
                    set_field(draft, path, None, delete=True)
                if tags is not None:
                    if not isinstance(tags, dict) or tags.get("mode") not in ("replace", "modify"):
                        raise APIError("invalid_tags", "标签更新模式错误")
                    permitted = {"mode", "values"} if tags["mode"] == "replace" else {"mode", "add", "remove"}
                    if set(tags) - permitted:
                        raise APIError("invalid_tags", "标签参数冲突")
                    lists = [tags.get("values")] if tags["mode"] == "replace" else [tags.get("add", []), tags.get("remove", [])]
                    if any(not isinstance(items, list) or any(not isinstance(t, str) or t not in index["tag_index"] for t in items) for items in lists):
                        raise APIError("invalid_tags", "标签需为已定义 ID 列表")
                    if tags["mode"] == "replace":
                        values = lists[0]
                    else:
                        add, remove = lists
                        if set(add) & set(remove):
                            raise APIError("invalid_tags", "不能同时添加和删除同一标签")
                        values = [t for t in draft.get("classification", {}).get("tags", []) if t not in remove] + add
                    set_field(draft, "classification.tags", list(dict.fromkeys(values)))
                paths = FIELDS | {"classification.tags"}
                changed = sorted(p for p in paths if get_field(before, p) != get_field(draft, p))
                task["draft"] = draft
                if changed:
                    task["revision"] += 1
                    task["updated_at"] = now()
                report = self._validation(task, index)
                result = {k: report[k] for k in ("task_id", "revision", "missing_fields", "ready_to_commit")}
                result["changed_fields"] = changed
                remember(task, request_id, digest, result)
                self.store.save(task)
                return result

    def write_task_method(self, task_id, expected_revision, request_id, markdown):
        with self.store.lock(task_id):
            task, digest, old = self._begin(task_id, request_id, "write_task_method", {
                "expected_revision": expected_revision, "markdown": markdown})
            if old is not None:
                return old
            self._revision(task, expected_revision)
            self._editable(task)
            if not isinstance(markdown, str) or not markdown.strip():
                raise APIError("invalid_markdown", "方法正文不能为空")
            content_hash = hash_text(markdown)
            reference = {"content_hash": content_hash, "path": f"methods/{content_hash}.md"}
            atomic_text(self.store.directory(task_id) / reference["path"], markdown)
            if task.get("method") != reference:
                task["revision"] += 1
                task["updated_at"] = now()
                task["method"] = reference
            result = {"task_id": task_id, "revision": task["revision"], "content_hash": content_hash}
            remember(task, request_id, digest, result)
            self.store.save(task)
            return result

    def _cleanup_path(self, task_id):
        return self.config.data / "request_receipts" / "cleanup" / (task_id + ".json")

    def _cleanup(self, task_id):
        marker = self._cleanup_path(task_id)
        if marker.exists():
            self.store.remove(task_id)
            marker.unlink()

    def _vectors_and_finish(self, task, paper, request_id, digest):
        task.setdefault("requests", {})[request_key(request_id)] = {"fingerprint": digest, "pending": True}
        task["vector_status"] = "pending"
        self.store.save(task)
        try:
            vector = self.vectors.generate(paper)
            task["vector_status"] = "ready"
            task.pop("vector_error", None)
        except Exception as error:
            # 不输出第三方异常文本，避免泄漏请求头或 API Key。
            detail = error.as_dict() if isinstance(error, APIError) else {
                "code": "vector_failed", "message": "向量依赖、配置、网络或服务异常", "exception_type": type(error).__name__}
            task.update(vector_status="failed", vector_error=detail)
            vector = {"status": "failed", "error": detail}
        result = {"task_id": task["task_id"], "paper_id": paper["paper_id"], "committed": True,
                  "duplicate": task.get("duplicate", False), "vector": vector, "task_deleted": False,
                  "relative_path": paper["metadata"]["relative_path"]}
        remember(task, request_id, digest, result)
        self.store.save(task)
        if task["vector_status"] == "ready":
            result["task_deleted"] = True
            remember(task, request_id, digest, result)
            self.store.save(task)
            # 先导出所有请求回执；中断后可从 ready task 继续此步骤。
            try:
                self._export_and_cleanup(task)
            except OSError:
                result.update(task_deleted=False, cleanup_error="暂存文件清理失败；重新列出任务或重试请求可继续清理")
                remember(task, request_id, digest, result)
                if (self.store.directory(task["task_id"]) / "task.json").exists():
                    self.store.save(task)
                self.receipts.save(task["task_id"], request_id, digest, result)
        return result

    def _export_and_cleanup(self, task):
        task_id = task["task_id"]
        directory = self.receipts.directory / hash_text(task_id)
        for key, record in task.get("requests", {}).items():
            if "result" not in record:
                # 先前超时的提交/重试也需能在任务删除后取得最终完成结果。
                record = {"fingerprint": record["fingerprint"], "result": {
                    "task_id": task_id, "paper_id": task["paper_id"], "committed": True,
                    "duplicate": task.get("duplicate", False), "vector": {"status": "ready"}, "task_deleted": True}}
            write_json(directory / (key + ".json"), record)
        write_json(self._cleanup_path(task_id), {"task_id": task_id, "paper_id": task["paper_id"]})
        self._cleanup(task_id)

    def commit_task(self, task_id, expected_revision, request_id, duplicate_decision=None):
        payload = {"expected_revision": expected_revision, "duplicate_decision": duplicate_decision}
        with self.store.lock(task_id):
            task, digest, old = self._begin(task_id, request_id, "commit_task", payload)
            if old is not None:
                return old
            self._revision(task, expected_revision)
            task.setdefault("requests", {})[request_key(request_id)] = {"fingerprint": digest, "pending": True}
            self.store.save(task)
            try:
                paper, duplicate = self.stock.commit(task, duplicate_decision)
            except Exception:
                if (self.store.directory(task_id) / "commit.json").exists():
                    task["status"] = "recovery_required"
                    self.store.save(task)
                raise
            return self._vectors_and_finish(task, paper, request_id, digest)

    def retry_task_vectors(self, task_id, request_id):
        with self.store.lock(task_id):
            task, digest, old = self._begin(task_id, request_id, "retry_task_vectors", {})
            if old is not None:
                return old
            if task["status"] != "committed" or not task.get("paper_id"):
                raise APIError("not_committed", "任务尚未完成正式入库")
            with self.store.library_lock():
                index = read_json(self.config.index)
                paper = next((p for p in index["papers"] if p["paper_id"] == task["paper_id"]), None)
                if paper is None:
                    raise APIError("paper_not_found", "正式论文不存在")
            return self._vectors_and_finish(task, paper, request_id, digest)
