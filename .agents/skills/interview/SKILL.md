---
name: interview
description: >
  Generates targeted interview prep packs, STAR behavioral stories, technical deep-dives,
  and reverse questions for an upcoming interview. Triggers on /interview, interview prep.
---

# /interview - Interview Preparation Workflow

Generates a stage-specific interview preparation pack for an applied job posting, connecting the company requirements with the candidate's verified achievements.

---

## Step 0: Identify Target Role & Materials

1. Read application details from `job_search_tracker.csv`.
2. Locate the archived job posting: `documents/applications/<company>_<role>/job_posting.md`.
3. Locate the submitted CV: `cv/main_<company>_<role>.pdf` (or `.tex`).
4. Read interview framework: [../job-application-assistant/07-interview-prep.md](../job-application-assistant/07-interview-prep.md).

---

## Step 1: Technical Deep Dive & System Design

1. Map the company's tech stack to candidate experience:
   - Golang concurrency patterns (goroutines, channels, sync.Mutex, sync.WaitGroup).
   - High-throughput API patterns (gRPC, Gin, REST, 10M+ daily requests scale).
   - Event streaming architectures (Kafka topics, partitions, consumer groups, DLQs).
   - Distributed state, caching, and database query optimization (Redis, PostgreSQL, Oracle).
2. Anticipate architecture questions tailored to the company domain.

---

## Step 2: STAR Behavioral Stories

Frame concrete STAR (Situation, Task, Action, Result) stories strictly grounded in the candidate profile:
- Story 1: Resolving concurrency and race conditions under peak traffic (TCS reservation engine).
- Story 2: Improving API latency and database decoupling (TCS Kafka/Redis pipeline).
- Story 3: Independent ownership and architectural initiatives (TrueBite AI intelligence platform).

---

## Step 3: Company-Specific Reverse Questions

Generate 4 to 6 insightful reverse questions demonstrating deep preparation and interest in their engineering challenges.

---

## Step 4: Save Preparation Pack

Write the complete cheat sheet to:
`interview_prep/prep_<company>_<role>.md`
Provide a clickable markdown link to the user.
