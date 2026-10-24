# Paper Repo

本地论文库，支持分类与标签、中文精细总结、Markdown/LaTeX 渲染及向量检索。

## 启动

需要 Python 3.10 或更新版本，在项目根目录运行：

```bash
python -m pip install -r requirements.txt
python launch.py
```

首次启动自动初始化空资料库并打开浏览器。数据位于 `data/`，配置见 `src/config.py`；嵌入向量服务默认使用硅基流动平台`BGE_M3`模型，需设置环境变量 `BGE_M3_API_KEY`，普通浏览无需密钥。

## 文档

- [论文入库与维护](AGENTS.md)
- [查看器与服务](viewer/README.md)
- [向量检索模块](src/semantic_search/README.md)
