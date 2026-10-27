"""Optional LLM layer. Three specialist agents (Tone, Terminology, Claims) are asked for judgement-based findings.

Safety design:
 * confidential terms and emails/phones are masked BEFORE any external call and restored afterwards;
 * the model must return strict JSON; anything malformed, uncited or not found in the text is discarded;
 * if no API key is set or the call fails, BrandCouncil still works with the rule engine alone.
"""
import os, re, json, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_FALLBACKS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]
_working_model = None
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")

AGENTS = {
    "Tone Agent": {"prefixes": ["tone"], "category": "tone",
                   "job": "Judge whether the wording matches the brand voice guidelines (warm, calm, not pushy, not shouting)."},
    "Terminology Agent": {"prefixes": ["terms"], "category": "terminology",
                          "job": "Find uses of terms that conflict with the preferred-terminology guideline, including close variants the simple rules may miss."},
    "Claims Agent": {"prefixes": ["claims"], "category": "claim",
                     "job": "Find promotional or factual claims that are unsupported, exaggerated, outdated or that contradict the approved facts. Never invent facts."},
}


def provider():
    if os.environ.get("GEMINI_API_KEY"): return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"): return "anthropic"
    return None


def mask(text, terms):
    """Replace confidential terms, emails and phone numbers by tokens. Returns (masked, mapping)."""
    mapping, n = {}, 0
    def sub(m):
        nonlocal n
        n += 1; tok = f"[C{n}]"; mapping[tok] = m.group(0); return tok
    patterns = [re.escape(t) for t in terms if t.strip()] + [r"[\w.+-]+@[\w-]+\.[\w.]+", r"\+?\d[\d\s-]{8,}\d"]
    masked = re.sub("(?:" + "|".join(patterns) + ")", sub, text, flags=re.I) if patterns else text
    return masked, mapping


def unmask(text, mapping):
    for tok, val in mapping.items(): text = text.replace(tok, val)
    return text


def _post(url, headers, body, timeout=25):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def http_detail(e):
    """Short, key-free description of an HTTPError."""
    try:
        msg = json.loads(e.read().decode()).get("error", {}).get("message", "")
    except Exception:
        msg = ""
    key = os.environ.get("GEMINI_API_KEY", "")
    msg = msg.replace(key, "***") if key else msg
    return f"HTTP {e.code}: {msg[:160]}".strip()


def call_model(system, user):
    global _working_model
    p = provider()
    if p == "gemini":
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
        models = list(dict.fromkeys(([_working_model] if _working_model else []) + [GEMINI_MODEL] + GEMINI_FALLBACKS))[:4]
        last = None
        for m in models:
            for attempt in (1, 2):
                try:
                    d = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                              {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, body, timeout=15)
                    _working_model = m
                    return d["candidates"][0]["content"]["parts"][0]["text"]
                except urllib.error.HTTPError as e:
                    last = e
                    if e.code in (401, 403): raise                 # the key itself is the problem: other models will not help
                    if e.code in (429, 500, 502, 503, 504) and attempt == 1:
                        time.sleep(1.2); continue                  # busy: one quick retry, then try the next model
                    break                                          # 400/404 or still busy: next model
                except (urllib.error.URLError, TimeoutError) as e:
                    last = e; break
        raise last
    if p == "anthropic":
        d = _post("https://api.anthropic.com/v1/messages",
                  {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                  {"model": ANTHROPIC_MODEL, "max_tokens": 1500, "system": system, "messages": [{"role": "user", "content": user}]})
        return d["content"][0]["text"]
    raise RuntimeError("no provider")


def diagnose():
    """Used by the admin 'Test AI connection' button. Never returns the key."""
    p = provider()
    if not p: return {"ok": False, "provider": None, "detail": "No API key is set (GEMINI_API_KEY). The rule-based council is running alone."}
    try:
        out = call_model("Reply with the JSON array [] and nothing else.", "ping")
        return {"ok": True, "provider": p, "model": _working_model or GEMINI_MODEL, "detail": "The AI service answered correctly."}
    except urllib.error.HTTPError as e:
        hint = {400: "The model name or request was rejected.", 401: "The API key was rejected.", 403: "The key is not allowed to use this API (create a key in Google AI Studio and enable it for the Gemini API).",
                404: "No usable model was found.", 429: "Quota or rate limit reached. Wait a minute and retry."}.get(e.code, "")
        return {"ok": False, "provider": p, "detail": f"{http_detail(e)} {hint}".strip()}
    except Exception as e:
        return {"ok": False, "provider": p, "detail": f"{type(e).__name__}: {str(e)[:160]}"}


def _parse(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    data = json.loads(raw)
    if isinstance(data, dict): data = data.get("findings", [])
    return data if isinstance(data, list) else []


def _run_agent(name, cfg, masked_text, guidelines, facts):
    gl = [g for g in guidelines if g["key"].split(".")[0] in cfg["prefixes"]]
    if not gl: return []
    glines = "\n".join(f'- {g["id"]} ({g["title"]}): {g["text"]}' for g in gl)
    flines = "\n".join(f'- {f["id"]}: {f["statement"]} (source: {f["source"]}, expires: {f["expires"] or "never"})' for f in facts) if name == "Claims Agent" else "(not needed)"
    system = (f"You are the {name} of BrandCouncil, a brand-governance reviewer. {cfg['job']} "
              "Only flag issues that a listed guideline or approved fact supports. Do not rewrite the whole post. "
              "Return ONLY a JSON array (no prose, no markdown). Each item: "
              '{"text": exact substring copied from the content, "severity": "high|medium|low", "guideline_id": id from the list, '
              '"fact_id": id or null, "reason": one plain sentence, "suggestion": replacement wording that keeps the creator\'s intent, "confidence": 0-1}. '
              "If nothing is wrong return []. Tokens like [C1] are masked confidential text: never change them.")
    user = f"GUIDELINES:\n{glines}\n\nAPPROVED FACTS:\n{flines}\n\nCONTENT:\n{masked_text}"
    return _parse(call_model(system, user))


def ai_findings(text, guidelines, facts, conf_terms):
    """Returns (findings, status). status: 'off' | 'ok' | 'error: ...'. Findings are validated and already unmasked."""
    if not provider(): return [], "off"
    masked, mapping = mask(text, conf_terms)
    by_id = {g["id"]: g for g in guidelines}; fact_by_id = {f["id"]: f for f in facts}
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {name: ex.submit(_run_agent, name, cfg, masked, guidelines, facts) for name, cfg in AGENTS.items()}
        for name, fut in futs.items():
            try:
                for item in fut.result():
                    g = by_id.get(item.get("guideline_id"))
                    if not g or g["key"].split(".")[0] not in AGENTS[name]["prefixes"]: continue   # must cite a real guideline
                    quote = unmask(str(item.get("text", "")), mapping)
                    i = text.find(quote)
                    if not quote or i < 0: continue                                              # must quote the content exactly
                    f = fact_by_id.get(item.get("fact_id"))
                    sev = item.get("severity") if item.get("severity") in ("high", "medium", "low") else "medium"
                    sugg = unmask(str(item.get("suggestion") or ""), mapping) or None
                    results.append({"span": [i, i + len(quote)], "text": quote, "category": AGENTS[name]["category"], "severity": sev,
                                    "agent": name, "guideline_id": g["id"], "guideline_title": g["title"], "guideline_quote": g["text"],
                                    "fact_id": f["id"] if f else None, "fact_statement": f["statement"] if f else None,
                                    "fact_source": f["source"] if f else None,
                                    "reason": str(item.get("reason", ""))[:300], "suggestion": sugg[:300] if sugg else None,
                                    "replacement": sugg[:300] if sugg else None,
                                    "confidence": float(item.get("confidence", 0.7) or 0.7), "source": "ai"})
            except urllib.error.HTTPError as e:
                errors.append(f"{name}: {http_detail(e)}")
            except Exception as e:  # network, malformed JSON...
                errors.append(f"{name}: {type(e).__name__}")
    uniq = sorted({err.split(": ", 1)[1] for err in errors})
    status = "ok" if not errors else (("partial: " if results else "error: ") + "; ".join(uniq))
    return results, status
