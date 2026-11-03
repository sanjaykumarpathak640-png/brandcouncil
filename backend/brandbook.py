"""Brand-book import: turn a brand-book text into PROPOSED guidelines and facts. Nothing is active until an admin approves it.

Two paths: AI proposals (validated: every item needs an excerpt that really exists in the document) and a local
rule-based extractor that works without any AI key. Each proposal keeps its source excerpt for the admin to check."""
import re, datetime
import engine

SAMPLE_BRANDBOOK = """Urban Roots Cafe - Brand Book (fictional sample)

Our voice
We speak like a friendly neighbour. Always keep a warm, calm tone and never shout. Do not use more than one exclamation mark in a post.

Words we use
We call the people who visit us 'guests'. Never say 'customers' or 'users'. Say 'fresh', not 'cheap'.

Pressure language
Avoid urgency phrases such as 'limited time' or 'grab it now'. Invite people instead of pushing them.

Claims and promises
Never promise a health benefit. Do not call us 'the best' unless an award supports it.

Approved facts
Home delivery takes 3 days. Delivery is free on orders above Rs 599. Our welcome offer gives 15% off the first order until 2027-03-31.
"""

Q = re.compile(r"(?<![A-Za-z])[‘'\"“](.{1,60}?)[’'\"”](?=[\s,.;:)]|$)")
BAD_CUE = re.compile(r"\b(never say|don't say|do not say|never use|do not use|don't use|avoid|not)\b", re.I)
PRESS_CUE = re.compile(r"\b(urgency|pressure|pushy|pushing|hype|sales language|hard sell)\b", re.I)
RULE_CUE = re.compile(r"\b(always|never|must|do not|don't|avoid|should|only|no more than|not more than)\b", re.I)
STOP = {"the", "a", "an", "and", "or", "of", "on", "in", "is", "are", "our", "your", "to", "for", "with", "gives", "takes", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "first", "order", "orders", "until", "above", "than", "this", "that", "it", "we", "you"}
VALID_UNITS = {"", "day", "hour", "month", "year", "pct", "inr"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


def _sents(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 12]


def _date(s):
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", s)
    if m: return m.group(0)
    m = re.search(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(20\d\d)\b", s, re.I)
    if m:
        try: return datetime.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
        except ValueError: return None
    return None


def _kw(s):
    words = [w for w in re.findall(r"[a-z]{4,}", s.lower()) if w not in STOP and w not in ("days", "hours", "months", "years", "percent", "home", "gives", "takes")]
    seen = []
    for w in words:
        if w not in seen: seen.append(w)
    if "free" in seen and len(seen) > 1:
        o = next(w for w in seen if w != "free")
        return [f"free {o}", f"{o} is free"]
    return seen[:2]


def heuristic_proposals(text):
    items = []
    for s in _sents(text):
        quotes = [m.group(1).strip() for m in Q.finditer(s)]
        qs = " ".join(quotes)
        done = False
        if quotes and PRESS_CUE.search(s):
            for ph in quotes:
                items.append({"kind": "hype", "data": {"phrase": ph.lower(), "alternative": "take a look"}, "excerpt": s}); done = True
        elif quotes:
            m = re.search(r"\b(?:say|use|call\w*)\b[^'‘\"“]*[‘'\"“]([^’'\"”]{1,60})[’'\"”]\s*,?\s*(?:not|instead of|rather than)\s+[‘'\"“]([^’'\"”]{1,60})[’'\"”]", s, re.I)
            if m:
                items.append({"kind": "term", "data": {"bad": m.group(2).strip().lower(), "good": m.group(1).strip()}, "excerpt": s}); done = True
            elif BAD_CUE.search(s) and len(quotes) >= 1 and re.search(r"\b(never say|don't say|do not say|never use|do not use|don't use)\b", s, re.I):
                good = next((m.group(1) for t in _sents(text) for m in [re.search(r"\bcall\w*\b[^'‘\"“]*[‘'\"“]([^’'\"”]{1,60})[’'\"”]", t, re.I)] if m), None)
                if good:
                    for ph in quotes:
                        if ph.lower() != good.lower():
                            items.append({"kind": "term", "data": {"bad": ph.lower(), "good": good}, "excerpt": s}); done = True
        qty = engine.quantities(s)
        if not done and qty:
            for v, u, a, z in qty[:1]:
                kws = _kw(re.sub(r"[\d₹%,]|\brs\.?", " ", s, flags=re.I))
                items.append({"kind": "fact", "data": {"topic": (kws[0].title() if kws else "Fact"), "statement": s.rstrip("."), "keywords": kws, "value": v, "unit": u,
                                                         "source": "Imported brand book", "expires": _date(s)}, "excerpt": s}); done = True
        if not done and RULE_CUE.search(s):
            title = " ".join(s.split()[:7]).rstrip(",.;:")
            items.append({"kind": "guideline", "data": {"title": title, "text": s}, "excerpt": s})
    seen, out = set(), []
    for it in items:
        k = (it["kind"], str(sorted(it["data"].items()))[:120])
        if k in seen: continue
        seen.add(k); out.append({**it, "source": "rules"})
    return out[:40]


def _norm(s): return re.sub(r"\s+", " ", s).strip().lower()


def validate_ai(ai, text):
    """Keep only AI items whose excerpt really occurs in the document and whose fields are sane."""
    if not isinstance(ai, dict): return []
    nt, out = _norm(text), []
    def ok(x): return isinstance(x, dict) and isinstance(x.get("excerpt"), str) and len(_norm(x["excerpt"])) >= 8 and _norm(x["excerpt"]) in nt
    for x in ai.get("guidelines", []) or []:
        if ok(x) and x.get("title") and x.get("text"):
            out.append({"kind": "guideline", "data": {"title": str(x["title"])[:100], "text": str(x["text"])[:500]}, "excerpt": x["excerpt"][:400]})
    for x in ai.get("preferred_terms", []) or []:
        if ok(x) and x.get("bad") and x.get("good"):
            out.append({"kind": "term", "data": {"bad": str(x["bad"]).lower()[:60], "good": str(x["good"])[:60]}, "excerpt": x["excerpt"][:400]})
    for x in ai.get("pressure_phrases", []) or []:
        if ok(x) and x.get("phrase"):
            out.append({"kind": "hype", "data": {"phrase": str(x["phrase"]).lower()[:60], "alternative": str(x.get("alternative") or "take a look")[:60]}, "excerpt": x["excerpt"][:400]})
    for x in ai.get("facts", []) or []:
        if not (ok(x) and x.get("statement")): continue
        unit = x.get("unit") or ""
        try: val = float(x["value"]) if x.get("value") is not None else None
        except (TypeError, ValueError): val = None
        if unit not in VALID_UNITS: unit = ""; val = None
        exp = x.get("expires") if isinstance(x.get("expires"), str) and re.fullmatch(r"\d{4}-\d\d-\d\d", x["expires"]) else None
        kws = [str(k).lower()[:40] for k in (x.get("keywords") or []) if str(k).strip()][:6]
        out.append({"kind": "fact", "data": {"topic": str(x.get("topic") or "Fact")[:80], "statement": str(x["statement"])[:300], "keywords": kws or _kw(x["statement"]),
                                              "value": val, "unit": unit, "source": str(x.get("source") or "Imported brand book")[:100], "expires": exp}, "excerpt": x["excerpt"][:400]})
    return [{**i, "source": "ai"} for i in out]


def build(text, ai_dict):
    """Returns (items, mode). AI items are used when valid; otherwise the local extractor."""
    items = validate_ai(ai_dict, text) if ai_dict else []
    if items: return items, "ai"
    return heuristic_proposals(text), "rules"
