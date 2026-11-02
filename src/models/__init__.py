from __future__ import annotations

import os

from .client import Completion, LLMClient, LLMError, Models, make_meta_client, make_open_client

# Backwards-compatible names used by older code / notes
MuseSparkClient = make_meta_client
OpenWeightClient = make_open_client

_models: Models | None = None


def get_models() -> Models:
    """Process-wide router. CONTINUUM_FAKE_LLM=1 swaps in a deterministic offline fake (tests/dev only)."""
    global _models
    if _models is None:
        if os.getenv("CONTINUUM_FAKE_LLM") == "1":
            from .fake import FakeLLM

            _models = Models(FakeLLM("meta-api", "muse-spark-1.3"), FakeLLM("baseten", "muse-spark-open-fake"))
        else:
            _models = Models(make_meta_client(), make_open_client())
    return _models


def reset_models() -> None:
    global _models
    _models = None


__all__ = [
    "Completion", "LLMClient", "LLMError", "Models", "get_models", "reset_models",
    "MuseSparkClient", "OpenWeightClient",
]
