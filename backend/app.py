"""BrandCouncil API + static frontend (single deployable service)."""
import os, json, time, secrets, hashlib, sqlite3, datetime, uuid
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form, Depends
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import engine, llm, seed, imagecheck, docextract, brandbook, benchmark
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(HERE, "data"))
os.makedirs(os.path.join(DATA_DIR, "uploads"), exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "brandcouncil.db")
FRONTEND = os.path.join(os.path.dirname(HERE), "frontend")
MAX_IMAGE = 5 * 1024 * 1024

app = FastAPI(title="BrandCouncil", version="3.0")


# ------------------------------------------------------------------ database
def conn():
    c = sqlite3.connect(DB_PATH, timeout=15); c.row_factory = sqlite3.Row; return c


def now(): return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def hash_pw(pw, salt): return hashlib.sha256((salt + pw).encode()).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, name TEXT, role TEXT, pw_hash TEXT, salt TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, created TEXT);
CREATE TABLE IF NOT EXISTS guidelines(id TEXT PRIMARY KEY, key TEXT, title TEXT, text TEXT, data TEXT, enabled INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY, topic TEXT, keywords TEXT, statement TEXT, value REAL, unit TEXT, source TEXT, expires TEXT, allows TEXT, enabled INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, author_id INTEGER, title TEXT, channel TEXT, kind TEXT, content TEXT, image_file TEXT, alt_text TEXT,
  status TEXT, findings TEXT, verified TEXT, decisions TEXT, score INTEGER, ai_status TEXT, demo INTEGER DEFAULT 0, version INTEGER DEFAULT 1, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS proposals(id INTEGER PRIMARY KEY, import_id TEXT, kind TEXT, data TEXT, excerpt TEXT, source TEXT, status TEXT DEFAULT 'pending', created TEXT, decided_by TEXT);
CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY, filename TEXT, mode TEXT, ai_status TEXT, truncated INTEGER, created TEXT, by_user TEXT);
CREATE TABLE IF NOT EXISTS benchmark_runs(id INTEGER PRIMARY KEY, ts TEXT, result TEXT, by_user TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, review_id TEXT, user_name TEXT, action TEXT, note TEXT, ts TEXT);
"""


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
        if "meta" not in [r["name"] for r in c.execute("PRAGMA table_info(reviews)")]:
            c.execute("ALTER TABLE reviews ADD COLUMN meta TEXT DEFAULT '{}'")
        if not c.execute("SELECT 1 FROM users").fetchone():
            for u, n, r in [("creator", "Priya (Content Creator)", "creator"), ("manager", "Rahul (Brand Manager)", "manager"), ("admin", "Meera (Brand Admin)", "admin")]:
                salt = secrets.token_hex(8)
                c.execute("INSERT INTO users(username,name,role,pw_hash,salt) VALUES(?,?,?,?,?)", (u, n, r, hash_pw("demo123", salt), salt))
        if not c.execute("SELECT 1 FROM guidelines").fetchone():
            for g in seed.GUIDELINES:
                c.execute("INSERT INTO guidelines VALUES(?,?,?,?,?,1)", (g["id"], g["key"], g["title"], g["text"], json.dumps(g["data"])))
            for f in seed.FACTS:
                c.execute("INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,1)", (f["id"], f["topic"], json.dumps(f["keywords"]), f["statement"], f["value"], f["unit"], f["source"], f["expires"], json.dumps(f["allows"])))
            c.execute("INSERT INTO settings VALUES('confidential_terms',?)", (json.dumps(seed.SETTINGS["confidential_terms"]),))


def load_guidelines(c, only_enabled=True):
    rows = c.execute("SELECT * FROM guidelines" + (" WHERE enabled=1" if only_enabled else "") + " ORDER BY id").fetchall()
    return [{**dict(r), "data": json.loads(r["data"] or "{}"), "enabled": bool(r["enabled"])} for r in rows]


def load_facts(c, only_enabled=True):
    rows = c.execute("SELECT * FROM facts" + (" WHERE enabled=1" if only_enabled else "") + " ORDER BY id").fetchall()
    return [{**dict(r), "keywords": json.loads(r["keywords"]), "allows": json.loads(r["allows"] or "[]"), "enabled": bool(r["enabled"]),
             "value": (int(r["value"]) if r["value"] is not None and float(r["value"]).is_integer() else r["value"])} for r in rows]


def conf_terms(c):
    r = c.execute("SELECT v FROM settings WHERE k='confidential_terms'").fetchone()
    return json.loads(r["v"]) if r else []


def log(c, rid, user, action, note=""):
    c.execute("INSERT INTO events(review_id,user_name,action,note,ts) VALUES(?,?,?,?,?)", (rid, user, action, note, now()))


# ------------------------------------------------------------------ auth
def current_user(authorization: Optional[str] = Header(None)):
    token = (authorization or "").replace("Bearer ", "").strip()
    with conn() as c:
        r = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,)).fetchone()
    if not r: raise HTTPException(401, "Please sign in")
    return dict(r)


def need(*roles):
    def dep(u=Depends(current_user)):
        if u["role"] not in roles: raise HTTPException(403, f"This action needs one of these roles: {', '.join(roles)}")
        return u
    return dep


class Login(BaseModel): username: str; password: str


@app.post("/api/login")
def login(b: Login):
    with conn() as c:
        u = c.execute("SELECT * FROM users WHERE username=?", (b.username.strip().lower(),)).fetchone()
        if not u or hash_pw(b.password, u["salt"]) != u["pw_hash"]: raise HTTPException(401, "Wrong username or password")
        t = secrets.token_urlsafe(24)
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (t, u["id"], now()))
    return {"token": t, "user": {"id": u["id"], "name": u["name"], "role": u["role"], "username": u["username"]}}


@app.get("/api/me")
def me(u=Depends(current_user)):
    return {"id": u["id"], "name": u["name"], "role": u["role"], "username": u["username"]}


# ------------------------------------------------------------------ brand data (guidelines, facts, settings)
@app.get("/api/brand")
def brand(u=Depends(current_user)):
    with conn() as c:
        return {"guidelines": load_guidelines(c, False), "facts": load_facts(c, False), "confidential_terms": conf_terms(c)}


class GuidelineIn(BaseModel):
    id: Optional[str] = None; key: str; title: str; text: str; data: dict = {}; enabled: bool = True


class FactIn(BaseModel):
    id: Optional[str] = None; topic: str; keywords: list = []; statement: str; value: Optional[float] = None
    unit: str = ""; source: str = ""; expires: Optional[str] = None; allows: list = []; enabled: bool = True


@app.put("/api/guidelines")
def save_guideline(g: GuidelineIn, u=Depends(need("admin"))):
    with conn() as c:
        gid = g.id or f"G{int(time.time()) % 100000}"
        c.execute("INSERT OR REPLACE INTO guidelines VALUES(?,?,?,?,?,?)", (gid, g.key, g.title, g.text, json.dumps(g.data), int(g.enabled)))
        log(c, "-", u["name"], "guideline_saved", f"{gid} {g.title}")
    return {"id": gid}


@app.delete("/api/guidelines/{gid}")
def del_guideline(gid: str, u=Depends(need("admin"))):
    with conn() as c:
        c.execute("DELETE FROM guidelines WHERE id=?", (gid,)); log(c, "-", u["name"], "guideline_deleted", gid)
    return {"ok": True}


@app.put("/api/facts")
def save_fact(f: FactIn, u=Depends(need("admin"))):
    with conn() as c:
        fid = f.id or f"F{int(time.time()) % 100000}"
        c.execute("INSERT OR REPLACE INTO facts VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (fid, f.topic, json.dumps([k.strip().lower() for k in f.keywords if k.strip()]), f.statement, f.value, f.unit, f.source, f.expires or None, json.dumps(f.allows), int(f.enabled)))
        log(c, "-", u["name"], "fact_saved", f"{fid} {f.topic}")
    return {"id": fid}


@app.delete("/api/facts/{fid}")
def del_fact(fid: str, u=Depends(need("admin"))):
    with conn() as c:
        c.execute("DELETE FROM facts WHERE id=?", (fid,)); log(c, "-", u["name"], "fact_deleted", fid)
    return {"ok": True}


class Terms(BaseModel): terms: list


@app.put("/api/settings/confidential")
def save_terms(b: Terms, u=Depends(need("admin"))):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO settings VALUES('confidential_terms',?)", (json.dumps([t.strip() for t in b.terms if t.strip()]),))
        log(c, "-", u["name"], "confidential_terms_saved", f"{len(b.terms)} terms")
    return {"ok": True}


# ------------------------------------------------------------------ analysis
def analyze_text(c, text, use_ai=True, paragraphs=False):
    gl = load_guidelines(c); facts = load_facts(c)
    G = {g["key"]: g for g in gl}
    rule_findings, verified = engine.run_rules(text, G, facts)
    ai_f, ai_status = (llm.ai_findings(text[:6000], gl, facts, conf_terms(c)) if use_ai else ([], "off"))
    findings, score, counts = engine.coordinate(rule_findings + [{"id": "x", **f} for f in ai_f])
    if paragraphs:
        for f in findings:
            if f["span"]: f["paragraph"] = docextract.paragraph_of(text, f["span"][0])
        for v in verified:
            i = text.find(v["text"]); v["paragraph"] = docextract.paragraph_of(text, i) if i >= 0 else None
    return findings, verified, score, ai_status


def analyze_image_bytes(c, data, alt):
    G = {g["key"]: g for g in load_guidelines(c)}
    items, meta = imagecheck.analyze_image(data, alt, G)
    b = engine.Builder("")
    for it in items:
        b.add(it["g"], None, None, it["reason"], it["suggestion"], None, it["severity"], confidence=it["confidence"], text=it["text"])
    return b.items, meta


def insert_review(c, **kw):
    cols = dict(id=None, author_id=None, title="", channel="", kind="text", content="", image_file=None, alt_text=None, status="draft", findings="[]",
                verified="[]", decisions="{}", score=100, ai_status="off", demo=0, version=1, created=now(), updated=now(), meta="{}")
    cols.update(kw)
    for k in ("findings", "verified", "decisions", "meta"):
        if not isinstance(cols[k], str): cols[k] = json.dumps(cols[k])
    c.execute(f"INSERT INTO reviews({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(cols.values()))


def review_row(r, full=True):
    d = dict(r)
    for k in ("findings", "verified", "decisions", "meta"): d[k] = json.loads(d.get(k) or ("[]" if k in ("findings", "verified") else "{}"))
    if not full: d.pop("content", None); d.pop("findings", None); d.pop("verified", None)
    return d


def counts_of(findings): return {s: sum(1 for f in findings if f["severity"] == s) for s in ("high", "medium", "low")}


class TextIn(BaseModel): title: str = "Untitled"; channel: str = "Website"; text: str


@app.post("/api/reviews")
def create_review(b: TextIn, u=Depends(need("creator", "manager", "admin"))):
    if not b.text.strip(): raise HTTPException(400, "Please enter some content to review")
    if len(b.text) > 8000: raise HTTPException(400, "Content is too long (max 8000 characters)")
    with conn() as c:
        findings, verified, score, ai = analyze_text(c, b.text)
        rid = uuid.uuid4().hex[:10]
        insert_review(c, id=rid, author_id=u["id"], title=b.title[:120], channel=b.channel[:40], content=b.text, findings=findings, verified=verified, score=score, ai_status=ai)
        log(c, rid, u["name"], "created", f"{len(findings)} flags, score {score}, ai={ai}")
        return review_row(c.execute("SELECT * FROM reviews WHERE id=?", (rid,)).fetchone())


@app.post("/api/reviews/image")
async def create_image_review(title: str = Form("Image post"), channel: str = Form("Instagram"), alt_text: str = Form(""), caption: str = Form(""),
                              text_in_image: str = Form(""), read_text: str = Form("1"),
                              file: UploadFile = File(...), u=Depends(need("creator", "manager", "admin"))):
    data = await file.read()
    if not data: raise HTTPException(400, "The image file is empty")
    if len(data) > MAX_IMAGE: raise HTTPException(400, "Image is larger than 5 MB")
    if not (file.content_type or "").startswith("image/"): raise HTTPException(400, "Please upload an image file (PNG or JPG)")
    with conn() as c:
        try: img_f, meta = analyze_image_bytes(c, data, alt_text)
        except Exception: raise HTTPException(400, "Could not read this image file")
        # text that appears INSIDE the image: typed by the creator, else read by the vision model
        src, inner = "skipped", text_in_image.strip()
        if inner: src = "typed"
        elif read_text == "1":
            inner, st = llm.read_image_text(data, file.content_type)
            src = "vision" if st == "ok" else ("unavailable" if st == "off" else "unavailable")
            if st == "ok" and not inner: src = "vision_none"
        combined = "\n\n".join(p for p in (inner, caption.strip()) if p)
        txt_f, verified, _, ai = analyze_text(c, combined, paragraphs=True) if combined else ([], [], 100, "off")
        findings, score, counts = engine.coordinate(img_f + txt_f)
        rid = uuid.uuid4().hex[:10]
        fname = f"{rid}.img"
        with open(os.path.join(DATA_DIR, "uploads", fname), "wb") as fh: fh.write(data)
        meta = {**meta, "text_source": src, "image_text": inner, "caption_len": len(caption.strip())}
        insert_review(c, id=rid, author_id=u["id"], title=title[:120], channel=channel[:40], kind="image", content=combined, image_file=fname, alt_text=alt_text,
                      findings=findings, verified=verified, score=score, ai_status=ai, meta=meta)
        log(c, rid, u["name"], "created", f"image, text read: {src}, {len(findings)} flags, score {score}")
        return review_row(c.execute("SELECT * FROM reviews WHERE id=?", (rid,)).fetchone())


@app.post("/api/reviews/document")
async def create_document_review(title: str = Form(""), channel: str = Form("Document"), file: UploadFile = File(...),
                                 u=Depends(need("creator", "manager", "admin"))):
    data = await file.read()
    try: text, kind, truncated = docextract.extract_text(file.filename, data)
    except docextract.DocError as e: raise HTTPException(400, str(e))
    with conn() as c:
        findings, verified, score, ai = analyze_text(c, text, paragraphs=True)
        rid = uuid.uuid4().hex[:10]
        insert_review(c, id=rid, author_id=u["id"], title=(title.strip() or file.filename or "Document")[:120], channel=channel[:40], kind="document", content=text,
                      findings=findings, verified=verified, score=score, ai_status=ai,
                      meta={"filename": file.filename, "file_kind": kind, "truncated": truncated, "paragraphs": text.count("\n\n") + 1})
        log(c, rid, u["name"], "created", f"document {file.filename}, {len(findings)} flags, score {score}")
        return review_row(c.execute("SELECT * FROM reviews WHERE id=?", (rid,)).fetchone())


@app.get("/api/reviews/{rid}/image")
def get_image(rid: str, token: str = ""):
    from fastapi.responses import FileResponse
    with conn() as c:
        ok = c.execute("SELECT 1 FROM sessions WHERE token=?", (token,)).fetchone()
        r = c.execute("SELECT image_file FROM reviews WHERE id=?", (rid,)).fetchone()
    if not ok or not r or not r["image_file"]: raise HTTPException(404, "No image")
    return FileResponse(os.path.join(DATA_DIR, "uploads", r["image_file"]), media_type="image/png")


def get_review(c, rid, u):
    r = c.execute("SELECT * FROM reviews WHERE id=?", (rid,)).fetchone()
    if not r: raise HTTPException(404, "Review not found")
    if u["role"] == "creator" and r["author_id"] != u["id"]: raise HTTPException(403, "This review belongs to another creator")
    return r


@app.get("/api/reviews")
def list_reviews(status: str = "", u=Depends(current_user)):
    q, args = "SELECT r.*, u.name AS author FROM reviews r JOIN users u ON u.id=r.author_id", []
    cond = []
    if u["role"] == "creator": cond.append("r.author_id=?"); args.append(u["id"])
    if status: cond.append("r.status=?"); args.append(status)
    if cond: q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY r.updated DESC LIMIT 200"
    with conn() as c:
        rows = c.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = review_row(r, full=False); d["author"] = r["author"]
            d["counts"] = counts_of(json.loads(r["findings"] or "[]")); out.append(d)
    return out


@app.get("/api/reviews/{rid}")
def read_review(rid: str, u=Depends(current_user)):
    with conn() as c:
        r = get_review(c, rid, u); d = review_row(r)
        a = c.execute("SELECT name FROM users WHERE id=?", (r["author_id"],)).fetchone(); d["author"] = a["name"] if a else "?"
        d["events"] = [dict(e) for e in c.execute("SELECT * FROM events WHERE review_id=? ORDER BY id", (rid,)).fetchall()]
        d["counts"] = counts_of(d["findings"])
    return d


class Decision(BaseModel): finding_id: str; decision: str; note: str = ""


@app.post("/api/reviews/{rid}/decisions")
def decide(rid: str, b: Decision, u=Depends(need("creator", "manager", "admin"))):
    if b.decision not in ("accepted", "dismissed", "pending"): raise HTTPException(400, "Decision must be accepted or dismissed")
    with conn() as c:
        r = get_review(c, rid, u)
        if r["status"] in ("approved", "rejected") : raise HTTPException(400, "This review is already closed")
        findings = json.loads(r["findings"]); dec = json.loads(r["decisions"] or "{}")
        if b.finding_id not in {f["id"] for f in findings}: raise HTTPException(404, "Unknown flag")
        if b.decision == "pending": dec.pop(b.finding_id, None)
        else: dec[b.finding_id] = {"decision": b.decision, "by": u["name"], "role": u["role"], "ts": now(), "note": b.note}
        c.execute("UPDATE reviews SET decisions=?, updated=? WHERE id=?", (json.dumps(dec), now(), rid))
        log(c, rid, u["name"], f"flag_{b.decision}", f"{b.finding_id}: " + next(f["text"] for f in findings if f["id"] == b.finding_id)[:60])
    return {"decisions": dec}


class Revise(BaseModel): text: Optional[str] = None; apply_accepted: bool = False


@app.post("/api/reviews/{rid}/revise")
def revise(rid: str, b: Revise, u=Depends(need("creator", "manager", "admin"))):
    """Creator edits the text (or applies accepted fixes) and the council re-checks it. The old text is kept in history."""
    with conn() as c:
        r = get_review(c, rid, u)
        if r["kind"] == "image": raise HTTPException(400, "Image reviews cannot be edited here. Upload the corrected image as a new review.")
        if r["status"] in ("approved", "rejected"): raise HTTPException(400, "This review is already closed")
        text = r["content"]
        if b.apply_accepted:
            dec = json.loads(r["decisions"] or "{}")
            text = engine.apply_fixes(text, json.loads(r["findings"]), {k for k, v in dec.items() if v["decision"] == "accepted"})
        elif b.text is not None: text = b.text
        if not text.strip(): raise HTTPException(400, "Content cannot be empty")
        if len(text) > 30000: raise HTTPException(400, "Content is too long")
        findings, verified, score, ai = analyze_text(c, text, paragraphs=(r["kind"] == "document"))
        c.execute("UPDATE reviews SET content=?, findings=?, verified=?, decisions='{}', score=?, ai_status=?, status='draft', version=version+1, updated=? WHERE id=?",
                  (text, json.dumps(findings), json.dumps(verified), score, ai, now(), rid))
        log(c, rid, u["name"], "revised", f"v{r['version']+1}: score {r['score']} -> {score}. Previous text: {r['content'][:200]}")
        return review_row(c.execute("SELECT * FROM reviews WHERE id=?", (rid,)).fetchone())


@app.post("/api/reviews/{rid}/submit")
def submit(rid: str, u=Depends(need("creator", "manager", "admin"))):
    with conn() as c:
        r = get_review(c, rid, u)
        if r["status"] not in ("draft", "changes_requested"): raise HTTPException(400, "Already submitted")
        findings = json.loads(r["findings"]); dec = json.loads(r["decisions"] or "{}")
        open_high = [f for f in findings if f["severity"] == "high" and f["id"] not in dec]
        c.execute("UPDATE reviews SET status='pending', updated=? WHERE id=?", (now(), rid))
        log(c, rid, u["name"], "submitted", f"{len(open_high)} high-severity flag(s) without a decision")
    return {"status": "pending", "open_high": len(open_high)}


class Comment(BaseModel): text: str


@app.post("/api/reviews/{rid}/comment")
def comment(rid: str, b: Comment, u=Depends(current_user)):
    if not b.text.strip(): raise HTTPException(400, "Empty comment")
    with conn() as c:
        get_review(c, rid, u); log(c, rid, u["name"], "comment", b.text.strip()[:1000])
    return {"ok": True}


class Verdict(BaseModel): verdict: str; note: str = ""


@app.post("/api/reviews/{rid}/verdict")
def verdict(rid: str, b: Verdict, u=Depends(need("manager", "admin"))):
    m = {"approved": "approved", "rejected": "rejected", "changes_requested": "changes_requested"}
    if b.verdict not in m: raise HTTPException(400, "Unknown verdict")
    with conn() as c:
        r = get_review(c, rid, u)
        if r["status"] != "pending": raise HTTPException(400, "Only submitted reviews can be approved or rejected")
        c.execute("UPDATE reviews SET status=?, updated=? WHERE id=?", (m[b.verdict], now(), rid))
        log(c, rid, u["name"], b.verdict, b.note)
    return {"status": m[b.verdict]}


# ------------------------------------------------------------------ insights (GovernIQ)
def build_insights(c):
    gl = {g["id"]: g for g in load_guidelines(c, False)}
    stats = {}; total_flags = accepted = dismissed = 0; cat = {}; examples = {}
    rows = c.execute("SELECT findings, decisions, score FROM reviews").fetchall()
    scores = [r["score"] for r in rows]
    for r in rows:
        dec = json.loads(r["decisions"] or "{}")
        for f in json.loads(r["findings"] or "[]"):
            s = stats.setdefault(f["guideline_id"], {"flags": 0, "accepted": 0, "dismissed": 0})
            s["flags"] += 1; total_flags += 1; cat[f["category"]] = cat.get(f["category"], 0) + 1
            d = dec.get(f["id"], {}).get("decision")
            if d == "accepted": s["accepted"] += 1; accepted += 1
            if d == "dismissed": s["dismissed"] += 1; dismissed += 1; examples.setdefault(f["guideline_id"], []).append(f["text"][:60])
    table = []
    for gid, s in stats.items():
        decided = s["accepted"] + s["dismissed"]; rate = s["dismissed"] / decided if decided else 0
        unclear = decided >= 3 and rate >= 0.5
        g = gl.get(gid, {"title": gid, "text": ""})
        row = {"guideline_id": gid, "title": g["title"], "text": g["text"], **s, "dismiss_rate": round(rate, 2), "unclear": unclear}
        if unclear:
            ex = ", ".join(f"'{e}'" for e in examples.get(gid, [])[:3])
            row["suggested_wording"] = (f"{g['text']} Add concrete examples. Reviewers often dismissed flags such as {ex}; state clearly whether wording like this is allowed or not, and when an exception applies.")
        table.append(row)
    table.sort(key=lambda r: -r["flags"])
    return {"reviews": len(rows), "flags": total_flags, "accepted": accepted, "dismissed": dismissed,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            "by_category": sorted(cat.items(), key=lambda x: -x[1]), "guidelines": table}


@app.get("/api/insights")
def insights(u=Depends(need("manager", "admin"))):
    with conn() as c: return build_insights(c)


class GuidelineUpdate(BaseModel): guideline_id: str; text: str


@app.post("/api/insights/apply-wording")
def apply_wording(b: GuidelineUpdate, u=Depends(need("admin"))):
    with conn() as c:
        c.execute("UPDATE guidelines SET text=? WHERE id=?", (b.text, b.guideline_id)); log(c, "-", u["name"], "guideline_reworded", b.guideline_id)
    return {"ok": True}


# ------------------------------------------------------------------ Round 3: impact preview + AI-drafted wording
def candidate_change(g, dismissed_texts):
    """A concrete, reversible rule tweak that would silence the flags reviewers keep dismissing. Returns (description, new_data) or (None, None)."""
    d = json.loads(json.dumps(g["data"])); k = g["key"]; low = {t.lower().strip() for t in dismissed_texts}
    if k == "tone.hype":
        drop = [p for p in d.get("phrases", {}) if p.lower() in low]
        for p in drop: d["phrases"].pop(p)
        return (f"Stop flagging: {', '.join(repr(p) for p in drop)}", d) if drop else (None, None)
    if k == "terms":
        drop = [p for p in d.get("pairs", []) if p["bad"].lower() in low]
        d["pairs"] = [p for p in d.get("pairs", []) if p not in drop]
        return (f"Stop flagging: {', '.join(repr(p['bad']) for p in drop)}", d) if drop else (None, None)
    if k == "tone.shouting":
        d["max_exclaim"] = d.get("max_exclaim", 1) + 1
        d["max_caps_words"] = d.get("max_caps_words", 1) + 1
        return (f"Allow up to {d['max_exclaim']} exclamation marks and {d['max_caps_words']} capitalised words per post", d)
    if k == "access.readability":
        d["max_words"] = d.get("max_words", 30) + 10
        return (f"Raise the sentence limit to {d['max_words']} words", d)
    return None, None


def simulate(c, g, new_data):
    """Re-run every stored text/document review with the changed rule (rules only) and count what would change."""
    gl = load_guidelines(c); facts = load_facts(c)
    G_old = {x["key"]: x for x in gl}
    G_new = {**G_old, g["key"]: {**g, "data": new_data, "enabled": True}}
    before = after = rem_acc = rem_dis = checked = 0
    for r in c.execute("SELECT content, findings, decisions, kind FROM reviews WHERE kind!='image' OR content!=''").fetchall():
        old = [f for f in json.loads(r["findings"] or "[]") if f["guideline_id"] == g["id"] and f.get("source") == "rules"]
        if not old: continue
        checked += 1
        dec = json.loads(r["decisions"] or "{}")
        new_f, _ = engine.run_rules(r["content"], G_new, facts)
        new_texts = {(f["guideline_id"], f["text"].lower()) for f in new_f}
        for f in old:
            before += 1
            if (f["guideline_id"], f["text"].lower()) in new_texts: after += 1; continue
            d = dec.get(f["id"], {}).get("decision")
            if d == "accepted": rem_acc += 1
            elif d == "dismissed": rem_dis += 1
    return {"reviews_affected": checked, "flags_before": before, "flags_after": after, "removed_total": before - after,
            "removed_that_humans_dismissed": rem_dis, "removed_that_humans_accepted": rem_acc}


@app.get("/api/insights/suggestions")
def suggestions(guideline_id: str, u=Depends(need("manager", "admin"))):
    with conn() as c:
        g = next((x for x in load_guidelines(c, False) if x["id"] == guideline_id), None)
        if not g: raise HTTPException(404, "Guideline not found")
        dismissed = []
        for r in c.execute("SELECT findings, decisions FROM reviews").fetchall():
            dec = json.loads(r["decisions"] or "{}")
            dismissed += [f["text"] for f in json.loads(r["findings"] or "[]") if f["guideline_id"] == guideline_id and dec.get(f["id"], {}).get("decision") == "dismissed"]
        desc, nd = candidate_change(g, dismissed)
        out = {"guideline": {"id": g["id"], "title": g["title"], "text": g["text"]}, "dismissed_examples": sorted(set(dismissed))[:5], "candidate": None}
        if desc:
            out["candidate"] = {"description": desc, "new_data": nd, "impact": simulate(c, g, nd)}
        return out


class DraftIn(BaseModel): guideline_id: str


@app.post("/api/insights/draft-wording")
def draft_wording_ep(b: DraftIn, u=Depends(need("manager", "admin"))):
    with conn() as c:
        g = next((x for x in load_guidelines(c, False) if x["id"] == b.guideline_id), None)
        if not g: raise HTTPException(404, "Guideline not found")
        ex = []
        for r in c.execute("SELECT findings, decisions FROM reviews").fetchall():
            dec = json.loads(r["decisions"] or "{}")
            ex += [f["text"][:60] for f in json.loads(r["findings"] or "[]") if f["guideline_id"] == b.guideline_id and dec.get(f["id"], {}).get("decision") == "dismissed"]
        ex = sorted(set(ex))[:5]
    desc = "Reviewers often dismissed flags on: " + (", ".join(f"'{e}'" for e in ex) or "(no examples yet)")
    text, st = llm.draft_wording(g["text"], desc)
    if text: return {"draft": text, "source": "ai", "status": st}
    fallback = f"{g['text']} Add concrete examples. Reviewers often dismissed flags such as {', '.join(repr(e) for e in ex) or 'borderline wording'}; state clearly whether wording like this is allowed and when an exception applies."
    return {"draft": fallback, "source": "template", "status": st}


class AdoptIn(BaseModel): guideline_id: str; text: str; new_data: Optional[dict] = None


@app.post("/api/insights/adopt")
def adopt(b: AdoptIn, u=Depends(need("admin"))):
    if not b.text.strip(): raise HTTPException(400, "Guideline text cannot be empty")
    with conn() as c:
        if not c.execute("SELECT 1 FROM guidelines WHERE id=?", (b.guideline_id,)).fetchone(): raise HTTPException(404, "Guideline not found")
        c.execute("UPDATE guidelines SET text=? WHERE id=?", (b.text.strip(), b.guideline_id))
        if b.new_data is not None: c.execute("UPDATE guidelines SET data=? WHERE id=?", (json.dumps(b.new_data), b.guideline_id))
        log(c, "-", u["name"], "guideline_adopted_suggestion", f"{b.guideline_id}{' (rule settings changed)' if b.new_data is not None else ''}")
    return {"ok": True}


# ------------------------------------------------------------------ Round 3: brand-book import
def _load_item(r):
    d = dict(r); d["data"] = json.loads(d["data"]); return d


class BookText(BaseModel): text: str; filename: str = "pasted text"


def _import(c, u, text, filename, truncated=False):
    text = text.strip()
    if len(text) < 40: raise HTTPException(400, "The brand book is too short to read. Paste or upload at least a few sentences.")
    ai, st = llm.propose_from_brandbook(text)
    items, mode = brandbook.build(text, ai)
    iid = uuid.uuid4().hex[:8]
    c.execute("INSERT INTO imports VALUES(?,?,?,?,?,?,?)", (iid, filename[:120], mode, st, int(truncated), now(), u["name"]))
    for it in items:
        c.execute("INSERT INTO proposals(import_id,kind,data,excerpt,source,created) VALUES(?,?,?,?,?,?)", (iid, it["kind"], json.dumps(it["data"]), it["excerpt"], it["source"], now()))
    log(c, "-", u["name"], "brandbook_imported", f"{filename}: {len(items)} proposals ({mode})")
    return {"import_id": iid, "mode": mode, "ai_status": st, "count": len(items), "truncated": truncated}


@app.get("/api/brandbook/sample")
def bb_sample(u=Depends(need("admin"))): return {"text": brandbook.SAMPLE_BRANDBOOK, "filename": "sample-brand-book.txt"}


@app.post("/api/brandbook/import")
async def bb_import(text: str = Form(""), file: Optional[UploadFile] = File(None), u=Depends(need("admin"))):
    truncated, fname = False, "pasted text"
    if file is not None and file.filename:
        try: text, _, truncated = docextract.extract_text(file.filename, await file.read())
        except docextract.DocError as e: raise HTTPException(400, str(e))
        fname = file.filename
    with conn() as c: return _import(c, u, text, fname, truncated)


@app.get("/api/proposals")
def list_proposals(status: str = "pending", u=Depends(need("admin"))):
    with conn() as c:
        rows = c.execute("SELECT * FROM proposals WHERE status=? ORDER BY id", (status,)).fetchall()
        imps = [dict(r) for r in c.execute("SELECT * FROM imports ORDER BY created DESC LIMIT 5").fetchall()]
        return {"items": [_load_item(r) for r in rows], "imports": imps}


class ProposalEdit(BaseModel): data: dict


@app.put("/api/proposals/{pid}")
def edit_proposal(pid: int, b: ProposalEdit, u=Depends(need("admin"))):
    with conn() as c:
        r = c.execute("SELECT * FROM proposals WHERE id=? AND status='pending'", (pid,)).fetchone()
        if not r: raise HTTPException(404, "Proposal not found or already decided")
        c.execute("UPDATE proposals SET data=? WHERE id=?", (json.dumps(b.data), pid))
    return {"ok": True}


def apply_proposal(c, r, u):
    d = json.loads(r["data"]); kind = r["kind"]
    if kind == "term":
        g = c.execute("SELECT * FROM guidelines WHERE key='terms'").fetchone()
        data = json.loads(g["data"]) if g else {"pairs": []}
        bad, good = str(d.get("bad", "")).strip().lower(), str(d.get("good", "")).strip()
        if not bad or not good: raise HTTPException(400, "A preferred term needs both the word to avoid and the word to use")
        data["pairs"] = [p for p in data.get("pairs", []) if p["bad"].lower() != bad] + [{"bad": bad, "good": good}]
        if g: c.execute("UPDATE guidelines SET data=? WHERE id=?", (json.dumps(data), g["id"]))
        else: c.execute("INSERT INTO guidelines VALUES('G2.1','terms','Preferred terminology',?,?,1)", ("Use our preferred terms.", json.dumps(data)))
    elif kind == "hype":
        g = c.execute("SELECT * FROM guidelines WHERE key='tone.hype'").fetchone()
        ph = str(d.get("phrase", "")).strip().lower()
        if not ph: raise HTTPException(400, "A pressure phrase cannot be empty")
        data = json.loads(g["data"]) if g else {"phrases": {}}
        data.setdefault("phrases", {})[ph] = str(d.get("alternative") or "take a look")
        if g: c.execute("UPDATE guidelines SET data=? WHERE id=?", (json.dumps(data), g["id"]))
        else: c.execute("INSERT INTO guidelines VALUES('G1.2','tone.hype','No pushy sales language',?,?,1)", ("Invite, don't pressure.", json.dumps(data)))
    elif kind == "fact":
        kws = d.get("keywords") or []
        if isinstance(kws, str): kws = kws.split(",")
        kws = [k.strip().lower() for k in kws if k.strip()]
        if not kws or not str(d.get("statement", "")).strip(): raise HTTPException(400, "A fact needs a statement and at least one keyword")
        fid = "F" + uuid.uuid4().hex[:5]
        unit = d.get("unit") or ""
        val = d.get("value")
        c.execute("INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,1)", (fid, d.get("topic") or "Fact", json.dumps(kws), d["statement"], float(val) if val not in (None, "") else None,
                                                                   unit if unit in brandbook.VALID_UNITS else "", d.get("source") or "Imported brand book", d.get("expires") or None, "[]"))
    elif kind == "guideline":
        if not str(d.get("text", "")).strip(): raise HTTPException(400, "A guideline needs text")
        n = c.execute("SELECT COUNT(*) FROM guidelines WHERE key LIKE 'tone.custom%'").fetchone()[0] + 1
        gid = "G9." + uuid.uuid4().hex[:5]
        c.execute("INSERT INTO guidelines VALUES(?,?,?,?,?,1)", (gid, f"tone.custom{n}_{gid}", str(d.get("title") or "Imported guideline")[:100], d["text"], "{}"))
    c.execute("UPDATE proposals SET status='approved', decided_by=? WHERE id=?", (u["name"], r["id"]))
    log(c, "-", u["name"], "proposal_approved", f"{kind}: {json.dumps(d)[:120]}")


@app.post("/api/proposals/{pid}/approve")
def approve(pid: int, u=Depends(need("admin"))):
    with conn() as c:
        r = c.execute("SELECT * FROM proposals WHERE id=? AND status='pending'", (pid,)).fetchone()
        if not r: raise HTTPException(404, "Proposal not found or already decided")
        apply_proposal(c, r, u)
    return {"ok": True}


@app.post("/api/proposals/{pid}/reject")
def reject(pid: int, u=Depends(need("admin"))):
    with conn() as c:
        r = c.execute("SELECT * FROM proposals WHERE id=? AND status='pending'", (pid,)).fetchone()
        if not r: raise HTTPException(404, "Proposal not found or already decided")
        c.execute("UPDATE proposals SET status='rejected', decided_by=? WHERE id=?", (u["name"], pid)); log(c, "-", u["name"], "proposal_rejected", r["kind"])
    return {"ok": True}


@app.post("/api/proposals/approve-all")
def approve_all(u=Depends(need("admin"))):
    n = bad = 0
    with conn() as c:
        for r in c.execute("SELECT * FROM proposals WHERE status='pending' ORDER BY id").fetchall():
            try: apply_proposal(c, r, u); n += 1
            except HTTPException: bad += 1
    return {"approved": n, "needs_edit": bad}


# ------------------------------------------------------------------ Round 3: accuracy benchmark
@app.post("/api/benchmark/run")
def run_benchmark(u=Depends(need("manager", "admin"))):
    with conn() as c:
        res = benchmark.evaluate(load_guidelines(c, False), load_facts(c))
        c.execute("INSERT INTO benchmark_runs(ts,result,by_user) VALUES(?,?,?)", (now(), json.dumps(res), u["name"]))
        log(c, "-", u["name"], "benchmark_run", f"exact {res['posts_exact']}/{res['posts']}")
    return {**res, "ts": now()}


@app.get("/api/benchmark")
def benchmark_history(u=Depends(need("manager", "admin"))):
    with conn() as c:
        rows = c.execute("SELECT * FROM benchmark_runs ORDER BY id DESC LIMIT 8").fetchall()
    out = []
    for r in rows:
        x = json.loads(r["result"]); out.append({"ts": r["ts"], "by": r["by_user"], "posts_exact": x["posts_exact"], "posts": x["posts"], "overall": x["overall"]})
    return {"history": out, "dataset_size": len(benchmark.DATASET)}


# ------------------------------------------------------------------ friendly errors
@app.exception_handler(RequestValidationError)
async def bad_input(request, exc):
    return JSONResponse(status_code=400, content={"detail": "Some required information is missing or in the wrong format. Please check the form and try again."})


@app.exception_handler(Exception)
async def unexpected(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side. Your data is safe; please try again."})


# ------------------------------------------------------------------ demo data, samples, about
def seed_demo(c):
    """Creates synthetic reviews with simulated reviewer decisions so the insights dashboard has data. Always labelled [Demo]."""
    creator = c.execute("SELECT id, name FROM users WHERE username='creator'").fetchone()
    for i, s in enumerate(seed.SAMPLES * 2):
        findings, verified, score, ai = analyze_text(c, s["text"], use_ai=False)
        dec = {}
        for f in findings:
            key = next((g["key"] for g in load_guidelines(c, False) if g["id"] == f["guideline_id"]), "")
            reject = key in ("tone.hype", "access.readability") or (key == "tone.shouting" and f["severity"] == "low" and i % 2 == 0)
            dec[f["id"]] = {"decision": "dismissed" if reject else "accepted", "by": "Rahul (Brand Manager)", "role": "manager", "ts": now(), "note": "synthetic demo decision"}
        status = ["approved", "pending", "changes_requested", "approved"][i % 4]
        rid = uuid.uuid4().hex[:10]
        insert_review(c, id=rid, author_id=creator["id"], title="[Demo] " + s["title"], channel=s["channel"], content=s["text"], status=status, findings=findings, verified=verified, decisions=dec, score=score, demo=1)
        log(c, rid, creator["name"], "created", "synthetic demo data")
        if status != "pending" and status != "draft": log(c, rid, "Rahul (Brand Manager)", status, "synthetic demo decision")


@app.post("/api/admin/seed-demo")
def seed_demo_ep(u=Depends(need("admin"))):
    with conn() as c: seed_demo(c)
    return {"ok": True}


@app.get("/api/samples")
def samples(u=Depends(current_user)): return seed.SAMPLES


@app.get("/api/about")
def about():
    p = llm.provider()
    return {"name": "BrandCouncil", "ai_provider": p, "ai_model": (llm.GEMINI_MODEL if p == "gemini" else llm.ANTHROPIC_MODEL if p == "anthropic" else None),
            "ai_enabled": bool(p), "libraries": ["FastAPI", "SQLite", "Pillow", "pypdf", "Python standard library"],
            "note": "Rule-based checks run locally. When an AI key is configured, three specialist agents add judgement-based findings; confidential terms, emails and phone numbers are masked before any external call."}


@app.get("/api/ai-test")
def ai_test(u=Depends(need("admin"))): return llm.diagnose()


@app.get("/api/health")
def health(): return {"ok": True}


init_db()
with conn() as _c:
    if not _c.execute("SELECT 1 FROM reviews").fetchone(): seed_demo(_c)

if os.path.isdir(FRONTEND):
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
