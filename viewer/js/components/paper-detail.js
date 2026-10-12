import {esc, fileUrl, pdfUrl} from '../utils.js';
import {renderMethodMarkdown} from '../markdown.js';

export function createPaperDetail({dialog, container, getLibrary, api}) {
  let detailToken = 0;
  dialog.addEventListener('close', () => { detailToken++; });

  function show(paper) {
    const token = ++detailToken;
    const library = getLibrary();
    const info = paper.metadata || {};
    const file = pdfUrl(paper);
    const methodFile = paper.method_document ? fileUrl(paper.method_document) : '';
    const tags = (paper.classification?.tags || []).map(id => `<span class="tag">${esc(library.tagName(id))}</span>`).join(' ');
    container.innerHTML = `
      <button class="close" aria-label="关闭">×</button>
      <div class="type">${esc(library.categoryName(paper.classification?.primary_category))} · ${esc(info.document_type || '论文')}</div>
      <h2>${esc(info.title || '未命名论文')}</h2>
      <div class="tags">${tags}</div>
      <section><h3>内容介绍</h3><p>${esc(paper.summary || '暂无')}</p></section>
      <section><h3>方法介绍</h3>
        <div class="markdown" id="method-content"><p>正在读取方法文档…</p></div>
        ${methodFile ? `<a class="method-link" href="${methodFile}" target="_blank" rel="noopener">查看 Markdown 原文件 ↗</a>` : ''}
      </section>
      <section><h3>基本信息</h3><p>
        编号：${esc(paper.paper_id)}<br>入库时间：${esc(paper.added_at || '未记录')}<br>
        作者：${esc(info.authors || '未录入')}<br>年份：${esc(info.year || '未录入')}<br>文件：${esc(info.original_filename || '')}
      </p></section>
      ${file ? `<a class="open-pdf" href="${file}" target="_blank" rel="noopener">打开论文 PDF ↗</a>` : ''}`;
    container.querySelector('.close').addEventListener('click', () => dialog.close());
    if (!dialog.open) dialog.showModal();
    api.loadMethod(paper).then(markdown => {
      if (token === detailToken && dialog.open) {
        container.querySelector('#method-content').innerHTML = renderMethodMarkdown(markdown);
      }
    }).catch(error => {
      if (token === detailToken && dialog.open) {
        container.querySelector('#method-content').innerHTML = `<p>方法文档加载失败：${esc(error.message)}。请重新运行 start_viewer.bat。</p>`;
      }
    });
  }

  return {show};
}
