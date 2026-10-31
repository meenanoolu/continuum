from __future__ import annotations
import os
from typing import Any
from openai import OpenAI
from src.utils import get_env, console

class MuseSparkClient:
    """
    Client for Meta Model API (Muse Spark / Muse Wonder).
    Used only for Orchestrator, reflections, explanations, learning paths.
    """

    def __init__(self):
        api_key = get_env("META_API_KEY")
        base_url = os.getenv("META_BASE_URL", "https://api.meta.ai/v1")

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.default_model = "muse-spark-1.3"

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        reasoning_effort: str | None = None,
    ) -> str:
        model = model or self.default_model

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            console.print(f"[dim]DEBUG raw response type: {type(response)}[/dim]")

            if not response.choices:
                console.print("[red]No choices in response[/red]")
                return ""

            message = response.choices[0].message
            content = message.content

            if content is None or str(content).strip() == "":
                console.print("[red]Model returned empty content[/red]")
                console.print(f"[dim]Full message object: {message}[/dim]")
                return ""

            return str(content).strip()

        except Exception as e:
            console.print(f"[red]MuseSpark error: {e}[/red]")
            raise

    def test_connection(self) -> bool:
        try:
            reply = self.chat(
                messages=[{"role": "user", "content": "Reply with exactly: Continuum ready"}],
                max_tokens=20,
                temperature=0,
            )
            console.print(f"[green]MuseSpark connection OK → {reply}[/green]")
            return True
        except Exception as e:
            console.print(f"[red]MuseSpark connection failed: {e}[/red]")
            return False