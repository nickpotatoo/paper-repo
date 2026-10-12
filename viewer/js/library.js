import {compareCategoryIds} from './utils.js';

export function createLibrary(data) {
  if (!data || !Array.isArray(data.papers)) throw new Error('JSON 格式不正确：没有找到 papers 列表。');
  const papers = data.papers;
  const papersById = new Map();
  const categoryIndex = data.category_index || {};
  for (const [id, entry] of Object.entries(categoryIndex)) {
    if (!/^C[0-9]{3,}$/.test(id) || !entry || typeof entry.name !== 'string' || typeof entry.folder !== 'string' || typeof entry.description !== 'string') throw new Error(`分类索引格式不正确：${id}`);
  }
  const tagIndex = data.tag_index || {};
  for (const paper of papers) {
    const id = paper.paper_id;
    if (typeof id !== 'string' || !/^P[0-9]{6,}$/.test(id) || Number(id.slice(1)) < 1 || id !== `P${String(Number(id.slice(1))).padStart(6, '0')}`) throw new Error(`无效论文编号：${id}`);
    if (papersById.has(id)) throw new Error(`重复论文编号：${id}`);
    papersById.set(id, paper);
    const categoryId = paper.classification?.primary_category;
    if (!Object.hasOwn(categoryIndex, categoryId)) throw new Error(`未知分类索引：${categoryId}`);
    for (const id of paper.classification?.tags || []) {
      if (!Object.hasOwn(tagIndex, id)) throw new Error(`未知标签索引：${id}`);
    }
  }
  function tagName(id) {
    return tagIndex[id] || id;
  }

  function categoryName(id) {
    return categoryIndex[id] ? `${id} · ${categoryIndex[id].name}` : (id || '未分类');
  }

  function searchable(p) {
    const categoryId = p.classification?.primary_category;
    return [p.paper_id,p.metadata?.title,p.metadata?.document_type,categoryName(categoryId),categoryIndex[categoryId]?.description,...(p.classification?.tags||[]).map(tagName),p.summary].join(' ').toLocaleLowerCase();
  }
  return {
    papers, papersById, categoryIndex, tagIndex, tagName, categoryName, searchable,
    categories() { return Object.entries(categoryIndex).sort(([a], [b]) => compareCategoryIds(a, b)); },
  };
}
