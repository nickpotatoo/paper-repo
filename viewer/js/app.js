import {createApi} from './api.js';
import {createRepo} from './repo.js';
import {emptyFilters, filterPapers, groupPapers} from './filters.js';
import {esc} from './utils.js';
import {createPaperList} from './components/paper-list.js';
import {createPaperDetail} from './components/paper-detail.js';
import {createSemanticSearch} from './components/semantic-search.js';

const element = selector => document.querySelector(selector);
const ui = {
  search:element('#search'), category:element('#category'), addedFrom:element('#added-from'),
  addedTo:element('#added-to'), status:element('#status'), clearSemantic:element('#clear-semantic'),
};
const state = {repo:null, filters:emptyFilters(), semantic:null};
const api = createApi();
const getRepo = () => state.repo;
const detail = createPaperDetail({dialog:element('#dialog'), container:element('#detail'), getRepo, api});
const list = createPaperList({container:element('#results'), getRepo, onOpen:detail.show});
const semantic = createSemanticSearch({
  dialog:element('#semantic-dialog'), form:element('#semantic-form'), openButton:element('#open-semantic'),
  cancelButton:element('#semantic-cancel'), queryInput:element('#semantic-query'), topKInput:element('#semantic-top-k'),
  status:element('#semantic-status'), submitButton:element('#semantic-submit'), api,
  onResults(result) {
    state.semantic = {ids:result.ids.filter(id => state.repo.papersById.has(id)), query:result.query};
    state.filters.term = ''; state.filters.categoryId = '';
    syncFilters(); ui.clearSemantic.hidden = false; render();
  },
});

function setStatus(message, error = false) {
  ui.status.textContent = message; ui.status.classList.toggle('error', error);
}
function syncFilters() {
  ui.search.value = state.filters.term; ui.category.value = state.filters.categoryId;
  ui.addedFrom.value = state.filters.addedFrom; ui.addedTo.value = state.filters.addedTo;
}
function readFilters() {
  state.filters = {term:ui.search.value, categoryId:ui.category.value, addedFrom:ui.addedFrom.value, addedTo:ui.addedTo.value};
  render();
}
function render() {
  if (!state.repo) return;
  try {
    const {candidates, matches} = filterPapers(state.repo, state.filters, state.semantic);
    setStatus(state.semantic
      ? `向量检索「${state.semantic.query}」：返回 ${candidates.length} 篇，当前显示 ${matches.length} 篇（按检索顺序）`
      : `已载入 ${state.repo.papers.length} 篇论文，当前显示 ${matches.length} 篇；打开卡片时读取对应精细总结文档`);
    if (!matches.length) { list.showEmpty('没有找到符合条件的论文。'); return; }
    list.render(groupPapers(matches, state.semantic), state.repo, state.semantic !== null);
  } catch (error) {
    setStatus(error.message, true); list.showEmpty('请调整入库日期范围。');
  }
}

ui.search.addEventListener('input', readFilters);
ui.category.addEventListener('change', readFilters);
ui.addedFrom.addEventListener('input', readFilters);
ui.addedTo.addEventListener('input', readFilters);
element('#clear-dates').addEventListener('click', () => {
  state.filters.addedFrom = ''; state.filters.addedTo = ''; syncFilters(); render();
});
ui.clearSemantic.addEventListener('click', () => {
  state.semantic = null; state.filters = emptyFilters(); ui.clearSemantic.hidden = true; syncFilters(); render();
});

Promise.all([api.loadPapers(), api.loadTaxonomy()]).then(([papers, taxonomy]) => {
  state.repo = createRepo(papers, taxonomy); api.clearDetailedSummaries();
  ui.category.innerHTML = '<option value="">全部分类</option>' + state.repo.categories()
    .map(([id, entry]) => `<option value="${esc(id)}" title="${esc(entry.description)}">${esc(state.repo.categoryName(id))}</option>`).join('');
  // Preserve input typed while the data was loading.
  readFilters(); semantic.setEnabled(true);
}).catch(error => setStatus(`无法读取论文资料：${error.message}。请在项目根目录运行 python launch.py 后刷新页面。`, true));
const heartbeat = setInterval(() => api.heartbeat(), 30000);
window.addEventListener('pagehide', () => { clearInterval(heartbeat); semantic.cancel(); });
