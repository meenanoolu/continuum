"""Tiny in-process trace of every model call, so the UI can show which Meta model did what."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

_lock = threading.Lock()
_calls: deque[dict[str, Any]] = deque(maxlen=200)


def record(
    *,
    purpose: str,
    provider: str,
    model: str,
    ms: int,
    tokens: int | None,
    ok: bool,
    fallback_from: str | None = None,
    note: str = "",
) -> None:
    with _lock:
        _calls.append(
            {
                "t": time.time(),
                "purpose": purpose,
                "provider": provider,
                "model": model,
                "ms": ms,
                "tokens": tokens,
                "ok": ok,
                "fallback_from": fallback_from,
                "note": note,
            }
        )


def recent(limit: int = 15) -> list[dict[str, Any]]:
    with _lock:
        return list(_calls)[-limit:]


def summary() -> dict[str, dict[str, int]]:
    """Calls per provider/model, for the footer of the UI."""
    out: dict[str, dict[str, int]] = {}
    with _lock:
        for c in _calls:
            key = f"{c['provider']}|{c['model']}"
            slot = out.setdefault(key, {"calls": 0, "tokens": 0})
            slot["calls"] += 1
            slot["tokens"] += c["tokens"] or 0
    return out


def clear() -> None:
    with _lock:
        _calls.clear()
