import {fileUrl} from './utils.js';

export function createApi(fetcher = (...args) => fetch(...args)) {
  const methodTexts = new Map();
  const pendingMethods = new Map();
  return {
    async loadIndex() {
      const response = await fetcher('/paper_index.json');
      if (!response.ok) throw new Error(`读取失败：${response.status}`);
      return response.json();
    },
    loadMethod(paper) {
      const id = paper.paper_id;
      if (!paper.method_document) return Promise.reject(new Error('索引未记录方法文档路径'));
      if (methodTexts.has(id)) return Promise.resolve(methodTexts.get(id));
      if (pendingMethods.has(id)) return pendingMethods.get(id);
      const job = fetcher(fileUrl(paper.method_document)).then(response => {
        if (!response.ok) throw new Error(`读取失败：${response.status}`);
        return response.text();
      }).then(text => { methodTexts.set(id, text); return text; });
      pendingMethods.set(id, job);
      job.then(() => pendingMethods.delete(id), () => pendingMethods.delete(id));
      return job;
    },
    clearMethods() { methodTexts.clear(); pendingMethods.clear(); },
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
