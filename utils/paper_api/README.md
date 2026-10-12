# 论文任务接口

本地 Python 服务层，Python 3.10+。尚未提供 HTTP 或 MCP 传输；两者可调用同一 `PaperAPI.call()`。创建、编辑、查重使用标准库，提交和向量重试才加载现有 SSBridge 的依赖与配置。

## Python 使用

```python
from utils.paper_api import PaperAPI, APIError

api = PaperAPI()  # 默认使用本项目；可指定 root、vectors_path
created = api.create_task(source_path=r"C:\downloads\paper.pdf")
task_id = created["task_id"]
report = api.validate_task(task_id)

updated = api.update_task(
    task_id=task_id,
    expected_revision=report["revision"],
    request_id="独立且不重复的请求ID-1",
    fields={
        "metadata.title": "Paper Title",
        "metadata.document_type": "Method and experiments",
        "metadata.authors": None,
        "metadata.year": 2026,
        "classification.primary_category": "C002",
        "summary": "根据原文整理的中文内容概述。",
        "reading_notes": "已阅读摘要、引言、方法与实验。",
        "extraction_status": "text_extractable",
    },
    tags={"mode": "replace", "values": ["T017"]},
)
method = api.write_task_method(
    task_id=task_id, expected_revision=updated["revision"],
    request_id="独立且不重复的请求ID-2", markdown="# Paper Title\n\n实际方法正文……",
)
# commit_task 会进行正式写入，并调用外部嵌入服务。
result = api.commit_task(task_id, method["revision"], "独立且不重复的请求ID-3")
# 若向量失败，先修复环境，然后使用新的 request_id：
# result = api.retry_task_vectors(task_id, "独立且不重复的请求ID-4")
```

示例内容需替换为论文实际信息。Agent 每次处理论文前仍需阅读当前 AGENTS.md；接口校验结构，不判断论文事实或标签的语义近似。

直接调用失败会抛出 `APIError` 或文件/环境异常。包装接口推荐使用：

```python
response = api.call("validate_task", {"task_id": task_id})
# {"ok": True, "result": ...} 或 {"ok": False, "error": {"code": ..., ...}}
```

## JSON 命令行入口

在项目根目录创建 UTF-8 请求文件，例如 `request.json`：

```json
{"operation": "tasks", "arguments": {}}
```

```powershell
python -m utils.paper_api --request request.json
```

也支持 stdin，以及 `--root <论文库路径>`、`--vectors-path <向量文件路径>`。输出 UTF-8 JSON，失败退出码为 1。不会启动浏览器或监听网络。

## 接口补充

- `tasks()`：未完成任务的 `{task_id: title}`；无标题则显示原文件名。
- `create_task(source_path)`：返回 task_id、sha256、duplicate_candidates、暂存 PDF 和 task.json 的绝对路径。原始来源文件保留。
- `validate_task(task_id)`：revision、missing_fields、errors、ready_to_commit、duplicate_candidates、requires_duplicate_decision、status、paper_id、vector_status、vector_error。
- `create_category(name, description, folder_slug, request_id)`：folder_slug 由调用者提供英文短名，如 `agent-planning`；程序自动添加目录序号并分配 C 编号。
- `create_tag(name, request_id)`：分配 T 编号。同名标签复用；同名分类定义或目录短名不同则报冲突。
- `clear_fields` 只删除白名单中的草稿字段；标签清空使用 `{"mode":"replace","values":[]}`。
- `tags` 支持 replace/values 或 modify/add/remove。必须引用现有标签 ID。
- `write_task_method()` 完整替换正文，不做追加；返回 revision 和 content_hash。
- `check_task_duplicates()` 仅返回 bool。匹配 PDF 哈希或规范化标题即为 true。

仅标题匹配且确认不同论文时，`commit_task(..., duplicate_decision=...)` 使用：

```json
{
  "action": "distinct",
  "candidate_ids": ["P000001"],
  "revision": 2,
  "source_sha256": "当前task的sha256",
  "normalized_title": "候选中返回的normalized_title",
  "reason": "依据作者、内容等说明为何不是同一论文。"
}
```

候选列表、版本、哈希和标题必须与当前检查一致；完全相同 PDF 不能强制新增，而会关联已有论文编号。标题未确认的任务可以提交带决定的请求，程序重新检查条件。新文件名使用标题的 ASCII 短名加 paper_id，避免覆盖和 Windows 保留文件名。

## 向量和完成任务

先保存正式资料，再同步调用 SSBridge。核对全部文本块、metadata、向量维度和数值；即使 saved=False，也必须验证现有向量与当前内容一致。不完整或正文不一致时报告失败，保留任务，不自动替换向量。

失败不回滚论文。`retry_task_vectors()` 不重新入库。任务与向量状态可通过 validate_task 查询。成功后导出请求回执并删除暂存目录；tasks() 或相同请求重试可继续中断的清理。

超时后使用原 request_id 和相同参数重试以获取原结果；一次明确失败后，若希望重新执行向量生成，使用新的 request_id。任务删除后请求回执仍可重放；任务不再出现在 tasks()，validate_task 返回 task_not_found。

## 存储及恢复

任务目录、去重索引和回执在调用接口时创建，导入模块不会修改资料库。JSON 使用 UTF-8 原子替换。任务锁位于 data/locks，正式索引写入共用 library.lock。向量调用共用向量文件旁的 .lock。

提交计划记录在 tasks/<task_id>/commit.json；恢复时重用原编号、路径和 added_at。异常后状态可能是 recovery_required，使用相同提交请求重试；恢复期间不允许编辑草稿。所有未完成计划中的编号参与后续编号分配，永不复用。

正式文件先完整写入临时文件，再通过 hard link 原子安装，因此要求目标文件系统支持硬链接（Windows NTFS 支持）。目标已存在时仅接受完全相同内容，不覆盖不同文件。

去重索引每次从当前索引及 PDF 重建，确保历史论文无需迁移即可查重；资料库很大时可再优化缓存。没有运行测试，也未自动调用向量服务。

并发保护只覆盖本接口。现有生成向量脚本、手工编辑和其他写入方未共用锁，应避免与提交同时运行。
