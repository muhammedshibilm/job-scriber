

import os
import re
import csv
import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

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
MAX_PAGES_PER_QUERY = 3  # keep well inside free-tier quotas

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
# Source: Adzuna
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
# Source: Jooble
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


# Register every source function here. Add more as you get API keys
# for other legitimate aggregators (e.g. Careerjet, USAJobs, RemoteOK).
SOURCES = [
    fetch_adzuna,
    fetch_jooble,
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
        print("ERROR: set at least one source's API keys "
              "(ADZUNA_APP_ID+ADZUNA_APP_KEY and/or JOOBLE_API_KEY).")
        sys.exit(1)

    jobs = fetch_all()
    write_outputs(jobs, Path(__file__).resolve().parent.parent / "data")
