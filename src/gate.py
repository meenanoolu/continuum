"""
The Gate. After every step the next one stays locked until the human proves understanding.

Flow:  prepare()  -> reflection + explanation + concept + grounded questions (one model call)
       evaluate() -> grade explain-back + answers (+ optional image) -> pass, or forced learning path
       complete_learning() -> a fresh retry question must be answered before unlocking

Adaptive: strictness, number of questions and pass threshold come from personal memory.
Grounded: questions are built from the Worker's real evidence (diff, test output), not its story.
"""
from __future__ import annotations

import re
import time
from typing import Any

from src.memory import PersonalMemory
from src.memory.personal_memory import norm_concept
from src.models import Models
from src.utils import console, load_prompt

_WORD = re.compile(r"[a-z0-9_]{4,}")


def overlap_ratio(answer: str, reference: str) -> float:
    """Share of the answer's distinctive words that also appear in the reference (0..1)."""
    a = _WORD.findall(answer.lower())
    if len(a) < 8:
        return 0.0
    ref = set(_WORD.findall(reference.lower()))
    return sum(1 for w in a if w in ref) / len(a)


def _clip(n: Any, lo: int = 0, hi: int = 2) -> int:
    try:
        return max(lo, min(hi, int(round(float(n)))))
    except (TypeError, ValueError):
        return 0


class Gate:
    def __init__(self, models: Models, memory: PersonalMemory):
        self.models = models
        self.memory = memory

    # ------------------------------------------------------------------ prepare
    def prepare(self, project: str, step: dict[str, Any], worker_text: str, policy: dict[str, Any]) -> dict[str, Any]:
        n = policy["questions"]
        user = (
            f"Step: {step['title']}\nWhy: {step.get('why', '')}\nIntended concept: {step.get('concept', '')}\n\n"
            f"Learning policy: {policy['strictness']}; ask exactly {n} questions."
            + (f" Weak concepts to probe if relevant: {', '.join(policy['weak_concepts'])}." if policy["weak_concepts"] else "")
            + f"\n\n{worker_text}"
        )
        data = self.models.json(
            "meta", "gate.prepare",
            [{"role": "system", "content": load_prompt("gate_prepare")}, {"role": "user", "content": user}],
            max_tokens=1800,
            validate=lambda d: isinstance(d, dict) and isinstance(d.get("questions"), list) and len(d["questions"]) >= 2,
        )
        if data is None:
            console.print("[yellow]Gate.prepare: model unavailable, using evidence-only fallback[/yellow]")
            data = self._fallback(step, worker_text, n)

        questions = []
        for q in data["questions"][:n]:
            if isinstance(q, str):
                q = {"question": q}
            questions.append(
                {"question": str(q.get("question", "")).strip() or "Explain the key decision in this step.",
                 "type": str(q.get("type", "why")), "focus": str(q.get("focus", ""))}
            )
        refl = data.get("reflection") or {}
        reflection = {k: str(refl.get(k, "")).strip() or "-" for k in ("what_happened", "what_worked", "what_was_difficult", "why")}
        concept = norm_concept(str(data.get("concept") or step.get("concept") or step["title"]))
        explanation = str(data.get("explanation", "")).strip() or "No explanation was generated."
        self.memory.add_reflection(project, step["title"], reflection, explanation)
        return {
            "concept": concept,
            "reflection": reflection,
            "explanation": explanation,
            "questions": questions,
            "policy": policy,
            "started_at": time.time(),
            "attempt": 0,
            "learning": None,
            "image_notes": None,
        }

    @staticmethod
    def _fallback(step: dict[str, Any], worker_text: str, n: int) -> dict[str, Any]:
        first = worker_text.splitlines()[0] if worker_text else "no evidence"
        qs = [
            {"question": "In your own words, what does the code you just got actually do, and why was it built that way?", "type": "why", "focus": ""},
            {"question": "What would break or change if the main input of this step were empty or invalid?", "type": "what_if", "focus": ""},
            {"question": "Which part of the result would you check first to be sure it works, and how?", "type": "trace", "focus": ""},
            {"question": "What is the riskiest assumption in this step?", "type": "why", "focus": ""},
        ]
        return {
            "concept": step.get("concept") or step["title"],
            "reflection": {"what_happened": first, "what_worked": "-", "what_was_difficult": "-", "why": "-"},
            "explanation": "The Gate model was unavailable, so this check uses generic questions. " + first,
            "questions": qs[:n],
        }

    # ------------------------------------------------------------------ evaluate
    def evaluate(
        self,
        project: str,
        step: dict[str, Any],
        state: dict[str, Any],
        explain_back: str,
        answers: list[str],
        worker_text: str,
    ) -> dict[str, Any]:
        questions = state["questions"]
        if len(explain_back.strip()) < 30:
            return {"status": "rejected", "reason": "Explain-back is too short. Write a few real sentences."}
        if len(answers) != len(questions) or any(len(a.strip()) < 3 for a in answers):
            return {"status": "rejected", "reason": "Answer every check question."}

        reference = state["explanation"] + " " + " ".join(state["reflection"].values())
        elapsed = time.time() - state["started_at"]
        eb_overlap = overlap_ratio(explain_back, reference)
        ans_overlap = [overlap_ratio(a, reference) for a in answers]
        signals = {
            "parroting": eb_overlap > 0.75 or any(o > 0.8 for o in ans_overlap),
            "shallow_explain": len(explain_back.split()) < 25,
            "fast_submit": elapsed < 12,
        }
        hints = []
        if eb_overlap > 0.75:
            hints.append(f"explain-back overlaps the reference explanation {eb_overlap:.0%}")
        for i, o in enumerate(ans_overlap):
            if o > 0.8:
                hints.append(f"answer {i + 1} overlaps the reference explanation {o:.0%}")
        if signals["fast_submit"]:
            hints.append(f"all answers were submitted within {int(elapsed)} seconds")

        user = f"Step: {step['title']}\n\nREFERENCE (what the human was shown):\n{state['explanation']}\n\n{worker_text[:2500]}\n\n"
        user += f"HUMAN EXPLAIN-BACK:\n{explain_back}\n\nQUESTIONS AND ANSWERS:\n"
        for i, (q, a) in enumerate(zip(questions, answers), 1):
            user += f"{i}. Q: {q['question']}\n   A: {a}\n"
        if hints:
            user += "\nINTEGRITY SIGNALS:\n- " + "\n- ".join(hints) + "\n"
        if state.get("image_notes"):
            user += f"\nIMAGE THE HUMAN ATTACHED (description by a vision model):\n{state['image_notes']}\n"

        data = self.models.json(
            "meta", "gate.grade",
            [{"role": "system", "content": load_prompt("gate_grade")}, {"role": "user", "content": user}],
            max_tokens=1200,
            validate=lambda d: isinstance(d, dict) and isinstance(d.get("answers"), list) and "explain_back" in d,
        )
        if data is None:
            # Never punish the human (or their memory) for a grader outage.
            return {"status": "grader_error", "reason": "The grader model is unavailable right now. Try submitting again."}

        eb = _clip((data.get("explain_back") or {}).get("score"))
        if eb_overlap > 0.75:
            eb = min(eb, 1)
        item_scores: list[int] = []
        details = []
        raw_answers = data["answers"]
        for i, q in enumerate(questions):
            entry = raw_answers[i] if i < len(raw_answers) and isinstance(raw_answers[i], dict) else {}
            s = _clip(entry.get("score"))
            if ans_overlap[i] > 0.8:
                s = min(s, 1)
            item_scores.append(s)
            details.append({"question": q["question"], "score": s, "note": str(entry.get("note", ""))})
        vm = data.get("visual_match")
        extra = [_clip(vm.get("score"))] if isinstance(vm, dict) and state.get("image_notes") else []
        weights_total = 2 + len(item_scores) + len(extra)
        avg = (2 * eb + sum(item_scores) + sum(extra)) / weights_total
        passed = avg >= state["policy"]["pass_threshold"] and eb >= 1

        missing = [norm_concept(c) for c in (data.get("missing_concepts") or []) if str(c).strip()]
        state["attempt"] += 1
        concept = state["concept"] if passed or not missing else missing[0]
        self.memory.record_gate(project, step["title"], concept, passed, avg, signals, state["attempt"])

        result: dict[str, Any] = {
            "status": "passed" if passed else "blocked_by_learning",
            "passed": passed,
            "score": round(avg, 2),
            "threshold": state["policy"]["pass_threshold"],
            "explain_back": {"score": eb, "note": str((data.get("explain_back") or {}).get("note", ""))},
            "answers": details,
            "visual": {"score": extra[0], "note": str(vm.get("note", ""))} if extra else None,
            "signals": [s for s, f in signals.items() if f],
            "feedback": str(data.get("feedback", "")).strip(),
        }
        if not passed:
            result["learning"] = self._learning_path(step, state, explain_back, result["feedback"], concept)
        return result

    # ------------------------------------------------------------------ learning
    def _learning_path(self, step: dict[str, Any], state: dict[str, Any], explain_back: str, feedback: str, concept: str) -> dict[str, Any]:
        user = (
            f"Step: {step['title']}\nMissing concept: {concept}\nGrader feedback: {feedback}\n"
            f"What they wrote:\n{explain_back[:800]}\nQuestions they were asked:\n"
            + "\n".join(f"- {q['question']}" for q in state["questions"])
        )
        data = self.models.json(
            "meta", "gate.learning_path",
            [{"role": "system", "content": load_prompt("learning_path")}, {"role": "user", "content": user}],
            max_tokens=900,
            validate=lambda d: isinstance(d, dict) and isinstance(d.get("items"), list) and d.get("retry_question"),
        )
        if data is None:
            data = {
                "concept": concept,
                "why_it_mattered": "The check showed this idea is not solid yet.",
                "items": [
                    "Re-read the diff for this step and mark the line where the key decision happens.",
                    "Write down, before running anything, what you expect the code to output for one input; then run it and compare.",
                    "Explain the decision out loud in two sentences, without looking at the explanation.",
                ],
                "retry_question": f"Without looking back: explain {concept} as it applies to this step, with one concrete example.",
            }
        data["concept"] = norm_concept(str(data.get("concept") or concept))
        data["items"] = [str(i) for i in data["items"]][:5]
        state["learning"] = data
        return data

    def complete_learning(self, project: str, state: dict[str, Any], confirmation: str, retry_answer: str) -> dict[str, Any]:
        learning = state.get("learning")
        if not learning:
            return {"status": "rejected", "reason": "There is no active learning path."}
        if len(confirmation.strip()) < 15:
            return {"status": "rejected", "reason": "Write a short note on what you learned (15+ characters)."}
        if len(retry_answer.strip()) < 20:
            return {"status": "rejected", "reason": "Answer the retry question properly (a few sentences)."}
        user = (
            f"Concept: {learning['concept']}\nRetry question: {learning['retry_question']}\n"
            f"Reference explanation they were shown earlier:\n{state['explanation']}\n\nTheir answer:\n{retry_answer}"
        )
        if overlap_ratio(retry_answer, state["explanation"]) > 0.8:
            user += "\n\nINTEGRITY SIGNAL: the answer overlaps the reference explanation by more than 80%. Score at most 1."
        data = self.models.json(
            "meta", "gate.learning_grade",
            [{"role": "system", "content": load_prompt("learning_grade")}, {"role": "user", "content": user}],
            max_tokens=500,
            validate=lambda d: isinstance(d, dict) and "score" in d,
        )
        if data is None:
            return {"status": "grader_error", "reason": "The grader model is unavailable right now. Try again."}
        score = _clip(data.get("score"))
        if overlap_ratio(retry_answer, state["explanation"]) > 0.8:
            score = min(score, 1)
        passed = score >= 1
        self.memory.record_learning(project, learning["concept"], passed)
        return {
            "status": "passed" if passed else "retry",
            "passed": passed,
            "score": score,
            "feedback": str(data.get("feedback", "")).strip(),
        }
