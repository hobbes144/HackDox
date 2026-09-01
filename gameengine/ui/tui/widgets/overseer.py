"""OverseerPanel."""

from __future__ import annotations

from textual.widgets import Static
from gameengine.core.models import CandidateResult, Verdict


class OverseerPanel(Static):
    """Overseer dialogue + running stats."""

    can_focus = False

    def __init__(self, intro_text: str) -> None:
        super().__init__(id="overseer-side")
        self.border_title = " Overseer "
        self._intro      = intro_text
        self._admits     = 0
        self._denies     = 0
        self._correct    = 0
        self._total      = 0
        self._compute_spent = 0

    def record_result(self, result: CandidateResult, compute_before: int,
                      compute_after: int) -> None:
        if result.player_verdict == Verdict.ADMIT:
            self._admits += 1
        else:
            self._denies += 1
        if result.correct:
            self._correct += 1
        self._total += 1
        # Issue #27: verdicts never grant ⏱, so spend is a simple difference.
        self._compute_spent += max(0, compute_before - compute_after)
        self.refresh()

    def reset(self) -> None:
        self._admits = self._denies = self._correct = self._total = 0
        self._compute_spent = 0
        self.refresh()

    def render(self) -> str:
        accuracy = (
            f"{round(100 * self._correct / self._total)}%"
            if self._total else "—"
        )
        lines = [
            f"[italic #c8d4e1]{self._intro}[/]",
            "",
            f"[#6b7785]Admits[/]    [#7dd3c0]{self._admits}[/]   "
            f"[#6b7785]Denies[/] [#7dd3c0]{self._denies}[/]",
            f"[#6b7785]Accuracy[/]  [#7dd3c0]{accuracy}[/]",
            f"[#6b7785]⏱ spent[/]   [#ffb454]{self._compute_spent}[/]",
        ]
        return "\n".join(lines)
