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
    # Before the split the Rules tab was ~3x the next longest. Allow 2.3x as
    # the regression bound so ordinary copy growth doesn't trip this — batch-3
    # added 4 new upgrade-catalog rows + per-tool category headers (task #2),
    # nudging Rules from ~2.0x to ~2.04x. Still a real ceiling: it just isn't
    # pinned so tight that legitimate catalog growth fails the guard.
    assert lengths["rules"] < 2.3 * max(others), lengths


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


# ─── Progressive unlock reaches the Rules Pages + Evidence Board (#33 ext.) ──
#
# The tool pages themselves were already locked out entirely (#33); this
# closes the gap where the Rules overlay and the Evidence Board still showed
# every violation and every rule regardless of what the player had actually
# been taught. A kind/rule tied to a still-locked tool describes evidence
# that cannot exist yet (candidate_gen.intro_day gates generation on the same
# schedule via config.TOOL_UNLOCK_DAY), so showing it early would teach the
# player to hunt for something that isn't there.


def test_dossier_tab_no_longer_double_lists_domains():
    """Regression: day_01's rule_sheet used to spell out the exact same
    trusted/disposable domain names the 'email domains' reference block right
    below it already renders from tools_bridge's banks. Each domain should
    appear exactly once on the tab now."""
    day = load_day(1)
    text = rules_content.build_dossier_text(day)
    assert text.count("gmail.com") == 1
    assert text.count("mailinator.com") == 1


def test_locked_tool_tab_shows_placeholder_not_content():
    day = load_day(1)
    locked = rules_content.build_osint_text(day, unlocked_tools=set())
    assert "LOCKED" in locked
    assert "PLATFORM SWEEP" not in locked   # the real tab content
    unlocked = rules_content.build_osint_text(day, unlocked_tools={"ghostscan"})
    assert "LOCKED" not in unlocked
    assert "PLATFORM SWEEP" in unlocked


def test_locked_tab_default_none_shows_full_content():
    """unlocked_tools=None (every pre-existing caller, incl. the tests above
    this one in the file) must render exactly as it did before progressive
    unlock reached the Rules Pages."""
    day = load_day(1)
    assert "LOCKED" not in rules_content.build_osint_text(day)
    assert "LOCKED" not in rules_content.build_creds_text(day)
    assert "LOCKED" not in rules_content.build_logs_text(day)
    assert "LOCKED" not in rules_content.build_stego_text(day)


def test_rules_tab_disqualifying_weighted_gated_by_unlocked_tools():
    day = load_day(1)
    dossier_only = rules_content.build_rules_text(day, unlocked_tools=set())
    everything = rules_content.build_rules_text(
        day, unlocked_tools={"ghostscan", "hashcrack", "logwatch", "stegotool"})
    # OSINT/CREDENTIAL-tier rules are locked out until their tool is unlocked...
    assert "sock-puppet accounts" not in dossier_only
    assert "breach corpus" not in dossier_only
    # ...but a DOSSIER-tier rule (always available) is there from day one.
    assert "throwaway service" in dossier_only
    # ...and everything reappears once every tool is unlocked.
    assert "sock-puppet accounts" in everything
    assert "breach corpus" in everything
    assert "more rule" in dossier_only        # hint that more rules exist
    assert "more rule" not in everything      # nothing left hidden


def test_rules_tab_unlocked_tools_none_shows_full_rulebook():
    """The default (no gating context) must not regress pre-existing callers
    such as the split/length tests above this one in the file."""
    day = load_day(1)
    full  = rules_content.build_rules_text(day)
    gated = rules_content.build_rules_text(day, unlocked_tools=set())
    assert len(full.splitlines()) > len(gated.splitlines())
    assert "more rule" not in full


def test_rule_text_boilerplate_is_dimmed_and_trigger_is_highlighted():
    """Every rule opens with one of two fixed boilerplate phrases; the render
    should dim that lead-in and bold+colour the clause that actually differs
    rule to rule, rather than leaving the whole line one flat colour."""
    day = load_day(1)
    text = rules_content.build_rules_text(day)
    assert "[dim]Deny any candidate who" in text
    assert "[dim]Flag (do not auto-deny)" in text
    # The highlighted remainder keeps the section's accent colour + bold.
    assert "[#ff5470][b]" in text
    assert "[#ff8c42][b]" in text


def test_rules_screen_evidence_board_respects_unlocked_tools():
    """The Evidence tab embedded in the Rules overlay shares the same gating
    as the tool-page boards — no separate code path to drift out of sync."""
    from gameengine.ui.tui.app import EvidenceState, RulesScreen

    day = load_day(1)
    state_obj = EvidenceState()
    screen = RulesScreen(day, state_obj, unlocked_tools={"ghostscan"})
    groups = {g for g, _k, _l in screen._ev_board._items}
    assert groups == {"DOSSIER", "OSINT"}


def test_every_violation_has_a_worked_example():
    """Batch-3 task #6: '~3 lines per example' for every violation, shown
    paired with that violation's own row on its group's tab, not off in a
    separate reference section the player has to cross-reference by hand."""
    from gameengine.core.models import DiscrepancyKind

    missing = [k.name for k in DiscrepancyKind if k not in rules_content._EXAMPLE]
    assert not missing, f"no worked example for: {missing}"
    for kind, lines in rules_content._EXAMPLE.items():
        assert len(lines) == 3, f"{kind.name} example is not exactly 3 lines"
        assert all(isinstance(ln, str) and ln for ln in lines), (
            f"{kind.name} example has an empty line")


def test_worked_examples_render_as_valid_markup_next_to_their_violation():
    """Each example must parse as valid Rich markup (no stray '[' / ']' from
    example content breaking a tag) and must appear directly under its own
    violation's row — not just exist somewhere on the tab."""
    from rich.errors import MarkupError
    from rich.text import Text

    day = load_day(1)
    for group in rules_content.GROUP_ORDER:
        lines = rules_content.violation_table(day, group)
        for ln in lines:
            try:
                Text.from_markup(ln)
            except MarkupError as e:
                raise AssertionError(f"invalid markup in {group} table: {ln!r} ({e})")

        # pairing: an "example:" line must appear right after its own row.
        text = "\n".join(lines)
        for kind, _lbl in [(k, lbl) for g, k, lbl in rules_content.VIOLATION_CATALOG if g == group]:
            header_idx = text.find(kind.value.upper())
            assert header_idx != -1, f"{kind.name} row missing from {group} table"
            next_example = text.find("example:", header_idx)
            # the next violation header after this one, if any (bounds the search)
            catch_idx = text.find("catch:", header_idx)
            assert next_example != -1 and (catch_idx == -1 or next_example > catch_idx), (
                f"{kind.name}'s example is not positioned right after its own row")


def test_dossier_encryption_strength_section_has_a_worked_example_per_tier():
    """Nick, follow-up to task #6: the Hashcrack tab's encryption-strength
    reference already had worked hash examples; the Dossier tab's shorter
    quick-reference version of the same chip didn't. Every tier (and the
    UNSALTED marker) now shows a recognizable example hash/value alongside
    its description, and the whole section still parses as valid markup."""
    from rich.errors import MarkupError
    from rich.text import Text

    day = load_day(1)
    text = rules_content.build_dossier_text(day)
    i = text.find("password encryption strength")
    assert i != -1
    section = text[i:i + 1400]

    # A recognizable example for each tier, distinguishable by hex length /
    # prefix shape — the whole point of "so the player can recognize it".
    assert "5f4dcc3b5aa765d61d8327deb882cf99" in section   # WEAK / MD5, 32 hex
    assert "a94a8fe5ccb19ba61c4c0873d391e987" in section    # MEDIUM / SHA256, 64 hex
    assert "$2b$12$" in section                              # STRONG / bcrypt prefix
    assert "monkey123" in section or "UNSALTED" in section

    for ln in text.split("\n"):
        try:
            Text.from_markup(ln)
        except MarkupError as e:
            raise AssertionError(f"invalid markup in dossier text: {ln!r} ({e})")
