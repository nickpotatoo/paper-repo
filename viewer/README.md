# 论文查看器开发说明

查看器使用原生 JavaScript ES Modules，无需 npm 安装或构建。根目录 `paper_viewer.html` 保存页面布局，通过 `viewer/js/app.js` 初始化。CSS 位于 `viewer/styles/main.css`；Marked 和 KaTeX 继续使用根目录 `vendor/` 中的本地依赖。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `js/app.js` | 页面入口；集中管理 library、filters、semantic 状态；连接组件和更新结果 |
| `js/api.js` | 索引、Markdown、语义搜索及心跳 HTTP 请求；按论文 ID 缓存 Markdown 和合并进行中的加载请求 |
| `js/library.js` | 校验索引结构和编号引用；按 ID 查询论文；解析分类和标签；组合搜索文本 |
| `js/filters.js` | 根据筛选条件计算结果；按分类 ID 排序分组；保留向量检索结果顺序 |
| `js/utils.js` | HTML 转义、分类编号比较、文件 URL、北京时间日期转换 |
| `js/markdown.js` | Markdown 及四种 LaTeX 定界符渲染 |
| `js/components/paper-list.js` | 分组和卡片展示；通过事件委托处理单击、双击、键盘操作 |
| `js/components/paper-detail.js` | 详情弹窗和方法文档延迟加载；防止旧请求覆盖新的详情 |
| `js/components/semantic-search.js` | 向量搜索弹窗、参数检查、请求取消和结果回调 |

数据流：`api.loadIndex()` → `createLibrary()` → app 状态 → `filterPapers()` / `groupPapers()` → 卡片。组件通过回调报告操作，不直接修改其他组件。HTTP 请求集中在 api 模块中，索引和筛选模块不访问 DOM。

## 运行与扩展

继续双击项目根目录 `start_viewer.bat`。需要重启旧的 Python 服务，使新增 `/viewer/` 静态资源路由生效；随后刷新页面。ES Modules 需要通过 HTTP 加载，不支持直接双击 HTML 文件运行。

- 新增筛选：扩展 `emptyFilters()` 和 `filterPapers()`，在 HTML 添加输入，最后在 app 中绑定状态。
- 新增界面功能：在 components 中创建模块，由 app 注入所需元素、数据访问函数及回调。
- 新增服务端接口：在 `paper_server.py` 添加路由，在 api 中封装调用，再供组件使用。
- 改变 JSON 格式：先更新 library 校验和访问方法；同步维护论文处理规范。界面开发说明维护在本文件。
- 方法文档始终按需加载；向量命中通过 `paper_id` 映射记录，不使用数组下标。

## 本地检查

`node viewer/tests/smoke.mjs` 检查模块、筛选、交互和模拟 HTTP 调用，无需外部 API。该检查使用 DOM 替身，不能替代浏览器中的视觉检查。

`python viewer/tests/http_smoke.py` 临时启动仅监听 `127.0.0.1` 的实际 HTTP 服务，检查 JS/CSS 资源、JavaScript MIME 类型、HTML/索引及路径越界拦截，结束后关闭测试进程。两项检查均不调用嵌入服务。
