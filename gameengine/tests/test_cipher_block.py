"""Tests for the Hashcrack cipher block — a two-stage decryption minigame.

The engine-side guards in test_engine_foundation.py cover how this tool fits
the rest of the game: the evidence-token contract, the foreign-claim guard,
corpus agreement across surfaces, and the upgrade gates. This file covers the
mechanic itself — block construction, the window choice, the alignment dial,
and the widget — plus the violation redistribution the rework carried with it.

Habits carried in from the Batch 4 write-up and round 1 of this feature:

  · Assert against the BLOCK, not against password_strength(). A guard that
    reads a conclusion computed from the same ground truth it asserts cannot
    detect a missing observation.

  · load_day(1) is authored tutorial content and is never a generic fixture.

  · When a revert-check comes back green, decide whether the GUARD is inert or
    the MUTATION was a no-op before changing anything.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from gameengine import config
from gameengine.core import candidate_gen, tools_bridge
from gameengine.core.content_loader import load_day
from gameengine.core.models import Archetype, DiscrepancyKind, GameState, ToolName
from gameengine.ui.tui import rules_content


def _unconstrained_day(number: int):
    """A day shape with no authored whitelist or script."""
    return replace(load_day(1), number=number, allowed_violations=(),
                   forced_includes={}, forced_violations={})


def _blocks(day_number: int, seeds: int = 40):
    day = _unconstrained_day(day_number)
    for seed in range(seeds):
        for slot in range(day.candidate_count):
            cand = candidate_gen.generate(seed, day, slot)
            yield cand, tools_bridge.build_cipher_block(cand, day_number)


def _first_block(day_number: int = 8, **want):
    """The first block matching every attribute in `want`."""
    for cand, block in _blocks(day_number, seeds=60):
        if all(getattr(block, k) == v for k, v in want.items()):
            return cand, block
    raise AssertionError(f"no block matching {want} — guard is inert")


def _rich_state(day_number: int = 8) -> GameState:
    st = GameState(seed=1, current_day=day_number, compute_hours=10_000)
    st.unlocked_tools = {"ghostscan", "hashcrack", "logwatch", "stegotool"}
    return st


# ── Block construction ──────────────────────────────────────────────────────


def test_block_is_deterministic_per_candidate():
    """Same candidate, same day → an identical block, down to the dial.

    Save replay and the lab CLI's `--seed` reproduction both depend on this,
    and so does the dial itself: a player turning it back and forth must see
    the same picture at the same value.
    """
    for cand, block in _blocks(5, seeds=10):
        again = tools_bridge.build_cipher_block(cand, 5)
        assert block.cipher_glyphs == again.cipher_glyphs
        assert block.plain_glyphs == again.plain_glyphs
        assert block.cell_tolerance == again.cell_tolerance
        assert block.align_true == again.align_true


@pytest.mark.parametrize("tier", ["weak", "medium", "strong"])
def test_each_tier_has_a_visibly_distinct_block_width(tier):
    """Block shape is the free tell, so the three tiers must not converge.

    This is the skill the feature is built on: the player reads the block
    against the reference table and decides both which window fits and whether
    to open it at all. Two tiers at the same width deletes that read — and it
    would do so without failing any other test, because every other surface
    would still be correct.
    """
    widths = {t: config.CIPHER_GRID_BASE[t][0]
              for t in ("weak", "medium", "strong")}
    others = [w for t, w in widths.items() if t != tier]
    assert all(abs(widths[tier] - w) >= 4 for w in others), (
        f"{tier} block ({widths[tier]} cols) is within 4 columns of another "
        f"tier {widths} — the tiers are no longer distinguishable at a glance")


def test_digest_shape_distinguishes_every_tier():
    """The header's free line must actually separate the three algorithms.

    Asserted on the RENDERED header rather than on cipher_tier(), which is
    computed from the same hash the assertion would use. The header is the only
    thing the player sees.
    """
    seen = {}
    for _cand, block in _blocks(8, seeds=40):
        header = "\n".join(tools_bridge.cipher_header_lines(block, set()))
        digest = next(ln for ln in header.split("\n") if "digest:" in ln)
        seen.setdefault(block.tier, set()).add(digest)
    assert set(seen) == {"weak", "medium", "strong"}, "guard is inert"
    flat = [d for v in seen.values() for d in v]
    assert len(set(flat)) == len(flat), (
        f"two tiers print the same digest line {seen} — the free read is gone")


def test_bcrypt_blocks_carry_their_prefix_and_have_no_dial():
    """The strong tier's defining facts, asserted on the block itself."""
    checked = 0
    for _cand, block in _blocks(8, seeds=25):
        if block.tier != "strong":
            continue
        checked += 1
        assert not block.crackable
        assert block.plaintext is None
        assert block.align_range == 0, "a bcrypt block has a dial to turn"
        top = "".join(block.cipher_glyphs[0][:len(config.CIPHER_BCRYPT_PREFIX)])
        assert top == config.CIPHER_BCRYPT_PREFIX, (
            f"bcrypt block's top row starts {top!r}, not its cost prefix — "
            f"the structural tell is gone")
    assert checked, "guard is inert — no bcrypt candidate examined"


def test_the_decrypted_block_is_the_password_tiled():
    """Every row of the solved block reads as repeats of the password.

    Tiling is what lets a player at 70% read the password by consensus across
    rows, which is the whole reason the last few dial steps are satisfying
    rather than fiddly. A block that decrypted to one run in a sea of filler
    would lose that and no other test would notice.
    """
    _cand, block = _first_block(8, tier="medium", pre_revealed=False)
    flat = "".join("".join(row) for row in block.plain_glyphs)
    unit = block.plaintext + config.CIPHER_TILE_SEPARATOR
    assert flat, "guard is inert"
    # Every character position must match the repeating unit.
    expected = (unit * (len(flat) // len(unit) + 2))[:len(flat)]
    assert flat == expected, "the decrypted block is not a clean tiling"
    assert flat.count(block.plaintext) >= 2, (
        "the password appears once — there is nothing to cross-reference")


def test_unsalted_blocks_arrive_decrypted():
    """UNSALTED_STORAGE means the value is exposed with no tool run at all."""
    checked = 0
    for day_n in (1, 8, 12):
        for cand, block in _blocks(day_n, seeds=30):
            if not any(d.kind == DiscrepancyKind.UNSALTED_STORAGE
                       for d in cand.truth.discrepancies):
                continue
            checked += 1
            assert block.pre_revealed
            grid = tools_bridge.render_block(block, 0, engaged=False)
            assert all(res for row in grid for _g, res in row), (
                "an unsalted block still renders as ciphertext — the violation "
                "is that no decryption is required")
            assert tools_bridge.alignment_locked(block, 0)
    assert checked, "guard is inert — no unsalted candidate examined"


# ── Stage 1 — the decryption window ─────────────────────────────────────────


def test_only_the_matching_window_engages_the_decrypt():
    """The three outcomes, asserted per tier against every window."""
    checked = 0
    for tier in ("weak", "medium", "strong"):
        _cand, block = _first_block(8, tier=tier, pre_revealed=False)
        for key, _label, _shape in config.CIPHER_WINDOWS:
            res = tools_bridge.apply_window(block, key, _rich_state())
            checked += 1
            if key != tier:
                assert res.outcome == tools_bridge.CIPHER_WINDOW_WRONG
            elif tier == "strong":
                assert res.outcome == tools_bridge.CIPHER_WINDOW_STALLED, (
                    "the bcrypt window ENGAGED — correctly identifying "
                    "key-stretching must not make it crackable")
            else:
                assert res.outcome == tools_bridge.CIPHER_WINDOW_ENGAGED
    assert checked == 9, "guard is inert"


def test_a_window_costs_the_tools_base_cost_and_respects_its_upgrade():
    """Window price routes through tool_cost(), so inflation and the optimizer
    both keep applying to Hashcrack exactly as to every other tool."""
    for day_n in (1, 4, 12, 20):
        plain = GameState(seed=1, current_day=day_n)
        assert (tools_bridge.window_cost(plain)
                == config.DAY_TOOL_COST("hashcrack", day_n))
        opt = GameState(seed=1, current_day=day_n)
        opt.upgrades = {config.UPGRADE_TOOLCOST_HASHCRACK}
        assert tools_bridge.window_cost(opt) < tools_bridge.window_cost(plain), (
            "Hashcrack Optimizer stopped reducing the window price")


def test_a_wrong_window_still_costs_and_a_refused_one_does_not():
    """Being wrong is paid for; being unable to pay is free.

    The second half matters more than it looks: apply_window() must check
    affordability BEFORE deducting, or a player at 1 ⏱ ends the day at a
    negative balance for a purchase that never happened.
    """
    _cand, block = _first_block(8, tier="medium", pre_revealed=False)

    rich = _rich_state()
    before = rich.compute_hours
    res = tools_bridge.apply_window(block, "weak", rich)
    assert res.outcome == tools_bridge.CIPHER_WINDOW_WRONG
    assert rich.compute_hours == before - res.cost, "a wrong window was free"

    broke = GameState(seed=1, current_day=8, compute_hours=1)
    with pytest.raises(tools_bridge.InsufficientCompute):
        tools_bridge.apply_window(block, "medium", broke)
    assert broke.compute_hours == 1, "a refused purchase still spent ⏱"


def test_reading_the_block_is_free_and_opening_bcrypt_is_not():
    """The economic shape of the whole feature, in one assertion.

    A player who reads the digest and walks away from a bcrypt spends nothing.
    A player who opens it to find out pays a full window for information that
    was on screen from the start. That gap IS the skill the free read rewards,
    and if it ever closes the read stops mattering.
    """
    _cand, block = _first_block(8, tier="strong")

    reader = _rich_state()
    before = reader.compute_hours
    tools_bridge.cipher_header_lines(block, set())
    tools_bridge.get_cipher_intro(block, set())
    assert reader.compute_hours == before, "reading the block cost ⏱"

    opener = _rich_state()
    before = opener.compute_hours
    res = tools_bridge.apply_window(block, "strong", opener)
    assert res.outcome == tools_bridge.CIPHER_WINDOW_STALLED
    assert opener.compute_hours < before, (
        "opening a bcrypt block was free — the free read has nothing to reward")


# ── Stage 2 — the alignment dial ────────────────────────────────────────────


def test_the_dial_is_free_to_turn():
    """Stage 2 costs nothing; the spend decision was made once, in stage 1."""
    _cand, block = _first_block(8, tier="medium", pre_revealed=False)
    state = _rich_state()
    tools_bridge.apply_window(block, block.tier, state)
    after_purchase = state.compute_hours
    for d in range(block.align_range + 1):
        tools_bridge.render_block(block, d)
        tools_bridge.resolved_fraction(block, d)
        tools_bridge.alignment_locked(block, d)
    assert state.compute_hours == after_purchase, "turning the dial cost ⏱"


def test_exact_alignment_is_distinguishable_from_one_step_off():
    """err=1 must NOT look the same as err=0.

    The failure this catches is subtle and was real: drawing per-cell tolerance
    from 1..tol gives every cell a tolerance of at least one, so the block
    renders fully legible one step away from true. The player would see a
    finished password and have no way to know they were not there yet, and
    "fine-tune it exactly" would have no meaning. A share of cells must have
    tolerance 0 so they only settle at the exact value.
    """
    checked = 0
    for _cand, block in _blocks(8, seeds=40):
        if not block.crackable or block.pre_revealed:
            continue
        if block.align_true >= block.align_range:
            continue
        checked += 1
        exact = tools_bridge.resolved_fraction(block, block.align_true)
        off_by_one = tools_bridge.resolved_fraction(block, block.align_true + 1)
        assert exact == 1.0, "the true alignment does not fully resolve"
        assert off_by_one < 1.0, (
            "one step off the true value renders identically to exact — every "
            "cell has a non-zero tolerance, so nothing marks the lock")
        assert not tools_bridge.alignment_locked(block, block.align_true + 1)
        assert tools_bridge.alignment_locked(block, block.align_true)
    assert checked, "guard is inert"


def test_the_block_sharpens_monotonically_toward_the_true_value():
    """Closer must never look worse, or hill-climbing by eye is a lie."""
    checked = 0
    for _cand, block in _blocks(8, seeds=25):
        if not block.crackable or block.pre_revealed:
            continue
        checked += 1
        prev = None
        for err in range(block.align_tolerance + 2, -1, -1):
            d = block.align_true + err
            if d > block.align_range:
                continue
            frac = tools_bridge.resolved_fraction(block, d)
            if prev is not None:
                assert frac >= prev, (
                    f"moving from err {err + 1} to {err} made the block LESS "
                    f"legible ({prev:.2f} -> {frac:.2f})")
            prev = frac
    assert checked, "guard is inert"


def test_beyond_tolerance_the_block_is_pure_ciphertext():
    """Out of range there is no partial signal to read — you must sweep."""
    checked = 0
    for _cand, block in _blocks(8, seeds=25):
        if not block.crackable or block.pre_revealed:
            continue
        far = block.align_true + block.align_tolerance + 1
        if far > block.align_range:
            far = block.align_true - block.align_tolerance - 1
        if far < 0:
            continue
        checked += 1
        assert tools_bridge.resolved_fraction(block, far) == 0.0
        grid = tools_bridge.render_block(block, far)
        assert not any(res for row in grid for _g, res in row)
    assert checked, "guard is inert"


def test_the_dial_shows_nothing_until_a_window_is_applied():
    """A block the player has not paid for must render as ciphertext at EVERY
    dial position — otherwise stage 1 could be skipped by spinning."""
    _cand, block = _first_block(8, tier="medium", pre_revealed=False)
    for d in range(block.align_range + 1):
        grid = tools_bridge.render_block(block, d, engaged=False)
        assert not any(res for row in grid for _g, res in row), (
            f"dial position {d} leaked plaintext before a window was bought")


# ── Violation redistribution ────────────────────────────────────────────────


def test_credential_severities_match_the_redistribution():
    """The severity ordering this rework set, asserted where it is defined."""
    sev = {k: s for k, (_t, s) in candidate_gen._SEVERITY_REVEAL.items()}
    assert sev[DiscrepancyKind.CROSS_BREACH_REUSE] == "critical", (
        "reuse outranks exposure: being dumped is misfortune, still using it "
        "is a choice")
    assert sev[DiscrepancyKind.LEAKED_PASSWORD] == "major"
    assert sev[DiscrepancyKind.UNSALTED_STORAGE] == "major"
    assert sev[DiscrepancyKind.WEAK_CREDENTIAL] == "minor"
    assert sev[DiscrepancyKind.WEAK_ENCRYPTION] == "minor"


def test_every_eligible_kind_fits_its_archetypes_budget():
    """No archetype may list a kind it has no budget slot to hold.

    This is the guard the codebase did not have, and its absence is what let
    CROSS_BREACH_REUSE's promotion to critical silently delete the kind from
    Clumsy Cutie. `_roll_discrepancies` gates each pick against its own
    severity's slot, so a listed-but-unaffordable kind is not an error — it
    simply never appears, on an archetype somebody chose it for.
    """
    # One documented, deliberate exception. The White Hat's budget is sized
    # exactly to its three scripted day-12 forced kinds (major=1, critical=2)
    # so `take()` has nothing spare to fill in randomly afterwards; these two
    # minor kinds are, in the spec's own words, "eligible but never actually
    # rolled" and kept listed for variety if the budget is ever widened. It is
    # exempted by NAME rather than by loosening the rule, so a NEW unrollable
    # kind on any archetype — including this one — still fails.
    KNOWN_UNROLLABLE = {
        (Archetype.WHITE_HAT, DiscrepancyKind.MISSING_PUBLIC_PROFILE),
        (Archetype.WHITE_HAT, DiscrepancyKind.AFFILIATION_NOT_STATED),
    }

    sev = {k: s for k, (_t, s) in candidate_gen._SEVERITY_REVEAL.items()}
    problems = []
    for arch, spec in candidate_gen.ARCHETYPE_SPECS.items():
        budget = spec.budget
        for kind in spec.eligible_kinds:
            if (arch, kind) in KNOWN_UNROLLABLE:
                continue
            slots = getattr(budget, sev[kind], 0)
            if slots <= 0:
                problems.append(
                    f"{arch.value} lists {kind.name} ({sev[kind]}) but has no "
                    f"{sev[kind]} slot")
    assert not problems, (
        "archetypes list violations they can never roll:\n  "
        + "\n  ".join(problems))

    # The exemptions must stay real: if one is fixed or removed, drop it here
    # rather than leaving a stale entry that would mask a genuine regression.
    for arch, kind in KNOWN_UNROLLABLE:
        spec = candidate_gen.ARCHETYPE_SPECS[arch]
        assert kind in spec.eligible_kinds, (
            f"{arch.value} no longer lists {kind.name} — remove it from "
            f"KNOWN_UNROLLABLE so this guard keeps its teeth")


def test_cross_breach_reuse_moved_to_the_misconduct_archetypes():
    """The kind is off Clumsy Cutie and reachable on the archetypes it moved
    to — asserted by GENERATING, not by reading the spec lists."""
    base = load_day(1)
    seen = {}
    for arch in (Archetype.CLUMSY_CUTIE, Archetype.SNEAKY_BUGGER,
                 Archetype.BAD_ACTOR):
        found = 0
        for day_n in (3, 8, 16):
            day = replace(base, number=day_n, allowed_violations=(),
                          forced_includes={0: arch}, forced_violations={},
                          archetype_mix={arch: 1})
            for seed in range(40):
                c = candidate_gen.generate(seed, day, 0)
                if DiscrepancyKind.CROSS_BREACH_REUSE in {
                        d.kind for d in c.truth.discrepancies}:
                    found += 1
        seen[arch] = found
    assert seen[Archetype.CLUMSY_CUTIE] == 0, (
        "Clumsy Cutie still rolls CROSS_BREACH_REUSE — it has no critical slot, "
        "so this should be impossible")
    assert seen[Archetype.SNEAKY_BUGGER] > 0, "Sneaky Bugger never rolls it"
    assert seen[Archetype.BAD_ACTOR] > 0, "Bad Actor never rolls it"


def test_day_3_still_teaches_reuse():
    """Day 3's scripted lesson must actually land.

    It stopped landing when CROSS_BREACH_REUSE became critical while slot 2
    was still a Clumsy Cutie: the day loaded, read as a credentials tutorial,
    and simply never planted the kind — in 40 of 40 seeds. The forced_violations
    loader validates tier, expressibility and whitelist but never budget
    capacity, so nothing failed loudly.
    """
    day = load_day(3)
    missing = 0
    for seed in range(60):
        c = candidate_gen.generate(seed, day, 2)
        if DiscrepancyKind.CROSS_BREACH_REUSE not in {
                d.kind for d in c.truth.discrepancies}:
            missing += 1
    assert missing == 0, (
        f"day 3's reuse lesson is absent in {missing}/60 seeds — slot 2's "
        f"archetype cannot hold a critical violation")


def test_day_3_is_solvable_with_day_3_tools():
    """Nothing on the credentials tutorial may need a tool the player lacks."""
    day = load_day(3)
    available = {ToolName.DOSSIER, ToolName.GHOSTSCAN, ToolName.HASHCRACK}
    unreachable = set()
    for seed in range(60):
        for slot in range(day.candidate_count):
            c = candidate_gen.generate(seed, day, slot)
            for d in c.truth.discrepancies:
                if d.revealed_by not in available:
                    unreachable.add(f"{d.kind.name} via {d.revealed_by.value}")
    assert not unreachable, (
        f"day 3 plants violations the player cannot investigate: "
        f"{sorted(unreachable)}")


# ── Cascade into the tracking surfaces ──────────────────────────────────────


def test_every_credential_kind_is_grouped_and_clustered_together():
    """All five credential violations track on one board group.

    WEAK_ENCRYPTION reached this test the hard way: it was retiered
    DOSSIER -> HASHCRACK while its catalogue entry stayed under DOSSIER, so the
    board filed it under a group whose tool no longer revealed it. A kind's
    group and its revealing tool are allowed to differ (UNSALTED_STORAGE does,
    deliberately) — what is not allowed is a credential kind tracking somewhere
    other than with the credentials.
    """
    want = {
        DiscrepancyKind.WEAK_ENCRYPTION, DiscrepancyKind.UNSALTED_STORAGE,
        DiscrepancyKind.WEAK_CREDENTIAL, DiscrepancyKind.LEAKED_PASSWORD,
        DiscrepancyKind.CROSS_BREACH_REUSE,
    }
    grouped = {k for g, k, _lbl in rules_content.VIOLATION_CATALOG
               if g == "CREDENTIAL"}
    assert grouped == want, (
        f"CREDENTIAL group is {sorted(k.name for k in grouped)}, expected "
        f"{sorted(k.name for k in want)}")

    clustered = {k for g, _cid, _lbl, kinds in rules_content.VIOLATION_CLUSTERS
                 if g == "CREDENTIAL" for k in kinds}
    assert clustered == want, "board clusters disagree with the catalogue"


def test_unsalted_storage_is_documented_before_hashcrack_unlocks():
    """A kind must never be plantable and undocumented on the same day.

    UNSALTED_STORAGE is catalogued under CREDENTIAL but tiered DOSSIER, so it
    is plantable from day 1 while the CREDENTIAL rules tab stays locked until
    day 3. The locked tab therefore has to document it — otherwise a day-1
    player meets a chip on the evidence board with nowhere to look it up.
    """
    locked = rules_content.build_creds_text(load_day(1), set())
    assert "UNSALTED_STORAGE" in locked, (
        "the locked CREDENTIAL tab does not document the one credential "
        "violation reachable without the tool")
    # ...and it must not spoil the kinds that ARE gated.
    for gated in ("LEAKED_PASSWORD", "CROSS_BREACH_REUSE", "WEAK_CREDENTIAL"):
        assert gated not in locked, (
            f"{gated} is documented on a locked tab before its tool exists")

    unlocked = rules_content.build_creds_text(load_day(5), {"hashcrack"})
    for kind in ("UNSALTED_STORAGE", "LEAKED_PASSWORD", "CROSS_BREACH_REUSE",
                 "WEAK_CREDENTIAL", "WEAK_ENCRYPTION"):
        assert kind in unlocked, f"{kind} missing from the unlocked tab"


def test_the_rules_page_shows_the_redistributed_severities():
    """The rules table reads severity from the generator, so a redistribution
    must reach the player without anyone editing prose."""
    text = rules_content.build_creds_text(load_day(5), {"hashcrack"})
    rows = [ln for ln in text.split("\n") if "CROSS_BREACH_REUSE" in ln]
    assert any("critical" in r for r in rows), (
        "the rules page still calls cross-breach reuse something other than "
        "critical")
    rows = [ln for ln in text.split("\n") if "LEAKED_PASSWORD" in ln]
    assert any("major" in r for r in rows)


# ── The widget ──────────────────────────────────────────────────────────────


class _Recorder:
    """Stands in for the Static that compose() would mount.

    Captures the markup the panel writes rather than reading it back out of
    Textual — Static's internal storage attribute has moved between Textual
    versions, and a test that reaches for it fails on an upgrade for reasons
    that have nothing to do with this widget.
    """

    def __init__(self) -> None:
        self.text = ""

    def update(self, markup: str) -> None:
        self.text = markup


def _panel(cand, day_number=8, **flags):
    from gameengine.ui.tui.widgets import CipherBlockPanel
    p = CipherBlockPanel()
    p._content = _Recorder()
    for k, v in flags.items():
        setattr(p, k, v)
    p.load_candidate(cand, day_number)
    return p


def test_panel_walks_the_two_stages():
    cand, block = _first_block(8, tier="medium", pre_revealed=False)
    p = _panel(cand)
    assert p.state == p.IDLE

    p.open_selector()
    assert p.state == p.SELECTING
    tiers = [w[0] for w in config.CIPHER_WINDOWS]
    p.move_selection(1)
    assert p.selected_tier == tiers[1]
    p.move_selection(-1)
    assert p.selected_tier == tiers[0]

    p.apply_result(tools_bridge.apply_window(block, "weak", _rich_state()))
    assert p.state == p.SELECTING, "a wrong window should leave the retry open"
    assert p.attempts == 1

    p.apply_result(tools_bridge.apply_window(block, block.tier, _rich_state()))
    assert p.state == p.ENGAGED and p.dial == 0

    p.move_dial(block.align_true)
    assert p.locked and p.dial == block.align_true


def test_panel_dial_is_clamped_to_the_track():
    cand, block = _first_block(8, tier="medium", pre_revealed=False)
    p = _panel(cand)
    p.open_selector()
    p.apply_result(tools_bridge.apply_window(block, block.tier, _rich_state()))
    p.move_dial(-9999)
    assert p.dial == 0
    p.move_dial(9999)
    assert p.dial == block.align_range


def test_panel_keeps_an_engaged_block_when_the_player_leaves():
    """Closing decrypt mode must not discard a purchase."""
    cand, block = _first_block(8, tier="medium", pre_revealed=False)
    p = _panel(cand)
    p.open_selector()
    p.apply_result(tools_bridge.apply_window(block, block.tier, _rich_state()))
    p.move_dial(3)
    p.close()
    assert p.state == p.ENGAGED and p.dial == 3, (
        "walking away reset a window the player already paid for")
    p.open_selector()
    assert p.state == p.ENGAGED, "re-entering restarted stage 1 after a buy"


def test_panel_resets_between_candidates():
    day = _unconstrained_day(8)
    p = _panel(candidate_gen.generate(3, day, 0))
    p.open_selector()
    p.apply_result(tools_bridge.apply_window(
        p.block, p.block.tier, _rich_state()))
    p.move_dial(2)
    p.load_candidate(candidate_gen.generate(3, day, 1), 8)
    assert p.attempts == 0 and p.dial == 0
    assert p.state in (p.IDLE, p.LOCKED)


def test_panel_marks_the_hint_band_only_with_credential_hud():
    """Checks the RENDER, not the flag — the bug this guards against is a
    renderer that draws the band unconditionally, which would leave the flag
    looking correct while every player saw the hint."""
    cand, block = _first_block(8, tier="medium", pre_revealed=False)

    def render(hint: bool) -> str:
        p = _panel(cand, hint_upgrade=hint)
        p.open_selector()
        p.apply_result(tools_bridge.apply_window(
            block, block.tier, _rich_state()))
        return p._content.text

    plain, hinted = render(False), render(True)
    assert plain != hinted, (
        "Credential HUD changed nothing on screen — the band is either always "
        "drawn or never drawn")
    assert "#4a6b8a" in hinted and "#4a6b8a" not in plain


def test_panel_never_shows_a_progress_percentage():
    """The dial shows POSITION, never PROGRESS.

    A percentage readout would let the player hill-climb a number instead of
    reading the block, which is the one thing this stage exists for.
    """
    cand, block = _first_block(8, tier="medium", pre_revealed=False)
    p = _panel(cand)
    p.open_selector()
    p.apply_result(tools_bridge.apply_window(block, block.tier, _rich_state()))
    for d in (0, block.align_range // 2, block.align_true):
        p.move_dial(d - p.dial)
        assert "%" not in p._content.text, (
            f"the panel printed a percentage at dial {d} — that replaces "
            f"reading the block with reading a number")
