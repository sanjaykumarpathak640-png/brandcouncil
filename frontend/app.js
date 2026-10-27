"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const main = $("#main");
let token = sessionStorage.getItem("bc_token"), me = null;
const STATUS = { draft: "Draft", pending: "Waiting for approval", approved: "Approved", rejected: "Rejected", changes_requested: "Changes requested" };

function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 3200); }
async function api(path, opts = {}) {
  const h = { ...(opts.headers || {}) }; if (token) h.Authorization = "Bearer " + token;
  if (opts.json !== undefined) { h["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const r = await fetch("/api" + path, { method: opts.method || (opts.body ? "POST" : "GET"), headers: h, body: opts.body });
  let data = null; try { data = await r.json(); } catch (e) { }
  if (!r.ok) { if (r.status === 401 && token) { logout(); } throw new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : "Invalid input") : "Request failed"); }
  return data;
}
const wrap = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message); } };

// ---------------------------------------------------------------- auth
async function start() {
  if (token) { try { me = await api("/me"); } catch (e) { token = null; } }
  if (!me) return loginView();
  $("#top").hidden = false; $("#whoami").textContent = `${me.name}`;
  nav(); route();
}
function logout() { sessionStorage.removeItem("bc_token"); token = null; me = null; $("#top").hidden = true; loginView(); }
$("#logout").onclick = logout;

function loginView() {
  main.innerHTML = `<div class="card login"><h1>BrandCouncil</h1>
  <p class="sub">A council of AI and rule-based reviewers that checks content against your brand rules <b>before</b> it is published. Humans make every final decision.</p>
  <h3>Try it in one click (demo accounts)</h3>
  <div class="demo">
    <button data-u="creator"><b>Content creator</b> - paste a post, see explained flags, fix and submit</button>
    <button data-u="manager"><b>Brand manager</b> - review submitted posts, comment, approve, see insights</button>
    <button data-u="admin"><b>Brand admin</b> - edit guidelines, approved facts, privacy settings</button></div>
  <details><summary>Sign in with username and password</summary>
    <label for="u">Username</label><input id="u" autocomplete="username"><label for="p">Password</label><input id="p" type="password" autocomplete="current-password">
    <p class="row"><button id="go">Sign in</button></p></details>
  <p class="muted">Demo password for all three accounts: <code>demo123</code>. All data in this demo is synthetic (fictional brand "FreshBrew").</p></div>`;
  const doLogin = wrap(async (u, p) => { const r = await api("/login", { json: { username: u, password: p } }); token = r.token; sessionStorage.setItem("bc_token", token); location.hash = "#/new"; await start(); });
  main.querySelectorAll(".demo button").forEach(b => b.onclick = () => doLogin(b.dataset.u, "demo123"));
  $("#go").onclick = () => doLogin($("#u").value, $("#p").value);
}

function nav() {
  const items = [["new", "New review"], ["queue", me.role === "creator" ? "My reviews" : "Review queue"]];
  if (me.role !== "creator") items.push(["insights", "Insights"]);
  if (me.role === "admin") items.push(["brand", "Brand rules"]);
  items.push(["about", "About & AI use"]);
  $("#nav").innerHTML = items.map(([k, l]) => `<button data-k="${k}">${l}</button>`).join("");
  $("#nav").querySelectorAll("button").forEach(b => b.onclick = () => location.hash = "#/" + b.dataset.k);
}
window.addEventListener("hashchange", () => me && route());
function route() {
  const [, page, arg] = (location.hash || "#/new").split("/");
  $("#nav").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.k === page));
  const views = { new: newView, queue: queueView, review: () => reviewView(arg), insights: insightsView, brand: brandView, about: aboutView };
  (views[page] || newView)().catch(e => toast(e.message));
}

// ---------------------------------------------------------------- new review
async function newView() {
  const samples = await api("/samples");
  main.innerHTML = `<h1>Check content before it goes out</h1><p class="sub">Paste a post or upload an image. The council checks it against your brand guidelines and approved facts and explains every flag.</p>
  <div class="grid g2"><div class="card"><h2>Text post</h2>
    <label for="t1">Title</label><input id="t1" value="Instagram post">
    <label for="ch">Channel</label><select id="ch"><option>Instagram</option><option>Facebook</option><option>LinkedIn</option><option>Twitter</option><option>Website</option><option>Newsletter</option></select>
    <label for="tx">Content</label><textarea id="tx" placeholder="Paste your draft here..."></textarea>
    <div class="row"><select id="sm" style="width:auto;max-width:60%"><option value="">Load a sample post...</option>${samples.map((s, i) => `<option value="${i}">${esc(s.title)}</option>`).join("")}</select><span class="sp"></span><button id="runT">Check with the council</button></div></div>
  <div class="card"><h2>Image post</h2>
    <label for="t2">Title</label><input id="t2" value="Image post">
    <label for="im">Image (PNG or JPG, max 5 MB)</label><input id="im" type="file" accept="image/*">
    <label for="alt">Alt-text (description for screen readers)</label><input id="alt" placeholder="e.g. Latte on a wooden table">
    <label for="cap">Caption (optional, checked as text)</label><textarea id="cap" style="min-height:70px"></textarea>
    <div class="row"><span class="sp"></span><button id="runI">Check image</button></div>
    <p class="muted">Image checks: alt-text, brand colour palette and overall contrast (heuristic).</p></div></div>`;
  $("#sm").onchange = e => { const s = samples[e.target.value]; if (s) { $("#tx").value = s.text; $("#t1").value = s.title; $("#ch").value = s.channel; } };
  $("#runT").onclick = wrap(async () => {
    const b = $("#runT"); b.disabled = true; b.textContent = "Council is reviewing...";
    try { const r = await api("/reviews", { json: { title: $("#t1").value, channel: $("#ch").value, text: $("#tx").value } }); location.hash = "#/review/" + r.id; }
    finally { b.disabled = false; b.textContent = "Check with the council"; }
  });
  $("#runI").onclick = wrap(async () => {
    const f = $("#im").files[0]; if (!f) return toast("Please choose an image first");
    const fd = new FormData(); fd.append("file", f); fd.append("title", $("#t2").value); fd.append("alt_text", $("#alt").value); fd.append("caption", $("#cap").value);
    const r = await api("/reviews/image", { body: fd }); location.hash = "#/review/" + r.id;
  });
}

// ---------------------------------------------------------------- queue
async function queueView() {
  const rows = await api("/reviews");
  main.innerHTML = `<h1>${me.role === "creator" ? "My reviews" : "Review queue"}</h1><p class="sub">${me.role === "creator" ? "Your checked posts and their approval status." : "Posts submitted for approval appear first. Click a row to review it."}</p>
  <div class="row" style="margin-bottom:10px"><select id="fs" style="width:auto"><option value="">All statuses</option>${Object.entries(STATUS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
  <div class="card" style="padding:0;overflow:auto"><table><thead><tr><th>Title</th><th>Author</th><th>Status</th><th>Score</th><th>Flags</th><th>Updated</th></tr></thead><tbody id="tb"></tbody></table></div>`;
  const draw = () => {
    const f = $("#fs").value, list = rows.filter(r => !f || r.status === f).sort((a, b) => (b.status === "pending") - (a.status === "pending"));
    $("#tb").innerHTML = list.map(r => `<tr class="click" data-id="${r.id}"><td><b>${esc(r.title)}</b><div class="tag">${esc(r.channel)} · ${r.kind}${r.demo ? " · synthetic demo" : ""}</div></td><td>${esc(r.author)}</td>
      <td><span class="badge s-${r.status}">${STATUS[r.status]}</span></td><td>${r.score}</td><td>${r.counts.high} high · ${r.counts.medium} med · ${r.counts.low} low</td><td class="tag">${esc(r.updated.replace("T", " ").slice(0, 16))}</td></tr>`).join("") || `<tr><td colspan="6">No reviews yet.</td></tr>`;
    $("#tb").querySelectorAll("tr.click").forEach(tr => tr.onclick = () => location.hash = "#/review/" + tr.dataset.id);
  };
  $("#fs").onchange = draw; draw();
}

// ---------------------------------------------------------------- review detail
function highlight(text, findings, dec) {
  const spans = findings.filter(f => f.span).sort((a, b) => a.span[0] - b.span[0]); let out = "", pos = 0;
  for (const f of spans) {
    if (f.span[0] < pos) continue;
    const d = dec[f.id]?.decision;
    out += esc(text.slice(pos, f.span[0])) + `<mark class="${d === "accepted" ? "dim" : f.severity === "high" ? "high" : ""}" data-f="${f.id}" title="${esc(f.reason)}">${esc(text.slice(f.span[0], f.span[1]) || " ")}</mark>`; pos = f.span[1];
  }
  return out + esc(text.slice(pos));
}
function flagCard(f, dec, canDecide, open) {
  const d = dec[f.id]?.decision;
  return `<div class="flag ${f.severity} ${d || ""}" id="card-${f.id}">
   <div class="row"><span class="badge b-${f.severity}">${f.severity}</span><b>${esc(f.agent)}</b><span class="tag">${esc(f.category)} · ${f.source === "ai" ? "AI-assisted" : "rule check"} · confidence ${Math.round(f.confidence * 100)}%</span>
     <span class="sp"></span>${d ? `<span class="badge ${d === "accepted" ? "s-approved" : "s-draft"}">${d === "accepted" ? "Accepted" : "Dismissed"} by ${esc(dec[f.id].by)}</span>` : ""}</div>
   ${f.text ? `<div style="margin:6px 0">Flagged: <b>"${esc(f.text.trim())}"</b></div>` : ""}
   <div>${esc(f.reason)}</div>
   <div class="quote"><b>${esc(f.guideline_id)} · ${esc(f.guideline_title)}:</b> ${esc(f.guideline_quote)}</div>
   ${f.fact_id ? `<div class="quote"><b>Approved fact ${esc(f.fact_id)}:</b> ${esc(f.fact_statement)} <span class="tag">Source: ${esc(f.fact_source)}</span></div>` : ""}
   ${f.suggestion ? `<div class="fixbox"><b>Suggested fix:</b> ${esc(f.suggestion)}${f.replacement !== null && f.replacement !== undefined && f.span ? `<div class="tag">Replaces with: "${esc(f.replacement) || "(remove)"}"</div>` : ""}</div>` : ""}
   ${canDecide && open ? `<div class="row">${d !== "accepted" ? `<button class="mini good" data-a="accepted" data-f="${f.id}">Accept</button>` : ""}${d !== "dismissed" ? `<button class="mini sec" data-a="dismissed" data-f="${f.id}">Dismiss</button>` : ""}${d ? `<button class="mini sec" data-a="pending" data-f="${f.id}">Undo</button>` : ""}</div>` : ""}</div>`;
}

async function reviewView(id) {
  const r = await api("/reviews/" + id);
  const open = !["approved", "rejected"].includes(r.status), canDecide = true;
  const isMine = r.author === me.name, isMgr = me.role !== "creator";
  const acc = Object.values(r.decisions).filter(d => d.decision === "accepted").length;
  main.innerHTML = `<div class="row"><a href="#/queue">&larr; Back</a><span class="sp"></span><span class="badge s-${r.status}">${STATUS[r.status]}</span></div>
  <h1>${esc(r.title)}</h1><p class="sub">${esc(r.channel)} · by ${esc(r.author)} · version ${r.version}${r.demo ? " · <b>synthetic demo data</b>" : ""}</p>
  <div class="grid g4" style="margin-bottom:14px"><div class="card kpi"><div class="score">${r.score}<small>/100</small></div><div class="muted">Brand-safety score</div></div>
    <div class="card kpi"><b style="color:var(--high)">${r.counts.high}</b><span class="muted">High</span></div><div class="card kpi"><b style="color:var(--med)">${r.counts.medium}</b><span class="muted">Medium</span></div><div class="card kpi"><b>${r.counts.low}</b><span class="muted">Low</span></div></div>
  ${r.ai_status && r.ai_status !== "off" ? `<div class="notice">AI-assisted review: ${esc(r.ai_status)}. Confidential terms were masked before the AI call.</div>` : `<div class="notice">Rule-based council checks only (no AI key configured in this deployment). Every flag below is still explained and cited.</div>`}
  <div class="grid g2" style="align-items:start"><div>
    <div class="card"><h2>Content</h2>
      ${r.kind === "image" ? `<img alt="${esc(r.alt_text || "Uploaded image")}" src="/api/reviews/${r.id}/image?token=${encodeURIComponent(token)}" style="max-width:100%;border-radius:8px;margin-bottom:8px">` : ""}
      <div class="preview" id="pv">${highlight(r.content, r.findings, r.decisions) || "<span class='muted'>(no caption)</span>"}</div>
      ${r.kind === "text" && open ? `<details style="margin-top:10px"><summary>Edit text and re-check</summary><textarea id="edit">${esc(r.content)}</textarea><p class="row"><button id="recheck" class="sec">Re-check edited text</button></p></details>` : ""}
      <div class="row" style="margin-top:10px">
        ${r.kind === "text" && open ? `<button id="apply" ${acc ? "" : "disabled"}>Apply ${acc} accepted fix${acc === 1 ? "" : "es"} and re-check</button>` : ""}
        ${open && ["draft", "changes_requested"].includes(r.status) ? `<button id="submit" class="good">Submit for approval</button>` : ""}</div>
      <p class="muted">Nothing is changed automatically. Accepted fixes are applied only when you press the button, and you can edit the result.</p></div>
    ${r.verified.length ? `<div class="card"><h2>Verified claims</h2>${r.verified.map(v => `<div style="margin-bottom:6px"><span class="badge s-approved">Supported</span> "${esc(v.text)}"<div class="tag">${esc(v.fact_statement)} (Source: ${esc(v.source)})</div></div>`).join("")}</div>` : ""}
  </div><div>
    <h2>Council findings (${r.findings.length})</h2>
    ${r.findings.map(f => flagCard(f, r.decisions, canDecide, open)).join("") || `<div class="card">No issues found. This content matches the brand guidelines and approved facts.</div>`}
  </div></div>
  ${isMgr && r.status === "pending" ? `<div class="card"><h2>Manager decision</h2><label for="vn">Note to the creator (optional)</label><input id="vn"><div class="row" style="margin-top:10px"><button class="good" data-v="approved">Approve</button><button class="sec" data-v="changes_requested">Request changes</button><button class="bad" data-v="rejected">Reject</button></div></div>` : ""}
  <div class="card"><h2>Comments and history</h2><div class="row"><input id="cm" placeholder="Add a comment..." style="flex:1"><button id="addc" class="sec">Comment</button></div>
   <div class="timeline" style="margin-top:10px">${r.events.slice().reverse().map(e => `<div><b>${esc(e.user_name)}</b> · ${esc(e.action.replace(/_/g, " "))} <span class="tag">${esc(e.ts.replace("T", " ").slice(0, 16))}</span>${e.note ? `<div class="muted">${esc(e.note)}</div>` : ""}</div>`).join("")}</div></div>`;

  main.querySelectorAll("mark[data-f]").forEach(m => m.onclick = () => $("#card-" + m.dataset.f)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  main.querySelectorAll("button[data-a]").forEach(b => b.onclick = wrap(async () => { await api(`/reviews/${id}/decisions`, { json: { finding_id: b.dataset.f, decision: b.dataset.a } }); await reviewView(id); }));
  const ap = $("#apply"); if (ap) ap.onclick = wrap(async () => { await api(`/reviews/${id}/revise`, { json: { apply_accepted: true } }); toast("Fixes applied and content re-checked"); await reviewView(id); });
  const rc = $("#recheck"); if (rc) rc.onclick = wrap(async () => { await api(`/reviews/${id}/revise`, { json: { text: $("#edit").value } }); toast("Re-checked"); await reviewView(id); });
  const sb = $("#submit"); if (sb) sb.onclick = wrap(async () => {
    const un = r.findings.filter(f => f.severity === "high" && !r.decisions[f.id]).length;
    if (un && !confirm(`${un} high-severity flag(s) have no decision yet. Submit anyway?`)) return;
    await api(`/reviews/${id}/submit`, { method: "POST" }); toast("Submitted for approval"); await reviewView(id);
  });
  main.querySelectorAll("button[data-v]").forEach(b => b.onclick = wrap(async () => { await api(`/reviews/${id}/verdict`, { json: { verdict: b.dataset.v, note: $("#vn").value } }); toast("Decision recorded"); await reviewView(id); }));
  $("#addc").onclick = wrap(async () => { const t = $("#cm").value.trim(); if (!t) return; await api(`/reviews/${id}/comment`, { json: { text: t } }); await reviewView(id); });
}

// ---------------------------------------------------------------- insights
async function insightsView() {
  const d = await api("/insights");
  const rate = d.accepted + d.dismissed ? Math.round(100 * d.accepted / (d.accepted + d.dismissed)) : 0;
  const maxF = Math.max(1, ...d.guidelines.map(g => g.flags));
  main.innerHTML = `<h1>Governance insights</h1><p class="sub">What goes wrong most often, and which guidelines reviewers disagree with. The demo data here is synthetic.</p>
  <div class="grid g4"><div class="card kpi"><b>${d.reviews}</b>Reviews</div><div class="card kpi"><b>${d.flags}</b>Flags raised</div><div class="card kpi"><b>${rate}%</b>Flags accepted by humans</div><div class="card kpi"><b>${d.avg_score ?? "-"}</b>Average score</div></div>
  <div class="card"><h2>Recurring issues by guideline</h2><table><thead><tr><th>Guideline</th><th style="width:30%">Flags</th><th>Accepted</th><th>Dismissed</th><th>Status</th></tr></thead><tbody>
  ${d.guidelines.map(g => `<tr><td><b>${esc(g.guideline_id)}</b> ${esc(g.title)}</td><td><div class="bar"><i style="width:${100 * g.flags / maxF}%"></i></div>${g.flags}</td><td>${g.accepted}</td><td>${g.dismissed}</td>
    <td>${g.unclear ? `<span class="badge b-high">Possibly unclear (${Math.round(g.dismiss_rate * 100)}% dismissed)</span>` : `<span class="badge s-approved">Clear</span>`}</td></tr>`).join("")}</tbody></table></div>
  ${d.guidelines.filter(g => g.unclear).map(g => `<div class="card"><h2>Unclear guideline: ${esc(g.guideline_id)} ${esc(g.title)}</h2><p class="muted">Reviewers dismiss most flags for this rule, which usually means the rule is ambiguous, not that the AI is wrong.</p>
    <div class="quote"><b>Current:</b> ${esc(g.text)}</div><div class="fixbox"><b>Suggested wording:</b> ${esc(g.suggested_wording)}</div>
    ${me.role === "admin" ? `<button class="sec" data-g="${esc(g.guideline_id)}" data-t="${esc(g.suggested_wording)}">Adopt suggested wording</button>` : `<p class="muted">Only an admin can change guidelines.</p>`}</div>`).join("")}
  <div class="card"><h2>Issues by category</h2>${d.by_category.map(([c, n]) => `<span class="badge s-draft" style="margin-right:6px">${esc(c)}: ${n}</span>`).join("")}</div>`;
  main.querySelectorAll("button[data-g]").forEach(b => b.onclick = wrap(async () => { await api("/insights/apply-wording", { json: { guideline_id: b.dataset.g, text: b.dataset.t } }); toast("Guideline updated"); await insightsView(); }));
}

// ---------------------------------------------------------------- brand rules (admin)
async function brandView() {
  const b = await api("/brand");
  const gcard = g => `<div class="card" data-gid="${esc(g.id)}"><div class="row"><b>${esc(g.id)}</b><input class="gt" value="${esc(g.title)}" style="flex:1"><label class="row" style="margin:0"><input type="checkbox" class="ge" ${g.enabled ? "checked" : ""} style="width:auto"> On</label></div>
    <label>Guideline text (quoted in every flag)</label><textarea class="gx" style="min-height:70px">${esc(g.text)}</textarea>
    <details><summary>Rule settings (${esc(g.key)})</summary><textarea class="gd" style="font-family:monospace;min-height:80px">${esc(JSON.stringify(g.data, null, 2))}</textarea></details>
    <div class="row" style="margin-top:8px"><button class="mini gs">Save</button><button class="mini sec gdel">Delete</button></div></div>`;
  const fcard = f => `<div class="card" data-fid="${esc(f.id)}"><div class="row"><b>${esc(f.id)}</b><input class="ft" value="${esc(f.topic)}" style="flex:1"><label class="row" style="margin:0"><input type="checkbox" class="fe" ${f.enabled ? "checked" : ""} style="width:auto"> On</label></div>
    <label>Approved statement</label><input class="fs" value="${esc(f.statement)}">
    <div class="grid g3"><div><label>Keywords (comma separated)</label><input class="fk" value="${esc(f.keywords.join(", "))}"></div>
      <div><label>Number</label><input class="fv" type="number" step="any" value="${f.value ?? ""}"></div>
      <div><label>Unit</label><select class="fu">${["", "day", "hour", "month", "year", "pct", "inr"].map(u => `<option ${u === f.unit ? "selected" : ""} value="${u}">${u || "(none)"}</option>`).join("")}</select></div></div>
    <div class="grid g3"><div><label>Source</label><input class="fo" value="${esc(f.source)}"></div><div><label>Expires</label><input class="fx" type="date" value="${f.expires || ""}"></div>
      <div><label>Allows superlatives?</label><select class="fa"><option value="">No</option><option value="superlative" ${f.allows.includes("superlative") ? "selected" : ""}>Yes (award / ranking)</option></select></div></div>
    <div class="row" style="margin-top:8px"><button class="mini fsv">Save</button><button class="mini sec fdel">Delete</button></div></div>`;
  main.innerHTML = `<h1>Brand rules</h1><p class="sub">Admins control the guidelines, approved facts and privacy settings. Changes apply to the next review immediately.</p>
  <h2>Guidelines</h2><div id="gl">${b.guidelines.map(gcard).join("")}</div><button class="sec" id="addg">+ Add guideline</button>
  <h2 style="margin-top:22px">Approved Facts Vault</h2><div id="fl">${b.facts.map(fcard).join("")}</div><button class="sec" id="addf">+ Add approved fact</button>
  <h2 style="margin-top:22px">Privacy: confidential terms</h2><div class="card"><p class="muted">These terms (plus any email address or phone number) are replaced by tokens before content is sent to an external AI service.</p>
   <textarea id="ct" style="min-height:90px">${esc(b.confidential_terms.join("\n"))}</textarea><p class="row"><button id="sct">Save confidential terms</button></p></div>
  ${"" /* demo data */}<div class="card"><h2>Demo data</h2><p class="muted">Adds more synthetic reviews with simulated decisions, for the insights dashboard.</p><button class="sec" id="seed">Add synthetic demo reviews</button></div>`;
  main.querySelectorAll("[data-gid]").forEach(c => {
    const id = c.dataset.gid, g = b.guidelines.find(x => x.id === id);
    c.querySelector(".gs").onclick = wrap(async () => { let data; try { data = JSON.parse(c.querySelector(".gd").value || "{}"); } catch (e) { return toast("Rule settings must be valid JSON"); }
      await api("/guidelines", { method: "PUT", json: { id, key: g.key, title: c.querySelector(".gt").value, text: c.querySelector(".gx").value, data, enabled: c.querySelector(".ge").checked } }); toast("Guideline saved"); });
    c.querySelector(".gdel").onclick = wrap(async () => { if (confirm("Delete this guideline?")) { await api("/guidelines/" + id, { method: "DELETE" }); await brandView(); } });
  });
  main.querySelectorAll("[data-fid]").forEach(c => {
    const id = c.dataset.fid;
    c.querySelector(".fsv").onclick = wrap(async () => { const v = c.querySelector(".fv").value;
      await api("/facts", { method: "PUT", json: { id, topic: c.querySelector(".ft").value, statement: c.querySelector(".fs").value, keywords: c.querySelector(".fk").value.split(","), value: v === "" ? null : Number(v), unit: c.querySelector(".fu").value, source: c.querySelector(".fo").value, expires: c.querySelector(".fx").value || null, allows: c.querySelector(".fa").value ? [c.querySelector(".fa").value] : [], enabled: c.querySelector(".fe").checked } }); toast("Fact saved"); });
    c.querySelector(".fdel").onclick = wrap(async () => { if (confirm("Delete this fact?")) { await api("/facts/" + id, { method: "DELETE" }); await brandView(); } });
  });
  $("#addg").onclick = wrap(async () => { const key = prompt("Rule type: tone.shouting, tone.hype, terms, claims.superlative, claims.health, claims.absolute, claims.facts, access.alt, access.contrast, access.readability, visual.palette", "terms"); if (!key) return;
    await api("/guidelines", { method: "PUT", json: { key, title: "New guideline", text: "Describe the rule here.", data: key === "terms" ? { pairs: [] } : {}, enabled: true } }); await brandView(); });
  $("#addf").onclick = wrap(async () => { await api("/facts", { method: "PUT", json: { topic: "New fact", statement: "Write the approved statement.", keywords: [], unit: "", source: "", enabled: true } }); await brandView(); });
  $("#sct").onclick = wrap(async () => { await api("/settings/confidential", { method: "PUT", json: { terms: $("#ct").value.split("\n") } }); toast("Saved"); });
  $("#seed").onclick = wrap(async () => { await api("/admin/seed-demo", { method: "POST" }); toast("Demo reviews added"); });
}

// ---------------------------------------------------------------- about / AI disclosure
async function aboutView() {
  const a = await api("/about");
  main.innerHTML = `<h1>About BrandCouncil and AI use</h1><p class="sub">How the product works, what uses AI, and how your content is protected.</p>
  <div class="grid g2"><div class="card"><h2>The council</h2><table><tbody>
    <tr><td><b>Tone Agent</b></td><td>Shouting, pushy sales language, voice</td></tr><tr><td><b>Terminology Agent</b></td><td>Preferred and banned terms</td></tr>
    <tr><td><b>Claims Agent</b></td><td>Superlatives, health claims, promises; checks every claim against the Approved Facts Vault, including expiry</td></tr>
    <tr><td><b>Accessibility / Visual</b></td><td>Alt-text, contrast, readability, brand palette</td></tr><tr><td><b>Coordinator</b></td><td>Merges findings, removes duplicates, discards anything without a guideline citation, ranks by severity</td></tr></tbody></table></div>
  <div class="card"><h2>AI and external services</h2><p>AI mode in this deployment: <b>${a.ai_enabled ? "ON (" + esc(a.ai_provider) + ", model " + esc(a.ai_model) + ")" : "OFF (rule-based checks only)"}</b></p>
    <p>${esc(a.note)}</p><ul><li>AI output is validated: it must quote the content exactly and cite a real guideline, otherwise it is discarded.</li><li>Findings are labelled "AI-assisted" or "rule check".</li><li>AI only suggests. Humans accept, edit, approve or reject.</li><li>Libraries: ${a.libraries.map(esc).join(", ")}.</li></ul></div></div>
  <div class="card"><h2>Human control and privacy</h2><ul><li>No content is rewritten or published automatically.</li><li>Roles: creators check and submit, managers approve, admins manage rules.</li><li>Every decision, comment and revision is stored in the history.</li><li>Confidential terms, emails and phone numbers are masked before any external AI call.</li><li>All data in this demo is synthetic.</li></ul></div>`;
}

start();
