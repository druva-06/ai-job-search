---
name: outcome
description: >
  Records application status progression (applied, screening, interview, offer, rejected)
  in job_search_tracker.csv and calibrates fit framework based on outcomes. Triggers on /outcome.
---

# /outcome - Application Status Progression

Records status updates and outcome feedback in `job_search_tracker.csv`, updating candidate calibration over time.

---

## Step 0: Find Application Row

1. Open `job_search_tracker.csv`.
2. Locate the row matching the target company and role.

---

## Step 1: Update Application State

Update status to one of the standard values:
- `applied`: Submitted to company portal
- `screening`: Recruiter screen scheduled
- `interview`: Technical or behavioral rounds ongoing
- `offer`: Offer extended
- `rejected`: Application closed without offer
- `no response`: Stale application closed after follow-up period

Append dated notes recording communication or feedback received.

---

## Step 2: Calibrate Fit Rubric

If patterns emerge across multiple applications (e.g. repeated rejections on specific seniority requirements, or high response rates in specific domains), calibrate the weights in [../job-application-assistant/04-job-evaluation.md](../job-application-assistant/04-job-evaluation.md).
