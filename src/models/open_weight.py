from __future__ import annotations
import os
from typing import Any
from openai import OpenAI
from src.utils import get_env, console

class OpenWeightClient:
    """
    Client for Muse Spark Open via Baseten (primary).
    Used for specialized Workers only.
    """

    def __init__(self):
        api_key = os.getenv("BASETEN_API_KEY")
        base_url = os.getenv("BASETEN_BASE_URL", "https://inference.baseten.co/v1")
        self.model = os.getenv("BASETEN_MODEL", "meta-models/muse-spark-open-1026")

        if not api_key:
            self.client = None
            console.print("[yellow]BASETEN_API_KEY not set – OpenWeightClient disabled for now[/yellow]")
            return

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.4,
        max_tokens: int = 2048,
    ) -> str:
        if self.client is None:
            raise RuntimeError("OpenWeightClient is not configured (missing BASETEN_API_KEY)")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            console.print(f"[red]OpenWeight error: {e}[/red]")
            raise

    def test_connection(self) -> bool:
        if self.client is None:
            console.print("[yellow]OpenWeightClient skipped (no Baseten key yet)[/yellow]")
            return False
        try:
            reply = self.chat(
                messages=[{"role": "user", "content": "Reply with exactly: Worker ready"}],
                max_tokens=20,
                temperature=0,
            )
            console.print(f"[green]OpenWeight connection OK → {reply.strip()}[/green]")
            return True
        except Exception as e:
            console.print(f"[red]OpenWeight connection failed: {e}[/red]")
            return False