from __future__ import annotations
from src.models import OpenWeightClient, MuseSparkClient
from src.utils import console

class TestWorker:
    def __init__(self):
        self.open_weight = OpenWeightClient()
        self.muse = MuseSparkClient()

    def run(self, step: str, context: str = "") -> str:
        console.print(f"[blue]TestWorker working on:[/blue] {step}")

        prompt = f"""You are the Test Worker in Continuum.
Your job is to think about how to verify that the previous work is correct.

Step: {step}
Context: {context}

Return:
- What should be tested
- Simple test cases or checks
- Clear pass/fail criteria
Be practical and concise.
"""

        messages = [{"role": "user", "content": prompt}]

        if self.open_weight.client is not None:
            try:
                return self.open_weight.chat(messages, temperature=0.3, max_tokens=900)
            except Exception:
                pass

        return self.muse.chat(messages, temperature=0.3, max_tokens=900)