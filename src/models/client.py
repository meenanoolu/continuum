"""
One OpenAI-compatible client for both Meta endpoints Continuum uses:

  * Meta Model API  (Muse Spark 1.x, closed weights)    -> max_completion_tokens
  * Baseten         (Muse Spark Open, open weights)     -> max_tokens

Key fact from the Meta docs: Muse Spark always reasons internally, and reasoning tokens
count against the output cap. A small cap therefore yields EMPTY visible content. The old
code used tiny caps (400-700) and silently got "" back. This client adds reasoning
headroom to every cap, lowers reasoning effort, and retries once with a bigger budget
when the answer comes back empty with finish_reason == "length".
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from openai import BadRequestError, OpenAI

from src import trace
from src.jsonutil import extract_json
from src.utils import console


class LLMError(RuntimeError):
    """Raised when every provider failed for a request."""


@dataclass
class Completion:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""
    provider: str = ""
    model: str = ""
    tokens: int | None = None
    # message dict that can be replayed verbatim into the next request (tool loops)
    raw_message: dict[str, Any] = field(default_factory=dict)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class LLMClient:
    def __init__(
        self,
        *,
        provider: str,
        api_key: str | None,
        base_url: str,
        model: str,
        token_param: str,
        reasoning_effort: str | None,
    ):
        self.provider = provider
        self.model = model
        self.token_param = token_param
        self.reasoning_effort = reasoning_effort
        self.reasoning_headroom = _int_env("REASONING_HEADROOM", 2500)
        self.client: OpenAI | None = None
        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=180, max_retries=2)

    @property
    def available(self) -> bool:
        return self.client is not None

    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    # ------------------------------------------------------------------
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        purpose: str = "chat",
        max_tokens: int = 1200,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> Completion:
        """`max_tokens` is the size of the VISIBLE answer you want; headroom is added for reasoning."""
        if self.client is None:
            raise LLMError(f"{self.provider} is not configured (missing API key)")

        budget = max_tokens + self.reasoning_headroom
        started = time.time()
        for attempt in range(2):
            try:
                comp = self._call(messages, budget, temperature, tools)
            except Exception as e:  # network, auth, 4xx, 5xx after SDK retries
                trace.record(
                    purpose=purpose, provider=self.provider, model=self.model,
                    ms=int((time.time() - started) * 1000), tokens=None, ok=False, note=str(e)[:160],
                )
                raise LLMError(f"{self.label()}: {e}") from e

            empty = not comp.content.strip() and not comp.tool_calls
            if empty and comp.finish_reason == "length" and attempt == 0:
                budget = min(budget * 3, 16000)  # reasoning ate the budget; try once more
                continue
            trace.record(
                purpose=purpose, provider=self.provider, model=self.model,
                ms=int((time.time() - started) * 1000), tokens=comp.tokens, ok=not empty,
                note="empty reply" if empty else "",
            )
            return comp
        raise LLMError(f"{self.label()}: empty reply after retry")  # pragma: no cover

    def _call(self, messages, budget, temperature, tools) -> Completion:
        assert self.client is not None
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages, self.token_param: budget}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort

        try:
            resp = self.client.chat.completions.create(**kwargs)
        except BadRequestError:
            # Some hosts reject the optional reasoning_effort param; drop it once and retry.
            if "reasoning_effort" not in kwargs:
                raise
            kwargs.pop("reasoning_effort")
            resp = self.client.chat.completions.create(**kwargs)

        if not resp.choices:
            return Completion(provider=self.provider, model=self.model)
        choice = resp.choices[0]
        msg = choice.message
        calls: list[dict[str, Any]] = []
        for tc in getattr(msg, "tool_calls", None) or []:
            calls.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                }
            )
        raw: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if calls:
            raw["tool_calls"] = calls
        usage = getattr(resp, "usage", None)
        return Completion(
            content=(msg.content or "").strip(),
            tool_calls=calls,
            finish_reason=choice.finish_reason or "",
            provider=self.provider,
            model=self.model,
            tokens=getattr(usage, "total_tokens", None),
            raw_message=raw,
        )


# ----------------------------------------------------------------------
def make_meta_client() -> LLMClient:
    return LLMClient(
        provider="meta-api",
        api_key=os.getenv("META_API_KEY") or os.getenv("MODEL_API_KEY"),
        base_url=os.getenv("META_BASE_URL", "https://api.meta.ai/v1"),
        model=os.getenv("META_MODEL", "muse-spark-1.3"),
        token_param="max_completion_tokens",
        reasoning_effort=os.getenv("META_REASONING_EFFORT", "low"),
    )


def make_open_client() -> LLMClient:
    return LLMClient(
        provider="baseten",
        api_key=os.getenv("BASETEN_API_KEY"),
        base_url=os.getenv("BASETEN_BASE_URL", "https://inference.baseten.co/v1"),
        model=os.getenv("BASETEN_MODEL", "meta-models/muse-spark-open-1026"),
        token_param="max_tokens",
        reasoning_effort=os.getenv("BASETEN_REASONING_EFFORT", "low"),
    )


class Models:
    """Routes calls to the preferred provider and falls back to the other one."""

    def __init__(self, meta: Any, open_weight: Any):
        self.meta = meta
        self.open = open_weight

    def status(self) -> dict[str, Any]:
        return {
            "meta": {"available": self.meta.available, "model": self.meta.model, "provider": self.meta.provider},
            "open": {"available": self.open.available, "model": self.open.model, "provider": self.open.provider},
        }

    def any_available(self) -> bool:
        return self.meta.available or self.open.available

    def _order(self, prefer: str, only: str | None = None) -> list[Any]:
        if only:
            c = self.meta if only == "meta" else self.open
            return [c] if c.available else []
        first, second = (self.meta, self.open) if prefer == "meta" else (self.open, self.meta)
        return [c for c in (first, second) if c.available]

    def complete(
        self,
        prefer: str,
        purpose: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1200,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        only: str | None = None,
    ) -> Completion:
        """`only` disables fallback: the call must be served by that provider or raise LLMError."""
        order = self._order(prefer, only)
        if not order:
            raise LLMError("No model provider configured. Set META_API_KEY and/or BASETEN_API_KEY.")
        errors: list[str] = []
        for i, client in enumerate(order):
            try:
                comp = client.complete(
                    messages, purpose=purpose, max_tokens=max_tokens, temperature=temperature, tools=tools
                )
                if i > 0:
                    console.print(f"[yellow]{purpose}: fell back to {client.label()}[/yellow]")
                return comp
            except LLMError as e:
                errors.append(str(e))
        raise LLMError("; ".join(errors))

    def json(
        self,
        prefer: str,
        purpose: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1500,
        validate: Any = None,
    ) -> Any | None:
        """Ask for JSON; one corrective retry; returns parsed object or None (never raises)."""
        msgs = list(messages)
        for attempt in range(2):
            try:
                comp = self.complete(prefer, purpose, msgs, max_tokens=max_tokens)
            except LLMError as e:
                console.print(f"[red]{purpose}: {e}[/red]")
                return None
            data = extract_json(comp.content)
            if data is not None and (validate is None or validate(data)):
                return data
            msgs = msgs + [
                {"role": "assistant", "content": comp.content[:1500]},
                {"role": "user", "content": "That was not valid JSON in the required shape. Reply with ONLY the JSON."},
            ]
        return None

    def describe_image(self, data_url: str, instruction: str, purpose: str = "vision") -> str:
        """Muse Spark vision (Meta API first; Muse Spark Open on Baseten also accepts images)."""
        content = [
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        comp = self.complete("meta", purpose, [{"role": "user", "content": content}], max_tokens=600)
        return comp.content
