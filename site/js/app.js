/* UI wiring: load the snapshot, hold preferences, render ranked results. */
(() => {
  const $ = sel => document.querySelector(sel);
  const STORE = 'gradradar.v1';

  const TYPES = [
    ['graduate-scheme', 'Graduate scheme'],
    ['graduate', 'Graduate role'],
    ['internship', 'Internship'],
    ['placement', 'Placement / year in industry'],
    ['entry-level', 'Entry level'],
  ];
  const CATS = [
    ['finance', 'Finance'], ['consulting', 'Consulting'], ['marketing', 'Marketing'],
    ['sales', 'Sales & BD'], ['operations', 'Operations'], ['people', 'HR & People'],
    ['data-tech', 'Data & Tech'],
  ];

  const state = {
    jobs: [], meta: {}, view: 'all', sort: 'match',
    cvText: '', cvName: '',
    boost: [], must: [], not: [],
    cvWeight: 0.6,
    types: new Set(), cats: new Set(),
    loc: '', remote: false, salaryOnly: false, maxAge: 30,
    saved: {}, applied: {}, hidden: {},
  };

  /* ------------------------------------------------------------- storage */
  function save() {
    const { jobs, meta, ...rest } = state;
    localStorage.setItem(STORE, JSON.stringify({
      ...rest, types: [...state.types], cats: [...state.cats],
    }));
  }
  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE) || '{}');
      Object.assign(state, raw, {
        types: new Set(raw.types || []), cats: new Set(raw.cats || []),
        saved: raw.saved || {}, applied: raw.applied || {}, hidden: raw.hidden || {},
      });
    } catch { /* corrupt or cleared storage: start fresh */ }
  }

  /* ----------------------------------------------------------- date bits */
  const DAY = 86400000;
  function daysBetween(iso, from = Date.now()) {
    if (!iso) return null;
    const t = Date.parse(iso + (iso.length === 10 ? 'T12:00:00Z' : ''));
    if (Number.isNaN(t)) return null;
    return Math.round((t - from) / DAY);
  }
  function openedLabel(iso) {
    const d = daysBetween(iso);
    if (d === null) return '';
    const ago = -d;
    if (ago <= 0) return 'Opened today';
    if (ago === 1) return 'Opened yesterday';
    if (ago < 7) return `Opened ${ago} days ago`;
    if (ago < 14) return 'Opened last week';
    if (ago < 60) return `Opened ${Math.round(ago / 7)} weeks ago`;
    return `Opened ${Math.round(ago / 30)} months ago`;
  }
  function closesInfo(job) {
    if (job.closes) {
      const d = daysBetween(job.closes);
      if (d === null) return null;
      if (d < 0) return { text: 'Closed', level: 'gone' };
      if (d === 0) return { text: 'Closes today', level: 'urgent' };
      if (d === 1) return { text: 'Closes tomorrow', level: 'urgent' };
      if (d <= 7) return { text: `Closes in ${d} days`, level: 'urgent' };
      if (d <= 21) return { text: `Closes in ${d} days`, level: 'soon' };
      return { text: `Closes ${fmtDate(job.closes)}`, level: 'ok' };
    }
    if (job.rolling) return { text: 'Rolling deadline', level: 'ok' };
    return null;
  }
  function fmtDate(iso) {
    const t = Date.parse(iso + 'T12:00:00Z');
    if (Number.isNaN(t)) return iso;
    return new Date(t).toLocaleDateString('en-GB',
      { day: 'numeric', month: 'short', year: 'numeric' });
  }

  /* ------------------------------------------------------------ filtering */
  function passesFilters(job) {
    if (state.types.size && !state.types.has(job.type)) return false;
    if (state.cats.size && !(job.cats || []).some(c => state.cats.has(c))) return false;
    if (state.loc) {
      const want = state.loc.toLowerCase().split(',').map(s => s.trim()).filter(Boolean);
      const where = (job.location || '').toLowerCase();
      if (want.length && !want.some(w => where.includes(w))) return false;
    }
    if (state.remote && !job.remote) return false;
    if (state.salaryOnly && !job.salary) return false;
    if (state.maxAge) {
      const d = daysBetween(job.posted);
      if (d !== null && -d > state.maxAge) return false;
    }
    const closed = closesInfo(job);
    if (closed && closed.level === 'gone') return false;
    return true;
  }

  /* -------------------------------------------------------------- render */
  function render() {
    const ranked = Match.rank(state.jobs, {
      cvText: state.cvText,
      boost: state.boost, must: state.must, exclude: state.not,
      cvWeight: state.cvWeight,
    });

    const buckets = { all: [], saved: [], applied: [], hidden: [] };
    for (const entry of ranked) {
      const id = entry.job.id;
      if (state.hidden[id]) { buckets.hidden.push(entry); continue; }
      if (state.applied[id]) buckets.applied.push(entry);
      if (state.saved[id]) buckets.saved.push(entry);
      if (passesFilters(entry.job)) buckets.all.push(entry);
    }

    $('#n-all').textContent = buckets.all.length;
    $('#n-saved').textContent = buckets.saved.length;
    $('#n-applied').textContent = buckets.applied.length;
    $('#n-hidden').textContent = buckets.hidden.length;

    let list = buckets[state.view].slice();
    if (state.sort === 'date') {
      list.sort((a, b) => (b.job.posted || '').localeCompare(a.job.posted || ''));
    } else if (state.sort === 'salary') {
      const amt = j => parseInt((j.salary || '').replace(/[^\d]/g, '') || '0', 10);
      list.sort((a, b) => amt(b.job) - amt(a.job));
    } else if (state.sort === 'closing') {
      const key = j => j.closes ? Date.parse(j.closes) : Infinity;
      list.sort((a, b) => key(a.job) - key(b.job));
    }

    const box = $('#list');
    box.innerHTML = '';
    const empty = $('#empty');
    if (!list.length) {
      empty.hidden = false;
      empty.innerHTML = emptyMessage();
      return;
    }
    empty.hidden = true;

    const frag = document.createDocumentFragment();
    for (const entry of list) frag.appendChild(card(entry));
    box.appendChild(frag);
  }

  function emptyMessage() {
    if (state.view === 'saved') return '<p>Nothing saved yet. Hit <strong>Save</strong> on a role to park it here.</p>';
    if (state.view === 'applied') return '<p>No applications logged. Mark roles as <strong>Applied</strong> to track them.</p>';
    if (state.view === 'hidden') return '<p>Nothing hidden.</p>';
    if (!state.jobs.length) return '<p>No job data loaded yet.</p>';
    return '<p>No roles match those filters. Try widening the date range or clearing a keyword.</p>';
  }

  function card({ job, score, reasons, scored }) {
    const el = document.createElement('article');
    el.className = 'card';

    const closes = closesInfo(job);
    const typeLabel = (TYPES.find(t => t[0] === job.type) || [, job.type])[1];

    const meta = [];
    if (job.location) meta.push(esc(job.location));
    if (job.salary) meta.push(`<span class="salary">${esc(job.salary)}</span>`);
    if (job.remote) meta.push('Remote');

    el.innerHTML = `
      <div class="card-score ${scored ? '' : 'is-quiet'}"
           title="${scored ? 'Match against your CV and keywords' : 'Add a CV or keywords to rank these'}">
        <span class="score-num">${scored ? score : '–'}</span>
        <span class="score-pc">${scored ? '% match' : 'no CV'}</span>
      </div>
      <div class="card-body">
        <h3><a href="${esc(job.url)}" target="_blank" rel="noopener noreferrer">${esc(job.title)}</a></h3>
        <p class="company">${esc(job.company)}</p>
        <p class="meta">${meta.join('<span class="dot">·</span>')}</p>
        <p class="dates">
          <span class="opened">${esc(openedLabel(job.posted))}</span>
          ${closes ? `<span class="closes lvl-${closes.level}">${esc(closes.text)}</span>` : ''}
        </p>
        ${reasons.length ? `<p class="why"><span class="why-lbl">matches</span>${
          reasons.map(r => `<span class="why-chip">${esc(r)}</span>`).join('')}</p>` : ''}
        <p class="summary">${esc(job.summary || '')}</p>
        <p class="tags">
          <span class="tag tag-type">${esc(typeLabel)}</span>
          ${(job.cats || []).map(c => `<span class="tag">${esc(
            (CATS.find(x => x[0] === c) || [, c])[1])}</span>`).join('')}
          <span class="tag tag-src">via ${esc(job.source)}</span>
        </p>
        <div class="actions">
          <a class="btn btn-primary btn-sm" href="${esc(job.url)}" target="_blank" rel="noopener noreferrer">Open role ↗</a>
          <button class="btn btn-sm ${state.saved[job.id] ? 'is-on' : ''}" data-act="save" data-id="${job.id}">${state.saved[job.id] ? '★ Saved' : '☆ Save'}</button>
          <button class="btn btn-sm ${state.applied[job.id] ? 'is-on' : ''}" data-act="applied" data-id="${job.id}">${state.applied[job.id] ? '✓ Applied' : 'Mark applied'}</button>
          <button class="btn btn-sm btn-quiet" data-act="hide" data-id="${job.id}">${state.hidden[job.id] ? 'Unhide' : 'Hide'}</button>
        </div>
      </div>`;
    return el;
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /* ------------------------------------------------------------- chips UI */
  function renderChips(key, host) {
    host.innerHTML = state[key].map((term, i) =>
      `<span class="chip">${esc(term)}<button aria-label="remove ${esc(term)}" data-chip="${key}" data-i="${i}">×</button></span>`
    ).join('');
  }
  function wireKeywordInput(inputSel, hostSel, key) {
    const input = $(inputSel), host = $(hostSel);
    renderChips(key, host);
    input.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ',') return;
      e.preventDefault();
      const value = input.value.trim().replace(/,$/, '');
      if (value && !state[key].includes(value)) {
        state[key].push(value);
        renderChips(key, host); save(); render();
      }
      input.value = '';
    });
    host.addEventListener('click', e => {
      const btn = e.target.closest('button[data-chip]');
      if (!btn) return;
      state[key].splice(Number(btn.dataset.i), 1);
      renderChips(key, host); save(); render();
    });
  }

  function renderChecks(hostSel, items, setKey) {
    const host = $(hostSel);
    host.innerHTML = items.map(([value, label]) =>
      `<label><input type="checkbox" value="${value}" ${state[setKey].has(value) ? 'checked' : ''}> ${esc(label)}</label>`
    ).join('');
    host.addEventListener('change', e => {
      const box = e.target;
      if (box.checked) state[setKey].add(box.value); else state[setKey].delete(box.value);
      save(); render();
    });
  }

  /* --------------------------------------------------------------- CV bits */
  function setCv(text, name) {
    state.cvText = text; state.cvName = name;
    $('#cv-status').hidden = !text;
    $('#cv-name').textContent = name ? `Using: ${name}` : '';
    $('#dropzone').classList.toggle('has-cv', !!text);
    save(); render();
  }

  async function handleFile(file) {
    const zone = $('#dropzone');
    zone.classList.add('is-busy');
    zone.querySelector('.dz-main').textContent = 'Reading…';
    try {
      const text = await CvReader.extract(file);
      setCv(text, file.name);
      zone.querySelector('.dz-main').textContent = 'CV loaded ✓';
      zone.querySelector('.dz-sub').textContent = 'Drop another to replace it';
    } catch (err) {
      zone.querySelector('.dz-main').textContent = 'Drop your CV here';
      zone.querySelector('.dz-sub').textContent = err.message;
      zone.classList.add('is-error');
      setTimeout(() => zone.classList.remove('is-error'), 2500);
    } finally {
      zone.classList.remove('is-busy');
    }
  }

  function weightHint(v) {
    if (v >= 0.85) return 'Almost entirely your CV — shows more of the same.';
    if (v >= 0.6) return 'Mostly your CV, nudged by your keywords.';
    if (v >= 0.4) return 'Balanced between your CV and your keywords.';
    if (v >= 0.15) return 'Mostly your keywords — good for changing direction.';
    return 'Ignoring your CV completely — keywords only.';
  }

  /* ----------------------------------------------------------------- init */
  function wire() {
    const zone = $('#dropzone'), fileInput = $('#cv-file');
    zone.addEventListener('click', () => fileInput.click());
    zone.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files[0]) handleFile(fileInput.files[0]);
    });
    ['dragenter', 'dragover'].forEach(ev => zone.addEventListener(ev, e => {
      e.preventDefault(); zone.classList.add('is-over');
    }));
    ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, e => {
      e.preventDefault(); zone.classList.remove('is-over');
    }));
    zone.addEventListener('drop', e => {
      const file = e.dataTransfer?.files?.[0];
      if (file) handleFile(file);
    });

    $('#cv-paste-save').addEventListener('click', () => {
      const text = CvReader.clean($('#cv-paste').value);
      if (text.length > 80) setCv(text, 'pasted text');
    });
    $('#cv-clear').addEventListener('click', () => {
      setCv('', '');
      zone.querySelector('.dz-main').textContent = 'Drop your CV here';
      zone.querySelector('.dz-sub').textContent = 'PDF, Word or text · or click to browse';
    });

    wireKeywordInput('#kw-boost', '#chips-boost', 'boost');
    wireKeywordInput('#kw-must', '#chips-must', 'must');
    wireKeywordInput('#kw-not', '#chips-not', 'not');
    renderChecks('#filter-type', TYPES, 'types');
    renderChecks('#filter-cat', CATS, 'cats');

    const slider = $('#cv-weight');
    slider.value = String(Math.round(state.cvWeight * 100));
    $('#cv-weight-out').textContent = slider.value + '%';
    $('#cv-weight-hint').textContent = weightHint(state.cvWeight);
    slider.addEventListener('input', () => {
      state.cvWeight = Number(slider.value) / 100;
      $('#cv-weight-out').textContent = slider.value + '%';
      $('#cv-weight-hint').textContent = weightHint(state.cvWeight);
      save(); render();
    });

    $('#filter-loc').value = state.loc;
    $('#filter-loc').addEventListener('input', e => {
      state.loc = e.target.value; save(); render();
    });
    $('#filter-remote').checked = state.remote;
    $('#filter-remote').addEventListener('change', e => {
      state.remote = e.target.checked; save(); render();
    });
    $('#filter-salary').checked = state.salaryOnly;
    $('#filter-salary').addEventListener('change', e => {
      state.salaryOnly = e.target.checked; save(); render();
    });
    $('#filter-age').value = String(state.maxAge);
    $('#filter-age').addEventListener('change', e => {
      state.maxAge = Number(e.target.value); save(); render();
    });
    $('#sort').value = state.sort;
    $('#sort').addEventListener('change', e => {
      state.sort = e.target.value; save(); render();
    });

    $('#tabs').addEventListener('click', e => {
      const tab = e.target.closest('.tab');
      if (!tab) return;
      state.view = tab.dataset.view;
      [...document.querySelectorAll('.tab')].forEach(t => t.classList.toggle('is-on', t === tab));
      save(); render();
    });

    $('#list').addEventListener('click', e => {
      const btn = e.target.closest('button[data-act]');
      if (!btn) return;
      const { act, id } = btn.dataset;
      const map = { save: 'saved', applied: 'applied', hide: 'hidden' }[act];
      if (state[map][id]) delete state[map][id];
      else state[map][id] = new Date().toISOString().slice(0, 10);
      save(); render();
    });

    $('#reset').addEventListener('click', () => {
      if (!confirm('Clear your CV, keywords, filters and saved roles?')) return;
      localStorage.removeItem(STORE);
      location.reload();
    });

    if (state.cvText) {
      $('#cv-status').hidden = false;
      $('#cv-name').textContent = `Using: ${state.cvName || 'saved CV'}`;
      zone.classList.add('has-cv');
      zone.querySelector('.dz-main').textContent = 'CV loaded ✓';
      zone.querySelector('.dz-sub').textContent = 'Drop another to replace it';
    }
  }

  async function boot() {
    load();
    wire();
    try {
      const res = await fetch('data/jobs.json', { cache: 'no-cache' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.jobs = data.jobs || [];
      state.meta = data;
      $('#stat-count').textContent = state.jobs.length;
      $('#stat-updated').textContent = data.generated
        ? 'updated ' + new Date(data.generated).toLocaleDateString('en-GB',
            { day: 'numeric', month: 'short' })
        : '';
      $('#foot-sources').textContent = Object.entries(data.sources || {})
        .map(([s, n]) => `${s} ${n}`).join(' · ');
    } catch (err) {
      $('#empty').hidden = false;
      $('#empty').innerHTML =
        `<p>Couldn't load the job data (${esc(err.message)}).</p>
         <p class="hint">If you're opening this file directly, run a local server instead:
         <code>python3 -m http.server</code> inside the <code>site</code> folder.</p>`;
      return;
    }
    render();
  }

  boot();
})();
