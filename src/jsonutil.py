"""Robust JSON extraction from model output (fences, prose around JSON, trailing text)."""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json|JSON)?")


def extract_json(text: str | None) -> Any | None:
    """Return the first valid JSON object/array found in `text`, or None."""
    if not text:
        return None
    cleaned = _FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    for i, ch in enumerate(cleaned):
        if ch not in "{[":
            continue
        end = _match_bracket(cleaned, i)
        if end == -1:
            continue
        try:
            return json.loads(cleaned[i : end + 1])
        except Exception:
            continue
    return None


def _match_bracket(s: str, start: int) -> int:
    """Index of the bracket closing s[start], string-aware; -1 if unbalanced."""
    opener = s[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i
    return -1
