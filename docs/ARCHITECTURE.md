# BrandCouncil architecture

```
Browser (HTML/CSS/vanilla JS)
   |  JSON over HTTPS, Bearer token
FastAPI service (backend/app.py)  -- serves the API and the static frontend
   |-- auth + roles (creator / manager / admin), audit events
   |-- engine.py   Tone, Terminology, Claims (FactVault), Accessibility agents (deterministic) + Coordinator
   |-- imagecheck.py  alt-text, palette, contrast (Pillow)
   |-- llm.py      optional AI agents (Gemini / Claude): mask -> prompt -> strict JSON -> validate -> unmask
   |-- SQLite      users, guidelines, facts, reviews, events, settings
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
- AI models (optional, only when a key is configured): Google Gemini (`gemini-2.5-flash` by default) or Anthropic Claude via their HTTPS APIs
- Python libraries: FastAPI, Uvicorn, python-multipart, Pillow, Python standard library (sqlite3, re, hashlib, urllib)
- Frontend: plain HTML, CSS and JavaScript (no framework, no external CDN)
- Hosting: Render (web service)
- Datasets: none external. All demo data (brand "FreshBrew", guidelines, facts, sample posts, simulated reviewer decisions) is synthetic and created in `backend/seed.py`
