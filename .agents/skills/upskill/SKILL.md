---
name: upskill
description: >
  Compares tracked job postings against candidate profile to identify recurring skill gaps
  and generates a prioritized learning roadmap with study resources. Triggers on /upskill,
  skill gaps, learning plan.
---

# /upskill - Skills Gap Analysis & Learning Plan

Analyzes recurring requirements across target job postings where the candidate profile has gaps, generating a focused upskilling roadmap.

---

## Step 0: Collect Job Requirements

1. Read tracked applications in `job_search_tracker.csv`.
2. Read top-ranked jobs (`rank_score >= 70`) from `job_scraper/seen_jobs.json`.
3. Read candidate profile in [../job-application-assistant/01-candidate-profile.md](../job-application-assistant/01-candidate-profile.md).

---

## Step 1: Identify Skill Gaps

1. Cross-reference required competencies against verified candidate skills.
2. Rank gaps by frequency of occurrence across job postings.
3. Classify gaps into:
   - High Priority (Frequently required in target roles)
   - Medium Priority (Differentiating skills / nice to have)
   - Low Priority (Role-specific or niche tools)

---

## Step 2: Formulate Learning Roadmap

1. Generate practical learning milestones for top skills.
2. Recommend concrete, hands-on project extensions (e.g. extending TrueBite with OTEL tracing, Helm deployments, or multi-cluster replication).
3. Save the report to `upskill/upskill_report_<date>.md`.
