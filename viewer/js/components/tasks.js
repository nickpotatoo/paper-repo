import {esc} from '../utils.js';
import {renderDetailedSummaryMarkdown} from '../markdown.js';

const TASK_REFRESH_INTERVAL_MS = 5000;

const statuses = {
  pending:'待处理', running:'进行中', waiting:'等待处理', failed:'失败',
  completed:'已完成', duplicate:'重复论文', cancelled:'已取消', skipped:'已跳过',
};
const stages = {
  prepare:'准备任务', deduplicate:'检查重复', extract:'提取 PDF', metadata:'提取元数据',
  classify:'生成分类', rough_summary:'生成粗略总结', detailed_summary:'生成精细总结',
  validate:'校验草稿', review:'审阅', vectorize:'生成向量', regenerate_classification:'重新生成分类',
  regenerate_metadata:'重新生成元数据',
  regenerate_rough_summary:'重新生成粗略总结', regenerate_detailed_summary:'重新生成精细总结',
};
const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone:'Asia/Shanghai', dateStyle:'medium', timeStyle:'medium',
});
const timestamp = value => Date.parse(value) || 0;
const contentActions = {
  metadata: {id:'regenerate_metadata', label:'重新生成元数据', success:'论文元数据已更新。'},
  classification: {id:'regenerate_classification', label:'重新生成分类', success:'论文分类已更新。'},
  'rough-summary': {id:'regenerate_rough_summary', label:'重新生成粗略总结', success:'粗略总结已更新。'},
  'detailed-summary': {id:'regenerate_detailed_summary', label:'重新生成精细总结', success:'精细总结已更新。'},
};
const label = (labels, value) => esc(Object.hasOwn(labels, value) ? labels[value] : value ?? '—');

const fieldNames = {
  title:'标题', authors:'作者', year:'年份', filename:'文件名', original_filename:'原始文件名',
  primary_category:'主分类', document_type:'文献类型', tags:'标签',
  proposed_categories:'候选分类', proposed_tags:'候选标签', proposed_document_types:'候选文献类型',
  name:'名称', description:'描述', issues:'问题', severity:'级别', message:'说明',
  status:'状态', page_count:'页数', duplicate_of:'匹配论文',
};

function renderJson(value, depth = 0) {
  if (value === null || value === '') return '<span class="task-json-muted">—</span>';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value !== 'object') return esc(value);
  if (depth >= 8) return `<pre class="task-plain-text">${esc(JSON.stringify(value, null, 2))}</pre>`;
  if (Array.isArray(value)) {
    if (!value.length) return '<span class="task-json-muted">无条目</span>';
    return `<ol class="task-json-array">${value.map(item => `<li>${renderJson(item, depth + 1)}</li>`).join('')}</ol>`;
  }
  const entries = Object.entries(value);
  if (!entries.length) return '<span class="task-json-muted">无字段</span>';
  return `<dl class="task-json-fields">${entries.map(([key, item]) =>
    `<div><dt>${label(fieldNames, key)}</dt><dd>${renderJson(item, depth + 1)}</dd></div>`).join('')}</dl>`;
}

function renderTask(task, expanded, generating) {
  const vectorStatus = generating ? 'running' : task.stages?.vectorize?.status;
  const taskStatus = generating ? 'running' : task.status;
  const stageRecords = Object.entries(task.stages ?? {}).filter(([id, stage]) =>
    (id !== 'vectorize' || task.paper_id) &&
    (!id.startsWith('regenerate_') || stage?.status !== 'pending' || id === task.current_stage),
  );
  const active = task.current_stage ? task.stages?.[task.current_stage] : null;
  const updated = timestamp(task.updated_at);
  let state = label(statuses, taskStatus);
  if (taskStatus === 'waiting' && task.current_stage === 'review') state = '待审阅';
  if (taskStatus === 'pending' && task.current_stage === 'vectorize') state = '待生成向量';
  const details = stageRecords.map(([id, stage]) => {
    const vectorRunning = id === 'vectorize' && generating;
    const note = vectorRunning ? null : stage?.error?.message || stage?.wait_reason;
    const current = id === task.current_stage;
    return `<li${current ? ' class="task-stage-current" aria-current="step"' : ''}>
      <span>${label(stages, id)}</span>
      <span>${label(statuses, vectorRunning ? 'running' : stage?.status)}</span>
      ${note ? `<small>${esc(note)}</small>` : ''}
    </li>`;
  }).join('');
  return `<details class="task-entry" data-task-id="${esc(task.task_id)}"${expanded ? ' open' : ''}>
    <summary>
      <span class="task-filename">${esc(task.source?.original_filename || task.task_id)}</span>
      <span class="task-state" data-state="${esc(taskStatus)}">${state}</span>
      <span class="task-quick-meta">
        ${task.current_stage ? `<span>${label(stages, task.current_stage)}</span>` : ''}
        ${updated ? `<time datetime="${esc(task.updated_at)}" title="北京时间">${dateFormatter.format(updated)}</time>` : ''}
      </span>
    </summary>
    <dl class="task-meta">
      <dt>任务 ID</dt><dd>${esc(task.task_id)}</dd>
      ${task.paper_id ? `<dt>入库编号</dt><dd>${esc(task.paper_id)}</dd>` : ''}
      ${task.duplicate_of ? `<dt>匹配论文</dt><dd>${esc(task.duplicate_of)}</dd>` : ''}
      ${!task.paper_id && active?.wait_reason ? `<dt>等待原因</dt><dd>${esc(active.wait_reason)}</dd>` : ''}
    </dl>
    ${details ? `<ol class="task-stages" aria-label="阶段进度">${details}</ol>` : ''}
    <div class="task-entry-actions">
      <div class="task-management-actions">
      <button class="action task-secondary" type="button" data-read-task="${esc(task.task_id)}">阅读任务内容</button>
      ${task.paper_id ? '' : '<button class="action task-secondary" type="button" data-manage-action="restart" aria-haspopup="dialog">重新执行</button>'}
      <button class="action task-secondary task-delete" type="button" data-manage-action="delete" aria-haspopup="dialog">删除任务</button>
      </div>
      ${!task.paper_id && task.can_ingest
        ? `<button class="action" type="button" data-ingest-task="${esc(task.task_id)}" aria-haspopup="dialog">入库</button>` : ''}
      ${task.paper_id && task.current_stage === 'vectorize' && vectorStatus !== 'completed'
        ? `<button class="action" type="button" data-vector-task="${esc(task.task_id)}"${vectorStatus === 'running' ? ' disabled' : ''}>${vectorStatus === 'running' ? '生成中…' : vectorStatus === 'failed' ? '重试生成向量' : '生成向量'}</button>` : ''}
    </div>
  </details>`;
}

export function setupTasks(api, onIngest = () => {}) {
  const dialog = document.querySelector('#tasks-dialog');
  const form = document.querySelector('#tasks-form');
  const password = document.querySelector('#tasks-password');
  const refreshButton = document.querySelector('#refresh-tasks');
  const status = document.querySelector('#tasks-status');
  const list = document.querySelector('#tasks-list');
  const filters = document.querySelector('#tasks-filters');
  const search = document.querySelector('#tasks-search');
  const statusFilter = document.querySelector('#tasks-status-filter');
  const reader = document.querySelector('#task-reader');
  const overview = document.querySelector('#tasks-overview');
  const overviewTitle = document.querySelector('#tasks-title');
  const title = document.querySelector('#task-reader-title');
  const backButton = document.querySelector('#close-task-reader');
  const contentsList = document.querySelector('#task-content-list');
  const contentStatus = document.querySelector('#task-content-status');
  const preview = document.querySelector('#task-preview');
  const previewTitle = document.querySelector('#task-preview-title');
  const previewStatus = document.querySelector('#task-preview-status');
  const previewBody = document.querySelector('#task-preview-body');
  const previewContent = document.querySelector('#task-preview-content');
  const ingestDialog = document.querySelector('#task-ingest-dialog');
  const ingestFilename = document.querySelector('#task-ingest-filename');
  const ingestStatus = document.querySelector('#task-ingest-status');
  const ingestCancel = document.querySelector('#cancel-task-ingest');
  const ingestConfirm = document.querySelector('#confirm-task-ingest');
  const manageDialog = document.querySelector('#task-manage-dialog');
  const manageTitle = document.querySelector('#task-manage-title');
  const manageDescription = document.querySelector('#task-manage-description');
  const manageStatus = document.querySelector('#task-manage-status');
  const manageCancel = document.querySelector('#cancel-task-manage');
  const manageConfirm = document.querySelector('#confirm-task-manage');
  let request = null;
  let refreshTimer = null;
  let autoRefreshEnabled = false;
  let contentRequest = null;
  let previewRequest = null;
  let previewTrigger = null;
  let activeTask = null;
  let availableContents = [];
  let sourceButton = null;
  let overviewScroll = 0;
  let tasks = [];
  let selectedForIngest = null;
  let managementSelection = null;
  const expandedTasks = new Set();
  const generatingTasks = new Set();
  const regeneratingTasks = new Set();
  const visibleStatus = task => generatingTasks.has(task.task_id) ? 'running' : task.status;

  function renderList() {
    for (const item of list.querySelectorAll('[data-task-id]')) {
      if (item.open) expandedTasks.add(item.dataset.taskId);
      else expandedTasks.delete(item.dataset.taskId);
    }
    const term = search.value.trim().toLowerCase();
    const visible = tasks.filter(task => {
      if (statusFilter.value && visibleStatus(task) !== statusFilter.value) return false;
      const filename = task.source?.original_filename ?? '';
      return !term || filename.toLowerCase().includes(term) || task.task_id.toLowerCase().includes(term);
    });
    list.innerHTML = visible.map(task =>
      renderTask(task, expandedTasks.has(task.task_id), generatingTasks.has(task.task_id)),
    ).join('');
    if (!tasks.length) status.textContent = '暂无论文处理任务。';
    else if (!visible.length) status.textContent = '没有符合条件的任务。';
    else status.textContent = `显示 ${visible.length} / ${tasks.length} 个任务`;
  }

  function refreshStatusOptions() {
    const selected = statusFilter.value;
    const counts = new Map();
    for (const task of tasks) {
      const state = visibleStatus(task);
      counts.set(state, (counts.get(state) ?? 0) + 1);
    }
    statusFilter.replaceChildren(
      new Option(`全部状态（${tasks.length}）`, ''),
      ...Object.keys(statuses).filter(status => status !== 'skipped' && (counts.has(status) || status === selected))
        .map(status => new Option(`${statuses[status]}（${counts.get(status) ?? 0}）`, status)),
    );
    statusFilter.value = selected;
  }

  function resetList() {
    tasks = [];
    expandedTasks.clear();
    list.replaceChildren();
    filters.hidden = true;
    search.value = '';
    statusFilter.value = '';
  }

  search.addEventListener('input', renderList);
  statusFilter.addEventListener('change', renderList);

  manageCancel.addEventListener('click', () => manageDialog.close());
  manageDialog.addEventListener('cancel', event => {
    if (manageConfirm.disabled) event.preventDefault();
  });
  manageDialog.addEventListener('close', scheduleRefresh);
  manageConfirm.addEventListener('click', async () => {
    if (!managementSelection || !password.value || manageConfirm.disabled) return;
    const {id, action} = managementSelection;
    manageConfirm.disabled = true;
    manageCancel.disabled = true;
    manageStatus.classList.remove('error');
    manageStatus.textContent = '正在提交…';
    try {
      if (action === 'delete') {
        await api.deleteTask(id, password.value);
        tasks = tasks.filter(task => task.task_id !== id);
      } else {
        const restarted = await api.restartTask(id, password.value);
        const task = tasks.find(item => item.task_id === id);
        if (task) Object.assign(task, restarted, {stages:{}, duplicate_of:null, can_ingest:false});
      }
      manageDialog.close();
      refreshStatusOptions();
      filters.hidden = !tasks.length;
      renderList();
      status.classList.remove('error');
      status.textContent = action === 'delete' ? '任务已归档。' : '已提交重新执行，可在任务列表查看进度。';
      refreshButton.focus();
    } catch (error) {
      manageStatus.classList.add('error');
      manageStatus.textContent = error.message || '操作失败。';
    } finally {
      manageConfirm.disabled = false;
      manageCancel.disabled = false;
    }
  });

  ingestCancel.addEventListener('click', () => ingestDialog.close());
  ingestDialog.addEventListener('cancel', event => {
    if (ingestConfirm.disabled) event.preventDefault();
  });
  ingestConfirm.addEventListener('click', async () => {
    if (!selectedForIngest || !password.value || ingestConfirm.disabled) return;
    const task = selectedForIngest;
    ingestConfirm.disabled = true;
    ingestCancel.disabled = true;
    ingestStatus.classList.remove('error');
    ingestStatus.textContent = '正在入库…';
    let paperId;
    try {
      paperId = await api.ingestTask(task.task_id, password.value);
    } catch (error) {
      ingestStatus.classList.add('error');
      ingestStatus.textContent = error.message || '入库失败。';
      return;
    } finally {
      ingestConfirm.disabled = false;
      ingestCancel.disabled = false;
    }
    task.paper_id = paperId;
    task.can_ingest = false;
    task.status = 'pending';
    task.current_stage = 'vectorize';
    task.stages = {
      ...task.stages,
      review: {...task.stages?.review, status:'completed', wait_reason:null, error:null},
      vectorize: {status:'pending'},
    };
    ingestDialog.close();
    refreshStatusOptions();
    renderList();
    status.textContent = `已入库：${paperId}，待生成向量。`;
    const entry = Array.from(list.querySelectorAll('[data-task-id]')).find(row => row.dataset.taskId === task.task_id);
    (entry?.querySelector('summary') ?? refreshButton).focus();
    onIngest();
  });

  function clearPreview() {
    previewRequest?.abort();
    previewRequest = null;
    previewContent.replaceChildren();
    previewStatus.textContent = '';
    previewStatus.classList.remove('error');
  }

  function closeReader() {
    contentRequest?.abort();
    contentRequest = null;
    previewTrigger = null;
    if (preview.open) preview.close();
    clearPreview();
    contentsList.replaceChildren();
    availableContents = [];
    contentStatus.textContent = '';
    contentStatus.classList.remove('error');
    activeTask = null;
    sourceButton = null;
    reader.hidden = true;
    title.hidden = true;
    backButton.hidden = true;
    overview.hidden = false;
    overviewTitle.hidden = false;
    dialog.setAttribute('aria-labelledby', 'tasks-title');
  }

  function goBack() {
    const button = sourceButton;
    closeReader();
    dialog.scrollTop = overviewScroll;
    button?.focus({preventScroll:true});
  }

  backButton.addEventListener('click', goBack);
  dialog.addEventListener('cancel', event => {
    if (reader.hidden) return;
    event.preventDefault();
    goBack();
  });

  document.querySelector('#close-task-preview').addEventListener('click', () => preview.close());
  preview.addEventListener('close', () => {
    if (preview.open) return;
    clearPreview();
    previewTrigger?.focus({preventScroll:true});
    previewTrigger = null;
  });

  async function openPdf(button) {
    const signal = contentRequest.signal;
    contentStatus.classList.remove('error');
    const tab = window.open('about:blank', '_blank');
    if (!tab) {
      contentStatus.classList.add('error');
      contentStatus.textContent = '浏览器拦截了新标签页，请允许弹出窗口后重试。';
      return;
    }
    tab.opener = null;
    button.disabled = true;
    button.textContent = '正在打开…';
    contentStatus.textContent = '';
    try {
      const {value} = await api.loadTaskContent(activeTask, 'pdf', password.value, signal);
      if (signal.aborted) {
        tab.close();
      } else if (!tab.closed) {
        const url = URL.createObjectURL(value);
        try {
          tab.location.replace(url);
        } finally {
          setTimeout(() => URL.revokeObjectURL(url), 60000);
        }
      }
      if (!signal.aborted) contentStatus.textContent = '';
    } catch (error) {
      tab.close();
      if (!signal.aborted) {
        contentStatus.classList.add('error');
        contentStatus.textContent = error.message || '打开 PDF 失败。';
      }
    } finally {
      button.disabled = false;
      button.textContent = '打开 PDF';
    }
  }

  function renderTaskContents() {
    const task = tasks.find(item => item.task_id === activeTask);
    const canRegenerate = task?.status === 'waiting' && task.current_stage === 'review' && !task.paper_id;
    const disabled = regeneratingTasks.has(activeTask) ? ' disabled' : '';
    contentsList.innerHTML = availableContents.map(({title, key}) => {
      const action = key === 'pdf' ? '打开 PDF' : '预览';
      const accessibleLabel = key === 'pdf' ? '在新标签页打开 PDF' : `预览${title}`;
      const regenerate = canRegenerate && Object.hasOwn(contentActions, key) ? contentActions[key] : null;
      return `<li>
        <span>${esc(title)}</span>
        <div class="task-content-actions">
          ${regenerate ? `<button class="action" type="button" data-regenerate-key="${esc(key)}"${disabled}>${regenerate.label}</button>` : ''}
          <button class="action" type="button" data-content-key="${esc(key)}" aria-label="${esc(accessibleLabel)}"${disabled}>${action}</button>
        </div>
      </li>`;
    }).join('');
  }

  async function regenerateContent(key) {
    const id = activeTask;
    if (!id || !password.value || regeneratingTasks.has(id) || !Object.hasOwn(contentActions, key)) return;
    const {id:action, label, success} = contentActions[key];
    regeneratingTasks.add(id);
    renderTaskContents();
    contentStatus.classList.remove('error');
    contentStatus.textContent = `正在${label}…`;
    let error;
    let result;
    try {
      result = await api.regenerateTaskContent(id, action, password.value);
    } catch (failure) {
      error = failure;
    } finally {
      regeneratingTasks.delete(id);
    }
    const task = tasks.find(item => item.task_id === id);
    const outcome = result?.stage_status ?? error?.stageStatus;
    if (task && outcome) {
      task.stages = {...task.stages, [action]: {
        status:outcome, error: error ? {message:error.message} : null,
      }};
      if (result?.updated_at) task.updated_at = result.updated_at;
    }
    if (activeTask !== id || !dialog.open) {
      if (dialog.open && !activeTask) renderList();
      return;
    }
    renderTaskContents();
    contentsList.querySelector(`[data-regenerate-key="${key}"]`)?.focus();
    contentStatus.classList.toggle('error', Boolean(error));
    contentStatus.textContent = error ? error.message : success;
  }

  contentsList.addEventListener('click', async event => {
    const regenerate = event.target.closest('[data-regenerate-key]');
    if (regenerate && !regenerate.disabled) {
      await regenerateContent(regenerate.dataset.regenerateKey);
      return;
    }
    const button = event.target.closest('[data-content-key]');
    if (!button || button.disabled || !activeTask || !password.value || preview.open) return;
    if (button.dataset.contentKey === 'pdf') {
      await openPdf(button);
      return;
    }
    clearPreview();
    const current = new AbortController();
    previewRequest = current;
    previewTrigger = button;
    previewTitle.textContent = button.closest('li').querySelector('span').textContent;
    previewStatus.textContent = '正在读取内容…';
    preview.showModal();
    previewBody.scrollTop = 0;
    try {
      const {kind, value} = await api.loadTaskContent(activeTask, button.dataset.contentKey, password.value, current.signal);
      if (previewRequest !== current || !preview.open) return;
      if (kind === 'json') {
        previewContent.innerHTML = renderJson(value);
      } else if (kind === 'markdown') {
        const markdown = document.createElement('div');
        markdown.className = 'markdown';
        markdown.innerHTML = renderDetailedSummaryMarkdown(value, {allowLinksAndImages:false});
        previewContent.append(markdown);
      } else {
        const text = document.createElement('pre');
        text.className = 'task-plain-text';
        text.textContent = value;
        previewContent.append(text);
      }
      previewStatus.textContent = '';
    } catch (error) {
      if (previewRequest === current && preview.open) {
        previewStatus.classList.add('error');
        previewStatus.textContent = error.message || '读取任务内容失败。';
      }
    }
  });

  async function generateVector(taskId) {
    const task = tasks.find(item => item.task_id === taskId);
    if (!task?.paper_id || task.current_stage !== 'vectorize' ||
        task.stages?.vectorize?.status === 'running' || generatingTasks.has(taskId)) return;
    generatingTasks.add(taskId);
    refreshStatusOptions();
    renderList();
    let nextStatus;
    let message;
    let failed = false;
    try {
      nextStatus = await api.generateTaskVector(taskId, password.value);
      message = nextStatus === 'completed' ? '向量已生成。' : '向量正在生成，可刷新查看结果。';
    } catch (error) {
      nextStatus = error.stageStatus;
      failed = true;
      message = error.message || '向量生成失败。';
    } finally {
      generatingTasks.delete(taskId);
    }
    const current = tasks.find(item => item.task_id === taskId);
    if (!dialog.open || !current) return;
    if (nextStatus) {
      current.status = nextStatus;
      current.current_stage = nextStatus === 'completed' ? null : 'vectorize';
      current.stages.vectorize = {
        ...current.stages.vectorize, status:nextStatus,
        error: nextStatus === 'failed' ? {message} : null,
      };
    }
    refreshStatusOptions();
    renderList();
    status.classList.toggle('error', failed);
    status.textContent = message;
  }

  list.addEventListener('click', async event => {
    const manageButton = event.target.closest('[data-manage-action]');
    if (manageButton && password.value && !refreshButton.disabled) {
      const id = manageButton.closest('[data-task-id]').dataset.taskId;
      const task = tasks.find(item => item.task_id === id);
      const action = manageButton.dataset.manageAction;
      if (!task || (action === 'restart' && task.paper_id)) return;
      request?.abort();
      request = null;
      clearTimeout(refreshTimer);
      managementSelection = {id, action};
      const filename = task.source?.original_filename || id;
      const deleting = action === 'delete';
      manageTitle.textContent = deleting ? '删除任务' : '重新执行';
      manageDescription.textContent = deleting
        ? `「${filename}」将从任务列表移除，任务文件会归档。已入库的论文和向量会保留。`
        : `「${filename}」将归档旧产物并从原始 PDF 重新处理。提取的文本将发送给已配置的大模型服务。`;
      manageConfirm.textContent = deleting ? '确认删除' : '确认重新执行';
      manageStatus.textContent = '';
      manageStatus.classList.remove('error');
      manageDialog.showModal();
      return;
    }
    const vectorButton = event.target.closest('[data-vector-task]');
    if (vectorButton && password.value && !refreshButton.disabled) {
      await generateVector(vectorButton.dataset.vectorTask);
      return;
    }
    const ingestButton = event.target.closest('[data-ingest-task]');
    if (ingestButton && password.value && !refreshButton.disabled) {
      selectedForIngest = tasks.find(task => task.task_id === ingestButton.dataset.ingestTask && task.can_ingest);
      if (selectedForIngest) {
        ingestFilename.textContent = selectedForIngest.source?.original_filename || selectedForIngest.task_id;
        ingestStatus.textContent = '';
        ingestStatus.classList.remove('error');
        ingestDialog.showModal();
      }
      return;
    }
    const button = event.target.closest('[data-read-task]');
    if (!button || !password.value || refreshButton.disabled) return;
    closeReader();
    sourceButton = button;
    overviewScroll = dialog.scrollTop;
    activeTask = button.dataset.readTask;
    title.textContent = button.closest('.task-entry').querySelector('.task-filename').textContent;
    overview.hidden = true;
    overviewTitle.hidden = true;
    title.hidden = false;
    backButton.hidden = false;
    reader.hidden = false;
    dialog.setAttribute('aria-labelledby', 'task-reader-title');
    dialog.scrollTop = 0;
    backButton.focus({preventScroll:true});
    const current = new AbortController();
    contentRequest = current;
    contentStatus.textContent = '正在读取可用内容…';
    try {
      const contents = await api.loadTaskContents(activeTask, password.value, current.signal);
      if (contentRequest !== current || !dialog.open) return;
      if (!contents.length) {
        contentStatus.textContent = '此任务尚无可阅读的内容。';
        return;
      }
      availableContents = contents;
      renderTaskContents();
      contentStatus.textContent = regeneratingTasks.has(activeTask) ? '正在处理，请稍候…' : '';
    } catch (error) {
      if (contentRequest === current && dialog.open) {
        contentStatus.classList.add('error');
        contentStatus.textContent = error.message || '读取内容列表失败。';
      }
    }
  });

  function stopAutoRefresh() {
    autoRefreshEnabled = false;
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }

  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    if (!autoRefreshEnabled || !dialog.open) return;
    refreshTimer = setTimeout(async () => {
      if (document.hidden || activeTask || ingestDialog.open || manageDialog.open || request) {
        scheduleRefresh();
        return;
      }
      await refresh({automatic:true});
    }, TASK_REFRESH_INTERVAL_MS);
  }

  async function refresh({automatic = false} = {}) {
    if (!dialog.open || !password.value || refreshButton.disabled) return;
    clearTimeout(refreshTimer);
    if (!automatic) closeReader();
    request?.abort();
    const current = new AbortController();
    request = current;
    if (!automatic) {
      refreshButton.disabled = true;
      status.classList.remove('error');
      status.textContent = '正在读取任务…';
    }
    try {
      const loaded = await api.loadTasks(password.value, current.signal);
      if (request !== current || !dialog.open) return;
      autoRefreshEnabled = true;
      if (automatic && (activeTask || ingestDialog.open || manageDialog.open)) return;
      const next = [...loaded].sort((a, b) => timestamp(b.updated_at) - timestamp(a.updated_at));
      if (automatic && !status.classList.contains('error') && JSON.stringify(next) === JSON.stringify(tasks)) return;
      const focused = document.activeElement;
      const focusedTask = focused?.closest('[data-task-id]')?.dataset.taskId;
      tasks = next;
      refreshStatusOptions();
      filters.hidden = !tasks.length;
      status.classList.remove('error');
      renderList();
      if (focusedTask) {
        const entry = Array.from(list.querySelectorAll('[data-task-id]')).find(row => row.dataset.taskId === focusedTask);
        const action = entry && Array.from(entry.querySelectorAll('button')).find(button =>
          !button.disabled && button.textContent === focused.textContent,
        );
        (action ?? entry?.querySelector('summary'))?.focus({preventScroll:true});
      }
      refreshButton.textContent = '立即刷新';
    } catch (error) {
      if (request === current && dialog.open) {
        const denied = [401, 403].includes(error.statusCode);
        if (!automatic || denied) {
          stopAutoRefresh();
          closeReader();
          resetList();
          refreshButton.textContent = '查看任务';
        }
        status.classList.add('error');
        status.textContent = error.message || '读取任务失败。';
      }
    } finally {
      if (request === current) {
        request = null;
        refreshButton.disabled = false;
        scheduleRefresh();
      }
    }
  }

  document.querySelector('#open-tasks').addEventListener('click', () => {
    closeReader();
    resetList();
    form.reset();
    refreshButton.textContent = '查看任务';
    status.textContent = '';
    status.classList.remove('error');
    dialog.showModal();
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    refresh();
  });
  password.addEventListener('input', () => {
    stopAutoRefresh();
    request?.abort();
    request = null;
    refreshButton.disabled = false;
    refreshButton.textContent = '查看任务';
  });
  document.querySelector('#close-tasks').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    if (dialog.open) return;
    stopAutoRefresh();
    closeReader();
    if (ingestDialog.open) ingestDialog.close();
    if (manageDialog.open) manageDialog.close();
    selectedForIngest = null;
    request?.abort();
    request = null;
    refreshButton.disabled = false;
    form.reset();
    resetList();
  });
}
