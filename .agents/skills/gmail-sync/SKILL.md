---
name: gmail-sync
description: >
  Scans user Gmail for application status updates (interviews, assessments, offers, rejections)
  and syncs confirmed updates to job_search_tracker.csv. Triggers on /gmail-sync.
---

# /gmail-sync - Application Status Sync from Gmail

Scans user Gmail for status signals regarding active job applications and syncs confirmed updates into `job_search_tracker.csv`.

---

## Step 0: Identify Active Applications

1. Load `job_search_tracker.csv`.
2. Filter for applications with active statuses (`applied`, `screening`, `interview`).

---

## Step 1: Scan for Status Signals

1. Check for recent emails matching target companies or recruiters.
2. Identify email categories:
   - Interview invites or scheduling requests
   - Technical assessment links
   - Rejection notifications
   - Offer letters

---

## Step 2: Confirm and Update Tracker

1. Present detected changes to the user for confirmation.
2. Upon approval, update the status and notes in `job_search_tracker.csv`.
