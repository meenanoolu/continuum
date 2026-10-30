from __future__ import annotations
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src.orchestrator import Orchestrator
from src.workers import CodeWorker, ResearchWorker, TestWorker
from src.utils import console
import uvicorn

app = FastAPI(title="Continuum")

# Serve frontend
app.mount("/static", StaticFiles(directory="frontend"), name="static")

orch = Orchestrator()

class StartRequest(BaseModel):
    project_name: str
    plan: str

class RunStepRequest(BaseModel):
    pass

@app.get("/")
def read_index():
    return FileResponse("frontend/index.html")

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
    if not orch.current_project or not orch.current_plan:
        raise HTTPException(status_code=400, detail="No active project")

    if orch.current_step_index >= len(orch.current_plan):
        return {"status": "plan_complete"}

    step = orch.current_plan[orch.current_step_index]

    # Simple worker routing
    step_lower = step.lower()
    if any(w in step_lower for w in ["test", "verify", "check"]):
        worker = TestWorker()
    elif any(w in step_lower for w in ["research", "find", "gather", "docs"]):
        worker = ResearchWorker()
    else:
        worker = CodeWorker()

    worker_output = worker.run(step)
    result = orch.run_next_step(worker_output=worker_output)

    return {
        "status": result["status"],
        "step": step,
        "gate": result.get("gate"),
        "remaining_steps": result.get("remaining_steps", 0),
        "current_step_index": orch.current_step_index
    }

@app.get("/status")
def get_status():
    return {
        "project": orch.current_project,
        "plan": orch.current_plan,
        "current_step_index": orch.current_step_index,
        "memory_summary": orch.memory.get_context_for_orchestrator(orch.current_project or "default")
    }

if __name__ == "__main__":
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=True)