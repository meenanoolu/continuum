from __future__ import annotations
from typing import Any
from src.models import MuseSparkClient, OpenWeightClient
from src.memory import PersonalMemory
from src.gate import Gate
from src.utils import console
from pathlib import Path

class Orchestrator:
    """
    Central controller of Continuum.
    - Demands a concrete next-piece plan
    - Breaks it into steps
    - Assigns steps to Workers
    - Forces the Gate after every important step
    - Uses personal memory to adapt
    - Can revise the plan when repeated difficulty appears
    """

    def __init__(self):
        self.muse = MuseSparkClient()
        self.open_weight = OpenWeightClient()
        self.memory = PersonalMemory()
        self.gate = Gate(self.muse, self.memory)
        self.prompts_dir = Path("prompts")

        self.current_project: str | None = None
        self.current_plan: list[str] = []
        self.current_step_index: int = 0

    def _load_prompt(self, name: str) -> str:
        path = self.prompts_dir / f"{name}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def start_project(self, project_name: str) -> None:
        self.current_project = project_name
        self.current_plan = []
        self.current_step_index = 0
        console.print(f"\n[bold blue]Continuum started on project: {project_name}[/bold blue]")
        console.print(self.memory.get_context_for_orchestrator(project_name))

    def require_plan(self, user_plan: str) -> list[str]:
        """
        The session cannot begin without a short, concrete plan
        for only the next meaningful piece of work.
        """
        if not user_plan or len(user_plan.strip()) < 20:
            raise ValueError(
                "Plan is too vague. Give a short, concrete plan for only the next meaningful piece of work."
            )

        system = self._load_prompt("orchestrator") + (
            "\n\nYou receive a user's plan for the next meaningful piece of work. "
            "Break it into 3-7 clear, ordered, actionable steps. "
            "Reply with a numbered list only. No extra commentary."
        )

        raw = self.muse.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"User plan:\n{user_plan}"},
            ],
            temperature=0.2,
            max_tokens=600,
        )

        steps = []
        for line in raw.splitlines():
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-")):
                # Remove leading number/bullet
                clean = line.lstrip("0123456789.-) ").strip()
                if clean:
                    steps.append(clean)

        if not steps:
            steps = [user_plan.strip()]

        self.current_plan = steps
        self.current_step_index = 0

        console.print("\n[bold]Plan accepted and broken into steps:[/bold]")
        for i, s in enumerate(steps, 1):
            console.print(f"  {i}. {s}")

        return steps

    def run_next_step(self, worker_output: str | None = None) -> dict[str, Any]:
        """
        Runs the next step in the plan.
        For the 10-day version we simulate the Worker output if none is provided,
        then immediately force the Gate.
        """
        if not self.current_project or not self.current_plan:
            raise RuntimeError("No active project or plan. Call start_project() and require_plan() first.")

        if self.current_step_index >= len(self.current_plan):
            console.print("[green]All steps in the current plan are complete.[/green]")
            return {"status": "plan_complete"}

        step = self.current_plan[self.current_step_index]
        console.print(f"\n[bold magenta]→ Executing step {self.current_step_index + 1}: {step}[/bold magenta]")

        # In the full version the Worker would run here.
        # For now we accept an external worker_output or create a placeholder.
        if worker_output is None:
            worker_output = f"[Worker placeholder output for: {step}]"

        # Force the Gate
        gate_result = self.gate.run(
            project_name=self.current_project,
            step=step,
            worker_output=worker_output,
        )

        if not gate_result["passed"]:
            console.print("\n[bold red]GATE BLOCKED – learning path must be completed before continuing[/bold red]")
            console.print(gate_result["learning_path"])
            return {
                "status": "blocked_by_gate",
                "gate": gate_result,
            }

        # Gate passed → advance
        self.current_step_index += 1
        console.print(f"[green]Gate passed. Moving to next step.[/green]")

        # Simple repeated-difficulty check
        recent = self.memory.get_recent_difficulties(self.current_project, limit=3)
        if len(recent) >= 2:
            console.print("[yellow]Repeated difficulty detected – consider plan revision[/yellow]")

        return {
            "status": "step_complete",
            "gate": gate_result,
            "remaining_steps": len(self.current_plan) - self.current_step_index,
        }

    def revise_plan(self, reason: str) -> list[str]:
        """Called when repeated difficulty appears."""
        if not self.current_project:
            raise RuntimeError("No active project")

        remaining = self.current_plan[self.current_step_index:]
        context = self.memory.get_context_for_orchestrator(self.current_project)

        system = (
            "You are the Continuum Orchestrator. The user is hitting repeated difficulty. "
            "Revise the remaining plan to be more realistic and to include necessary learning. "
            "Reply with a new numbered list of steps only."
        )

        user_content = (
            f"Reason for revision: {reason}\n"
            f"Remaining steps:\n" + "\n".join(f"- {s}" for s in remaining) + "\n\n"
            f"User memory context:\n{context}"
        )

        raw = self.muse.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=600,
        )

        new_steps = []
        for line in raw.splitlines():
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-")):
                clean = line.lstrip("0123456789.-) ").strip()
                if clean:
                    new_steps.append(clean)

        if new_steps:
            self.current_plan = self.current_plan[:self.current_step_index] + new_steps
            self.memory.record_plan_revision(
                self.current_project,
                reason,
                " → ".join(new_steps[:3]) + ("..." if len(new_steps) > 3 else ""),
            )
            console.print("[bold yellow]Plan revised:[/bold yellow]")
            for i, s in enumerate(new_steps, 1):
                console.print(f"  {i}. {s}")

        return new_steps