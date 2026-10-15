export const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
export const compareCategoryIds = (a, b) => a.localeCompare(b, 'en', {numeric:true});

export function fileUrl(path) {
  const segments = path.replace(/\\/g, '/').split('/').map(encodeURIComponent).join('/');
  return new URL(segments, new URL('/files/', location.href)).href;
}

export function detailedSummaryPath(paper) {
  return `detailed_summaries/${paper.paper_id}.md`;
}

export function pdfUrl(paper, repo) {
  const path = repo.pdfPath(paper);
  return path ? fileUrl(`pdfs/${path}`) : '';
}
const addedDateFormatter = new Intl.DateTimeFormat("en-CA", {timeZone:"Asia/Shanghai", year:"numeric", month:"2-digit", day:"2-digit"});
export function addedDate(paper) {
  if (!paper.added_at) return '';
  const date = new Date(paper.added_at);
  if (Number.isNaN(date.getTime())) return '';
  const parts = Object.fromEntries(addedDateFormatter.formatToParts(date).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}
