let currentQuestions = [];
let currentStep = "";

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

    btn.disabled = false;
    btn.textContent = "Run Next Step";

    if (data.status === "plan_complete") {
      document.getElementById("gate-area").innerHTML = `
        <div class="bg-emerald-900/40 border border-emerald-700 rounded-xl p-5">
          <h3 class="font-medium text-emerald-400">Plan completed</h3>
        </div>`;
      return;
    }

    if (data.status === "awaiting_human") {
      showHumanGate(data);
      return;
    }

    alert("Unexpected status: " + data.status);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Run Next Step";
    alert("Error: " + err.message);
  }
}

function showHumanGate(data) {
  const g = data.gate;
  currentQuestions = g.questions || [];
  currentStep = data.step;

  const reflection = g.reflection || {};
  const questionsHtml = currentQuestions.map((q, i) => `
    <div class="mb-4">
      <label class="block text-sm text-zinc-400 mb-1">${i + 1}. ${q}</label>
      <textarea id="answer-${i}" rows="2"
                class="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
                placeholder="Your answer..."></textarea>
    </div>
  `).join("");

  document.getElementById("gate-area").innerHTML = `
    <div class="bg-zinc-900 border border-zinc-700 rounded-xl p-5">
      <h3 class="font-medium text-emerald-400 mb-3">Reflection</h3>
      <div class="space-y-2 text-sm">
        <p><span class="text-zinc-500">What happened:</span><br>${reflection.what_happened || "—"}</p>
        <p><span class="text-zinc-500">What worked:</span><br>${reflection.what_worked || "—"}</p>
        <p><span class="text-zinc-500">What was difficult:</span><br>${reflection.what_was_difficult || "—"}</p>
        <p><span class="text-zinc-500">Why:</span><br>${reflection.why || "—"}</p>
      </div>
    </div>

    <div class="bg-zinc-900 border border-zinc-700 rounded-xl p-5">
      <h3 class="font-medium text-sky-400 mb-2">Explanation</h3>
      <p class="text-sm text-zinc-300 whitespace-pre-wrap">${g.explanation || "—"}</p>
    </div>

    <div class="bg-zinc-900 border border-amber-700 rounded-xl p-5">
      <h3 class="font-medium text-amber-400 mb-3">Your turn – Prove understanding</h3>
      
      <label class="block text-sm text-zinc-400 mb-1">Explain-back (in your own words)</label>
      <textarea id="explain-back" rows="3"
                class="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm mb-4 focus:outline-none focus:border-zinc-500"
                placeholder="What was done in this step and what was difficult?"></textarea>

      ${questionsHtml}

      <button onclick="submitAnswers()"
              class="bg-amber-600 hover:bg-amber-500 text-white font-medium px-6 py-3 rounded-xl transition">
        Submit Answers
      </button>
    </div>
  `;
}

async function submitAnswers() {
  const explainBack = document.getElementById("explain-back").value.trim();
  const answers = currentQuestions.map((_, i) => {
    const el = document.getElementById(`answer-${i}`);
    return el ? el.value.trim() : "";
  });

  if (!explainBack || explainBack.length < 30) {
    alert("Please write a longer explain-back (at least a few sentences).");
    return;
  }

  const res = await fetch("/submit-answers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ explain_back: explainBack, answers: answers })
  });

  const data = await res.json();

  if (data.status === "passed") {
    document.getElementById("gate-area").innerHTML = `
      <div class="bg-emerald-900/40 border border-emerald-700 rounded-xl p-5">
        <h3 class="font-medium text-emerald-400 mb-2">Gate Passed</h3>
        <p class="text-sm">${data.feedback || "You demonstrated understanding. Next step unlocked."}</p>
      </div>`;
    return;
  }

  if (data.status === "blocked_by_learning") {
    showLearningPath(data);
    return;
  }

  alert(data.reason || data.feedback || "Something went wrong");
}

function showLearningPath(data) {
  document.getElementById("gate-area").innerHTML = `
    <div class="bg-amber-900/30 border border-amber-700 rounded-xl p-5">
      <h3 class="font-medium text-amber-400 mb-3">Gate Blocked – Learning Path Required</h3>
      <p class="text-sm text-zinc-400 mb-3">${data.feedback || ""}</p>
      <pre class="text-sm whitespace-pre-wrap bg-zinc-950 p-4 rounded-lg mb-4">${data.learning_path || "No path returned"}</pre>

      <label class="block text-sm text-zinc-400 mb-1">Confirm what you learned</label>
      <textarea id="learning-confirmation" rows="3"
                class="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm mb-4"
                placeholder="Short summary of what you now understand..."></textarea>

      <button onclick="completeLearning()"
              class="bg-amber-600 hover:bg-amber-500 text-white font-medium px-6 py-3 rounded-xl transition">
        Complete Learning Path
      </button>
    </div>
  `;
}

async function completeLearning() {
  const confirmation = document.getElementById("learning-confirmation").value.trim();

  if (!confirmation || confirmation.length < 15) {
    alert("Please write a short confirmation of what you learned.");
    return;
  }

  const res = await fetch("/complete-learning", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmation: confirmation })
  });

  const data = await res.json();

  if (data.status === "passed") {
    document.getElementById("gate-area").innerHTML = `
      <div class="bg-emerald-900/40 border border-emerald-700 rounded-xl p-5">
        <h3 class="font-medium text-emerald-400 mb-2">Learning Path Completed</h3>
        <p class="text-sm">Next step unlocked.</p>
      </div>`;
  } else {
    alert(data.reason || "Confirmation rejected");
  }
}