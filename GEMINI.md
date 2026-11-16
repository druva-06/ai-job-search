# Google Antigravity & Gemini CLI Guidelines

This workspace is configured for Google Antigravity (Antigravity IDE and `agy` CLI).

## Candidate Profile Summary
* **Candidate:** Druvasena Reddy Naini
* **Target Roles:** Backend Engineer, Software Engineer II (SDE-2), Distributed Systems Engineer
* **Core Stack:** Golang (Primary), Microservices, Concurrency (Goroutines/Channels), Apache Kafka, Redis, PostgreSQL, Docker, Kubernetes, Linux
* **Current Experience:** Software Engineer at TCS (Aug 2023 - Present, ~2.5 years)
  - Owns 6 production Golang microservices processing 10M+ daily API requests with 99.9% uptime.
  - High-frequency allocation engine handling 500+ requests/second with distributed locking and 100% state consistency.
  - Kafka event pipelines processing 1.5M+ daily events with DLQ and retries.
  - Strategic Redis caching reducing DB load by 40% and keeping p99 API latency under 50ms.
* **Flagship Project:** TrueBite (Distributed AI food label intelligence platform using LangGraph, Weaviate RAG, 4 Golang microservices, and Redis caching).
* **Education:** B.Tech in Information Technology, MLR Institute of Technology, Hyderabad (Aug 2019 - Jun 2023), CGPA: 7.5/10.

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
