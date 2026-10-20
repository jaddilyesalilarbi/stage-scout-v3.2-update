// Run the actual application against a small DOM boundary, without browser packages.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '..', 'dashboard-src', 'app.js'), 'utf8');

function dashboard(overrides = {}, saved = {}) {
  const nodes = new Map();
  const storage = new Map([['stage-scout-review-v4', JSON.stringify(saved)]]);
  const downloads = [];
  const job = { id:'stable-id', company:'ACME', title:'Mechanical intern', location:'Paris',
    country:'France', score:70, source:'Lever', kind:'Internship', why:'CAD',
    description_excerpt:'Short summary', description:'Full description\nTAIL <script>bad()</script>',
    description_url:'https://x.test/job?x=1&y=2', apply_url:'https://x.test/job/apply',
    url:'https://x.test/job', ...overrides };
  function element(id) {
    if (!nodes.has(id)) nodes.set(id, { value:'', checked:false, hidden:false, textContent:'',
      innerHTML:'', listeners:{}, classList:{add(){},remove(){},toggle(){}},
      addEventListener(name, callback){this.listeners[name] = callback;},
      appendChild(){}, setAttribute(){}, remove(){}, click(){this.listeners.click?.({});} });
    return nodes.get(id);
  }
  element('job-data').textContent = JSON.stringify({jobs:[job], meta:{}, coverage:[]});
  const context = {
    document:{getElementById:element, createElement:()=>element(Symbol()),
      querySelector:()=>element(Symbol()), addEventListener(){}, body:{appendChild(){}}},
    localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
    window:{matchMedia:()=>({matches:false})}, console, Blob,
    URL:{createObjectURL:blob=>{downloads.push(blob);return 'blob:test';}, revokeObjectURL(){}},
    setTimeout:()=>1, clearTimeout(){},
  };
  vm.runInNewContext(script, context, {filename:'app.js'});
  return {element, storage, downloads, detail:()=>element('job-detail').innerHTML};
}

test('separate offer and application links; full body is escaped', () => {
  const app = dashboard();
  assert.match(app.detail(), /href="https:\/\/x.test\/job\?x=1&amp;y=2"[^>]*>Voir l'offre/);
  assert.match(app.detail(), /href="https:\/\/x.test\/job\/apply"[^>]*>Postuler/);
  assert.match(app.detail(), /TAIL &lt;script&gt;bad\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(app.detail(), /<script>/);
});

test('application-only and legacy records do not invent offer links', () => {
  const application = dashboard({description_url:''});
  assert.match(application.detail(), /disabled>Voir l'offre<\/button>/);
  assert.match(application.detail(), /href="https:\/\/x.test\/job\/apply"[^>]*>Postuler/);
  const legacy = dashboard({description:'',description_url:'',apply_url:''});
  assert.match(legacy.detail(), /Short summary/);
  assert.match(legacy.detail(), /href="https:\/\/x.test\/job"[^>]*>Lien historique/);
  assert.match(legacy.detail(), /disabled>Postuler<\/button>/);
});

test('saved favorite, status and note survive rendering and updates', () => {
  const app = dashboard({}, {'stable-id':{favorite:true,status:'applied',note:'Call <Alice>'}});
  assert.match(app.detail(), /★ Favori/);
  assert.match(app.detail(), /value="applied" selected/);
  assert.match(app.detail(), /Call &lt;Alice&gt;/);
  app.element('detail-fav').click();
  const saved = JSON.parse(app.storage.get('stage-scout-review-v4'))['stable-id'];
  assert.equal(saved.favorite, false);
  assert.equal(saved.status, 'applied');
  assert.equal(saved.note, 'Call <Alice>');
  app.element('detail-status').listeners.change({target:{value:'interview'}});
  assert.equal(JSON.parse(app.storage.get('stage-scout-review-v4'))['stable-id'].status, 'interview');
});

test('search can find terms beyond the old excerpt', () => {
  const app = dashboard();
  app.element('search').value = 'TAIL';
  app.element('search').listeners.input({});
  assert.match(app.element('results-title').textContent, /^1 annonce/);
});

test('CSV export retains tracking and both link roles', async () => {
  const app = dashboard({}, {'stable-id':{favorite:true,status:'applied',note:'Call Alice'}});
  app.element('export-csv').click();
  const csv = await app.downloads[0].text();
  assert.match(csv, /url,description_url,apply_url/);
  assert.match(csv, /https:\/\/x.test\/job\?x=1&y=2/);
  assert.match(csv, /https:\/\/x.test\/job\/apply/);
  assert.match(csv, /Postulé/);
  assert.match(csv, /Call Alice/);
});
