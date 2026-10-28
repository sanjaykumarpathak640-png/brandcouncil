import os, io, sys, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fastapi.testclient import TestClient
from PIL import Image
import app as appmod, engine, seed

client = TestClient(appmod.app)


def login(u):
    r = client.post("/api/login", json={"username": u, "password": "demo123"}); assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_login_rejects_wrong_password():
    assert client.post("/api/login", json={"username": "creator", "password": "nope"}).status_code == 401


def test_requires_auth():
    assert client.get("/api/reviews").status_code == 401


def test_intern_post_is_flagged_with_citations():
    h = login("creator")
    r = client.post("/api/reviews", headers=h, json={"title": "t", "channel": "Instagram", "text": seed.SAMPLES[0]["text"]}).json()
    kinds = {(f["guideline_id"]) for f in r["findings"]}
    assert {"G3.2", "G3.4", "G3.6", "G2.1", "G1.1"} <= kinds
    assert all(f["guideline_quote"] and f["reason"] for f in r["findings"])
    contra = [f for f in r["findings"] if f["fact_id"] == "F1"][0]
    assert contra["replacement"] == "2 days" and contra["fact_source"]


def test_clean_post_scores_100():
    h = login("creator")
    r = client.post("/api/reviews", headers=h, json={"text": seed.SAMPLES[2]["text"]}).json()
    assert r["score"] == 100 and r["findings"] == [] and len(r["verified"]) >= 1


def test_expired_fact_is_outdated():
    h = login("creator")
    r = client.post("/api/reviews", headers=h, json={"text": "Diwali offer: 20% off all beans."}).json()
    assert any(f["fact_id"] == "F5" and f["severity"] == "high" for f in r["findings"])


def test_full_workflow_and_roles():
    c, m = login("creator"), login("manager")
    r = client.post("/api/reviews", headers=c, json={"text": "Our users love us!!"}).json()
    rid = r["id"]
    for f in r["findings"]:
        assert client.post(f"/api/reviews/{rid}/decisions", headers=c, json={"finding_id": f["id"], "decision": "accepted"}).status_code == 200
    r2 = client.post(f"/api/reviews/{rid}/revise", headers=c, json={"apply_accepted": True}).json()
    assert r2["content"] == "Our coffee lovers love us!" and r2["score"] == 100 and r2["version"] == 2
    assert client.post(f"/api/reviews/{rid}/submit", headers=c).status_code == 200
    assert client.post(f"/api/reviews/{rid}/verdict", headers=c, json={"verdict": "approved"}).status_code == 403   # creator cannot approve
    assert client.post(f"/api/reviews/{rid}/comment", headers=m, json={"text": "Looks good"}).status_code == 200
    assert client.post(f"/api/reviews/{rid}/verdict", headers=m, json={"verdict": "approved", "note": "ok"}).json()["status"] == "approved"
    d = client.get(f"/api/reviews/{rid}", headers=m).json()
    assert d["status"] == "approved" and [e["action"] for e in d["events"]][-1] == "approved"


def test_creator_cannot_see_others_and_cannot_read_insights():
    c, a = login("creator"), login("admin")
    assert client.get("/api/insights", headers=c).status_code == 403
    rid = client.post("/api/reviews", headers=a, json={"text": "hello there"}).json()["id"]
    assert client.get(f"/api/reviews/{rid}", headers=c).status_code == 403


def test_admin_rule_changes_affect_review():
    a, c = login("admin"), login("creator")
    g = [x for x in client.get("/api/brand", headers=a).json()["guidelines"] if x["key"] == "terms"][0]
    g["data"]["pairs"].append({"bad": "folks", "good": "coffee lovers"})
    assert client.put("/api/guidelines", headers=c, json=g).status_code == 403
    assert client.put("/api/guidelines", headers=a, json=g).status_code == 200
    r = client.post("/api/reviews", headers=c, json={"text": "Hello folks."}).json()
    assert any(f["text"].lower() == "folks" for f in r["findings"])


def test_image_review():
    c = login("creator")
    img = Image.new("RGB", (200, 200), (0, 200, 0)); buf = io.BytesIO(); img.save(buf, "PNG")
    r = client.post("/api/reviews/image", headers=c, data={"title": "img", "alt_text": ""}, files={"file": ("a.png", buf.getvalue(), "image/png")}).json()
    ids = {f["guideline_id"] for f in r["findings"]}
    assert "G4.1" in ids and "G5.1" in ids          # missing alt-text and off-palette green
    buf2 = io.BytesIO(); Image.new("RGB", (200, 200), (75, 46, 30)).save(buf2, "PNG")
    r2 = client.post("/api/reviews/image", headers=c, data={"alt_text": "Espresso brown card"}, files={"file": ("b.png", buf2.getvalue(), "image/png")}).json()
    assert r2["findings"] == []
    bad = client.post("/api/reviews/image", headers=c, data={}, files={"file": ("x.txt", b"hi", "text/plain")})
    assert bad.status_code == 400


def test_insights_flags_unclear_guideline():
    a = login("admin")
    d = client.get("/api/insights", headers=a).json()
    assert d["reviews"] >= 10 and d["flags"] > 0
    unclear = [g for g in d["guidelines"] if g["unclear"]]
    assert unclear and unclear[0]["suggested_wording"]


def test_masking_hides_confidential_terms():
    import llm
    m, mp = llm.mask("Email me at a@b.com about Project Mocha, call +91 98765 43210", ["Project Mocha"])
    assert "Project Mocha" not in m and "a@b.com" not in m and "98765" not in m
    assert llm.unmask(m, mp) == "Email me at a@b.com about Project Mocha, call +91 98765 43210"


def test_ai_findings_are_validated(monkeypatch):
    import llm
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    good = '[{"text":"fantastic beans","severity":"low","guideline_id":"G1.2","reason":"salesy","suggestion":"lovely beans","confidence":0.8},' \
           '{"text":"not in text","severity":"high","guideline_id":"G1.2","reason":"x"},' \
           '{"text":"fantastic beans","severity":"high","guideline_id":"G9.9","reason":"fake guideline"}]'
    monkeypatch.setattr(llm, "call_model", lambda s, u: good)
    with appmod.conn() as c:
        gl = appmod.load_guidelines(c); facts = appmod.load_facts(c)
    f, status = llm.ai_findings("Try our fantastic beans today", gl, facts, [])
    tone = [x for x in f if x["agent"] == "Tone Agent"]
    assert status == "ok" and len(tone) == 1 and tone[0]["span"] == [8, 23]   # invented text and fake guideline dropped
    monkeypatch.setattr(llm, "call_model", lambda s, u: (_ for _ in ()).throw(RuntimeError("boom")))
    f, status = llm.ai_findings("Try our fantastic beans today", gl, facts, [])
    assert f == [] and status.startswith("error")


def test_contradicted_sentence_is_not_listed_as_verified():
    h = login("creator")
    r = client.post("/api/reviews", headers=h, json={"text": "Free delivery in 1 day."}).json()
    assert any(f["fact_id"] == "F1" for f in r["findings"])
    assert r["verified"] == []
    r2 = client.post("/api/reviews", headers=h, json={"text": "Free delivery in 2 days."}).json()
    assert r2["findings"] == [] and len(r2["verified"]) >= 1
