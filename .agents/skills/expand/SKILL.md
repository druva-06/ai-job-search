---
name: expand
description: >
  Enriches the candidate profile by discovering competencies from documents, past projects,
  and public online profiles. Triggers on /expand.
---

# /expand - Competency Profile Expansion

Discovers additional skills, project achievements, and competencies from documents or repositories, proposing additive updates to the candidate profile.

---

## Step 0: Read Source Documents

1. Scan files under `documents/` (CVs, project notes, certificates).
2. Scan public repositories or project documentation.

---

## Step 1: Extract Additional Competencies

1. Identify verified achievements with metrics.
2. Formulate bullet points following style rules in [../job-application-assistant/03-writing-style.md](../job-application-assistant/03-writing-style.md).

---

## Step 2: Propose Additions

Present proposed additions to the user. On confirmation, append new competencies to [../job-application-assistant/01-candidate-profile.md](../job-application-assistant/01-candidate-profile.md).
