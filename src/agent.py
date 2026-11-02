"""
Tool-using agent loop for Workers (runs on Muse Spark Open via Baseten, falls back to Muse Spark).

Design principle: TRUST BUT VERIFY. Whatever the model says it did, `verify()` re-runs the tests /
compile check in the sandbox itself, and the Gate is shown that ground truth, not the model's story.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from src.models import LLMError, Models
from src.sandbox import RunResult, Sandbox, SandboxError
from src.utils import console

Emit = Callable[[str, str], None]  # (kind, text)

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_files": {
        "description": "List files in the workspace.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "read_file": {
        "description": "Read a text file from the workspace.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    "write_file": {
        "description": "Create or overwrite a text file in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    "run_python": {
        "description": "Run a python script from the workspace, e.g. 'main.py'.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    "run_tests": {
        "description": "Run pytest over the workspace.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def tool_defs(names: list[str]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": n, **TOOL_SCHEMAS[n]}} for n in names]


@dataclass
class AgentRun:
    summary: str = ""
    mode: str = "tool_calling"  # tool_calling | text_fallback | muse_code | none
    actions: list[dict[str, Any]] = field(default_factory=list)
    runs: list[RunResult] = field(default_factory=list)
    models_used: list[str] = field(default_factory=list)
    turns: int = 0


class ToolAgent:
    MAX_TURNS = 10

    def __init__(self, models: Models, sandbox: Sandbox, emit: Emit, tools: list[str]):
        self.models = models
        self.sandbox = sandbox
        self.emit = emit
        self.tools = tools

    # ------------------------------------------------------------------
    def run(self, system: str, task: str) -> AgentRun:
        """Prefer Muse Spark Open (open weights, Baseten): native tools, then text protocol.
        Only if both fail does the Meta API model take over, so the open model stays in charge when it can."""
        result = AgentRun()
        if self.models.open.available:
            out = self._tool_loop(system, task, result, only="open")
            if out is not None:
                return out
            self.emit("info", "Muse Spark Open did not accept native tool calls; using its text protocol")
            out = self._text_fallback(system, task, result, only="open")
            if out is not None:
                return out
            self.emit("info", "Falling back to the Meta API model for this step")
        out = self._tool_loop(system, task, result, only=None)
        if out is not None:
            return out
        result.summary, result.mode = "Worker failed: no model could run this step.", "none"
        return result

    def _tool_loop(self, system: str, task: str, result: AgentRun, only: str | None) -> AgentRun | None:
        """Returns None only when the very first call fails (so the caller can try another route)."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]
        defs = tool_defs(self.tools)
        for turn in range(self.MAX_TURNS):
            result.turns = turn + 1
            try:
                comp = self.models.complete("open", f"worker.{result.turns}", messages, max_tokens=2500, tools=defs, only=only)
            except LLMError as e:
                if turn == 0:
                    console.print(f"[yellow]tool loop failed on first call: {str(e)[:120]}[/yellow]")
                    return None
                result.summary = result.summary or f"Worker stopped: {e}"
                return result
            label = f"{comp.provider}:{comp.model}"
            if label not in result.models_used:
                result.models_used.append(label)

            if not comp.tool_calls:
                if turn == 0 and "### FILE:" in comp.content and "write_file" in self.tools:
                    self.emit("info", "Model answered with code blocks instead of tool calls; applying them")
                    return self._apply_file_blocks(comp.content, result)
                result.summary = comp.content
                return result

            messages.append(comp.raw_message)
            for call in comp.tool_calls:
                out = self._execute(call, result)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": out[:4000]})
        result.summary = result.summary or "Worker hit the turn limit before finishing."
        return result

    # ------------------------------------------------------------------
    def _execute(self, call: dict[str, Any], result: AgentRun) -> str:
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"]["arguments"] or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
        except Exception as e:
            return f"error: bad arguments ({e})"
        if name not in self.tools:
            return f"error: tool '{name}' is not available for this step"
        try:
            if name == "list_files":
                files = self.sandbox.list_files()
                self.emit("tool", "list_files")
                out = "\n".join(files) or "(empty workspace)"
            elif name == "read_file":
                self.emit("tool", f"read_file {args.get('path')}")
                out = self.sandbox.read_file(str(args.get("path", "")))
            elif name == "write_file":
                rel = self.sandbox.write_file(str(args.get("path", "")), str(args.get("content", "")))
                self.emit("tool", f"write_file {rel}")
                out = f"wrote {rel}"
            elif name == "run_python":
                r = self.sandbox.run(f"python {args.get('path', '')}")
                result.runs.append(r)
                self.emit("run" if r.ok else "fail", f"python {args.get('path')} -> exit {r.exit_code}")
                out = f"exit {r.exit_code}\n{r.output}"
            elif name == "run_tests":
                r = self.sandbox.run_tests()
                result.runs.append(r)
                self.emit("run" if r.ok else "fail", f"pytest -> exit {r.exit_code}")
                out = f"exit {r.exit_code}\n{r.output}"
            else:
                out = "error: unknown tool"
        except SandboxError as e:
            self.emit("fail", f"{name}: {e}")
            out = f"error: {e}"
        result.actions.append({"tool": name, "args": {k: (str(v)[:80]) for k, v in args.items()}})
        return out

    # ------------------------------------------------------------------
    _FILE_BLOCK = re.compile(r"###\s*FILE:\s*([^\n]+)\n```(?:\w+)?\n(.*?)```", re.DOTALL | re.IGNORECASE)

    def _apply_file_blocks(self, text: str, result: AgentRun) -> AgentRun:
        result.mode = "text_fallback"
        for rel, code in self._FILE_BLOCK.findall(text):
            try:
                rel = self.sandbox.write_file(rel.strip(), code.strip() + "\n")
                self.emit("tool", f"write_file {rel}")
                result.actions.append({"tool": "write_file", "args": {"path": rel}})
            except SandboxError as e:
                self.emit("fail", f"write_file: {e}")
        result.summary = "Implemented via text protocol (no native tool calling)."
        return result

    def _text_fallback(self, system: str, task: str, result: AgentRun, only: str | None) -> AgentRun | None:
        """No native tool calling: ask for FILE blocks and write them. Verification still runs afterwards."""
        fmt = (
            "\n\nOutput format (no tools available): reply with complete files as\n"
            "### FILE: relative/path.py\n```python\n<code>\n```\n"
            "Include a test file test_*.py. Then one short paragraph summary."
        )
        try:
            comp = self.models.complete(
                "open", "worker.text", [{"role": "system", "content": system + fmt}, {"role": "user", "content": task}],
                max_tokens=3500, only=only,
            )
        except LLMError:
            return None
        result.models_used.append(f"{comp.provider}:{comp.model}")
        if "write_file" in self.tools:
            return self._apply_file_blocks(comp.content, result)
        result.mode = "text_fallback"
        result.summary = comp.content
        return result


# ----------------------------------------------------------------------
@dataclass
class Evidence:
    level: str  # verified | compiles | failed | unverified | not_applicable
    headline: str
    tests: dict[str, Any] | None
    compile: dict[str, Any] | None
    claim_mismatch: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level, "headline": self.headline, "tests": self.tests,
            "compile": self.compile, "claim_mismatch": self.claim_mismatch,
        }


_SUCCESS_CLAIM = re.compile(r"(all (the )?tests? (pass|passed|passing)|tests? pass(ed)?|works? (correctly|as expected)|successfully)", re.I)


def verify(sandbox: Sandbox, summary: str, changes_expected: bool) -> Evidence:
    """Independent check, never trusting the Worker's own claim."""
    if not changes_expected:
        return Evidence("not_applicable", "Research step: nothing to execute.", None, None)
    comp = sandbox.compile_check()
    tests = sandbox.run_tests() if sandbox.has_tests() else None
    if tests is not None:
        level = "verified" if tests.ok else "failed"
        headline = "Tests passed (re-run independently)" if tests.ok else "Tests FAILED when re-run independently"
    elif comp.exit_code == 0:
        level, headline = "compiles", "Code compiles, but no tests exist to prove behavior"
    elif comp.exit_code == 5:
        level, headline = "unverified", "No code was produced to verify"
    else:
        level, headline = "failed", "Code does not compile"
    mismatch = level in ("failed", "unverified") and bool(_SUCCESS_CLAIM.search(summary or ""))
    if mismatch:
        headline += " - the Worker claimed success"
    console.print(f"[dim]verify: {level}[/dim]")
    return Evidence(level, headline, tests.to_dict() if tests else None, comp.to_dict(), mismatch)
