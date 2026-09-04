"""CreditRevealScreen."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from gameengine.core.models import Candidate, Verdict
from gameengine.ui.tui import rules_content


class CreditRevealScreen(ModalScreen):
    """HackDox Credit reveal (issue #25) — a read-only, spent-credit debug
    window showing the candidate's ground truth: the correct verdict and the
    planted violation KINDS. Deliberately excludes the evidence trail
    (descriptions / which tool reveals what) per the issue AC. Distinct
    violet styling marks it as a paid debug view, not normal tool output."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss_reveal", "Close"),
        Binding("enter",  "dismiss_reveal", "Close"),
    ]

    def __init__(self, candidate: Candidate, credits_left: int) -> None:
        super().__init__()
        self._candidate    = candidate
        self._credits_left = credits_left

    def compose(self) -> ComposeResult:
        c, t = self._candidate, self._candidate.truth
        sev  = {"minor": "#ffd93d", "major": "#ff8c42", "critical": "#ff5470"}
        vcol = "#00ff9f" if t.correct_verdict == Verdict.ADMIT else "#ff5470"
        rows = [
            "[#c084fc][b]⬢ HACKDOX CREDIT SPENT — GROUND TRUTH REVEAL[/][/]",
            "[dim]read-only · no verdict submitted · evidence trail not included[/]",
            "",
            f"[#6b7785]Candidate[/]        [b]{c.display_name}[/]  ({c.handle})",
            f"[#6b7785]Correct verdict[/]  [{vcol}][b]{t.correct_verdict.value.upper()}[/][/]",
            "",
            f"[#6b7785]Planted violations ({len(t.discrepancies)}):[/]",
        ]
        if t.discrepancies:
            for d in t.discrepancies:
                col = sev.get(d.severity, "#c8d4e1")
                # #56: same shared label as the board and the dev window.
                rows.append(f"  [{col}]▲ {rules_content.label_for(d.kind)}[/]"
                            f"  [dim]({d.severity})[/]")
        else:
            rows.append("  [dim](clean — no violations planted)[/]")
        rows += [
            "",
            f"[#c084fc]credits remaining: {self._credits_left}[/]",
            "",
            "[dim]Esc / Enter to close[/]",
        ]
        with Container(id="credit-modal"):
            yield Static("\n".join(rows))

    def action_dismiss_reveal(self) -> None:
        self.dismiss()
