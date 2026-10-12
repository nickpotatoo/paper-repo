"""论文接口路径配置；构造配置不会写文件。"""
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta, timezone
import os


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


@dataclass
class Config:
    root: Path = Path(__file__).resolve().parents[2]
    vectors_path: Path | None = None

    def __post_init__(self):
        self.root = Path(self.root).resolve()
        if self.vectors_path is not None:
            self.vectors_path = Path(self.vectors_path).resolve()

    @property
    def index(self):
        return self.root / "paper_index.json"

    @property
    def tasks_dir(self):
        return self.root / "tasks"

    @property
    def data(self):
        return self.root / "data"

    def inside(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("路径超出论文库")
        return path

    def vector_path(self):
        # 延迟加载现有配置，使 .env 与查看器采用相同规则。
        from utils.semantic_search import config as existing
        value = self.vectors_path or os.environ.get("VECTORS_PATH")
        if value:
            return Path(value).resolve()
        directory = os.environ.get("SEMANTIC_SEARCH_DATA_DIR")
        return Path(directory).resolve() / "vectors.jsonl" if directory else self.data / "vectors.jsonl"
