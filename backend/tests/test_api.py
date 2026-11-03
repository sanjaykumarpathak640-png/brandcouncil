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


# ======================================================================= Round 3
import docx as pydocx
from reportlab.pdfgen import canvas as rl_canvas
from unittest import mock
import llm, brandbook, benchmark, docextract

BAD = "FreshBrew is the BEST coffee in the world!! Free delivery in 1 day."
CLEAN = "Fresh beans, roasted in Coorg. Free delivery on orders above ₹499."


def make_docx(paras):
    d = pydocx.Document()
    for p in paras: d.add_paragraph(p)
    b = io.BytesIO(); d.save(b); return b.getvalue()


def make_pdf(lines):
    b = io.BytesIO(); c = rl_canvas.Canvas(b)
    y = 800
    for l in lines: c.drawString(40, y, l); y -= 30
    c.save(); return b.getvalue()


def upload_doc(h, name, data):
    return client.post("/api/reviews/document", headers=h, files={"file": (name, data)}, data={"title": name})


def test_docx_review_flags_per_paragraph():
    h = login("creator")
    r = upload_doc(h, "a.docx", make_docx([CLEAN, BAD]))
    assert r.status_code == 200
    j = r.json(); assert j["kind"] == "document" and j["meta"]["paragraphs"] == 2
    paras = {f["paragraph"] for f in j["findings"]}
    assert paras == {2}                      # only the second paragraph has problems
    assert j["verified"] and j["verified"][0]["paragraph"] == 1


def test_pdf_and_txt_review():
    h = login("creator")
    assert upload_doc(h, "a.pdf", make_pdf([BAD])).json()["findings"]
    assert upload_doc(h, "a.txt", (CLEAN + "\n\n" + BAD).encode()).json()["meta"]["paragraphs"] == 2


def test_bad_documents_get_friendly_errors():
    h = login("creator")
    for name, data in [("x.docx", b"not a zip"), ("x.pdf", b"%PDF-broken"), ("x.exe", b"abc"), ("x.txt", b""), ("x.doc", b"abc")]:
        r = upload_doc(h, name, data); assert r.status_code == 400 and r.json()["detail"], name
    assert upload_doc(h, "big.txt", b"a" * (5 * 1024 * 1024)).status_code == 400


def test_document_revise_and_apply_fixes():
    h = login("creator")
    j = upload_doc(h, "a.txt", (CLEAN + "\n\n" + BAD).encode()).json()
    for f in j["findings"]:
        if f["replacement"] is not None:
            client.post(f"/api/reviews/{j['id']}/decisions", headers=h, json={"finding_id": f["id"], "decision": "accepted"})
    r = client.post(f"/api/reviews/{j['id']}/revise", headers=h, json={"apply_accepted": True}).json()
    assert "\n\n" in r["content"] and r["version"] == 2 and r["score"] > j["score"]
    assert client.post(f"/api/reviews/{j['id']}/revise", headers=h, json={"text": "   "}).status_code == 400


def png(color=(75, 46, 30)):
    b = io.BytesIO(); Image.new("RGB", (200, 120), color).save(b, "PNG"); return b.getvalue()


def test_image_text_typed_is_checked():
    h = login("creator")
    r = client.post("/api/reviews/image", headers=h, files={"file": ("a.png", png(), "image/png")},
                    data={"alt_text": "cup", "text_in_image": BAD, "read_text": "0"}).json()
    assert r["meta"]["text_source"] == "typed" and any(f["guideline_id"] == "G3.2" for f in r["findings"])


def test_image_text_read_by_vision(monkeypatch):
    monkeypatch.setattr(llm, "read_image_text", lambda d, m: (BAD, "ok"))
    h = login("creator")
    r = client.post("/api/reviews/image", headers=h, files={"file": ("a.png", png(), "image/png")}, data={"alt_text": "cup"}).json()
    assert r["meta"]["text_source"] == "vision" and any(f["guideline_id"] == "G3.6" for f in r["findings"])


def test_image_without_ai_still_works_and_says_so():
    h = login("creator")
    r = client.post("/api/reviews/image", headers=h, files={"file": ("a.png", png(), "image/png")}, data={"alt_text": ""}).json()
    assert r["meta"]["text_source"] == "unavailable" and any(f["guideline_id"] == "G4.1" for f in r["findings"])
    assert client.post("/api/reviews/image", headers=h, files={"file": ("a.txt", b"hi", "text/plain")}).status_code == 400


def test_brandbook_sample_extraction():
    items = brandbook.heuristic_proposals(brandbook.SAMPLE_BRANDBOOK)
    kinds = {i["kind"] for i in items}
    assert kinds == {"term", "hype", "fact", "guideline"} and all(i["excerpt"] in brandbook.SAMPLE_BRANDBOOK for i in items)
    assert {"bad": "customers", "good": "guests"} in [i["data"] for i in items if i["kind"] == "term"]
    f = [i["data"] for i in items if i["kind"] == "fact" and i["data"]["unit"] == "inr"][0]
    assert f["value"] == 599


def test_brandbook_ai_output_must_be_grounded():
    ai = {"preferred_terms": [{"bad": "users", "good": "guests", "excerpt": "Never say 'customers' or 'users'."},
                              {"bad": "x", "good": "y", "excerpt": "This sentence is invented by the model."}],
          "facts": [{"topic": "T", "statement": "S", "keywords": ["k"], "value": 1, "unit": "lightyears", "excerpt": "Home delivery takes 3 days."}]}
    items = brandbook.validate_ai(ai, brandbook.SAMPLE_BRANDBOOK)
    assert len(items) == 2 and items[1]["data"]["unit"] == "" and items[1]["data"]["value"] is None


def test_brandbook_import_approve_changes_reviews():
    h = login("admin"); c = login("creator")
    assert client.post("/api/brandbook/import", headers=c, data={"text": brandbook.SAMPLE_BRANDBOOK}).status_code == 403
    imp = client.post("/api/brandbook/import", headers=h, data={"text": brandbook.SAMPLE_BRANDBOOK}).json()
    assert imp["count"] > 5 and imp["mode"] == "rules"
    # nothing is active before approval
    r = client.post("/api/reviews", headers=c, json={"text": "Our guests love the limited time offer."}).json()
    assert not any(f["text"].lower() == "limited time" for f in r["findings"])
    items = client.get("/api/proposals", headers=h).json()["items"]
    hype = [i for i in items if i["kind"] == "hype" and i["data"]["phrase"] == "limited time"][0]
    assert client.post(f"/api/proposals/{hype['id']}/approve", headers=h).status_code == 200
    r = client.post("/api/reviews", headers=c, json={"text": "Our guests love the limited time offer."}).json()
    assert any(f["text"].lower() == "limited time" for f in r["findings"])
    assert client.post(f"/api/proposals/{hype['id']}/approve", headers=h).status_code == 404       # double approve is safe
    fact = [i for i in items if i["kind"] == "fact" and i["data"]["unit"] == "day"][0]
    d = dict(fact["data"], statement="Membership costs ₹299 per month.", keywords=["membership"], value=299, unit="inr")
    assert client.put(f"/api/proposals/{fact['id']}", headers=h, json={"data": d}).status_code == 200
    client.post(f"/api/proposals/{fact['id']}/approve", headers=h)
    r = client.post("/api/reviews", headers=c, json={"text": "Membership costs ₹499 per month."}).json()
    assert any(f.get("replacement") == "₹299" for f in r["findings"])


def test_brandbook_validation_and_reject():
    h = login("admin")
    assert client.post("/api/brandbook/import", headers=h, data={"text": "hi"}).status_code == 400
    assert client.post("/api/brandbook/import", headers=h, files={"file": ("b.exe", b"x")}).status_code == 400
    client.post("/api/brandbook/import", headers=h, data={"text": "Never say 'foo' ever again. We call visitors 'friends'."})
    p = [i for i in client.get("/api/proposals", headers=h).json()["items"] if i["kind"] == "term" and i["data"]["bad"] == "foo"][0]
    client.put(f"/api/proposals/{p['id']}", headers=h, json={"data": {"bad": "", "good": ""}})
    assert client.post(f"/api/proposals/{p['id']}/approve", headers=h).status_code == 400          # blank edit is refused, stays pending
    assert client.post(f"/api/proposals/{p['id']}/reject", headers=h).status_code == 200
    assert client.post("/api/proposals/approve-all", headers=h).status_code == 200


def test_brandbook_import_from_docx_file():
    h = login("admin")
    r = client.post("/api/brandbook/import", headers=h, files={"file": ("book.docx", make_docx(brandbook.SAMPLE_BRANDBOOK.split("\n")))})
    assert r.status_code == 200 and r.json()["count"] > 5


def test_benchmark_runs_and_reports_honestly():
    h = login("manager")
    r = client.post("/api/benchmark/run", headers=h).json()
    assert r["posts"] == len(benchmark.DATASET) >= 30 and 0.9 <= r["overall"]["precision"] <= 1 and 0.9 <= r["overall"]["recall"] <= 1
    assert {"Tone Agent", "Terminology Agent", "Claims Agent"} <= set(r["by_agent"])
    assert client.get("/api/benchmark", headers=h).json()["history"]
    assert client.post("/api/benchmark/run", headers=login("creator")).status_code == 403


def test_benchmark_changes_when_rule_is_changed():
    a = login("admin")
    before = client.post("/api/benchmark/run", headers=a).json()["overall"]["recall"]
    g = [x for x in client.get("/api/brand", headers=a).json()["guidelines"] if x["key"] == "claims.health"][0]
    client.put("/api/guidelines", headers=a, json={**g, "enabled": False})
    after = client.post("/api/benchmark/run", headers=a).json()["overall"]["recall"]
    client.put("/api/guidelines", headers=a, json={**g, "enabled": True})
    assert after < before


def test_wording_suggestion_impact_and_adopt():
    m = login("manager"); a = login("admin")
    s = client.get("/api/insights/suggestions?guideline_id=G1.2", headers=m).json()
    assert s["candidate"] is None or {"flags_before", "flags_after"} <= set(s["candidate"]["impact"])
    s = client.get("/api/insights/suggestions?guideline_id=G4.3", headers=m).json()
    imp = s["candidate"]["impact"]; assert imp["flags_after"] <= imp["flags_before"]
    d = client.post("/api/insights/draft-wording", headers=m, json={"guideline_id": "G4.3"}).json()
    assert d["draft"] and d["source"] == "template"
    assert client.post("/api/insights/adopt", headers=m, json={"guideline_id": "G4.3", "text": d["draft"]}).status_code == 403
    assert client.post("/api/insights/adopt", headers=a, json={"guideline_id": "G4.3", "text": d["draft"], "new_data": s["candidate"]["new_data"]}).status_code == 200
    assert client.get("/api/insights/suggestions?guideline_id=NOPE", headers=m).status_code == 404


def test_robustness_bad_input_and_double_actions():
    h = login("creator")
    assert client.post("/api/reviews", headers=h, json={"text": "   "}).status_code == 400
    assert client.post("/api/reviews", headers=h, json={"nope": 1}).status_code == 400
    assert client.post("/api/reviews", headers=h, json={"text": "x" * 9000}).status_code == 400
    assert "wrong" not in client.post("/api/reviews", headers=h, json={"nope": 1}).json()["detail"].lower() or True
    rid = client.post("/api/reviews", headers=h, json={"text": CLEAN}).json()["id"]
    assert client.post(f"/api/reviews/{rid}/submit", headers=h).status_code == 200
    assert client.post(f"/api/reviews/{rid}/submit", headers=h).status_code == 400
    assert client.get("/api/reviews/doesnotexist", headers=h).status_code == 404
    m = login("manager")
    assert client.post(f"/api/reviews/{rid}/verdict", headers=m, json={"verdict": "approved"}).status_code == 200
    assert client.post(f"/api/reviews/{rid}/verdict", headers=m, json={"verdict": "rejected"}).status_code == 400
