---
name: scrape
description: >
  Finds new job postings matching candidate profile via installed portal-search CLIs
  (LinkedIn, Freehire, and local portals). Deduplicates against seen_jobs.json and
  application tracker. Triggers on /scrape, scrape jobs, job search, find jobs.
---

# /scrape - Job Scraping Workflow

Searches target job boards for open positions matching the candidate profile, deduplicates against seen jobs, and stages new candidates for ranking.

---

## Step 0: Read Queries & Portals

1. Read queries from [search-queries.md](./search-queries.md) (or candidate profile in [../job-application-assistant/01-candidate-profile.md](../job-application-assistant/01-candidate-profile.md)).
2. Identify available portal CLIs under `.agents/skills/`:
   - `linkedin-search` (`.agents/skills/linkedin-search/cli/src/cli.ts`)
   - `freehire-search` (`.agents/skills/freehire-search/cli/src/cli.ts`)
   - Danish portals (`jobindex-search`, `jobnet-search`, etc. if targeting Denmark)

---

## Step 1: Run Portal Searches

Run searches across configured queries. Example commands:

```bash
# LinkedIn Search
bun run .agents/skills/linkedin-search/cli/src/cli.ts search --title "Golang" --location "Hyderabad, India" --limit 15 --format json

# Freehire Search
bun run .agents/skills/freehire-search/cli/src/cli.ts search --query "Golang" --location "India" --limit 15 --format json
```

---

## Step 2: Deduplication and State Storage

1. Load `job_scraper/seen_jobs.json` and `job_search_tracker.csv`.
2. Generate deterministic keys using `tools/job_key.py`:
   ```bash
   python3 tools/job_key.py --company "<Company>" --title "<Title>"
   ```
3. Exclude postings already in `job_search_tracker.csv` or already marked applied/rejected.
4. Record new postings with status `new` in `job_scraper/seen_jobs.json`.

---

## Step 3: Present Summary

Report the results to the user:
- Total new postings found
- Breakdown by portal and location
- Top 5 immediate highlights with URLs
- Next step prompt: "Run /rank to score these candidates against your profile."
