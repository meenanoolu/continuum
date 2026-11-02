import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTINUUM_FAKE_LLM", "1")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "mem.json"))
    monkeypatch.setenv("SESSION_PATH", str(tmp_path / "session.json"))
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.delenv("USE_MUSE_CODE", raising=False)
    from src import api, trace
    from src.models import reset_models

    reset_models()
    api.reset_for_tests()
    trace.clear()
    yield tmp_path
    reset_models()
    api.reset_for_tests()


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient
    from src.api import app

    return TestClient(app)
