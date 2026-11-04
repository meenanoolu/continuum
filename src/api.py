"""FastAPI layer. Thin: all behavior lives in the Orchestrator."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import os
import subprocess
import tempfile
import httpx

from src import trace
from src.models import get_models
from src.orchestrator import Orchestrator, OrchestratorError

app = FastAPI(title="Continuum")
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

_orch: Orchestrator | None = None


def orch() -> Orchestrator:
    global _orch
    if _orch is None:
        _orch = Orchestrator()
    return _orch


def reset_for_tests() -> None:
    global _orch
    _orch = None


# ---------------------------------------------------------------- background job (live agent log)
class Job:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.status = "idle"  # idle | running | done
        self.t0 = 0.0

    def start(self) -> None:
        with self.lock:
            self.events, self.status, self.t0 = [], "running", time.time()

    def emit(self, kind: str, text: str) -> None:
        with self.lock:
            self.events.append({"i": len(self.events), "t": round(time.time() - self.t0, 1), "kind": kind, "text": text})

    def finish(self) -> None:
        with self.lock:
            self.status = "done"

    def since(self, n: int) -> dict[str, Any]:
        with self.lock:
            return {"status": self.status, "events": self.events[n:], "next": len(self.events)}


job = Job()


def _err(e: OrchestratorError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=str(e))


# ---------------------------------------------------------------- schemas
class StartRequest(BaseModel):
    project_name: str = Field(min_length=1, max_length=80)
    plan: str = Field(min_length=1, max_length=4000)
    repo: str | None = Field(default=None, max_length=300)
    context_image: str | None = None  # data URL


class AnswersRequest(BaseModel):
    explain_back: str = Field(max_length=6000)
    answers: list[str] = Field(max_length=6)


class LearningRequest(BaseModel):
    confirmation: str = Field(max_length=3000)
    retry_answer: str = Field(max_length=6000)


class ImageRequest(BaseModel):
    data_url: str
    purpose: str = "gate"


class ReviseRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


# ---------------------------------------------------------------- routes
@app.get("/")
def index() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    import os

    return {"ok": True, "models": get_models().status(), "fake_llm": os.getenv("CONTINUUM_FAKE_LLM") == "1"}


@app.get("/api/state")
def state() -> dict[str, Any]:
    return orch().snapshot()


@app.post("/api/start")
def start(req: StartRequest) -> dict[str, Any]:
    o = orch()
    try:
        o.check_plan_text(req.plan)  # reject a vague plan BEFORE wiping the current session
        o.start_project(req.project_name, req.repo)
        if req.context_image:
            o.attach_image(req.context_image, "context")
        o.require_plan(req.plan)
    except OrchestratorError as e:
        raise _err(e)
    return o.snapshot()


@app.post("/api/step/run", status_code=202)
def run_step() -> dict[str, Any]:
    o = orch()
    if job.status == "running" or o.state["phase"] != "planned":
        raise HTTPException(status_code=409, detail=f"Cannot run a step now (phase: {o.state['phase']}).")
    job.start()

    def work() -> None:
        try:
            o.run_step(job.emit)
        finally:
            job.finish()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True}


@app.get("/api/job")
def job_events(since: int = 0) -> dict[str, Any]:
    out = job.since(max(0, since))
    out["state"] = orch().snapshot() if out["status"] == "done" else None
    return out


@app.post("/api/gate/answers")
def gate_answers(req: AnswersRequest) -> dict[str, Any]:
    try:
        return orch().submit_answers(req.explain_back, req.answers)
    except OrchestratorError as e:
        raise _err(e)


@app.post("/api/gate/learning")
def gate_learning(req: LearningRequest) -> dict[str, Any]:
    try:
        return orch().complete_learning(req.confirmation, req.retry_answer)
    except OrchestratorError as e:
        raise _err(e)


@app.post("/api/image")
def image(req: ImageRequest) -> dict[str, Any]:
    try:
        notes = orch().attach_image(req.data_url, req.purpose)
    except OrchestratorError as e:
        raise _err(e)
    return {"notes": notes}


@app.post("/api/plan/revise")
def revise(req: ReviseRequest) -> dict[str, Any]:
    try:
        out = orch().revise_plan(req.reason)
    except OrchestratorError as e:
        raise _err(e)
    return {**out, "state": orch().snapshot()}


@app.get("/api/diff")
def diff() -> dict[str, str]:
    o = orch()
    return {"diff": o.sandbox.diff(40000) if o.sandbox else ""}


@app.get("/api/memory")
def memory() -> dict[str, Any]:
    o = orch()
    return o.memory.profile(o.state["project"])


@app.post("/api/memory/reset")
def memory_reset() -> dict[str, bool]:
    orch().memory.reset()
    trace.clear()
    return {"ok": True}


@app.post("/api/project/abandon")
def abandon() -> dict[str, Any]:
    try:
        orch().abandon()
    except OrchestratorError as e:
        raise _err(e)
    return orch().snapshot()



@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)) -> dict[str, Any]:
    """Record from the browser mic → Muse Voice Transcribe → plain text for the user to edit."""
    key = os.getenv("META_API_KEY") or os.getenv("MODEL_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="META_API_KEY is not set; voice input is unavailable.")

    raw = await audio.read()
    if not raw or len(raw) < 200:
        raise HTTPException(status_code=400, detail="Recording was empty or too short.")
    if len(raw) > 8_000_000:
        raise HTTPException(status_code=400, detail="Recording is too long (max ~60s).")

    suffix = Path(audio.filename or "clip.webm").suffix or ".webm"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{suffix}"
        wav = Path(td) / "out.wav"
        src.write_bytes(raw)
        # Muse Voice Transcribe wants mono 16-bit WAV at 16 kHz or 24 kHz
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(wav)],
                check=True, capture_output=True, timeout=30,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            raise HTTPException(status_code=400, detail=f"Could not convert audio: {e}")

        with wav.open("rb") as f:
            files = {
                "request": (None, '{"model":"muse-voice-transcribe-1.0","audioEncoding":"WAV","mode":"PUSH_TO_TALK"}', "application/json"),
                "audio": ("audio.wav", f, "audio/wav"),
            }
            try:
                r = httpx.post(
                    "https://api.meta.ai/v1/asr/transcribe",
                    headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                    files=files,
                    timeout=60,
                )
            except httpx.HTTPError as e:
                raise HTTPException(status_code=502, detail=f"Voice service unreachable: {e}")

    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Voice service error ({r.status_code}): {r.text[:300]}")

    data = r.json()
    # Response shapes vary; collect text from common fields
    text_out = ""
    if isinstance(data, dict):
        if "text" in data:
            text_out = str(data["text"])
        elif "transcript" in data:
            text_out = str(data["transcript"])
        elif "turns" in data and isinstance(data["turns"], list):
            parts = []
            for t in data["turns"]:
                if isinstance(t, dict):
                    parts.append(str(t.get("text") or t.get("transcript") or ""))
                else:
                    parts.append(str(t))
            text_out = " ".join(p for p in parts if p).strip()
        else:
            # last-resort: walk for any string that looks like speech
            text_out = str(data)
    else:
        text_out = str(data)

    text_out = text_out.strip()
    if not text_out:
        raise HTTPException(status_code=502, detail="Got an empty transcript. Try speaking a bit longer.")

    trace.record(purpose="voice.transcribe", provider="meta", model="muse-voice-transcribe-1.0",
                 ms=0, tokens=None, ok=True, note=f"{len(text_out)} chars")
    return {"text": text_out}



if __name__ == "__main__":
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=False)
