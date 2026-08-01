import os
import re
import csv
import json
import time
import random
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY")
JOOBLE_API_KEY = os.environ.get("JOOBLE_API_KEY")

# Adzuna country codes — India only
ADZUNA_COUNTRIES = ["in"]

# Jooble location strings to query per "country" — India only
JOOBLE_LOCATIONS = {
    "India": "India",
}

SEARCH_TERMS = ["software engineer", "software developer"]

RESULTS_PER_PAGE = 50
MAX_PAGES_PER_QUERY = 3   # keep well inside free-tier quotas
SCRAPE_PAGES = 2          # max pages per scraper source (be polite)
SCRAPE_DELAY = (2, 4)     # random sleep seconds between scrape requests

FRESHER_INCLUDE = re.compile(
    r"\b(fresher|freshers|entry[- ]?level|graduate|new ?grad|trainee|"
    r"junior|jr\.?|intern(ship)?|0-1 ?year|associate software engineer)\b",
    re.IGNORECASE,
)
SENIOR_EXCLUDE = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|architect|"
    r"[2-9]\+? ?years?|[3-9] ?yrs?)\b",
    re.IGNORECASE,
)
KERALA_HINTS = re.compile(
    r"\b(kerala|thiruvananthapuram|trivandrum|kochi|cochin|kozhikode|"
    r"calicut|thrissur|kollam|kannur|palakkad)\b",
    re.IGNORECASE,
)

# Rotating user agents so scraped sites don't fingerprint us as a bot
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


def _headers(extra=None):
    h = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if extra:
        h.update(extra)
    return h


def is_fresher_role(title: str, description: str) -> bool:
    text = f"{title} {description}"
    if SENIOR_EXCLUDE.search(text):
        return False
    return bool(FRESHER_INCLUDE.search(text))


def short_summary(description: str, max_len: int = 220) -> str:
    text = re.sub(r"\s+", " ", description or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def html_to_text(html: str) -> str:
    """Strip HTML tags out of a snippet/description."""
    if not html:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ", strip=True)).strip()


def make_record(source, title, company, location, country, description,
                 apply_link, company_link, posted_date, salary_min=None,
                 salary_max=None):
    return {
        "source": source,
        "date_fetched": str(date.today()),
        "posted_date": posted_date or "",
        "title": title,
        "company": company,
        "location": location,
        "country": country,
        "in_kerala": bool(KERALA_HINTS.search(f"{title} {description} {location}")),
        "experience_level": "Fresher / 0-1 yr",
        "short_description": short_summary(description),
        "apply_link": apply_link,
        "company_link": company_link,
        "salary_min": salary_min,
        "salary_max": salary_max,
    }


# ---------------------------------------------------------------------
# HTTP helpers for scraping
# ---------------------------------------------------------------------
def get_soup(url, params=None, headers=None, timeout=30, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params,
                                headers=headers or _headers(), timeout=timeout)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            last_err = e
            print(f"[warn] GET {url} (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    print(f"[error] giving up on {url}: {last_err}")
    return None


# ---------------------------------------------------------------------
# Source: Adzuna (API)
# ---------------------------------------------------------------------
def fetch_adzuna() -> list:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("[skip] Adzuna: ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
        return []

    results = []
    for country in ADZUNA_COUNTRIES:
        country_name = "India"
        for term in SEARCH_TERMS:
            for page in range(1, MAX_PAGES_PER_QUERY + 1):
                url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
                params = {
                    "app_id": ADZUNA_APP_ID,
                    "app_key": ADZUNA_APP_KEY,
                    "results_per_page": RESULTS_PER_PAGE,
                    "what": term,
                    "content-type": "application/json",
                    "sort_by": "date",
                }
                try:
                    resp = requests.get(url, params=params, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                except requests.RequestException as e:
                    print(f"[warn] Adzuna {country}/{term}/page{page}: {e}")
                    break

                jobs = data.get("results", [])
                if not jobs:
                    break

                for job in jobs:
                    title = job.get("title", "")
                    description = job.get("description", "")
                    if not is_fresher_role(title, description):
                        continue
                    company = (job.get("company") or {}).get("display_name", "")
                    location = (job.get("location") or {}).get("display_name", "")
                    company_link = (
                        f"https://www.adzuna.co.in/search?q={requests.utils.quote(company)}"
                        if company else ""
                    )
                    results.append(make_record(
                        source="Adzuna",
                        title=title,
                        company=company,
                        location=location,
                        country=country_name,
                        description=description,
                        apply_link=job.get("redirect_url", ""),
                        company_link=company_link,
                        posted_date=job.get("created", ""),
                        salary_min=job.get("salary_min"),
                        salary_max=job.get("salary_max"),
                    ))
                time.sleep(0.5)
    return results


# ---------------------------------------------------------------------
# Source: Jooble (API)
# ---------------------------------------------------------------------
def fetch_jooble() -> list:
    if not JOOBLE_API_KEY:
        print("[skip] Jooble: JOOBLE_API_KEY not set")
        return []

    results = []
    url = f"https://jooble.org/api/{JOOBLE_API_KEY}"

    for country_name, location in JOOBLE_LOCATIONS.items():
        for term in SEARCH_TERMS:
            for page in range(1, MAX_PAGES_PER_QUERY + 1):
                payload = {"keywords": term, "location": location, "page": str(page)}
                try:
                    resp = requests.post(url, json=payload, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                except requests.RequestException as e:
                    print(f"[warn] Jooble {country_name}/{term}/page{page}: {e}")
                    break

                jobs = data.get("jobs", [])
                if not jobs:
                    break

                for job in jobs:
                    title = job.get("title", "")
                    description = job.get("snippet", "")
                    if not is_fresher_role(title, description):
                        continue
                    company = job.get("company", "")
                    results.append(make_record(
                        source="Jooble",
                        title=title,
                        company=company,
                        location=job.get("location", ""),
                        country=country_name,
                        description=description,
                        apply_link=job.get("link", ""),
                        company_link="",  # Jooble doesn't expose one
                        posted_date=job.get("updated", ""),
                        salary_min=None,
                        salary_max=None,
                    ))
                time.sleep(0.5)
    return results


# ---------------------------------------------------------------------
# Source: Indeed India (scraped, best-effort)
# ---------------------------------------------------------------------
INDEED_BASE = "https://in.indeed.com"

def fetch_indeed() -> list:
    """Indeed serves ~15 results per page and aggressively CAPTCHAs
    datacenter IPs, so this often returns 0 from GitHub Actions runners.
    It works far better from a residential IP (run it locally)."""
    results = []
    for term in SEARCH_TERMS:
        for page in range(SCRAPE_PAGES):
            params = {"q": f"{term} fresher", "l": "India", "start": page * 10}
            soup = get_soup(INDEED_BASE + "/jobs", params=params)
            if soup is None:
                break

            page_text = soup.get_text(" ", strip=True).lower()[:3000]
            if "captcha" in page_text or "unusual traffic" in page_text:
                print("[warn] Indeed blocked us (CAPTCHA / unusual traffic).")
                break

            cards = (
                soup.select("div.job_seen_beacon")
                or soup.select("div.result")
                or soup.select("div.jobsearch-ResultsList > div")
            )
            if not cards:
                print(f"[warn] Indeed: no job cards on page {page} (markup changed?)")
                break

            for card in cards:
                title_el = (
                    card.select_one("h2.jobTitle span")
                    or card.select_one("h2 a")
                    or card.select_one(".jobTitle")
                )
                link_el = card.select_one("h2 a[href]") or card.select_one("a[href*='/rc/clk']")
                company_el = (
                    card.select_one("[data-company-name]")
                    or card.select_one(".companyName")
                    or card.select_one(".company_location")
                )
                loc_el = card.select_one(".companyLocation") or card.select_one(".location")
                snippet_el = card.select_one(".job-snippet") or card.select_one(".summary")
                date_el = card.select_one(".date") or card.select_one("[data-testid='job-date']")

                title = title_el.get_text(" ", strip=True) if title_el else ""
                description = html_to_text(snippet_el.decode()) if snippet_el else ""
                if not is_fresher_role(title, description):
                    continue

                href = link_el.get("href", "") if link_el else ""
                results.append(make_record(
                    source="Indeed",
                    title=title,
                    company=company_el.get_text(" ", strip=True) if company_el else "",
                    location=loc_el.get_text(" ", strip=True) if loc_el else "",
                    country="India",
                    description=description,
                    apply_link=urljoin(INDEED_BASE, href) if href else "",
                    company_link="",
                    posted_date=date_el.get_text(" ", strip=True) if date_el else "",
                ))
            time.sleep(random.uniform(*SCRAPE_DELAY))
    return results


# ---------------------------------------------------------------------
# Source: LinkedIn (scraped guest API, best-effort)
# ---------------------------------------------------------------------
LINKEDIN_GUEST = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

def fetch_linkedin() -> list:
    """LinkedIn's guest endpoint works without login, but LinkedIn rate-limits
    datacenter IPs hard (999 / authwall). Expect 0 results from GitHub Actions;
    run locally for real results."""
    results = []
    for term in SEARCH_TERMS:
        for page in range(SCRAPE_PAGES):
            params = {"keywords": term, "location": "India", "start": page * 25}
            soup = get_soup(LINKEDIN_GUEST, params=params,
                            headers=_headers({"Accept": "text/html"}))
            if soup is None:
                break

            cards = soup.select("li[data-job-id]") or soup.select("li.base-card")
            if not cards:
                print(f"[warn] LinkedIn: no cards on page {page} (authwall / blocked?)")
                break

            for card in cards:
                title_el = card.select_one("h3.base-search-card__title")
                company_el = card.select_one("h4.base-search-card__subtitle")
                loc_el = card.select_one("span.job-search-card__location")
                link_el = card.select_one("a.base-card__full-link")
                time_el = card.select_one("time.job-search-card__listdate")

                title = title_el.get_text(" ", strip=True) if title_el else ""
                if not is_fresher_role(title, ""):
                    continue
                href = link_el.get("href", "") if link_el else ""
                results.append(make_record(
                    source="LinkedIn",
                    title=title,
                    company=company_el.get_text(" ", strip=True) if company_el else "",
                    location=loc_el.get_text(" ", strip=True) if loc_el else "",
                    country="India",
                    description="",
                    apply_link=href,
                    company_link="",
                    posted_date=time_el.get("datetime", "") if time_el else "",
                ))
            time.sleep(random.uniform(*SCRAPE_DELAY))
    return results


# ---------------------------------------------------------------------
# Source: Monster India (scraped, best-effort)
# ---------------------------------------------------------------------
MONSTER_BASE = "https://www.monsterindia.com"

def fetch_monster() -> list:
    results = []
    for term in SEARCH_TERMS:
        for page in range(1, SCRAPE_PAGES + 1):
            url = f"{MONSTER_BASE}/search/{term.replace(' ', '-')}-jobs"
            soup = get_soup(url, params={"page": page})
            if soup is None:
                break

            cards = (
                soup.select("div.job-card")
                or soup.select("section.job-card")
                or soup.select("[data-testid='job-card']")
            )
            if not cards:
                print(f"[warn] Monster: no cards on page {page} (blocked / markup changed?)")
                break

            for card in cards:
                title_el = card.select_one("a.job-title") or card.select_one("h2 a") or card.select_one("h3 a")
                company_el = card.select_one("span.company-name") or card.select_one(".company-name")
                loc_el = card.select_one("span.location") or card.select_one(".location")
                snippet_el = card.select_one(".description") or card.select_one(".job-description")

                title = title_el.get_text(" ", strip=True) if title_el else ""
                description = html_to_text(snippet_el.decode()) if snippet_el else ""
                if not is_fresher_role(title, description):
                    continue
                href = title_el.get("href", "") if title_el else ""
                results.append(make_record(
                    source="Monster",
                    title=title,
                    company=company_el.get_text(" ", strip=True) if company_el else "",
                    location=loc_el.get_text(" ", strip=True) if loc_el else "",
                    country="India",
                    description=description,
                    apply_link=urljoin(MONSTER_BASE, href) if href else "",
                    company_link="",
                    posted_date="",
                ))
            time.sleep(random.uniform(*SCRAPE_DELAY))
    return results


# ---------------------------------------------------------------------
# Source: RemoteOK (free JSON API — reliable)
# ---------------------------------------------------------------------
def fetch_remoteok() -> list:
    """RemoteOK exposes a free JSON endpoint. Mostly global-remote roles,
    but the fresher filter still catches junior/entry-level ones."""
    results = []
    try:
        resp = requests.get("https://remoteok.com/api", headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[warn] RemoteOK failed: {e}")
        return results

    # First item in the array is an API notice dict, the rest are jobs
    for job in data[1:]:
        title = job.get("position", "")
        description = html_to_text(job.get("description", ""))
        if not is_fresher_role(title, description):
            continue

        apply = job.get("apply_url") or job.get("url") or ""
        apply_link = apply if apply.startswith("http") else urljoin("https://remoteok.com/", apply)
        results.append(make_record(
            source="RemoteOK",
            title=title,
            company=job.get("company", ""),
            location=job.get("location", ""),
            country="Remote",
            description=description,
            apply_link=apply_link,
            company_link=job.get("company_url", ""),
            posted_date=str(job.get("date", ""))[:10],
        ))
    return results


# ---------------------------------------------------------------------
# Source: We Work Remotely (plain HTML — reliable)
# ---------------------------------------------------------------------
WWR_BASE = "https://weworkremotely.com"

def fetch_wwr() -> list:
    results = []
    for term in SEARCH_TERMS:
        soup = get_soup(WWR_BASE + "/remote-jobs/search", params={"term": term})
        if soup is None:
            continue

        items = soup.select("section.jobs li") or soup.select("ul.jobs li")
        for li in items:
            link_el = li.find("a", href=True)
            if not link_el or "remote-jobs" not in link_el["href"]:
                continue
            title_el = li.select_one("span.title")
            company_el = li.select_one("span.company")
            loc_el = li.select_one("span.location") or li.select_one("span.region")
            time_el = li.select_one("time")

            title = title_el.get_text(" ", strip=True) if title_el else ""
            if not is_fresher_role(title, ""):
                continue
            results.append(make_record(
                source="WeWorkRemotely",
                title=title,
                company=company_el.get_text(" ", strip=True) if company_el else "",
                location=loc_el.get_text(" ", strip=True) if loc_el else "",
                country="Remote",
                description="",
                apply_link=urljoin(WWR_BASE, link_el["href"]),
                company_link="",
                posted_date=time_el.get_text(" ", strip=True) if time_el else "",
            ))
        time.sleep(random.uniform(*SCRAPE_DELAY))
    return results


# Register every source function here. Add more the same way.
SOURCES = [
    fetch_adzuna,
    fetch_jooble,
    fetch_indeed,
    fetch_linkedin,
    fetch_monster,
    fetch_remoteok,
    fetch_wwr,
]


def dedupe(jobs: list) -> list:
    seen = set()
    deduped = []
    for job in jobs:
        key = (
            job["title"].strip().lower(),
            job["company"].strip().lower(),
            job["location"].strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)
    return deduped


def fetch_all() -> list:
    all_jobs = []
    for source_fn in SOURCES:
        try:
            jobs = source_fn()
            print(f"[info] {source_fn.__name__}: {len(jobs)} fresher-role matches")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"[error] {source_fn.__name__} failed: {e}")

    all_jobs = dedupe(all_jobs)
    # Kerala listings first
    all_jobs.sort(key=lambda r: not r["in_kerala"])
    return all_jobs


def write_outputs(jobs: list, out_dir: Path):
    if not jobs:
        print("[warn] No jobs collected this run — keeping previous data files untouched.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    today_str = str(date.today())

    fieldnames = [
        "source", "date_fetched", "posted_date", "title", "company",
        "location", "country", "in_kerala", "experience_level",
        "short_description", "apply_link", "company_link",
        "salary_min", "salary_max",
    ]

    for json_path in (out_dir / f"{today_str}.json", out_dir / "latest.json"):
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

    for csv_path in (out_dir / f"{today_str}.csv", out_dir / "latest.csv"):
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(jobs)

    print(f"Wrote {len(jobs)} total jobs -> {out_dir}/{today_str}.json (+csv)")


if __name__ == "__main__":
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY) and not JOOBLE_API_KEY:
        print("[info] No API keys set — API sources (Adzuna/Jooble) will be "
              "skipped, but the scraping sources will still run.")

    jobs = fetch_all()
    write_outputs(jobs, Path(__file__).resolve().parent.parent / "data")
