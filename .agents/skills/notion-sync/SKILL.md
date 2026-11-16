---
name: notion-sync
description: >
  Publishes a read-only mirror of ranked jobs and application tracker state to a Notion database.
  Triggers on /notion-sync.
---

# /notion-sync - Sync State to Notion Database

Pushes ranked jobs and active applications to a designated Notion workspace database.

---

## Step 0: Read Local State

1. Load `job_scraper/seen_jobs.json`.
2. Load `job_search_tracker.csv`.

---

## Step 1: Format Database Entries

1. Match or create entries for each tracked application.
2. Sync properties: Company, Role, Location, Fit Score, Status, CV Link, Posting URL.

---

## Step 2: Push Updates

Execute database sync via Notion MCP or API integration.
