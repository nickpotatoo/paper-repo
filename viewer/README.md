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

后端使用 FastAPI + Uvicorn，需要 Python 3.10 或更新版本。首次运行前使用 `python -m pip install -r requirements.txt` 安装依赖。在项目根目录运行 `python launch.py` 启动服务并打开浏览器，保留当前监听地址 `0.0.0.0:5000`；浏览器自动打开本机可访问的 `http://127.0.0.1:5000/`。使用 `--no-open-viewer` 可只启动服务，`--port 0` 可自动分配空闲端口。默认在约十分钟无请求时退出；沿用现有命令行行为，`-s` 或 `--auto-shutdown` 会关闭自动退出。修改服务端代码后重启服务，修改索引或 Markdown 后刷新页面。ES Modules 需要通过 HTTP 加载，不支持直接双击 HTML 文件运行。

`src.routes.create_app(...)` 返回 FastAPI 应用，不绑定端口或打开浏览器；`src.server.launch(...)` 负责运行 Uvicorn，资料及查看器路径统一读取 `src/config.py`，不再接收路径参数。浏览器开关、自动退出、校验、端口和监听地址仍作为启动参数；`host` 可指定监听地址，例如 `host="127.0.0.1"`。自动退出由 `launch()` 向应用传入 `on_idle` 回调，连接应用空闲计时与 Uvicorn 的优雅关闭；单独托管 `create_app()` 时，宿主可通过该回调接管关闭。

模块边界：`src/server.py` 只负责端口绑定、Uvicorn 启动与浏览器打开，通过 `routes.create_app(...)` 获取应用。`src/routes.py` 负责应用创建、启动资料校验、HTTP 路由、请求/响应适配及 HTTP 活动计时，将数据读取转发给 `src.load_data`，语义检索转发给 semantic_search 提供的服务句柄。PaperVectorService 的延迟创建、生命周期锁与关闭都在 `src/semantic_search/lifecycle.py` 内部；存储操作锁仍由 VectorStore 管理。routes 只在应用 lifespan 接入 `paper_vector_service_lifespan(...)`，不直接创建或关闭服务。入口仍为 `python launch.py`。

`routes.py` 内部分工：`create_app()` 组装应用并接入模块生命周期；`_AppRuntime` 只记录 HTTP 请求活动与空闲计时，请求计数持续到响应发送完成。`create_router()` 分别注册 JSON、页面、心跳、静态资源、PDF、精细总结及搜索路由，未知路径兜底放在末尾。`_read_repo_json()` 统一数据读取和错误映射，`_serve_file()` 统一安全路径、文件读取、MIME 与响应头，`_parse_search_request()` 负责受限正文读取及搜索参数校验。检索通过当前服务句柄转发；路由层不持有服务锁、不调用 close、不访问内部存储或 HTTP 客户端。校验描述和检索失败类型通过模块 logger 输出，后者不记录查询正文、密钥或上游响应。

### HTTP 接口兼容

后端配置统一在 `src/config.py` 按路径、服务、检索请求限制、嵌入服务、向量存储与计算、文件哈希分组。命令行参数优先于启动默认值；修改配置后重启服务。`SERVER_PORT` 是命令行默认端口，直接调用 `launch(port=None)` 仍保留自动分配端口的行为。

前端不读取 Python 配置，也不新增配置接口。查询上限、数量范围仍在 `semantic-search.js` 和 `paper_viewer.html` 写死，数量默认值在 HTML 写死；`TOP_K` 只统一后端默认值。前端心跳仍在 `app.js` 中写死为 30000 ms，卡片单击延迟仍在 `paper-list.js` 中写死为 600 ms。涉及重复值的后端配置项已在注释中说明，修改时按需同步前端。

前端请求路径不变，无需修改 `viewer/js/api.js`：

| 请求 | 行为 |
| --- | --- |
| `GET /`、`GET /paper_viewer.html` | 返回原查看器页面 |
| `GET /papers.json`、`/taxonomy.json`、`/repo_state.json` | 每次读取原 JSON 文件；不存在返回 404，读取或格式错误返回 500，JSON 错误字段为 `error` |
| `GET /viewer/...`、`/vendor/...` | 返回原静态资源，JavaScript MIME 保持 `text/javascript` |
| `GET /files/pdfs/...`、`/files/detailed_summaries/...` | 从配置中的附件目录读取；拒绝目录越界与逃逸符号链接 |
| `GET /heartbeat` | 返回无正文的 204，延续服务活动时间 |
| `POST /api/semantic-search` | 接收 `query`、`top_k`，成功返回 `{"paper_ids": [...]}`，按原顺序去重 |
| 其他 `POST` 路径 | 返回 404 与 `{"error": "接口不存在"}` |

语义检索保留原校验：请求正文 1 至 32768 字节，查询 1 至 4000 字，`top_k` 为 1 至 100 的整数（不接受布尔值），默认 5；参数错误返回 400 和 `error`，不改为 FastAPI 默认的 422。检索依赖或服务失败返回 503。嵌入客户端继续延迟初始化，同步检索在线程池执行，检索和写入的串行锁由 VectorStore 自行管理；没有请求向量接口时不调用嵌入服务。退出时释放客户端连接。静态资源和 JSON 响应继续设置 `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`。

- 新增筛选：扩展 `emptyFilters()` 和 `filterPapers()`，在 HTML 添加输入，最后在 app 中绑定状态。
- 新增界面功能：在 components 中创建模块，由 app 注入所需元素、数据访问函数及回调。
- 新增服务端接口：在 `src/routes.py` 的 `create_router()` 中添加路由，具体路由放在通配路由之前；由应用层转发给相应业务模块，在前端 api 中封装调用，再供组件使用。无需修改 `src/server.py`。
- 后端配置集中在 `src/config.py`；数据读取和校验位于 `src/load_data.py`；向量检索模块位于 `src/semantic_search/`。入口 `launch.py` 从项目根目录运行。
- 改变 JSON 格式：更新 repo 校验和访问方法；同步维护论文处理规范。界面开发说明维护在本文件。
- 论文记录保存在 `data/papers.json`，分类标签保存在 `data/taxonomy.json`。精细总结文档的虚拟路径按 `detailed_summaries/<paper_id>.md` 推导，实际文件位于 `data/detailed_summaries/`，路径统一按论文编号推导。
- 精细总结文档始终按需加载；向量命中通过 `paper_id` 映射记录，不使用数组下标。

## 本地检查

`node viewer/tests/smoke.mjs` 检查模块、筛选、交互和模拟 HTTP 调用，无需外部 API。该检查使用 DOM 替身，不能替代浏览器中的视觉检查。

`python viewer/tests/http_smoke.py` 临时启动仅监听 `127.0.0.1` 的实际 HTTP 服务，检查 JS/CSS 资源、JavaScript MIME 类型、三个数据文件、Markdown 及路径越界拦截，结束后关闭测试进程。两项检查均不调用嵌入服务。
