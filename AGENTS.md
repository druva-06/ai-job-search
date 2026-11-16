---
framework_version: 1.1.0
---

# Agent Guidelines: AI Job Search

This workspace is structured to manage job search activities, scraper tools, CVs, cover letters, and interview preparation across multiple AI agent runtimes (Claude Code, Google Antigravity, OpenAI Codex, Cursor).

## Multi-Agent Thin-Pointer Architecture

To prevent duplication and configuration drift across different AI agent frameworks, this workspace uses a unified hierarchy:

1. **Vendor-Neutral Skills & Workflows (`.agents/skills/`):**
   - The portable Agent Skills format lives in `.agents/skills/`.
   - Google Antigravity (`agy` CLI and IDE) and OpenAI Codex automatically discover all skills here.
   - Each skill directory contains a `SKILL.md` with standard YAML frontmatter (`name`, `description`).
   - In Antigravity interactive mode, every skill automatically maps to its slash command:
     - `/scrape`: Multi-portal job scraping and deduplication
     - `/rank`: 5-dimension fit scoring and shortlist generation
     - `/apply`: Drafter-reviewer application drafting (1-page CV and cover letter)
     - `/interview`: Targeted interview cheat sheets and STAR stories
     - `/setup`: Candidate profile calibration and search query setup
     - `/outcome`: Application lifecycle status tracking and feedback calibration
     - `/upskill`: Skill gap analysis and personalized learning plans
     - `/html-report`: Visual pipeline metrics dashboard
     - `/add-portal`: New job board search CLI integration
     - `/add-template`: New CV or cover letter layout template registration

2. **Claude Code Runtime Compatibility (`.claude/`):**
   - Claude Code reads slash commands from `.claude/commands/*.md` and skills from `.claude/skills/*/SKILL.md`.
   - Tool permissions and sandbox policies are defined in `.claude/settings.json`.
   - Both `.claude/` and `.agents/skills/` are maintained in parallel without code or instruction divergence.

3. **Candidate Profile & Methodology Modules:**
   - Candidate profile data, behavioral profile, writing style rules, and evaluation rubrics live in `.claude/skills/job-application-assistant/` (numbered `01-*.md` through `09-*.md`) and are symlinked into `.agents/skills/job-application-assistant/`.
   - Any updates made in one path reflect instantly across all agent runtimes with zero file drift.

4. **Portal Search CLIs:**
   - Dedicated portal search CLIs live under `.agents/skills/<portal>-search/` and are executed via Bun.
   - Portals include `linkedin-search`, `freehire-search`, and Danish boards (`jobindex-search`, `jobnet-search`, `jobbank-search`, `jobdanmark-search`).

5. **Interactive Seen Jobs Web Dashboard & Management Tool:**
   - Run `python3 tools/seen_jobs_dashboard.py` to start the live interactive web dashboard for `job_scraper/seen_jobs.json`.
   - Features rich filtering (date presets, custom ranges, company, portal, score, search), real-time live auto-update on disk changes, atomic deletions with automated backups (`seen_jobs.json.bak-*`), and 1-click restore.
   - Run with `--export reports/seen_jobs_dashboard.html` to generate an offline standalone HTML report.

6. **Style and Formatting Rules:**
   - **No em-dashes:** Do not use em-dashes or en-dashes. Use commas, hyphens, or periods.
   - **Strict 1-page CV:** Moderncv banking style at 11pt font must compile to exactly 1 page.
   - **Strict honesty:** Never hallucinate or exaggerate skills beyond verified experience.
