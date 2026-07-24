"""HackDox — Game Engine CLI.

Entry point. v1 commands:

    new-game        Start a fresh save.
    play            Launch the Textual TUI (Day 1 vertical slice).
    simulate        Headless smoke-test: generate Day 1's candidates,
                    evaluate them against the rules, and dump a report.
                    Useful for verifying the engine without UI.
    inspect         Generate a single candidate by seed/day/slot and
                    pretty-print the dossier + ground truth.

The Textual UI (`play`) is implemented in `gameengine/ui/tui/app.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Make `ghostscan`, `logwatch`, etc. importable for the in-process tool bridge.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gameengine import config
from gameengine.core import candidate_gen, rules_engine, scoring
from gameengine.core.content_loader import load_day, load_narratives
from gameengine.core.models import Archetype, GameState, Verdict


app = typer.Typer(add_completion=False, help="HackDox game engine.")
console = Console()


@app.command("new-game")
def new_game(seed: int = typer.Option(0xC0FFEE, help="RNG seed for the run.")) -> None:
    """Wipe the save slot and start fresh."""
    state = GameState(
        seed=seed,
        current_day=1,
        compute_hours=config.daily_compute_budget(1, config.STARTING_COMPUTE),
        compute_capacity=config.STARTING_COMPUTE,
        alignment=config.STARTING_ALIGNMENT,
        site_health=config.SITE_HEALTH_START,
        hackdollars=config.STARTING_HACKDOLLARS,
        hackdox_credits=config.STARTING_HACKDOX_CREDITS,
    )
    # Persistence module is TODO — for now just announce.
    console.print(Panel.fit(
        f"[bold green]New game ready.[/]\nSeed: [cyan]{state.seed:#x}[/]  "
        f"Compute: {state.compute_hours}⏱  Site Health: {state.site_health:.0f}%  "
        f"HD$: {state.hackdollars}  Credits: {state.hackdox_credits}",
        title="HackDox",
    ))


@app.command("simulate")
def simulate(
    seed: int = typer.Option(0xC0FFEE, help="RNG seed."),
    day_number: int = typer.Option(1, "--day", help="Which day to simulate."),
) -> None:
    """Headless: generate the day's candidates and dump a verdict table.

    Auto-verdict policy for the smoke test: ADMIT iff the rules engine
    finds zero disqualifying triggers. This is the "by-the-book" player —
    they always follow the rulebook. Use this to confirm the foundation
    is wired up before the Textual UI lands.
    """
    day = load_day(day_number)
    narratives = load_narratives()
    state = GameState(seed=seed)

    console.print(Panel(
        narratives[day.overseer_intro_key],
        title=f"[cyan]Overseer — {day.title}",
        border_style="cyan",
    ))

    table = Table(title=f"Day {day.number} — by-the-book simulation", show_lines=False)
    table.add_column("#", justify="right")
    table.add_column("Candidate")
    table.add_column("Archetype", style="dim")
    table.add_column("Disqual. rules")
    table.add_column("Auto verdict")
    table.add_column("Ground truth")
    table.add_column("Correct?")

    for slot in range(day.candidate_count):
        candidate = candidate_gen.generate(seed, day, slot)
        evaluation = rules_engine.evaluate(candidate, day)
        auto = Verdict.DENY if evaluation.triggered_disqualifying else Verdict.ADMIT
        result = scoring.apply(candidate, auto, state)
        rule_ids = ", ".join(r.id for r in evaluation.triggered_disqualifying) or "—"
        table.add_row(
            str(slot + 1),
            f"{candidate.display_name} ({candidate.handle})",
            candidate.archetype.value,
            rule_ids,
            auto.value,
            candidate.truth.correct_verdict.value,
            "[green]✓[/]" if result.correct else "[red]✗[/]",
        )

    console.print(table)
    console.print(Panel.fit(
        f"Compute: {state.compute_hours}⏱    Site Health: {state.site_health:.0f}%    "
        f"HD$: {state.hackdollars}    Alignment: {state.alignment:+d}",
        title="End of simulation",
    ))


@app.command("inspect")
def inspect(
    seed: int = typer.Option(0xC0FFEE, help="RNG seed."),
    day_number: int = typer.Option(1, "--day"),
    slot: int = typer.Option(0, "--slot"),
) -> None:
    """Print a single candidate in full — useful for content tuning."""
    day = load_day(day_number)
    candidate = candidate_gen.generate(seed, day, slot)

    body = Table.grid(padding=(0, 2))
    body.add_row("Name:", candidate.display_name)
    body.add_row("Handle:", candidate.handle)
    body.add_row("Email:", candidate.email)
    body.add_row("Affiliation:", candidate.claimed_affiliation)
    body.add_row("Purpose:", candidate.claimed_purpose)
    body.add_row("Archetype (hidden):", f"[yellow]{candidate.archetype.value}[/]")
    body.add_row("Correct verdict (hidden):", f"[yellow]{candidate.truth.correct_verdict.value}[/]")
    body.add_row("Moral modifier:", str(candidate.truth.moral_modifier))
    console.print(Panel(body, title=f"Candidate slot {slot}", border_style="magenta"))

    if candidate.truth.discrepancies:
        disc_table = Table(title="Planted discrepancies", show_header=True)
        disc_table.add_column("Kind")
        disc_table.add_column("Severity")
        disc_table.add_column("Revealed by")
        disc_table.add_column("Description")
        for d in candidate.truth.discrepancies:
            disc_table.add_row(d.kind.value, d.severity, d.revealed_by.value, d.description)
        console.print(disc_table)
    else:
        console.print("[dim]No discrepancies planted (clean dossier).[/]")

    chat_table = Table(title="Chat script", show_header=False, box=None)
    for line in candidate.chat_script:
        chat_table.add_row(f"[dim]{line.timestamp}[/]", f"[italic]{line.text}[/]")
    console.print(chat_table)


@app.command("play")
def play(seed: int = typer.Option(0xC0FFEE, help="RNG seed for the run.")) -> None:
    """Launch the Textual TUI (Day 1 vertical slice)."""
    try:
        from gameengine.ui.tui.app import run as run_tui
    except ImportError as e:
        console.print(f"[red]Could not import Textual UI:[/] {e}")
        console.print("Install Textual: [cyan]pip install textual[/]")
        raise typer.Exit(code=1)
    run_tui(seed=seed)


if __name__ == "__main__":
    app()
