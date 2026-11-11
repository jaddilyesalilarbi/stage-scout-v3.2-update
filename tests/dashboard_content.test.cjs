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
      appendChild(){}, replaceChildren(){}, setAttribute(){}, remove(){}, click(){this.listeners.click?.({});} });
    return nodes.get(id);
  }
  element('job-data').textContent = JSON.stringify({jobs:[job], meta:{}, coverage:[]});
  const context = {
    document:{getElementById:element, createElement:()=>element(Symbol()),
      querySelector:()=>element(Symbol()), addEventListener(){}, body:{appendChild(){}}},
    localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
    window:{matchMedia:()=>({matches:false})}, console, Blob,
    URL:{createObjectURL:blob=>{downloads.push(blob);return 'blob:test';}, revokeObjectURL(){}},
    FileReader:class {readAsText(file){this.result = file.text; this.onload();}},
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

test('expired verification is dated and keeps historical text without application action', () => {
  const app = dashboard({enrichment_outcome:'expired', availability:'expired',
    enrichment_checked_at:'2026-10-20T12:30:00+00:00', enrichment_confidence:'high'});
  assert.match(app.detail(), /Offre expirée/);
  assert.match(app.element('job-list').innerHTML, /Offre expirée/);
  assert.match(app.detail(), /Texte conservé d.historique/);
  assert.match(app.detail(), /2026-10-20T12:30:00\+00:00/);
  assert.match(app.detail(), /disabled>Postuler<\/button>/);
  assert.match(app.detail(), /TAIL &lt;script&gt;/);
});

test('uncertain verification labels historical links and preserves saved tracking', () => {
  const app = dashboard({enrichment_outcome:'inaccessible', availability:'unknown',
    enrichment_checked_at:'2026-10-20T12:30:00Z', enrichment_confidence:'none',
    enrichment_error:'Access <denied>'},
    {'stable-id':{favorite:true,status:'applied',note:'Call Alice'}});
  assert.match(app.detail(), /Vérification incertaine/);
  assert.match(app.element('job-list').innerHTML, /Vérification incertaine/);
  assert.match(app.detail(), /Lien non vérifié/);
  assert.match(app.detail(), /Lien historique/);
  assert.doesNotMatch(app.detail(), />Voir l'offre/);
  assert.match(app.detail(), /Access &lt;denied&gt;/);
  assert.match(app.detail(), /value="applied" selected/);
  assert.match(app.detail(), /Call Alice/);
  app.element('detail-fav').click();
  assert.equal(JSON.parse(app.storage.get('stage-scout-review-v4'))['stable-id'].note, 'Call Alice');
});

test('mismatching or missing offers cannot activate historical or application links', () => {
  for (const enrichment_outcome of ['mismatch', 'not_found']) {
    const app = dashboard({enrichment_outcome, availability:'unknown'});
    assert.doesNotMatch(app.detail(), /href="https:\/\/x.test/);
    assert.match(app.detail(), /disabled>Lien historique<\/button>/);
    assert.match(app.detail(), /disabled>Postuler<\/button>/);
  }
});

test('confirmed enrichment uses the detail URL alias and keeps tracking export', async () => {
  const app = dashboard({enrichment_outcome:'enriched', availability:'open',
    enrichment_confidence:'high', detail_url:'https://official.test/confirmed',
    enrichment_checked_at:'2026-10-20T12:30:00Z'},
    {'stable-id':{favorite:true,status:'applied',note:'Call Alice'}});
  assert.match(app.detail(), /href="https:\/\/official.test\/confirmed"[^>]*>Voir l'offre/);
  assert.match(app.detail(), /Disponibilité constatée lors de la vérification/);
  app.element('export-track').click();
  const exported = JSON.parse(await app.downloads[0].text());
  assert.equal(exported.records['stable-id'].favorite, true);
  assert.equal(exported.records['stable-id'].note, 'Call Alice');
});

test('tracking import remains compatible for enriched records', () => {
  const app = dashboard({enrichment_outcome:'inaccessible', availability:'unknown'});
  const text = JSON.stringify({format:'stage-scout-tracking-v1', records:{
    'stable-id':{favorite:true,status:'interview',note:'Imported <note>'}}});
  app.element('import-file').listeners.change({target:{files:[{text}]}});
  assert.match(app.detail(), /value="interview" selected/);
  assert.match(app.detail(), /Imported &lt;note&gt;/);
  const saved = JSON.parse(app.storage.get('stage-scout-review-v4'))['stable-id'];
  assert.equal(saved.favorite, true);
  assert.equal(saved.note, 'Imported <note>');
});

test('medium confidence cannot present a match as a confirmed official offer', () => {
  const app = dashboard({enrichment_outcome:'enriched', availability:'open',
    enrichment_confidence:'medium', detail_url:'https://official.test/unconfirmed'});
  assert.match(app.detail(), /Vérification incertaine/);
  assert.doesNotMatch(app.detail(), />Voir l'offre/);
  assert.match(app.detail(), /disabled>Postuler<\/button>/);
});

test('verified identity keeps official offer link when availability is unknown', () => {
  const app = dashboard({enrichment_outcome:'enriched', availability:'unknown',
    enrichment_confidence:'high', detail_url:'https://official.test/verified',
    enrichment_checked_at:'2026-10-20T12:30:00Z'});
  assert.match(app.detail(), /href="https:\/\/official.test\/verified"[^>]*>Voir l'offre/);
  assert.match(app.detail(), /Disponibilité inconnue/);
  assert.match(app.element('job-list').innerHTML, /Disponibilité inconnue/);
  assert.match(app.detail(), /2026-10-20T12:30:00Z/);
  assert.match(app.detail(), /disabled>Postuler<\/button>/);
  assert.doesNotMatch(app.detail(), /Lien non vérifié|Lien historique|Texte conservé d.historique/);
});
