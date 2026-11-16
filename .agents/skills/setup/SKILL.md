---
name: setup
description: >
  Onboards and calibrates candidate profile, skills, target preferences, search queries,
  and CV templates. Triggers on /setup or profile calibration requests.
---

# /setup - Candidate Profile & Search Setup

Calibrates the candidate profile, target roles, search queries, and CV templates across all agent runtimes.

---

## Step 0: Intake Candidate Data

1. Review candidate information from resume text, LinkedIn profile, or user conversation.
2. Extract:
   - Full name, location, contact details
   - Core languages and frameworks (e.g. Golang, Microservices, Distributed Systems)
   - Verified work experience, achievements, and metrics
   - Education, CGPA, and certifications

---

## Step 1: Update Profile Modules

Update candidate profile files under `.agents/skills/job-application-assistant/`:
- `01-candidate-profile.md`: Structured profile and competencies
- `02-behavioral-profile.md`: Working style and preferences
- `04-job-evaluation.md`: Custom rubric dimensions and gates

---

## Step 2: Calibrate Search Queries

Update `.agents/skills/scrape/search-queries.md` with:
- Target role titles (e.g. Backend Engineer, SDE-2, Software Engineer II)
- Primary technology keywords (e.g. Golang)
- Target locations (e.g. Hyderabad, Bengaluru, Remote)

---

## Step 3: Verify Master CV & Environment

1. Update `cv/main.tex` and verify it compiles cleanly to exactly 1 page:
   ```bash
   lualatex -interaction=nonstopmode -output-directory=cv cv/main.tex
   python3 tools/verify_pdf.py cv/main.pdf --pages 1
   ```
2. Run skill linter and security checks:
   ```bash
   python3 tools/lint_skills.py
   python3 tools/security_guards.py
   ```
