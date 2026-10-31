from __future__ import annotations
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src.orchestrator import Orchestrator
from src.workers import CodeWorker, ResearchWorker, TestWorker
from src.utils import console
from pathlib import Path
import uvicorn

app = FastAPI(title="Continuum")

# Serve frontend
frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

orch = Orchestrator()

# Temporary storage for the current Gate state (simple in-memory for the hackathon)
current_gate_state: dict = {}

class StartRequest(BaseModel):
    project_name: str
    plan: str

class HumanAnswersRequest(BaseModel):
    explain_back: str
    answers: list[str]          # exactly 3 answers

class LearningConfirmationRequest(BaseModel):
    confirmation: str

@app.get("/")
def read_index():
    return FileResponse(frontend_dir / "index.html")

@app.post("/start")
def start_project(req: StartRequest):
    try:
        orch.start_project(req.project_name)
        steps = orch.require_plan(req.plan)
        return {
            "status": "ok",
            "project": req.project_name,
            "steps": steps,
            "current_step": 0
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/run-step")
def run_step():
    """Run the worker and start the Gate (first half)."""
    global current_gate_state

    if not orch.current_project or not orch.current_plan:
        raise HTTPException(status_code=400, detail="No active project")

    if orch.current_step_index >= len(orch.current_plan):
        return {"status": "plan_complete"}

    step = orch.current_plan[orch.current_step_index]

    # Simple worker routing
    step_lower = step.lower()
    if any(w in step_lower for w in ["test", "verify", "check", "validate"]):
        worker = TestWorker()
    elif any(w in step_lower for w in ["research", "find", "gather", "investigate", "docs"]):
        worker = ResearchWorker()
    else:
        worker = CodeWorker()

    worker_output = worker.run(step)

    # Start the human-in-the-loop Gate
    gate_result = orch.gate.start_gate(
        project_name=orch.current_project,
        step=step,
        worker_output=worker_output,
    )

    # Store state so we can evaluate later
    current_gate_state = {
        "step": step,
        "reflection": gate_result["reflection"],
        "explanation": gate_result["explanation"],
        "questions": gate_result["questions"],
    }

    return {
        "status": "awaiting_human",
        "step": step,
        "gate": gate_result,
        "current_step_index": orch.current_step_index,
    }

@app.post("/submit-answers")
def submit_answers(req: HumanAnswersRequest):
    """Second half of the Gate – grade the human."""
    global current_gate_state

    if not current_gate_state:
        raise HTTPException(status_code=400, detail="No active Gate. Run a step first.")

    if len(req.answers) != 3:
        raise HTTPException(status_code=400, detail="Please provide exactly 3 answers")

    result = orch.gate.evaluate_human(
        project_name=orch.current_project,
        step=current_gate_state["step"],
        explain_back=req.explain_back,
        answers=req.answers,
        questions=current_gate_state["questions"],
        reflection=current_gate_state["reflection"],
        explanation=current_gate_state["explanation"],
    )

    if result["passed"]:
        # Unlock next step
        orch.current_step_index += 1
        current_gate_state = {}
        return {
            "status": "passed",
            "feedback": result["feedback"],
            "current_step_index": orch.current_step_index,
            "remaining_steps": len(orch.current_plan) - orch.current_step_index,
        }

    # Failed → learning path forced
    current_gate_state["learning_path"] = result["learning_path"]
    current_gate_state["feedback"] = result["feedback"]

    return {
        "status": "blocked_by_learning",
        "feedback": result["feedback"],
        "learning_path": result["learning_path"],
    }

@app.post("/complete-learning")
def complete_learning(req: LearningConfirmationRequest):
    """Human finished the forced learning path."""
    global current_gate_state

    if not current_gate_state or "learning_path" not in current_gate_state:
        raise HTTPException(status_code=400, detail="No active learning path")

    result = orch.gate.complete_learning_path(
        project_name=orch.current_project,
        step=current_gate_state["step"],
        learning_path=current_gate_state["learning_path"],
        user_confirmation=req.confirmation,
    )

    if result["passed"]:
        orch.current_step_index += 1
        current_gate_state = {}
        return {
            "status": "passed",
            "feedback": result["feedback"],
            "current_step_index": orch.current_step_index,
            "remaining_steps": len(orch.current_plan) - orch.current_step_index,
        }

    return {
        "status": "rejected",
        "reason": result.get("reason", "Confirmation too short"),
    }

@app.get("/status")
def get_status():
    return {
        "project": orch.current_project,
        "plan": orch.current_plan,
        "current_step_index": orch.current_step_index,
        "memory_summary": orch.memory.get_context_for_orchestrator(orch.current_project or "default"),
    }

if __name__ == "__main__":
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=True)