import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createApi} from '../js/api.js';
import {createLibrary} from '../js/library.js';
import {emptyFilters, filterPapers, groupPapers} from '../js/filters.js';
import {addedDate} from '../js/utils.js';
import {renderMethodMarkdown} from '../js/markdown.js';
import {createPaperList} from '../js/components/paper-list.js';
import {createPaperDetail} from '../js/components/paper-detail.js';
import {createSemanticSearch} from '../js/components/semantic-search.js';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const data = JSON.parse(readFileSync(new URL('../../paper_index.json', import.meta.url), 'utf8'));
const library = createLibrary(data);
const paper = library.papers[0];
const next = library.papers[1];
globalThis.location = {href:'http://127.0.0.1:8000/'};
globalThis.window = new EventTarget();
window.marked = require('../../vendor/marked.umd.js');
window.katex = require('../../vendor/katex/katex.min.js');

class Element extends EventTarget {
  value = '';
  innerHTML = '';
  textContent = '';
  hidden = false;
  disabled = false;
  open = false;
  children = new Map();
  classList = {toggle() {}, remove() {}, add() {}};
  querySelector(selector) {
    if (!this.children.has(selector)) this.children.set(selector, new Element());
    return this.children.get(selector);
  }
  contains() { return true; }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatchEvent(new Event('close')); }
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const fire = (element, type, fields = {}) => {
  const event = new Event(type, {cancelable:true});
  for (const [key, value] of Object.entries(fields)) Object.defineProperty(event, key, {value});
  element.dispatchEvent(event);
};
assert.equal(library.papersById.get(paper.paper_id), paper);
assert.throws(() => createLibrary({...data, papers:[paper, paper]}), /重复/);
assert.throws(() => createLibrary({...data, category_index:{}}), /未知分类/);
const extra = {name:'扩展分类', folder:'test', description:'测试'};
const expanded = createLibrary({...data, category_index:{C1000:extra, C010:extra, C006:extra, ...data.category_index}});
assert.deepEqual(expanded.categories().map(([id]) => id), ['C001','C002','C003','C004','C005','C006','C010','C1000']);
assert.equal(addedDate({added_at:'2026-10-07T16:00:00Z'}), '2026-10-08');
assert.equal(filterPapers(library, {...emptyFilters(), term:paper.paper_id}).matches.length, 1);
assert.throws(() => filterPapers(library, {...emptyFilters(), addedFrom:'2026-10-09', addedTo:'2026-10-01'}));
const synthetic = {...library, papers:[{...paper, added_at:'2026-10-07T16:00:00Z'}, {...next, added_at:null}]};
assert.equal(filterPapers(synthetic, {...emptyFilters(), addedFrom:'2026-10-08', addedTo:'2026-10-08'}).matches.length, 1);
assert.deepEqual(groupPapers(library.papers).map(([id]) => id), library.categories().map(([id]) => id).filter(id => library.papers.some(p => p.classification.primary_category === id)));
const semantic = {ids:[next.paper_id, paper.paper_id]};
assert.deepEqual(filterPapers(library, emptyFilters(), semantic).matches, [next, paper]);

let requests = [];
const api = createApi(async (url, options) => {
  requests.push({url, options});
  if (url === '/api/semantic-search') return {ok:true, json:async () => ({paper_ids:[next.paper_id, paper.paper_id, next.paper_id]})};
  return {ok:true, text:async () => '# Method'};
});
assert.equal(requests.length, 0);
await Promise.all([api.loadMethod(paper), api.loadMethod(paper)]);
await api.loadMethod(paper);
assert.equal(requests.length, 1);
assert.deepEqual(await api.semanticSearch('query', 5), [next.paper_id, paper.paper_id]);
assert.deepEqual(JSON.parse(requests.at(-1).options.body), {query:'query', top_k:5});
for (const source of ['$x+1$', '\\(x+1\\)', '$$x+1$$', '\\[x+1\\]']) {
  assert(renderMethodMarkdown(source).includes('class="katex"'), source);
}
assert(!renderMethodMarkdown('<script>alert(1)</script>').includes('<script>'));

const container = new Element();
const dialog = new Element();
const pending = new Map();
const detail = createPaperDetail({dialog, container, getLibrary:() => library,
  api:{loadMethod(p) { return new Promise(resolve => pending.set(p.paper_id, resolve)); }}});
detail.show(paper); detail.show(next);
pending.get(next.paper_id)('# New'); await flush();
const current = container.querySelector('#method-content').innerHTML;
pending.get(paper.paper_id)('# Old'); await flush();
assert.equal(container.querySelector('#method-content').innerHTML, current);
assert(container.innerHTML.includes(next.paper_id));

let pdfOpened = false;
globalThis.document = {body:{append() {}}, createElement:() => ({click() { pdfOpened = true; }, remove() {}})};
const cards = new Element(); let opened = [];
const list = createPaperList({container:cards, getLibrary:() => library, onOpen:p => opened.push(p.paper_id)});
list.render(groupPapers(library.papers), library, false);
assert(cards.innerHTML.includes(library.tagName(paper.classification.tags[0])));
const card = {dataset:{paper:paper.paper_id}};
const target = {closest:() => card};
fire(cards, 'click', {target}); fire(cards, 'dblclick', {target});
await new Promise(resolve => setTimeout(resolve, 650));
assert(pdfOpened); assert.equal(opened.length, 0);
fire(cards, 'keydown', {target, key:'Enter'}); assert.deepEqual(opened, [paper.paper_id]);

const searchUI = Object.fromEntries(['dialog','form','openButton','cancelButton','queryInput','topKInput','status','submitButton'].map(key => [key, new Element()]));
let resolveSearch; let received = [];
createSemanticSearch({...searchUI, api:{semanticSearch:() => new Promise(resolve => {resolveSearch = resolve;})}, onResults:result => received.push(result)});
searchUI.queryInput.value = 'memory'; searchUI.topKInput.value = '5';
fire(searchUI.openButton, 'click'); fire(searchUI.form, 'submit');
fire(searchUI.cancelButton, 'click'); resolveSearch([paper.paper_id]); await flush();
assert.equal(received.length, 0); assert(!searchUI.submitButton.disabled);
fire(searchUI.openButton, 'click'); fire(searchUI.form, 'submit');
resolveSearch([next.paper_id]); await flush(); assert.deepEqual(received[0].ids, [next.paper_id]);

const nodes = new Map();
document.querySelector = selector => { if (!nodes.has(selector)) nodes.set(selector, new Element()); return nodes.get(selector); };
globalThis.fetch = async url => ({ok:true, json:async () => data, text:async () => '# Method'});
await import('../js/app.js'); await flush(); await flush();
assert(nodes.get('#results').innerHTML.includes(paper.paper_id));
nodes.get('#search').value = paper.paper_id; fire(nodes.get('#search'), 'input');
assert(nodes.get('#results').innerHTML.includes(paper.paper_id));
assert(!nodes.get('#results').innerHTML.includes(`data-paper="${next.paper_id}"`));
fire(window, 'pagehide');
console.log('PASS: module startup, future categories, filters, Beijing dates, ranking, request caching, Markdown/LaTeX, detail races, card actions, semantic cancellation. No external API calls.');
