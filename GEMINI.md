# Google Antigravity & Gemini CLI Guidelines

This workspace is configured for Google Antigravity (Antigravity IDE and `agy` CLI).

## Candidate Profile (Single Source of Truth)

Per the workspace's thin-pointer architecture, candidate profile details, contact information, target roles, verified experience, and skill rubrics are maintained in:

* [CLAUDE.md](CLAUDE.md): Primary candidate profile, identity, target roles, and guidelines.
* [.claude/skills/job-application-assistant/01-candidate-profile.md](.claude/skills/job-application-assistant/01-candidate-profile.md): Structured profile data, verified achievements, and competencies.

To prevent configuration drift, personal data is not duplicated here. Always refer to [CLAUDE.md](CLAUDE.md) as the canonical source.

---

## Slash Commands & Workflows in Antigravity
The workspace skills in `.agents/skills/` map directly to interactive slash commands in Antigravity:

* **/scrape:** Runs multi-portal search CLIs (LinkedIn, Freehire) using queries from `.agents/skills/scrape/search-queries.md`. Deduplicates in `job_scraper/seen_jobs.json`.
* **/rank:** Deep-scores scraped postings across the 5-dimension rubric and outputs a ranked shortlist.
* **/apply:** Evaluates job posting, drafts tailored 1-page moderncv CV and 1-page cover letter, compiles PDFs, verifies layout, and updates `job_search_tracker.csv`.
* **/interview:** Prepares company-specific interview cheat sheets, technical deep-dives, and STAR stories in `interview_prep/`.
* **/setup:** Calibrates candidate profile and search queries.
* **/outcome:** Updates application lifecycle state in `job_search_tracker.csv`.
* **/upskill:** Identifies recurring technical skill gaps across postings.
* **/html-report:** Generates an interactive visual dashboard in `reports/`.

---

## LaTeX & Document Standards
* **CV Format:** Moderncv banking style at 11pt font, scale=0.82.
* **CV Page Budget:** **Must fit on exactly 1 page**. Any second page is a failure that must be trimmed before presenting to the user.
* **Cover Letter Format:** `cover.cls` template at 11pt font. **Must fit on exactly 1 page**.
* **Compilers:**
  - CV: Compile with `lualatex`
  - Cover Letter: Compile with `xelatex`
* **Layout Verification:** Run `python3 tools/verify_pdf.py <pdf_path> --pages 1 --ascii-dates` after every build.

---

## Style Guidelines
* **Simple English:** Avoid dense jargon. Be direct and concise.
* **Format:** Use bullet points and markdown tables with clean spacing.
* **No Em-Dashes:** Never use em-dashes or en-dashes. Use commas, hyphens, or periods.
* **Honesty Rule:** Never exaggerate or invent candidate experience. Ground every point in verified profile facts.
* **File Links:** Always provide clickable `file://` markdown links to created files.
