# 精细总结文档编辑说明

每篇论文的精细总结保存在本目录下独立的 `.md` 文件中，文件名与 `data/papers.json` 论文数组中的 `paper_id` 完全一致，例如 `P000001.md`。实际文件路径由编号推导为 `data/detailed_summaries/<paper_id>.md`，通过 `/files/detailed_summaries/<paper_id>.md` 访问；论文记录不再保存 `detailed_summary_document`。编辑现有 Markdown 文件后，刷新查看器页面即可看到更新。

在项目根目录运行 `python launch.py` 启动本地服务。页面分别读取论文数组和分类标签；打开某篇卡片时，才从原始 Markdown 文件读取该篇的精细总结正文。搜索使用论文的标题、内容概述和标签名称。

可使用普通 Markdown 标题、列表、表格、代码块和链接。LaTeX 公式支持以下写法：

- 行内公式：`$M_t = f(M_{t-1}, x_t)$` 或 `\(M_t = f(M_{t-1}, x_t)\)`
- 独立公式：

  ```text
  $$
  M_t = f(M_{t-1}, x_t)
  $$
  ```

直接编辑对应论文的 Markdown，保留已有内容；原历史迁移工具已移除。精细总结文档根据论文方法、系统设计或综述框架扩写，并区分论文报告的评估结果与概念性方案。
