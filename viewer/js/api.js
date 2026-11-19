import {fileUrl, detailedSummaryPath, encodeServicePassword} from './utils.js';

export function createApi(fetcher = (...args) => fetch(...args)) {
  const detailedSummaryTexts = new Map();
  const pendingDetailedSummaries = new Map();
  async function getJson(url) {
    const response = await fetcher(url);
    if (!response.ok) throw new Error(`读取失败：${response.status} (${url})`);
    return response.json();
  }
  async function getTaskResponse(path, password, signal, method = 'GET') {
    const response = await fetcher(path, {
      method, signal, cache:'no-store', headers:{'X-Service-Password':encodeServicePassword(password)},
    });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      const error = new Error(data?.error || `任务请求失败（HTTP ${response.status}）`);
      error.statusCode = response.status;
      error.stageStatus = data?.stage_status;
      throw error;
    }
    return response;
  }
  return {
    loadPapers() { return getJson('/papers.json'); },
    loadTaxonomy() { return getJson('/taxonomy.json'); },
    async loadTasks(password, signal) {
      const response = await getTaskResponse('/api/tasks', password, signal);
      const data = await response.json();
      if (!Array.isArray(data?.tasks) ||
          data.tasks.some(task => !task || typeof task.task_id !== 'string')) {
        throw new Error('任务接口返回格式不正确。');
      }
      return data.tasks;
    },
    async loadTaskContents(taskId, password, signal) {
      const path = `/api/tasks/${encodeURIComponent(taskId)}/contents`;
      const response = await getTaskResponse(path, password, signal);
      const data = await response.json();
      if (!Array.isArray(data?.contents) || data.contents.some(item =>
        typeof item?.key !== 'string' || typeof item?.title !== 'string')) {
        throw new Error('任务内容列表格式不正确。');
      }
      return data.contents;
    },
    async regenerateTaskContent(taskId, action, password) {
      const path = `/api/tasks/${encodeURIComponent(taskId)}/regenerate/${encodeURIComponent(action)}`;
      const response = await getTaskResponse(path, password, undefined, 'POST');
      return response.json();
    },
    async deleteTask(taskId, password) {
      const path = `/api/tasks/${encodeURIComponent(taskId)}`;
      await getTaskResponse(path, password, undefined, 'DELETE');
    },
    async restartTask(taskId, password) {
      const path = `/api/tasks/${encodeURIComponent(taskId)}/restart`;
      const response = await getTaskResponse(path, password, undefined, 'POST');
      return response.json();
    },
    async ingestTask(taskId, password) {
      const path = `/api/tasks/${encodeURIComponent(taskId)}/ingest`;
      const response = await getTaskResponse(path, password, undefined, 'POST');
      const data = await response.json();
      if (typeof data?.paper_id !== 'string') throw new Error('入库结果缺少论文编号。');
      return data.paper_id;
    },
    async generateTaskVector(taskId, password) {
      const path = `/api/tasks/${encodeURIComponent(taskId)}/vector`;
      const response = await getTaskResponse(path, password, undefined, 'POST');
      const data = await response.json();
      if (!['running', 'completed'].includes(data?.stage_status)) throw new Error('向量生成结果格式不正确。');
      return data.stage_status;
    },
    async loadTaskContent(taskId, key, password, signal) {
      const path = `/api/tasks/${encodeURIComponent(taskId)}/contents/${encodeURIComponent(key)}`;
      const response = await getTaskResponse(path, password, signal);
      if (key === 'pdf') return {kind:'pdf', value:await response.blob()};
      if (response.headers.get('content-type')?.startsWith('application/json')) {
        return {kind:'json', value:await response.json()};
      }
      const kind = ['detailed-summary', 'extracted-text'].includes(key) ? 'markdown' : 'text';
      return {kind, value:await response.text()};
    },
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
