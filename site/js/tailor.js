/* "Tailor" panel: what to change on your CV for one specific job, and what to
 * put in the cover letter.
 *
 * This is deliberately NOT an AI writer. It runs entirely in the browser with
 * no API key, comparing the advert's distinctive vocabulary against your CV to
 * produce a checklist and a scaffold you fill in yourself. That keeps it free,
 * instant, private - and stops anyone posting a generated letter that every
 * other applicant also sent.
 */
const Tailor = (() => {

  // Words that describe the job rather than a skill - useless as CV advice.
  const NOT_ADVICE = new Set(`company business role team candidate opportunity
    apply application join work working looking great good strong world leading
    global uk london brand people customer customers client clients product
    products service services help support ensure deliver drive across within
    new every day time year years including include well best right
    benefits pension holiday hybrid remote office salary bonus scheme
    diversity inclusive inclusion equal opportunity employer welcome
    wider ways way improve improving innovative exciting passionate dynamic
    leading ambitious purpose mission vision values culture journey impact
    meaningful difference together collaborative environment fast paced
    challenge challenges growth develop development learn learning career
    careers future success successful excellence excellent quality high level
    key core main important essential desirable required requirements
    responsibilities duties tasks activities areas range variety broad
    opportunities experience skills knowledge understanding awareness
    stakeholders internal external cross functional various multiple
    part full time based site office location team teams colleagues
    per annum plus package competitive
    specific hands changes change things thing lots plenty able ability
    across around within throughout given taken making doing getting
    someone anyone everyone people person individuals candidates
    looking seeking wanted needed required must should would could
    really very much many more most some any all both each every`
    .split(/\s+/).filter(Boolean));

  const pretty = t => t.replace(/_/g, ' ');

  /**
   * @param job      the posting
   * @param cvText   raw CV text ('' if none loaded)
   * @param model    idf model from Match.buildIdf
   * @returns {{strengths:string[], missing:string[], hasCv:boolean}}
   */
  function analyse(job, cvText, model) {
    const vec = Match.jobVector(job, model);
    const cvProfile = cvText ? Match.profileFromCv(cvText, model) : new Map();

    // Words from the job title are not CV advice - "12 Month Placement Student"
    // yields "month" and "student", which help nobody.
    const titleWords = new Set(Match.tokenise(job.title || ''));
    // The employer's own name is not a skill to add to your CV.
    const companyWords = new Set(Match.tokenise(job.company || ''));

    const useful = ([term]) => {
      if (NOT_ADVICE.has(term) || term.length < 3) return false;
      if (titleWords.has(term) || companyWords.has(term)) return false;
      // A term in only one advert is company jargon (a product or acronym),
      // not a transferable skill worth putting on a CV.
      const df = model.df ? (model.df.get(term) || 0) : 2;
      if (df < 2 && !Match.SIGNAL.has(term)) return false;
      if (/^[a-z]{1,3}$/.test(term) && !Match.SIGNAL.has(term)) return false;
      return true;
    };

    // What this advert actually emphasises, strongest first.
    const seen = new Set();
    const jobTerms = [...vec.entries()]
      .filter(useful)
      .sort((a, b) => b[1] - a[1])
      .map(([t]) => t)
      .filter(t => !seen.has(t) && seen.add(t))
      .slice(0, 26);

    const strengths = [];
    const missing = [];
    for (const term of jobTerms) {
      if (cvProfile.has(term)) {
        if (strengths.length < 8) strengths.push(pretty(term));
      } else if (missing.length < 10) {
        missing.push(pretty(term));
      }
    }
    return { strengths, missing, hasCv: cvProfile.size > 0 };
  }

  /** A scaffold with real prompts, not a finished letter. */
  function coverLetter(job, analysis) {
    const company = job.company || 'the company';
    const lead = analysis.strengths.slice(0, 3);
    const asks = analysis.missing.slice(0, 4);

    const evidence = lead.length
      ? `Pick your two strongest of: ${lead.join(', ')}.`
      : 'Pick your two most relevant experiences.';
    const gaps = asks.length
      ? `The advert leans on: ${asks.join(', ')}.`
      : 'Re-read the advert and mirror its priorities.';

    return [
      `Dear Hiring Team at ${company},`,
      '',
      `[1 — Why this role] Name it: ${job.title}. One sentence on why ${company} `
        + `specifically, not just any employer. Look at their site for something `
        + `concrete — a product, a value, a recent announcement — and say why it `
        + `interests you.`,
      '',
      `[2 — Your evidence] ${evidence} For each one: what you did, what changed `
        + `because of it, and a number if you have one. Two short paragraphs beat `
        + `a list of adjectives.`,
      '',
      `[3 — Closing the gap] ${gaps} Show the closest thing you have done, even `
        + `if it came from a society, a part-time job or coursework. Do not claim `
        + `what you have not done — say what you would bring to it instead.`,
      '',
      `[4 — Close] State your availability${job.closes ? ` (their deadline is `
        + `${job.closes})` : ''} and ask directly for an interview.`,
      '',
      'Yours sincerely,',
      '[Your name]',
    ].join('\n');
  }

  const CV_TIPS = [
    'Mirror the advert\'s own words. Most large employers screen CVs by keyword before a human reads them.',
    'Put the matching terms in your top third — the bit that survives a six-second skim.',
    'Quantify anything you can: budget size, follower growth, hours saved, people managed.',
    'One page unless you have genuine industry experience. Two is the absolute limit.',
    'Never add a skill you cannot discuss for two minutes in an interview.',
  ];

  return { analyse, coverLetter, CV_TIPS };
})();
