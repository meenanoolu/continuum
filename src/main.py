"""Terminal interface. The web UI (python -m src.api) is the main experience; this is the same loop in a shell."""
from __future__ import annotations

from src.orchestrator import Orchestrator, OrchestratorError
from src.utils import console


def _ask(prompt: str) -> str:
    return input(prompt).strip()


def main() -> None:
    console.print("[bold green]Continuum[/bold green] - forces understanding. Grows with you.\n")
    orch = Orchestrator()
    try:
        orch.start_project(_ask("Project name: ") or "default-project", _ask("Attach a repo (path or GitHub URL, optional): ") or None)
        console.print("\n[bold]Describe only the NEXT meaningful piece of work[/bold] (2-4 sentences):")
        orch.require_plan(_ask("> "))
    except OrchestratorError as e:
        console.print(f"[red]{e}[/red]")
        return

    def emit(kind: str, text: str) -> None:
        console.print(f"  [dim]{kind}[/dim] {text}")

    while orch.state["phase"] == "planned":
        for i, s in enumerate(orch.state["plan"], 1):
            mark = "x" if s["status"] == "done" else " "
            console.print(f"[{mark}] {i}. ({s['kind']}) {s['title']}")
        if _ask("\nRun the next step? (y/q): ").lower() != "y":
            break
        orch.run_step(emit)
        gate = orch.state["gate"]
        if not gate:
            console.print(f"[red]{orch.state['error']}[/red]")
            continue
        ev = orch.state["last_result"]["evidence"]
        console.print(f"\n[bold]Evidence:[/bold] {ev['level']} - {ev['headline']}")
        console.print("[bold]Reflection[/bold]", gate["reflection"])
        console.print("[bold]Explanation[/bold]\n" + gate["explanation"])
        if gate["policy"]["strictness"] == "strict":
            console.print("[yellow]Strict Gate: " + "; ".join(gate["policy"]["reasons"]) + "[/yellow]")
        while orch.state["phase"] == "awaiting_human":
            eb = _ask("\nExplain back in your own words:\n> ")
            answers = [_ask(f"{i}. {q['question']}\n> ") for i, q in enumerate(gate["questions"], 1)]
            try:
                res = orch.submit_answers(eb, answers)
            except OrchestratorError as e:
                console.print(f"[red]{e}[/red]")
                continue
            if res["status"] in ("rejected", "grader_error"):
                console.print(f"[red]{res['reason']}[/red]")
                continue
            console.print(f"\n{res['feedback']}  (score {res['score']} / needed {res['threshold']})")
        while orch.state["phase"] == "learning":
            lp = orch.state["gate"]["learning"]
            console.print(f"\n[bold red]GATE BLOCKED[/bold red] - learning path: {lp['concept']}")
            for i, item in enumerate(lp["items"], 1):
                console.print(f"  {i}. {item}")
            conf = _ask("What did you learn?\n> ")
            ans = _ask(f"{lp['retry_question']}\n> ")
            res = orch.complete_learning(conf, ans)
            console.print(res.get("feedback") or res.get("reason", ""))
    console.print("\n[bold]Session ended. Personal memory updated.[/bold]")


if __name__ == "__main__":
    main()
