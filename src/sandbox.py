"""
Project workspace + command runner used by the Workers.

What it does:   path-confined file tools, allowlisted commands (python / pytest only),
                wall-clock timeout, CPU/memory/file-size rlimits, API keys stripped from env,
                snapshot-based diffs (no git needed).
What it is NOT: a security boundary. Model-written Python still runs on this machine.
                Run Continuum in the provided Dockerfile if you want real isolation.
"""
from __future__ import annotations

import difflib
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", ".mypy_cache", ".idea"}
MAX_FILE_BYTES = 200_000
MAX_OUTPUT_CHARS = 6_000
ALLOWED_BINARIES = {"python", "python3", "pytest"}


class SandboxError(ValueError):
    pass


@dataclass
class RunResult:
    cmd: str
    exit_code: int
    output: str
    timed_out: bool = False
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


def _limit_resources() -> None:  # pragma: no cover - runs in the child process
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
        resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
        resource.setrlimit(resource.RLIMIT_FSIZE, (20_000_000, 20_000_000))
    except Exception:
        pass


class Sandbox:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._baseline: dict[str, str] = {}

    # ---------------- files ----------------
    def resolve(self, rel: str) -> Path:
        if not rel or not isinstance(rel, str):
            raise SandboxError("empty path")
        p = (self.root / rel.strip().lstrip("/")).resolve()
        if p != self.root and self.root not in p.parents:
            raise SandboxError(f"path escapes the workspace: {rel}")
        if any(part in SKIP_DIRS for part in p.relative_to(self.root).parts):
            raise SandboxError(f"path not allowed: {rel}")
        return p

    def write_file(self, rel: str, content: str) -> str:
        p = self.resolve(rel)
        if len(content.encode("utf-8", "ignore")) > MAX_FILE_BYTES:
            raise SandboxError("file too large")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p.relative_to(self.root).as_posix()

    def read_file(self, rel: str, max_chars: int = 12_000) -> str:
        p = self.resolve(rel)
        if not p.is_file():
            raise SandboxError(f"no such file: {rel}")
        return p.read_text(encoding="utf-8", errors="replace")[:max_chars]

    def list_files(self, limit: int = 200) -> list[str]:
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for fn in sorted(filenames):
                out.append((Path(dirpath) / fn).relative_to(self.root).as_posix())
                if len(out) >= limit:
                    return out
        return out

    # ---------------- running things ----------------
    def run(self, cmd: str, timeout: int = 30) -> RunResult:
        try:
            parts = shlex.split(cmd)
        except ValueError as e:
            raise SandboxError(f"cannot parse command: {e}") from e
        if not parts or parts[0] not in ALLOWED_BINARIES:
            raise SandboxError(f"only these commands are allowed: {', '.join(sorted(ALLOWED_BINARIES))}")
        if parts[0] in ("python", "python3"):
            parts[0] = sys.executable
            # block `python -c` / stdin tricks; scripts and -m modules only
            if len(parts) > 1 and parts[1] in ("-c", "-"):
                raise SandboxError("use a script file or -m module, not -c")
        else:  # pytest
            parts = [sys.executable, "-m", "pytest", *parts[1:]]
        for a in parts[1:]:
            if not a.startswith("-") and (a.startswith("/") or ".." in Path(a).parts):
                raise SandboxError(f"argument leaves the workspace: {a}")

        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join(
                [str(self.root)] + ([str(self.root / "repo")] if (self.root / "repo").is_dir() else [])
            ),
            "LANG": "C.UTF-8",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",  # third-party pytest plugins are not needed and can break isolation
        }  # deliberately no API keys
        if os.name == "nt":
            # Windows needs these to start Python and initialise sockets (otherwise WinError 10106)
            for key in ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"):
                if key in os.environ:
                    env[key] = os.environ[key]
            env["USERPROFILE"] = str(self.root)
        import time

        t0 = time.time()
        try:
            proc = subprocess.run(
                parts,
                cwd=self.root,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                preexec_fn=_limit_resources if os.name == "posix" else None,
                start_new_session=True,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            return RunResult(cmd, proc.returncode, _tail(out), False, round(time.time() - t0, 2))
        except subprocess.TimeoutExpired as e:
            partial = ((e.stdout or b"") if isinstance(e.stdout, bytes) else (e.stdout or "")) or ""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", "replace")
            return RunResult(cmd, -1, _tail(partial + f"\n[timed out after {timeout}s]"), True, float(timeout))

    def has_tests(self) -> bool:
        for f in self.list_files(400):
            name = Path(f).name
            if name.startswith("test_") and name.endswith(".py") or name.endswith("_test.py"):
                return True
        return False

    def run_tests(self, timeout: int = 60) -> RunResult:
        if not self.has_tests():
            return RunResult("pytest", 5, "no tests found", False, 0.0)
        return self.run("pytest -x -q --no-header -p no:cacheprovider", timeout=timeout)

    def compile_check(self) -> RunResult:
        pys = [f for f in self.list_files(400) if f.endswith(".py")]
        if not pys:
            return RunResult("compile", 5, "no python files", False, 0.0)
        errors = []
        for f in pys:
            try:
                compile((self.root / f).read_text(encoding="utf-8", errors="replace"), f, "exec")
            except SyntaxError as e:
                errors.append(f"{f}:{e.lineno}: {e.msg}")
        if errors:
            return RunResult("compile", 1, "\n".join(errors)[:MAX_OUTPUT_CHARS])
        return RunResult("compile", 0, f"{len(pys)} python file(s) compile")

    # ---------------- snapshots / diffs ----------------
    def _read_all(self) -> dict[str, str]:
        files: dict[str, str] = {}
        for rel in self.list_files(2000):
            p = self.root / rel
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
                files[rel] = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
        return files

    def snapshot(self) -> None:
        self._baseline = self._read_all()

    def changed_files(self) -> list[str]:
        now = self._read_all()
        changed = [f for f, c in now.items() if self._baseline.get(f) != c]
        changed += [f for f in self._baseline if f not in now]
        return sorted(set(changed))

    def diff(self, max_chars: int = 8000) -> str:
        now = self._read_all()
        chunks: list[str] = []
        for f in self.changed_files():
            a = self._baseline.get(f, "").splitlines(keepends=True)
            b = now.get(f, "").splitlines(keepends=True)
            chunks.extend(difflib.unified_diff(a, b, f"a/{f}", f"b/{f}", n=2))
        text = "".join(chunks)
        return text[:max_chars] + ("\n... [diff truncated]" if len(text) > max_chars else "")

    # ---------------- repo attach ----------------
    def attach_repo(self, source: str) -> dict:
        """Copy a local folder or shallow-clone a GitHub URL into the workspace."""
        info: dict = {"source": source, "kind": "", "log": ""}
        if source.startswith(("http://", "https://")):
            if not source.startswith("https://github.com/"):
                raise SandboxError("only https://github.com/ URLs can be cloned")
            if shutil.which("git") is None:
                raise SandboxError("git is not installed")
            target = self.root / "repo"
            if target.exists():
                shutil.rmtree(target)
            proc = subprocess.run(
                ["git", "clone", "--depth", "20", source, str(target)],
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode != 0:
                raise SandboxError(f"git clone failed: {proc.stderr.strip()[:200]}")
            info["kind"] = "github"
            info["log"] = self._git_log(target)
        else:
            src = Path(source).expanduser().resolve()
            if not src.is_dir():
                raise SandboxError(f"not a directory: {source}")
            target = self.root / "repo"
            if target.exists():
                shutil.rmtree(target)
            count = 0

            def _ignore(d: str, names: list[str]) -> list[str]:
                nonlocal count
                keep_out = [n for n in names if n in SKIP_DIRS - {".git"}]
                count += len(names)
                if count > 5000:
                    raise SandboxError("repository too large (limit 5000 entries)")
                return keep_out

            shutil.copytree(src, target, ignore=_ignore, symlinks=False)
            info["kind"] = "local"
            info["log"] = self._git_log(target)
        # ensure the git history is never shown to / modified by model-run code
        shutil.rmtree(target / ".git", ignore_errors=True)
        info["tree"] = [f for f in self.list_files(80)]
        readme = next((f for f in self.list_files(400) if Path(f).name.lower().startswith("readme")), None)
        info["readme"] = self.read_file(readme, 1500) if readme else ""
        self.snapshot()
        return info

    @staticmethod
    def _git_log(path: Path) -> str:
        if shutil.which("git") is None or not (path / ".git").exists():
            return ""
        try:
            proc = subprocess.run(
                ["git", "-C", str(path), "log", "-8", "--pretty=format:%h %s"],
                capture_output=True, text=True, timeout=10,
            )
            return proc.stdout.strip()
        except Exception:
            return ""


def _tail(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else "...[truncated]...\n" + text[-limit:]