'use strict';
(() => {
  const payloadNode = document.getElementById('job-data');
  let payload;
  try { payload = JSON.parse(payloadNode.textContent); }
  catch (error) { document.getElementById('job-list').textContent = 'Impossible de charger les annonces.'; console.error(error); return; }
  const jobs = payload.jobs || [];
  const jobsById = new Map(jobs.map(job => [job.id, job]));
  const storageKey = 'stage-scout-review-v4';
  const statusLabels = {
    to_review: 'À examiner', shortlisted: 'Intéressant', to_apply: 'À postuler',
    applied: 'Postulé', interview: 'Entretien', rejected: 'Refusé', ignored: 'Ignoré'
  };
  const statusColors = { to_review: '', shortlisted: '', to_apply: '', applied: '', interview: '', rejected: '', ignored: 'ignored' };
  const decisionLabels = {to_review:'À examiner', retained:'Retenue', revisit:'À revoir', discarded:'Écartée'};
  const pdmLabels = {explicit:'PDM explicite', high:'Potentiel PDM élevé', medium:'Potentiel PDM moyen', low:'Potentiel PDM faible', uncertain:'Potentiel PDM incertain'};
  const pdmRank = {explicit:4, high:3, medium:2, uncertain:1, low:0};
  const constraintLabels = {compatible:'Compatible', incompatible:'Incompatible', unknown:'À vérifier'};
  const constraintNames = {duration:'Durée', start_date:'Date de début', languages:'Langues', location:'Lieu', education:'Formation', eligibility:'Éligibilité'};
  const technicalCategories = ['Mechanical Design','R&D / Product Development','Simulation / CAE','Testing / Validation','Manufacturing / Production','Systems Integration','Robotics / Mechatronics','Automation / Control','Materials / Processes','Energy / Thermal','Quality','Supply Chain / Logistics','Project Management','Other'];
  let currentView = 'jobs';
  const viewSort = {jobs:'score', preselection:'combined'};
  const today = new Date();
  let tracking = {};
  let selectedId = '';
  let visibleLimit = 80;
  let filtered = [];
  let toastTimer;
  const $ = id => document.getElementById(id);
  const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const esc = s => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  const initial = s => String(s || '?').trim().charAt(0).toUpperCase();
  const prettifyDate = s => {
    if (!/^\d{4}-\d{2}-\d{2}/.test(s || '')) return s || 'Non précisée';
    const parts = String(s).slice(0,10).split('-').map(Number);
    const d = new Date(parts[0], parts[1]-1, parts[2]);
    return d.toLocaleDateString('fr-FR', {day:'numeric', month:'short', year:'numeric'});
  };
  const fromDate = s => /^\d{4}-\d{2}-\d{2}/.test(s || '') ? new Date(`${s.slice(0,10)}T12:00:00`) : null;
  const daysAgo = s => {
    const d = fromDate(s);
    return d ? Math.round((today - d) / 86400000) : Infinity;
  };
  const isNew = job => daysAgo(job.first_seen) >= 0 && daysAgo(job.first_seen) <= 7;
  const isPdm = job => {
    const titleMatches = /master.{0,12}thesis|thesis|pdm|master.{0,12}project|diploma.{0,12}project|abschlussarbeit|mémoire/i.test(job.title || '');
    const kind = job.kind || '';
    if (/pdm not confirmed|thesis not confirmed|non confirm[eé]/i.test(kind)) return titleMatches;
    return titleMatches || /master.{0,12}thesis|thesis|pdm|master.{0,12}project/i.test(kind);
  };
  const isOfficial = job => /published_board|company|direct|official/i.test(`${job.verification} ${job.source}`) || /ats/i.test(job.source);
  const enrichmentStatus = job => {
    const identityConfirmed = job.enrichment_outcome === 'enriched' && job.enrichment_confidence === 'high';
    return {
      checked: !!job.enrichment_outcome,
      expired: job.availability === 'expired' || job.enrichment_outcome === 'expired',
      identityConfirmed,
      openConfirmed: identityConfirmed && job.availability === 'open',
      blocked: ['mismatch', 'not_found'].includes(job.enrichment_outcome)
    };
  };
  function baseStatus(job) {
    const value = norm(job.status).trim();
    if (['applied','postule','postulee'].includes(value)) return 'applied';
    if (['ignored','dismissed','ignore'].includes(value)) return 'ignored';
    if (['interview','entretien'].includes(value)) return 'interview';
    if (['to apply','a postuler'].includes(value)) return 'to_apply';
    if (['shortlisted','interesting','interessant'].includes(value)) return 'shortlisted';
    if (['rejected','refuse'].includes(value)) return 'rejected';
    return 'to_review';
  }
  const state = job => tracking[job.id] || {};
  const getStatus = job => state(job).status || baseStatus(job);
  const isFavorite = job => !!state(job).favorite;
  const getNote = job => state(job).note || '';
  const getDecision = job => Object.hasOwn(decisionLabels, state(job).selection_decision) ? state(job).selection_decision : 'to_review';
  const strings = value => Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
  const selectedValues = id => Array.from($(id).selectedOptions || []).map(option => option.value).filter(Boolean);
  function cleanOverride(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const result = {...(Object.hasOwn(pdmLabels,value.pdm_potential) ? {pdm_potential:value.pdm_potential} : {}),
      ...(typeof value.technical_score === 'number' && Number.isFinite(value.technical_score) && value.technical_score >= 0 && value.technical_score <= 100 ? {technical_score:value.technical_score} : {}),
      ...(Array.isArray(value.technical_categories) && value.technical_categories.every(item => typeof item === 'string') ? {technical_categories:value.technical_categories.slice(0,30).map(item => item.slice(0,200))} : {}),
      ...(typeof value.reason === 'string' ? {reason:value.reason.slice(0,2000)} : {}),
      ...(typeof value.input_hash === 'string' ? {input_hash:value.input_hash.slice(0,200)} : {})};
    return ['pdm_potential','technical_score','technical_categories','reason'].some(key => Object.hasOwn(result,key)) ? result : null;
  }
  function assessment(job) {
    const base = job.assessment || {};
    const server = cleanOverride(base.manual_override);
    const local = cleanOverride(state(job).assessment_override);
    const result = {...base, ...(server || {}), ...(local || {})};
    result.pdm_potential = Object.hasOwn(pdmLabels,result.pdm_potential) ? result.pdm_potential : 'uncertain';
    result.technical_score = typeof result.technical_score === 'number' && Number.isFinite(result.technical_score) ? Math.max(0,Math.min(100,result.technical_score)) : 0;
    result.technical_categories = strings(result.technical_categories);
    result.override = local || server ? {...(server || {}), ...(local || {})} : null;
    result.sourceChanged = !!result.override?.input_hash && result.override.input_hash !== base.input_hash;
    return result;
  }
  const combinedScore = job => { const a = assessment(job); return a.technical_score * ((pdmRank[a.pdm_potential] + 1) / 5); };
  function assessmentBadges(job) {
    const a = assessment(job);
    return `<span class="pill pdm">${esc(pdmLabels[a.pdm_potential])}</span><span class="pill technical">Technique ${a.technical_score}/100</span>${a.technical_categories.map(category => `<span class="pill category">${esc(category)}</span>`).join('')}${job.priority_company ? '<span class="pill priority">Entreprise prioritaire</span>' : ''}<span class="pill decision">${esc(decisionLabels[getDecision(job)])}</span>`;
  }
  function cardAssessment(job) {
    if (currentView !== 'preselection') return '';
    const a = assessment(job);
    const evidence = strings(a.mission_evidence).find(text => text.trim()) || strings(a.technical_reasons).find(text => text.trim()) || a.pdm_reason || 'Missions à préciser.';
    const text = String(evidence).replace(/\s+/g,' ').trim();
    const summary = text.length > 220 ? text.slice(0,217).replace(/\s+\S*$/,'').trimEnd() + '…' : text;
    const status = Object.hasOwn(constraintLabels,a.constraint_status) ? a.constraint_status : 'unknown';
    return `<p class="card-justification">${esc(summary)}</p><span class="pill constraints ${status}">Contraintes : ${esc(constraintLabels[status])}</span>`;
  }
  function updateCategoryOptions() {
    const selected = new Set(selectedValues('technical-categories'));
    const categories = [...new Set([...jobs.flatMap(job => assessment(job).technical_categories), ...selected])].filter(Boolean).sort((a,b)=>a.localeCompare(b,'fr'));
    const options = categories.map(value => { const option = document.createElement('option'); option.value = value; option.textContent = value; option.selected = selected.has(value); return option; });
    $('technical-categories').replaceChildren(...options);
  }
  function loadTracking() {
    try {
      const raw = JSON.parse(localStorage.getItem(storageKey) || '{}');
      tracking = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
    } catch (_) { tracking = {}; }
  }
  function saveTracking() { try { localStorage.setItem(storageKey, JSON.stringify(tracking)); } catch (_) { toast('Sauvegarde locale indisponible : exporte ton suivi.'); } }
  function patchJob(id, changes) {
    tracking[id] = {...(tracking[id] || {}), ...changes, updatedAt: new Date().toISOString()};
    saveTracking();
    renderCounters();
  }
  function toast(message) {
    const target = $('toast'); target.textContent = message; target.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => target.hidden = true, 3600);
  }
  function isVisible(job) {
    if ($('hide-ignored').checked && getStatus(job) === 'ignored') return false;
    const search = norm($('search').value).trim();
    if (search) {
      const corpus = norm(`${job.title} ${job.company} ${job.location} ${job.country} ${job.kind} ${job.description || job.description_excerpt} ${job.why}`);
      if (!search.split(/\s+/).every(word => corpus.includes(word))) return false;
    }
    if ($('country').value && job.country !== $('country').value) return false;
    if ($('role').value === 'pdm' && !isPdm(job)) return false;
    if ($('role').value === 'intern' && isPdm(job)) return false;
    if ($('review-status').value && getStatus(job) !== $('review-status').value) return false;
    if (job.score < Number($('min-score').value || 0)) return false;
    if ($('fave-only').checked && !isFavorite(job)) return false;
    if ($('new-only').checked && !isNew(job)) return false;
    if ($('official-only').checked && !isOfficial(job)) return false;
    if (currentView === 'preselection') {
      const a = assessment(job);
      if (!$('show-low').checked && $('pdm-filter').value !== 'low' && a.pdm_potential === 'low') return false;
      if ($('pdm-filter').value && a.pdm_potential !== $('pdm-filter').value) return false;
      const categories = selectedValues('technical-categories');
      if (categories.length && !categories.some(category => a.technical_categories.includes(category))) return false;
      if (a.technical_score < Number($('technical-min').value || 0)) return false;
      if ($('company-filter').value && job.company !== $('company-filter').value) return false;
      if ($('selection-decision').value && getDecision(job) !== $('selection-decision').value) return false;
      if ($('constraint-filter').value && (a.constraint_status || 'unknown') !== $('constraint-filter').value) return false;
      if ($('availability-filter').value && (job.availability || 'unknown') !== $('availability-filter').value) return false;
    }
    return true;
  }
  function sortJobs(list) {
    const mode = $('sort').value;
    list.sort((a,b) => {
      const aa = assessment(a), ab = assessment(b);
      const tie = () => ab.technical_score - aa.technical_score || pdmRank[ab.pdm_potential] - pdmRank[aa.pdm_potential] || (b.first_seen || '').localeCompare(a.first_seen || '') || a.id.localeCompare(b.id);
      if (mode === 'combined') return combinedScore(b) - combinedScore(a) || tie();
      if (mode === 'pdm') return pdmRank[ab.pdm_potential] - pdmRank[aa.pdm_potential] || tie();
      if (mode === 'technical') return ab.technical_score - aa.technical_score || tie();
      if (mode === 'priority') return Number(!!b.priority_company) - Number(!!a.priority_company) || combinedScore(b) - combinedScore(a) || tie();
      if (mode === 'newest') return (b.first_seen || '').localeCompare(a.first_seen || '') || b.score - a.score;
      if (mode === 'posted') return (b.posted_at || '').localeCompare(a.posted_at || '') || b.score - a.score;
      if (mode === 'company') return a.company.localeCompare(b.company, 'fr') || b.score - a.score;
      return b.score - a.score || (b.first_seen || '').localeCompare(a.first_seen || '');
    });
  }
  function renderCounters() {
    $('total-stat').textContent = jobs.length.toLocaleString('fr-FR');
    $('new-stat').textContent = jobs.filter(isNew).length.toLocaleString('fr-FR');
    $('favorite-stat').textContent = jobs.filter(isFavorite).length.toLocaleString('fr-FR');
    $('applied-stat').textContent = jobs.filter(j => ['applied', 'interview'].includes(getStatus(j))).length.toLocaleString('fr-FR');
  }
  function renderList() {
    $('results-title').textContent = `${filtered.length.toLocaleString('fr-FR')} annonce${filtered.length > 1 ? 's' : ''}`;
    $('results-subtitle').textContent = `${Math.min(filtered.length, visibleLimit).toLocaleString('fr-FR')} affichée${Math.min(filtered.length, visibleLimit) > 1 ? 's' : ''} · Sélectionnez une offre pour voir le détail`;
    if (!filtered.length) {
      $('job-list').innerHTML = '<div class="empty-list"><h3>Aucune offre trouvée</h3><p>Essaie de retirer un filtre ou d’élargir la recherche.</p><button type="button" class="button button-light" id="reset-empty">Réinitialiser les filtres</button></div>';
      $('reset-empty').addEventListener('click', resetFilters);
    } else {
      $('job-list').innerHTML = filtered.slice(0, visibleLimit).map(job => {
        const s = getStatus(job);
        const scoreClass = job.score >= 70 ? '' : job.score >= 45 ? 'mid' : 'low';
        const verification = enrichmentStatus(job);
        const verificationBadge = verification.checked && !verification.openConfirmed
          ? `<span class="pill status">${verification.expired ? 'Offre expirée' : verification.identityConfirmed ? 'Disponibilité inconnue' : 'Vérification incertaine'}</span>` : '';
        return `<article class="job-card ${job.id === selectedId ? 'selected' : ''}" role="listitem" tabindex="0" data-job-id="${esc(job.id)}" aria-label="${esc(job.title)} chez ${esc(job.company)}">
          <div class="job-main"><div class="job-company"><span class="company-avatar">${esc(initial(job.company))}</span><span>${esc(job.company)}</span></div>
          <div class="job-title">${esc(job.title)}</div>
          <div class="job-meta"><span>⌁ ${esc(job.location || 'Lieu non précisé')}</span><span>· ${esc(job.source || 'Source non précisée')}</span></div>
          <div class="job-badges"><span class="pill score ${scoreClass}">Recherche ${Number(job.score) || 0}/100</span>${assessmentBadges(job)}${isNew(job) ? '<span class="pill new">Nouveau</span>' : ''}${verificationBadge}${s !== 'to_review' ? `<span class="pill status ${statusColors[s]}">${esc(statusLabels[s])}</span>` : ''}</div>${cardAssessment(job)}</div>
          <button class="favorite-btn ${isFavorite(job) ? 'active' : ''}" type="button" data-fav-id="${esc(job.id)}" aria-label="${isFavorite(job) ? 'Retirer des' : 'Ajouter aux'} favoris" title="Favori">${isFavorite(job) ? '★' : '☆'}</button>
        </article>`;
      }).join('');
    }
    $('show-more').hidden = visibleLimit >= filtered.length;
    if (!$('show-more').hidden) $('show-more').textContent = `Afficher 80 offres de plus (${(filtered.length-visibleLimit).toLocaleString('fr-FR')} restantes)`;
  }
  function fact(label, value) { return `<div class="fact"><dt>${esc(label)}</dt><dd>${esc(value || 'Non précisé')}</dd></div>`; }
  function renderAssessment(job) {
    const a = assessment(job);
    const bullets = (title, values) => strings(values).length ? `<h4>${esc(title)}</h4><ul>${strings(values).map(value => `<li>${esc(value)}</li>`).join('')}</ul>` : '';
    const categories = [...new Set([...technicalCategories, ...jobs.flatMap(item => assessment(item).technical_categories), ...a.technical_categories])].sort();
    const options = Object.entries(pdmLabels).map(([value,label]) => `<option value="${value}" ${value === a.pdm_potential ? 'selected' : ''}>${esc(label)}</option>`).join('');
    return `<section class="assessment-panel" aria-label="Analyse de présélection"><h3>Analyse de présélection</h3><div class="job-badges">${assessmentBadges(job)}</div>
      <p>${esc(a.pdm_reason || 'Potentiel PDM non évalué.')}</p><p class="analysis-meta">Confiance PDM : ${esc(({high:'élevée',medium:'moyenne',low:'faible',none:'non évaluée'})[a.pdm_confidence] || a.pdm_confidence || 'non évaluée')}${a.rules_version ? ` · Règles ${esc(a.rules_version)}` : ''}</p>
      ${a.override ? `<p class="analysis-meta">Correction manuelle${a.override.reason ? ` : ${esc(a.override.reason)}` : ''}.</p>` : ''}
      ${a.sourceChanged ? '<div class="warning-note">La source a changé depuis la correction manuelle. Vérifiez votre analyse ; la correction est conservée.</div>' : ''}
      ${bullets('Correspondance technique',a.technical_reasons)}${bullets('Éléments de mission',a.mission_evidence)}${bullets('Informations manquantes',a.missing_information)}
      <h4>Contraintes pratiques</h4><p class="analysis-meta">État global : ${esc(constraintLabels[a.constraint_status] || 'À vérifier')}${a.needs_human_review ? ' · Vérification humaine nécessaire' : ''}</p>
      <dl class="constraint-facts">${Object.entries(constraintNames).map(([key,label]) => { const c = a.constraints?.[key] || {}; return `<div><dt>${esc(label)} <span class="pill">${esc(constraintLabels[c.status] || 'À vérifier')}</span></dt><dd>${esc(c.value || 'Non précisé')}${c.reason ? `<br>${esc(c.reason)}` : ''}${strings(c.evidence).map(text => `<blockquote>${esc(text)}</blockquote>`).join('')}</dd></div>`; }).join('')}</dl>
      <details class="override-editor"><summary>Corriger l’analyse</summary><label for="override-pdm">Potentiel PDM</label><select id="override-pdm">${options}</select>
        <label for="override-score">Score technique (0–100)</label><input id="override-score" type="number" min="0" max="100" value="${a.technical_score}">
        <label for="override-categories">Catégories techniques (plusieurs choix)</label><select id="override-categories" multiple size="5">${categories.map(value => `<option value="${esc(value)}" ${a.technical_categories.includes(value) ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select>
        <label for="override-reason">Motif (facultatif)</label><textarea id="override-reason">${esc(a.override?.reason || '')}</textarea><div class="override-actions"><button id="override-save" type="button" class="button button-quiet">Enregistrer la correction</button><button id="override-reset" type="button" class="text-link">Réinitialiser la correction locale</button></div><p class="track-help">La correction est conservée lors des prochains calculs.</p></details></section>`;
  }
  function renderDetail() {
    const job = jobsById.get(selectedId);
    if (!job) {
      $('job-detail').innerHTML = '<div class="empty-detail"><div class="empty-icon">↗</div><h3>Aucune offre sélectionnée</h3><p>Choisissez une annonce dans la liste.</p></div>';
      return;
    }
    const status = getStatus(job);
    const options = Object.entries(statusLabels).map(([key, label]) => `<option value="${key}" ${status === key ? 'selected' : ''}>${esc(label)}</option>`).join('');
    const actionLink = (url, label, style) => /^https?:\/\//i.test(url || '')
      ? `<a class="button ${style}" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`
      : `<button class="button ${style}" disabled>${label}</button>`;
    const {checked, expired, identityConfirmed, openConfirmed, blocked} = enrichmentStatus(job);
    const detailUrl = job.detail_url || job.description_url;
    const link = checked
      ? actionLink(blocked ? '' : (identityConfirmed ? detailUrl : job.url || detailUrl), identityConfirmed ? "Voir l'offre" : 'Lien historique', 'button-dark')
        + actionLink(openConfirmed ? job.apply_url : '', 'Postuler', 'button-quiet')
      : actionLink(detailUrl, "Voir l'offre", 'button-dark')
        + actionLink(job.apply_url, 'Postuler', 'button-quiet')
        + (!detailUrl && !job.apply_url && job.url ? actionLink(job.url, 'Lien historique', 'button-light') : '');
    const verificationLabel = expired ? 'Offre expirée' : openConfirmed
      ? 'Disponibilité constatée lors de la vérification' : identityConfirmed
        ? 'Disponibilité inconnue' : 'Vérification incertaine — disponibilité inconnue';
    const verification = checked ? `<div class="warning-note">${esc(verificationLabel)}.
      ${!identityConfirmed && !blocked ? 'Lien non vérifié.' : ''}${blocked ? 'Aucun lien confirmé pour cette offre.' : ''}
      Vérification : ${esc(job.enrichment_checked_at || 'date non renseignée')}.
      ${job.enrichment_error ? esc(job.enrichment_error) : ''}</div>` : '';
    const historicalText = checked && (!identityConfirmed || expired);
    $('job-detail').innerHTML = `
      <div class="detail-company"><span class="company-avatar">${esc(initial(job.company))}</span>${esc(job.company)}</div>
      <h2 class="detail-title">${esc(job.title)}</h2>
      <div class="detail-location"><span>⌁ ${esc(job.location || 'Lieu non précisé')}</span><span class="big-score">Recherche ${Number(job.score) || 0}/100</span>${isNew(job) ? '<span class="pill new">Nouveau</span>' : ''}</div>
      <div class="detail-actions">${link}<button id="detail-fav" type="button" class="button button-light heart-btn">${isFavorite(job) ? '★ Favori' : '☆ Favori'}</button></div>
      <div class="detail-body">
        ${verification}
        ${renderAssessment(job)}
        <h3>Pourquoi ce poste correspond</h3><p>${esc(job.why || 'Aucune justification fournie par le moteur de recherche.')}</p>
        <h3>Description de l'offre</h3><p>${esc(job.description || job.description_excerpt || 'Aucune description disponible : consulter directement le site de l’entreprise.')}</p>
        <p class="description-origin">${historicalText ? 'Texte conservé d’historique ; disponibilité actuelle non confirmée.' : job.description ? (job.description_status === 'partial' ? 'Description partielle fournie par la source.' : 'Texte conservé tel que fourni par la source.') : 'Ancien extrait uniquement.'}${job.description_source ? ` Source : ${esc(job.description_source)}.` : ''}</p>
        ${job.warnings ? `<div class="warning-note">Attention : ${esc(job.warnings)}</div>` : ''}
        <dl class="facts">${fact('Pays', job.country)}${fact('Type', job.kind)}${fact('Durée', job.duration)}${fact('Source', job.source)}${fact('Première détection', prettifyDate(job.first_seen))}${fact('Date de publication', prettifyDate(job.posted_at))}${fact('Dernière détection', prettifyDate(job.last_seen))}</dl>
      </div>
      <div class="track-panel"><h3 class="detail-body" style="font-size:13px;margin:22px 0 8px">Mon suivi</h3>
        <label for="detail-decision">Décision de présélection</label><select id="detail-decision">${Object.entries(decisionLabels).map(([value,label]) => `<option value="${value}" ${getDecision(job) === value ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select>
        <label for="detail-status">Statut de candidature</label><select id="detail-status">${options}</select>
        <label for="detail-notes">Notes personnelles</label><textarea id="detail-notes" placeholder="Contact, date de candidature, questions, prochaine action…">${esc(getNote(job))}</textarea>
        <p class="track-help">Sauvegardé sur cet appareil. Pense à exporter ton suivi régulièrement.</p>
      </div>`;
    $('detail-fav').addEventListener('click', () => { patchJob(job.id, { favorite: !isFavorite(job) }); renderList(); renderDetail(); });
    $('detail-status').addEventListener('change', e => { patchJob(job.id, {status: e.target.value}); refresh(); });
    $('detail-decision').addEventListener('change', e => { if (Object.hasOwn(decisionLabels,e.target.value)) { patchJob(job.id,{selection_decision:e.target.value}); refresh(); } });
    $('override-save').addEventListener('click', () => {
      const score = $('override-score').value;
      const override = cleanOverride({pdm_potential:$('override-pdm').value, technical_score:score.trim() ? Number(score) : NaN, technical_categories:selectedValues('override-categories'), reason:$('override-reason').value, input_hash:job.assessment?.input_hash || ''});
      if (!override || !Object.hasOwn(override,'pdm_potential') || !Object.hasOwn(override,'technical_score')) { toast('Choisissez un potentiel PDM et un score technique entre 0 et 100.'); return; }
      patchJob(job.id,{assessment_override:override}); updateCategoryOptions(); refresh(); toast('Correction enregistrée.');
    });
    $('override-reset').addEventListener('click', () => { patchJob(job.id,{assessment_override:undefined}); updateCategoryOptions(); refresh(); toast('Correction locale réinitialisée.'); });
    $('detail-notes').addEventListener('input', e => { patchJob(job.id, {note: e.target.value}); });
  }
  function refresh(resetLimit = false) {
    if (resetLimit) visibleLimit = 80;
    filtered = jobs.filter(isVisible);
    sortJobs(filtered);
    if (!filtered.some(j => j.id === selectedId)) selectedId = filtered[0]?.id || '';
    renderCounters(); renderList(); renderDetail();
  }
  function resetFilters() {
    ['search','country','role','review-status'].forEach(id => $(id).value = '');
    $('min-score').value = 0; $('score-label').textContent = '0';
    ['fave-only','new-only','official-only'].forEach(id => $(id).checked = false);
    ['pdm-filter','company-filter','selection-decision','constraint-filter','availability-filter'].forEach(id => $(id).value = '');
    for (const option of Array.from($('technical-categories').options || [])) option.selected = false;
    $('technical-min').value = 0; $('technical-label').textContent = '0'; $('show-low').checked = false;
    $('hide-ignored').checked = true; $('sort').value = currentView === 'preselection' ? 'combined' : 'score';
    refresh(true);
  }
  function downloadFile(name, content, mime) {
    const blob = new Blob([content], {type: mime});
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = name;
    document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function exportTracking() {
    const used = Object.fromEntries(Object.entries(tracking).filter(([id]) => jobsById.has(id)));
    downloadFile(`stage-scout-suivi-${new Date().toISOString().slice(0,10)}.json`, JSON.stringify({format:'stage-scout-tracking-v1',exported_at:new Date().toISOString(),records:used},null,2), 'application/json;charset=utf-8');
    toast('Suivi exporté. Conserve ce fichier en lieu sûr.');
  }
  function importTracking(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const content = JSON.parse(String(reader.result || ''));
        if (content.format !== 'stage-scout-tracking-v1' || typeof content.records !== 'object' || !content.records || Array.isArray(content.records)) throw Error('Format non reconnu');
        let count = 0;
        for (const [id, record] of Object.entries(content.records)) {
          if (!jobsById.has(id) || !record || typeof record !== 'object' || Array.isArray(record)) continue;
          const override = cleanOverride(record.assessment_override);
          tracking[id] = {...(tracking[id] || {}), ...(Object.hasOwn(statusLabels,record.status) ? {status:record.status} : {}),
            ...(typeof record.favorite === 'boolean' ? {favorite:record.favorite} : {}),
            ...(typeof record.note === 'string' ? {note:record.note.slice(0,10000)} : {}),
            ...(Object.hasOwn(decisionLabels,record.selection_decision) ? {selection_decision:record.selection_decision} : {}),
            ...(override ? {assessment_override:{...(cleanOverride(tracking[id]?.assessment_override) || {}), ...override}} : {})};
          count++;
        }
        saveTracking(); updateCategoryOptions(); refresh(true); toast(`${count} fiches de suivi restaurées.`);
      } catch (error) { toast(`Impossible de restaurer : ${error.message}`); }
    };
    reader.readAsText(file, 'utf-8');
  }
  function exportCSV() {
    const keys = ['score','company','title','location','country','kind','duration','pdm_potential','technical_score','technical_categories','selection_decision','status','favorite','note','source','url','description_url','apply_url','first_seen','posted_at'];
    const escapeCSV = s => `"${String(s ?? '').replaceAll('"','""')}"`;
    const rows = [keys.join(','), ...filtered.map(job => { const a = assessment(job); return keys.map(key => escapeCSV(key === 'selection_decision' ? decisionLabels[getDecision(job)] : key === 'technical_categories' ? a.technical_categories.join(' | ') : ['pdm_potential','technical_score'].includes(key) ? a[key] : key === 'status' ? statusLabels[getStatus(job)] : key === 'favorite' ? (isFavorite(job) ? 'oui' : 'non') : key === 'note' ? getNote(job) : job[key])).join(','); })];
    downloadFile(`stage-scout-selection-${new Date().toISOString().slice(0,10)}.csv`, '\ufeff' + rows.join('\r\n'), 'text/csv;charset=utf-8');
    toast(`${filtered.length} offres exportées en CSV.`);
  }
  function closePanels() { $('detail-pane').classList.remove('open'); $('filter-pane').classList.remove('open'); $('mobile-scrim').hidden = true; }
  function showDetail(id) { selectedId = id; renderList(); renderDetail(); if (window.matchMedia('(max-width:1190px)').matches) { $('detail-pane').classList.add('open'); $('mobile-scrim').hidden = false; } }

  // -------- Verified employer coverage, independent from job aggregates --------
  const coverageCompanies = Array.isArray(payload.coverage) ? payload.coverage : [];
  function coverageState(row) {
    if (row.enabled === false) return 'pending';
    const status = row.last_outcome || '';
    if (['scanned', 'directory_result'].includes(status)) return 'scanned';
    if (['directory_result', 'lookup_only', 'not_found'].includes(status)) return 'lookup';
    if (['error', 'timeout', 'unsupported_url', 'invalid_url', 'failed'].includes(status)) return 'error';
    return 'pending';
  }
  function coverageLabel(row) {
    if (row.enabled === false) return 'Désactivée';
    const status = row.last_outcome || '';
    const labels = {
      scanned: 'Site scanné', directory_result: 'Scannée via annuaire', lookup_only: 'Annuaire seulement',
      not_found: 'Non trouvée', timeout: 'Délai dépassé', error: 'Erreur de scan',
      unsupported_url: 'URL non compatible', invalid_url: 'URL invalide'
    };
    return labels[status] || 'Pas encore scannée';
  }
  function countryLabel(code) {
    return ({FR:'France',CH:'Suisse',DE:'Allemagne',NL:'Pays-Bas',BE:'Belgique',UK:'Royaume-Uni',GB:'Royaume-Uni'})[code] || code || 'Non renseigné';
  }
  function isRecentSuccessfulScan(row) {
    const d = daysAgo(row.last_success);
    return d >= 0 && d <= 14;
  }
  function renderCoverage() {
    const all = coverageCompanies;
    const q = norm($('cov-search').value.trim());
    const country = $('cov-country').value;
    const state = $('cov-state').value;
    const rows = all.filter(row => {
      const matchesTerm = !q || norm([row.name, row.country, row.careers_url, row.notes, row.last_resolved_url].join(' ')).includes(q);
      const matchesCountry = !country || (country === 'other' ? !['FR','CH'].includes(row.country) : row.country === country);
      return matchesTerm && matchesCountry && (!state || coverageState(row) === state);
    });
    $('cov-all').textContent = all.filter(r => r.enabled !== false).length.toLocaleString('fr-FR');
    $('cov-scanned').textContent = all.filter(r => r.enabled !== false && isRecentSuccessfulScan(r)).length.toLocaleString('fr-FR');
    $('cov-urls').textContent = all.filter(r => r.enabled !== false && /^https?:\/\//i.test(r.careers_url || '')).length.toLocaleString('fr-FR');
    $('cov-missing').textContent = all.filter(r => r.enabled !== false && !r.careers_url).length.toLocaleString('fr-FR');
    $('cov-count').textContent = `${rows.length.toLocaleString('fr-FR')} entreprises affichées · Un « scan » = le connecteur a effectivement consulté la page ATS`;
    $('coverage-rows').innerHTML = rows.length ? rows.map(row => {
      const state = coverageState(row);
      const url = /^https?:\/\//i.test(row.careers_url || '') ? row.careers_url : '';
      const resolved = /^https?:\/\//i.test(row.last_resolved_url || '') ? row.last_resolved_url : '';
      const urlText = url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" class="cov-url" title="${esc(url)}">${esc(url)}</a>` : '<span class="cov-blank">URL à compléter</span>';
      const resolvedText = resolved && resolved !== url ? `<a class="cov-url cov-small" href="${esc(resolved)}" target="_blank" rel="noopener noreferrer">ATS découvert ↗</a>` : '';
      const originLabel = row.origin === 'csv_watchlist' ? 'Liste CSV' : row.origin === 'config_direct' ? 'Configuration directe' : 'Recherche annuaire (config)';
      return `<tr>
        <td><div class="cov-name">${esc(row.name)}</div><div class="cov-origin">${esc(originLabel)}${row.notes ? ' · ' + esc(row.notes) : ''}</div></td>
        <td>${esc(countryLabel(row.country))}</td>
        <td>${urlText}${resolvedText}</td>
        <td><span class="cov-tag ${state}">${esc(coverageLabel(row))}</span>${row.last_message ? `<div class="cov-small">${esc(row.last_message)}</div>` : ''}</td>
        <td>${esc(prettifyDate(row.last_attempt || ''))}${row.last_success && row.last_success !== row.last_attempt ? `<div class="cov-small">Dernier succès : ${esc(prettifyDate(row.last_success))}</div>` : ''}</td>
        <td>${row.last_jobs === undefined ? '—' : Number(row.last_jobs).toLocaleString('fr-FR')}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="6" style="padding:28px;text-align:center;color:#8a97a5">Aucune entreprise pour ces filtres.</td></tr>';
  }
  function exportCoverageCSV() {
    const watched = coverageCompanies;
    const header = ['name','country','careers_url','enabled','notes'];
    const quote = s => `"${String(s ?? '').replaceAll('"','""')}"`;
    const rows = [header.join(','), ...watched.map(r => [r.name,r.country,r.careers_url,r.enabled===false?'no':'yes',r.notes].map(quote).join(','))];
    downloadFile('companies.csv', '\ufeff' + rows.join('\r\n'), 'text/csv;charset=utf-8');
    toast(`${watched.length} entreprises exportées. Remplace companies.csv dans GitHub pour modifier la surveillance.`);
  }
  function showView(view) {
    if (currentView !== 'coverage') viewSort[currentView] = $('sort').value;
    currentView = view;
    const jobsView = view !== 'coverage';
    $('coverage-page').hidden = jobsView;
    document.querySelector('.workspace').hidden = !jobsView;
    document.querySelector('.summary').hidden = !jobsView;
    for (const name of ['jobs','preselection','coverage']) {
      $(`tab-${name}`).classList.toggle('active',view === name);
      $(`tab-${name}`).setAttribute('aria-pressed',String(view === name));
    }
    $('preselection-filters').hidden = view !== 'preselection';
    $('preselection-caption').hidden = view !== 'preselection';
    $('summary-title').textContent = view === 'preselection' ? 'Votre présélection' : 'Vos opportunités';
    if (jobsView) { $('sort').value = viewSort[view]; refresh(true); }
    closePanels();
    if (!jobsView) renderCoverage();
  }
  function initCoverage() {
    $('tab-jobs').addEventListener('click', () => showView('jobs'));
    $('tab-preselection').addEventListener('click', () => showView('preselection'));
    $('tab-coverage').addEventListener('click', () => showView('coverage'));
    for (const id of ['cov-search','cov-country','cov-state']) {
      $(id).addEventListener(id === 'cov-search' ? 'input' : 'change', renderCoverage);
    }
    $('coverage-export').addEventListener('click', exportCoverageCSV);
    renderCoverage();
  }

  function init() {
    loadTracking();
    const countries = [...new Set(jobs.map(j => j.country))].sort((a,b)=>a.localeCompare(b,'fr'));
    for (const name of countries) { const option = document.createElement('option'); option.value = name; option.textContent = name; $('country').appendChild(option); }
    for (const [id, values] of [['company-filter',[...new Set(jobs.map(job => job.company))]]]) {
      for (const value of values.filter(Boolean).sort((a,b)=>a.localeCompare(b,'fr'))) { const option = document.createElement('option'); option.value = value; option.textContent = value; $(id).appendChild(option); }
    }
    updateCategoryOptions();
    for (const id of ['pdm-filter','technical-categories','company-filter','selection-decision','constraint-filter','availability-filter','show-low']) $(id).addEventListener('change',() => refresh(true));
    $('technical-min').addEventListener('input',e => { $('technical-label').textContent = e.target.value; refresh(true); });
    const date = payload.meta?.scan_date || payload.meta?.generated_at?.slice(0,10);
    $('update-date').textContent = date ? `Données du ${prettifyDate(date)}` : 'Données archivées';
    for (const id of ['search','country','role','review-status','fave-only','new-only','official-only','hide-ignored']) {
      $(id).addEventListener(id === 'search' ? 'input' : 'change', () => refresh(true));
    }
    $('min-score').addEventListener('input', e => { $('score-label').textContent = e.target.value; refresh(true); });
    $('sort').addEventListener('change', () => refresh(true));
    $('clear-filters').addEventListener('click', resetFilters);
    $('show-more').addEventListener('click', () => { visibleLimit += 80; renderList(); });
    $('job-list').addEventListener('click', e => {
      const favButton = e.target.closest('[data-fav-id]');
      if (favButton) { const job = jobsById.get(favButton.dataset.favId); if (job) { patchJob(job.id,{favorite:!isFavorite(job)}); renderList(); renderDetail(); } return; }
      const card = e.target.closest('[data-job-id]');
      if (card) showDetail(card.dataset.jobId);
    });
    $('job-list').addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { const card=e.target.closest('[data-job-id]'); if(card && e.target.tagName !== 'BUTTON') { e.preventDefault(); showDetail(card.dataset.jobId); } } });
    $('export-track').addEventListener('click', exportTracking);
    $('import-track').addEventListener('click', () => $('import-file').click());
    $('import-file').addEventListener('change', e => { if(e.target.files?.[0]) importTracking(e.target.files[0]); e.target.value=''; });
    $('export-csv').addEventListener('click', exportCSV);
    $('mobile-filters').addEventListener('click', () => { $('filter-pane').classList.add('open'); $('mobile-scrim').hidden = false; });
    $('close-detail').addEventListener('click', closePanels);
    $('mobile-scrim').addEventListener('click', closePanels);
    document.addEventListener('keydown', e => { if(e.key === 'Escape') closePanels(); if (e.key === '/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)) { e.preventDefault(); $('search').focus(); } });
    refresh(true);
    initCoverage();
  }
  init();
})();
