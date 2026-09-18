/* Ranking: how well does each posting fit this person?
 *
 * The fetcher already reduced every advert to a frequency-ordered keyword list,
 * so the browser only has to compare bags of words. Scoring is TF-IDF style:
 * terms that show up in nearly every advert ("team", "client") carry almost no
 * weight, while the rarer things that actually distinguish a CV count for a lot.
 */
const Match = (() => {

  const STOP = new Set(`a about above after again against all am an and any are as at be because been
  before being below between both but by can cannot could did do does doing down during each few for
  from further had has have having he her here hers him his how i if in into is it its itself me more
  most my no nor not of off on once only or other our out over own same she should so some such than
  that the their them then there these they this those through to too under until up very was we were
  what when where which while who whom why will with you your yours i'm i've we're it's don't
  cv curriculum vitae email phone mobile address linkedin github references available request
  university college school degree bsc msc ba ma phd hons class grade gcse a-level alevel
  present current ongoing january february march april may june july august september october
  november december mon tue wed thu fri sat sun
  responsible responsibilities duties including included various different using used work worked
  working role job company team teams also new within across help helped make made provide provided
  ensure ensuring support supported assist assisted involved based experience skills`
    .split(/\s+/).filter(Boolean));

  // Words that mean more on a CV than their raw frequency suggests.
  const SIGNAL = new Set(`excel powerpoint word outlook sql python r tableau powerbi power_bi looker
  salesforce hubspot sap oracle xero sage quickbooks stata spss matlab vba macros pivot_tables vlookup
  bloomberg capitaliq factset eviews
  accounting audit tax treasury actuarial valuation forecasting budgeting reconciliation payroll
  finance financial investment banking equity equities trading portfolio derivatives fixed_income
  risk credit compliance aml kyc underwriting insurance
  marketing brand branding campaign campaigns seo sem ppc crm copywriting copy content social_media
  instagram tiktok linkedin analytics google_analytics google_ads meta_ads klaviyo mailchimp
  ecommerce merchandising buying category advertising influencer affiliate email_marketing
  sales prospecting pipeline crm negotiation retention churn upsell partnerships
  consulting strategy advisory research analysis modelling modeling benchmarking
  operations logistics procurement supply_chain inventory planning forecasting lean six_sigma
  recruitment hr people onboarding
  aca acca cima cfa cipd prince2 aat
  spanish french german mandarin italian dutch portuguese arabic
  president society committee captain volunteer charity fundraising ambassador
  internship placement dissertation thesis`.split(/\s+/).filter(Boolean));

  const PHRASES = [
    'social media','google analytics','google ads','meta ads','power bi','pivot tables',
    'supply chain','six sigma','fixed income','email marketing','business development',
    'account management','financial modelling','financial modeling','data analysis',
    'market research','project management','public relations','paid search','paid social',
    'customer success','business intelligence','management accounting','investment banking',
    'private equity','asset management','risk management','due diligence','capital iq'
  ];

  /* ---------------------------------------------------------- tokenising */
  function tokenise(text) {
    const low = (text || '').toLowerCase();
    const out = [];
    for (const phrase of PHRASES) {
      if (low.includes(phrase)) out.push(phrase.replace(/ /g, '_'));
    }
    const words = low.match(/[a-z][a-z0-9+#._&-]{1,24}/g) || [];
    for (const raw of words) {
      const w = raw.replace(/^[._&-]+|[._&-]+$/g, '');
      if (w.length > 2 && !STOP.has(w) && !/^\d+$/.test(w)) out.push(w);
    }
    return out;
  }

  /* ------------------------------------------------- corpus term weights */
  // Document frequency across the whole snapshot, so boilerplate self-cancels.
  function buildIdf(jobs) {
    const df = new Map();
    for (const job of jobs) {
      const seen = new Set((job.kw || '').split(' '));
      for (const term of seen) if (term) df.set(term, (df.get(term) || 0) + 1);
    }
    const n = Math.max(jobs.length, 1);
    const idf = new Map();
    for (const [term, count] of df) {
      // Terms in more than ~45% of adverts are noise; damp them hard.
      idf.set(term, Math.max(0, Math.log(n / (1 + count)) - 0.15));
    }
    return { idf, n };
  }

  function idfOf(model, term) {
    if (model.idf.has(term)) return model.idf.get(term);
    return Math.log(model.n / 2); // unseen term: treat as rare but not infinite
  }

  /* --------------------------------------------------------- CV profile */
  function profileFromCv(cvText, model) {
    const counts = new Map();
    for (const term of tokenise(cvText)) counts.set(term, (counts.get(term) || 0) + 1);

    const weights = new Map();
    for (const [term, tf] of counts) {
      // sqrt damping: mentioning Excel six times isn't six times as meaningful
      let w = Math.sqrt(tf) * idfOf(model, term);
      if (SIGNAL.has(term)) w *= 2.2;
      if (term.includes('_')) w *= 1.5;   // multi-word phrases are specific
      if (w > 0) weights.set(term, w);
    }
    return normalise(weights, 220);
  }

  function profileFromKeywords(list, model) {
    const weights = new Map();
    for (const entry of list || []) {
      for (const term of tokenise(entry)) {
        weights.set(term, (weights.get(term) || 0) + idfOf(model, term) * 2.0);
      }
    }
    return normalise(weights, 120);
  }

  // Keep the strongest terms and scale to unit length so scores compare fairly.
  function normalise(weights, keep) {
    const top = [...weights.entries()].sort((a, b) => b[1] - a[1]).slice(0, keep);
    const mag = Math.sqrt(top.reduce((s, [, w]) => s + w * w, 0)) || 1;
    return new Map(top.map(([t, w]) => [t, w / mag]));
  }

  /* ------------------------------------------------------- job vectors */
  function jobVector(job, model) {
    const terms = (job.kw || '').split(' ').filter(Boolean);
    const vec = new Map();
    // The fetcher emits terms in frequency order, so rank stands in for weight.
    terms.forEach((term, i) => {
      const rankWeight = 1 / (1 + i / 12);
      vec.set(term, Math.max(vec.get(term) || 0, rankWeight * idfOf(model, term)));
    });
    const titleTerms = new Set(tokenise(job.title));
    for (const term of titleTerms) {
      vec.set(term, (vec.get(term) || 0) + idfOf(model, term) * 1.8);
    }
    const mag = Math.sqrt([...vec.values()].reduce((s, w) => s + w * w, 0)) || 1;
    for (const [t, w] of vec) vec.set(t, w / mag);
    return vec;
  }

  /* ------------------------------------------------------------ scoring */
  function similarity(profile, vec) {
    // Walk the smaller map for speed.
    let dot = 0;
    const [small, large] = profile.size < vec.size ? [profile, vec] : [vec, profile];
    for (const [term, w] of small) {
      const other = large.get(term);
      if (other) dot += w * other;
    }
    return dot;
  }

  function overlapTerms(profile, vec, limit = 6) {
    const hits = [];
    for (const [term, w] of profile) {
      const other = vec.get(term);
      if (other) hits.push([term, w * other]);
    }
    hits.sort((a, b) => b[1] - a[1]);
    return hits.slice(0, limit).map(([t]) => t.replace(/_/g, ' '));
  }

  /* Turn raw cosine scores into readable percentages.
   *
   * Absolute cosine values are always smallish - a CV and a job advert share
   * only part of their vocabulary even when they fit perfectly - so a fixed
   * curve makes a great match look like 35%. Instead we calibrate against the
   * strongest match actually present, then damp the whole scale down when even
   * the best match is weak, so a hopeless search can't show 90%.
   */
  function percentiler(raws) {
    const sorted = raws.filter(r => r > 0).sort((a, b) => a - b);
    if (!sorted.length) return () => 0;
    const ref = sorted[Math.floor(sorted.length * 0.98)] || sorted[sorted.length - 1];
    return raw => {
      if (raw <= 0) return 0;
      const shape = 1 - Math.exp(-2.2 * (raw / ref));
      const confidence = Math.min(1, raw / 0.08); // weak in absolute terms? scale back
      return Math.max(1, Math.round(Math.min(99, 99 * shape * confidence)));
    };
  }

  /**
   * Rank every job.
   * opts: { cvText, boost[], must[], exclude[], cvWeight (0..1) }
   */
  function rank(jobs, opts) {
    const model = buildIdf(jobs);
    const cvProfile = opts.cvText ? profileFromCv(opts.cvText, model) : new Map();
    const kwProfile = profileFromKeywords(opts.boost, model);

    const hasCv = cvProfile.size > 0;
    const hasKw = kwProfile.size > 0;
    // With only one signal present, it gets the full say.
    let cvShare = opts.cvWeight ?? 0.6;
    if (!hasCv) cvShare = 0;
    else if (!hasKw) cvShare = 1;

    const must = (opts.must || []).map(s => s.toLowerCase().trim()).filter(Boolean);
    const exclude = (opts.exclude || []).map(s => s.toLowerCase().trim()).filter(Boolean);

    const out = [];
    for (const job of jobs) {
      const hay = `${job.title} ${job.company} ${job.kw} ${job.summary}`.toLowerCase();
      if (must.length && !must.every(term => hay.includes(term))) continue;
      if (exclude.length && exclude.some(term => hay.includes(term))) continue;

      const vec = jobVector(job, model);
      const cvSim = hasCv ? similarity(cvProfile, vec) : 0;
      const kwSim = hasKw ? similarity(kwProfile, vec) : 0;
      let raw = cvShare * cvSim + (1 - cvShare) * kwSim;

      // Nudge: explicitly early-career postings beat generic entry-level ones.
      if (job.type === 'graduate-scheme') raw *= 1.12;
      else if (job.type === 'graduate' || job.type === 'internship') raw *= 1.07;

      const reasons = [];
      if (hasCv && cvSim > 0) reasons.push(...overlapTerms(cvProfile, vec, 5));
      if (hasKw && kwSim > 0) {
        for (const term of overlapTerms(kwProfile, vec, 3)) {
          if (!reasons.includes(term)) reasons.push(term);
        }
      }

      out.push({ job, raw, reasons: reasons.slice(0, 6), scored: hasCv || hasKw });
    }

    const toPercent = percentiler(out.map(e => e.raw));
    for (const entry of out) entry.score = toPercent(entry.raw);

    out.sort((a, b) => b.raw - a.raw || (b.job.posted || '').localeCompare(a.job.posted || ''));
    return out;
  }

  return { rank, tokenise };
})();
