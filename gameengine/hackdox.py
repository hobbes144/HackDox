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
from gameengine.core import candidate_gen, rules_engine, scoring, tools_bridge
from gameengine.core.content_loader import load_day, load_narratives, synthesize_day
from gameengine.core.models import (
    Archetype,
    DiscrepancyKind,
    GameState,
    ToolName,
    Verdict,
)

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
        # #38: simulate already has the evaluation in hand - pass it so the
        # headless run records both scoring tracks too.
        result = scoring.apply(candidate, auto, state, evaluation=evaluation)
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


# ─── lab — controlled candidate generation (issue #52) ───────────────────────
#
# Chasing a generation or rendering bug used to mean rolling seeds until the
# case you wanted appeared. Every audit sweep in this codebase was written by
# hand with dataclasses.replace to pin an archetype and a day — which is the
# friction this command removes.
#
# It deliberately builds its day through content_loader.synthesize_day (#17) and
# runs the REAL filtered tool output, rather than reimplementing either. A lab
# that doesn't exercise the same code path as play would happily show a case
# that works here and breaks in a shift.


def _lab_day(day_number: int, archetypes: list[str], violations: list[str],
             count: int):
    """A synthesized day constrained to the requested archetypes/violations."""
    from dataclasses import replace

    day = synthesize_day(day_number) if day_number > 1 else load_day(1)
    forced = {i: Archetype(a) for i, a in enumerate(archetypes[:count])}
    mix = dict(day.archetype_mix)
    for arch in forced.values():
        mix[arch] = mix.get(arch, 0) + 1
    allowed = tuple(DiscrepancyKind(v) for v in violations)
    return replace(day, number=day_number, candidate_count=count,
                   forced_includes=forced, archetype_mix=mix,
                   allowed_violations=allowed)


def _lab_tool_output(candidate, tool: ToolName, day, seed: int) -> list[str]:
    """The real filtered output of `tool` for this candidate.

    The shared Logwatch/Hashcrack day logs are built per (seed, day) and contain
    a block per candidate in the roster, so the seed must be the one the
    candidate came from — passing a different one yields a log the candidate
    simply is not in, which looks exactly like a rendering bug and isn't.
    """
    state = GameState(seed=seed, current_day=day.number, compute_hours=10_000)
    if tool == ToolName.GHOSTSCAN:
        return list(tools_bridge.run_ghostscan_filtered_shared(candidate, state).raw_lines)
    if tool == ToolName.HASHCRACK:
        entries = tools_bridge.generate_hashcrack_day_log(seed, day)
        return list(tools_bridge.run_hashcrack_filtered_shared(entries, candidate, state).raw_lines)
    if tool == ToolName.LOGWATCH:
        entries = tools_bridge.generate_day_log(seed, day)
        return list(tools_bridge.run_logwatch_filtered_shared(entries, candidate, state).raw_lines)
    if tool == ToolName.STEGOTOOL:
        img = tools_bridge.build_stego_image(candidate, day.number)
        return list(tools_bridge.stamp_signature_lines(img, reveal_type=True))
    return []


@app.command("lab")
def lab(
    # noqa: B008 -- typer.Option(...) in the default position is the required
    # Typer idiom: Typer inspects these call objects at import time to build
    # the CLI's flags/help text, so moving the call into the function body
    # (bugbear's usual fix) would break `hackdox lab --help` entirely.
    archetype: list[str] = typer.Option(  # noqa: B008
        [], "--archetype", "-a",
        help="Pin an archetype into a slot. Repeatable, one per slot."),
    violation: list[str] = typer.Option(  # noqa: B008
        [], "--violation", "-v",
        help="Restrict planted violations to these kinds. Repeatable."),
    tool: str = typer.Option(
        None, "--tool", "-t",
        help="Restrict violations to those this tool reveals, and show its "
             "filtered output. One of: ghostscan, hashcrack, logwatch, stegotool."),
    day_number: int = typer.Option(5, "--day", "-d", help="Which day to build."),
    count: int = typer.Option(1, "--count", "-n", help="Candidates to generate."),
    seed: int = typer.Option(
        None, "--seed", "-s",
        help="Fix the RNG seed. Omitted: search for one satisfying the "
             "constraints and report which was used."),
    play: bool = typer.Option(
        False, "--play", help="Launch the TUI on this constrained day instead "
                              "of dumping text."),
) -> None:
    """Generate candidates under explicit constraints, for debugging.

    Examples:

        hackdox lab -a sneaky_bugger -v typosquat_handle --day 5
        hackdox lab -a clumsy_cutie --tool hashcrack -n 3
        hackdox lab -a sneaky_bugger --tool stegotool --play
    """
    # Validate up front — a typo'd archetype should say so, not roll 500 seeds
    # and report "no match", which is what a bare enum lookup deeper in would
    # effectively do.
    try:
        archetypes = [Archetype(a).value for a in archetype] or None
    except ValueError:
        console.print("[red]Unknown archetype.[/] Valid: "
                      + ", ".join(a.value for a in Archetype))
        raise typer.Exit(code=1)
    tool_name: ToolName | None = None
    if tool:
        try:
            tool_name = ToolName(tool)
        except ValueError:
            console.print("[red]Unknown tool.[/] Valid: "
                          + ", ".join(t.value for t in ToolName if t != ToolName.DOSSIER))
            raise typer.Exit(code=1)

    violations = list(violation)
    if tool_name and not violations:
        # --tool alone means "any violation this tool reveals", so the caller
        # doesn't have to remember which kinds belong to which tool.
        violations = [k.value for k, (t, _s) in candidate_gen._SEVERITY_REVEAL.items()
                      if t == tool_name]
    try:
        for v in violations:
            DiscrepancyKind(v)
    except ValueError:
        console.print("[red]Unknown violation kind.[/] Valid: "
                      + ", ".join(k.value for k in DiscrepancyKind))
        raise typer.Exit(code=1)

    archetypes = archetypes or [Archetype.SNEAKY_BUGGER.value]
    if len(archetypes) < count:
        archetypes = (archetypes * count)[:count]

    day = _lab_day(day_number, archetypes, violations, count)

    # Seed search. The constraints are a filter on a random roll, not a
    # guarantee, so with no --seed we look for one that actually satisfies them
    # and print it — the whole point is a reproducible case.
    wanted = {DiscrepancyKind(v) for v in violations}
    used_seed = seed
    if seed is None:
        used_seed = None
        for trial in range(2000):
            cands = [candidate_gen.generate(trial, day, i) for i in range(count)]
            if not wanted or all(
                    {d.kind for d in c.truth.discrepancies} & wanted for c in cands):
                used_seed = trial
                break
        if used_seed is None:
            console.print(
                "[red]No seed in 2000 tries satisfied those constraints.[/]\n"
                "The evidence-tier gate (#31) may be excluding the violation on "
                f"day {day_number} — check its tool's unlock day, or raise --day.")
            raise typer.Exit(code=1)

    if play:
        try:
            from gameengine.ui.tui.app import run as run_tui
        except ImportError as e:
            console.print(f"[red]Could not import Textual UI:[/] {e}")
            raise typer.Exit(code=1)
        console.print(Panel.fit(
            f"Lab shift — day {day_number}, {count} candidate(s), "
            f"seed [cyan]{used_seed}[/]\n"
            f"archetypes: {', '.join(archetypes)}",
            title="HackDox lab", border_style="magenta"))
        run_tui(seed=used_seed, lab_day=day)
        return

    console.print(Panel.fit(
        f"day [cyan]{day_number}[/] · band [cyan]{day.difficulty_band}[/] · "
        f"seed [cyan]{used_seed}[/]  [dim](reproduce with --seed "
        f"{used_seed})[/]\n"
        f"constraints: archetypes={', '.join(archetypes)} · "
        f"violations={', '.join(violations) or 'any'}",
        title="HackDox lab", border_style="magenta"))

    for slot in range(count):
        c = candidate_gen.generate(used_seed, day, slot)
        evaluation = rules_engine.evaluate(c, day)

        body = Table.grid(padding=(0, 2))
        body.add_row("Name / handle:", f"{c.display_name}  [cyan]{c.handle}[/]")
        body.add_row("Email:", c.email)
        body.add_row("Affiliation:", c.claimed_affiliation)
        body.add_row("GitHub:", str(c.dossier.claimed_github))
        body.add_row("Archetype:", f"[yellow]{c.archetype.value}[/]")
        body.add_row("Correct verdict:", f"[yellow]{c.truth.correct_verdict.value}[/]")
        body.add_row("Rules verdict:",
                     "deny" if evaluation.triggered_disqualifying else "admit")
        if c.dossier.handle_squats:
            body.add_row("Handle squats:", f"[magenta]{c.dossier.handle_squats}[/]")
        console.print(Panel(body, title=f"slot {slot}", border_style="cyan"))

        if c.truth.discrepancies:
            dt = Table(show_header=True, box=None)
            dt.add_column("Kind"); dt.add_column("Sev"); dt.add_column("Revealed by")
            for d in c.truth.discrepancies:
                dt.add_row(d.kind.value, d.severity, d.revealed_by.value)
            console.print(dt)
        else:
            console.print("[dim]no discrepancies planted[/]")

        # The pairing that matters: ground truth beside what the tool actually
        # renders. Showing them together is how a violation that is planted but
        # invisible — or worse, contradicted — becomes obvious immediately.
        tools_to_show = ([tool_name] if tool_name else
                         sorted({d.revealed_by for d in c.truth.discrepancies
                                 if d.revealed_by != ToolName.DOSSIER},
                                key=lambda t: t.value))
        for t in tools_to_show:
            out = _lab_tool_output(c, t, day, used_seed)
            console.print(Panel("\n".join(out) or "[dim](no output)[/]",
                                title=f"{t.value} — filtered",
                                border_style="green"))


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
