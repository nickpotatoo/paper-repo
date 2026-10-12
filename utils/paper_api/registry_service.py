import re
from copy import deepcopy
from .task_store import APIError, read_json, write_json
from .request_store import fingerprint
from .validator import validate_index


class RegistryService:
    def __init__(self, config, store, receipts):
        self.config, self.store, self.receipts = config, store, receipts

    def list(self, kind):
        with self.store.library_lock():
            return deepcopy(read_json(self.config.index)[kind + "_index"])

    def create(self, kind, name, request_id, description=None, folder_slug=None):
        if not isinstance(name, str) or not name.strip():
            raise APIError("invalid_name", "名称不能为空")
        name = name.strip()
        if kind == "category":
            if not isinstance(description, str) or not description.strip():
                raise APIError("invalid_description", "分类定义不能为空")
            if not isinstance(folder_slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", folder_slug):
                raise APIError("invalid_folder_slug", "分类目录短名需为英文小写短横线格式")
        digest = fingerprint("create_" + kind, {"name": name, "description": description, "folder_slug": folder_slug})
        with self.store.library_lock():
            receipt_path = self.receipts.path("registry", request_id)
            pending = read_json(receipt_path) if receipt_path.exists() else None
            if pending is not None and pending.get("pending"):
                if pending["fingerprint"] != digest:
                    raise APIError("request_conflict", "同一 request_id 不能用于不同请求")
                index = read_json(self.config.index)
                validate_index(index)
                plan = pending["result"]
                table = index[kind + "_index"]
                if plan["id"] in table and table[plan["id"]] != plan["entry"]:
                    raise APIError("recovery_required", "分类或标签恢复记录冲突")
                if kind == "category":
                    self.config.inside(plan["entry"]["folder"]).mkdir(exist_ok=True)
                table[plan["id"]] = plan["entry"]
                write_json(self.config.index, index)
                self.receipts.save("registry", request_id, digest, plan)
                return plan
            old = self.receipts.read("registry", request_id, digest)
            if old is not None:
                return old
            index = read_json(self.config.index)
            validate_index(index)
            table = index[kind + "_index"]
            for key, value in table.items():
                if kind == "tag" and value == name:
                    result = {"id": key, "entry": value, "created": False}
                    break
                if kind == "category" and value["name"] == name:
                    if value["description"] != description or value["folder"].split("_", 1)[-1] != folder_slug:
                        raise APIError("definition_conflict", "同名分类具有不同定义", category_id=key)
                    result = {"id": key, "entry": value, "created": False}
                    break
            else:
                counter_path = self.config.data / "registry_counters.json"
                counters = read_json(counter_path) if counter_path.exists() else {}
                prefix = "C" if kind == "category" else "T"
                number = max([int(k[1:]) for k in table] + [counters.get(kind, 0)]) + 1
                counters[kind] = number
                write_json(counter_path, counters)
                key = f"{prefix}{number:03d}"
                value = name
                if kind == "category":
                    numbers = [int(v["folder"].split("_", 1)[0]) for v in table.values()
                               if re.match(r"^\d+_", v["folder"])]
                    numbers += [int(p.name.split("_", 1)[0]) for p in self.config.root.iterdir()
                                if p.is_dir() and re.match(r"^\d+_", p.name)]
                    folder = f"{max(numbers + [0]) + 1:02d}_{folder_slug}"
                    self.config.inside(folder).mkdir(exist_ok=False)
                    value = {"name": name, "folder": folder, "description": description}
                result = {"id": key, "entry": value, "created": True}
                write_json(receipt_path, {"fingerprint": digest, "result": result, "pending": True})
                table[key] = value
                write_json(self.config.index, index)
            self.receipts.save("registry", request_id, digest, result)
            return result
