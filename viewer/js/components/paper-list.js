import {esc, addedDate, pdfUrl} from '../utils.js';


export function createPaperList({container, getLibrary, onOpen}) {
  const clickTimers = new Map();
  function cancelClick(id) { clearTimeout(clickTimers.get(id)); clickTimers.delete(id); }
  function cardFor(event) {
    const card = event.target.closest('.card');
    return card && container.contains(card) ? card : null;
  }
  container.addEventListener('click', event => {
    const card = cardFor(event);
    if (!card) return;
    const id = card.dataset.paper;
    cancelClick(id);
    clickTimers.set(id, setTimeout(() => {
      clickTimers.delete(id);
      const paper = getLibrary().papersById.get(id);
      if (paper) onOpen(paper);
    }, 600));
  });
  container.addEventListener('dblclick', event => {
    const card = cardFor(event);
    if (!card) return;
    cancelClick(card.dataset.paper);
    const paper = getLibrary().papersById.get(card.dataset.paper);
    const file = paper && pdfUrl(paper);
    if (!file) return;
    const link = document.createElement('a');
    link.href = file; link.target = '_blank'; link.rel = 'noopener';
    document.body.append(link); link.click(); link.remove();
  });
  container.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const card = cardFor(event);
    if (!card) return;
    event.preventDefault(); cancelClick(card.dataset.paper);
    const paper = getLibrary().papersById.get(card.dataset.paper);
    if (paper) onOpen(paper);
  });
  function cancelAll() { for (const id of clickTimers.keys()) cancelClick(id); }
  return {
    showEmpty(message) { cancelAll(); container.innerHTML = `<div class="empty">${esc(message)}</div>`; },
    render(orderedGroups, library, isSemantic) {
      cancelAll();
      container.innerHTML = orderedGroups.map(([name, papers]) => `
        <section>
          <div class="group">${esc(isSemantic ? name : library.categoryName(name))}
            <span class="group-count">· ${papers.length} 篇</span>
          </div>
          <div class="grid">${papers.map(paper => `
            <article class="card" tabindex="0" role="button" data-paper="${esc(paper.paper_id)}" aria-label="查看 ${esc(paper.metadata?.title)}">
              <div class="type">${esc(paper.paper_id)} · ${esc(paper.metadata?.document_type || '论文')}</div>
              <h2>${esc(paper.metadata?.title || '未命名论文')}</h2>
              <p class="desc">${esc(paper.summary || '')}</p>
              <div class="type added-date">入库日期：${esc(addedDate(paper) || '未记录')}</div>
              <div class="tags">${(paper.classification?.tags || []).slice(0, 4).map(id => `<span class="tag">${esc(library.tagName(id))}</span>`).join('')}</div>
            </article>`).join('')}
          </div>
        </section>`).join('');
    },
  };
}
