from __future__ import annotations
from src.orchestrator import Orchestrator
from src.utils import console

def main():
    console.print("[bold green]Continuum – Personal Multi-Agent System[/bold green]")
    console.print("Forces understanding. Grows with you.\n")

    orch = Orchestrator()

    # 1. Start project
    project = input("Project name: ").strip() or "default-project"
    orch.start_project(project)

    # 2. Require a concrete plan
    console.print("\n[bold]Describe only the NEXT meaningful piece of work[/bold] (2-4 sentences):")
    user_plan = input("> ").strip()

    try:
        steps = orch.require_plan(user_plan)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return

    # 3. Execute steps one by one with the Gate
    while True:
        if orch.current_step_index >= len(orch.current_plan):
            console.print("\n[bold green]Current plan completed.[/bold green]")
            break

        step = orch.current_plan[orch.current_step_index]
        console.print(f"\n[bold]Next step ({orch.current_step_index + 1}/{len(orch.current_plan)}):[/bold] {step}")

        proceed = input("Run this step? (y/n/q): ").strip().lower()
        if proceed == "q":
            break
        if proceed != "y":
            continue

        # Decide which worker to use
        step_lower = step.lower()
        if any(word in step_lower for word in ["test", "verify", "check", "validate"]):
            from src.workers import TestWorker
            worker = TestWorker()
        elif any(word in step_lower for word in ["research", "find", "gather", "investigate", "docs", "look up"]):
            from src.workers import ResearchWorker
            worker = ResearchWorker()
        else:
            from src.workers import CodeWorker
            worker = CodeWorker()

        # Run the chosen Worker
        worker_output = worker.run(step)

        # Force the Gate
        result = orch.run_next_step(worker_output=worker_output)

        if result["status"] == "blocked_by_gate":
            console.print("\n[bold red]Gate blocked the next step.[/bold red]")
            console.print("Complete the learning path above, then come back and continue.")
            break

        if result["status"] == "plan_complete":
            break

    console.print("\n[bold]Session ended. Personal memory has been updated.[/bold]")

if __name__ == "__main__":
    main()