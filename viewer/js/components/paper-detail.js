import {esc, fileUrl, pdfUrl, detailedSummaryPath} from '../utils.js';
import {renderDetailedSummaryMarkdown} from '../markdown.js';

export function createPaperDetail({dialog, container, getRepo, api}) {
  let detailToken = 0;
  dialog.addEventListener('close', () => { detailToken++; });

  function show(paper) {
    const token = ++detailToken;
    const repo = getRepo();
    const info = paper.metadata || {};
    const file = pdfUrl(paper, repo);
    const detailedSummaryFile = fileUrl(detailedSummaryPath(paper));
    const tags = (paper.classification?.tags || []).map(id => `<span class="tag">${esc(repo.tagName(id))}</span>`).join(' ');
    container.innerHTML = `
      <button class="close" aria-label="关闭">×</button>
      <div class="type">${esc(repo.categoryName(paper.classification?.primary_category))} · ${esc(repo.documentTypeName(info.document_type))}</div>
      <h2>${esc(info.title || '未命名论文')}</h2>
      <div class="tags">${tags}</div>
      <section><h3>内容介绍</h3><p>${esc(paper.summary || '暂无')}</p></section>
      <section><h3>精细总结</h3>
        <div class="markdown" id="detailed-summary-content"><p>正在读取精细总结文档…</p></div>
        ${detailedSummaryFile ? `<a class="detailed-summary-link" href="${detailedSummaryFile}" target="_blank" rel="noopener">查看 Markdown 原文件 ↗</a>` : ''}
      </section>
      <section><h3>基本信息</h3><p>
        编号：${esc(paper.paper_id)}<br>入库时间：${esc(paper.added_at || '未记录')}<br>
        作者：${esc(info.authors || '未录入')}<br>年份：${esc(info.year || '未录入')}<br>文件：${esc(info.original_filename || '')}
      </p></section>
      ${file ? `<a class="open-pdf" href="${file}" target="_blank" rel="noopener">打开论文 PDF ↗</a>` : ''}`;
    container.querySelector('.close').addEventListener('click', () => dialog.close());
    if (!dialog.open) dialog.showModal();
    api.loadDetailedSummary(paper).then(markdown => {
      if (token === detailToken && dialog.open) {
        container.querySelector('#detailed-summary-content').innerHTML = renderDetailedSummaryMarkdown(markdown);
      }
    }).catch(error => {
      if (token === detailToken && dialog.open) {
        container.querySelector('#detailed-summary-content').innerHTML = `<p>精细总结文档加载失败：${esc(error.message)}。请在项目根目录运行 python launch.py 后刷新页面。</p>`;
      }
    });
  }

  return {show};
}
