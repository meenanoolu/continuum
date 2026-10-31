from __future__ import annotations
from pathlib import Path
from src.models import MuseSparkClient, OpenWeightClient
from src.utils import console
import os
import re

class CodeWorker:
    """
    Practical CodeWorker (Option A)
    - Generates real code
    - Saves it into workspace/
    - Returns the actual code so the Gate can test understanding on real output
    """

    def __init__(self):
        self.muse = MuseSparkClient()
        self.open_weight = OpenWeightClient() if os.getenv("BASETEN_API_KEY") else None
        self.workspace = Path("workspace")
        self.workspace.mkdir(exist_ok=True)

    def run(self, step: str) -> str:
        console.print(f"[cyan]→ CodeWorker executing: {step}[/cyan]")

        # Prefer open-weight model for Workers when available
        client = self.open_weight if self.open_weight else self.muse
        model_name = "Muse Spark Open (Baseten)" if self.open_weight else "Muse Spark"

        system = (
            "You are a senior software engineer. "
            "Given a concrete coding step, write real, working code. "
            "Reply with the complete code for one or more files. "
            "Use this exact format:\n\n"
            "### FILE: relative/path/to/file.py\n"
            "```python\n"
            "# real code here\n"
            "```\n\n"
            "You may output multiple FILE blocks. "
            "Do not write explanations outside the code blocks."
        )

        user_content = f"Implement this step with real code:\n\n{step}"

        raw = client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=1800,
        )

        if not raw or not raw.strip():
            return (
                f"[CodeWorker using {model_name}]\n"
                "Model returned empty content. No files were written."
            )

        # Parse and save files
        saved_files = self._save_code_blocks(raw)

        if not saved_files:
            # Fallback: save the whole response as a single file
            fallback_path = self.workspace / "generated_step.py"
            fallback_path.write_text(raw, encoding="utf-8")
            saved_files = [str(fallback_path)]

        summary = (
            f"[CodeWorker using {model_name}]\n"
            f"Step: {step}\n\n"
            f"Files written:\n" + "\n".join(f"- {f}" for f in saved_files) + "\n\n"
            f"Generated code:\n{raw[:3000]}"
        )

        console.print(f"[green]✓ CodeWorker wrote {len(saved_files)} file(s)[/green]")
        return summary

    def _save_code_blocks(self, text: str) -> list[str]:
        """Extract ### FILE: path blocks and save them."""
        saved = []
        # Pattern: ### FILE: path\n```lang\ncode\n```
        pattern = r"###\s*FILE:\s*([^\n]+)\n```(?:\w+)?\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)

        for rel_path, code in matches:
            rel_path = rel_path.strip().lstrip("./")
            if not rel_path or ".." in rel_path:
                continue

            file_path = self.workspace / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(code.strip() + "\n", encoding="utf-8")
            saved.append(str(file_path))

        return saved