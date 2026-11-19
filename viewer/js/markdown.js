import {esc} from './utils.js';

function safeMarkdownUrl(href, allowMail = false) {
  try {
    const url = new URL(href, window.location.href);
    if (url.protocol === 'http:' || url.protocol === 'https:' || (allowMail && url.protocol === 'mailto:')) {
      return url.href;
    }
  } catch {
    return null;
  }
  return null;
}

export function renderDetailedSummaryMarkdown(source, {allowLinksAndImages = true} = {}) {
  if (!source) return '<p>精细总结文档未载入。请在项目根目录运行 python launch.py 打开查看器。</p>';
  const formulas = [];
  const protectedText = source.replace(/(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\\)\$(?!\$)[^\n$]+?(?<!\\)\$)/g, expression => {
    const number = formulas.push(expression) - 1;
    return `PAPERMATH${number}END`;
  });
  const safeText = protectedText.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const options = {gfm:true, breaks:true};
  if (window.marked) {
    const renderer = new window.marked.Renderer();
    const {link, image} = renderer;
    renderer.link = function (token) {
      const href = allowLinksAndImages && safeMarkdownUrl(token.href, true);
      return href ? link.call(this, {...token, href}) : this.parser.parseInline(token.tokens);
    };
    renderer.image = function (token) {
      const href = allowLinksAndImages && safeMarkdownUrl(token.href);
      return href ? image.call(this, {...token, href}) : esc(token.text);
    };
    options.renderer = renderer;
  }
  const html = window.marked ? window.marked.parse(safeText, options) : `<pre>${esc(source)}</pre>`;
  return html.replace(/PAPERMATH(\d+)END/g, (_, number) => {
    const expression = formulas[Number(number)];
    if (expression === undefined) return _;
    if (!window.katex) return `<code>${esc(expression)}</code>`;
    const display = expression.startsWith('$$') || expression.startsWith('\\[');
    const width = expression.startsWith('$$') || expression.startsWith('\\[') || expression.startsWith('\\(') ? 2 : 1;
    return window.katex.renderToString(expression.slice(width, -width), {displayMode:display, throwOnError:false, trust:false});
  });
}
