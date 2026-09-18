# 🎯 Grad Radar

UK graduate schemes, internships and placements from dozens of employer job
boards, pulled into one page and ranked against your CV.

- **One list, not ten tabs.** A bot refreshes the jobs every morning.
- **Ranked to you.** Drop in your CV and roles are sorted by how well they fit.
- **Not limited to your CV.** Add your own keywords to steer it somewhere else —
  useful when what you've done isn't what you want to do next.
- **Shows the clock.** Every role displays when it opened and when it closes.
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
| SmartRecruiters | 8 |
| Lever | 5 |
| Recruitee | 2 |
| Workable | 1 |

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

> LinkedIn and Indeed are deliberately not used. Both block automated access and
> scraping them breaks constantly; the official APIs above cover more graduate
> roles and keep working.

## Setup

### 1. Put it on GitHub

```bash
git init && git add . && git commit -m "Grad Radar"
gh repo create grad-radar --public --source=. --push
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

## Layout

```
fetcher/          the daily job collector (stdlib only)
  sources/ats.py      Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee
  sources/boards.py   Adzuna, Reed
  classify.py         is this actually a grad role, and in what field?
  deadline.py         digs closing dates out of advert text
  uk.py               UK-only filtering
site/             the static site published to GitHub Pages
tools/            employer-slug validator
config/           search terms and verified employer boards
```

## A note on scope

This finds and ranks jobs. It doesn't auto-apply to them — that would get you
rejected and is against every job board's terms. Read the advert, then apply
properly.
