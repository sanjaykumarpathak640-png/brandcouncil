"""BrandCouncil API + static frontend (single deployable service)."""
import os, json, time, secrets, hashlib, sqlite3, datetime, uuid
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form, Depends
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import engine, llm, seed, imagecheck

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(HERE, "data"))
os.makedirs(os.path.join(DATA_DIR, "uploads"), exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "brandcouncil.db")
FRONTEND = os.path.join(os.path.dirname(HERE), "frontend")
MAX_IMAGE = 5 * 1024 * 1024

app = FastAPI(title="BrandCouncil", version="2.0")


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
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, review_id TEXT, user_name TEXT, action TEXT, note TEXT, ts TEXT);
"""


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
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
def analyze_text(c, text, use_ai=True):
    gl = load_guidelines(c); facts = load_facts(c)
    G = {g["key"]: g for g in gl}
    rule_findings, verified = engine.run_rules(text, G, facts)
    ai_f, ai_status = (llm.ai_findings(text, gl, facts, conf_terms(c)) if use_ai else ([], "off"))
    findings, score, counts = engine.coordinate(rule_findings + [{"id": "x", **f} for f in ai_f])
    return findings, verified, score, ai_status


def analyze_image_bytes(c, data, alt):
    G = {g["key"]: g for g in load_guidelines(c)}
    items, meta = imagecheck.analyze_image(data, alt, G)
    b = engine.Builder("")
    for it in items:
        b.add(it["g"], None, None, it["reason"], it["suggestion"], None, it["severity"], confidence=it["confidence"], text=it["text"])
    return b.items, meta


def review_row(r, full=True):
    d = dict(r)
    for k in ("findings", "verified", "decisions"): d[k] = json.loads(d.get(k) or ("{}" if k == "decisions" else "[]"))
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
        c.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,1,?,?)",
                  (rid, u["id"], b.title[:120], b.channel[:40], "text", b.text, None, None, "draft", json.dumps(findings), json.dumps(verified), "{}", score, ai, now(), now()))
        log(c, rid, u["name"], "created", f"{len(findings)} flags, score {score}, ai={ai}")
        return review_row(c.execute("SELECT * FROM reviews WHERE id=?", (rid,)).fetchone())


@app.post("/api/reviews/image")
async def create_image_review(title: str = Form("Image post"), channel: str = Form("Instagram"), alt_text: str = Form(""), caption: str = Form(""),
                              file: UploadFile = File(...), u=Depends(need("creator", "manager", "admin"))):
    data = await file.read()
    if len(data) > MAX_IMAGE: raise HTTPException(400, "Image is larger than 5 MB")
    if not (file.content_type or "").startswith("image/"): raise HTTPException(400, "Please upload an image file (PNG or JPG)")
    with conn() as c:
        try: img_f, meta = analyze_image_bytes(c, data, alt_text)
        except Exception: raise HTTPException(400, "Could not read this image file")
        txt_f, verified, _, ai = analyze_text(c, caption) if caption.strip() else ([], [], 100, "off")
        findings, score, counts = engine.coordinate(img_f + txt_f)
        rid = uuid.uuid4().hex[:10]
        fname = f"{rid}.img"
        with open(os.path.join(DATA_DIR, "uploads", fname), "wb") as fh: fh.write(data)
        c.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,1,?,?)",
                  (rid, u["id"], title[:120], channel[:40], "image", caption, fname, alt_text, "draft", json.dumps(findings), json.dumps(verified), "{}", score, ai, now(), now()))
        log(c, rid, u["name"], "created", f"image, {len(findings)} flags, score {score}")
        r = review_row(c.execute("SELECT * FROM reviews WHERE id=?", (rid,)).fetchone()); r["image_meta"] = meta
        return r


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
        if r["kind"] != "text": raise HTTPException(400, "Only text posts can be revised here")
        if r["status"] in ("approved", "rejected"): raise HTTPException(400, "This review is already closed")
        text = r["content"]
        if b.apply_accepted:
            dec = json.loads(r["decisions"] or "{}")
            text = engine.apply_fixes(text, json.loads(r["findings"]), {k for k, v in dec.items() if v["decision"] == "accepted"})
        elif b.text is not None: text = b.text
        findings, verified, score, ai = analyze_text(c, text)
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
        c.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,?,?)",
                  (rid, creator["id"], "[Demo] " + s["title"], s["channel"], "text", s["text"], None, None, status, json.dumps(findings), json.dumps(verified), json.dumps(dec), score, "off", now(), now()))
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
            "ai_enabled": bool(p), "libraries": ["FastAPI", "SQLite", "Pillow", "Python standard library"],
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
