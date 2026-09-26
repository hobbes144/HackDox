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

    # "password encryption strength" became "the password field" when the
    # dossier stopped labelling encryption tiers — establishing the algorithm
    # is the cipher block's job now, and the tier table lives on the
    # CREDENTIALS tab. The section itself still belongs on Dossier: it
    # describes what the dossier actually shows.
    for moved in ("the password field", "email domains",
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
    # Keyword highlighting puts markup INSIDE phrases, so compare plain text.
    from rich.text import Text
    dossier_only = Text.from_markup(dossier_only).plain
    everything = Text.from_markup(everything).plain
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


def test_rule_text_boilerplate_is_dropped_and_only_keywords_are_highlighted():
    """2026-09-25 (Nick): the whole trigger clause used to be bold + coloured,
    which made the list a wall of colour. The "Deny any candidate whose" /
    "Flag (do not auto-deny)" lead-in is gone (the ✗/△ marker says it) and
    only each rule's KEYWORDS carry the accent."""
    day = load_day(1)
    text = rules_content.build_rules_text(day)
    assert "Deny any candidate" not in text
    assert "Flag (do not auto-deny)" not in text
    assert "[b #ff5470]brute-force[/]" in text          # a DENY keyword
    assert "[b #ff8c42]MD5[/]" in text                  # a FLAG keyword
    # The rest of the clause is NOT bold.
    assert "[b #ff5470]Submitted logs" not in text


def test_every_rule_line_has_a_highlighted_keyword():
    """Every kind any day's ruleset uses has a fixed RULE_TEXT line, and that
    line contains at least one of its RULE_KEYWORDS — otherwise it renders
    with nothing to scan for."""
    import re as _re
    for n in range(1, 21):
        for r in load_day(n).rules:
            kind = rules_content._rule_kind(r)
            if kind is None:
                continue
            line = rules_content.RULE_TEXT.get(kind)
            assert line, f"{kind.name} has no RULE_TEXT line"
            kws = rules_content.RULE_KEYWORDS.get(kind, ())
            assert any(_re.search(_re.escape(k), line, _re.IGNORECASE)
                       for k in kws), f"{kind.name}: no keyword in {line!r}"


def _rule_rows(day_n):
    """{kind: (page heading, index within page, marker)} from the Rules tab."""
    from rich.text import Text
    text = Text.from_markup(rules_content.build_rules_text(load_day(day_n))).plain
    # First line of each rendered rule -> kind (every RULE_TEXT line is
    # distinct in its first five words).
    by_head = {tuple(t.split()[:5]): k for k, t in rules_content.RULE_TEXT.items()}
    assert len(by_head) == len(rules_content.RULE_TEXT)
    rows, page, idx = {}, None, 0
    for ln in text.split("\n"):
        if ln.startswith("▎ ") and ln.endswith("PAGE"):
            page, idx = ln[2:], 0
            continue
        if page and ln.startswith(("  ✗  ", "  △  ")):
            rows[by_head[tuple(ln[5:].split()[:5])]] = (page, idx, ln[2])
            idx += 1
    return rows


def test_rule_position_and_wording_are_static_colour_follows_severity():
    """2026-09-25 (Nick): the Evidence Board model — static position, dynamic
    colour. A rule re-tiered between days keeps its page and its slot and its
    wording; only the ✗/△ marker (and keyword colour) changes. Day 8 → 12
    re-tiers several rules, so the comparison is not vacuous."""
    early, late = _rule_rows(8), _rule_rows(12)
    common = set(early) & set(late)
    assert len(common) > 15
    moved = [k for k in common if early[k][:2] != late[k][:2]]
    assert not moved, moved
    retiered = [k for k in common if early[k][2] != late[k][2]]
    assert retiered, "expected at least one rule to change tier between day 8 and 12"
    # The marker is today's severity, never the authored wording's.
    day12 = {rules_content._rule_kind(r): r.severity for r in load_day(12).rules}
    for k, (_p, _i, mark) in late.items():
        assert (mark == "✗") == (day12[k] == "disqualifying"), k


def test_rules_tab_never_contradicts_its_marker():
    """The authored rule texts carried their day's stance ("— not proof of
    malice", "until then it is a flag, not a deny"), which read wrong once a
    later day re-tiered the rule. None of that wording reaches the Rules tab."""
    from rich.text import Text
    for n in range(1, 21):
        text = Text.from_markup(rules_content.build_rules_text(load_day(n))).plain
        ruleset = text.split("DAILY QUOTAS")[0]
        rows = [ln for ln in ruleset.split("\n") if ln.startswith(("  ✗  ", "  △  "))]
        for ln in rows:
            for bad in ("not a deny", "don't deny", "not proof", "do not auto-deny",
                        "Deny any candidate", "automatic deny"):
                assert bad not in ln, (n, ln)


def test_rules_are_grouped_by_the_page_that_reveals_them():
    from rich.text import Text
    day = load_day(1)
    text = Text.from_markup(rules_content.build_rules_text(day)).plain
    heads = ["DOSSIER PAGE", "GHOSTSCAN PAGE", "HASHCRACK PAGE",
             "LOGWATCH PAGE", "STEGOTOOL PAGE"]
    pos = [text.index("▎ " + h) for h in heads]
    assert pos == sorted(pos), "pages out of tool-unlock order"
    # A logwatch rule sits under LOGWATCH, not under another page.
    i = text.index("brute-force")
    assert pos[3] < i < pos[4]
    # Locked tools contribute no heading at all.
    locked = Text.from_markup(
        rules_content.build_rules_text(day, unlocked_tools=set())).plain
    assert "DOSSIER PAGE" in locked and "LOGWATCH PAGE" not in locked


def test_rules_lines_are_valid_markup_and_wrap_under_their_own_text():
    from rich.text import Text
    for n in (1, 8, 12, 20):
        for ln in rules_content.build_rules_text(load_day(n)).split("\n"):
            Text.from_markup(ln)                           # raises if malformed
    text = rules_content.build_rules_text(load_day(1))
    for ln in text.split("\n"):
        plain = Text.from_markup(ln).plain
        if plain.startswith(("  ✗  ", "  △  ")):
            assert len(plain) <= rules_content._W, plain


def test_reference_lists_are_side_by_side_columns():
    """2026-09-25 (Nick): trusted / questionable / disposable side by side,
    one entry per line."""
    from rich.text import Text
    from gameengine.core import candidate_gen
    text = Text.from_markup(rules_content.build_dossier_text(load_day(1))).plain
    rows = text.split("\n")
    head = next(r for r in rows if "✓ TRUSTED" in r and "? QUESTIONABLE" in r
                and "✗ DISPOSABLE" in r)
    assert head is not None
    head_aff = next(r for r in rows if "✓ TRUSTED" in r and "✗ THREAT" in r)
    assert head_aff is not None
    # Every bank entry appears on its own row (first line of its cell).
    for d in (*candidate_gen.DOMAINS_TRUSTED, *candidate_gen.DOMAINS_PRIVACY,
              *candidate_gen.DOMAINS_DISPOSABLE):
        assert any(f"· {d}" in r for r in rows), d
    for org in (*candidate_gen.AFFILIATIONS_THIN,):
        first = org.split()[0]
        assert any(f"· {first}" in r for r in rows), org
    # And the old " · "-joined runs are gone.
    assert "gmail.com · " not in text


def test_dossier_tab_has_one_violation_table():
    text = rules_content.build_dossier_text(load_day(6))
    assert text.count("▎ VIOLATIONS — DOSSIER") == 1


def test_rules_screen_evidence_board_respects_unlocked_tools():
    """The Evidence tab embedded in the Rules overlay shares the same gating
    as the tool-page boards — no separate code path to drift out of sync."""
    from gameengine.ui.tui.app import EvidenceState, RulesScreen

    # Day 6, not Day 1 — see test_unlock_ui.test_evidence_boards_are_gated_by_
    # unlocked_tools for why: the board now also gates on whether today's own
    # content (allowed_violations, archetype_mix) could plant a kind, and
    # Day 1's own whitelist doesn't teach any OSINT kind yet. Day 6 is the
    # first day with no whitelist restriction, so it isolates pure
    # tool-gating the way this test means to.
    day = load_day(6)
    state_obj = EvidenceState()
    screen = RulesScreen(day, state_obj, unlocked_tools={"ghostscan"})
    groups = {g for g, _k, _l in screen._ev_board._items}
    # Back to {DOSSIER, OSINT} on 2026-09-15. CREDENTIAL briefly appeared here
    # because UNSALTED_STORAGE was grouped there while tiered DOSSIER, so one
    # chip in it was observable before Hashcrack existed. That kind has since
    # moved to the DOSSIER group, where its tier already was, so every
    # remaining CREDENTIAL kind needs Hashcrack and the group is correctly
    # absent with only ghostscan unlocked.
    #
    # The RULE has not changed, and it is the thing to hold on to if this flips
    # again: a group appears exactly when at least one of its kinds is
    # observable, judged per KIND by that kind's own revealing tool, never per
    # group. Both spellings of this assertion were correct under that rule at
    # different times.
    assert groups == {"DOSSIER", "OSINT"}


def test_violation_table_and_board_respect_the_days_whitelist_and_archetype_mix():
    """Progression-unlock fix: a kind whose TOOL is unlocked can still be
    unreachable today because the day's own content can't plant it yet --
    either its allowed_violations whitelist excludes it (the tutorial teaches
    OSINT kinds progressively across days 2-5, not all at once the moment
    Ghostscan unlocks) or no archetype eligible for it is in today's
    archetype_mix. Before this fix, violation_table/visible_catalog/
    clustered_catalog gated on unlocked_tools alone, so e.g. TYPOSQUAT_HANDLE
    and the Stego carrier-shape kinds (SIGNAL_COMMS_PAYLOAD etc.) showed on
    the board and the Rules tabs from the moment their tool unlocked, days
    before the tutorial's own whitelist actually taught them."""
    from gameengine.core.models import DiscrepancyKind

    day2 = load_day(2)   # Ghostscan's unlock day; its own whitelist doesn't
                          # yet include TYPOSQUAT_HANDLE (that opens Day 6).
    gated_text = "\n".join(
        rules_content.violation_table(day2, "OSINT", unlocked_tools={"ghostscan"}))
    assert "TYPOSQUAT_HANDLE" not in gated_text, (
        "TYPOSQUAT_HANDLE shown on Day 2's OSINT table even though Day 2's "
        "own allowed_violations whitelist doesn't teach it yet")

    day6 = load_day(6)   # first day with an empty whitelist -> fully taught.
    open_text = "\n".join(
        rules_content.violation_table(day6, "OSINT", unlocked_tools={"ghostscan"}))
    assert "TYPOSQUAT_HANDLE" in open_text, (
        "TYPOSQUAT_HANDLE missing from Day 6's OSINT table even though "
        "nothing restricts it any more -- the gate should have opened, not "
        "just closed"
    )

    # Same rule, the Evidence Board's own catalog builders (not just the
    # Rules-tab table), and the Stego carrier-shape kinds specifically --
    # Nick's other concrete example of the gap.
    day5 = load_day(5)   # Stegotool's unlock day; its whitelist covers the
                          # colour kinds but not the carrier-shape kinds yet.
    day5_kinds = {k for _g, k, _l in
                  rules_content.visible_catalog({"stegotool"}, day5)}
    assert DiscrepancyKind.SIGNAL_COMMS_PAYLOAD not in day5_kinds
    assert DiscrepancyKind.RECURSIVE_PAYLOAD not in day5_kinds
    assert DiscrepancyKind.HOSTILE_PAYLOAD not in day5_kinds

    day6_kinds = {
        k for _grp, _cid, _lab, items in
        rules_content.clustered_catalog({"stegotool"}, day6)
        for _g2, k, _lbl in items
    }
    assert DiscrepancyKind.SIGNAL_COMMS_PAYLOAD in day6_kinds

    # `unlocked_tools=None` must still mean "no gating context at all" --
    # both filters off, not just the tool one (regression guard for the
    # None-symmetry bug this fix introduced and then fixed in the same pass).
    unfiltered = {k for _g, k, _l in rules_content.visible_catalog(None, day2)}
    assert DiscrepancyKind.TYPOSQUAT_HANDLE in unfiltered


def test_reachability_is_cumulative_and_never_revokes_a_kind():
    """Progression-unlock fix (2026-09-21): once a DiscrepancyKind has been
    reachable on some day, it must stay reachable on every later day, even
    when that later day's own scripted archetype_mix wouldn't roll it.

    Nick's concrete repro: Day 3 is hand-scripted and its archetype_mix
    happens not to include an archetype eligible for DISPOSABLE_EMAIL or
    UNSALTED_STORAGE, even though both are DOSSIER kinds with no tool gate at
    all and both were plainly reachable on Day 1 and Day 2. Before this fix,
    the single-day `candidate_gen.kinds_the_day_can_plant(day)` check made
    them vanish from the Evidence Board and the Rules tables on Day 3 --
    evidence types the player had already been shown flickering off the
    board reads as the Overseer erasing evidence, not as a difficulty gate,
    and defeats the board's whole point as a running checklist."""
    from gameengine.core.models import DiscrepancyKind
    from gameengine.core import candidate_gen, content_loader

    day3 = content_loader.load_day(3)
    single_day = candidate_gen.kinds_the_day_can_plant(day3)
    assert DiscrepancyKind.DISPOSABLE_EMAIL not in single_day, (
        "test fixture assumption broken: Day 3's own archetype_mix now DOES "
        "carry DISPOSABLE_EMAIL, so it no longer isolates the cumulative fix"
    )
    assert DiscrepancyKind.UNSALTED_STORAGE not in single_day

    cumulative = content_loader.kinds_discovered_through(3)
    assert DiscrepancyKind.DISPOSABLE_EMAIL in cumulative, (
        "DISPOSABLE_EMAIL was reachable on Day 1/2 and must stay reachable "
        "through Day 3, even though Day 3's own script wouldn't roll it"
    )
    assert DiscrepancyKind.UNSALTED_STORAGE in cumulative

    # And the fix must actually be wired into the player-facing surfaces --
    # not just the underlying content_loader helper.
    unlocked = {"dossier", "ghostscan", "hashcrack", "logwatch", "stegotool"}
    board_kinds = {
        k for _grp, _cid, _lab, items in
        rules_content.clustered_catalog(unlocked, day3)
        for _g2, k, _lbl in items
    }
    assert DiscrepancyKind.DISPOSABLE_EMAIL in board_kinds
    assert DiscrepancyKind.UNSALTED_STORAGE in board_kinds

    table_text = "\n".join(
        rules_content.violation_table(day3, "DOSSIER", unlocked_tools=unlocked))
    assert "DISPOSABLE_EMAIL" in table_text
    assert "UNSALTED_STORAGE" in table_text


def test_rules_page_tables_group_rows_under_evidence_board_subcategories():
    """Nick, 2026-09-21: 'include the evidence types subcategories on the
    rules page so the user can better understand their organization' with
    the same 'dynamic colour, static position' policy as the board -- rows
    grouped and ordered exactly like `VIOLATION_CLUSTERS`/`clustered_catalog`,
    not re-sorted by severity, so a row's position never moves and only its
    colour changes when a rule is re-tiered."""
    day1 = load_day(1)
    lines = rules_content.violation_table(day1, "DOSSIER")
    text = "\n".join(lines)
    # Both DOSSIER subcategory headers from VIOLATION_CLUSTERS must appear,
    # in their authored order, each ahead of the rows it groups.
    assert "Identity Confirmation" in text
    assert "Personal" in text
    assert text.index("Identity Confirmation") < text.index("AFFILIATION_NOT_STATED")
    assert text.index("Personal") < text.index("HOSTILE_CHAT")
    assert text.index("AFFILIATION_NOT_STATED") < text.index("Personal"), (
        "Identity Confirmation's rows must render before the Personal header"
    )

    # Rows must NOT be severity-sorted any more: AFFILIATION_NOT_STATED
    # (minor) stays ahead of DISPOSABLE_EMAIL (major) because that is their
    # authored cluster order, not because of their severity.
    assert (text.index("AFFILIATION_NOT_STATED")
            < text.index("DISPOSABLE_EMAIL")), (
        "DOSSIER rows were re-sorted by severity instead of keeping "
        "VIOLATION_CLUSTERS' authored order"
    )


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


def test_the_tier_reference_moved_to_the_credentials_tab():
    """The per-tier reference lives where the player now needs it.

    Rewritten 2026-09-14. The Dossier tab used to carry a quick-reference
    version of the encryption-strength chip, with a worked example per tier.
    That chip no longer exists: the dossier shows a raw hash and says nothing
    about it, because establishing the algorithm is the cipher block's job and
    WEAK_ENCRYPTION is a violation ABOUT the algorithm.

    So the assertion moves rather than disappears — the reference a player
    matches a digest against still has to exist somewhere, and that somewhere
    is the CREDENTIALS tab. The Dossier tab keeps only what the dossier itself
    shows: a raw hash, and the one credential violation visible with no tool."""
    from rich.errors import MarkupError
    from rich.text import Text

    day = load_day(1)
    creds = rules_content.build_creds_text(day, {"hashcrack"})

    # Each tier identifiable by the shape the block header actually prints.
    assert "32 hex characters" in creds     # WEAK / MD5
    assert "64 hex characters" in creds     # MEDIUM / SHA256
    assert "$2b$ prefix" in creds           # STRONG / bcrypt
    # ...and the tab must say which of them is worth opening at all.
    assert "bcrypt is a dead end by design" in creds

    dossier = rules_content.build_dossier_text(day)
    i = dossier.find("the password field")
    assert i != -1
    section = dossier[i:i + 1400]
    assert "UNSALTED" in section, (
        "the dossier no longer documents the one credential violation it does "
        "show for free")
    for gone in ("WEAK ENC", "MEDIUM ENC", "STRONG ENC"):
        assert gone not in section, (
            f"{gone!r} is back on the dossier — the tier chip was removed so "
            f"that WEAK_ENCRYPTION is not pre-flagged on every candidate")

    # Per-LINE rather than whole-text: a single malformed tag is far easier to
    # find when the failure names the one line carrying it.
    for label, body in (("credentials tab", creds), ("dossier tab", dossier)):
        for ln in body.split("\n"):
            try:
                Text.from_markup(ln)
            except MarkupError as e:
                raise AssertionError(
                    f"invalid markup in {label}: {ln!r} ({e})") from e
