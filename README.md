# Continuum

**A personal multi-agent system that makes sure you finish what you start, and understand what you built.**

AI tools write code for you and leave you with a project you cannot explain. Continuum does the opposite of autopilot. Agents do the work *and prove it works*; **you** must prove you understood it before the next step unlocks. It learns how *you* personally lose momentum and skip understanding, and it gets stricter exactly where you are weakest.

> Built for the **Meta Global AI Developer Hackathon** (Oct 27 - Nov 4, 2026) - track: Build for Your World. Open source, solo entry. See the git history for exactly what was written when.


---

## The loop

1. **Plan only the next piece.** You describe one concrete piece of work (optionally with a screenshot/diagram and an existing repo). The Orchestrator refuses vague plans, and splits the work into 3-6 steps, each naming the one concept you must understand.
2. **Workers act, with tools.** A Code, Test or Research Worker runs a real tool loop in a project workspace: `write_file`, `read_file`, `run_python`, `run_tests`. They fix their own failures.
3. **Trust, but verify.** Whatever the Worker *says*, Continuum re-runs the tests itself. The Gate sees ground truth (real test output, real diff). If the Worker claimed success and the independent check disagrees, the UI says so in red.
4. **The Gate locks.** You get a reflection, an explanation, and questions pointing at real lines of the diff. You write an explain-back in your own words. Pasting the explanation back is detected and scored down.
5. **Fail the check -> forced learning path.** A short, targeted path plus a *fresh* retry question you must answer before the next step unlocks.
6. **Memory changes behavior.** Failed concepts, copy-paste habits, rushed answers are stored. The next Gate gets stricter (4 questions, higher bar) and *tells you why*. Two failed checks in a row make the Orchestrator re-plan the remaining work with a prerequisite step.

## Where the Meta models are used

| Job | Model | Why this one |
|---|---|---|
| Orchestrator planning and plan revision | Muse Spark 1.3 (Meta Model API) | Strict structured planning |
| Gate: reflection, grounded questions, grading, learning paths | Muse Spark 1.3 (Meta Model API) | Judgement-heavy, needs the strongest reasoning |
| Vision: screenshots/diagrams for planning and "show your work" checks | Muse Spark 1.3 vision | Gate verifies your explanation against what the image really shows |
| **Workers: tool-calling agent loop** | **Muse Spark Open (open weights) on Baseten** | Cheap, fast, high-volume execution. Native tool calls first, text protocol if the host lacks them |
| Optional coding delegate | Muse Code (`muse exec`) | Opt-in with `USE_MUSE_CODE=1`; output is verified independently like any other Worker |

Every model call is recorded and shown in the **Model trace** panel of the UI (purpose, model, latency).

A detail that matters: Muse Spark always reasons internally and reasoning tokens count against the output cap, so a small cap returns *empty* content. Continuum adds reasoning headroom to every request, lowers reasoning effort, and retries once with a bigger budget on `finish_reason=length`.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # add META_API_KEY and BASETEN_API_KEY
python scripts/smoke_live.py                           # 30-second check that your keys and capabilities work
python -m src.api                                      # open http://127.0.0.1:8000
```

CLI version of the same loop: `python -m src.main`.

Safer execution: `docker build -t continuum . && docker run --env-file .env -p 8000:8000 continuum`.

### Tests (offline, no credits used)

```bash
python -m pytest
```

24 tests run the whole product against a deterministic fake model: sandbox confinement, independent verification, claim-vs-evidence mismatch, adaptive Gate strictness, copy detection, automatic plan revision, forced learning path, session persistence, image validation, provider fallback. `CONTINUUM_FAKE_LLM=1` starts the UI with that fake model (it shows an "OFFLINE FAKE MODEL" badge so it can never be mistaken for the real thing).

## Honest limitations

- **Code execution is not a security boundary.** Model-written Python runs on your machine with an allowlist (python/pytest only), a timeout, CPU/memory limits and API keys stripped from its environment. Use the Dockerfile for real isolation.
- Grading and question quality depend on the model; a grader outage never penalizes you or your memory (you can simply resubmit).
- Memory is a local JSON file for one user. There is no account system.
- Muse Code delegation depends on the `muse` CLI being installed; if it is missing or fails, the built-in tool loop is used.

## Layout

```
src/orchestrator.py    plan, route, persist session, auto-revise
src/gate.py            reflection, grounded questions, grading, learning path
src/agent.py           tool loop + independent verification
src/sandbox.py         workspace, allowlisted runner, diffs, repo attach
src/memory/            adaptive personal memory
src/models/            Meta API + Baseten client, routing, offline fake
src/workers/           Code / Test / Research workers
frontend/              web UI (no framework; model text is never injected as HTML)
prompts/               every system prompt, as plain files
tests/                 offline test suite
scripts/smoke_live.py  check your real keys
```
