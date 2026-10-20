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
    return true;
  }
  function sortJobs(list) {
    const mode = $('sort').value;
    list.sort((a,b) => {
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
        return `<article class="job-card ${job.id === selectedId ? 'selected' : ''}" role="listitem" tabindex="0" data-job-id="${esc(job.id)}" aria-label="${esc(job.title)} chez ${esc(job.company)}">
          <div class="job-main"><div class="job-company"><span class="company-avatar">${esc(initial(job.company))}</span><span>${esc(job.company)}</span></div>
          <div class="job-title">${esc(job.title)}</div>
          <div class="job-meta"><span>⌁ ${esc(job.location || 'Lieu non précisé')}</span><span>· ${esc(job.source || 'Source non précisée')}</span></div>
          <div class="job-badges"><span class="pill score ${scoreClass}">${job.score}/100</span>${isPdm(job) ? '<span class="pill pdm">Master thesis</span>' : ''}${isNew(job) ? '<span class="pill new">Nouveau</span>' : ''}${s !== 'to_review' ? `<span class="pill status ${statusColors[s]}">${esc(statusLabels[s])}</span>` : ''}</div></div>
          <button class="favorite-btn ${isFavorite(job) ? 'active' : ''}" type="button" data-fav-id="${esc(job.id)}" aria-label="${isFavorite(job) ? 'Retirer des' : 'Ajouter aux'} favoris" title="Favori">${isFavorite(job) ? '★' : '☆'}</button>
        </article>`;
      }).join('');
    }
    $('show-more').hidden = visibleLimit >= filtered.length;
    if (!$('show-more').hidden) $('show-more').textContent = `Afficher 80 offres de plus (${(filtered.length-visibleLimit).toLocaleString('fr-FR')} restantes)`;
  }
  function fact(label, value) { return `<div class="fact"><dt>${esc(label)}</dt><dd>${esc(value || 'Non précisé')}</dd></div>`; }
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
    const link = actionLink(job.description_url, "Voir l'offre", 'button-dark')
      + actionLink(job.apply_url, 'Postuler', 'button-quiet')
      + (!job.description_url && !job.apply_url && job.url ? actionLink(job.url, 'Lien historique', 'button-light') : '');
    $('job-detail').innerHTML = `
      <div class="detail-company"><span class="company-avatar">${esc(initial(job.company))}</span>${esc(job.company)}</div>
      <h2 class="detail-title">${esc(job.title)}</h2>
      <div class="detail-location"><span>⌁ ${esc(job.location || 'Lieu non précisé')}</span><span class="big-score">${job.score}/100</span>${isNew(job) ? '<span class="pill new">Nouveau</span>' : ''}</div>
      <div class="detail-actions">${link}<button id="detail-fav" type="button" class="button button-light heart-btn">${isFavorite(job) ? '★ Favori' : '☆ Favori'}</button></div>
      <div class="detail-body">
        <h3>Pourquoi ce poste correspond</h3><p>${esc(job.why || 'Aucune justification fournie par le moteur de recherche.')}</p>
        <h3>Description de l'offre</h3><p>${esc(job.description || job.description_excerpt || 'Aucune description disponible : consulter directement le site de l’entreprise.')}</p>
        <p class="description-origin">${job.description ? (job.description_status === 'partial' ? 'Description partielle fournie par la source.' : 'Texte conservé tel que fourni par la source.') : 'Ancien extrait uniquement.'}${job.description_source ? ` Source : ${esc(job.description_source)}.` : ''}</p>
        ${job.warnings ? `<div class="warning-note">Attention : ${esc(job.warnings)}</div>` : ''}
        <dl class="facts">${fact('Pays', job.country)}${fact('Type', job.kind)}${fact('Durée', job.duration)}${fact('Source', job.source)}${fact('Première détection', prettifyDate(job.first_seen))}${fact('Date de publication', prettifyDate(job.posted_at))}${fact('Dernière détection', prettifyDate(job.last_seen))}</dl>
      </div>
      <div class="track-panel"><h3 class="detail-body" style="font-size:13px;margin:22px 0 8px">Mon suivi</h3>
        <label for="detail-status">Statut de candidature</label><select id="detail-status">${options}</select>
        <label for="detail-notes">Notes personnelles</label><textarea id="detail-notes" placeholder="Contact, date de candidature, questions, prochaine action…">${esc(getNote(job))}</textarea>
        <p class="track-help">Sauvegardé sur cet appareil. Pense à exporter ton suivi régulièrement.</p>
      </div>`;
    $('detail-fav').addEventListener('click', () => { patchJob(job.id, { favorite: !isFavorite(job) }); renderList(); renderDetail(); });
    $('detail-status').addEventListener('change', e => { patchJob(job.id, {status: e.target.value}); refresh(); });
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
    $('hide-ignored').checked = true; $('sort').value = 'score';
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
          tracking[id] = {...(tracking[id] || {}), ...(statusLabels[record.status] ? {status:record.status} : {}), favorite:!!record.favorite, note:String(record.note || '').slice(0,10000)};
          count++;
        }
        saveTracking(); refresh(true); toast(`${count} fiches de suivi restaurées.`);
      } catch (error) { toast(`Impossible de restaurer : ${error.message}`); }
    };
    reader.readAsText(file, 'utf-8');
  }
  function exportCSV() {
    const keys = ['score','company','title','location','country','kind','duration','status','favorite','note','source','url','description_url','apply_url','first_seen','posted_at'];
    const escapeCSV = s => `"${String(s ?? '').replaceAll('"','""')}"`;
    const rows = [keys.join(','), ...filtered.map(job => keys.map(key => escapeCSV(key === 'status' ? statusLabels[getStatus(job)] : key === 'favorite' ? (isFavorite(job) ? 'oui' : 'non') : key === 'note' ? getNote(job) : job[key])).join(','))];
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
    const jobsView = view === 'jobs';
    $('coverage-page').hidden = jobsView;
    document.querySelector('.workspace').hidden = !jobsView;
    document.querySelector('.summary').hidden = !jobsView;
    $('tab-jobs').classList.toggle('active', jobsView);
    $('tab-coverage').classList.toggle('active', !jobsView);
    $('tab-jobs').setAttribute('aria-pressed', String(jobsView));
    $('tab-coverage').setAttribute('aria-pressed', String(!jobsView));
    closePanels();
    if (!jobsView) renderCoverage();
  }
  function initCoverage() {
    $('tab-jobs').addEventListener('click', () => showView('jobs'));
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
