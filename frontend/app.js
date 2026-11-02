"use strict";
// Every piece of model or user text goes in through textContent (see h()). There is no innerHTML anywhere.

const $ = (id) => document.getElementById(id);
let S = null;          // latest server snapshot
let lastGrade = null;  // last gate / learning result, shown until the next step runs
let ctxImage = null;   // optional planning image (data URL)
let renderedKey = "";
let polling = false;
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

async function api(path, method = "GET", body) {
  const res = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await res.json(); } catch (_) { /* non-JSON error body */ }
  if (!res.ok) throw new Error((data && (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))) || `Request failed (${res.status})`);
  return data;
}

// Large screenshots are downscaled so they stay far below the API size limit.
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

// ------------------------------------------------------------------ start
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
  btn.disabled = true; btn.textContent = "Planning...";
  try { lastGrade = null; renderedKey = ""; S = await api("/api/start", "POST", body); render(); }
  catch (ex) { err.textContent = ex.message; err.hidden = false; }
  finally { btn.disabled = false; btn.textContent = "Plan this work"; }
});

// ------------------------------------------------------------------ run + live log
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
  if (S.error) showError(S.error);
  render();
}

function appendLog(ev) {
  const log = $("log");
  log.append(h("div", { class: ev.kind }, h("span", { class: "t" }, `${ev.t.toFixed(1)}s`), ev.text));
  log.scrollTop = log.scrollHeight;
}
function showError(msg) { const b = $("error-box"); b.textContent = msg; b.hidden = false; }

// ------------------------------------------------------------------ render
function render() {
  renderPills();
  const active = S && S.project && S.phase !== "idle";
  $("start").hidden = !!active; $("app").hidden = !active;
  if (!active) return;
  $("project-label").textContent = S.project;
  if (S.phase === "planned" && lastGrade && lastGrade.status === "passed" && !polling) $("log").hidden = true;
  renderThread(); renderHeadline(); renderRun(); renderEvidence(); renderGate(); renderMemory(); renderRevisions(); renderTrace();
  fx = { slam: false, openIdx: null, shake: false };
}

function renderPills() {
  const el = clear($("pills")), m = S && S.models;
  const pill = (name, on) => h("span", { class: "pill " + (on ? "on" : "") }, h("i"), name);
  if (m) el.append(pill("Muse Spark on Meta API", m.meta.available), pill("Muse Spark Open on Baseten", m.open.available));
  if (window.__fake) el.append(h("span", { class: "pill warn" }, "Offline fake model"));
}

function renderThread() {
  const ol = clear($("thread")), locked = ["awaiting_human", "learning"].includes(S.phase);
  S.plan.forEach((s, i) => {
    const cur = i === S.index && S.phase !== "complete";
    const cls = s.status === "done" ? "done" : s.status === "replaced" ? "replaced" : s.status === "blocked" ? "blocked" : s.status === "running" ? "running" : cur ? "current" : "pending";
    const mark = s.status === "done" ? "✓" : s.status === "blocked" ? "!" : "";
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

// ------------------------------------------------------------------ evidence
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

// ------------------------------------------------------------------ gate
function area(label, id, rows, hint) {
  return h("div", { class: "q" }, label, h("textarea", { id, rows, placeholder: hint || "" }));
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
  if (key === renderedKey) return;       // keep typed text intact across polling re-renders
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
      imgNote.textContent = "Reading your image with Muse Spark vision...";
      try { await api("/api/image", "POST", { data_url: await fileToDataUrl(f), purpose: "gate" }); imgNote.textContent = `Attached ${f.name}. Your explanation will be checked against it.`; }
      catch (ex) { imgNote.textContent = ex.message; }
    } });
    el.append(h("div", { class: "gate-sheet" },
      h("div", { class: "gate-top" }, svgLock(), h("h3", {}, "Gate locked")),
      h("div", { class: "gate-body" },
        pol.strictness === "strict" ? h("div", { class: "strict" }, h("b", {}, "This Gate is stricter than usual: "), pol.reasons.join("; ") + ". You get four questions and a higher bar.") : null,
        area(h("label", { for: "explain-back" }, "Explain it back in your own words. What was built, and why this way?"), "explain-back", 4, "Pasting the explanation above is detected and scores zero."),
        gate.questions.map((q, i) => area(h("label", { for: `ans-${i}` }, h("span", { class: "kind" }, q.type.replace("_", " ")), q.question, q.focus ? h("span", { class: "focus" }, q.focus) : null), `ans-${i}`, 2)),
        err,
        h("div", { class: "gate-actions" }, submit, h("label", { class: "ghost", style: "margin:0" }, "Show your work with an image", imgInput), imgNote))));
    return;
  }

  if (S.phase === "learning" && gate.learning) {
    const lp = gate.learning, err = h("p", { class: "error", role: "alert" });
    const submit = h("button", { class: "gate-btn", type: "button", onclick: async () => {
      submit.disabled = true; submit.textContent = "Checking...";
      try {
        const res = await api("/api/gate/learning", "POST", { confirmation: $("lp-confirm").value, retry_answer: $("lp-retry").value });
        if (["rejected", "grader_error"].includes(res.status)) err.textContent = res.reason;
        else if (res.status === "retry") { err.textContent = res.feedback || "Not there yet. Work through the path again, then retry."; fx.shake = true; }
        else { lastGrade = res; S = res.state; fx.openIdx = lastDoneIndex(); render(); return; }
      } catch (e) { err.textContent = e.message; }
      submit.disabled = false; submit.textContent = "Finish learning path";
      document.querySelector(".gate-row.closed")?.classList.add("shake");
    } }, "Finish learning path");
    el.append(h("div", { class: "gate-sheet fail" },
      h("div", { class: "gate-top" }, svgLock(), h("h3", {}, `Still locked: learn ${lp.concept}`)),
      h("div", { class: "gate-body" }, h("p", {}, lp.why_it_mattered),
        h("ol", { class: "path" }, lp.items.map((i) => h("li", {}, i))),
        area(h("label", { for: "lp-confirm" }, "What did you learn, in a sentence or two?"), "lp-confirm", 2),
        area(h("label", { for: "lp-retry" }, lp.retry_question), "lp-retry", 4),
        err, h("div", { class: "gate-actions" }, submit))));
  }
}
function lastDoneIndex() { let k = null; S.plan.forEach((s, i) => { if (s.status === "done") k = i; }); return k; }

// ------------------------------------------------------------------ dossier
function renderMemory() {
  const m = S.memory, el = clear($("memory"));
  const strict = m.strictness === "strict";
  el.append(h("div", {}, h("h4", {}, "Gate strictness"), h("div", { class: `strictness ${strict ? "strict" : ""}` }, cap(m.strictness)),
    m.strictness_reasons.length ? h("ul", { class: "sent" }, m.strictness_reasons.map((r) => h("li", {}, cap(r) + "."))) : h("p", { class: "none" }, "No bad habits detected yet.")));
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

// ------------------------------------------------------------------ misc buttons
$("revise-btn").addEventListener("click", async () => {
  try { const r = await api("/api/plan/revise", "POST", {}); S = r.state; renderedKey = ""; render(); if (!r.revised) showError("The planner could not produce a revision. Try again."); }
  catch (e) { showError(e.message); }
});
$("reset-mem").addEventListener("click", async () => {
  if (!confirm("Erase everything Continuum has learned about you?")) return;
  await api("/api/memory/reset", "POST"); S = await api("/api/state"); render();
});
$("new-btn").addEventListener("click", async () => {
  try { S = await api("/api/project/abandon", "POST"); lastGrade = null; renderedKey = ""; $("log").hidden = true; render(); }
  catch (e) { showError(e.message); }
});

(async function init() {
  try { window.__fake = (await api("/api/health")).fake_llm; } catch (_) { /* ignore */ }
  try { S = await api("/api/state"); } catch (_) { S = null; }
  render();
})();
