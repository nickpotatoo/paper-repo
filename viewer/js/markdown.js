import {esc} from './utils.js';

export function renderDetailedSummaryMarkdown(source) {
  if (!source) return '<p>精细总结文档未载入。请在项目根目录运行 python launch.py 打开查看器。</p>';
  const formulas = [];
  const protectedText = source.replace(/(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\\)\$(?!\$)[^\n$]+?(?<!\\)\$)/g, expression => {
    const number = formulas.push(expression) - 1;
    return `PAPERMATH${number}END`;
  });
  const safeText = protectedText.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const html = window.marked ? window.marked.parse(safeText, {gfm:true, breaks:true}) : `<pre>${esc(source)}</pre>`;
  return html.replace(/PAPERMATH(\d+)END/g, (_, number) => {
    const expression = formulas[Number(number)];
    if (!window.katex) return `<code>${esc(expression)}</code>`;
    const display = expression.startsWith('$$') || expression.startsWith('\\[');
    const width = expression.startsWith('$$') || expression.startsWith('\\[') || expression.startsWith('\\(') ? 2 : 1;
    return window.katex.renderToString(expression.slice(width, -width), {displayMode:display, throwOnError:false, trust:false});
  });
}
