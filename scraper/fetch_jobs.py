#!/usr/bin/env python3
"""
Daily fresher / 0-1 yr Software Engineer job fetcher.

Uses the Adzuna Jobs API (https://developer.adzuna.com/) which legally
aggregates listings from LinkedIn, Indeed, and many other job boards.
Direct scraping of linkedin.com or indeed.com is against their Terms
of Service and gets IPs/accounts blocked -- this script avoids that by
using an official, free, ToS-compliant API instead.

Outputs, per run:
  data/YYYY-MM-DD.json
  data/YYYY-MM-DD.csv
  data/latest.json
  data/latest.csv

Required environment variables (set as GitHub Actions secrets):
  ADZUNA_APP_ID
  ADZUNA_APP_KEY
"""

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

if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
    print("ERROR: ADZUNA_APP_ID / ADZUNA_APP_KEY env vars are required.")
    sys.exit(1)

# Adzuna country codes: "in" = India, "us" = United States
COUNTRIES = ["in", "us"]

# Search terms cast a wide net; we filter precisely afterwards
SEARCH_TERMS = ["software engineer", "software developer"]

RESULTS_PER_PAGE = 50
MAX_PAGES_PER_QUERY = 3  # keep well inside free tier limits

# Titles/descriptions containing these are treated as "fresher / 0-1 yr"
FRESHER_INCLUDE = re.compile(
    r"\b(fresher|freshers|entry[- ]?level|graduate|new ?grad|trainee|"
    r"junior|jr\.?|intern(ship)?|0-1 ?year|associate software engineer)\b",
    re.IGNORECASE,
)

# Titles/descriptions containing these are excluded even if the above matched
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


def adzuna_search(country: str, what: str, page: int):
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": RESULTS_PER_PAGE,
        "what": what,
        "content-type": "application/json",
        "sort_by": "date",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


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


def normalize(job: dict, country: str) -> dict:
    title = job.get("title", "")
    description = job.get("description", "")
    company = (job.get("company") or {}).get("display_name", "")
    location = (job.get("location") or {}).get("display_name", "")
    apply_link = job.get("redirect_url", "")
    # Adzuna doesn't expose a direct company homepage; give a company
    # search link on Adzuna itself as a stable "company link".
    company_link = (
        f"https://www.adzuna.{'co.in' if country == 'in' else 'com'}/search"
        f"?q={requests.utils.quote(company)}"
        if company
        else ""
    )

    return {
        "date_fetched": str(date.today()),
        "posted_date": job.get("created", ""),
        "title": title,
        "company": company,
        "location": location,
        "country": "India" if country == "in" else "United States",
        "in_kerala": bool(KERALA_HINTS.search(f"{title} {description} {location}")),
        "experience_level": "Fresher / 0-1 yr",
        "short_description": short_summary(description),
        "apply_link": apply_link,
        "company_link": company_link,
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
    }


def fetch_all() -> list:
    results = []
    seen_ids = set()

    for country in COUNTRIES:
        for term in SEARCH_TERMS:
            for page in range(1, MAX_PAGES_PER_QUERY + 1):
                try:
                    data = adzuna_search(country, term, page)
                except requests.HTTPError as e:
                    print(f"[warn] {country}/{term}/page{page}: {e}")
                    break

                jobs = data.get("results", [])
                if not jobs:
                    break

                for job in jobs:
                    job_id = job.get("id")
                    if job_id in seen_ids:
                        continue

                    title = job.get("title", "")
                    description = job.get("description", "")
                    if not is_fresher_role(title, description):
                        continue

                    seen_ids.add(job_id)
                    results.append(normalize(job, country))

                time.sleep(0.5)  # be polite to the API

    # Kerala / India results first, then rest of India, then US
    results.sort(key=lambda r: (r["country"] != "India", not r["in_kerala"]))
    return results


def write_outputs(jobs: list, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    today_str = str(date.today())

    json_path = out_dir / f"{today_str}.json"
    csv_path = out_dir / f"{today_str}.csv"
    latest_json = out_dir / "latest.json"
    latest_csv = out_dir / "latest.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    fieldnames = [
        "date_fetched", "posted_date", "title", "company", "location",
        "country", "in_kerala", "experience_level", "short_description",
        "apply_link", "company_link", "salary_min", "salary_max",
    ]
    for path in (csv_path, latest_csv):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(jobs)

    print(f"Wrote {len(jobs)} jobs -> {json_path}, {csv_path}")


if __name__ == "__main__":
    jobs = fetch_all()
    write_outputs(jobs, Path(__file__).resolve().parent.parent / "data")
