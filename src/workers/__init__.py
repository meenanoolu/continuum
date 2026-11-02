from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from src.agent import AgentRun, Emit, Evidence, ToolAgent, verify
from src.models import Models
from src.sandbox import Sandbox
from src.utils import load_prompt


@dataclass
class WorkerResult:
    kind: str
    summary: str
    mode: str
    files_changed: list[str]
    diff: str
    evidence: Evidence
    runs: list[dict[str, Any]] = field(default_factory=list)
    models_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "summary": self.summary, "mode": self.mode,
            "files_changed": self.files_changed, "diff": self.diff,
            "evidence": self.evidence.to_dict(), "runs": self.runs, "models_used": self.models_used,
        }

    def for_gate(self) -> str:
        """Ground-truth text handed to the Gate (evidence first, the Worker's story last)."""
        ev = self.evidence
        parts = [f"EVIDENCE LEVEL: {ev.level} - {ev.headline}"]
        if ev.tests:
            parts.append(f"Independent test run (exit {ev.tests['exit_code']}):\n{ev.tests['output'][-1500:]}")
        if ev.compile and ev.compile["exit_code"] not in (0, 5):
            parts.append(f"Compile errors:\n{ev.compile['output'][-800:]}")
        parts.append("Files changed: " + (", ".join(self.files_changed) or "none"))
        if self.diff:
            parts.append(f"Diff:\n{self.diff[:3500]}")
        parts.append(f"Worker's own summary (unverified claim):\n{self.summary[:1200]}")
        return "\n\n".join(parts)


class BaseWorker:
    kind = "code"
    prompt_name = "worker_code"
    tools = ["list_files", "read_file", "write_file", "run_python", "run_tests"]
    changes_code = True

    def __init__(self, models: Models, sandbox: Sandbox, emit: Emit):
        self.models = models
        self.sandbox = sandbox
        self.emit = emit

    def run(self, step: dict[str, Any], context: str = "") -> WorkerResult:
        task = f"Step: {step['title']}\nWhy: {step.get('why', '')}\n"
        if context:
            task += f"\nProject context:\n{context}\n"
        run = self._execute(load_prompt(self.prompt_name), task)
        ev = verify(self.sandbox, run.summary, self.changes_code)
        return WorkerResult(
            kind=self.kind,
            summary=run.summary or "(no summary)",
            mode=run.mode,
            files_changed=self.sandbox.changed_files(),
            diff=self.sandbox.diff(),
            evidence=ev,
            runs=[r.to_dict() for r in run.runs],
            models_used=run.models_used,
        )

    def _execute(self, system: str, task: str) -> AgentRun:
        return ToolAgent(self.models, self.sandbox, self.emit, self.tools).run(system, task)


class CodeWorker(BaseWorker):
    kind = "code"

    def _execute(self, system: str, task: str) -> AgentRun:
        if os.getenv("USE_MUSE_CODE") == "1":
            run = self._muse_code(task)
            if run is not None:
                return run
            self.emit("info", "Muse Code unavailable or failed; using the built-in tool loop")
        return super()._execute(system, task)

    def _muse_code(self, task: str) -> AgentRun | None:
        """Delegate coding to Meta's Muse Code CLI (`muse exec`), then verify independently.

        Opt-in (USE_MUSE_CODE=1). Needs the `muse` binary and META_API_KEY. Muse Code keeps its own
        sandbox on; we never pass --yolo.
        """
        if shutil.which("muse") is None or not os.getenv("META_API_KEY"):
            return None
        prompt = task + "\nWrite a pytest test file for your change and run it. End with a short honest summary."
        self.emit("info", "Delegating to Muse Code (muse exec)")
        try:
            proc = subprocess.run(
                ["muse", "exec", "--json", "--max-model-steps", "15", prompt],
                cwd=self.sandbox.root, capture_output=True, text=True, timeout=300,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if proc.returncode != 0:
            return None
        summary = ""
        for line in proc.stdout.splitlines():
            try:
                ev = json.loads(line)
            except Exception:
                continue
            for key in ("text", "message", "content", "summary"):
                val = ev.get(key) if isinstance(ev, dict) else None
                if isinstance(val, str) and val.strip():
                    summary = val.strip()
        run = AgentRun(summary=summary or proc.stdout[-800:], mode="muse_code")
        run.models_used.append("muse-code")
        return run


class TestWorker(BaseWorker):
    __test__ = False  # not a pytest class
    kind = "test"
    prompt_name = "worker_test"


class ResearchWorker(BaseWorker):
    kind = "research"
    prompt_name = "worker_research"
    tools = ["list_files", "read_file"]
    changes_code = False


WORKERS = {"code": CodeWorker, "test": TestWorker, "research": ResearchWorker}


def make_worker(kind: str, models: Models, sandbox: Sandbox, emit: Emit) -> BaseWorker:
    return WORKERS.get(kind, CodeWorker)(models, sandbox, emit)


__all__ = ["WorkerResult", "CodeWorker", "TestWorker", "ResearchWorker", "make_worker"]
