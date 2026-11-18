# RepoManager

`src.RepoManager` 提供资料初始化、读取、校验和管理接口。调用方可以为实例指定独立的资料与附件路径。

```python
from src.RepoManager import RepoManager, load_data

repo = RepoManager()
data = load_data()
tag_id = repo.add_taxonomy_entry("tag", "图检索")
repo.update_taxonomy_entry("tag", tag_id, "图结构检索")
repo.delete_taxonomy_entry("tag", tag_id)
```

- `get_paper(paper_id)` 与 `get_taxonomy()` 读取已校验的记录和索引。
- 分类索引接口接受 `category`、`tag` 或 `document_type`。新增分类须提供 `description`，并自动创建 PDF 目录。改名保留编号。仍被论文引用的定义不能删除。删除分类定义会保留磁盘上的目录。
- `delete_paper(paper_id)` 从索引及正式附件目录移除论文记录、PDF、精细总结和向量文件，返回位于论文索引同目录下 `.deleted_papers/` 的归档路径。归档保存原记录及当时存在的附件。论文计数器保持原值。
- 管理方法在进程内串行写入，JSON 使用原子替换。论文删除涉及多个文件，遇到普通写入错误时尝试恢复附件。多进程写入和进程崩溃恢复由调用方协调。
