# 🎯 Job Radar

UK graduate schemes, internships, placements and local part-time work from
dozens of job boards, pulled into one page and ranked against your CV.

- **Five tabs, not ten browser windows.** Graduate schemes, internships,
  placements, all graduate roles, and local/hourly work — each with its own tab.
- **One list.** A bot refreshes every source each morning.
- **Ranked to you.** Drop in your CV and roles are sorted by how well they fit.
- **Not limited to your CV.** Add your own keywords to steer it somewhere else —
  useful when what you've done isn't what you want to do next.
- **Shows the clock.** Every role displays when it opened and when it closes,
  with the urgent ones flagged in red.
- **Shows the money.** Pay is pulled from structured fields where a board
  provides one and parsed out of the advert text where it doesn't. Commission
  and OTE are shown separately, so a £24k sales job can't masquerade as £60k.
- **Tailors your application.** Pick any role and it compares the advert against
  your CV: what to lead with, what's missing, and a cover-letter scaffold.
- **Private.** Your CV is parsed in your browser and stored on your device only.
  It is never uploaded, and the site has no accounts, no backend and no tracking.

---

## How it fits together

```
 GitHub Action (daily)                Static site (GitHub Pages)
 ─────────────────────                ──────────────────────────
 fetcher/  ──▶ employer ATS APIs      index.html
           ──▶ Adzuna + Reed APIs     js/cv.js     reads your CV in-browser
                    │                 js/match.js  TF-IDF ranking
                    ▼                 js/app.js    filters, saving, tracking
        site/data/jobs.json  ───────▶ fetched by the page at load
```

The fetcher does the expensive text work once per day and writes a compact
keyword list per job, so the browser only compares bags of words. That keeps the
page fast and means no server is needed at all.

## Where the jobs come from

**Employer boards — no API key, work out of the box.** These are the public JSON
endpoints behind companies' own careers pages, so the listings are first-party
and complete.

| Platform | Boards currently verified |
|---|---|
| Greenhouse | 34 |
| Ashby | 23 |
| Workday | 13 |
| SmartRecruiters | 8 |
| Lever | 5 |
| Recruitee | 2 |
| Workable | 1 |

**Workday matters most.** It runs the large graduate schemes — PwC, Santander,
NatWest, Aviva, GSK, AstraZeneca, Diageo, Accenture — and it is the only source
that publishes a real application deadline, so those roles arrive with genuine
closing dates rather than ones parsed out of prose. The API needs an exact
tenant + data-centre + site triple, none of which are documented, so they are
brute-forced:

```bash
python3 tools/validate_workday.py --write
```

**Keyless aggregators.** Arbeitnow, Remotive and Jobicy need no key either. They
skew remote and tech-heavy so most of what they return is filtered out, but they
cost nothing to include.

`config/employers.yml` holds the verified list. Regenerate it any time with:

```bash
python3 tools/validate_employers.py --write
```

That probes every candidate company across all six platforms and keeps whatever
answers with live jobs, so the list never drifts into dead links.

**Job boards — free API keys, big volume.** Adzuna and Reed cover the large
employers that don't use a modern ATS (Big Four, banks, retailers). Both are
free and take a couple of minutes to set up — see below. Without them everything
still runs, you just get fewer roles.

### Why there's no LinkedIn scraper

LinkedIn blocks datacentre IPs aggressively, so a scraper would fail from GitHub
Actions within days, and running one risks the account of whoever it's logged in
as — a bad trade while you're actively applying. There is no free public jobs
API. Instead every role carries a **Search on LinkedIn** link that opens their
own search, signed in as you. Indeed is excluded for the same reasons.

## Setup

### 1. Put it on GitHub

```bash
git init && git add . && git commit -m "Grad Radar"
gh repo create job-radar --public --source=. --push
```

Then in the repo: **Settings → Pages → Source: GitHub Actions**.

Push to `main` and the site builds itself. It'll be at
`https://<your-username>.github.io/grad-radar/` — that's the link to send your mates.

### 2. Add the free API keys (optional, but worth it)

| Key | Where to get it | Free tier |
|---|---|---|
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | [developer.adzuna.com](https://developer.adzuna.com/) | yes, generous |
| `REED_API_KEY` | [reed.co.uk/developers](https://www.reed.co.uk/developers) | yes |

Add them under **Settings → Secrets and variables → Actions**. The next daily run
picks them up.

### 3. Tune what it looks for

- `config/searches.yml` — the search terms and cities the bot queries.
- `config/employers.yml` — which company boards to pull.
- `tools/validate_employers.py` — add company names to `CANDIDATES`, rerun, and
  any that have a live board get added automatically.

## Running it locally

No dependencies — a plain Python 3 install is enough.

```bash
python3 -m fetcher.main          # rebuild site/data/jobs.json
cd site && python3 -m http.server   # then open http://localhost:8000
```

Useful flags: `--no-boards` (skip Adzuna/Reed), `--no-ats` (skip employer
boards), `--max-age-days 30`.

## How the ranking works

1. The fetcher reduces each advert to its most distinctive ~70 terms.
2. The browser computes how rare each term is across the whole snapshot, so
   boilerplate ("team", "client", "fast-paced") ends up worth almost nothing.
3. Your CV becomes a weighted term vector, with known skills (Excel, SQL, Klaviyo,
   ACA…) weighted up.
4. Each job is scored by cosine similarity against your CV vector and your
   keyword vector, blended by the **CV influence** slider.
5. Scores are calibrated against the strongest match actually present, and damped
   when even the best match is weak — so a hopeless search can't show 90%.

Slide **CV influence** to 0 to ignore your CV entirely and search purely by
keywords.

## Filtering out the rubbish

The fetcher drops a posting unless it is genuinely early-career, which is
fiddlier than it sounds:

- "Graduate Recruitment **Manager**" hires graduates — it isn't one. Dropped.
- "Marketing **Executive**" is a junior UK role. Kept.
- "**Chief** Executive" obviously isn't. Dropped.
- Anything demanding 3+ years' experience is dropped unless the title says
  graduate, intern or placement.
- Non-UK postings are filtered out, including the "Cambridge, MA" trap.

Closing dates come from Reed directly, and are otherwise parsed out of the
advert text ("applications close on 30 November", "rolling basis").

## The local & part-time tab

A second stream for hourly work — bar, retail, warehouse, care, admin, cleaning,
childcare. It bypasses the graduate filter entirely and is classified by trade
instead, with hourly pay and shift pattern (part-time, weekends, evenings) shown
on each card.

**This tab needs the Adzuna or Reed key to do anything.** Employer ATS boards
carry graduate schemes, not pub and shop vacancies, so without a key it stays
empty. Configure the searches in `config/searches-local.yml` — it is
location-first, since hourly work is only useful if it's commutable.

## Tailoring your application

Click **Tailor CV** on any role:

- **Already in your CV** — terms the advert and your CV share. Move these into
  the top third of the page.
- **Missing from your CV** — what the advert stresses that you don't mention,
  filtered down to transferable skills (job-title words, the employer's own
  name, and one-off company jargon are all excluded).
- **Cover letter scaffold** — four prompts to fill in yourself.

This runs entirely in the browser with no API key and no AI writing. That is
deliberate: a generated letter reads like every other generated letter, and
graduate recruiters see hundreds. The scaffold tells you what to say; the words
have to be yours.

## Layout

```
fetcher/          the daily job collector (stdlib only)
  sources/ats.py          Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee
  sources/workday.py      Workday career sites - the big graduate schemes
  sources/boards.py       Adzuna, Reed
  sources/aggregators.py  Arbeitnow, Remotive, Jobicy
  classify.py             grad role or local work, and in what field?
  deadline.py             digs closing dates out of advert text
  salary.py               pay and commission, structured or from prose
  uk.py                   UK-only filtering
site/             the static site published to GitHub Pages
tools/            employer-slug and Workday-site validators
config/           search terms and verified employer boards
```

## A note on scope

This finds and ranks jobs. It doesn't auto-apply to them — that would get you
rejected and is against every job board's terms. Read the advert, then apply
properly.
