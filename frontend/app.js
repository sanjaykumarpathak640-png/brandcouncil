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
  if (me.role !== "creator") items.push(["accuracy", "Accuracy"]);
  if (me.role === "admin") { items.push(["import", "Import brand book"]); items.push(["brand", "Brand rules"]); }
  items.push(["about", "About & AI use"]);
  $("#nav").innerHTML = items.map(([k, l]) => `<button data-k="${k}">${l}</button>`).join("");
  $("#nav").querySelectorAll("button").forEach(b => b.onclick = () => location.hash = "#/" + b.dataset.k);
}
window.addEventListener("hashchange", () => me && route());
function route() {
  const [, page, arg] = (location.hash || "#/new").split("/");
  $("#nav").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.k === page));
  const views = { new: newView, queue: queueView, review: () => reviewView(arg), insights: insightsView, accuracy: accuracyView, import: importView, brand: brandView, about: aboutView };
  (views[page] || newView)().catch(e => toast(e.message));
}

// ---------------------------------------------------------------- new review
async function newView() {
  const samples = await api("/samples");
  main.innerHTML = `<h1>Check content before it goes out</h1>
  <p class="sub">Three steps: <b>1.</b> add your content below &middot; <b>2.</b> read the flags (each one explains why and quotes the rule) &middot; <b>3.</b> accept or dismiss, then submit for approval. Nothing is changed unless you choose it.</p>
  <div class="grid g3"><div class="card"><h2>Text post</h2>
    <label for="t1">Title</label><input id="t1" value="Instagram post">
    <label for="ch">Channel</label><select id="ch"><option>Instagram</option><option>Facebook</option><option>LinkedIn</option><option>Twitter</option><option>Website</option><option>Newsletter</option></select>
    <label for="tx">Content</label><textarea id="tx" placeholder="Paste your draft here..."></textarea>
    <div class="row"><select id="sm" aria-label="Sample posts" style="width:auto;max-width:60%"><option value="">Try a sample post...</option>${samples.map((s, i) => `<option value="${i}">${esc(s.title)}</option>`).join("")}</select><span class="sp"></span><button id="runT">Check this text</button></div></div>
  <div class="card"><h2>Document</h2><p class="muted">Upload a Word (.docx), PDF or text file. Every flag shows the paragraph it came from.</p>
    <label for="dt">Title (optional)</label><input id="dt" placeholder="e.g. Newsletter draft">
    <label for="df">File (.docx, .pdf, .txt, max 4 MB)</label><input id="df" type="file" accept=".docx,.pdf,.txt,.md">
    <div class="row" style="margin-top:12px"><span class="sp"></span><button id="runD">Check this document</button></div>
    <p class="muted">Scanned PDFs (pictures of pages) cannot be read. Paste their text instead.</p></div>
  <div class="card"><h2>Image post</h2>
    <label for="t2">Title</label><input id="t2" value="Image post">
    <label for="im">Image (PNG or JPG, max 5 MB)</label><input id="im" type="file" accept="image/*">
    <label for="alt">Alt-text (description for screen readers)</label><input id="alt" placeholder="e.g. Latte on a wooden table">
    <label for="tii">Text shown inside the image (optional)</label><input id="tii" placeholder="Leave empty to let the AI read it">
    <label for="cap">Caption (optional)</label><textarea id="cap" style="min-height:60px"></textarea>
    <div class="row" style="margin-top:12px"><span class="sp"></span><button id="runI">Check this image</button></div>
    <p class="muted">Checks alt-text, brand colours, contrast, and the words written on the image (read by AI when available).</p></div></div>`;
  $("#sm").onchange = e => { const s = samples[e.target.value]; if (s) { $("#tx").value = s.text; $("#t1").value = s.title; $("#ch").value = s.channel; } };
  const busy = (id, label, fn) => $(id).onclick = wrap(async () => { const b = $(id), old = b.textContent; if (b.disabled) return; b.disabled = true; b.textContent = label;
    try { await fn(); } finally { b.disabled = false; b.textContent = old; } });
  busy("#runT", "Council is reviewing...", async () => {
    if (!$("#tx").value.trim()) return toast("Please paste some content first, or try a sample post");
    const r = await api("/reviews", { json: { title: $("#t1").value, channel: $("#ch").value, text: $("#tx").value } }); location.hash = "#/review/" + r.id; });
  busy("#runD", "Reading document...", async () => {
    const f = $("#df").files[0]; if (!f) return toast("Please choose a file first");
    const fd = new FormData(); fd.append("file", f); fd.append("title", $("#dt").value);
    const r = await api("/reviews/document", { body: fd }); location.hash = "#/review/" + r.id; });
  busy("#runI", "Checking image...", async () => {
    const f = $("#im").files[0]; if (!f) return toast("Please choose an image first");
    const fd = new FormData(); fd.append("file", f); fd.append("title", $("#t2").value); fd.append("alt_text", $("#alt").value); fd.append("caption", $("#cap").value); fd.append("text_in_image", $("#tii").value);
    const r = await api("/reviews/image", { body: fd }); location.hash = "#/review/" + r.id; });
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
      <td><span class="badge s-${r.status}">${STATUS[r.status]}</span></td><td>${r.score}</td><td>${r.counts.high} high · ${r.counts.medium} med · ${r.counts.low} low</td><td class="tag">${esc(r.updated.replace("T", " ").slice(0, 16))}</td></tr>`).join("") || `<tr><td colspan="6">Nothing here yet. Go to <a href="#/new">New review</a> to check your first post.</td></tr>`;
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
   ${f.paragraph ? `<div class="tag">Paragraph ${f.paragraph}</div>` : ""}
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
  const textual = r.kind !== "image";
  const srcNote = { typed: "Text inside the image was typed by the creator and checked.", vision: "Text inside the image was read by AI and checked. Please confirm it matches the image.",
    vision_none: "AI found no readable text inside the image.", unavailable: "The text inside the image could not be read automatically (AI is not available). Type it into 'Text shown inside the image' to have it checked.", skipped: "" }[(r.meta || {}).text_source] || "";
  const acc = Object.values(r.decisions).filter(d => d.decision === "accepted").length;
  main.innerHTML = `<div class="row"><a href="#/queue">&larr; Back</a><span class="sp"></span><span class="badge s-${r.status}">${STATUS[r.status]}</span></div>
  <h1>${esc(r.title)}</h1><p class="sub">${esc(r.channel)} · by ${esc(r.author)} · version ${r.version}${r.demo ? " · <b>synthetic demo data</b>" : ""}</p>
  <div class="grid g4" style="margin-bottom:14px"><div class="card kpi"><div class="score">${r.score}<small>/100</small></div><div class="muted">Brand-safety score</div></div>
    <div class="card kpi"><b style="color:var(--high)">${r.counts.high}</b><span class="muted">High</span></div><div class="card kpi"><b style="color:var(--med)">${r.counts.medium}</b><span class="muted">Medium</span></div><div class="card kpi"><b>${r.counts.low}</b><span class="muted">Low</span></div></div>
  ${r.ai_status && r.ai_status !== "off" ? `<div class="notice ${r.ai_status.startsWith("ok") ? "" : "warn"}">${r.ai_status.startsWith("ok") ? "AI-assisted review: ok. Confidential terms were masked before the AI call." : "AI agents could not be used for this review (" + esc(r.ai_status) + "). The rule-based council results below are complete and still explained."}</div>` : `<div class="notice">Rule-based council checks only (no AI key configured in this deployment). Every flag below is still explained and cited.</div>`}
  <p class="muted" style="margin-top:-4px">How to read this: the score starts at 100 and drops for every flag (High -15, Medium -8, Low -3). High means a likely legal or factual problem, Medium a clear guideline breach, Low a style issue.</p>
  ${r.kind === "document" ? `<div class="notice">Document <b>${esc(r.meta.filename || "")}</b> (${esc(r.meta.file_kind)}) &middot; ${r.meta.paragraphs} paragraphs${r.meta.truncated ? " &middot; <b>only the first part was checked (file is very long)</b>" : ""}</div>` : ""}
  ${srcNote ? `<div class="notice ${(r.meta || {}).text_source === "unavailable" ? "warn" : ""}">${esc(srcNote)}</div>` : ""}
  <div class="grid g2" style="align-items:start"><div>
    <div class="card"><h2>Content</h2>
      ${r.kind === "image" ? `<img alt="${esc(r.alt_text || "Uploaded image")}" src="/api/reviews/${r.id}/image?token=${encodeURIComponent(token)}" style="max-width:100%;border-radius:8px;margin-bottom:8px">` : ""}
      <div class="preview" id="pv" style="white-space:pre-wrap">${highlight(r.content, r.findings, r.decisions) || "<span class='muted'>(no caption)</span>"}</div>
      ${textual && open ? `<details style="margin-top:10px"><summary>Edit text and re-check</summary><textarea id="edit">${esc(r.content)}</textarea><p class="row"><button id="recheck" class="sec">Re-check edited text</button></p></details>` : ""}
      <div class="row" style="margin-top:10px">
        ${textual && open ? `<button id="apply" ${acc ? "" : "disabled"}>Apply ${acc} accepted fix${acc === 1 ? "" : "es"} and re-check</button>` : ""}
        ${open && ["draft", "changes_requested"].includes(r.status) ? `<button id="submit" class="good">Submit for approval</button>` : ""}</div>
      <p class="muted">Nothing is changed automatically. Accepted fixes are applied only when you press the button, and you can edit the result.</p></div>
    ${r.verified.length ? `<div class="card"><h2>Verified claims</h2>${r.verified.map(v => `<div style="margin-bottom:6px"><span class="badge s-approved">Supported</span> "${esc(v.text)}"<div class="tag">${esc(v.fact_statement)} (Source: ${esc(v.source)})</div></div>`).join("")}</div>` : ""}
  </div><div>
    <h2>Council findings (${r.findings.length})</h2>
    ${r.findings.map(f => flagCard(f, r.decisions, canDecide, open)).join("") || `<div class="card"><b>No issues found.</b> This content matches the brand guidelines and approved facts.</div>`}
  </div></div>
  ${isMgr && r.status === "pending" ? `<div class="card"><h2>Manager decision</h2><label for="vn">Note to the creator (optional)</label><input id="vn"><div class="row" style="margin-top:10px"><button class="good" data-v="approved">Approve</button><button class="sec" data-v="changes_requested">Request changes</button><button class="bad" data-v="rejected">Reject</button></div></div>` : ""}
  <div class="card"><h2>Comments and history</h2><div class="row"><input id="cm" placeholder="Add a comment..." style="flex:1"><button id="addc" class="sec">Comment</button></div>
   <div class="timeline" style="margin-top:10px">${r.events.slice().reverse().map(e => `<div><b>${esc(e.user_name)}</b> · ${esc(e.action.replace(/_/g, " "))} <span class="tag">${esc(e.ts.replace("T", " ").slice(0, 16))}</span>${e.note ? `<div class="muted">${esc(e.note)}</div>` : ""}</div>`).join("")}</div></div>`;

  main.querySelectorAll("mark[data-f]").forEach(m => m.onclick = () => $("#card-" + m.dataset.f)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  main.querySelectorAll("button[data-a]").forEach(b => b.onclick = wrap(async () => { await api(`/reviews/${id}/decisions`, { json: { finding_id: b.dataset.f, decision: b.dataset.a } }); await reviewView(id); }));
  const ap = $("#apply"); if (ap) ap.onclick = wrap(async () => { await api(`/reviews/${id}/revise`, { json: { apply_accepted: true } }); toast("Fixes applied and content re-checked"); await reviewView(id); });
  const rc = $("#recheck"); if (rc) rc.onclick = wrap(async () => { await api(`/reviews/${id}/revise`, { json: { text: $("#edit").value } }); toast("Re-checked"); await reviewView(id); });
  const sb = $("#submit"); if (sb) sb.onclick = wrap(async () => { if (sb.disabled) return; sb.disabled = true;
    const un = r.findings.filter(f => f.severity === "high" && !r.decisions[f.id]).length;
    if (un && !confirm(`${un} high-severity flag(s) have no decision yet. Submit anyway?`)) return;
    await api(`/reviews/${id}/submit`, { method: "POST" }); toast("Submitted for approval"); await reviewView(id);
  });
  main.querySelectorAll("button[data-v]").forEach(b => b.onclick = wrap(async () => { main.querySelectorAll("button[data-v]").forEach(x => x.disabled = true); await api(`/reviews/${id}/verdict`, { json: { verdict: b.dataset.v, note: $("#vn").value } }); toast("Decision recorded"); await reviewView(id); }));
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
    <div class="row"><button class="sec" data-prev="${esc(g.guideline_id)}">Preview impact and draft better wording</button></div><div id="prev-${esc(g.guideline_id)}"></div></div>`).join("")}
  <div class="card"><h2>Is the council accurate?</h2><p class="muted">See measured precision and recall on 34 labelled posts.</p><a href="#/accuracy">Open the accuracy page</a></div>
  <div class="card"><h2>Issues by category</h2>${d.by_category.map(([c, n]) => `<span class="badge s-draft" style="margin-right:6px">${esc(c)}: ${n}</span>`).join("")}</div>`;
  main.querySelectorAll("button[data-prev]").forEach(b => b.onclick = wrap(async () => { b.disabled = true; b.textContent = "Working..."; const gid = b.dataset.prev;
    try {
      const [sg, dr] = await Promise.all([api("/insights/suggestions?guideline_id=" + encodeURIComponent(gid)), api("/insights/draft-wording", { json: { guideline_id: gid } })]);
      const c = sg.candidate, i = c && c.impact;
      document.getElementById("prev-" + gid).innerHTML = `<div class="fixbox" style="margin-top:10px"><b>Drafted wording${dr.source === "ai" ? " (AI-assisted)" : " (template, AI not available)"}:</b><textarea id="dw-${esc(gid)}" style="min-height:90px">${esc(dr.draft)}</textarea></div>
      ${c ? `<div class="quote"><b>Possible rule change:</b> ${esc(c.description)}<br>Impact on the ${i.reviews_affected} stored reviews that have this flag: <b>${i.flags_before} flags &rarr; ${i.flags_after}</b>. Removed flags that humans had dismissed: <b>${i.removed_that_humans_dismissed}</b>; removed flags that humans had accepted: <b style="color:var(--high)">${i.removed_that_humans_accepted}</b>.</div>` : `<p class="muted">No automatic rule change is proposed for this guideline; only the wording can be improved.</p>`}
      ${me.role === "admin" ? `<div class="row"><button class="good" data-adopt="${esc(gid)}">Adopt wording</button>${c ? `<label class="row" style="margin:0"><input type="checkbox" id="rc-${esc(gid)}" style="width:auto"> also apply the rule change above</label>` : ""}</div>` : `<p class="muted">Only an admin can adopt changes.</p>`}`;
      const ad = main.querySelector(`button[data-adopt="${gid}"]`);
      if (ad) ad.onclick = wrap(async () => { ad.disabled = true; const apply = c && document.getElementById("rc-" + gid).checked; await api("/insights/adopt", { json: { guideline_id: gid, text: document.getElementById("dw-" + gid).value, new_data: apply ? c.new_data : null } }); toast("Guideline updated"); await insightsView(); });
    } finally { b.disabled = false; b.textContent = "Preview impact and draft better wording"; } }));
}

// ---------------------------------------------------------------- accuracy benchmark
const pct = v => v === null || v === undefined ? "n/a" : Math.round(v * 100) + "%";
async function accuracyView() {
  const h = await api("/benchmark");
  main.innerHTML = `<h1>Accuracy of the council</h1><p class="sub">We test the rule-based council on ${h.dataset_size} labelled posts where a human decided in advance which guidelines should be flagged.
   <b>Precision</b> = of the flags raised, how many were right. <b>Recall</b> = of the problems that exist, how many were found. Re-run it after you change any rule.</p>
  <div class="row"><button id="runB">Run benchmark now</button><span class="muted">AI agents are not part of this test, so the numbers are repeatable.</span></div><div id="bres"></div>
  <div class="card"><h2>Previous runs</h2>${h.history.length ? `<table><thead><tr><th>When</th><th>By</th><th>Posts fully correct</th><th>Precision</th><th>Recall</th></tr></thead><tbody>${h.history.map(x => `<tr><td>${esc(x.ts.replace("T", " ").slice(0, 16))}</td><td>${esc(x.by)}</td><td>${x.posts_exact}/${x.posts}</td><td>${pct(x.overall.precision)}</td><td>${pct(x.overall.recall)}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">No runs yet. Press "Run benchmark now".</p>`}</div>`;
  $("#runB").onclick = wrap(async () => { const b = $("#runB"); b.disabled = true; b.textContent = "Running..."; try {
    const r = await api("/benchmark/run", { method: "POST" }); const o = r.overall;
    $("#bres").innerHTML = `<div class="grid g4" style="margin:14px 0"><div class="card kpi"><b>${r.posts_exact}/${r.posts}</b>Posts fully correct</div><div class="card kpi"><b>${pct(o.precision)}</b>Precision</div><div class="card kpi"><b>${pct(o.recall)}</b>Recall</div><div class="card kpi"><b>${o.tp}/${o.tp + o.fn}</b>Real problems found</div></div>
     <div class="card"><h2>By agent</h2><table><thead><tr><th>Agent</th><th>Precision</th><th>Recall</th><th>Found</th><th>Missed</th><th>False alarms</th></tr></thead><tbody>${Object.entries(r.by_agent).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${pct(v.precision)}</td><td>${pct(v.recall)}</td><td>${v.tp}</td><td>${v.fn}</td><td>${v.fp}</td></tr>`).join("")}</tbody></table></div>
     <div class="card"><h2>By guideline</h2><table><tbody>${Object.entries(r.by_guideline).map(([k, v]) => `<tr><td><b>${esc(k)}</b> ${esc(v.title)}</td><td>precision ${pct(v.precision)}</td><td>recall ${pct(v.recall)}</td></tr>`).join("")}</tbody></table></div>
     <div class="card"><h2>Where it went wrong (shown honestly)</h2>${r.missed.concat(r.false_alarms).length ? r.missed.map(m => `<p><span class="badge b-high">Missed</span> ${esc(m.guideline_id)}: "${esc(m.text)}"</p>`).join("") + r.false_alarms.map(m => `<p><span class="badge b-medium">False alarm</span> ${esc(m.guideline_id)}: "${esc(m.text)}"</p>`).join("") : "<p>No mistakes on this set.</p>"}</div>`;
    toast("Benchmark finished"); } finally { b.disabled = false; b.textContent = "Run benchmark now"; } });
}

// ---------------------------------------------------------------- brand book import (admin)
async function importView() {
  const p = await api("/proposals");
  const field = (k, v, w) => `<input data-k="${k}" value="${esc(v ?? "")}" ${w ? `style="width:${w}"` : ""} aria-label="${k}">`;
  const row = it => { const d = it.data, K = it.kind;
    const body = K === "term" ? `Avoid ${field("bad", d.bad)} &rarr; use ${field("good", d.good)}`
      : K === "hype" ? `Pressure phrase ${field("phrase", d.phrase)} &rarr; suggest ${field("alternative", d.alternative)}`
      : K === "fact" ? `${field("topic", d.topic)}<label>Approved statement</label>${field("statement", d.statement)}<div class="grid g3"><div><label>Keywords</label>${field("keywords", (d.keywords || []).join(", "))}</div><div><label>Number</label>${field("value", d.value)}</div><div><label>Unit (day, hour, month, year, pct, inr)</label>${field("unit", d.unit)}</div></div><label>Expires (YYYY-MM-DD, optional)</label>${field("expires", d.expires)}`
      : `${field("title", d.title)}<label>Guideline text</label><textarea data-k="text" style="min-height:60px">${esc(d.text)}</textarea>`;
    return `<div class="card" data-pid="${it.id}"><div class="row"><span class="badge s-draft">${{ term: "Preferred term", hype: "Pressure phrase", fact: "Approved fact", guideline: "Guideline" }[K]}</span><span class="tag">${it.source === "ai" ? "AI-proposed" : "rule-based extraction"}</span></div>
      <div style="margin:8px 0">${body}</div><div class="quote"><b>Found in your brand book:</b> "${esc(it.excerpt)}"</div>
      <div class="row"><button class="mini good pa">Approve</button><button class="mini sec pr">Reject</button></div></div>`; };
  main.innerHTML = `<h1>Import a brand book</h1><p class="sub">Upload your brand book (PDF, Word or text) or paste it. BrandCouncil proposes guidelines, preferred terms and approved facts, each with the sentence it came from. <b>Nothing becomes active until you approve it.</b></p>
  <div class="card"><div class="grid g2"><div><label for="bf">Brand book file (.docx, .pdf, .txt)</label><input id="bf" type="file" accept=".docx,.pdf,.txt,.md"></div><div><label for="bt">...or paste text</label><textarea id="bt" style="min-height:90px"></textarea></div></div>
   <div class="row" style="margin-top:10px"><button id="bi">Read brand book</button><button id="bs" class="sec">Load a sample brand book</button></div><div id="bmsg" class="muted"></div></div>
  <div class="row"><h2 style="margin:0">Waiting for your decision (${p.items.length})</h2><span class="sp"></span>${p.items.length ? `<button id="aa" class="sec">Approve all</button>` : ""}</div>
  ${p.items.map(row).join("") || `<div class="card muted">No proposals waiting. Import a brand book above.</div>`}`;
  const run = wrap(async () => { const b = $("#bi"); if (b.disabled) return; const f = $("#bf").files[0], t = $("#bt").value;
    if (!f && !t.trim()) return toast("Choose a file or paste some text first");
    b.disabled = true; b.textContent = "Reading..."; try { const fd = new FormData(); if (f) fd.append("file", f); fd.append("text", t);
      const r = await api("/brandbook/import", { body: fd }); toast(`${r.count} proposals created (${r.mode === "ai" ? "AI-assisted" : "rule-based"})`); await importView(); } finally { b.disabled = false; b.textContent = "Read brand book"; } });
  $("#bi").onclick = run;
  $("#bs").onclick = wrap(async () => { const s = await api("/brandbook/sample"); $("#bt").value = s.text; });
  const aa = $("#aa"); if (aa) aa.onclick = wrap(async () => { if (!confirm("Approve every proposal as shown? Items that are incomplete stay in the list.")) return; aa.disabled = true; const r = await api("/proposals/approve-all", { method: "POST" }); toast(`${r.approved} approved` + (r.needs_edit ? `, ${r.needs_edit} need editing` : "")); await importView(); });
  main.querySelectorAll("[data-pid]").forEach(c => { const id = c.dataset.pid, it = p.items.find(x => String(x.id) === id);
    const read = () => { const d = { ...it.data }; c.querySelectorAll("[data-k]").forEach(i => { let v = i.value; if (i.dataset.k === "keywords") v = v.split(",").map(x => x.trim()).filter(Boolean); else if (i.dataset.k === "value") v = v === "" ? null : Number(v); else if (i.dataset.k === "expires") v = v || null; d[i.dataset.k] = v; }); return d; };
    c.querySelector(".pa").onclick = wrap(async () => { const b = c.querySelector(".pa"); if (b.disabled) return; b.disabled = true; try { await api("/proposals/" + id, { method: "PUT", json: { data: read() } }); await api(`/proposals/${id}/approve`, { method: "POST" }); toast("Approved and now active"); await importView(); } catch (e) { b.disabled = false; throw e; } });
    c.querySelector(".pr").onclick = wrap(async () => { await api(`/proposals/${id}/reject`, { method: "POST" }); await importView(); }); });
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
  ${me.role === "admin" ? `<div class="card"><h2>Test AI connection</h2><p class="muted">Admins can check whether the AI service accepts the configured key.</p><button id="aitest" class="sec">Test AI connection</button><p id="aires" class="muted"></p></div>` : ""}
  <div class="card"><h2>Human control and privacy</h2><ul><li>No content is rewritten or published automatically.</li><li>Roles: creators check and submit, managers approve, admins manage rules.</li><li>Every decision, comment and revision is stored in the history.</li><li>Confidential terms, emails and phone numbers are masked before any external AI call.</li><li>All data in this demo is synthetic.</li></ul></div>`;
  const bt = $("#aitest"); if (bt) bt.onclick = wrap(async () => { $("#aires").textContent = "Testing..."; const r = await api("/ai-test"); $("#aires").innerHTML = (r.ok ? "<b style='color:#067647'>Working.</b> " : "<b style='color:#b42318'>Not working.</b> ") + esc(r.detail) + (r.model ? " Model: " + esc(r.model) : ""); });
}

start();
