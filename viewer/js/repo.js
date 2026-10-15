import {compareCategoryIds} from './utils.js';

export function createRepo(papers, taxonomy) {
  if (!Array.isArray(papers)) throw new Error('papers.json 格式不正确：需要论文数组。');
  if (!taxonomy || typeof taxonomy !== 'object' || Array.isArray(taxonomy)) throw new Error('taxonomy.json 格式不正确：需要分类与标签对象。');
  const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  if (!isObject(taxonomy.category_index) || !isObject(taxonomy.tag_index) || !isObject(taxonomy.document_type_index)) throw new Error('taxonomy.json 必须包含 category_index、tag_index 和 document_type_index 字典。');
  const papersById = new Map();
  const categoryIndex = taxonomy.category_index;
  for (const [id, entry] of Object.entries(categoryIndex)) {
    if (!/^C[0-9]{3,}$/.test(id) || !entry || typeof entry.name !== 'string' || typeof entry.description !== 'string') throw new Error(`分类索引格式不正确：${id}`);
  }
  const tagIndex = taxonomy.tag_index;
  const documentTypeIndex = taxonomy.document_type_index;
  for (const [id, name] of Object.entries(documentTypeIndex)) {
    if (!/^D[0-9]{3,}$/.test(id) || Number(id.slice(1)) < 1 || typeof name !== 'string' || !name.trim()) throw new Error(`文献类型索引格式不正确：${id}`);
  }
  for (const paper of papers) {
    if (!isObject(paper)) throw new Error('论文记录必须是对象。');
    const id = paper.paper_id;
    if (typeof id !== 'string' || !/^P[0-9]{6,}$/.test(id) || Number(id.slice(1)) < 1 || id !== `P${String(Number(id.slice(1))).padStart(6, '0')}`) throw new Error(`无效论文编号：${id}`);
    if (papersById.has(id)) throw new Error(`重复论文编号：${id}`);
    papersById.set(id, paper);
    if (typeof paper.metadata?.document_type !== 'string' || !Object.hasOwn(documentTypeIndex, paper.metadata.document_type)) throw new Error(`未知文献类型索引：${paper.metadata?.document_type}`);
    const categoryId = paper.classification?.primary_category;
    if (!Object.hasOwn(categoryIndex, categoryId)) throw new Error(`未知分类索引：${categoryId}`);
    const filename = paper.metadata?.filename;
    if (typeof filename !== 'string' || !filename || /[/\\:\0]/.test(filename) || !/\.pdf$/i.test(filename)) throw new Error(`无效 PDF 文件名：${id}`);
    const tags = paper.classification?.tags;
    if (!Array.isArray(tags)) throw new Error(`论文标签必须是数组：${id}`);
    for (const id of tags) {
      if (!Object.hasOwn(tagIndex, id)) throw new Error(`未知标签索引：${id}`);
    }
  }
  function tagName(id) {
    return tagIndex[id] || id;
  }
  function documentTypeName(id) {
    return documentTypeIndex[id] || id || '论文';
  }

  function categoryName(id) {
    return categoryIndex[id] ? `${id} · ${categoryIndex[id].name}` : (id || '未分类');
  }

  function pdfPath(paper) {
    return `${paper.classification.primary_category}/${paper.metadata.filename}`;
  }

  function searchable(p) {
    const categoryId = p.classification?.primary_category;
    return [p.paper_id,p.metadata?.title,p.metadata?.document_type,documentTypeName(p.metadata?.document_type),categoryName(categoryId),categoryIndex[categoryId]?.description,...(p.classification?.tags||[]).map(tagName),p.summary].join(' ').toLocaleLowerCase();
  }
  return {
    papers, papersById, categoryIndex, tagIndex, documentTypeIndex, tagName, documentTypeName, categoryName, searchable, pdfPath,
    categories() { return Object.entries(categoryIndex).sort(([a], [b]) => compareCategoryIds(a, b)); },
  };
}
