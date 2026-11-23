# Paper Repo

本地论文库。可按分类、标签和入库时间浏览论文，阅读 PDF 与中文精细总结，并使用向量检索。上传论文后，可在同一界面审阅处理结果、确认入库或重试失败阶段。

## 启动

需要 Python 3.10 或更新版本，在项目根目录运行：

```bash
python -m pip install -r requirements.txt
python launch.py
```

默认打开 `http://127.0.0.1:5000/`。用 `--without-open-viewer` 可只启动服务，用 `--port` 可指定端口。空库首次启动会初始化数据文件；已有资料但缺少索引文件时，请先恢复对应文件。

配置集中在 [src/config.py](src/config.py)。可参考 [.env.example](.env.example) 创建根目录的 `.env`：

| 配置 | 用途 |
| --- | --- |
| `SERVICE_PASSWORD` | 上传论文、查看任务及执行任务操作。 |
| `DEEPSEEK_API_KEY` | 生成元数据、分类、粗略总结和精细总结。 |
| `BGE_M3_API_KEY` | 生成向量与语义检索。默认使用硅基流动的 `BAAI/bge-m3`。 |

仅浏览已入库论文无需配置这些密钥。

## 处理论文

1. 在查看器选择「上传论文」→「上传并处理」。原件保存到 `new_papers/`，任务状态和产物保存在 `task/<task_id>/`。
2. 打开「任务状态」。任务自动查重、提取、生成草稿并校验，然后停在「待审阅」。可预览结果，按需单独重生成元数据、分类、粗略总结或精细总结。
3. 确认「入库」后，论文进入正式库，向量在后台生成。拿到论文编号表示已入库，向量是否完成以任务状态为准。
4. 阶段失败时，点击「重试：阶段名」从失败处继续。未入库任务也可选择「重新执行」，归档旧产物后从原始 PDF 开始。

正式数据位于 `data/`：`papers.json` 保存论文数组，`taxonomy.json` 保存分类、标签和文献类型，`repo_state.json` 保存编号计数器。PDF 按主分类 ID 分目录，精细总结和向量按论文 ID 存放。

## 文档

- [论文入库与维护](AGENTS.md)
- [论文处理流水线与任务接口](src/PaperProcessing/README.md)
- [正式资料库读写与校验](src/RepoManager/README.md)
- [查看器与服务](viewer/README.md)
- [向量检索模块](src/SemanticSearch/README.md)
