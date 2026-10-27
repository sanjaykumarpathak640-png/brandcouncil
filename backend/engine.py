"""BrandCouncil review engine.

Specialist 'agents' (Tone, Terminology, Claims, Accessibility) run deterministic checks.
An optional LLM layer (llm.py) adds judgement-based findings; the Coordinator merges both.
Every finding carries a citation to a guideline (and approved fact where relevant).
"""
import re, datetime

SEV_W = {"high": 15, "medium": 8, "low": 3}
SEV_RANK = {"high": 0, "medium": 1, "low": 2}
AGENT_BY_PREFIX = {"tone": "Tone Agent", "terms": "Terminology Agent", "claims": "Claims Agent",
                   "access": "Accessibility Agent", "visual": "Visual Agent"}
CATEGORY_BY_PREFIX = {"tone": "tone", "terms": "terminology", "claims": "claim", "access": "accessibility", "visual": "visual"}
WORDNUM = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10,"twelve":12,"twenty":20,"thirty":30}
UNITS = {"day":"day","days":"day","hour":"hour","hours":"hour","hr":"hour","hrs":"hour","year":"year","years":"year",
         "month":"month","months":"month","%":"pct","percent":"pct"}

SUPER_RE = re.compile(r"(?:\bthe\s+)?(?:\bworld'?s\s+)?(?:\b(?:best|finest|greatest|unbeatable|unmatched|ultimate|perfect)\b|#\s?1\b|\bnumber\s+one\b|\bno\.?\s?1\b)(?:\s+(?!of\b)[\w']+){0,2}?(?:\s+in\s+the\s+world|\s+ever)?", re.I)
HEALTH_RE = re.compile(r"\b(?:cure[sd]?|cures|treat(?:s|ed)?|heal(?:s|ed)?|prevent(?:s|ed)?|detox(?:es|ify)?|boosts?\s+immunity|clinically\s+proven|doctor[- ]approved|lose\s+weight)\b(?:\s+[\w']+){0,2}", re.I)
ABS_RE = re.compile(r"\b100\s?%\s*|\bguarantee[sd]?(?:\s+to)?\s*", re.I)
MARKER_RE = re.compile(r"(\d|%|award|certif|organic|free|guarantee|proven|rated|ranked|since\s+\d{4}|thousands|million)", re.I)


def _agent(key):  return AGENT_BY_PREFIX.get(key.split(".")[0], "Council")
def _cat(key):    return CATEGORY_BY_PREFIX.get(key.split(".")[0], "other")


def quantities(sentence):
    """Return [(value, unit, start, end)] for numbers with units inside a sentence."""
    out = []
    for m in re.finditer(r"(?:₹|rs\.?|inr)\s?(\d[\d,]*(?:\.\d+)?)", sentence, re.I):
        out.append((float(m.group(1).replace(",", "")), "inr", m.start(), m.end()))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[- ]?\s*(%|percent|days?|hours?|hrs?|years?|months?)(?![a-z])", sentence, re.I):
        out.append((float(m.group(1)), UNITS[m.group(2).lower()], m.start(), m.end()))
    for m in re.finditer(r"\b(" + "|".join(WORDNUM) + r")\s*[- ]?\s*(days?|hours?|years?|months?)\b", sentence, re.I):
        out.append((float(WORDNUM[m.group(1).lower()]), UNITS[m.group(2).lower()], m.start(), m.end()))
    return out


def fmt_quantity(value, unit):
    v = int(value) if float(value).is_integer() else value
    if unit == "inr": return f"₹{v}"
    if unit == "pct": return f"{v}%"
    return f"{v} {unit}" + ("" if v == 1 else "s")


def sentences(text):
    return [(m.start(), m.end(), m.group().strip()) for m in re.finditer(r"[^.!?\n]+[.!?]*", text) if m.group().strip()]


class Builder:
    def __init__(self, text):
        self.text, self.items, self.n = text, [], 0

    def add(self, g, start, end, reason, suggestion=None, replacement=None, severity="medium",
            fact=None, confidence=0.95, category=None, source="rules", text=None):
        self.n += 1
        self.items.append({
            "id": f"f{self.n}", "span": [start, end] if start is not None else None,
            "text": text if text is not None else (self.text[start:end] if start is not None else ""),
            "category": category or _cat(g["key"]), "severity": severity, "agent": _agent(g["key"]),
            "guideline_id": g["id"], "guideline_title": g["title"], "guideline_quote": g["text"],
            "fact_id": fact["id"] if fact else None,
            "fact_statement": fact["statement"] if fact else None,
            "fact_source": fact["source"] if fact else None,
            "reason": reason, "suggestion": suggestion, "replacement": replacement,
            "confidence": confidence, "source": source})


def _case_like(src, repl):
    return repl[:1].upper() + repl[1:] if src[:1].isupper() else repl


def fact_hit(fact, low):
    return any(k in low for k in fact["keywords"])


def run_rules(text, G, facts, today=None):
    """G: {key: guideline row (enabled)}; facts: list of enabled fact dicts. Returns (findings, verified)."""
    today = today or datetime.date.today().isoformat()
    b = Builder(text); verified = []
    sents = sentences(text)

    # ---- Tone Agent
    g = G.get("tone.shouting")
    if g:
        d = g["data"]; maxe = d.get("max_exclaim", 1); maxc = d.get("max_caps_words", 1)
        runs = list(re.finditer(r"!+", text)); total = sum(len(r.group()) for r in runs)
        if total > maxe:
            kept = 0
            for r in runs:
                if len(r.group()) > 1:
                    b.add(g, r.start(), r.end(), f"{len(r.group())} exclamation marks in a row read as shouting; the guideline allows at most {maxe} per post.",
                          "Use a single '!'.", "!", "medium")
                    kept += 1
                elif kept >= maxe:
                    b.add(g, r.start(), r.end(), f"More than {maxe} exclamation mark(s) in this post.", "Use a full stop.", ".", "low")
                else:
                    kept += 1
        allow = set(d.get("allow_caps", []))
        runs_c = [m for m in re.finditer(r"\b[A-Z]{3,}\b(?:\s+[A-Z]{2,}\b)*", text)
                  if not all(w in allow for w in m.group().split())]
        if sum(len(m.group().split()) for m in runs_c) > maxc:
            for m in runs_c:
                fixed = m.group().capitalize()
                b.add(g, m.start(), m.end(), f"'{m.group()}' is written in capitals, which reads as shouting.",
                      f"Write '{fixed}'.", fixed, "low")
    g = G.get("tone.hype")
    if g:
        for phrase, alt in g["data"].get("phrases", {}).items():
            for m in re.finditer(r"\b" + re.escape(phrase) + r"\b", text, re.I):
                b.add(g, m.start(), m.end(), f"'{m.group()}' is pressure language; our voice invites rather than pushes.",
                      f"Try '{alt}'.", _case_like(m.group(), alt), "low", confidence=0.85)

    # ---- Terminology Agent
    g = G.get("terms")
    if g:
        for pair in g["data"].get("pairs", []):
            for m in re.finditer(r"\b" + re.escape(pair["bad"]) + r"\b", text, re.I):
                b.add(g, m.start(), m.end(), f"'{m.group()}' is not our preferred term; we say '{pair['good']}'.",
                      f"Use '{pair['good']}'.", _case_like(m.group(), pair["good"]), "medium", confidence=0.98)

    # ---- Accessibility Agent (text)
    g = G.get("access.readability")
    if g:
        mw = g["data"].get("max_words", 30)
        for s0, s1, s in sents:
            n = len(s.split())
            if n > mw:
                b.add(g, s0 + (len(text[s0:s1]) - len(text[s0:s1].lstrip())), s1, f"This sentence has {n} words; the guideline asks for fewer than {mw}.",
                      "Split it into two or three shorter sentences.", None, "low", confidence=0.9)

    # ---- Claims Agent
    gsup, ghealth, gabs, gfacts = G.get("claims.superlative"), G.get("claims.health"), G.get("claims.absolute"), G.get("claims.facts")
    flagged_sent = set()
    for s0, s1, s in sents:
        low = s.lower()
        offset = s0 + (len(text[s0:s1]) - len(text[s0:s1].lstrip()))
        hits = [f for f in facts if fact_hit(f, low)]
        supported_super = any("superlative" in f.get("allows", []) and not (f["expires"] and f["expires"] < today) for f in hits)
        if gsup and not supported_super:
            for m in SUPER_RE.finditer(text, s0, s1):
                if not re.search(r"(best|finest|greatest|unbeatable|unmatched|ultimate|perfect|#|number|no)", m.group(), re.I): continue
                end = m.end()
                ext = re.match(r"(?:\s+[\w']+){0,2}?\s+(?:in\s+the\s+world|ever)\b", text[end:s1], re.I)
                if ext: end += ext.end()
                phrase = text[m.start():end]
                alt = gsup["data"].get("alternative")
                b.add(gsup, m.start(), end, f"'{phrase.strip()}' is a superlative claim and no approved fact (award or ranking) supports it.",
                      f"Replace it with something provable, e.g. '{alt}'." if alt else "Replace it with something provable.",
                      alt if ext else None, "high"); flagged_sent.add(s0)
        if ghealth:
            for m in HEALTH_RE.finditer(text, s0, s1):
                b.add(ghealth, m.start(), m.end(), f"'{m.group().strip()}' is a health claim. Coffee must not be described as curing, treating or preventing conditions.",
                      f"Rephrase without any medical benefit, e.g. 'a great pick-me-up'.", None, "high"); flagged_sent.add(s0)
        if gabs and not hits:
            for m in ABS_RE.finditer(text, s0, s1):
                b.add(gabs, m.start(), m.end(), f"'{m.group().strip()}' is an absolute promise that no approved fact supports.",
                      "Remove the absolute wording.", "" if m.group().strip().startswith("100") else None, "medium"); flagged_sent.add(s0)
        if gfacts:
            matched = False
            for f in hits:
                matched = True
                if f["expires"] and f["expires"] < today:
                    b.add(gfacts, offset, s1, f"This refers to '{f['topic']}', but that approved fact expired on {f['expires']}.",
                          "Remove the outdated offer or ask an admin to renew the fact.", None, "high", fact=f); flagged_sent.add(s0); continue
                bad = [q for q in quantities(s) if f["unit"] and q[1] == f["unit"] and abs(q[0] - float(f["value"])) > 1e-9] if f["value"] is not None else []
                if bad:
                    v, u, a, z = bad[0]
                    b.add(gfacts, offset + a, offset + z,
                          f"Contradicts approved fact {f['id']}: \"{f['statement']}\"",
                          f"Use the approved value: {fmt_quantity(f['value'], f['unit'])}.", fmt_quantity(f["value"], f["unit"]), "high", fact=f, category="claim"); flagged_sent.add(s0)
                else:
                    verified.append({"text": s, "fact_id": f["id"], "fact_statement": f["statement"], "source": f["source"]})
            if not matched and s0 not in flagged_sent and MARKER_RE.search(s) and not re.search(r"\bsince\b.*\bcoffee lovers\b", s, re.I):
                b.add(gfacts, offset, s1, "This factual or promotional claim has no matching approved fact in the Facts Vault.",
                      "Add an approved fact with a source, or remove the claim.", None, "medium", confidence=0.75, category="claim")
    return b.items, verified


def coordinate(findings):
    """Coordinator: drop uncited findings, remove duplicates, rank by severity, compute score."""
    seen, out = set(), []
    for f in findings:
        if not f.get("guideline_id"): continue
        key = (f["category"], tuple(f["span"]) if f["span"] else None, f["guideline_id"], f["text"])
        if key in seen: continue
        seen.add(key); out.append(f)
    # an AI finding that overlaps a rule finding of the same category is a duplicate
    rules = [f for f in out if f["source"] == "rules" and f["span"]]
    def overlaps(a, b): return a[0] < b[1] and b[0] < a[1]
    out = [f for f in out if not (f["source"] != "rules" and f["span"] and any(r["category"] == f["category"] and overlaps(r["span"], f["span"]) for r in rules))]
    out.sort(key=lambda f: (SEV_RANK[f["severity"]], f["span"][0] if f["span"] else -1))
    for i, f in enumerate(out, 1): f["id"] = f"f{i}"
    score = max(0, 100 - sum(SEV_W[f["severity"]] for f in out))
    counts = {s: sum(1 for f in out if f["severity"] == s) for s in SEV_W}
    return out, score, counts


def apply_fixes(text, findings, accepted_ids):
    """Apply accepted replacements; higher severity first, skipping overlaps."""
    todo = [f for f in findings if f["id"] in accepted_ids and f["span"] and f.get("replacement") is not None]
    todo.sort(key=lambda f: (SEV_RANK[f["severity"]], f["span"][0]))
    taken = []
    for f in todo:
        if all(not (f["span"][0] < t[1] and t[0] < f["span"][1]) for t in taken):
            taken.append((f["span"][0], f["span"][1], f["replacement"]))
    for a, z, r in sorted(taken, reverse=True):
        text = text[:a] + r + text[z:]
    return re.sub(r"[ \t]{2,}", " ", text).replace(" .", ".").replace(" !", "!").strip()
