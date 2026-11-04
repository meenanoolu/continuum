"""
Personal memory.

Memory is only worth having if it CHANGES what the system does. This one drives three things:
  1. Orchestrator planning   (weak concepts -> smaller steps / extra research step)
  2. Gate strictness         (parroting, shallow answers, repeated failures -> stricter Gate)
  3. Plan revision           (repeated failures -> re-plan with a prerequisite step)

Everything is stored locally in one JSON file the person owns.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import console, ensure_dir, get_env, load_json, save_json

PATTERN_LABELS = {
    "parroting": "copying the explanation instead of reasoning",
    "shallow_explain": "very short explain-backs",
    "fast_submit": "answers submitted within seconds",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm_concept(concept: str) -> str:
    c = re.sub(r"\s+", " ", (concept or "").strip().lower())
    return c[:60] or "unnamed concept"


class PersonalMemory:
    def __init__(self, path: str | None = None):
        self.path = Path(path or get_env("MEMORY_PATH", "./data/personal_memory.json"))
        ensure_dir(self.path.parent)
        self.data = self._migrate(load_json(self.path, default=self._empty()))

    # ---------------- structure ----------------
    def _empty(self) -> dict[str, Any]:
        return {
            "version": 2,
            "user_id": "default",
            "projects": {},
            "concepts": {},
            "patterns": {k: 0 for k in PATTERN_LABELS},
            "created_at": _now(),
            "updated_at": _now(),
        }

    def _migrate(self, data: dict[str, Any]) -> dict[str, Any]:
        base = self._empty()
        for key in ("user_id", "projects", "created_at"):
            if key in data:
                base[key] = data[key]
        base["concepts"] = data.get("concepts", {})
        base["patterns"].update(data.get("patterns", {}))
        # older memory files: carry over mastered concepts so nothing the person already learned is lost
        for c in data.get("global_patterns", {}).get("mastered_concepts", []):
            slot = base["concepts"].setdefault(norm_concept(c), self._concept_slot())
            if slot["passes"] == 0:
                slot["passes"], slot["last_outcome"] = 1, "pass"
        return base

    @staticmethod
    def _concept_slot() -> dict[str, Any]:
        return {"passes": 0, "failures": 0, "last_outcome": None, "last_seen": None}

    def save(self) -> None:
        self.data["updated_at"] = _now()
        save_json(self.data, self.path)

    def reset(self) -> None:
        self.data = self._empty()
        self.save()

    def get_project(self, project_name: str) -> dict[str, Any]:
        proj = self.data["projects"].setdefault(project_name, {})
        for key in ("reflections", "difficulties", "plan_revisions", "gate_outcomes", "concepts_learned", "completed_steps"):
            proj.setdefault(key, [])
        return proj

    # ---------------- recording ----------------
    def add_reflection(self, project_name: str, step: str, reflection: dict[str, str], explanation: str) -> None:
        self.get_project(project_name)["reflections"].append(
            {"timestamp": _now(), "step": step, "reflection": reflection, "explanation": explanation}
        )
        self.save()

    def record_gate(
        self,
        project_name: str,
        step: str,
        concept: str,
        passed: bool,
        score: float,
        signals: dict[str, bool],
        attempt: int,
    ) -> None:
        """One human attempt at a Gate. Updates concept stats, behavior patterns and the project log."""
        proj = self.get_project(project_name)
        key = norm_concept(concept)
        slot = self.data["concepts"].setdefault(key, self._concept_slot())
        slot["passes" if passed else "failures"] += 1
        slot["last_outcome"] = "pass" if passed else "fail"
        slot["last_seen"] = _now()
        for sig, flagged in signals.items():
            if flagged and sig in self.data["patterns"]:
                self.data["patterns"][sig] += 1
        proj["gate_outcomes"].append(
            {"timestamp": _now(), "step": step, "concept": key, "passed": passed,
             "score": round(score, 2), "attempt": attempt, "signals": [s for s, f in signals.items() if f]}
        )
        if not passed:
            proj["difficulties"].append({"timestamp": _now(), "step": step, "reason": f"failed understanding check on '{key}'"})
        elif key not in proj["concepts_learned"]:
            proj["concepts_learned"].append(key)
        self.save()

    def record_learning(self, project_name: str, concept: str, passed: bool) -> None:
        key = norm_concept(concept)
        slot = self.data["concepts"].setdefault(key, self._concept_slot())
        if passed:
            slot["passes"] += 1
            slot["last_outcome"] = "pass"
            proj = self.get_project(project_name)
            if key not in proj["concepts_learned"]:
                proj["concepts_learned"].append(key)
        else:
            slot["failures"] += 1
            slot["last_outcome"] = "fail"
        slot["last_seen"] = _now()
        self.save()

    def record_step_done(self, project_name: str, step: str) -> None:
        self.get_project(project_name)["completed_steps"].append({"timestamp": _now(), "step": step})
        self.save()

    def record_plan_revision(self, project_name: str, reason: str, new_plan_summary: str) -> None:
        self.get_project(project_name)["plan_revisions"].append(
            {"timestamp": _now(), "reason": reason, "new_plan_summary": new_plan_summary}
        )
        self.save()

    # ---------------- queries ----------------
    def weak_concepts(self, limit: int = 5) -> list[str]:
        weak = [
            (c, s["failures"]) for c, s in self.data["concepts"].items()
            if s["failures"] > 0 and (s["last_outcome"] == "fail" or s["failures"] > s["passes"])
        ]
        return [c for c, _ in sorted(weak, key=lambda x: -x[1])[:limit]]

    def mastered_concepts(self, limit: int = 8) -> list[str]:
        ok = [c for c, s in self.data["concepts"].items() if s["passes"] >= 1 and s["last_outcome"] == "pass"]
        return ok[-limit:]

    def has_mastered(self, concept: str) -> bool:
        return norm_concept(concept) in self.mastered_concepts(1000)

    def recent_outcomes(self, project_name: str, limit: int = 4) -> list[dict[str, Any]]:
        return self.get_project(project_name)["gate_outcomes"][-limit:]

    def get_recent_difficulties(self, project_name: str, limit: int = 5) -> list[dict]:
        return self.get_project(project_name)["difficulties"][-limit:]

    def gate_policy(self, project_name: str, concept: str | None = None) -> dict[str, Any]:
        """How hard should the next Gate be, and why? The reason is shown to the person."""
        reasons: list[str] = []
        pats = self.data["patterns"]
        recent = self.recent_outcomes(project_name, 4)
        recent_fails = sum(1 for o in recent if not o["passed"])
        if recent_fails >= 2:
            reasons.append(f"{recent_fails} of your last {len(recent)} checks in this project failed")
        if pats["parroting"] >= 2:
            reasons.append("you have repeated the explanation back instead of reasoning, twice or more")
        if pats["shallow_explain"] >= 3:
            reasons.append("your explain-backs are usually very short")
        if concept and norm_concept(concept) in self.weak_concepts(20):
            reasons.append(f"'{norm_concept(concept)}' is a concept you have struggled with before")
        strict = bool(reasons)
        return {
            "strictness": "strict" if strict else "standard",
            "questions": 3 if strict else 2,
            "pass_threshold": 1.4 if strict else 1.2,
            "weak_concepts": self.weak_concepts(3),
            "reasons": reasons,
        }

    def should_revise(self, project_name: str, already_revised_at: int) -> str | None:
        """Return a human-readable reason if the plan should be revised now, else None."""
        outcomes = self.get_project(project_name)["gate_outcomes"]
        if len(outcomes) <= already_revised_at:
            return None
        last = outcomes[-3:]
        fails = [o for o in last if not o["passed"]]
        if len(fails) >= 2:
            names = sorted({o["concept"] for o in fails})
            return f"repeated failed understanding checks on: {', '.join(names)}"
        return None

    def profile(self, project_name: str | None = None) -> dict[str, Any]:
        pats = self.data["patterns"]
        policy = self.gate_policy(project_name) if project_name else {"strictness": "standard", "reasons": []}
        return {
            "weak_concepts": self.weak_concepts(6),
            "mastered_concepts": self.mastered_concepts(8),
            "patterns": [
                {"key": k, "label": PATTERN_LABELS[k], "count": pats.get(k, 0)} for k in PATTERN_LABELS if pats.get(k, 0)
            ],
            "strictness": policy["strictness"],
            "strictness_reasons": policy["reasons"],
            "revisions": self.get_project(project_name)["plan_revisions"][-5:] if project_name else [],
            "attempts_logged": len(self.get_project(project_name)["gate_outcomes"]) if project_name else 0,
        }

    def get_context_for_orchestrator(self, project_name: str) -> str:
        p = self.profile(project_name)
        lines = [
            f"Concepts already mastered: {', '.join(p['mastered_concepts']) or 'none yet'}",
            f"Concepts they struggle with: {', '.join(p['weak_concepts']) or 'none yet'}",
        ]
        if p["patterns"]:
            lines.append("Behavior patterns: " + "; ".join(f"{x['label']} (x{x['count']})" for x in p["patterns"]))
        if p["strictness"] == "strict":
            lines.append("Gate is currently STRICT because: " + "; ".join(p["strictness_reasons"]))
        return "\n".join(lines)
