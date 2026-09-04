"""DossierPanel, CondensedDossier."""

from __future__ import annotations

from textual.widgets import Static

from gameengine.core.models import Candidate
from gameengine.ui.tui.shared import (
    _hl_affil,
    _hl_email,
    _password_markup,
)


class DossierPanel(Static):
    """Full candidate identity packet — candidate page only."""

    can_focus = True

    def __init__(self) -> None:
        super().__init__(id="dossier", classes="panel")
        self.border_title = " Dossier "
        self._candidate: Candidate | None = None
        self.upgrades: set = set()   # auto-highlight upgrades (issue #23)
        self.cracked_password: str | None = None   # issue #29 password state

    def set_candidate(self, candidate: Candidate) -> None:
        self._candidate = candidate
        self.refresh()

    def render(self) -> str:
        if self._candidate is None:
            return "[dim]No candidate loaded.[/]"
        c, d = self._candidate, self._candidate.dossier
        gh   = d.claimed_github       or "[dim](none)[/]"
        ip   = d.claimed_ip           or "[dim](none)[/]"
        img  = d.submitted_image_path or "[dim](none)[/]"
        pw_head, pw_state = _password_markup(d, self.cracked_password,
                                             upgrades=self.upgrades,
                                             prefix_len=20)
        rows = [
            "[#3d6478]-- identity ------------------------------------------[/]",
            f"  [#6b7785]Name[/]         [b]{c.display_name}[/]",
            f"  [#6b7785]Handle[/]       {c.handle}",
            f"  [#6b7785]Email[/]        {_hl_email(c.email, self.upgrades)}",
            f"  [#6b7785]Affiliation[/]  {_hl_affil(c.claimed_affiliation, self.upgrades)}",
            f"  [#6b7785]GitHub[/]       {gh}",
            "",
            "[#3d6478]-- submitted artifacts --------------------------------[/]",
            f"  [#6b7785]IP[/]           {ip}",
            "               [dim]breadcrumb — corroborate against Logwatch login IPs before denying[/]",
            f"  [#6b7785]Password[/]     {pw_head}",
            *( [f"               {pw_state}"] if pw_state else [] ),
            f"  [#6b7785]Image[/]        {img}",
            "",
            "[#3d6478]-- stated purpose ------------------------------------[/]",
            f"  [italic]{c.claimed_purpose}[/]",
            "",
            f"[dim]{d.notes}[/]",
        ]
        return "\n".join(rows)


class CondensedDossier(Static):
    """Slim identity strip for tool-page sidebars."""

    can_focus = False

    def __init__(self, widget_id: str) -> None:
        super().__init__(id=widget_id, classes="panel condensed-dossier")
        self.border_title = " Dossier "
        self._candidate: Candidate | None = None
        self.upgrades: set = set()   # auto-highlight upgrades (issue #23)
        self.cracked_password: str | None = None   # issue #29 password state

    def set_candidate(self, candidate: Candidate) -> None:
        self._candidate = candidate
        self.refresh()

    def render(self) -> str:
        if self._candidate is None:
            return "[dim]—[/]"
        c  = self._candidate
        d   = c.dossier
        gh  = d.claimed_github or "[dim](none)[/]"
        ip  = d.claimed_ip     or "[dim](none)[/]"
        img = d.submitted_image_path or "[dim](none)[/]"
        pw_head, pw_state = _password_markup(d, self.cracked_password,
                                             upgrades=self.upgrades,
                                             prefix_len=10)
        return "\n".join([
            f"[#6b7785]Name[/]   [b]{c.display_name}[/]",
            f"[#6b7785]Handle[/] {c.handle}",
            f"[#6b7785]Email[/]  {_hl_email(c.email, self.upgrades)}",
            f"[#6b7785]Org[/]    {_hl_affil(c.claimed_affiliation, self.upgrades)}",
            f"[#6b7785]GitHub[/] {gh}",
            "[#3d6478]-- submitted --[/]",
            f"[#6b7785]IP[/]     {ip}",
            f"[#6b7785]Passwd[/] {pw_head}",
            *( [f"       {pw_state}"] if pw_state else [] ),
            f"[#6b7785]Image[/]  {img}",
            "[#3d6478]-- purpose --[/]",
            f"[italic]{c.claimed_purpose}[/]",
        ])
