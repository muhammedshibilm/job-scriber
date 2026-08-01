# Daily Fresher Software Engineer Job Feed (India)

Fetches fresher / 0–1 year experience Software Engineer job listings
in India — with Kerala highlighted — once a day using GitHub Actions,
and saves them as JSON + CSV, combined from multiple sources.

## Why not scrape LinkedIn/Indeed/Unstop directly?

LinkedIn and Indeed both **prohibit automated scraping in their
Terms of Service** and actively block/ban IPs and accounts that try.
Unstop doesn't publish a documented public API for third-party use
either. Instead, this project combines **multiple free, official
APIs** that legally aggregate listings from LinkedIn, Indeed, and
hundreds of other boards/company career pages:

- **Adzuna** — https://developer.adzuna.com/
- **Jooble** — https://jooble.org/api/about

Both are free to register for and designed for exactly this kind of
use, so you get broad coverage without ToS/legal risk or getting
blocked. The script is written so adding a third or fourth legitimate
source later is just one more function (see `SOURCES` list in
`fetch_jobs.py`) — for example Careerjet (has an affiliate API) or
USAJobs (official US government jobs API) if you want even more
US coverage.

## 1. Get free API credentials

**Adzuna**
1. Sign up at https://developer.adzuna.com/
2. Create an app to get an `app_id` and `app_key`.

**Jooble**
1. Request a free key at https://jooble.org/api/about
2. You'll get a single API key.

You can run with just one of these configured — the script skips
any source whose keys aren't set — but using both gives noticeably
wider coverage.

## 2. Add them as GitHub Secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

- `ADZUNA_APP_ID`
- `ADZUNA_APP_KEY`
- `JOOBLE_API_KEY`

## 3. How it runs

`.github/workflows/daily-scrape.yml` runs `scraper/fetch_jobs.py`
every day at 03:00 UTC (~08:30 AM IST), and also supports manual
triggering from the **Actions** tab ("Run workflow").

Each run:
- Searches India (`in`) and US (`us`) for "software engineer" /
  "software developer" roles.
- Filters to titles/descriptions matching fresher, entry-level,
  graduate, trainee, junior, intern, 0–1 year — and excludes
  senior/lead/2+ years roles.
- Flags Kerala-based roles (`in_kerala: true`) and sorts them first.
- Writes:
  - `data/YYYY-MM-DD.json` / `data/YYYY-MM-DD.csv` — that day's snapshot
  - `data/latest.json` / `data/latest.csv` — always the most recent run
- Commits the new files back to the repo automatically.

## Output fields

| Field | Meaning |
|---|---|
| `source` | Which API the listing came from (Adzuna / Jooble) |
| `title` | Job title |
| `company` | Company name |
| `location` | City/region |
| `country` | India or United States |
| `in_kerala` | true if the role is based in Kerala |
| `experience_level` | Always "Fresher / 0-1 yr" (post-filter) |
| `short_description` | Short plain-text summary of the role |
| `apply_link` | Direct link to apply |
| `company_link` | Link to search that company's other listings |
| `posted_date` | When the listing was posted |
| `date_fetched` | The date this script ran |

## Run locally

```bash
pip install -r requirements.txt
export ADZUNA_APP_ID=your_id
export ADZUNA_APP_KEY=your_key
export JOOBLE_API_KEY=your_key
python scraper/fetch_jobs.py
```

## Notes / limits

- Adzuna's free tier has a daily call quota — `MAX_PAGES_PER_QUERY`
  in `fetch_jobs.py` is kept small (3 pages × 50 results × 2
  countries × 2 search terms) to stay well within it. Increase if
  your quota allows.
- If you want other countries later, add their Adzuna country code
  to the `COUNTRIES` list in `fetch_jobs.py` (Adzuna covers ~20
  countries, not just India/US).
