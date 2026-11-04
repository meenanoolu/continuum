import time

PLAN = "Build a small calculator module with an add function, then prove it works with tests and review it for gaps."
LONG = "add is a pure function so nothing outside its inputs affects the result, which is why I can test it with no setup at all"


def start(client, **kw):
    r = client.post("/api/start", json={"project_name": "calc", "plan": PLAN, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def run_step(client):
    assert client.post("/api/step/run").status_code == 202
    for _ in range(100):
        j = client.get("/api/job?since=0").json()
        if j["status"] == "done":
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def answer(client, text, n):
    return client.post("/api/gate/answers", json={"explain_back": text, "answers": [text] * n}).json()


def test_health_reports_fake(client):
    assert client.get("/api/health").json()["fake_llm"] is True


def test_vague_plan_rejected_and_keeps_session(client):
    start(client)
    r = client.post("/api/start", json={"project_name": "other", "plan": "make it good"})
    assert r.status_code == 400 and "vague" in r.json()["detail"]
    assert client.get("/api/state").json()["project"] == "calc"


def test_happy_path_is_verified_and_gate_locks(client):
    st = start(client)
    assert len(st["plan"]) == 3 and st["phase"] == "planned"
    j = run_step(client)
    assert any(e["kind"] == "tool" for e in j["events"])
    s = j["state"]
    assert s["phase"] == "awaiting_human"
    assert s["last_result"]["evidence"]["level"] == "verified"
    assert s["last_result"]["files_changed"] == ["calc.py", "test_calc.py"]
    # cannot run the next step while the gate is locked
    assert client.post("/api/step/run").status_code == 409
    res = answer(client, LONG, len(s["gate"]["questions"]))
    assert res["status"] == "passed" and res["state"]["index"] == 1 and res["state"]["phase"] == "planned"
    assert [x["status"] for x in res["state"]["plan"]][:2] == ["done", "pending"]


def test_fail_forces_learning_then_retry_unlocks(client):
    start(client)
    s = run_step(client)["state"]
    n = len(s["gate"]["questions"])
    res = answer(client, "dunno " * 12, n)
    assert res["status"] == "blocked_by_learning" and res["state"]["phase"] == "learning"
    assert res["state"]["index"] == 0
    assert client.post("/api/step/run").status_code == 409
    bad = client.post("/api/gate/learning", json={"confirmation": "read it all again", "retry_answer": "dunno " * 8}).json()
    assert bad["status"] == "retry"
    ok = client.post("/api/gate/learning", json={"confirmation": "I re-read the tests carefully", "retry_answer": LONG}).json()
    assert ok["status"] == "passed" and ok["state"]["index"] == 1


def test_memory_adapts_and_plan_revises_after_two_failures(client):
    start(client)
    s = run_step(client)["state"]
    n = len(s["gate"]["questions"])
    r1 = answer(client, "dunno " * 12, n)
    assert r1["status"] == "blocked_by_learning" and "revision" not in r1
    ok1 = client.post("/api/gate/learning", json={"confirmation": "I re-read the tests carefully", "retry_answer": LONG}).json()
    assert ok1["status"] == "passed" and ok1["state"]["index"] == 1
    # second failure on the next step -> memory triggers an automatic plan revision
    s = run_step(client)["state"]
    r2 = answer(client, "dunno " * 12, len(s["gate"]["questions"]))
    assert r2["revision"]["revised"] is True
    st = r2["state"]
    assert st["plan"][st["index"]]["title"].startswith("Hand-trace")
    assert st["memory"]["weak_concepts"] == ["unit testing"]
    ok = client.post("/api/gate/learning", json={"confirmation": "I traced it by hand", "retry_answer": LONG}).json()
    assert ok["status"] == "passed"
    assert ok["state"]["index"] == st["index"], "revised plan must not skip its first step"
    # next gate is stricter, and says why
    s3 = run_step(client)["state"]
    assert s3["gate"]["policy"]["strictness"] == "strict" and len(s3["gate"]["questions"]) == 3
    assert s3["gate"]["policy"]["reasons"]


def test_parroting_is_detected(client):
    start(client)
    s = run_step(client)["state"]
    copied = s["gate"]["explanation"]
    res = client.post("/api/gate/answers", json={"explain_back": copied, "answers": [copied] * len(s["gate"]["questions"])}).json()
    assert "parroting" in res["signals"]
    assert client.get("/api/memory").json()["patterns"][0]["key"] == "parroting"


def test_worker_claim_mismatch_is_flagged(client):
    r = client.post("/api/start", json={"project_name": "bad", "plan": PLAN + " FAIL_TESTS"})
    assert r.status_code == 200
    s = run_step(client)["state"]
    ev = s["last_result"]["evidence"]
    assert ev["level"] == "failed" and ev["claim_mismatch"] is True


def test_image_attach_and_validation(client):
    start(client)
    s = run_step(client)["state"]
    png = "data:image/png;base64,iVBORw0KGgo="
    assert client.post("/api/image", json={"data_url": png, "purpose": "gate"}).json()["notes"]
    assert client.post("/api/image", json={"data_url": "javascript:alert(1)", "purpose": "gate"}).status_code == 400
    res = answer(client, LONG, len(s["gate"]["questions"]))
    assert res["visual"] is not None


def test_session_survives_restart(client, env):
    start(client)
    run_step(client)
    from src import api
    api.reset_for_tests()
    st = client.get("/api/state").json()
    assert st["phase"] == "awaiting_human" and st["gate"]["questions"]


def test_repo_attach_through_start(client, env):
    src = env / "myrepo"
    src.mkdir()
    (src / "README.md").write_text("# hello")
    (src / "app.py").write_text("print(1)\n")
    st = start(client, repo=str(src))
    assert st["repo"]["kind"] == "local" and "repo/app.py" in st["repo"]["tree"]
    assert client.post("/api/start", json={"project_name": "x", "plan": PLAN, "repo": "/nonexistent/dir"}).status_code == 400