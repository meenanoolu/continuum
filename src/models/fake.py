"""
Deterministic offline stand-in for the Meta endpoints.

Used ONLY for tests and for developing the UI without spending credits (CONTINUUM_FAKE_LLM=1).
It is never used silently: the UI health badge and README both say when it is active.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .client import Completion

CALC = "def add(a, b):\n    return a + b\n"
TEST_OK = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n\ndef test_add_negative():\n    assert add(-1, 1) == 0\n"
TEST_BAD = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 6\n"


def _text(messages: list[dict[str, Any]]) -> str:
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        out.append(str(c or ""))
    return "\n".join(out)


class FakeLLM:
    available = True

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model

    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def _done(self, content: str = "", tool_calls: list | None = None) -> Completion:
        raw: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            raw["tool_calls"] = tool_calls
        return Completion(
            content=content, tool_calls=tool_calls or [], finish_reason="tool_calls" if tool_calls else "stop",
            provider=self.provider, model=self.model, tokens=10, raw_message=raw,
        )

    @staticmethod
    def _call(i: int, name: str, args: dict) -> dict:
        return {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}

    def complete(self, messages, *, purpose="chat", max_tokens=1000, temperature=None, tools=None) -> Completion:
        text = _text(messages)
        from src import trace

        trace.record(purpose=purpose, provider=self.provider, model=self.model, ms=5, tokens=10, ok=True, note="FAKE")

        if purpose.startswith("worker") and tools:
            names = {t["function"]["name"] for t in tools}
            stage = sum(1 for m in messages if m.get("role") == "tool")
            if "write_file" not in names:  # research worker
                if stage == 0:
                    return self._done(tool_calls=[self._call(1, "list_files", {})])
                return self._done("Found the code is a single small module; recommend adding input checks.")
            bad = "FAIL_TESTS" in text
            script = [
                ("write_file", {"path": "calc.py", "content": CALC}),
                ("write_file", {"path": "test_calc.py", "content": TEST_BAD if bad else TEST_OK}),
                ("run_tests", {}),
            ]
            if stage < len(script):
                n, a = script[stage]
                return self._done(tool_calls=[self._call(stage + 1, n, a)])
            return self._done("Implemented add() in calc.py and all tests pass.")

        if purpose == "worker.text":
            return self._done(f"### FILE: calc.py\n```python\n{CALC}```\n### FILE: test_calc.py\n```python\n{TEST_OK}```\nDone.")

        if purpose.startswith("vision"):
            return self._done("A diagram with three boxes (client, API, database) joined by arrows.")

        if purpose == "orchestrator.plan":
            tag = " FAIL_TESTS" if "FAIL_TESTS" in text else ""
            steps = [
                {"title": "Implement add() in calc.py" + tag, "kind": "code", "why": "Core behavior first.", "concept": "pure functions"},
                {"title": "Write edge-case tests for calc", "kind": "test", "why": "Prove it works.", "concept": "unit testing"},
                {"title": "Review the module for gaps", "kind": "research", "why": "Find missing cases.", "concept": "edge cases"},
            ]
            return self._done(json.dumps({"steps": steps}))

        if purpose == "orchestrator.revise":
            steps = [
                {"title": "Hand-trace add() for three inputs", "kind": "research", "why": "Rebuild the intuition.", "concept": "unit testing"},
                {"title": "Write one more test for calc", "kind": "test", "why": "Apply it.", "concept": "unit testing"},
            ]
            return self._done(json.dumps({"reason_summary": "Added a prerequisite trace step after two failed checks.", "steps": steps}))

        if purpose == "gate.prepare":
            n = int((re.search(r"ask exactly (\d+)", text) or [0, 3])[1])
            concept = (re.search(r"Intended concept: (.+)", text) or [0, "pure functions"])[1].strip()
            data = {
                "concept": concept,
                "reflection": {
                    "what_happened": "A small calc module and tests were written and run.",
                    "what_worked": "Tests ran and passed in the sandbox.",
                    "what_was_difficult": "Choosing which edge cases matter.",
                    "why": "Addition looks trivial but hides type and sign cases.",
                },
                "explanation": "add() is a pure function: output depends only on inputs, with no hidden state, which makes it trivial to test. Tests pin the behaviour so later edits cannot silently change it.",
                "questions": [
                    {"question": f"Why does add() in calc.py not need any setup before testing? (q{i + 1})", "type": "why", "focus": "calc.py"}
                    for i in range(n)
                ],
            }
            return self._done(json.dumps(data))

        if purpose == "gate.grade":
            nq = len(re.findall(r"^\d+\. Q:", text, re.M))
            bad = "dunno" in text.lower()
            s = 0 if bad else 2
            data = {
                "explain_back": {"score": s, "note": "fake"},
                "answers": [{"score": s, "note": "fake"} for _ in range(nq)],
                "visual_match": {"score": s, "note": "fake"} if "IMAGE THE HUMAN ATTACHED" in text else None,
                "feedback": "Fake grader feedback.",
                "missing_concepts": ["unit testing"] if bad else [],
                "demonstrated_concepts": [] if bad else ["pure functions"],
            }
            return self._done(json.dumps(data))

        if purpose == "gate.learning_path":
            data = {
                "concept": "unit testing", "why_it_mattered": "Tests pin behaviour.",
                "items": ["Re-read test_calc.py", "Predict the output of add(-1, 1)", "Explain it aloud"],
                "retry_question": "What does a unit test of a pure function need to set up, and why?",
            }
            return self._done(json.dumps(data))

        if purpose == "gate.learning_grade":
            s = 0 if "dunno" in text.lower() else 2
            return self._done(json.dumps({"score": s, "feedback": "Fake learning feedback."}))

        return self._done("ok")
