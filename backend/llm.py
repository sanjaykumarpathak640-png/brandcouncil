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


def call_model(system, user, image=None, json_mode=True):
    """image: optional (bytes, mime). json_mode False returns plain text."""
    global _working_model
    p = provider()
    if p == "gemini":
        import base64
        parts = [{"text": user}]
        if image: parts.append({"inline_data": {"mime_type": image[1], "data": base64.b64encode(image[0]).decode()}})
        gc = {"temperature": 0.1}
        if json_mode: gc["responseMimeType"] = "application/json"
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}], "generationConfig": gc}
        models = list(dict.fromkeys(([_working_model] if _working_model else []) + [GEMINI_MODEL] + GEMINI_FALLBACKS))[:4]
        last = None
        for m in models:
            for attempt in (1, 2):
                try:
                    d = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                              {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, body, timeout=30 if (image or not json_mode) else 15)
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
        import base64
        content = [{"type": "text", "text": user}]
        if image: content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": image[1], "data": base64.b64encode(image[0]).decode()}})
        d = _post("https://api.anthropic.com/v1/messages",
                  {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                  {"model": ANTHROPIC_MODEL, "max_tokens": 3000, "system": system, "messages": [{"role": "user", "content": content}]}, timeout=40)
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


# ---------------------------------------------------------------- Round 3 helpers
def _json_obj(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    return json.loads(raw)


def read_image_text(data, mime):
    """Vision model reads the visible text in an image. Returns (text, status). status: ok | off | error: ..."""
    if not provider(): return "", "off"
    try:
        out = call_model("You read text in images. Return ONLY the exact visible text of the image, in reading order, one line per text block. "
                         "If there is no text, return exactly NO_TEXT. Do not describe the image.",
                         "Transcribe the visible text.", image=(data, mime or "image/png"), json_mode=False)
        out = out.strip()
        return ("" if out == "NO_TEXT" else out[:2000]), "ok"
    except Exception as e:
        return "", f"error: {type(e).__name__}"


def draft_wording(old_text, change_description):
    """AI drafts clearer guideline wording. Returns (text, status); never applied automatically."""
    if not provider(): return "", "off"
    try:
        out = call_model("You improve brand guidelines. Rewrite the guideline so it is unambiguous: keep its intent, add concrete allowed and not-allowed examples, "
                         "keep it under 70 words, plain English. Return ONLY the rewritten guideline text.",
                         f"CURRENT GUIDELINE:\n{old_text}\n\nWHAT REVIEWERS KEEP DISAGREEING ABOUT:\n{change_description}", json_mode=False)
        return out.strip().strip('"')[:600], "ok"
    except Exception as e:
        return "", f"error: {type(e).__name__}"


BRANDBOOK_KEYS = ("tone", "terms", "hype", "facts")


def propose_from_brandbook(text):
    """Asks the model for structured proposals. Returns (dict, status). Output is validated by brandbook.validate_ai."""
    if not provider(): return None, "off"
    masked = text[:12000]
    system = ("You turn a brand book into structured, checkable rules. Return ONLY JSON: "
              '{"guidelines":[{"title":str,"text":str,"excerpt":str}],'
              '"preferred_terms":[{"bad":str,"good":str,"excerpt":str}],'
              '"pressure_phrases":[{"phrase":str,"alternative":str,"excerpt":str}],'
              '"facts":[{"topic":str,"statement":str,"keywords":[str],"value":number|null,"unit":"day|hour|month|year|pct|inr|",'
              '"source":str,"expires":"YYYY-MM-DD"|null,"excerpt":str}]}. '
              "EVERY item must include an excerpt copied EXACTLY (verbatim) from the brand book that supports it. Never invent rules or facts that are not written in the text.")
    try:
        return _json_obj(call_model(system, "BRAND BOOK:\n" + masked)), "ok"
    except Exception as e:
        return None, f"error: {type(e).__name__}"
