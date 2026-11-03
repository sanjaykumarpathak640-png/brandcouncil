# BrandCouncil architecture

```
Browser (HTML/CSS/vanilla JS)
   |  JSON over HTTPS, Bearer token
FastAPI service (backend/app.py)  -- serves the API and the static frontend
   |-- auth + roles (creator / manager / admin), audit events
   |-- engine.py   Tone, Terminology, Claims (FactVault), Accessibility agents (deterministic) + Coordinator
   |-- imagecheck.py  alt-text, palette, contrast (Pillow)
   |-- llm.py      optional AI agents (Gemini / Claude): mask -> prompt -> strict JSON -> validate -> unmask
   |-- docextract.py  DOCX (zip+XML), PDF (pypdf), TXT -> numbered paragraphs
   |-- brandbook.py   brand book -> proposals (AI output validated by exact source excerpt, or local extractor)
   |-- benchmark.py   34 labelled posts -> precision / recall per agent and guideline
   |-- SQLite      users, guidelines, facts, reviews, events, settings, imports, proposals, benchmark_runs
```

## Request flow for a text review
1. `POST /api/reviews` receives the text.
2. `engine.run_rules` splits the text into sentences and runs every enabled guideline (rules are driven by the admin-editable guideline data, so deleting or editing a guideline changes the result).
3. Claims Agent: for each sentence it finds approved facts by keyword, extracts numbers with units (days, hours, %, rupees, number words), and compares them with the approved value. Same unit and different value = *contradicts*; expired fact = *outdated*; no matching fact but promotional markers = *unsupported*.
4. If an AI key exists, `llm.ai_findings` masks confidential text, asks Tone, Terminology and Claims agents (in parallel) for JSON findings, and keeps only findings that quote the content exactly and cite a real guideline of the right agent.
5. `engine.coordinate` removes uncited and duplicate findings (an AI finding overlapping a rule finding of the same category is dropped), ranks by severity and computes the score.
6. The review is stored; humans accept / dismiss flags, apply fixes, submit, and a manager decides. Every step is written to the events table.

## Main technical decisions
- **Rules first, AI second.** Anything that can be checked exactly (banned terms, numbers vs facts, expiry, contrast, palette, alt-text) is plain code, so results are repeatable and explainable. AI is used only for judgement, and is optional.
- **Citations are mandatory.** A finding without a guideline reference is discarded, which also blocks hallucinated rules.
- **No auto-rewrite.** Suggested replacements are applied only when a human accepted them and pressed "Apply".
- **Privacy by design.** Confidential terms, emails, phone numbers are replaced by tokens before an external call and restored afterwards.
- **One deployable service, no build step.** The frontend is static files served by FastAPI, so judges get one link.
- **Insights from human decisions.** A guideline whose flags are mostly dismissed (at least 3 decisions, 50% or more dismissed) is marked "possibly unclear" with suggested wording.

## APIs, models, libraries and services used
- AI models (optional, only when a key is configured): Google Gemini (`gemini-flash-latest` by default, with fallbacks) or Anthropic Claude via their HTTPS APIs
- Python libraries: FastAPI, Uvicorn, python-multipart, Pillow, pypdf, Python standard library (sqlite3, re, hashlib, urllib)
- Frontend: plain HTML, CSS and JavaScript (no framework, no external CDN)
- Hosting: Render (web service)
- Datasets: none external. All demo data (brand "FreshBrew", guidelines, facts, sample posts, simulated reviewer decisions) is synthetic and created in `backend/seed.py`

## Round 3 flows
- **Document review** `POST /api/reviews/document`: `docextract.extract_text` (4 MB / 30 000 character limits, friendly `DocError` messages) -> same engine as text posts -> each finding gets a paragraph number from `paragraph_of`. Apply/re-check works on documents and keeps paragraph breaks.
- **Image text** `POST /api/reviews/image`: Pillow checks (alt-text, palette, contrast) + text inside the image, typed by the creator or read by the vision model (`llm.read_image_text`), then reviewed as text. If AI is unavailable the review says so instead of silently skipping.
- **Brand-book import** `POST /api/brandbook/import` -> `llm.propose_from_brandbook` -> `brandbook.build` keeps only items with a verbatim excerpt, falls back to `heuristic_proposals` -> rows in `proposals` (pending). `approve` merges into guidelines/facts (terms and pressure phrases are merged into existing rule data), `reject` discards. Admin can edit any field before approving; blank/invalid items are refused.
- **Benchmark** `POST /api/benchmark/run`: runs `engine.run_rules` + coordinator on every labelled post with the *current* guidelines and facts, compares to the human labels, stores each run. Rule engine only, so it is deterministic.
- **Wording + impact preview** `GET /api/insights/suggestions`, `POST /api/insights/draft-wording`, `POST /api/insights/adopt`: `candidate_change` proposes a reversible rule tweak from flags humans dismissed; `simulate` re-runs stored reviews with it and counts flags removed that humans had dismissed vs accepted. Admin chooses whether to adopt wording and/or the rule change.
- **Robustness**: validation errors and unexpected errors return friendly JSON (400 / 500), repeated approve/submit/verdict calls are rejected cleanly, UI buttons disable while a request is running.

## Testing
`backend/tests/test_api.py`: 29 tests (rules, roles, workflow, documents DOCX/PDF/TXT and bad files, image text typed and via mocked vision, brand-book extraction/grounding/approve/reject, benchmark, impact preview, robustness). The UI was exercised end to end in a headless browser (document upload, brand-book import and approval, benchmark, insights preview) with no console errors.
