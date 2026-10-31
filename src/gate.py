from __future__ import annotations
from typing import Any
from pathlib import Path
import json
import re
import os

from src.models import MuseSparkClient, OpenWeightClient
from src.memory import PersonalMemory
from src.utils import console

def get_reliable_client():
    """Prefer the model that actually returns content (Baseten first)."""
    if os.getenv("BASETEN_API_KEY"):
        try:
            client = OpenWeightClient()
            return client, "OpenWeight (Baseten)"
        except Exception:
            pass
    return MuseSparkClient(), "MuseSpark"

class Gate:
    def __init__(self, muse: MuseSparkClient, memory: PersonalMemory):
        self.muse = muse
        self.memory = memory
        self.prompts_dir = Path(__file__).parent.parent / "prompts"
        self.client, self.client_name = get_reliable_client()
        console.print(f"[dim]Gate using: {self.client_name}[/dim]")

    def _load_prompt(self, name: str) -> str:
        path = self.prompts_dir / f"{name}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def start_gate(self, project_name: str, step: str, worker_output: str) -> dict[str, Any]:
        console.print(f"\n[bold yellow]═══ GATE started for step: {step} ═══[/bold yellow]")

        reflection = self._generate_reflection(step, worker_output)
        explanation = self._generate_explanation(step, reflection, worker_output)
        questions = self._generate_check_questions(step, reflection, explanation)

        self.memory.add_reflection(project_name, step, reflection, explanation)

        return {
            "status": "awaiting_human",
            "step": step,
            "reflection": reflection,
            "explanation": explanation,
            "questions": questions,
            "passed": False,
            "learning_path": None,
        }

    def evaluate_human(
        self,
        project_name: str,
        step: str,
        explain_back: str,
        answers: list[str],
        questions: list[str],
        reflection: dict[str, str],
        explanation: str,
    ) -> dict[str, Any]:
        console.print("[bold yellow]═══ Evaluating human answers ═══[/bold yellow]")

        if not explain_back or len(explain_back.strip()) < 30:
            return {
                "status": "rejected",
                "reason": "Explain-back is too short. Write at least a few sentences.",
                "passed": False,
            }

        grade_result = self._grade_answers(step, explain_back, questions, answers, reflection)
        passed = grade_result["passed"]
        feedback = grade_result["feedback"]

        if passed:
            console.print("[green]✓ Human passed the Gate[/green]")
            for concept in grade_result.get("concepts_learned", []):
                self.memory.add_concept_learned(project_name, concept)
            return {
                "status": "passed",
                "passed": True,
                "feedback": feedback,
                "learning_path": None,
            }

        console.print("[yellow]✗ Human failed – forcing Learning Path[/yellow]")
        learning_path = self._create_forced_learning_path(step, reflection, explain_back, feedback)

        return {
            "status": "blocked_by_learning",
            "passed": False,
            "feedback": feedback,
            "learning_path": learning_path,
        }

    def complete_learning_path(
        self,
        project_name: str,
        step: str,
        learning_path: str,
        user_confirmation: str,
    ) -> dict[str, Any]:
        if not user_confirmation or len(user_confirmation.strip()) < 15:
            return {
                "status": "rejected",
                "reason": "Please write a short confirmation of what you learned.",
                "passed": False,
            }

        concept = "key concept from learning path"
        if "Concept:" in learning_path:
            try:
                concept = learning_path.split("Concept:")[1].split("\n")[0].strip()[:60]
            except Exception:
                pass

        self.memory.add_concept_learned(project_name, concept)
        console.print(f"[green]✓ Learning path completed. Concept marked: {concept}[/green]")

        return {
            "status": "passed",
            "passed": True,
            "feedback": "Learning path completed. Next step unlocked.",
        }

    # ------------------------------------------------------------------
    def _generate_reflection(self, step: str, worker_output: str) -> dict[str, str]:
        system = (
            "You are a strict reflection engine. "
            "Reply ONLY with valid JSON using exactly these keys: "
            "what_happened, what_worked, what_was_difficult, why"
        )
        user_content = f"Step: {step}\n\nWorker output:\n{worker_output[:1500]}\n\nProduce the reflection JSON."

        raw = self.client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=700,
        )
        return self._safe_parse_json(raw or "")

    def _generate_explanation(self, step: str, reflection: dict, worker_output: str) -> str:
        system = "Explain the key reasoning in clear plain language. 1-3 short paragraphs."
        user_content = (
            f"Step: {step}\nReflection: {json.dumps(reflection)}\n"
            f"Worker output: {worker_output[:800]}\n\nWrite the explanation."
        )
        raw = self.client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return (raw or "No explanation was generated.").strip()

    def _generate_check_questions(self, step: str, reflection: dict, explanation: str) -> list[str]:
        system = (
            "Generate exactly 3 short check questions that test whether a human "
            "understood the key decisions of this step. "
            "Reply with a JSON array of exactly 3 strings."
        )
        user_content = (
            f"Step: {step}\nReflection: {json.dumps(reflection)}\n"
            f"Explanation: {explanation}\n\nGenerate 3 check questions as a JSON array."
        )
        raw = self.client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=400,
        )

        try:
            cleaned = re.sub(r"```json|```", "", raw or "").strip()
            start = cleaned.find("[")
            end = cleaned.rfind("]") + 1
            if start >= 0 and end > start:
                questions = json.loads(cleaned[start:end])
                if isinstance(questions, list) and len(questions) >= 3:
                    return [str(q) for q in questions[:3]]
        except Exception:
            pass

        return [
            "What was the main goal of this step?",
            "What was the most difficult part and why?",
            "What would you do differently next time?",
        ]

    def _grade_answers(
        self,
        step: str,
        explain_back: str,
        questions: list[str],
        answers: list[str],
        reflection: dict,
    ) -> dict[str, Any]:
        system = (
            "You are grading a human's understanding. "
            'Reply ONLY with JSON: {"passed": true/false, "feedback": "...", "concepts_learned": []}'
        )
        user_content = (
            f"Step: {step}\nReflection: {json.dumps(reflection)}\n\n"
            f"Human explain-back:\n{explain_back}\n\nQuestions and answers:\n"
        )
        for i, (q, a) in enumerate(zip(questions, answers)):
            user_content += f"{i+1}. Q: {q}\n   A: {a}\n"
        user_content += "\nGrade whether the human understood the step."

        raw = self.client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=400,
        )

        try:
            cleaned = re.sub(r"```json|```", "", raw or "").strip()
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(cleaned[start:end])
                return {
                    "passed": bool(result.get("passed", False)),
                    "feedback": str(result.get("feedback", "")),
                    "concepts_learned": result.get("concepts_learned", []),
                }
        except Exception:
            pass

        return {
            "passed": False,
            "feedback": "Could not reliably grade the answers. Please try again with clearer responses.",
            "concepts_learned": [],
        }

    def _create_forced_learning_path(
        self, step: str, reflection: dict, explain_back: str, feedback: str
    ) -> str:
        system = (
            "Create a short forced learning path (3-5 items) because the human failed the understanding check. "
            "Start with 'Concept: ...'"
        )
        user_content = (
            f"Step: {step}\nReflection: {json.dumps(reflection)}\n"
            f"Human explain-back: {explain_back}\nGrading feedback: {feedback}\n\n"
            "Create the learning path."
        )
        raw = self.client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return (raw or "Concept: core idea of this step\n1. Review the reflection\n2. Re-explain the hard part\n3. Try the check questions again").strip()

    def _safe_parse_json(self, text: str) -> dict[str, str]:
        if not text:
            return {
                "what_happened": "No reflection content returned.",
                "what_worked": "—",
                "what_was_difficult": "—",
                "why": "—",
            }
        try:
            text = re.sub(r"```json|```", "", text).strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start == -1:
                raise ValueError("No JSON object")
            json_str = text[start:end] if end > start else text[start:] + "}"
            parsed = json.loads(json_str)
            return {
                "what_happened": str(parsed.get("what_happened", "")).strip() or "—",
                "what_worked": str(parsed.get("what_worked", "")).strip() or "—",
                "what_was_difficult": str(parsed.get("what_was_difficult", "")).strip() or "—",
                "why": str(parsed.get("why", "")).strip() or "—",
            }
        except Exception:
            return {
                "what_happened": text[:500],
                "what_worked": "Could not fully parse",
                "what_was_difficult": "Could not fully parse",
                "why": "Could not fully parse",
            }