from __future__ import annotations
from src.models import OpenWeightClient, MuseSparkClient
from src.utils import console

class CodeWorker:
    """
    Specialized Worker for coding tasks.
    Prefers open-weight (Baseten) when available, falls back to MuseSpark only if necessary.
    """

    def __init__(self):
        self.open_weight = OpenWeightClient()
        self.muse = MuseSparkClient()

    def run(self, step: str, context: str = "") -> str:
        console.print(f"[blue]CodeWorker working on:[/blue] {step}")

        prompt = f"""You are the Code Worker in Continuum.
Your job is to perform the following coding step and return a clear, concrete result.

Step: {step}

Additional context:
{context}

Return:
- What you did
- Key code changes or decisions (if any)
- Any problems you encountered
Be concise and factual.
"""

        messages = [{"role": "user", "content": prompt}]

        # Prefer open-weight when available
        if self.open_weight.client is not None:
            try:
                return self.open_weight.chat(messages, temperature=0.3, max_tokens=1200)
            except Exception as e:
                console.print(f"[yellow]OpenWeight failed ({e}), falling back to MuseSpark[/yellow]")

        # Fallback (uses your Meta credits – keep this rare)
        return self.muse.chat(messages, temperature=0.3, max_tokens=1200)