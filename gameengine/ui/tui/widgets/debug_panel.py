"""DebugPanel."""

from __future__ import annotations

from textual.widgets import Static

from gameengine.core.models import Candidate, Verdict
from gameengine.ui.tui import rules_content


class DebugPanel(Static):
    """DEV MODE — ground-truth answer key. Toggle with ` (backtick)."""

    can_focus = True

    def __init__(self) -> None:
        super().__init__(id="debug-panel", classes="panel")
        self.border_title = " ⚠  DEV — Ground Truth "
        self._candidate: Candidate | None = None
        self.display = False

    def set_candidate(self, candidate: Candidate) -> None:
        self._candidate = candidate
        self.refresh()

    def render(self) -> str:
        if self._candidate is None:
            return "[dim]No candidate.[/]"
        c  = self._candidate
        t  = c.truth
        sev = {"minor": "#ffd93d", "major": "#ff8c42", "critical": "#ff5470"}
        d_lines = [
            # #56: the shared label, not the raw enum. This window used to print
            # `affiliation_mismatch` while the evidence board printed "Faked
            # elite affiliation" for the same violation, which made dev
            # observations impossible to line up against what the player sees.
            f"  [{sev.get(d.severity,'#c8d4e1')}]●[/] [b]{rules_content.label_for(d.kind)}[/]"
            f" via [#7dd3c0]{d.revealed_by.value}[/] — {d.description}"
            for d in t.discrepancies
        ] or ["  [dim](none)[/]"]
        vcol = "#00ff9f" if t.correct_verdict == Verdict.ADMIT else "#ff5470"
        return (
            f"[#ffb454]Archetype:[/]       [b]{c.archetype.value}[/]\n"
            f"[#ffb454]Correct verdict:[/] [{vcol}][b]{t.correct_verdict.value.upper()}[/][/]\n"
            f"[#ffb454]Moral modifier:[/]  {t.moral_modifier:+d}\n"
            f"\n[#ffb454]Discrepancies ({len(t.discrepancies)}):[/]\n"
            + "\n".join(d_lines)
        )
