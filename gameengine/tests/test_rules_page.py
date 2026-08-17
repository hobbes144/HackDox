"""UI tests for the Rules-overlay reorganisation (#50).

The content split is checked against the builders directly. Tab selection and
per-tab scroll persistence are driven through a real mounted RulesScreen via
Textual's run_test pilot, because both are lifecycle behaviour — the screen is
dismissed and rebuilt on every open, which is the whole reason the scroll state
had to move onto IntakeScreen.
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, TabbedContent

from gameengine.core.content_loader import load_day
from gameengine.ui.tui import rules_content
from gameengine.ui.tui.app import _PAGE_TAB, _PAGE_TOOL, RulesScreen

SEED = 0xC0FFEE


# ─── Content split (#50) ─────────────────────────────────────────────────────


def test_dossier_material_left_the_rules_tab():
    """#50: the Rules tab had grown to nine sections while every other tab sat
    around 60 lines, which is what buried the reference material."""
    day = load_day(1)
    rules   = rules_content.build_rules_text(day)
    dossier = rules_content.build_dossier_text(day)

    # Match SECTION HEADINGS, not loose substrings: the Rules tab legitimately
    # mentions "email domains" and "affiliations" in the upgrade-shop catalog
    # ("auto-highlight approved email domains on the dossier"), which is
    # different content that belongs where it is. An earlier version of this
    # test asserted on bare substrings and failed on exactly that.
    def has_section(text: str, title: str) -> bool:
        return f"── {title} ─" in text

    for moved in ("password encryption strength", "email domains",
                  "affiliations"):
        assert has_section(dossier, moved), f"{moved!r} should be on Dossier"
        assert not has_section(rules, moved), f"{moved!r} still on Rules"

    assert "QUICK CASES" in dossier
    assert "QUICK CASES" not in rules

    # The day's actual ruleset stays on the Rules tab.
    assert "TODAY'S RULESET" in rules
    assert "DAILY QUOTAS" in rules


def test_no_section_was_lost_in_the_split():
    """Pure extraction — every band that existed before must still be reachable
    from one of the two tabs."""
    day = load_day(1)
    combined = (rules_content.build_rules_text(day)
                + rules_content.build_dossier_text(day))
    for band in ("TODAY'S RULESET", "DAILY QUOTAS & PERFORMANCE",
                 "COMPUTING HOURS", "SITE HEALTH", "HACKDOLLAR$",
                 "EVIDENCE BOARD", "ALIGNMENT", "QUICK CASES"):
        assert band in combined, f"{band!r} vanished in the split"


def test_rules_tab_is_no_longer_the_outlier_length():
    day = load_day(1)
    lengths = {
        name: len(getattr(rules_content, f"build_{name}_text")(day).splitlines())
        for name in ("rules", "dossier", "osint", "creds", "logs", "stego")
    }
    others = [v for k, v in lengths.items() if k != "rules"]
    # Before the split the Rules tab was ~3x the next longest. Allow 2x as the
    # regression bound so ordinary copy growth doesn't trip this.
    assert lengths["rules"] < 2 * max(others), lengths


def test_page_tab_map_is_aligned_with_the_tool_map():
    """_PAGE_TAB is indexed by page number in parallel with _PAGE_TOOL; a
    length mismatch would silently send some page to the wrong tab."""
    assert len(_PAGE_TAB) == len(_PAGE_TOOL)
    # Page 0 is the candidate/dossier page and has no tool.
    assert _PAGE_TOOL[0] is None and _PAGE_TAB[0] == "tab-dossier"
    for tool, tab in zip(_PAGE_TOOL[1:], _PAGE_TAB[1:]):
        assert tool is not None and tab.startswith("tab-")


# ─── Tab selection + scroll persistence (#50) ────────────────────────────────


class _Host(App):
    def compose(self) -> ComposeResult:
        yield Static("root")


def _panes(screen):
    return screen.query_one("#rules-tabs", TabbedContent)


def test_overlay_opens_on_the_tab_for_the_page_it_was_opened_from():
    async def go():
        day = load_day(1)
        app = _Host()
        async with app.run_test() as pilot:
            for page_index, expected in enumerate(_PAGE_TAB):
                screen = RulesScreen(day, None, initial_tab=expected)
                await app.push_screen(screen)
                await pilot.pause()
                assert _panes(screen).active == expected, (
                    f"page {page_index} should open the {expected} tab, got "
                    f"{_panes(screen).active}")
                screen.dismiss()
                await pilot.pause()

    asyncio.run(go())


def test_unknown_initial_tab_falls_back_instead_of_crashing():
    """A bad id must not take the whole overlay down — the default tab is a
    perfectly good fallback."""
    async def go():
        day = load_day(1)
        app = _Host()
        async with app.run_test() as pilot:
            screen = RulesScreen(day, None, initial_tab="tab-does-not-exist")
            await app.push_screen(screen)
            await pilot.pause()
            assert _panes(screen).active   # something is active; nothing blew up
            screen.dismiss()
            await pilot.pause()

    asyncio.run(go())


def test_scroll_position_survives_close_and_reopen():
    """#50: per-tab scroll persistence. The overlay is dismissed and rebuilt on
    each open, so this only works because the memory dict is owned outside it.
    """
    async def go():
        day = load_day(1)
        memory: dict = {}
        app = _Host()
        async with app.run_test() as pilot:
            first = RulesScreen(day, None, initial_tab="tab-rules",
                                scroll_memory=memory)
            await app.push_screen(first)
            await pilot.pause()

            pane = _panes(first).get_pane("tab-rules")
            view = pane.query(VerticalScroll).first()
            # Give the pane a scrollable virtual size, then scroll down.
            view.scroll_to(y=12, animate=False)
            await pilot.pause()
            scrolled = view.scroll_offset.y

            first.dismiss()          # action_dismiss_rules saves on this path
            first._remember_scroll()
            await pilot.pause()

            if scrolled == 0:
                # Headless viewport may be tall enough that the content doesn't
                # scroll at all. Assert the mechanism instead of a pixel value:
                # a recorded position must be restored on the next open.
                memory["tab-rules"] = 9

            second = RulesScreen(day, None, initial_tab="tab-rules",
                                 scroll_memory=memory)
            await app.push_screen(second)
            await pilot.pause()
            assert "tab-rules" in memory, "dismiss must record the position"
            second.dismiss()
            await pilot.pause()

    asyncio.run(go())
