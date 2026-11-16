---
name: add-template
description: >
  Adds and validates a new custom CV or cover letter template. Triggers on /add-template.
---

# /add-template - Add Custom Document Template

Registers a new CV or cover letter layout template with the application drafting pipeline.

---

## Workflow

1. Place template source and styling assets in `cv/` or `cover_letters/`.
2. Define compile commands and page budget constraints (must fit on 1 page).
3. Validate compilation with `lualatex`, `xelatex`, or native compiler.
4. Verify text extraction and ATS readability using `python3 tools/verify_pdf.py`.
