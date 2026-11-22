import io
import zipfile


def test_export_empty_no_project(client):
    r = client.get("/api/export")
    assert r.status_code == 404


def test_export_after_start(client):
    client.post("/api/start", json={"project_name": "exporttest", "plan": "Build a tiny hello world function and verify it with a test."})
    from src.api import orch
    o = orch()
    assert o.sandbox is not None
    o.sandbox.write_file("hello.py", "def hello():\n    return 'world'\n")
    r = client.get("/api/export")
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    assert "exporttest" in r.headers.get("content-disposition", "").lower()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "hello.py" in z.namelist()
