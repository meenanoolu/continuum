import os
import pytest
from src.sandbox import Sandbox, SandboxError


def test_path_escape_blocked(tmp_path):
    sb = Sandbox(tmp_path / "w")
    for bad in ("../x.py", "a/../../x", "../../etc/passwd"):
        with pytest.raises(SandboxError):
            sb.write_file(bad, "x")
    # absolute paths are re-rooted inside the workspace, never honored
    sb.write_file("/etc/evil.txt", "x")
    assert (sb.root / "etc" / "evil.txt").exists() and not __import__("os").path.exists("/etc/evil.txt")


def test_run_python_and_timeout(tmp_path):
    sb = Sandbox(tmp_path / "w")
    sb.write_file("ok.py", "print('hi')")
    r = sb.run("python ok.py")
    assert r.ok and "hi" in r.output
    sb.write_file("slow.py", "import time\ntime.sleep(10)")
    r = sb.run("python slow.py", timeout=1)
    assert r.timed_out and not r.ok


def test_disallowed_commands(tmp_path):
    sb = Sandbox(tmp_path / "w")
    for cmd in ("ls", "curl http://x", "python -c 'print(1)'", "python /etc/hosts"):
        with pytest.raises(SandboxError):
            sb.run(cmd)


def test_api_keys_not_leaked_to_model_code(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "SECRET123")
    sb = Sandbox(tmp_path / "w")
    sb.write_file("leak.py", "import os\nprint(os.environ.get('META_API_KEY'))")
    assert "SECRET123" not in sb.run("python leak.py").output


def test_tests_and_diff(tmp_path):
    sb = Sandbox(tmp_path / "w")
    sb.snapshot()
    sb.write_file("calc.py", "def add(a,b):\n    return a+b\n")
    sb.write_file("test_calc.py", "from calc import add\ndef test_a():\n    assert add(1,2)==3\n")
    assert sb.run_tests().ok
    assert sb.changed_files() == ["calc.py", "test_calc.py"]
    assert "+def add" in sb.diff()
    sb.snapshot()
    assert sb.changed_files() == []
    sb.write_file("test_calc.py", "from calc import add\ndef test_a():\n    assert add(1,2)==4\n")
    assert not sb.run_tests().ok


def test_attach_local_repo(tmp_path):
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "README.md").write_text("# Demo repo")
    (src / "pkg" / "a.py").write_text("x = 1\n")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "junk.js").write_text("x")
    sb = Sandbox(tmp_path / "w")
    info = sb.attach_repo(str(src))
    assert "repo/pkg/a.py" in info["tree"] and not any("node_modules" in f for f in info["tree"])
    assert "Demo repo" in info["readme"]
    assert sb.changed_files() == []
