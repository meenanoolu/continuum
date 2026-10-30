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

  try {
    const res = await fetch("/run-step", { method: "POST" });
    const data = await res.json();

    console.log("Gate result:", data);   // for debugging

    btn.disabled = false;
    btn.textContent = "Run Next Step";

    const gateDiv = document.getElementById("gate-result");

    if (data.status === "plan_complete") {
      gateDiv.innerHTML = `
        <div class="bg-emerald-900/40 border border-emerald-700 rounded-xl p-5">
          <h3 class="font-medium text-emerald-400">Plan completed</h3>
        </div>`;
      return;
    }

    if (data.status === "blocked_by_gate") {
      const learning = data.gate?.learning_path 
                    || data.gate?.missing_concept 
                    || "A learning path was required but no details were returned.";
      
      gateDiv.innerHTML = `
        <div class="bg-amber-900/30 border border-amber-700 rounded-xl p-5">
          <h3 class="font-medium text-amber-400 mb-3">Gate Blocked – Learning Path Required</h3>
          <div class="text-sm text-zinc-300 whitespace-pre-wrap">${learning}</div>
        </div>`;
      return;
    }

    // Success – show clean Gate results
    const g = data.gate || {};
    const reflection = g.reflection || {};

    gateDiv.innerHTML = `
      <div class="bg-zinc-900 border border-zinc-700 rounded-xl p-5">
        <h3 class="font-medium text-emerald-400 mb-3">Reflection</h3>
        <div class="space-y-2 text-sm">
          <p><span class="text-zinc-500">What happened:</span><br>${reflection.what_happened || "—"}</p>
          <p><span class="text-zinc-500">What worked:</span><br>${reflection.what_worked || "—"}</p>
          <p><span class="text-zinc-500">What was difficult:</span><br>${reflection.what_was_difficult || "—"}</p>
          <p><span class="text-zinc-500">Why:</span><br>${reflection.why || "—"}</p>
        </div>
      </div>

      <div class="bg-zinc-900 border border-zinc-700 rounded-xl p-5 mt-4">
        <h3 class="font-medium text-sky-400 mb-2">Explanation</h3>
        <p class="text-sm text-zinc-300 whitespace-pre-wrap">${g.explanation || "No explanation generated."}</p>
      </div>
    `;
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Run Next Step";
    alert("Error: " + err.message);
  }
}