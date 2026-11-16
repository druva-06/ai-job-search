---
name: reset
description: >
  Resets candidate profile and search configuration back to a blank template state
  for fresh setup. Triggers on /reset.
---

# /reset - Reset Candidate Profile Data

Resets candidate profile files and search queries back to initial placeholder tokens.

---

## Step 0: User Confirmation

This command is destructive. Prompt the user for explicit confirmation before altering any files.

---

## Step 1: Reset Configuration Files

On explicit confirmation, reset:
- `.claude/skills/job-application-assistant/01-candidate-profile.md`
- `.claude/skills/job-application-assistant/02-behavioral-profile.md`
- `.claude/skills/job-application-assistant/04-job-evaluation.md`
- `.claude/skills/job-scraper/search-queries.md`
