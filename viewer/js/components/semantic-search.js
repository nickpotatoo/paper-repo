export function createSemanticSearch({dialog, form, openButton, cancelButton, queryInput, topKInput, status, submitButton, api, onResults}) {
  let controller = null;
  function cancel() {
    controller?.abort(); controller = null; submitButton.disabled = false;
  }
  openButton.addEventListener('click', () => {
    status.textContent = ''; status.classList.remove('error');
    dialog.showModal(); queryInput.focus();
  });
  cancelButton.addEventListener('click', () => { cancel(); dialog.close(); });
  dialog.addEventListener('cancel', cancel);
  dialog.addEventListener('close', cancel);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const query = queryInput.value.trim();
    const topK = Number(topKInput.value);
    if (!query || query.length > 4000 || !Number.isInteger(topK) || topK < 1 || topK > 100) {
      status.textContent = '请输入 1 至 4000 字的搜索内容，结果数量为 1 至 100。';
      status.classList.add('error'); return;
    }
    cancel();
    const request = new AbortController(); controller = request;
    submitButton.disabled = true; status.classList.remove('error');
    status.textContent = '正在进行向量检索…';
    try {
      const ids = await api.semanticSearch(query, topK, request.signal);
      if (controller !== request) return;
      onResults({ids, query}); dialog.close();
    } catch (error) {
      if (error.name !== 'AbortError' && controller === request) {
        status.textContent = error.message; status.classList.add('error');
      }
    } finally {
      if (controller === request) { controller = null; submitButton.disabled = false; }
    }
  });
  return {cancel, setEnabled(enabled) { openButton.disabled = !enabled; }};
}
