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
    ['local', 'Local / hourly'],
  ];
  const STREAMS = ['early', 'grad-all', 'graduate-scheme', 'internship', 'placement', 'local'];
  // The three types worth chasing: a structured scheme, an internship or a
  // year in industry. Everything else is the "Everything graduate" tab.
  const EARLY = ['graduate-scheme', 'internship', 'placement'];
  const STREAM_NOTE = {
    'early': 'Structured graduate schemes, internships and year-in-industry placements — the ones with real intakes and deadlines. Use "Everything graduate" for entry-level roles too.',
    'graduate-scheme': 'Structured graduate programmes with a defined intake — these usually have hard deadlines, so check the closing dates.',
    'internship': 'Summer internships, spring weeks and insight programmes.',
    'placement': 'Year-in-industry and sandwich placements, normally taken between second and final year.',
    'local': 'Hourly and part-time work — bar, retail, warehouse, care and admin. Pay is shown per hour where the advert states it.',
  };
  const CATS = [
    ['finance', 'Finance'], ['consulting', 'Consulting'], ['marketing', 'Marketing'],
    ['sales', 'Sales & BD'], ['operations', 'Operations'], ['people', 'HR & People'],
    ['data-tech', 'Data & Tech'],
  ];
  // Shown instead of CATS when the local stream is active.
  const LOCAL_CATS = [
    ['hospitality', 'Bar & hospitality'], ['retail', 'Retail'],
    ['warehouse', 'Warehouse & driving'], ['care', 'Care & support'],
    ['admin', 'Admin & customer service'], ['cleaning', 'Cleaning'],
    ['childcare', 'Childcare & schools'], ['events', 'Events'],
    ['security', 'Security'],
  ];

  const state = {
    jobs: [], meta: {}, view: 'all', sort: 'match', stream: 'early',
    cvText: '', cvName: '',
    boost: [], must: [], not: [],
    cvWeight: 0.6,
    cats: new Set(), localCats: new Set(),
    loc: '', remote: false, salaryOnly: false, deadlineOnly: false,
    minPay: 0, maxAge: 30,
    saved: {}, applied: {}, hidden: {},
  };

  /* ------------------------------------------------------------- storage */
  function save() {
    const { jobs, meta, ...rest } = state;
    localStorage.setItem(STORE, JSON.stringify({
      ...rest, cats: [...state.cats], localCats: [...state.localCats],
    }));
  }
  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE) || '{}');
      Object.assign(state, raw, {
        cats: new Set(raw.cats || []), localCats: new Set(raw.localCats || []),
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
  function inStream(job) {
    if (state.stream === 'local') return job.stream === 'local';
    if (job.stream !== 'graduate') return false;
    if (state.stream === 'grad-all') return true;
    if (state.stream === 'early') return EARLY.includes(job.type);
    return job.type === state.stream;
  }

  function passesFilters(job) {
    if (!inStream(job)) return false;
    const catSet = state.stream === 'local' ? state.localCats : state.cats;
    if (catSet.size && !(job.cats || []).some(c => catSet.has(c))) return false;
    if (state.loc) {
      const want = state.loc.toLowerCase().split(',').map(s => s.trim()).filter(Boolean);
      // Multi-location roles carry every town, so match against all of them.
      const where = ((job.locs && job.locs.length ? job.locs : [job.location])
        .join(' | ')).toLowerCase();
      if (want.length && !want.some(w => where.includes(w))) return false;
    }
    if (state.remote && !job.remote) return false;
    if (state.salaryOnly && !job.salary) return false;
    if (state.deadlineOnly && !job.closes) return false;
    if (state.minPay && (job.salaryAnnual || 0) < state.minPay) return false;
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
    const streamCounts = Object.fromEntries(STREAMS.map(k => [k, 0]));
    for (const entry of ranked) {
      const job = entry.job, id = job.id;
      // Stream tallies ignore the current stream but respect everything else.
      if (!state.hidden[id]) {
        if (job.stream === 'local') streamCounts['local']++;
        else {
          streamCounts['grad-all']++;
          if (EARLY.includes(job.type)) streamCounts['early']++;
          if (streamCounts[job.type] !== undefined) streamCounts[job.type]++;
        }
      }
      if (state.hidden[id]) { buckets.hidden.push(entry); continue; }
      if (state.applied[id]) buckets.applied.push(entry);
      if (state.saved[id]) buckets.saved.push(entry);
      if (passesFilters(job)) buckets.all.push(entry);
    }
    for (const key of STREAMS) {
      const el = document.getElementById('s-' + key);
      if (el) el.textContent = streamCounts[key];
    }
    const earlyAll = document.getElementById('s-early-2');
    if (earlyAll) earlyAll.textContent = streamCounts['early'];
    const note = $('#stream-note');
    if (STREAM_NOTE[state.stream]) {
      note.hidden = false; note.textContent = STREAM_NOTE[state.stream];
    } else { note.hidden = true; }

    $('#n-all').textContent = buckets.all.length;
    $('#n-saved').textContent = buckets.saved.length;
    $('#n-applied').textContent = buckets.applied.length;
    $('#n-hidden').textContent = buckets.hidden.length;

    let list = buckets[state.view].slice();
    if (state.sort === 'date') {
      list.sort((a, b) => (b.job.posted || '').localeCompare(a.job.posted || ''));
    } else if (state.sort === 'salary') {
      list.sort((a, b) => (b.job.salaryAnnual || 0) - (a.job.salaryAnnual || 0));
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

  // Role types worth calling out loudly - these are what people filter for.
  const BADGE = {
    'graduate-scheme': ['Graduate scheme', 'badge-scheme'],
    'internship': ['Internship', 'badge-intern'],
    'placement': ['Placement', 'badge-placement'],
    'graduate': ['Graduate role', 'badge-grad'],
    'entry-level': ['Entry level', 'badge-entry'],
    'local': ['Local / hourly', 'badge-local'],
  };

  function card({ job, score, reasons, scored }) {
    const el = document.createElement('article');
    el.className = 'card';

    const closes = closesInfo(job);
    const [badgeLabel, badgeClass] = BADGE[job.type] || ['Role', 'badge-entry'];

    const meta = [];
    if (job.location) {
      meta.push(job.locationCount > 2
        ? `<span title="${esc((job.locs || []).join(', '))}">${esc(job.location)}</span>`
        : esc(job.location));
    }
    if (job.remote) meta.push('Remote');
    if (job.shift) meta.push(esc(job.shift));

    el.innerHTML = `
      <div class="card-score ${scored ? '' : 'is-quiet'}"
           title="${scored ? 'Match against your CV and keywords' : 'Add a CV or keywords to rank these'}">
        <span class="score-num">${scored ? score : '–'}</span>
        <span class="score-pc">${scored ? '% match' : 'no CV'}</span>
      </div>
      <div class="card-body">
        <p class="badges">
          <span class="badge ${badgeClass}">${esc(badgeLabel)}</span>
          ${job.salary
            ? `<span class="badge badge-pay">${esc(job.salary)}</span>`
            : '<span class="badge badge-nopay">Pay not stated</span>'}
          ${job.commission ? `<span class="badge badge-comm">${esc(job.commission)}</span>` : ''}
          ${job.duration ? `<span class="badge badge-len" title="How long the role lasts">⏱ ${esc(job.duration)}</span>` : ''}
        </p>
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
          ${(job.cats || []).map(c => `<span class="tag">${esc(catLabel(c))}</span>`).join('')}
          <span class="tag tag-src">via ${esc(job.source)}</span>
        </p>
        <div class="actions">
          <a class="btn btn-primary btn-sm" href="${esc(job.url)}" target="_blank" rel="noopener noreferrer">Open role ↗</a>
          <button class="btn btn-sm ${state.saved[job.id] ? 'is-on' : ''}" data-act="save" data-id="${job.id}">${state.saved[job.id] ? '★ Saved' : '☆ Save'}</button>
          <button class="btn btn-sm ${state.applied[job.id] ? 'is-on' : ''}" data-act="applied" data-id="${job.id}">${state.applied[job.id] ? '✓ Applied' : 'Mark applied'}</button>
          <button class="btn btn-sm btn-tailor" data-act="tailor" data-id="${job.id}">✎ Tailor CV</button>
          <button class="btn btn-sm btn-quiet" data-act="hide" data-id="${job.id}">${state.hidden[job.id] ? 'Unhide' : 'Hide'}</button>
        </div>
      </div>`;
    return el;
  }

  function catLabel(key) {
    const all = CATS.concat(LOCAL_CATS);
    return (all.find(x => x[0] === key) || [, key])[1];
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
    host.dataset.setKey = setKey;
  }

  // The Field filter lists different options for graduate vs local work.
  function refreshCatFilter() {
    const local = state.stream === 'local';
    renderChecks('#filter-cat', local ? LOCAL_CATS : CATS, local ? 'localCats' : 'cats');
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

  /* Keep both tab rows in step, and only show the sub-row for early careers. */
  const EARLY_STREAMS = ['early', 'graduate-scheme', 'internship', 'placement'];

  function syncStreamButtons() {
    const inEarly = EARLY_STREAMS.includes(state.stream);
    [...document.querySelectorAll('.stream')].forEach(b => {
      const on = b.dataset.stream === state.stream
        || (b.dataset.stream === 'early' && inEarly);
      b.classList.toggle('is-on', on);
    });
    [...document.querySelectorAll('.sub')].forEach(b =>
      b.classList.toggle('is-on', b.dataset.stream === state.stream));
    $('#substreams').hidden = !inEarly;
  }

  /* --------------------------------------------------------- tailor modal */
  function openTailor(id) {
    const job = state.jobs.find(j => j.id === id);
    if (!job) return;
    const model = Match.buildIdf(state.jobs);
    const analysis = Tailor.analyse(job, state.cvText, model);
    const letter = Tailor.coverLetter(job, analysis);

    $('#tailor-title').textContent = 'Tailor your application';
    $('#tailor-sub').textContent = `${job.title} — ${job.company}`;
    $('#tailor-body').innerHTML = `
      ${analysis.hasCv ? '' : `<p class="warn-note">No CV loaded, so this is based
        on the advert alone. Add your CV in the sidebar for a gap analysis.</p>`}

      ${analysis.strengths.length ? `
      <section class="tsec">
        <h3>✓ Already in your CV — lead with these</h3>
        <p class="tsec-hint">The advert and your CV both stress these. Move them into
          the top third of the page so a six-second skim catches them.</p>
        <p class="chipline">${analysis.strengths.map(t =>
          `<span class="why-chip">${esc(t)}</span>`).join('')}</p>
      </section>` : ''}

      ${analysis.missing.length ? `
      <section class="tsec">
        <h3>⚠ In the advert, missing from your CV</h3>
        <p class="tsec-hint">If you have done any of these — even in a society, a
          part-time job or coursework — name them using the advert's own wording.
          If you haven't, leave them off and address it in the cover letter.</p>
        <p class="chipline">${analysis.missing.map(t =>
          `<span class="gap-chip">${esc(t)}</span>`).join('')}</p>
      </section>` : ''}

      <section class="tsec">
        <h3>✎ Cover letter scaffold</h3>
        <p class="tsec-hint">Prompts, not a finished letter — a generated one reads
          like everyone else's. Fill each bracket in your own words.</p>
        <pre class="letter" id="letter">${esc(letter)}</pre>
        <button class="btn btn-sm" id="copy-letter">Copy scaffold</button>
      </section>

      <section class="tsec">
        <h3>General CV tips</h3>
        <ul class="tips">${Tailor.CV_TIPS.map(t => `<li>${esc(t)}</li>`).join('')}</ul>
      </section>`;

    $('#tailor').hidden = false;
    document.body.style.overflow = 'hidden';
    const copy = $('#copy-letter');
    if (copy) copy.addEventListener('click', () => {
      navigator.clipboard.writeText(letter).then(
        () => { copy.textContent = 'Copied ✓'; setTimeout(() => copy.textContent = 'Copy scaffold', 1800); },
        () => { copy.textContent = 'Press Ctrl/Cmd+C'; });
    });
  }

  function openSearchKit() {
    const streams = EARLY_STREAMS.includes(state.stream)
      ? (state.stream === 'early' ? ['graduate-scheme', 'internship', 'placement'] : [state.stream])
      : ['graduate-scheme', 'internship', 'placement'];
    const kit = SearchKit.build({
      cvText: state.cvText, boost: state.boost,
      location: state.loc || 'United Kingdom', streams,
    });

    $('#tailor-sub').textContent =
      'Searches to run on LinkedIn — save each as an alert and it checks for you';
    $('#tailor-title').textContent = 'Daily LinkedIn search kit';
    $('#tailor-body').innerHTML = `
      <p class="tsec-hint">Job Radar can't index LinkedIn — they block it. But you
        can search it yourself in seconds if you know what to type. These are built
        from your CV and keywords${state.loc ? `, around <strong>${esc(state.loc)}</strong>` : ''}.</p>
      <section class="tsec">
        ${kit.map((k, i) => `
          <div class="kit">
            <p class="kit-label">${esc(k.label)}</p>
            <code class="kit-q" id="kq${i}">${esc(k.query)}</code>
            <p class="kit-actions">
              <button class="btn btn-sm" data-copy="${i}">Copy</button>
              <a class="btn btn-sm btn-primary" href="${esc(k.url)}" target="_blank"
                 rel="noopener noreferrer">Run on LinkedIn ↗</a>
            </p>
          </div>`).join('')}
      </section>
      <section class="tsec">
        <h3>How to get the most from these</h3>
        <ul class="tips">${SearchKit.TIPS.map(t => `<li>${t}</li>`).join('')}</ul>
      </section>`;

    $('#tailor').hidden = false;
    document.body.style.overflow = 'hidden';
    $('#tailor-body').addEventListener('click', e => {
      const btn = e.target.closest('button[data-copy]');
      if (!btn) return;
      const text = kit[Number(btn.dataset.copy)].query;
      navigator.clipboard.writeText(text).then(() => {
        btn.textContent = 'Copied ✓';
        setTimeout(() => btn.textContent = 'Copy', 1600);
      }, () => { btn.textContent = 'Ctrl/Cmd+C'; });
    });
  }

  function closeTailor() {
    $('#tailor').hidden = true;
    document.body.style.overflow = '';
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
    refreshCatFilter();

    // One delegated listener survives the Field filter being re-rendered.
    $('#filter-cat').addEventListener('change', e => {
      const box = e.target.closest('input[type=checkbox]');
      if (!box) return;
      const setKey = $('#filter-cat').dataset.setKey;
      if (box.checked) state[setKey].add(box.value); else state[setKey].delete(box.value);
      save(); render();
    });

    const onStreamClick = e => {
      const btn = e.target.closest('.stream, .sub');
      if (!btn) return;
      state.stream = btn.dataset.stream;
      syncStreamButtons();
      // Local work is judged on trade and pay, not CV keyword overlap.
      if (state.stream === 'local' && state.sort === 'match') state.sort = 'date';
      if (state.stream !== 'local' && state.sort === 'date' && state.cvText) state.sort = 'match';
      $('#sort').value = state.sort;
      refreshCatFilter();
      save(); render();
    };
    $('#streams').addEventListener('click', onStreamClick);
    $('#substreams').addEventListener('click', onStreamClick);

    $('#filter-deadline').checked = state.deadlineOnly;
    $('#filter-deadline').addEventListener('change', e => {
      state.deadlineOnly = e.target.checked; save(); render();
    });
    $('#filter-pay').value = String(state.minPay);
    $('#filter-pay').addEventListener('change', e => {
      state.minPay = Number(e.target.value); save(); render();
    });

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
      if (act === 'tailor') { openTailor(id); return; }
      const map = { save: 'saved', applied: 'applied', hide: 'hidden' }[act];
      if (state[map][id]) delete state[map][id];
      else state[map][id] = new Date().toISOString().slice(0, 10);
      save(); render();
    });

    $('#tailor').addEventListener('click', e => {
      if (e.target.closest('[data-close]')) closeTailor();
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && !$('#tailor').hidden) closeTailor();
    });

    $('#search-kit').addEventListener('click', openSearchKit);

    $('#reset').addEventListener('click', () => {
      if (!confirm('Clear your CV, keywords, filters and saved roles?')) return;
      localStorage.removeItem(STORE);
      location.reload();
    });

    syncStreamButtons();

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
      const srcCount = Object.keys(data.sources || {}).length;
      $('#foot-sources').textContent =
        `${srcCount} sources · ${data.withSalary || 0} with pay listed · ` +
        `${data.withClosingDate || 0} with a closing date`;
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
