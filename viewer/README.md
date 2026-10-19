# 论文查看器开发说明

查看器使用原生 JavaScript ES Modules，无需 npm 安装或构建。根目录 `paper_viewer.html` 保存页面布局，通过 `viewer/js/app.js` 初始化。CSS 位于 `viewer/styles/main.css`；Marked 和 KaTeX 继续使用根目录 `vendor/` 中的本地依赖。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `js/app.js` | 页面入口；集中管理 repo、filters、semantic 状态；并行读取论文和分类标签，连接组件和更新结果 |
| `js/api.js` | 分别提供 `loadPapers()`、`loadTaxonomy()`，以及 Markdown、语义搜索和心跳 HTTP 请求；按论文 ID 缓存 Markdown 和合并进行中的加载请求 |
| `js/repo.js` | `createRepo(papers, taxonomy)` 接收两个独立参数；校验编号引用、按 ID 查询论文、解析分类标签和组合搜索文本 |
| `js/filters.js` | 根据筛选条件计算结果；默认按分类 ID 分组；支持跨分类按入库时间排序，默认保留向量检索结果顺序 |
| `js/utils.js` | HTML 转义、分类编号比较、文件 URL、北京时间日期转换 |
| `js/markdown.js` | Markdown 及四种 LaTeX 定界符渲染 |
| `js/components/paper-list.js` | 分组和卡片展示；通过事件委托处理单击、双击、键盘操作 |
| `js/components/paper-detail.js` | 详情弹窗和精细总结文档延迟加载；防止旧请求覆盖新的详情 |
| `js/components/semantic-search.js` | 向量搜索弹窗、参数检查、请求取消和结果回调 |

数据流：`Promise.all([api.loadPapers(), api.loadTaxonomy()])` → `createRepo(papers, taxonomy)` → app 状态 → `filterPapers()` / `groupPapers()` → 卡片。论文数组和分类标签对象始终作为两个参数传递，不生成聚合索引。组件通过回调报告操作，不直接修改其他组件。HTTP 请求集中在 api 模块中，repo 和筛选模块不访问 DOM。

`/papers.json` 返回论文数组，`/taxonomy.json` 返回含 `category_index`、`tag_index` 和 `document_type_index` 的对象。前端不读取 `repo_state.json`；编号计数器由服务端及维护工具使用。任一数据请求失败都会显示加载错误，不以空数据替代。

`metadata.document_type` 保存文献类型 ID（如 `D004`），`document_type_index` 将 ID 映射到中文名称。卡片和详情通过 `repo.documentTypeName(id)` 显示名称，关键词搜索同时匹配类型 ID 和名称；未定义的类型引用会阻止前端加载。类型改名只需修改 taxonomy。

PDF 存放在 `data/pdfs/<分类ID>/`，例如 `data/pdfs/C003/`。论文记录仅保存 `metadata.filename`（例如 `example.pdf`）；`repo.pdfPath(paper)` 根据 `classification.primary_category` 与文件名生成路径，`pdfUrl(paper, repo)` 将它映射到 `/files/pdfs/C003/example.pdf`，路径不写回论文记录。`taxonomy.json` 的分类仅保存显示名称 `name` 和主题 `description`，目录名直接使用分类 ID。精细总结文档位于 `data/detailed_summaries/<paper_id>.md`，通过 `/files/detailed_summaries/<paper_id>.md` 读取；URL 前缀由服务端映射到 `PDFS_DIR` 和 `DETAILED_SUMMARIES_DIR`，前端不依赖其磁盘绝对路径。

## 运行与扩展

工具栏的排序选项提供“默认顺序”“入库：最新优先”和“入库：最早优先”。时间排序按 `added_at` 的实际时刻跨分类排列，筛选后仍生效；相同时间保持原顺序，缺失或无效时间均放在末尾，不修改论文数组。默认顺序按分类浏览，向量检索时按相关性排列；主动选择时间排序后，检索结果按所选时间方向显示。搜索、日期筛选及返回全部论文均保留所选排序方式。

在项目根目录运行 `python launch.py` 启动服务并打开浏览器，默认监听 `127.0.0.1:5000`；使用 `python launch.py --no-open-viewer` 可只启动服务，`--port 0` 可自动分配空闲端口。修改服务端代码后重启服务，修改索引或 Markdown 后刷新页面。ES Modules 需要通过 HTTP 加载，不支持直接双击 HTML 文件运行。

- 新增筛选：扩展 `emptyFilters()` 和 `filterPapers()`，在 HTML 添加输入，最后在 app 中绑定状态。
- 新增界面功能：在 components 中创建模块，由 app 注入所需元素、数据访问函数及回调。
- 新增服务端接口：在 `src/server.py` 添加路由，在 api 中封装调用，再供组件使用。
- 后端配置集中在 `src/config.py`；数据读取和校验位于 `src/load_data.py`；向量检索模块位于 `src/semantic_search/`。入口 `launch.py` 从项目根目录运行。
- 改变 JSON 格式：更新 repo 校验和访问方法；同步维护论文处理规范。界面开发说明维护在本文件。
- 论文记录保存在 `data/papers.json`，分类标签保存在 `data/taxonomy.json`。精细总结文档的虚拟路径按 `detailed_summaries/<paper_id>.md` 推导，实际文件位于 `data/detailed_summaries/`，路径统一按论文编号推导。
- 精细总结文档始终按需加载；向量命中通过 `paper_id` 映射记录，不使用数组下标。

## 本地检查

`node viewer/tests/smoke.mjs` 检查模块、筛选、交互和模拟 HTTP 调用，无需外部 API。该检查使用 DOM 替身，不能替代浏览器中的视觉检查。

`python viewer/tests/http_smoke.py` 临时启动仅监听 `127.0.0.1` 的实际 HTTP 服务，检查 JS/CSS 资源、JavaScript MIME 类型、三个数据文件、Markdown 及路径越界拦截，结束后关闭测试进程。两项检查均不调用嵌入服务。
