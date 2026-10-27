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
pip install -r backend/requirements.txt
cd backend
uvicorn app:app --reload          # open http://localhost:8000
python -m pytest tests            # 12 automated tests
```
Set `GEMINI_API_KEY` (free key from Google AI Studio) to switch the AI agents on. Without it the rule-based council runs alone.

## Deploy (Render, free)
1. Push this repository to GitHub (public).
2. On render.com: New > Blueprint > pick the repo (it reads `render.yaml`).
3. Add the environment variable `GEMINI_API_KEY`. Deploy. The first request after idle can take ~50 s on the free plan.

## Documentation
- `docs/ARCHITECTURE.md` - architecture, technical decisions, APIs/models/libraries used
- Round 2 PDF - completed features, changes from the Round 1 plan, three Round 3 improvements

## Known limitations
Single organisation per deployment; SQLite storage (resets on free hosting restarts, demo data is re-created automatically); image checks are heuristic (no OCR yet); AI mode needs an API key.
