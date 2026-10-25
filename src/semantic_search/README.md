# 论文向量模块

## 职责与调用路径

```text
routes → lifecycle 代理 → PaperVectorService → VectorStore
                                               ├─ EmbedClient
                                               ├─ JsonStorage
                                               └─ chunking
```

- `lifecycle.py` 提供延迟创建的服务代理，管理创建和关闭；路由不直接访问内部资源。
- `paper_vector_service.py` 读取论文与 taxonomy、解析中文类型和标签、构造正文和上下文、生成 metadata，并将检索结果转换为稳定论文编号。
- `store.py` 协调生成、保存和相似度检索，负责文档组装、分块哈希、内容校验、分块展开及操作锁；通过显式的 `document_id` 将文件定位交给存储层，不从 metadata 中解析论文编号。
- `json_storage.py` 只负责安全文件定位、文件发现、JSON 解析/序列化、原子替换和 `delete(document_id)` 删除，不解释 metadata、chunks、哈希或 revision，也不管理 HTTP、相似度或操作锁。删除目标不存在时直接完成。
- `chunking.py` 负责正文分块和上下文前缀，检查 `size > 0`、`0 <= overlap < size` 及整数类型。
- `embed_client.py` 负责嵌入请求、响应数量/顺序/维度/有限数值校验及 HTTP 连接释放。

## 存储格式

默认目录为 `data/vectors/`，每篇论文一个 `<paper_id>.json`，例如 `P000020.json`：

```json
{
  "revision": 1,
  "metadata": {"title": "Paper title", "index": "P000020"},
  "chunks": [
    {
      "text": "论文上下文前缀\n\n对应正文分块",
      "text_hash": "<text 的 UTF-8 SHA-256，64 位小写十六进制>",
      "revision": 1,
      "vector": [0.1, 0.2]
    }
  ]
}
```

metadata 由论文服务构造，只包含 `title` 和 `index`。每个 chunk 的 `text` 是实际提交嵌入模型的完整输入，包含标题、中文文献类型和中文标签上下文；向量与文本按顺序一一对应。示例向量仅用于展示结构，实际维度取决于模型。

`text_hash` 由 store 复用 `src.hash_duplicate.hash_text()` 生成，按完整 text 的 UTF-8 字节计算 SHA-256，不去除空白或规范化换行。新文档主 `revision` 为 `1`，后续每批实际修改前在上次版本基础上加一，同批只加一次；新增或变化后写入的 chunk 使用本批主 revision，按哈希复用的 chunk 保留原 revision。仅修改 metadata、删除分块或调整顺序也递增主版本，完全不变则不写入、不递增。store 校验主版本为正整数，chunk 版本为不超过主版本的正整数。JsonStorage 仅原样读写 JSON，不计算哈希或管理版本。不兼容缺少这些字段的向量文件。

正文由概述和精细总结 Markdown 拼接。先按字符分块，再为每块附加相同前缀；`CHUNK_SIZE` 不包含前缀，也不是 tokenizer 的 token 上限。正文和 Markdown 必须非空，缺失文档不退化为仅嵌入概述。

只读取新格式 `.json`；不兼容、转换或读取旧 JSONL，也不再设置分片行数上限。已有旧文件不会因代码修改自动迁移，新格式向量需要另行生成。

## 保存与发布

`VectorStore.save(text, metadata, document_id=..., context=..., remove_stale_chunks=True)` 按文件编号定位并校验已有文档，对当前完整嵌入输入计算 `text_hash`。新编号创建 JSON；已有编号复用哈希匹配的向量，仅为新增哈希批量调用嵌入服务。同次保存内重复哈希只生成并保存一份，不跨论文复用向量。

`remove_stale_chunks` 必须为布尔值：默认 `True` 时移除当前文本中已不存在的分块，顺序按当前文本首次出现的位置排列；设为 `False` 时保留全部旧分块及其顺序，只在末尾追加新增哈希分块。关闭清理时，传入已有分块的子集且 metadata 未变会直接跳过，不生成向量或递增 revision。保留的旧分块仍会参与检索。论文服务当前使用默认清理行为。

正文、上下文、分块或 metadata 变化后，再次调用保存即可同步；创建、同步保存成功或内容完全相同均返回 `True`。内容未变时不调用嵌入服务、不写文件、不递增 revision；仅移除分块或修改 metadata 时不调用嵌入服务。模型变化不会反映在文本哈希中，切换模型仍需显式重建。

全部输入完成嵌入后，将 metadata 和所有 chunks 写入同目录临时文件，flush、fsync 后通过 `os.replace()` 发布正式 JSON。标题变化时替换同编号文件，不保留同篇旧版本。写入失败清理临时文件，并按下文约定删除对应正式 JSON；进程被强制终止时可能留下 `.tmp`，读取时忽略这些文件。

JSON 写入抛异常时，store 统一调用 `delete(document_id)` 删除对应正式 JSON，包括原有同名文件。清理完成后记录编号及异常类型并返回 `False`；删除失败继续抛出异常。嵌入和内容校验异常仍向上传递，不触发删除。`False` 表示 JSON 写入失败，不用于表示内容未变。

单文件替换避免逐块追加留下半篇记录，但不提供跨论文事务、跨进程写锁或断电持久性保证。新增分块生成失败时不会提前删除旧分块。只允许单写入者；同步软件和另一台设备的覆盖不受本实例锁保护。没有后台自动更新或整篇删除接口，重建前保留备份，可在新目录生成完整向量库后切换配置。

## 检索

目前不实现缓存。每次检索重新枚举并读取 JSON，校验内容后在本次调用内构造向量矩阵、范数及分块与文档的对应关系，计算相似度后返回结果；不跨请求保留矩阵、文本、metadata 或查询结果。

- `VectorStore.retrieve_document(query, top_k=...)` 按文档下标合并命中，每篇以最高分块相似度排序，返回 metadata 副本及 score。论文服务的同名方法保持原接口语义，返回稳定论文编号列表。
- `retrieve_chunk(query, top_k=...)` 在 store、论文服务和 lifecycle 代理中均返回 `[{"text": "...", "metadata": {"title": "...", "index": "P000020"}, "score": 0.9}]`。按分块相似度从高到低选取 top_k，不按论文合并，同一论文可命中多块；数量不足时返回全部可用分块，空库返回空列表，不调用嵌入服务。
- 两种方法复用 `_search()` 读取与相似度计算逻辑，均要求 top_k 为正整数，操作锁覆盖完整查询。`text` 包含保存时的论文上下文前缀，metadata 返回副本；不返回 vector。原 `retrieve()` 已改名，不保留旧别名。现有 HTTP 搜索继续调用文档检索并返回 paper_ids，未新增 chunk HTTP 路由。

保存只读取目标文档，不读取全库。已移除文件签名、检索快照及失效逻辑，缓存留待后续设计。远程向量数量由 EmbedClient 校验，本地文档、混合维度、哈希及 revision 仍由 store 校验。每次检索读取当时的文件，不提供外部并发写入下的全库一致性保证；本实例的保存、检索和关闭仍由操作锁串行保护。

## 生命周期

VectorStore 创建并拥有 EmbedClient 和 JsonStorage，通过同一把可重入锁保护完整的 `save()`、`retrieve_document()`、`retrieve_chunk()` 和 `close()`，包括网络请求和文件操作。`close()` 等待进行中的操作完成并关闭客户端；PaperVectorService 只关闭 store，不跨层访问客户端。

优先使用 `with PaperVectorService(...) as service`。关闭是终止操作，重复关闭安全，之后需要新实例，不自动重连。lifecycle 代理只锁定创建/关闭，不包裹正常存储操作；每次应用 lifespan 使用独立代理，普通浏览不会初始化嵌入客户端。

路径、模型、密钥、分块与计算参数见 `src/config.py`。读取或检索不会自动为论文生成向量；生成涉及向配置的外部服务发送正文，必须遵守用户对生成范围和数据外发的要求。
