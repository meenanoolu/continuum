from __future__ import annotations
import os
from openai import OpenAI
from src.utils import get_env, console

class MuseSparkClient:
    def __init__(self):
        api_key = get_env("META_API_KEY")
        base_url = os.getenv("META_BASE_URL", "https://api.meta.ai/v1")

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.default_model = os.getenv("META_MODEL", "muse-spark-1.3")
        self.model = self.default_model

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        model = model or self.default_model
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if not response.choices:
                return ""
            content = response.choices[0].message.content
            if content is None or str(content).strip() == "":
                console.print("[yellow]MuseSpark returned empty content[/yellow]")
                return ""
            return str(content).strip()
        except Exception as e:
            console.print(f"[red]MuseSpark error: {e}[/red]")
            return ""