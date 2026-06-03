#!/usr/bin/env python3
"""
stegotool — LSB Steganography tool for HackDox

Commands:
  hide       Embed a secret message into an image
  reveal     Extract hidden data from an image
  scan       Analyse an image for signs of hidden data
  generate   Create a game challenge (image + narrative + hidden flag)
  scenarios  List available game scenarios

Part of the HackDox cybersecurity game — Layer 3: Steganography
"""

import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

# ── App setup ─────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="stegotool",
    help="[bold cyan]stegotool[/] — LSB steganography tool · HackDox Layer 3",
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _banner():
    console.print(Panel(
        "[bold cyan]  ███████╗████████╗███████╗ ██████╗  ██████╗ ████████╗ ██████╗  ██████╗ ██╗     \n"
        "  ██╔════╝╚══██╔══╝██╔════╝██╔════╝ ██╔═══██╗╚══██╔══╝██╔═══██╗██╔═══██╗██║     \n"
        "  ███████╗   ██║   █████╗  ██║  ███╗██║   ██║   ██║   ██║   ██║██║   ██║██║     \n"
        "  ╚════██║   ██║   ██╔══╝  ██║   ██║██║   ██║   ██║   ██║   ██║██║   ██║██║     \n"
        "  ███████║   ██║   ███████╗╚██████╔╝╚██████╔╝   ██║   ╚██████╔╝╚██████╔╝███████╗\n"
        "  ╚══════╝   ╚═╝   ╚══════╝ ╚═════╝  ╚═════╝    ╚═╝    ╚═════╝  ╚═════╝ ╚══════╝[/bold cyan]\n"
        "[dim]  HackDox · Layer 3: Steganography · LSB Hide/Reveal Engine[/dim]",
        border_style="cyan",
        padding=(0, 1),
    ))


def _err(msg: str):
    console.print(f"[bold red]✗[/] {msg}")


def _ok(msg: str):
    console.print(f"[bold green]✓[/] {msg}")


def _resolve_difficulty(image_path: Path, difficulty: Optional[str], auto: bool) -> str:
    """Resolve difficulty: explicit > auto-detect > default."""
    if difficulty:
        return difficulty
    if auto:
        from modules.lsb import reveal_auto
        _, detected = reveal_auto(image_path)
        return detected or "easy"
    return "easy"


# ── hide command ──────────────────────────────────────────────────────────────

@app.command()
def hide(
    image: Path = typer.Argument(..., help="Cover image to embed data into (.png or .jpg)"),
    message: str = typer.Argument(..., help="Secret message to hide"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output path (default: <input>_stego.png)"),
    difficulty: str = typer.Option("easy", "--difficulty", "-d", help="easy / medium / hard"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Encryption key (required for hard)"),
    save: bool = typer.Option(False, "--save", help="Save operation report to output/"),
):
    """
    [bold cyan]Embed[/] a secret message into an image using LSB steganography.

    \b
    Difficulty levels:
      easy   → plaintext, blue channel only
      medium → base64 encoded, red + blue channels
      hard   → XOR encrypted, all 3 channels (requires --key)
    """
    _banner()

    if not image.exists():
        _err(f"Image not found: {image}")
        raise typer.Exit(1)

    if difficulty not in ("easy", "medium", "hard"):
        _err("Difficulty must be: easy, medium, or hard")
        raise typer.Exit(1)

    if difficulty == "hard" and not key:
        _err("Difficulty 'hard' requires --key <password>")
        raise typer.Exit(1)

    if output is None:
        output = image.parent / f"{image.stem}_stego.png"

    console.print(f"\n[dim]▸ Cover image :[/]  {image}")
    console.print(f"[dim]▸ Difficulty  :[/]  [cyan]{difficulty}[/]")
    console.print(f"[dim]▸ Output      :[/]  {output}")
    console.print()

    try:
        from modules.encoder import encode, DIFFICULTY_LABELS
        from modules.lsb import hide as lsb_hide

        with Progress(
            SpinnerColumn(spinner_name="dots2", style="cyan"),
            TextColumn("[cyan]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            t = progress.add_task("Encoding payload...", total=None)
            payload = encode(message, difficulty, key=key)
            progress.update(t, description="Embedding bits into pixels...")
            time.sleep(0.2)  # dramatic pause
            stats = lsb_hide(image, output, payload, difficulty)
            progress.update(t, description="Saving stego image...")
            time.sleep(0.1)

        # Results table
        table = Table(box=box.SIMPLE_HEAVY, border_style="cyan", show_header=False, padding=(0, 1))
        table.add_column("Key", style="dim cyan")
        table.add_column("Value", style="white")

        table.add_row("Status", "[bold green]✓ EMBEDDED[/]")
        table.add_row("Encoding", DIFFICULTY_LABELS[difficulty])
        table.add_row("Channels", ", ".join(stats["channels_used"]))
        table.add_row("Payload", f"{stats['payload_bytes']:,} bytes")
        table.add_row("Capacity", f"{stats['image_capacity_bytes']:,} bytes ({stats['payload_bytes']/stats['image_capacity_bytes']*100:.1f}% used)")
        table.add_row("Pixels modified", f"{stats['pixels_modified']:,}")
        table.add_row("Output", str(output))

        console.print(Panel(table, title="[bold cyan]HIDE RESULTS[/]", border_style="cyan"))

        if save:
            from modules.report import save_report
            rpath = save_report("hide", {
                "input": str(image),
                "output": str(output),
                "difficulty": difficulty,
                "encoding": DIFFICULTY_LABELS[difficulty],
                **stats,
            })
            _ok(f"Report saved → {rpath}")

    except Exception as e:
        _err(str(e))
        raise typer.Exit(1)


# ── reveal command ────────────────────────────────────────────────────────────

@app.command()
def reveal(
    image: Path = typer.Argument(..., help="Image to extract hidden data from"),
    difficulty: Optional[str] = typer.Option(None, "--difficulty", "-d", help="easy / medium / hard (omit to auto-detect)"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Decryption key (required for hard)"),
    raw: bool = typer.Option(False, "--raw", help="Print raw bytes instead of decoded string"),
    save: bool = typer.Option(False, "--save", help="Save operation report to output/"),
):
    """
    [bold cyan]Extract[/] hidden data from a stego image.

    If [bold]--difficulty[/] is omitted, stegotool tries all modes automatically.
    For [bold]hard[/] difficulty, you must supply [bold]--key[/].
    """
    _banner()

    if not image.exists():
        _err(f"Image not found: {image}")
        raise typer.Exit(1)

    console.print(f"\n[dim]▸ Target :[/] {image}\n")

    try:
        from modules.lsb import reveal as lsb_reveal, reveal_auto
        from modules.encoder import decode

        with Progress(
            SpinnerColumn(spinner_name="dots2", style="cyan"),
            TextColumn("[cyan]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            t = progress.add_task("Scanning pixel planes...", total=None)
            time.sleep(0.3)

            if difficulty:
                payload = lsb_reveal(image, difficulty=difficulty)
                detected_diff = difficulty
            else:
                progress.update(t, description="Auto-detecting difficulty...")
                payload, detected_diff = reveal_auto(image)

            progress.update(t, description="Decoding payload...")
            time.sleep(0.2)

        if payload is None:
            console.print(Panel(
                "[bold yellow]⚠  No hidden data found[/]\n\n"
                "[dim]This image appears clean under the current channel configuration.\n"
                "Try specifying a different [cyan]--difficulty[/dim] level.",
                border_style="yellow",
                title="[yellow]REVEAL RESULT[/]",
            ))
            raise typer.Exit(0)

        # Decode
        if raw:
            decoded = repr(payload)
        else:
            try:
                decoded = decode(payload, detected_diff, key=key)
            except ValueError as e:
                _err(str(e))
                raise typer.Exit(1)

        # Dramatic character-by-character reveal
        console.print(Panel(
            f"[bold green]✓ PAYLOAD EXTRACTED[/]  [dim](difficulty: {detected_diff} · {len(payload)} bytes)[/]",
            border_style="green",
            title="[bold green]HIDDEN DATA FOUND[/]",
        ))
        console.print()
        console.print("[bold white on dark_green] DECRYPTED MESSAGE [/]")
        console.print()

        # Typewriter-style output
        for char in decoded:
            console.print(f"[bright_green]{char}[/]", end="", highlight=False)
            time.sleep(0.004)
        console.print("\n")

        if save:
            from modules.report import save_report
            rpath = save_report("reveal", {
                "image": str(image),
                "difficulty_detected": detected_diff,
                "payload_bytes": len(payload),
                "decoded_message": decoded,
            })
            _ok(f"Report saved → {rpath}")

    except typer.Exit:
        raise
    except Exception as e:
        _err(str(e))
        raise typer.Exit(1)


# ── scan command ──────────────────────────────────────────────────────────────

@app.command()
def scan(
    image: Path = typer.Argument(..., help="Image to analyse for hidden data"),
    save: bool = typer.Option(False, "--save", help="Save scan report to output/"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-channel detail"),
):
    """
    [bold cyan]Analyse[/] an image for statistical signs of LSB steganography.

    Uses chi-square, RS analysis, and LSB histogram anomaly detection.
    Outputs a [bold]suspicion score[/] (0–100) and a verdict.
    """
    _banner()

    if not image.exists():
        _err(f"Image not found: {image}")
        raise typer.Exit(1)

    console.print(f"\n[dim]▸ Target :[/] {image}\n")

    try:
        from modules.steganalysis import scan as do_scan

        with Progress(
            SpinnerColumn(spinner_name="dots2", style="cyan"),
            TextColumn("[cyan]{task.description}"),
            BarColumn(bar_width=30, style="cyan"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            t = progress.add_task("Running chi-square analysis...", total=3)
            time.sleep(0.3)
            progress.advance(t)
            progress.update(t, description="Running RS pair analysis...")
            result = do_scan(image)
            time.sleep(0.2)
            progress.advance(t)
            progress.update(t, description="Computing suspicion score...")
            time.sleep(0.15)
            progress.advance(t)

        # Score bar
        score = result.suspicion_score
        bar_filled = score // 5
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        score_color = result.verdict_color

        console.print(Panel(
            f"[{score_color}]  {result.verdict}[/]  │  Score: [{score_color}]{score}/100[/]  │  [{score_color}]{bar}[/]\n\n"
            f"[dim]{result.width}×{result.height}px · {result.total_pixels:,} pixels · "
            f"max capacity ~{result.capacity_bytes:,} bytes[/]",
            title=f"[bold {score_color}]STEGANALYSIS RESULT[/]",
            border_style=score_color,
        ))

        # Evidence
        if result.evidence:
            console.print(f"\n[bold dim]EVIDENCE[/]\n")
            for i, ev in enumerate(result.evidence, 1):
                console.print(f"  [cyan]{i}.[/] {ev}")
            console.print()

        # Per-channel detail
        if verbose:
            ch_table = Table(
                title="Per-Channel LSB Analysis",
                box=box.SIMPLE_HEAVY,
                border_style="dim cyan",
            )
            ch_table.add_column("Channel", style="bold")
            ch_table.add_column("Zero-LSB %", justify="right")
            ch_table.add_column("Chi-Square", justify="right")
            ch_table.add_column("p-value", justify="right")
            ch_table.add_column("Suspicious")

            for ch in result.channels:
                flag = "[bold red]YES[/]" if ch.suspicious else "[green]no[/]"
                ch_table.add_row(
                    ch.name,
                    f"{ch.lsb_zero_pct:.1f}%",
                    f"{ch.chi_square:.2f}",
                    f"{ch.chi_p_value:.4f}",
                    flag,
                )
            console.print(ch_table)

        if save:
            from modules.report import save_report
            rpath = save_report("scan", {
                "image": str(image),
                "verdict": result.verdict,
                "suspicion_score": result.suspicion_score,
                "evidence": result.evidence,
                "channels": [
                    {
                        "name": c.name,
                        "lsb_zero_pct": c.lsb_zero_pct,
                        "chi_square": c.chi_square,
                        "chi_p_value": c.chi_p_value,
                        "suspicious": c.suspicious,
                    }
                    for c in result.channels
                ],
            })
            _ok(f"Report saved → {rpath}")

    except Exception as e:
        _err(str(e))
        raise typer.Exit(1)


# ── generate command ──────────────────────────────────────────────────────────

@app.command()
def generate(
    scenario: str = typer.Option("data_exfil", "--scenario", "-s", help="Scenario name (see: scenarios)"),
    difficulty: str = typer.Option("easy", "--difficulty", "-d", help="easy / medium / hard"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Encryption key for hard (auto-generated if omitted)"),
    reveal_flag: bool = typer.Option(False, "--reveal", help="Show the hidden answer in the output"),
    output_dir: Path = typer.Option(Path("challenges"), "--output-dir", "-o", help="Directory to save challenge files"),
):
    """
    [bold cyan]Generate[/] a game challenge: a stego image + narrative case file.

    Creates two files in [bold]challenges/[/]:
      - [cyan]<id>.png[/]   — the carrier image with hidden data
      - [cyan]<id>.json[/]  — the case file (narrative + objective)

    Use [bold]--reveal[/] to see the hidden flag (for testing / game master mode).
    """
    _banner()

    try:
        from modules.forge import forge, SCENARIOS, DIFFICULTY_ORDER

        if scenario not in SCENARIOS:
            _err(f"Unknown scenario '{scenario}'. Run [cyan]stegotool scenarios[/] to list available ones.")
            raise typer.Exit(1)

        if difficulty not in DIFFICULTY_ORDER:
            _err("Difficulty must be: easy, medium, or hard")
            raise typer.Exit(1)

        scen_data = SCENARIOS[scenario]

        # Pre-generate display
        diff_colors = {"easy": "green", "medium": "yellow", "hard": "red"}
        diff_labels = {
            "easy": "EASY  — plaintext, single channel",
            "medium": "MEDIUM — base64 encoded, two channels",
            "hard": "HARD   — XOR encrypted, all channels",
        }

        console.print(Panel(
            f"[bold white]{scen_data['icon']}  {scen_data['title']}[/]\n\n"
            f"[dim]{scen_data['brief']}[/]\n\n"
            f"[bold]Objective:[/] {scen_data['objective']}\n"
            f"[{diff_colors[difficulty]}]Difficulty:[/] {diff_labels[difficulty]}",
            title=f"[bold cyan]CASE FILE GENERATING[/]",
            border_style="cyan",
            padding=(1, 2),
        ))
        console.print()

        with Progress(
            SpinnerColumn(spinner_name="dots12", style="cyan"),
            TextColumn("[cyan]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            t = progress.add_task("Generating cover image...", total=None)
            time.sleep(0.2)
            progress.update(t, description="Crafting hidden payload...")
            time.sleep(0.1)
            manifest = forge(
                scenario=scenario,
                difficulty=difficulty,
                reveal_answer=reveal_flag,
                output_dir=output_dir,
                key=key,
            )
            progress.update(t, description="Embedding data into pixels...")
            time.sleep(0.3)
            progress.update(t, description="Saving challenge files...")
            time.sleep(0.1)

        # Results
        table = Table(box=box.SIMPLE_HEAVY, border_style="cyan", show_header=False, padding=(0, 1))
        table.add_column("Key", style="dim cyan")
        table.add_column("Value", style="white")

        table.add_row("Challenge ID", f"[bold]{manifest.challenge_id}[/]")
        table.add_row("Scenario", f"{manifest.icon}  {manifest.title}")
        table.add_row("Difficulty", f"[{diff_colors[difficulty]}]{difficulty.upper()}[/]")
        table.add_row("Encoding", manifest.encoding)
        table.add_row("Channels", ", ".join(manifest.channels_used))
        table.add_row("Lore", f"[dim italic]{manifest.lore}[/]")
        table.add_row("Image", manifest.image_file)
        table.add_row("Key hint", f"[dim]{manifest.key_hint}[/]")

        console.print(Panel(table, title="[bold cyan]CHALLENGE GENERATED[/]", border_style="cyan"))

        if reveal_flag:
            console.print(Panel(
                f"[bold red]⚠  ANSWER (GAME MASTER MODE)[/]\n\n[bright_green]{manifest._answer}[/]",
                border_style="red",
                title="[bold red]HIDDEN FLAG[/]",
            ))

        console.print(f"\n[dim]To solve this challenge:[/]")
        console.print(f"  [cyan]python stegotool.py scan {manifest.image_file}[/]")
        if difficulty == "hard":
            console.print(f"  [cyan]python stegotool.py reveal {manifest.image_file} --difficulty hard --key <key>[/]")
        else:
            console.print(f"  [cyan]python stegotool.py reveal {manifest.image_file}[/]")

    except typer.Exit:
        raise
    except Exception as e:
        _err(str(e))
        import traceback; traceback.print_exc()
        raise typer.Exit(1)


# ── scenarios command ─────────────────────────────────────────────────────────

@app.command()
def scenarios():
    """
    [bold cyan]List[/] all available game scenarios and their narrative briefs.
    """
    _banner()

    from modules.forge import SCENARIOS, DIFFICULTY_ORDER

    console.print("\n[bold cyan]Available Game Scenarios[/]\n")

    for name, data in SCENARIOS.items():
        diff_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1), border_style="dim")
        diff_table.add_column("Diff", style="bold")
        diff_table.add_column("Lore", style="dim italic")
        for d in DIFFICULTY_ORDER:
            color = {"easy": "green", "medium": "yellow", "hard": "red"}[d]
            diff_table.add_row(f"[{color}]{d.upper()}[/]", data["lore"][d])

        console.print(Panel(
            f"[bold white]{data['brief']}[/]\n\n"
            f"[bold]Objective:[/] {data['objective']}\n\n" +
            "[bold dim]Difficulty Lore:[/]",
            title=f"[bold cyan]{data['icon']}  {name}[/]  [dim]→  {data['title']}[/]",
            border_style="cyan",
            padding=(1, 2),
        ))
        console.print(diff_table)
        console.print()

    console.print("[dim]Generate a challenge:[/]")
    console.print(
        "  [cyan]python stegotool.py generate --scenario <name> --difficulty <easy|medium|hard>[/]\n"
    )



# ── verify command ────────────────────────────────────────────────────────────

@app.command()
def verify(
    image: Path = typer.Argument(..., help="Suspect image to analyse and adjudicate"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Decryption key (for hard difficulty)"),
    no_prompt: bool = typer.Option(False, "--no-prompt", help="Skip interactive verdict prompt (batch use)"),
    save: bool = typer.Option(False, "--save", help="Save full verdict report to output/"),
):
    """
    [bold cyan]Verify[/] a suspect image — the full 'Papers Please' game loop.

    Runs steganalysis + payload extraction, then asks you to make a determination:
    [bold bright_red]THREAT[/], [bold bright_green]CLEAN[/], or [bold yellow]INCONCLUSIVE[/].

    \b
    If the image was generated with [cyan]stegotool generate[/], your verdict is
    automatically checked against the case file answer key.
    """
    _banner()

    if not image.exists():
        _err(f"Image not found: {image}")
        raise typer.Exit(1)

    import uuid, json as _json

    case_id = uuid.uuid4().hex[:8].upper()
    console.rule(f"[bold dim]CASE FILE #{case_id}[/]")
    console.print()

    try:
        from modules.steganalysis import scan as do_scan
        from modules.lsb import reveal_auto
        from modules.encoder import decode as decode_payload

        # ── Step 1: Steganalysis ─────────────────────────────────────────────
        with Progress(
            SpinnerColumn(spinner_name="dots2", style="cyan"),
            TextColumn("[cyan]{task.description}"),
            BarColumn(bar_width=24, style="cyan"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            t = progress.add_task("Running chi-square analysis...", total=3)
            time.sleep(0.35)
            scan_result = do_scan(image)
            progress.advance(t)
            progress.update(t, description="Running RS pair analysis...")
            time.sleep(0.25)
            progress.advance(t)
            progress.update(t, description="Scoring anomalies...")
            time.sleep(0.15)
            progress.advance(t)

        # ── Step 2: Payload extraction ───────────────────────────────────────
        with Progress(
            SpinnerColumn(spinner_name="dots2", style="cyan"),
            TextColumn("[cyan]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            t = progress.add_task("Scanning LSB planes (easy -> medium -> hard)...", total=None)
            time.sleep(0.40)
            payload_raw, detected_diff = reveal_auto(image)
            progress.update(t, description="Decoding payload...")
            time.sleep(0.20)

        decoded_message: Optional[str] = None
        decode_error: Optional[str] = None
        if payload_raw is not None:
            try:
                decoded_message = decode_payload(payload_raw, detected_diff, key=key)
            except ValueError as e:
                decode_error = str(e)

        # ── Step 3: Detection panel ──────────────────────────────────────────
        score = scan_result.suspicion_score
        score_color = scan_result.verdict_color
        bar_filled = score // 5
        score_bar = (
            f"[{score_color}]{'X' * bar_filled}[/][dim]{'.' * (20 - bar_filled)}[/]"
            f"  [{score_color}]{score}/100[/]"
        ).replace("X", "█").replace(".", "░")

        det_body = "\n".join([
            f"[bold]Image:[/]      {image.name}",
            f"[bold]Dimensions:[/] {scan_result.width}x{scan_result.height}  .  {scan_result.total_pixels:,} pixels",
            f"[bold]Capacity:[/]   ~{scan_result.capacity_bytes:,} bytes max",
            "",
            f"[bold]Suspicion:[/]  {score_bar}",
            f"[bold]Verdict:[/]    [{score_color}]{scan_result.verdict}[/]",
            "",
            "[bold dim]Evidence:[/]",
        ] + [f"  [dim]{i}.[/] {ev}" for i, ev in enumerate(scan_result.evidence, 1)])

        console.print(Panel(
            det_body,
            title=f"[bold {score_color}]STEGANALYSIS[/]",
            border_style=score_color,
        ))

        # ── Step 4: Payload panel ────────────────────────────────────────────
        if decoded_message is not None:
            msg_lines = "\n".join(
                f"  [bold bright_green]>[/] [bright_green]{line}[/]"
                for line in decoded_message.splitlines()
            )
            console.print(Panel(
                f"[bold]Channel mode:[/] [cyan]{detected_diff}[/]  "
                f"[dim]({len(payload_raw):,} bytes extracted)[/]\n\n"
                f"[bold dim]Decoded payload:[/]\n{msg_lines}",
                title="[bold bright_red]WARNING  HIDDEN PAYLOAD FOUND[/]",
                border_style="bright_red",
            ))
        elif decode_error:
            console.print(Panel(
                f"[yellow]Payload found but could not be decoded.[/]\n\n"
                f"[dim]Error: {decode_error}[/]\n\n"
                "[dim]This may be a [bold]hard[/] difficulty challenge. "
                "Try adding [cyan]--key <password>[/].[/]",
                title="[bold yellow]WARNING  PAYLOAD FOUND - ENCRYPTED[/]",
                border_style="yellow",
            ))
        else:
            console.print(Panel(
                "[bold green]No valid steganographic payload detected.[/]\n\n"
                "[dim]The image appears clean under all difficulty configurations.\n"
                "This may be a genuine clean image, or an unknown channel scheme.[/]",
                title="[bold green]NO PAYLOAD DETECTED[/]",
                border_style="green",
            ))

        # ── Step 5: Player verdict ───────────────────────────────────────────
        player_verdict: Optional[str] = None

        if not no_prompt:
            console.print(Panel(
                "[bold white]Your call, Analyst.[/]\n\n"
                "Based on the steganalysis and extracted data above, "
                "make your determination:\n\n"
                "  [bold bright_red][T][/]  THREAT        -- Hidden data confirms malicious activity\n"
                "  [bold bright_green][C][/]  CLEAN         -- No credible threat, false positive\n"
                "  [bold yellow][I][/]  INCONCLUSIVE  -- Insufficient evidence to determine",
                title="[bold cyan]YOUR VERDICT[/]",
                border_style="cyan",
                padding=(1, 2),
            ))

            valid = {"t": "THREAT", "c": "CLEAN", "i": "INCONCLUSIVE"}
            choice = ""
            while choice not in valid:
                choice = typer.prompt(
                    "  Verdict [T/C/I]", prompt_suffix=" > "
                ).strip().lower()
                if choice not in valid:
                    console.print("  [dim red]Enter T, C, or I.[/]")

            player_verdict = valid[choice]
            vc = {"THREAT": "bright_red", "CLEAN": "bright_green",
                  "INCONCLUSIVE": "yellow"}[player_verdict]
            console.print(f"\n  [bold {vc}]>> VERDICT LOGGED: {player_verdict}[/]\n")

        # ── Step 6: Challenge debrief (if image came from generate) ──────────
        challenge_json = image.parent / (image.stem + ".json")
        challenge_correct: Optional[bool] = None

        if challenge_json.exists():
            with open(challenge_json) as f:
                manifest = _json.load(f)

            if player_verdict is not None:
                expected_threat = (decoded_message is not None) or bool(decode_error)
                player_said_threat = (player_verdict == "THREAT")
                challenge_correct = (player_said_threat == expected_threat)

                result_color = "bright_green" if challenge_correct else "bright_red"
                result_label = ("CORRECT DETERMINATION"
                                if challenge_correct else "INCORRECT DETERMINATION")
                result_icon = "OK" if challenge_correct else "FAIL"

                debrief_lines = [
                    f"[bold {result_color}]  [{result_icon}]  {result_label}[/]",
                    "",
                    f"  [dim]Case ID  :[/]  {manifest.get('challenge_id', '?')}",
                    f"  [dim]Scenario :[/]  {manifest.get('icon','')} "
                    f"{manifest.get('title','')}",
                    f"  [dim]Difficulty:[/] {manifest.get('difficulty','').upper()}",
                    f"  [dim]Lore     :[/]  "
                    f"[italic]{manifest.get('lore','')}[/italic]",
                ]
                if "ANSWER" in manifest:
                    debrief_lines += [
                        "",
                        f"  [dim]Answer   :[/]  "
                        f"[bright_green]{manifest['ANSWER']}[/]",
                    ]

                console.rule("[bold dim]CASE DEBRIEF[/]")
                console.print(Panel(
                    "\n".join(debrief_lines),
                    border_style=result_color,
                    padding=(0, 1),
                ))

        # ── Step 7: Save report ──────────────────────────────────────────────
        if save:
            from modules.report import save_report
            rpath = save_report("verify", {
                "case_id": case_id,
                "image": str(image),
                "steganalysis": {
                    "suspicion_score": scan_result.suspicion_score,
                    "verdict": scan_result.verdict,
                    "evidence": scan_result.evidence,
                },
                "payload_found": decoded_message is not None,
                "payload_difficulty": detected_diff if payload_raw else None,
                "decoded_message": decoded_message,
                "player_verdict": player_verdict,
                "challenge_correct": challenge_correct,
            })
            _ok(f"Report saved -> {rpath}")

    except typer.Exit:
        raise
    except Exception as e:
        _err(str(e))
        import traceback; traceback.print_exc()
        raise typer.Exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
