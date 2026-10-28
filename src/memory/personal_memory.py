from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from pathlib import Path
from src.utils import load_json, save_json, ensure_dir, get_env, console

class PersonalMemory:
    """
    Simple but persistent personal memory.
    Stores reflections, difficulties, concepts learned, and patterns.
    Designed so the Orchestrator can already use it in the 10-day version.
    """

    def __init__(self, path: str | None = None):
        self.path = Path(path or get_env("MEMORY_PATH", "./data/personal_memory.json"))
        ensure_dir(self.path.parent)
        self.data = load_json(self.path, default=self._empty())

    def _empty(self) -> dict[str, Any]:
        return {
            "user_id": "default",
            "projects": {},
            "global_patterns": {
                "repeated_difficulties": [],
                "mastered_concepts": [],
                "skip_tendencies": [],
                "momentum_loss_points": [],
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_json(self.data, self.path)

    def get_project(self, project_name: str) -> dict[str, Any]:
        if project_name not in self.data["projects"]:
            self.data["projects"][project_name] = {
                "reflections": [],
                "concepts_learned": [],
                "difficulties": [],
                "completed_steps": [],
                "plan_revisions": [],
            }
        return self.data["projects"][project_name]

    def add_reflection(
        self,
        project_name: str,
        step: str,
        reflection: dict[str, str],
        explanation: str,
    ) -> None:
        project = self.get_project(project_name)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step": step,
            "reflection": reflection,
            "explanation": explanation,
        }
        project["reflections"].append(entry)
        self.save()
        console.print(f"[cyan]Memory: reflection saved for step '{step}'[/cyan]")

    def add_difficulty(self, project_name: str, step: str, reason: str) -> None:
        project = self.get_project(project_name)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step": step,
            "reason": reason,
        }
        project["difficulties"].append(entry)

        # Also track globally for pattern learning
        self.data["global_patterns"]["repeated_difficulties"].append(
            {"step": step, "reason": reason, "project": project_name}
        )
        self.save()

    def add_concept_learned(self, project_name: str, concept: str) -> None:
        project = self.get_project(project_name)
        if concept not in project["concepts_learned"]:
            project["concepts_learned"].append(concept)

        if concept not in self.data["global_patterns"]["mastered_concepts"]:
            self.data["global_patterns"]["mastered_concepts"].append(concept)

        self.save()
        console.print(f"[cyan]Memory: concept marked as learned → {concept}[/cyan]")

    def has_mastered(self, concept: str) -> bool:
        return concept in self.data["global_patterns"]["mastered_concepts"]

    def get_recent_difficulties(self, project_name: str, limit: int = 5) -> list[dict]:
        project = self.get_project(project_name)
        return project["difficulties"][-limit:]

    def get_context_for_orchestrator(self, project_name: str) -> str:
        """
        Returns a short text summary the Orchestrator can put in its prompt
        so it already knows the user's patterns.
        """
        project = self.get_project(project_name)
        global_p = self.data["global_patterns"]

        lines = [
            f"Project: {project_name}",
            f"Concepts already mastered: {', '.join(global_p['mastered_concepts'][-8:]) or 'none yet'}",
            f"Recent difficulties in this project: {len(project['difficulties'])}",
        ]

        if project["difficulties"]:
            last = project["difficulties"][-3:]
            for d in last:
                lines.append(f"- {d['step']}: {d['reason']}")

        if global_p["repeated_difficulties"]:
            lines.append("Global repeated difficulty patterns exist. Be stricter on similar steps.")

        return "\n".join(lines)

    def record_plan_revision(self, project_name: str, reason: str, new_plan_summary: str) -> None:
        project = self.get_project(project_name)
        project["plan_revisions"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "new_plan_summary": new_plan_summary,
        })
        self.save()