"""本地 Python 接口门面；call 提供适合 HTTP/MCP 包装的 JSON 返回。"""
from .config import Config
from .task_store import APIError, TaskStore
from .request_store import RequestStore
from .registry_service import RegistryService
from .duplicate_service import DuplicateService
from .paper_stock import PaperStock
from .vector_service import VectorService
from .task_service import TaskService


class PaperAPI:
    OPERATIONS = {"list_categories", "list_tags", "create_category", "create_tag", "tasks", "create_task",
                  "check_task_duplicates", "validate_task", "write_task_method", "update_task", "commit_task", "retry_task_vectors"}

    def __init__(self, root=None, vectors_path=None):
        self.config = Config(**({"root": root} if root is not None else {}), vectors_path=vectors_path)
        store = TaskStore(self.config)
        receipts = RequestStore(self.config)
        duplicates = DuplicateService(self.config)
        self.registry = RegistryService(self.config, store, receipts)
        self.service = TaskService(self.config, store, receipts, duplicates,
                                   PaperStock(self.config, store, duplicates), VectorService(self.config))

    def list_categories(self):
        return self.registry.list("category")

    def list_tags(self):
        return self.registry.list("tag")

    def create_category(self, name, description, folder_slug, request_id):
        return self.registry.create("category", name, request_id, description, folder_slug)

    def create_tag(self, name, request_id):
        return self.registry.create("tag", name, request_id)

    def tasks(self):
        return self.service.tasks()

    def create_task(self, source_path):
        return self.service.create_task(source_path)

    def check_task_duplicates(self, task_id):
        return self.service.check_task_duplicates(task_id)

    def validate_task(self, task_id):
        return self.service.validate_task(task_id)

    def update_task(self, task_id, expected_revision, request_id, fields, tags=None, clear_fields=None):
        return self.service.update_task(task_id, expected_revision, request_id, fields, tags, clear_fields)

    def write_task_method(self, task_id, expected_revision, request_id, markdown):
        return self.service.write_task_method(task_id, expected_revision, request_id, markdown)

    def commit_task(self, task_id, expected_revision, request_id, duplicate_decision=None):
        return self.service.commit_task(task_id, expected_revision, request_id, duplicate_decision)

    def retry_task_vectors(self, task_id, request_id):
        return self.service.retry_task_vectors(task_id, request_id)

    def call(self, operation, arguments=None):
        try:
            if not isinstance(operation, str) or operation not in self.OPERATIONS:
                raise APIError("unknown_operation", "未知接口")
            if arguments is not None and not isinstance(arguments, dict):
                raise APIError("invalid_arguments", "arguments 必须为字典")
            return {"ok": True, "result": getattr(self, operation)(**(arguments or {}))}
        except APIError as error:
            return {"ok": False, "error": error.as_dict()}
        except Exception as error:
            return {"ok": False, "error": {"code": "operation_failed", "message": "参数、文件或运行环境异常",
                                            "exception_type": type(error).__name__}}
