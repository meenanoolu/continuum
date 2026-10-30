async function startProject() {
  const projectName = document.getElementById("project-name").value.trim();
  const plan = document.getElementById("plan").value.trim();

  if (!projectName || !plan) {
    alert("Please fill both fields");
    return;
  }

  const res = await fetch("/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_name: projectName, plan: plan })
  });

  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Error starting project");
    return;
  }

  // Show steps
  const list = document.getElementById("steps-list");
  list.innerHTML = data.steps.map((s, i) =>
    `<div class="bg-zinc-900 border border-zinc-700 rounded-xl px-4 py-3">
       <span class="text-zinc-500 mr-2">${i + 1}.</span> ${s}
     </div>`
  ).join("");

  document.getElementById("start-section").classList.add("hidden");
  document.getElementById("main-section").classList.remove("hidden");
}

async function runNextStep() {
  const btn = document.getElementById("run-btn");
  btn.disabled = true;
  btn.textContent = "Running...";

  const res = await fetch("/run-step", { method: "POST" });
  const data = await res.json();

  btn.disabled = false;
  btn.textContent = "Run Next Step";

  const gateDiv = document.getElementById("gate-result");

  if (data.status === "plan_complete") {
    gateDiv.innerHTML = `<div class="bg-emerald-900/40 border border-emerald-700 rounded-xl p-4">Plan completed.</div>`;
    return;
  }

  if (data.status === "blocked_by_gate") {
    gateDiv.innerHTML = `
      <div class="bg-amber-900/30 border border-amber-700 rounded-xl p-4">
        <h3 class="font-medium mb-2">Gate Blocked – Learning Path Required</h3>
        <pre class="text-sm whitespace-pre-wrap">${data.gate.learning_path}</pre>
      </div>`;
    return;
  }

  // Show Gate results
  const g = data.gate;
  gateDiv.innerHTML = `
    <div class="bg-zinc-900 border border-zinc-700 rounded-xl p-4">
      <h3 class="font-medium text-emerald-400 mb-1">Reflection</h3>
      <pre class="text-sm whitespace-pre-wrap">${JSON.stringify(g.reflection, null, 2)}</pre>
    </div>
    <div class="bg-zinc-900 border border-zinc-700 rounded-xl p-4">
      <h3 class="font-medium text-sky-400 mb-1">Explanation</h3>
      <p class="text-sm">${g.explanation}</p>
    </div>
  `;
}