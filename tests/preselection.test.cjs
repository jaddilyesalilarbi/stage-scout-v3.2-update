const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '../dashboard-src/app.js'), 'utf8');

function dashboard(jobs, saved = {}) {
  const nodes = new Map(), downloads = [], storage = new Map([['stage-scout-review-v4', JSON.stringify(saved)]]);
  function element(id) {
    if (!nodes.has(id)) nodes.set(id, {value:'', checked:false, hidden:false, selectedOptions:[], options:[],
      innerHTML:'', textContent:'', listeners:{}, classList:{add(){},remove(){},toggle(){}},
      addEventListener(name, fn){this.listeners[name]=fn;}, appendChild(child){this.options.push(child);},
      replaceChildren(...children){this.options=children;this.selectedOptions=children.filter(child=>child.selected);},
      setAttribute(){}, remove(){}, click(){this.listeners.click?.({});}});
    return nodes.get(id);
  }
  element('hide-ignored').checked = true;
  element('sort').value = 'score';
  element('job-data').textContent = JSON.stringify({jobs, coverage:[]});
  vm.runInNewContext(script, {document:{getElementById:element, querySelector:s=>element(s),
    createElement:()=>element(Symbol()), addEventListener(){}, body:{appendChild(){}}},
    localStorage:{getItem:k=>storage.get(k), setItem:(k,v)=>storage.set(k,v)}, window:{matchMedia:()=>({matches:false})},
    Blob, URL:{createObjectURL:b=>{downloads.push(b);return 'blob:test';}, revokeObjectURL(){}},
    FileReader:class {readAsText(file){this.result=file.text;this.onload();}}, console, setTimeout:()=>1, clearTimeout(){} });
  const change = (id, value) => {element(id).value=value; element(id).listeners.change?.({target:element(id)});};
  return {element, downloads, change, detail:()=>element('job-detail').innerHTML,
    ids:()=>[...element('job-list').innerHTML.matchAll(/data-job-id="([^"]+)"/g)].map(m=>m[1]),
    saved:()=>JSON.parse(storage.get('stage-scout-review-v4')),
    import:records=>element('import-file').listeners.change({target:{files:[{text:JSON.stringify({format:'stage-scout-tracking-v1', records})}]}})};
}
const job = (id, pdm, technical_score, extra={}) => ({id, title:id, company:'ACME', country:'France', score:90,
  first_seen:'2026-10-20', assessment:{pdm_potential:pdm, technical_score, technical_categories:['Structural engineering'],
    input_hash:'current', pdm_reason:'Reason <script>bad()</script>', pdm_confidence:'medium', constraints:{}, ...extra}});

test('preselection hides low only in its view and uses combined ranking without conflating thesis and technical fit', () => {
  const app=dashboard([job('low','low',100),job('explicit','explicit',10),job('high','high',90)]);
  assert.deepEqual(app.ids(), ['low','explicit','high']);
  app.element('tab-preselection').click();
  assert.equal(app.element('sort').value,'combined');
  assert.deepEqual(app.ids(),['high','explicit']);
  app.element('show-low').checked=true; app.change('show-low','');
  assert.ok(app.ids().includes('low'));
  app.element('tab-jobs').click(); assert.equal(app.element('sort').value,'score');
  assert.equal(app.ids().length,3);
});

test('technical category selection matches ANY selected category, independently of PDM and score filters', () => {
  const app=dashboard([job('structure','high',80),job('thermal','medium',75,{technical_categories:['Thermal engineering']}),
    job('software','high',95,{technical_categories:['Software engineering']})]);
  app.element('tab-preselection').click();
  app.element('technical-categories').selectedOptions=[{value:'Structural engineering'},{value:'Thermal engineering'}];
  app.change('technical-categories',''); assert.deepEqual(app.ids(),['structure','thermal']);
  app.change('pdm-filter','medium'); assert.deepEqual(app.ids(),['thermal']);
  app.element('technical-min').value='80'; app.element('technical-min').listeners.input({target:{value:'80'}});
  assert.deepEqual(app.ids(),[]);
});

test('PDM, technical, newest and priority sorts retain distinct dimensions', () => {
  const a=job('explicit','explicit',10), b=job('technical','high',90), c=job('priority','medium',70);
  c.priority_company=true; c.first_seen='2026-10-21';
  const app=dashboard([a,b,c]); app.element('tab-preselection').click();
  for (const [sort, first] of [['pdm','explicit'],['technical','technical'],['newest','priority'],['priority','priority']]) {
    app.change('sort',sort); assert.equal(app.ids()[0],first);
  }
});

test('selection decisions stay separate from candidatures and survive JSON and CSV export', async () => {
  const app=dashboard([job('a','high',80)], {a:{status:'applied',favorite:true,note:'Contact'}});
  app.change('detail-decision','retained');
  assert.equal(app.saved().a.selection_decision,'retained'); assert.equal(app.saved().a.status,'applied');
  app.element('export-track').click(); const data=JSON.parse(await app.downloads[0].text());
  assert.equal(data.records.a.selection_decision,'retained');
  app.element('export-csv').click(); const csv=await app.downloads[1].text();
  assert.match(csv,/pdm_potential,technical_score,technical_categories,selection_decision/); assert.match(csv,/Retenue/);
  app.import({a:{status:'interview', note:'Legacy', favorite:false}});
  assert.equal(app.saved().a.selection_decision,'retained'); assert.equal(app.saved().a.status,'interview');
});

test('local manual correction survives recalculation, is escaped, and resets only the override', async () => {
  const override={pdm_potential:'medium',technical_score:92,technical_categories:['Composites <img>'],reason:'Manual <script>',input_hash:'old'};
  const app=dashboard([job('a','low',5)], {a:{status:'applied',selection_decision:'revisit',note:'Keep',assessment_override:override}});
  assert.match(app.detail(),/92\/100/); assert.match(app.detail(),/source a changé/);
  assert.match(app.detail(),/Composites &lt;img&gt;/); assert.doesNotMatch(app.detail(),/<script>|<img>/);
  app.element('tab-preselection').click(); assert.deepEqual(app.ids(),['a']);
  app.element('export-track').click(); assert.deepEqual(JSON.parse(await app.downloads[0].text()).records.a.assessment_override,override);
  app.import({a:{assessment_override:{...override, technical_score:88},selection_decision:'discarded'}});
  assert.equal(app.saved().a.assessment_override.technical_score,88);
  app.import({a:{assessment_override:{technical_score:'100',technical_categories:[{}]},selection_decision:'invalid'}});
  assert.equal(app.saved().a.assessment_override.technical_score,88);
  app.element('override-reset').click(); assert.equal(app.saved().a.assessment_override,undefined);
  assert.equal(app.saved().a.status,'applied'); assert.equal(app.saved().a.selection_decision,'discarded');
});

test('editing analysis persists a typed override while preserving all tracking', () => {
  const app=dashboard([job('a','high',80)],{a:{status:'interview',note:'Keep'}});
  app.element('override-pdm').value='medium'; app.element('override-score').value='65';
  app.element('override-categories').selectedOptions=[{value:'Composites'}];
  app.element('override-reason').value='Confirmed by recruiter'; app.element('override-save').click();
  assert.equal(app.saved().a.assessment_override.technical_score,65);
  assert.deepEqual(app.saved().a.assessment_override.technical_categories,['Composites']);
  assert.equal(app.saved().a.assessment_override.input_hash,'current'); assert.equal(app.saved().a.note,'Keep');
});

test('partial server and imported overrides merge valid fields over automatic assessment', () => {
  const app=dashboard([job('a','low',80,{manual_override:{pdm_potential:'medium',reason:'Autonomy'}})]);
  app.element('tab-preselection').click(); assert.deepEqual(app.ids(),['a']);
  assert.match(app.detail(),/Technique 80\/100/); assert.match(app.detail(),/Autonomy/);
  app.import({a:{assessment_override:{technical_score:91},selection_decision:'retained'}});
  assert.equal(app.saved().a.assessment_override.technical_score,91);
  assert.match(app.detail(),/Technique 91\/100/); assert.match(app.detail(),/Potentiel PDM moyen/);
  app.import({a:{note:'Legacy only'}});
  assert.equal(app.saved().a.selection_decision,'retained'); assert.equal(app.saved().a.assessment_override.technical_score,91);
});

test('company, country, constraint, availability and decision filters compose', () => {
  const a=job('a','high',80,{constraint_status:'compatible'}), b=job('b','high',90,{constraint_status:'unknown'});
  a.availability='open'; b.availability='unknown'; b.company='Other'; b.country='Suisse';
  const app=dashboard([a,b],{a:{selection_decision:'retained'}}); app.element('tab-preselection').click();
  app.change('company-filter','ACME'); app.change('country','France'); app.change('constraint-filter','compatible');
  app.change('availability-filter','open'); app.change('selection-decision','retained'); assert.deepEqual(app.ids(),['a']);
  app.change('selection-decision','discarded'); assert.deepEqual(app.ids(),[]);
});

test('preselection cards show escaped mission evidence and constraints without changing full detail or all-offers cards', () => {
  const evidence='Design <img> structural test fixtures. ' + 'Measure results and validate the prototype. '.repeat(10);
  const app=dashboard([job('a','high',80,{mission_evidence:[evidence],constraint_status:'incompatible'})]);
  assert.doesNotMatch(app.element('job-list').innerHTML,/card-justification|Contraintes :/);
  app.element('tab-preselection').click();
  const cards=app.element('job-list').innerHTML;
  assert.match(cards,/Contraintes : Incompatible/);
  assert.match(cards,/Design &lt;img&gt; structural test fixtures/); assert.doesNotMatch(cards,/<img>/);
  const summary=cards.match(/class="card-justification">([^]*?)<\/p>/)[1];
  assert.match(summary,/…$/); assert.ok(summary.length<260);
  assert.ok(app.detail().includes(evidence.replace('<img>','&lt;img&gt;')));
  app.element('tab-jobs').click(); assert.doesNotMatch(app.element('job-list').innerHTML,/card-justification|Contraintes :/);
});

test('category options refresh after correction, reset and import while preserving selected filters', () => {
  const app=dashboard([job('a','high',80),job('b','high',70)]);
  const options=()=>app.element('technical-categories').options.map(option=>option.value);
  app.element('tab-preselection').click();
  app.element('technical-categories').selectedOptions=[{value:'Structural engineering'}];
  app.change('technical-categories','');
  app.element('override-pdm').value='high'; app.element('override-score').value='80';
  app.element('override-categories').selectedOptions=[{value:'Mechanical Design'}];
  app.element('override-save').click();
  assert.ok(options().includes('Mechanical Design'));
  assert.deepEqual(app.element('technical-categories').selectedOptions.map(option=>option.value),['Structural engineering']);
  app.import({a:{assessment_override:{technical_categories:['Custom <category>']}}});
  assert.ok(options().includes('Custom <category>'));
  assert.deepEqual(app.element('technical-categories').selectedOptions.map(option=>option.value),['Structural engineering']);
  app.element('tab-jobs').click();
  app.element('job-list').listeners.click({target:{closest:selector=>selector==='[data-job-id]' ? {dataset:{jobId:'a'}} : null}});
  app.element('override-reset').click();
  assert.ok(!options().includes('Custom <category>'));
  assert.ok(options().includes('Structural engineering'));
});

test('explicitly filtering low potential reveals low offers without another toggle', () => {
  const app=dashboard([job('a','low',80),job('b','high',70)]);
  app.element('tab-preselection').click(); assert.deepEqual(app.ids(),['b']);
  app.change('pdm-filter','low'); assert.deepEqual(app.ids(),['a']);
  assert.equal(app.element('show-low').checked,false);
  app.change('pdm-filter',''); assert.deepEqual(app.ids(),['b']);
});
