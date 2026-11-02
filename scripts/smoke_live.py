"""
30-second check of your REAL keys. Run:  python scripts/smoke_live.py
Prints PASS/FAIL for every capability Continuum depends on, so you find API surprises before the demo.
"""
from __future__ import annotations

import base64
import json
import sys
import zlib
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import tool_defs  # noqa: E402
from src.jsonutil import extract_json  # noqa: E402
from src.models import LLMError, get_models  # noqa: E402


def tiny_png() -> str:
    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes([220, 30, 30]) * 8 for _ in range(8))  # 8x8 solid red
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


def check(name: str, fn) -> bool:
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{type(e).__name__}: {str(e)[:160]}"
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok


def main() -> int:
    m = get_models()
    print(json.dumps(m.status(), indent=2))
    results = []

    if m.meta.available:
        results.append(check("Meta API: plain answer (not empty)", lambda: (
            lambda c: (bool(c.content), f"{c.content[:60]!r} finish={c.finish_reason}")
        )(m.meta.complete([{"role": "user", "content": "Reply with exactly: ready"}], purpose="smoke", max_tokens=50))))
        results.append(check("Meta API: JSON answer parses", lambda: (
            lambda d: (isinstance(d, dict) and "ok" in d, str(d))
        )(m.json("meta", "smoke.json", [{"role": "user", "content": 'Reply with ONLY this JSON: {"ok": true}'}], max_tokens=100))))
        results.append(check("Meta API: tool calling", lambda: (
            lambda c: (bool(c.tool_calls), f"tool_calls={[t['function']['name'] for t in c.tool_calls]}")
        )(m.meta.complete([{"role": "user", "content": "List the files in the workspace using the tool."}], purpose="smoke.tools",
                          max_tokens=200, tools=tool_defs(["list_files"])))))
        results.append(check("Meta API: vision (image input)", lambda: (
            lambda t: (bool(t.strip()), t[:80])
        )(m.describe_image(tiny_png(), "What colour is this image? One word.", purpose="smoke.vision"))))
    else:
        print("[SKIP] Meta API not configured (META_API_KEY)")

    if m.open.available:
        results.append(check("Baseten Muse Spark Open: plain answer (not empty)", lambda: (
            lambda c: (bool(c.content), f"{c.content[:60]!r} finish={c.finish_reason}")
        )(m.open.complete([{"role": "user", "content": "Reply with exactly: ready"}], purpose="smoke.open", max_tokens=50))))
        results.append(check("Baseten Muse Spark Open: native tool calling", lambda: (
            lambda c: (bool(c.tool_calls), f"tool_calls={[t['function']['name'] for t in c.tool_calls]} "
                       "(if FAIL, Continuum automatically uses its text protocol on Open)")
        )(m.open.complete([{"role": "user", "content": "List the files in the workspace using the tool."}], purpose="smoke.open.tools",
                          max_tokens=200, tools=tool_defs(["list_files"])))))
    else:
        print("[SKIP] Baseten not configured (BASETEN_API_KEY)")

    print("\nModel trace shows token use per call; check your Billing page for credit burn.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
