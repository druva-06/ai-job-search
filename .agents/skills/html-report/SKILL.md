---
name: html-report
description: >
  Generates an interactive HTML dashboard visualizing job search progress, application funnel,
  and fit scores. Triggers on /html-report.
---

# /html-report - Visual Job Search Dashboard

Generates a standalone, responsive HTML report summarizing application pipeline metrics, recent status updates, and fit distributions.

---

## Step 0: Read Tracking State

1. Load `job_search_tracker.csv`.
2. Load `job_scraper/seen_jobs.json`.

---

## Step 1: Compute Pipeline Metrics

Calculate:
- Total jobs scraped vs ranked vs applied
- Breakdown by status (drafted, applied, screening, interview, offer, rejected)
- Average fit scores by target company and portal

---

## Step 2: Generate Report

Write a clean HTML document with embedded CSS and charts to `reports/job_search_report.html`.
Provide a clickable `file://` link to the user.
