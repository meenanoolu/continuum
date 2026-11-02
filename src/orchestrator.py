"""
Orchestrator: owns the session. Plans the next piece of work, routes steps to Workers,
forces the Gate after every step, and re-plans when personal memory says the person is struggling.

State is persisted to data/session.json after every change, so a refresh or a server restart in the
middle of a demo never loses the plan or a pending Gate.
"""
from __future__ import annotations

import copy
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable

from src import trace
from src.gate import Gate
from src.memory import PersonalMemory
from src.models import LLMError, Models, get_models
from src.sandbox import Sandbox, SandboxError
from src.utils import console, ensure_dir, load_json, load_prompt, save_json
from src.workers import make_worker

KINDS = ("code", "test", "research")
IMAGE_RE = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=\s]+$")
MAX_IMAGE_CHARS = 7_000_000  # ~5 MB of image


class OrchestratorError(RuntimeError):
    """User-facing problem (bad input / wrong phase). The API maps it to HTTP 400/409."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "project"


def _guess_kind(title: str) -> str:
    t = title.lower()
    if any(w in t for w in ("test", "verify", "validate")):
        return "test"
    if any(w in t for w in ("research", "investigate", "read", "review", "find", "understand")):
        return "research"
    return "code"


def normalize_steps(raw: Any) -> list[dict[str, Any]]:
    steps = []
    for s in (raw or [])[:6]:
        if isinstance(s, str):
            s = {"title": s}
        if not isinstance(s, dict) or not str(s.get("title", "")).strip():
            continue
        title = str(s["title"]).strip()[:160]
        kind = str(s.get("kind", "")).lower()
        steps.append(
            {
                "title": title,
                "kind": kind if kind in KINDS else _guess_kind(title),
                "why": str(s.get("why", "")).strip()[:240],
                "concept": str(s.get("concept", "")).strip()[:60] or title[:40],
                "status": "pending",
            }
        )
    return steps


class Orchestrator:
    def __init__(
        self,
        models: Models | None = None,
        memory: PersonalMemory | None = None,
        workspace_dir: str | None = None,
        session_path: str | None = None,
    ):
        self.models = models or get_models()
        self.memory = memory or PersonalMemory()
        self.gate = Gate(self.models, self.memory)
        self.workspace_dir = Path(workspace_dir or os.getenv("WORKSPACE_DIR", "./workspace")).resolve()
        self.session_path = Path(session_path or os.getenv("SESSION_PATH", "./data/session.json"))
        ensure_dir(self.session_path.parent)
        self.lock = threading.RLock()
        self.sandbox: Sandbox | None = None
        self.state: dict[str, Any] = self._blank()
        self._load()

    # ---------------------------------------------------------------- state
    @staticmethod
    def _blank() -> dict[str, Any]:
        return {
            "phase": "idle",  # idle | planned | running | awaiting_human | learning | complete
            "project": None, "repo": None, "context_notes": None,
            "plan": [], "index": 0, "gate": None, "last_result": None,
            "revisions": [], "revised_at_outcomes": 0, "error": None,
        }

    def _save(self) -> None:
        save_json(self.state, self.session_path)

    def _load(self) -> None:
        data = load_json(self.session_path, default={})
        if not data or not data.get("project"):
            return
        self.state = {**self._blank(), **data}
        if self.state["phase"] == "running":  # server died mid-step; make the step re-runnable
            self.state["phase"] = "planned"
        self.sandbox = Sandbox(self.workspace_dir / _slug(self.state["project"]))
        self.sandbox.snapshot()

    def _require(self, *phases: str) -> None:
        if self.state["phase"] not in phases:
            raise OrchestratorError(f"Not allowed right now (phase: {self.state['phase']}).", 409)

    # ---------------------------------------------------------------- project + plan
    def start_project(self, name: str, repo: str | None = None) -> dict[str, Any]:
        with self.lock:
            if self.state["phase"] == "running":
                raise OrchestratorError("A step is running.", 409)
            name = name.strip()
            if not name:
                raise OrchestratorError("Project name is required.")
            self.state = {**self._blank(), "project": name}
            self.sandbox = Sandbox(self.workspace_dir / _slug(name))
            if repo and repo.strip():
                try:
                    self.state["repo"] = self.sandbox.attach_repo(repo.strip())
                except SandboxError as e:
                    raise OrchestratorError(str(e)) from e
            self.sandbox.snapshot()
            self.memory.get_project(name)
            self._save()
            return self.state

    @staticmethod
    def check_plan_text(user_plan: str) -> str:
        plan_text = (user_plan or "").strip()
        if len(plan_text) < 40 or len(plan_text.split()) < 8:
            raise OrchestratorError(
                "Plan is too vague. Describe only the NEXT meaningful piece of work in 2-4 concrete sentences."
            )
        return plan_text

    def require_plan(self, user_plan: str) -> list[dict[str, Any]]:
        with self.lock:
            if not self.state["project"]:
                raise OrchestratorError("Start a project first.")
            plan_text = self.check_plan_text(user_plan)
            if not self.models.any_available():
                raise OrchestratorError("No model configured. Set META_API_KEY and/or BASETEN_API_KEY in .env.", 503)

            ctx = [f"Project: {self.state['project']}", self.memory.get_context_for_orchestrator(self.state["project"])]
            if self.state["repo"]:
                r = self.state["repo"]
                ctx.append("Attached repository files (under repo/):\n" + "\n".join(r["tree"][:40]))
                if r.get("readme"):
                    ctx.append("Repo README (start):\n" + r["readme"][:800])
            if self.state.get("context_notes"):
                ctx.append("Attached image (described by a vision model):\n" + self.state["context_notes"])
            data = self.models.json(
                "meta", "orchestrator.plan",
                [
                    {"role": "system", "content": load_prompt("planner")},
                    {"role": "user", "content": "\n\n".join(ctx) + f"\n\nPlan for the next piece of work:\n{plan_text}"},
                ],
                max_tokens=1500,
                validate=lambda d: isinstance(d, dict) and (d.get("steps") or d.get("needs_clarification")),
            )
            if data is None:
                raise OrchestratorError("The planner model did not return a usable plan. Try again.", 502)
            if data.get("needs_clarification"):
                raise OrchestratorError(f"Needs more detail: {data['needs_clarification']}")
            steps = normalize_steps(data["steps"])
            if not steps:
                raise OrchestratorError("The planner returned no steps. Try again with more detail.", 502)
            self.state.update(plan=steps, index=0, phase="planned", gate=None, last_result=None)
            self._save()
            return steps

    # ---------------------------------------------------------------- step execution
    def run_step(self, emit: Callable[[str, str], None]) -> dict[str, Any]:
        with self.lock:
            self._require("planned")
            if self.state["index"] >= len(self.state["plan"]):
                self.state["phase"] = "complete"
                self._save()
                return self.state
            step = self.state["plan"][self.state["index"]]
            step["status"] = "running"
            self.state.update(phase="running", error=None)
            self._save()
        try:
            emit("info", f"Step {self.state['index'] + 1}: {step['title']} [{step['kind']} worker]")
            worker = make_worker(step["kind"], self.models, self.sandbox, emit)  # type: ignore[arg-type]
            result = worker.run(step, self._worker_context())
            emit("verify", f"Independent check: {result.evidence.headline}")
            emit("info", "Gate: preparing reflection and check questions")
            policy = self.memory.gate_policy(self.state["project"], step["concept"])
            gate = self.gate.prepare(self.state["project"], step, result.for_gate(), policy)
            gate["worker_text"] = result.for_gate()
            with self.lock:
                self.state.update(phase="awaiting_human", gate=gate, last_result=result.to_dict())
                step["status"] = "awaiting_gate"
                self._save()
            emit("gate", "Gate is locked until you prove understanding")
        except Exception as e:
            with self.lock:
                step["status"] = "pending"
                self.state.update(phase="planned", error=str(e)[:300])
                self._save()
            emit("error", f"{type(e).__name__}: {str(e)[:200]}")
        return self.state

    def _worker_context(self) -> str:
        bits = []
        done = [s["title"] for s in self.state["plan"] if s["status"] == "done"]
        if done:
            bits.append("Already done in this plan: " + "; ".join(done))
        files = self.sandbox.list_files(60) if self.sandbox else []
        bits.append("Workspace files: " + (", ".join(files) or "(empty)"))
        r = self.state.get("repo")
        if r:
            bits.append("An existing repository was attached under repo/ (edit files there).")
            if r.get("log"):
                bits.append("Recent commits:\n" + r["log"])
        return "\n".join(bits)

    # ---------------------------------------------------------------- gate
    def submit_answers(self, explain_back: str, answers: list[str]) -> dict[str, Any]:
        with self.lock:
            self._require("awaiting_human")
            gate, step = self.state["gate"], self.state["plan"][self.state["index"]]
            result = self.gate.evaluate(
                self.state["project"], step, gate, explain_back, answers, gate["worker_text"]
            )
            if result["status"] == "passed":
                self._advance(step)
            elif result["status"] == "blocked_by_learning":
                self.state["phase"] = "learning"
                step["status"] = "blocked"
                reason = self.memory.should_revise(self.state["project"], self.state["revised_at_outcomes"])
                if reason:
                    result["revision"] = self._revise(reason, from_gate=True)
            self._save()
            result["state"] = self.snapshot()
            return result

    def complete_learning(self, confirmation: str, retry_answer: str) -> dict[str, Any]:
        with self.lock:
            self._require("learning")
            step = self.state["plan"][self.state["index"]]
            result = self.gate.complete_learning(self.state["project"], self.state["gate"], confirmation, retry_answer)
            if result["status"] == "passed":
                self._advance(step)
            self._save()
            result["state"] = self.snapshot()
            return result

    def _advance(self, step: dict[str, Any]) -> None:
        revised = bool((self.state["gate"] or {}).get("revised"))
        if revised:
            # The plan was re-written while this Gate was open: index already points at the new first step.
            step["status"] = "replaced"
        else:
            step["status"] = "done"
            self.state["index"] += 1
        self.memory.record_step_done(self.state["project"], step["title"])
        if self.sandbox:
            self.sandbox.snapshot()  # next diff shows only the next step's changes
        self.state["gate"] = None
        self.state["phase"] = "complete" if self.state["index"] >= len(self.state["plan"]) else "planned"

    # ---------------------------------------------------------------- revision
    def revise_plan(self, reason: str | None = None) -> dict[str, Any]:
        with self.lock:
            self._require("planned", "learning", "awaiting_human")
            return self._revise(reason or "you asked for a revision", from_gate=self.state["phase"] != "planned")

    def _revise(self, reason: str, from_gate: bool) -> dict[str, Any]:
        project = self.state["project"]
        remaining = self.state["plan"][self.state["index"]:]
        user = (
            f"Why we are re-planning: {reason}\n\nRemaining steps:\n"
            + "\n".join(f"- [{s['kind']}] {s['title']} (concept: {s['concept']})" for s in remaining)
            + f"\n\nPersonal memory:\n{self.memory.get_context_for_orchestrator(project)}"
        )
        data = self.models.json(
            "meta", "orchestrator.revise",
            [{"role": "system", "content": load_prompt("reviser")}, {"role": "user", "content": user}],
            max_tokens=1500,
            validate=lambda d: isinstance(d, dict) and d.get("steps"),
        )
        steps = normalize_steps(data["steps"]) if data else []
        outcomes = len(self.memory.get_project(project)["gate_outcomes"])
        self.state["revised_at_outcomes"] = outcomes
        if not steps:
            return {"revised": False, "reason": reason}
        for s in remaining:
            if s["status"] in ("blocked", "awaiting_gate", "running"):
                s["status"] = "replaced"
        head = [s for s in self.state["plan"][: self.state["index"]]]
        replaced = [s for s in remaining if s["status"] == "replaced"]
        self.state["plan"] = head + replaced + steps
        self.state["index"] = len(head) + len(replaced)
        summary = str((data or {}).get("reason_summary") or reason)
        rev = {"reason": reason, "summary": summary, "new_steps": [s["title"] for s in steps]}
        self.state["revisions"].append(rev)
        self.memory.record_plan_revision(project, reason, " -> ".join(rev["new_steps"][:3]))
        if from_gate and self.state["gate"] is not None:
            self.state["gate"]["revised"] = True
        console.print(f"[bold yellow]Plan revised:[/bold yellow] {summary}")
        return {"revised": True, **rev}

    # ---------------------------------------------------------------- images
    def attach_image(self, data_url: str, purpose: str) -> str:
        if not IMAGE_RE.match(data_url or "") or len(data_url) > MAX_IMAGE_CHARS:
            raise OrchestratorError("Attach a PNG, JPEG, GIF or WebP image under about 5 MB.")
        with self.lock:
            if purpose == "gate":
                self._require("awaiting_human", "learning")
                instruction = (
                    "Describe precisely what this image shows (diagram elements and arrows, UI, code, visible text) "
                    "so a teacher can check whether someone's explanation of their work matches it. Be literal."
                )
            else:
                purpose = "context"
                instruction = (
                    "Describe this image as context for planning a software task: UI layout, diagram structure, "
                    "error messages or code you can read. Be literal and concise."
                )
        try:
            notes = self.models.describe_image(data_url, instruction, purpose=f"vision.{purpose}")
        except LLMError as e:
            raise OrchestratorError(f"Vision model unavailable: {str(e)[:150]}", 502) from e
        with self.lock:
            if purpose == "gate" and self.state["gate"]:
                self.state["gate"]["image_notes"] = notes
            else:
                self.state["context_notes"] = notes
            self._save()
        return notes

    # ---------------------------------------------------------------- views
    def abandon(self) -> None:
        with self.lock:
            if self.state["phase"] == "running":
                raise OrchestratorError("A step is running.", 409)
            self.state = self._blank()
            self.sandbox = None
            self._save()

    def snapshot(self) -> dict[str, Any]:
        s = copy.deepcopy(self.state)
        gate = s.get("gate")
        if gate:
            gate.pop("worker_text", None)
            gate.pop("started_at", None)
        project = s["project"]
        return {
            **s,
            "gate": gate,
            "memory": self.memory.profile(project) if project else self.memory.profile(None),
            "models": self.models.status(),
            "trace": trace.recent(14),
        }
