import {addedDate, compareCategoryIds} from './utils.js';

export function emptyFilters() {
  return {term:'', categoryId:'', addedFrom:'', addedTo:''};
}

export function filterPapers(repo, filters, semantic = null) {
  const {term, categoryId, addedFrom, addedTo} = filters;
  if (addedFrom && addedTo && addedFrom > addedTo) throw new Error('起始日期不能晚于结束日期。');
  const candidates = semantic === null ? repo.papers : semantic.ids.map(id => repo.papersById.get(id)).filter(Boolean);
  const query = term.trim().toLocaleLowerCase();
  const matches = candidates.filter(paper => {
    if (categoryId && paper.classification?.primary_category !== categoryId) return false;
    if (query && !repo.searchable(paper).includes(query)) return false;
    if (addedFrom || addedTo) {
      const date = addedDate(paper);
      if (!date || (addedFrom && date < addedFrom) || (addedTo && date > addedTo)) return false;
    }
    return true;
  });
  return {candidates, matches};
}

export function groupPapers(papers, semantic = null) {
  const groups = new Map();
  for (const paper of papers) {
    const key = semantic === null ? (paper.classification?.primary_category || '未分类') : '向量检索结果';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(paper);
  }
  const entries = [...groups];
  if (semantic === null) entries.sort(([a], [b]) => compareCategoryIds(a, b));
  return entries;
}
