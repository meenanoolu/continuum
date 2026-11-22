use strict";
// Every piece of model or user text goes in through textContent (see h()). There is no innerHTML anywhere.

const $ = (id) => document.getElementById(id);
let S = null;          // latest server snapshot
let lastGrade = null;  // last gate / learning result, shown until the next step runs
let ctxImage = null;   // optional planning image (data URL)
let renderedKey = "";
let polling = false;
let showHome = false;  // true while the person is looking at the home page with a project still in progress
let pastProjects = []; // saved projects from /api/projects (the current one included)
let fx = { slam: false, openIdx: null, shake: false };   // one-shot gate animations

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const svgLock = () => {
  const ns = "http://www.w3.org/2000/svg", s = document.createElementNS(ns, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", "lock"); s.setAttribute("aria-hidden", "true");
  const r = document.createElementNS(ns, "rect"); ["x", "y", "width", "height"].forEach((k, i) => r.setAttribute(k, [4, 10, 16, 11][i]));
  const p = document.createElementNS(ns, "path"); p.setAttribute("d", "M8 10V7a4 4 0 0 1 8 0v3");
  s.append(r, p); return s;
};

function svgIcon(kind) {
  const ns = "http://www.w3.org/2000/svg", s = document.createElementNS(ns, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("class", "mic-icon " + kind);
  s.setAttribute("aria-hidden", "true");
  const add = (tag, attrs) => {
    const e = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
    s.append(e);
  };
  if (kind === "mic") {
    add("rect", { x: 9, y: 3, width: 6, height: 11, rx: 3 });
    add("path", { d: "M5.5 11a6.5 6.5 0 0 0 13 0" });
    add("path", { d: "M12 17.5V21" });
  } else if (kind === "stop") {
    add("rect", { x: 7, y: 7, width: 10, height: 10, rx: 1.5 });
  } else {
    add("path", { d: "M12 4a8 8 0 1 0 8 8" });
  }
  return s;
}

async function api(path, method = "GET", body) {
  const res = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await res.json(); } catch (_) { /* non-JSON error body */ }
  if (!res.ok) throw new Error((data && (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))) || `Request failed (${res.status})`);
  return data;
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onerror = () => reject(new Error("Could not read that image."));
    fr.onload = () => {
      if (file.type === "image/gif" || file.size < 800_000) return resolve(fr.result);
      const img = new Image();
      img.onerror = () => reject(new Error("Could not decode that image."));
      img.onload = () => {
        const k = Math.min(1, 1600 / Math.max(img.width, img.height)), c = document.createElement("canvas");
        c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        resolve(c.toDataURL("image/jpeg", 0.85));
      };
      img.src = fr.result;
    };
    fr.readAsDataURL(file);
  });
}

$("ctx-image").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try { ctxImage = await fileToDataUrl(f); $("ctx-image-name").textContent = f.name; }
  catch (err) { ctxImage = null; $("ctx-image-name").textContent = err.message; }
});

$("start-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("start-btn"), err = $("start-error");
  err.hidden = true;
  const body = { project_name: $("project-name").value.trim(), plan: $("plan").value.trim(), repo: $("repo").value.trim() || null, context_image: ctxImage };
  if (!body.project_name || !body.plan) { err.textContent = "Add a project name and describe the next piece of work."; err.hidden = false; return; }
  const dup = pastProjects.some((p) => p.name.trim().toLowerCase() === body.project_name.toLowerCase());
  if (dup && !confirm(`A saved project named "${body.project_name}" already exists. Starting this replaces it. Continue?`)) return;
  btn.disabled = true; btn.textContent = "Planning...";
  try {
    lastGrade = null; renderedKey = "";
    S = await api("/api/start", "POST", body); showHome = false; render(); loadPast();
  }
  catch (ex) { err.textContent = ex.message; err.hidden = false; }
  finally { btn.disabled = false; btn.textContent = "Plan this work"; }
});

$("run-btn").addEventListener("click", async () => {
  lastGrade = null; renderedKey = "";
  clear($("log")).hidden = false; $("error-box").hidden = true;
  $("run-btn").disabled = true; $("run-btn").textContent = "Working...";
  try { await api("/api/step/run", "POST"); await poll(); }
  catch (e) { showError(e.message); S = await api("/api/state").catch(() => S); render(); }
});

async function poll() {
  if (polling) return;
  polling = true;
  let cursor = 0;
  try {
    for (;;) {
      const j = await api(`/api/job?since=${cursor}`);
      cursor = j.next;
      j.events.forEach(appendLog);
      if (j.status === "done") { if (j.state) S = j.state; break; }
      await new Promise((r) => setTimeout(r, 600));
    }
  } finally { polling = false; }
  if (S.phase === "awaiting_human") fx.slam = true;
  if (S.error) { showError(S.error + " \u2014 Click Run this step to retry."); }
  render();
}

function appendLog(ev) {
  const log = $("log");
  log.append(h("div", { class: ev.kind }, h("span", { class: "t" }, `${ev.t.toFixed(1)}s`), ev.text));
  log.scrollTop = log.scrollHeight;
}
function showError(msg) { const b = $("error-box"); b.textContent = msg; b.hidden = false; }

function render() {
  renderPills();
  const active = !!(S && S.project && S.phase !== "idle");
  const inApp = active && !showHome;
  $("start").hidden = inApp; $("app").hidden = !inApp;
  renderResume(active);
  if (!inApp) return;
  $("project-label").textContent = S.project;
  if (S.phase === "planned" && lastGrade && lastGrade.status === "passed" && !polling) $("log").hidden = true;
  renderThread(); renderHeadline(); renderRun(); renderEvidence(); renderGate(); renderMemory(); renderRevisions(); renderTrace();
  fx = { slam: false, openIdx: null, shake: false };
}

async function loadPast() {
  try { pastProjects = (await api("/api/projects")).projects || []; } catch (_) { pastProjects = []; }
  renderPast();
}
function renderPast() {
  const box = $("past");
  if (!box) return;
  clear(box);
  const list = pastProjects.filter((p) => !p.current);
  box.hidden = !list.length;
  if (!list.length) return;
  box.append(
    h("h3", {}, "Past projects"),
    h("ul", {}, list.map((p) => h("li", {},
      h("span", { class: "pname" }, p.name),
      h("span", { class: "pmeta" }, p.phase === "complete" ? `${p.total} steps, complete` : `${p.done}/${p.total} steps`),
      h("button", { class: "ghost", type: "button", onclick: () => openProject(p.id) }, "Open")))));
}
async function openProject(id) {
  try {
    lastGrade = null; renderedKey = "";
    S = await api(`/api/projects/${encodeURIComponent(id)}/resume`, "POST");
    showHome = false; $("log").hidden = true; render(); loadPast();
  } catch (e) { alert(e.message); }
}

function renderResume(active) {
  const box = $("resume");
  if (!box) return;
  clear(box); box.hidden = !active;
  if (!active) return;
  box.append(
    h("span", {}, h("b", {}, "Project in progress: "), S.project),
    h("button", { class: "ghost", type: "button", onclick: () => { showHome = false; render(); } }, "Continue this project"));
}

function renderPills() {
  const el = clear($("pills")), m = S && S.models;
  const pill = (name, on) => h("span", { class: "pill " + (on ? "on" : "") }, h("i"), name);
  if (m) el.append(pill("Muse Spark on Meta API", m.meta.available), pill("Muse Spark Open on Baseten", m.open.available), pill("Muse Voice Transcribe", m.meta.available));
  if (window.__fake) el.append(h("span", { class: "pill warn" }, "Offline fake model"));
}

function renderThread() {
  const ol = clear($("thread")), locked = ["awaiting_human", "learning"].includes(S.phase);
  S.plan.forEach((s, i) => {
    const cur = i === S.index && S.phase !== "complete";
    const cls = s.status === "done" ? "done" : s.status === "replaced" ? "replaced" : s.status === "blocked" ? "blocked" : s.status === "running" ? "running" : cur ? "current" : "pending";
    const mark = s.status === "done" ? "\u2713" : s.status === "blocked" ? "!" : "";
    ol.append(h("li", { class: `step ${cls}` },
      h("div", { class: "rail" }, h("span", { class: "node" }, mark)),
      h("div", { class: "body" }, h("div", { class: "title" }, s.title), h("div", { class: "meta" }, `${s.kind} worker, concept: ${s.concept}`))));
    const isLast = i === S.plan.length - 1;
    if (isLast || s.status === "replaced") return;
    let state = null, note = null;
    if (cur && locked) { state = "closed"; note = "Locked until you explain it"; }
    else if (s.status === "done") state = "open";
    if (!state) return;
    const opening = state === "open" && fx.openIdx === i;
    ol.append(h("li", { class: `gate-row ${state} ${opening ? "opening" : ""} ${state === "closed" && fx.slam ? "slam" : ""} ${state === "closed" && fx.shake ? "shake" : ""}`, "aria-hidden": note ? null : "true" },
      h("div", { class: "rail" }, h("div", { class: "gatebar" }, h("i"), h("i"))),
      note ? h("span", { class: "gate-note" }, note) : h("span")));
  });
}

function renderHeadline() {
  const el = clear($("headline")), step = S.plan[S.index];
  if (S.phase === "complete") { el.append(h("div", { class: "finale" }, "Understood."), h("p", {}, "Every step of this piece of work was built, verified, and explained by you.")); return; }
  if (!step) return;
  const line = {
    planned: ["You will need to explain ", h("b", {}, step.concept), "."],
    running: ["A worker is writing and testing this now."],
    awaiting_human: ["The next step stays locked until you explain ", h("b", {}, step.concept), "."],
    learning: ["Finish the learning path on ", h("b", {}, step.concept), ", then answer the retry question."],
  }[S.phase] || [];
  el.append(h("h2", {}, step.title), h("p", {}, line));
}

function renderRun() {
  const btn = $("run-btn"), hint = $("run-hint"), phase = S.phase;
  btn.disabled = phase !== "planned"; btn.textContent = phase === "running" ? "Working..." : "Run this step";
  btn.hidden = phase === "complete";
  hint.textContent = ({ awaiting_human: "Answer the Gate below to unlock the next step.", learning: "Finish the learning path below to unlock the next step." })[phase] || "";
  if (phase === "running" && !polling) { $("log").hidden = false; poll().catch((e) => showError(e.message)); }
}

const VERDICT = { verified: "Verified", compiles: "Compiles only", failed: "Failed", unverified: "Unverified", not_applicable: "Read only" };
function diffNodes(text) {
  return text.split("\n").map((l) => h("div", { class: l.startsWith("+++") || l.startsWith("---") || l.startsWith("@@") ? "hdr" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "" }, l || " "));
}
function renderEvidence() {
  const el = clear($("evidence")), r = S.last_result;
  if (!r || !["awaiting_human", "learning"].includes(S.phase)) return;
  const ev = r.evidence, t = ev.tests;
  const head = h("div", { class: "ticket-head" },
    h("div", {}, h("h3", {}, "Independent check"), h("div", { class: "by" }, `${r.kind} worker on ${(r.models_used || []).join(" and ") || "no model"} (${r.mode.replace("_", " ")})`)),
    h("div", { class: `stamp ${ev.level}` }, VERDICT[ev.level] || ev.level));
  const said = h("div", { class: "said" }, h("h4", {}, "The worker said"), h("blockquote", {}, r.summary || "(nothing)"));
  const measured = h("div", {}, h("h4", {}, "Continuum measured"), h("div", { class: "headline-measured" }, ev.headline),
    r.files_changed.length ? h("div", { class: "files" }, r.files_changed.map((f) => h("span", { class: "fchip" }, f))) : null,
    t ? h("pre", {}, `pytest exit ${t.exit_code}\n${t.output}`) : null);
  const card = h("div", { class: "ticket" }, head, ev.claim_mismatch ? h("div", { class: "liar" }, "The worker said it worked. The tests say otherwise. Trust the right-hand side.") : null, h("div", { class: "split" }, said, measured));
  if (r.diff) card.append(h("details", { class: "more" }, h("summary", {}, "See the diff"), h("div", { class: "diffbox" }, diffNodes(r.diff))));
  el.append(card);
}

function area(label, id, rows, hint) {
  const lab = typeof label === "string" ? h("label", { for: id }, label) : label;
  return h("div", { class: "q" }, lab,
    h("div", { class: "field-mic" }, h("textarea", { id, rows, placeholder: hint || "" }), micBtn(id)));
}
function pips(n) { return h("span", { class: "pips", "aria-label": `${n} of 2` }, [0, 1].map((i) => h("i", { class: i < n ? "on" : "" }))); }

function renderGrade(g) {
  const ok = g.status === "passed", pct = Math.min(100, ((g.score || 0) / 2) * 100), tick = Math.min(100, ((g.threshold || 0) / 2) * 100);
  const box = h("div", { class: `grade ${ok ? "pass" : "fail"}` }, h("h3", {}, ok ? "Gate open." : "Not yet."));
  if (g.score != null && g.threshold != null) {
    box.append(h("div", { class: "meter", role: "img", "aria-label": `Score ${g.score} of 2, needed ${g.threshold}` }, h("b", { style: `width:${pct}%` }), h("u", { style: `left:${tick}%` })),
      h("div", { class: "meter-label" }, `You scored ${g.score} out of 2. The bar for this Gate was ${g.threshold}.`));
  } else if (g.score != null) box.append(h("div", { class: "meter-label" }, `Retry answer scored ${g.score} out of 2.`));
  if (g.feedback) box.append(h("p", {}, g.feedback));
  const names = { parroting: "Copied the explanation", shallow_explain: "Very short explain-back", fast_submit: "Answered in seconds" };
  if (g.signals && g.signals.length) box.append(h("div", { class: "flags" }, g.signals.map((s) => h("span", { class: "flag" }, names[s] || s))));
  if (g.explain_back) box.append(h("div", { class: "qres" }, pips(g.explain_back.score), `Explain-back. ${g.explain_back.note || ""}`));
  (g.answers || []).forEach((a, i) => box.append(h("div", { class: "qres" }, pips(a.score), `Question ${i + 1}. ${a.note || ""}`)));
  if (g.visual) box.append(h("div", { class: "qres" }, pips(g.visual.score), `Your image. ${g.visual.note || ""}`));
  return box;
}

function renderGate() {
  const el = $("gate"), gate = S.gate;
  const key = `${S.phase}|${gate ? gate.questions.map((q) => q.question).join("|") + (gate.learning ? gate.learning.retry_question : "") : ""}|${lastGrade ? lastGrade.status + lastGrade.score : ""}`;
  if (key === renderedKey) return;
  renderedKey = key;
  clear(el); el.style.display = "grid"; el.style.gap = "1.5rem";
  if (lastGrade && S.phase !== "awaiting_human") el.append(renderGrade(lastGrade));
  if (S.phase === "complete" || !gate) return;

  if (S.phase === "awaiting_human") {
    const pol = gate.policy, r = gate.reflection;
    el.append(h("dl", { class: "reflect" }, [["What happened", r.what_happened], ["What worked", r.what_worked], ["What was hard", r.what_was_difficult], ["Why", r.why]].map(([l, v]) => [h("dt", {}, l), h("dd", {}, v)])));
    el.append(h("p", { class: "explain" }, gate.explanation));
    const err = h("p", { class: "error", role: "alert" });
    const imgNote = h("span", { class: "muted small" });
    const submit = h("button", { class: "gate-btn", type: "button", onclick: async () => {
      submit.disabled = true; submit.textContent = "Grading...";
      try {
        const res = await api("/api/gate/answers", "POST", { explain_back: $("explain-back").value, answers: gate.questions.map((_, i) => $(`ans-${i}`).value) });
        if (res.status === "rejected" || res.status === "grader_error") { err.textContent = res.reason; submit.disabled = false; submit.textContent = "Submit answers"; return; }
        lastGrade = res; S = res.state;
        if (res.status === "passed") fx.openIdx = lastDoneIndex(); else fx.shake = true;
        render();
      } catch (e) { err.textContent = e.message; submit.disabled = false; submit.textContent = "Submit answers"; }
    } }, "Submit answers");
    const imgInput = h("input", { type: "file", accept: "image/png,image/jpeg,image/gif,image/webp", hidden: true, onchange: async (e) => {
      const f = e.target.files[0]; if (!f) return;
      try {
        const data = await fileToDataUrl(f);
        const notes = (await api("/api/image", "POST", { data_url: data, purpose: "gate" })).notes;
        imgNote.textContent = "Image attached: " + notes.slice(0, 120) + (notes.length > 120 ? "\u2026" : "");
      } catch (ex) { imgNote.textContent = ex.message; }
    }});
    el.append(h("div", { class: "gate-sheet" },
      h("div", { class: "gate-top" }, svgLock(), h("h3", {}, "Prove you understand it")),
      h("div", { class: "gate-body" },
        pol.strictness === "strict" ? h("div", { class: "strict" }, h("b", {}, "Stricter this time. "), pol.reasons.join(". ") + ".") : null,
        area("Explain, in your own words, what was just built and why", "explain-back", 4, "What does the code do, and why was it done this way?"),
        ...gate.questions.map((q, i) => area(h("label", { for: `ans-${i}` }, h("span", { class: "kind" }, q.type), q.question, q.focus ? h("span", { class: "focus" }, q.focus) : null), `ans-${i}`, 3)),
        h("div", { class: "row" }, h("label", { class: "ghost file" }, "Attach a diagram or screenshot of your work", imgInput), imgNote),
        err,
        h("div", { class: "gate-actions" }, submit))));
  }

  if (S.phase === "learning" && gate.learning) {
    const L = gate.learning;
    const err = h("p", { class: "error", role: "alert" });
    const submit = h("button", { class: "gate-btn", type: "button", onclick: async () => {
      submit.disabled = true; submit.textContent = "Checking...";
      try {
        const res = await api("/api/gate/learning", "POST", { confirmation: $("confirm").value, retry_answer: $("retry").value });
        if (res.status === "rejected" || res.status === "grader_error") { err.textContent = res.reason; submit.disabled = false; submit.textContent = "Submit"; return; }
        lastGrade = res; S = res.state;
        if (res.status === "passed") fx.openIdx = lastDoneIndex(); else fx.shake = true;
        render();
      } catch (e) { err.textContent = e.message; submit.disabled = false; submit.textContent = "Submit"; }
    } }, "Submit");
    el.append(h("div", { class: "gate-sheet fail" },
      h("div", { class: "gate-top" }, svgLock(), h("h3", {}, "Learning path")),
      h("div", { class: "gate-body" },
        h("p", {}, L.why_it_mattered || ""),
        h("ol", { class: "path" }, L.items.map((item) => h("li", {}, item))),
        area("What did you just learn?", "confirm", 2, "A short note on what clicked."),
        area(L.retry_question, "retry", 4, "Answer without looking back."),
        err,
        h("div", { class: "gate-actions" }, submit))));
  }
}

function lastDoneIndex() { let k = null; S.plan.forEach((s, i) => { if (s.status === "done") k = i; }); return k; }

function renderMemory() {
  const m = S.memory, el = clear($("memory"));
  const strict = m.strictness === "strict";
  el.append(h("div", {}, h("h4", {}, "Gate strictness"), h("div", { class: `strictness ${strict ? "strict" : ""}` }, cap(m.strictness)),
    m.strictness_reasons.length ? h("ul", { class: "sent" }, m.strictness_reasons.map((r) => h("li", {}, cap(r) + "."))) : h("p", { class: "none" }, "No bad habits detected yet.")));

  const concepts = m.concept_details || [];
  if (concepts.length) {
    const dash = h("div", { class: "mastery-dash" }, h("h4", {}, "Concept mastery"));
    concepts.forEach(c => {
      const total = (c.passes || 0) + (c.failures || 0);
      const score = total ? Math.round((c.passes / total) * 100) : 0;
      const bar = h("div", { class: "mastery-bar" },
        h("div", { class: "mastery-label" }, c.name),
        h("div", { class: "mastery-track" }, h("div", { class: "mastery-fill", style: `width:${score}%` })),
        h("span", { class: "mastery-score" }, `${score}% (${c.passes}/${total})`)
      );
      dash.append(bar);
    });
    el.append(dash);
  }

  el.append(h("div", {}, h("h4", {}, "Where you struggle"), m.weak_concepts.length ? h("div", { class: "weak" }, m.weak_concepts.map((c) => h("span", {}, c))) : h("p", { class: "none" }, "Nothing yet.")));
  el.append(h("div", {}, h("h4", {}, "What you have shown you know"), m.mastered_concepts.length ? h("div", { class: "good" }, m.mastered_concepts.map((c) => h("span", {}, c))) : h("p", { class: "none" }, "Nothing yet.")));
  if (m.patterns.length) el.append(h("div", {}, h("h4", {}, "Habits it noticed"), h("ul", { class: "sent" }, m.patterns.map((p) => h("li", {}, `${cap(p.label)}. Seen ${p.count} time${p.count > 1 ? "s" : ""}.`)))));
}

function renderRevisions() {
  const el = clear($("revisions"));
  el.hidden = !S.revisions.length;
  S.revisions.forEach((r) => el.append(h("div", {}, h("b", {}, "Plan changed"), r.summary, h("div", { class: "muted" }, "Because of " + r.reason + "."))));
}
function renderTrace() {
  const el = clear($("trace"));
  if (!S.trace.length) { el.append(h("span", {}, "No calls yet.")); return; }
  S.trace.slice().reverse().forEach((c) => el.append(h("span", { class: c.ok ? "" : "bad", title: c.model }, `${c.purpose}  ${c.model.replace("meta-models/", "")}  ${c.ms}ms`)));
}

function micBtn(id) {
  const btn = h("button", { type: "button", class: "mic-btn", title: "Speak instead of typing", "aria-label": "Record voice" });
  btn.append(svgIcon("mic"));
  let rec = null, chunks = [];
  btn.onclick = async () => {
    if (rec && rec.state === "recording") { rec.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      rec = new MediaRecorder(stream);
      chunks = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        btn.disabled = true; btn.textContent = ""; btn.append(svgIcon("spin"));
        try {
          const blob = new Blob(chunks, { type: "audio/webm" });
          const fd = new FormData(); fd.append("audio", blob, "clip.webm");
          const r = await fetch("/api/transcribe", { method: "POST", body: fd });
          const data = await r.json();
          if (!r.ok) throw new Error(data.detail || "Transcription failed");
          const ta = document.getElementById(id);
          ta.value = (ta.value ? ta.value + " " : "") + data.text;
          ta.dispatchEvent(new Event("input"));
        } catch (e) { alert(e.message); }
        btn.disabled = false; btn.textContent = ""; btn.append(svgIcon("mic"));
      };
      rec.start(); btn.textContent = ""; btn.append(svgIcon("stop"));
      setTimeout(() => { if (rec && rec.state === "recording") rec.stop(); }, 45000);
    } catch (e) { alert("Microphone access denied or unavailable."); }
  };
  return btn;
}

$("revise-btn").onclick = async () => {
  const reason = prompt("Why revise the remaining steps? (optional)") || null;
  try { S = (await api("/api/plan/revise", "POST", { reason })).state; lastGrade = null; renderedKey = ""; render(); }
  catch (e) { alert(e.message); }
};
$("new-btn").onclick = () => { showHome = true; render(); };
$("reset-mem").onclick = async () => {
  if (!confirm("Erase all learning memory? This cannot be undone.")) return;
  await api("/api/memory/reset", "POST"); S = await api("/api/state"); render();
};
$("home-link").onclick = (e) => { if (S && S.project && S.phase !== "idle") { e.preventDefault(); showHome = true; render(); } };

(async () => {
  try { S = await api("/api/state"); } catch (_) { S = { phase: "idle" }; }
  try { const h = await api("/api/health"); window.__fake = h.fake_llm; } catch (_) {}
  render(); loadPast();
  document.querySelectorAll(".mic-btn").forEach((b) => { if (!b.querySelector("svg")) b.append(svgIcon("mic")); });
})();
