from __future__ import annotations
from curses import raw
from typing import Any
from src.models import MuseSparkClient
from src.memory import PersonalMemory
from src.utils import console
from pathlib import Path

class Gate:
    """
    Enforces the three required pieces after every important step:
    1. Structured Reflection
    2. Plain-language Explanation
    3. Learning Path (only if a missing concept is detected)
    """

    def __init__(self, muse: MuseSparkClient, memory: PersonalMemory):
        self.muse = muse
        self.memory = memory
        self.prompts_dir = Path("prompts")

    def _load_prompt(self, name: str) -> str:
        path = self.prompts_dir / f"{name}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def run(
        self,
        project_name: str,
        step: str,
        worker_output: str,
        user_question: str | None = None,
    ) -> dict[str, Any]:
        """
        Runs the full gate.
        Returns a dict with reflection, explanation, learning_path (or None), and passed=True/False.
        """
        console.print(f"\n[bold yellow]═══ GATE triggered for step: {step} ═══[/bold yellow]")

        # 1. Reflection
        reflection = self._generate_reflection(step, worker_output)
        console.print("[green]✓ Reflection generated[/green]")

        # 2. Explanation
        explanation = self._generate_explanation(step, reflection, worker_output)
        console.print("[green]✓ Explanation generated[/green]")

        # 3. Detect missing concept + optional learning path
        missing_concept, learning_path = self._detect_and_create_learning(
            project_name, step, reflection, user_question
        )

        if learning_path:
            console.print(f"[yellow]⚠ Missing concept detected: {missing_concept}[/yellow]")
            console.print("[yellow]Learning path created – must be completed before next step[/yellow]")
        else:
            console.print("[green]✓ No missing concept – gate can pass[/green]")

        # Save to personal memory
        self.memory.add_reflection(project_name, step, reflection, explanation)

        if "difficult" in str(reflection).lower() or "hard" in str(reflection).lower():
            self.memory.add_difficulty(
                project_name,
                step,
                reflection.get("what_was_difficult", "unspecified difficulty"),
            )

        result = {
            "step": step,
            "reflection": reflection,
            "explanation": explanation,
            "missing_concept": missing_concept,
            "learning_path": learning_path,
            "passed": learning_path is None,  # if there is a learning path, user must complete it
        }

        return result

    def _generate_reflection(self, step: str, worker_output: str) -> dict[str, str]:
        system = self._load_prompt("reflection") or (
            "You are a strict reflection engine. "
            "Given a step and the worker output, produce a structured reflection. "
            "Reply ONLY with valid JSON containing these keys: "
            "what_happened, what_worked, what_was_difficult, why"
        )

        user_content = f"Step: {step}\n\nWorker output:\n{worker_output}\n\nProduce the reflection JSON."

        raw = self.muse.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=800,
        )

        import json
        import re

        # Try to extract clean JSON
        try:
            # Remove markdown code blocks if present
            cleaned = re.sub(r"```json|```", "", raw).strip()
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(cleaned[start:end])
                # Make sure all keys exist
                return {
                    "what_happened": str(parsed.get("what_happened", "")),
                    "what_worked": str(parsed.get("what_worked", "")),
                    "what_was_difficult": str(parsed.get("what_was_difficult", "")),
                    "why": str(parsed.get("why", "")),
                }
        except Exception:
            pass

        # Fallback
        return {
            "what_happened": raw[:400],
            "what_worked": "See full reflection above",
            "what_was_difficult": "See full reflection above",
            "why": "See full reflection above",
        }

    def _generate_explanation(
        self, step: str, reflection: dict[str, str], worker_output: str
    ) -> str:
        system = self._load_prompt("explanation") or (
            "You explain technical work in clear, plain language so the understanding sticks. "
            "Be concise but complete. Do not repeat the reflection. Focus on the key reasoning."
        )

        user_content = (
            f"Step: {step}\n\n"
            f"Reflection: {reflection}\n\n"
            f"Worker output (summary): {worker_output[:800]}\n\n"
            "Write a plain-language explanation of the key decisions and reasoning."
        )

        return self.muse.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=600,
        )

    def _detect_and_create_learning(
        self,
        project_name: str,
        step: str,
        reflection: dict[str, str],
        user_question: str | None,
    ) -> tuple[str | None, str | None]:
        """
        Returns (missing_concept, learning_path) or (None, None)
        """
        difficult = reflection.get("what_was_difficult", "").lower()
        why = reflection.get("why", "").lower()
        context = self.memory.get_context_for_orchestrator(project_name)

        system = self._load_prompt("learning_path") or (
            "You decide whether a real missing concept blocked progress. "
            "If yes, create a short focused learning path (3-6 items). "
            "If the difficulty is just normal work, return NO_LEARNING_NEEDED."
        )

        user_content = (
            f"Step: {step}\n"
            f"Difficulty: {difficult}\n"
            f"Why: {why}\n"
            f"User question (if any): {user_question or 'none'}\n"
            f"User memory context:\n{context}\n\n"
            "Does this require a short learning path?\n"
            "If yes, reply in this exact format:\n\n"
            "Concept: <short name>\n"
            "Why it mattered: <one sentence>\n"
            "Learning path:\n"
            "1. ...\n"
            "2. ...\n"
            "3. ...\n\n"
            "If no, reply exactly: NO_LEARNING_NEEDED"
        )

        raw = self.muse.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=700,
        )

        if "NO_LEARNING_NEEDED" in raw.upper():
            return None, None

        # Extract concept name
        concept = "detected concept"
        if "Concept:" in raw:
            try:
                concept = raw.split("Concept:")[1].split("\n")[0].strip()
            except Exception:
                pass

        return concept, raw