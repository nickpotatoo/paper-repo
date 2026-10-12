"""请求指纹、草稿幂等记录和任务之外的最终回执。"""
import json
from utils.hash import hash_text
from .task_store import APIError, read_json, write_json


def fingerprint(operation, payload):
    try:
        return hash_text(json.dumps({"operation": operation, "payload": payload},
                                   sort_keys=True, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError):
        raise APIError("invalid_request", "参数必须可序列化为标准 JSON") from None


def request_key(request_id):
    if not isinstance(request_id, str) or not request_id.strip():
        raise APIError("invalid_request_id", "request_id 必须为非空字符串")
    return hash_text(request_id)


def replay(records, request_id, digest):
    record = records.get(request_key(request_id))
    if record is None:
        return None
    if record["fingerprint"] != digest:
        raise APIError("request_conflict", "同一 request_id 不能用于不同请求")
    return record.get("result")


def remember(task, request_id, digest, result):
    task.setdefault("requests", {})[request_key(request_id)] = {
        "fingerprint": digest, "result": result}


class RequestStore:
    def __init__(self, config):
        self.directory = config.data / "request_receipts"

    def path(self, scope, request_id):
        return self.directory / hash_text(scope) / (request_key(request_id) + ".json")

    def read(self, scope, request_id, digest):
        path = self.path(scope, request_id)
        if not path.exists():
            return None
        value = read_json(path)
        if value["fingerprint"] != digest:
            raise APIError("request_conflict", "同一 request_id 不能用于不同请求")
        return value["result"]

    def save(self, scope, request_id, digest, result):
        write_json(self.path(scope, request_id), {
            "request_id": request_id, "fingerprint": digest, "result": result})
