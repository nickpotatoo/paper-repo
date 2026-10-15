import {fileUrl, detailedSummaryPath} from './utils.js';

export function createApi(fetcher = (...args) => fetch(...args)) {
  const detailedSummaryTexts = new Map();
  const pendingDetailedSummaries = new Map();
  async function getJson(url) {
    const response = await fetcher(url);
    if (!response.ok) throw new Error(`读取失败：${response.status} (${url})`);
    return response.json();
  }
  return {
    loadPapers() { return getJson('/papers.json'); },
    loadTaxonomy() { return getJson('/taxonomy.json'); },
    loadDetailedSummary(paper) {
      const id = paper.paper_id;
      if (detailedSummaryTexts.has(id)) return Promise.resolve(detailedSummaryTexts.get(id));
      if (pendingDetailedSummaries.has(id)) return pendingDetailedSummaries.get(id);
      const job = fetcher(fileUrl(detailedSummaryPath(paper))).then(response => {
        if (!response.ok) throw new Error(`读取失败：${response.status}`);
        return response.text();
      }).then(text => { detailedSummaryTexts.set(id, text); return text; });
      pendingDetailedSummaries.set(id, job);
      job.then(() => pendingDetailedSummaries.delete(id), () => pendingDetailedSummaries.delete(id));
      return job;
    },
    clearDetailedSummaries() { detailedSummaryTexts.clear(); pendingDetailedSummaries.clear(); },
    async semanticSearch(query, topK, signal) {
      const response = await fetcher('/api/semantic-search', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({query, top_k:topK}), signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `检索失败：${response.status}`);
      if (!Array.isArray(data.paper_ids) || data.paper_ids.some(id => typeof id !== 'string')) throw new Error('检索接口返回格式不正确');
      return [...new Set(data.paper_ids)];
    },
    heartbeat() { return fetcher('/heartbeat').catch(() => {}); },
  };
}
