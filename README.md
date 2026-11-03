# BrandCouncil

**A council of specialist AI agents that checks content against your brand rules *before* it is published, explains every flag, and leaves the final decision to humans.**
Built for Codestar 30 (Inkloom AI problem statement: brand-governance platform) by team **Tech Titans**.

## Try it
Open the live link, then press one of the demo buttons on the sign-in page (no password typing needed):

| Role | What you can do |
|---|---|
| Content creator | Paste a post or upload an image, see explained flags, accept or dismiss fixes, apply them, submit for approval |
| Brand manager | Review submitted posts, comment, approve / request changes / reject, see governance insights |
| Brand admin | Edit guidelines, the Approved Facts Vault, confidential terms; adopt suggested guideline wording |

Demo password for all accounts: `demo123`. All data is synthetic (fictional brand "FreshBrew").
Quick test: sign in as creator, choose **"Instagram post - the intern draft"** from the sample list and press *Check with the council*.

## New in Round 3 (the three promised improvements, plus hardening)
1. **Brand-book import** (Admin > *Import brand book*): upload a PDF / Word / text brand book or paste it. BrandCouncil proposes guidelines, preferred terms, pressure phrases and approved facts. Every proposal shows the exact sentence it came from; AI proposals whose source sentence is not really in the document are discarded. **Nothing is active until an admin approves (or edits) it.** Works without an AI key through a local extractor.
2. **Images and documents**: image posts have the text written *inside* the picture read by a vision model (or typed by the creator) and checked like any text; `.docx`, `.pdf` and `.txt` documents are reviewed with every flag tied to its paragraph number.
3. **Measured accuracy + better wording**: *Accuracy* page runs the council on 34 labelled posts and reports precision / recall per agent and per guideline, including its own mistakes; re-run it after any rule change. In *Insights*, for guidelines reviewers keep dismissing, an AI-drafted clearer wording and a **what-if impact preview** (re-runs all stored reviews with the changed rule) are shown before an admin adopts anything.

Also: friendly errors for bad files and bad input, double-click protection, empty states, first-use guidance, score explanation, 29 automated tests.

## What works (Round 2)
- Guidelines, terminology, approved facts (with source and expiry) and confidential terms managed in the UI
- Text review by Tone, Terminology, Claims and Accessibility agents; every flag shows the flagged text, reason, the quoted guideline, the approved fact and source, a suggested fix and confidence
- FactVault: detects claims that contradict an approved fact (e.g. "delivery in 1 day" vs approved 2 days), expired offers, and unsupported claims
- Image review: alt-text, brand palette and overall-contrast checks
- Review workflow: accept / dismiss each flag, apply accepted fixes (never automatic), edit and re-check, submit, comments, approve / request changes / reject, full history
- Insights: recurring issues, accepted vs dismissed flags per guideline, "possibly unclear guideline" detection with suggested wording
- Privacy and AI disclosure: confidential terms, emails and phone numbers are masked before any external AI call; every finding is labelled "AI-assisted" or "rule check"; About page lists AI and services used
- Optional AI layer (Gemini or Claude) adds judgement-based findings; its output is validated (exact quote + real guideline citation required) or discarded

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt
cd backend
uvicorn app:app --reload          # open http://localhost:8000
python -m pytest tests            # 29 automated tests
```
Set `GEMINI_API_KEY` (free key from Google AI Studio) to switch the AI agents on. Without it the rule-based council runs alone.

## Deploy (Render, free)
1. Push this repository to GitHub (public).
2. On render.com: New > Blueprint > pick the repo (it reads `render.yaml`).
3. Add the environment variable `GEMINI_API_KEY`. Deploy. The first request after idle can take ~50 s on the free plan.

## Documentation
- `docs/ARCHITECTURE.md` - architecture, technical decisions, APIs/models/libraries used
- `docs/ROADMAP.md` - what comes next
- Round 3 PDF - final product summary

## Known limitations
Single organisation per deployment; SQLite storage (resets on free hosting restarts, demo data is re-created automatically); image colour/contrast checks are heuristic; reading text inside images and AI proposals need an AI key (without one, creators type the image text and the local extractor handles brand books); scanned PDFs are not OCR'd; the benchmark covers the rule engine only (34 posts) and is a regression check, not a guarantee on real-world content.
