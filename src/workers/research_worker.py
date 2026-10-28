from __future__ import annotations
from src.models import OpenWeightClient, MuseSparkClient
from src.utils import console

class ResearchWorker:
    def __init__(self):
        self.open_weight = OpenWeightClient()
        self.muse = MuseSparkClient()

    def run(self, step: str, context: str = "") -> str:
        console.print(f"[blue]ResearchWorker working on:[/blue] {step}")

        prompt = f"""You are the Research Worker in Continuum.
Your job is to gather the key information needed for this step.

Step: {step}
Context: {context}

Return a concise research result with:
- Key findings
- Important constraints or gotchas
- Recommended approach
Do not write full code. Focus on useful information.
"""

        messages = [{"role": "user", "content": prompt}]

        if self.open_weight.client is not None:
            try:
                return self.open_weight.chat(messages, temperature=0.3, max_tokens=1000)
            except Exception:
                pass

        return self.muse.chat(messages, temperature=0.3, max_tokens=1000)