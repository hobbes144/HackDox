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


def test_bcrypt_blocks_carry_their_prefix_and_have_no_pad():
    """The strong tier's defining facts, asserted on the block itself."""
    checked = 0
    for _cand, block in _blocks(8, seeds=25):
        if block.tier != "strong":
            continue
        checked += 1
        assert not block.crackable
        assert block.plaintext is None
        assert (block.align_span_x, block.align_span_y) == (0, 0), (
            "a bcrypt block has a pad to walk")
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
            grid = tools_bridge.render_block(block, 0, 0, engaged=False)
            assert all(res for row in grid for _g, res in row), (
                "an unsalted block still renders as ciphertext — the violation "
                "is that no decryption is required")
            assert tools_bridge.alignment_locked(block, 0, 0)
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


# ── Stage 2 — the alignment pad ─────────────────────────────────────────────


def _pad_positions(block):
    """Every coordinate on a block's pad."""
    for y in range(block.align_span_y + 1):
        for x in range(block.align_span_x + 1):
            yield x, y


def _crackable_blocks(day_n=8, seeds=25):
    for cand, block in _blocks(day_n, seeds=seeds):
        if block.crackable and not block.pre_revealed:
            yield cand, block


def test_walking_the_pad_costs_no_compute_by_itself():
    """The pad functions never charge — the step budget lives in IntakeScreen.

    Deliberately asserted at this layer. The overage fee has to be applied by
    the one component that owns ⏱; an engine function that quietly deducted
    would double-charge the moment the screen also did.
    """
    _cand, block = _first_block(8, tier="medium", pre_revealed=False)
    state = _rich_state()
    tools_bridge.apply_window(block, block.tier, state)
    after_purchase = state.compute_hours
    for x, y in _pad_positions(block):
        tools_bridge.render_block(block, x, y)
        tools_bridge.resolved_fraction(block, x, y)
        tools_bridge.alignment_locked(block, x, y)
    assert state.compute_hours == after_purchase, "reading the pad cost ⏱"


def test_exact_alignment_is_distinguishable_from_one_step_off():
    """err=1 must NOT look the same as err=0, on either axis.

    The failure this catches is subtle and was real: a per-cell tolerance draw
    with a floor of one makes the block render fully legible one step away from
    true. The player would see a finished password and have no way to know they
    were not there yet, and "fine-tune it exactly" would have no meaning. A
    share of cells must land on tolerance 0 so they only settle on the exact
    square.
    """
    checked = 0
    for _cand, block in _crackable_blocks(8, seeds=40):
        tx, ty = block.align_true
        neighbours = [(tx + 1, ty), (tx - 1, ty), (tx, ty + 1), (tx, ty - 1)]
        neighbours = [(x, y) for x, y in neighbours
                      if 0 <= x <= block.align_span_x
                      and 0 <= y <= block.align_span_y]
        assert neighbours, "pad has no neighbouring square to compare against"
        checked += 1
        assert tools_bridge.resolved_fraction(block, tx, ty) == 1.0, (
            "the true coordinate does not fully resolve")
        assert tools_bridge.alignment_locked(block, tx, ty)
        for x, y in neighbours:
            assert tools_bridge.resolved_fraction(block, x, y) < 1.0, (
                f"({x}, {y}) renders identically to the exact key — every cell "
                f"has a non-zero tolerance, so nothing marks the lock")
            assert not tools_bridge.alignment_locked(block, x, y)
    assert checked, "guard is inert"


def test_the_block_sharpens_as_you_physically_approach_the_key():
    """Stepping TOWARD the key must never make the block less legible.

    Measured against the pad's own geometry — distance computed here, in the
    test, from the coordinates — and NOT against block.error_at().

    That distinction is the whole value of this test, and the first version
    got it wrong. It grouped squares by error_at() and asserted the resolved
    fraction fell as error_at() rose, which is true by construction for ANY
    metric: resolved_fraction counts cells whose tolerance clears error_at(),
    so it is monotone in that function whatever the function does. Replacing
    the metric with nonsense — abs(|dx| - |dy|), which reports zero error all
    along a diagonal nowhere near the key — left the test green. A guard that
    passes on a metric pointing at the wrong square is not guarding anything.

    Phrased against real distance, it pins the property the player actually
    relies on: walk one square closer, and more characters settle.
    """
    checked = 0
    for _cand, block in _crackable_blocks(8, seeds=25):
        checked += 1
        tx, ty = block.align_true
        for x, y in _pad_positions(block):
            here_d = abs(x - tx) + abs(y - ty)
            here_f = tools_bridge.resolved_fraction(block, x, y)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx <= block.align_span_x
                        and 0 <= ny <= block.align_span_y):
                    continue
                there_d = abs(nx - tx) + abs(ny - ty)
                if there_d >= here_d:
                    continue          # that step moves away or sideways
                there_f = tools_bridge.resolved_fraction(block, nx, ny)
                assert there_f >= here_f, (
                    f"stepping from ({x}, {y}) to ({nx}, {ny}) moved "
                    f"{here_d - there_d} square closer to the key and made the "
                    f"block LESS legible ({here_f:.2f} -> {there_f:.2f})")
        # ...and reaching the key must be the unique maximum, or "closer is
        # better" has a plateau the player cannot walk off.
        assert tools_bridge.resolved_fraction(block, tx, ty) == 1.0
    assert checked, "guard is inert"


def test_the_reveal_depends_on_distance_alone():
    """Two squares the same distance from the key look the same.

    Rules out a reveal that leaks direction — if approaching along X painted a
    different picture than approaching along Y, the block would be telling the
    player which axis to fix, and the second axis would stop being a search.
    """
    checked = 0
    for _cand, block in _crackable_blocks(8, seeds=15):
        checked += 1
        tx, ty = block.align_true
        seen: dict[int, float] = {}
        for x, y in _pad_positions(block):
            d = abs(x - tx) + abs(y - ty)
            f = tools_bridge.resolved_fraction(block, x, y)
            if d in seen:
                assert seen[d] == f, (
                    f"two squares {d} from the key resolve differently "
                    f"({seen[d]:.3f} vs {f:.3f}) — the block is leaking which "
                    f"way you came")
            seen[d] = f
    assert checked, "guard is inert"


def test_every_square_on_the_pad_has_a_gradient_to_climb():
    """No dead zone: from anywhere, SOME characters are settled.

    This replaces an earlier guard that asserted the opposite — that beyond a
    fixed tolerance the block was pure ciphertext. That rule was written for
    the one-dimensional dial, where a dark region just meant "keep spinning".
    On a two-axis pad it meant over half the medium pad showed nothing at all,
    so every search opened with a blind walk. Blind walking is bad on its own,
    and it is worse now that stage 2 has a step budget: a player would be
    billed for steps they had no way to aim.

    So the tolerance distribution is convex over the whole pad instead
    (config.CIPHER_ALIGN_FALLOFF), and the invariant flips: the rim is DIM, not
    dark. Only the single farthest corner may be blank.
    """
    checked = 0
    for _cand, block in _crackable_blocks(8, seeds=25):
        checked += 1
        blank = [(x, y) for x, y in _pad_positions(block)
                 if tools_bridge.resolved_fraction(block, x, y) == 0.0
                 and block.error_at(x, y) < block.max_walk]
        assert not blank, (
            f"{len(blank)} squares inside the {block.tier} pad show no "
            f"resolved cells at all — those are dead zones the player cannot "
            f"steer out of, e.g. {blank[:3]}")
        # ...and the rim must still be much dimmer than the centre, or there
        # is no gradient worth reading.
        rim = tools_bridge.resolved_fraction(block, *_farthest_corner(block))
        assert rim < 0.35, (
            f"the far corner of the {block.tier} pad is {rim:.0%} legible — "
            f"the password is readable without walking anywhere")
    assert checked, "guard is inert"


def _farthest_corner(block):
    """The pad corner at maximum Manhattan distance from the true key."""
    return max(
        ((x, y) for x, y in [(0, 0), (block.align_span_x, 0),
                             (0, block.align_span_y),
                             (block.align_span_x, block.align_span_y)]),
        key=lambda p: block.error_at(*p))


def test_both_axes_move_the_error_by_exactly_one():
    """Every arrow press is worth the same, so none of them is a dead key.

    The metric has to be Manhattan for this. Under Chebyshev — the obvious
    alternative — a player one step off in x and nine off in y sees NOTHING
    change when they press left or right, because max() swallows the smaller
    axis. Half their presses would appear to do nothing, which reads as a
    broken control and makes the step budget arbitrary.
    """
    checked = 0
    for _cand, block in _crackable_blocks(8, seeds=15):
        checked += 1
        for x, y in _pad_positions(block):
            here = block.error_at(x, y)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx <= block.align_span_x
                        and 0 <= ny <= block.align_span_y):
                    continue
                assert abs(block.error_at(nx, ny) - here) == 1, (
                    f"stepping ({dx}, {dy}) from ({x}, {y}) moved the error by "
                    f"{abs(block.error_at(nx, ny) - here)}, not 1")
    assert checked, "guard is inert"


def test_the_pad_shows_nothing_until_a_window_is_applied():
    """A block the player has not paid for must render as ciphertext at EVERY
    pad square — otherwise stage 1 could be skipped by walking."""
    _cand, block = _first_block(8, tier="medium", pre_revealed=False)
    for x, y in _pad_positions(block):
        grid = tools_bridge.render_block(block, x, y, engaged=False)
        assert not any(res for row in grid for _g, res in row), (
            f"pad square ({x}, {y}) leaked plaintext before a window was bought")


# ── Stage 2 — the step budget ───────────────────────────────────────────────


def test_a_direct_walk_is_always_free():
    """The headline promise: play it right and stage 2 never costs anything.

    The cursor always starts at (0, 0), so the worst case a player who walks
    STRAIGHT at the key can face is the pad's full Manhattan diagonal. If the
    free allowance does not clear that, a player who did everything correctly
    still gets billed for the pad's size, and the fee stops meaning "you
    wandered" — which is the only thing it is supposed to mean.
    """
    checked = 0
    worst = 0
    for _cand, block in _crackable_blocks(8, seeds=25):
        checked += 1
        # From the CENTRE, which is where the cursor actually starts.
        direct = block.error_at(*block.start_cursor)
        worst = max(worst, direct, block.worst_direct_walk)
        assert tools_bridge.step_overage_charge(0, direct) == 0, (
            f"walking straight to the key on a {block.tier} block costs ⏱")
        assert direct <= block.worst_direct_walk, (
            "worst_direct_walk under-reports the real worst case")
    assert checked, "guard is inert"
    assert worst < config.CIPHER_DIAL_FREE_STEPS, (
        f"a perfect walk on the largest pad takes {worst} steps but only "
        f"{config.CIPHER_DIAL_FREE_STEPS} are free")


def test_the_budget_bills_every_boundary_a_move_crosses():
    """A multi-step move pays for all of it, not just the last threshold.

    Written this way because the naive implementation — "charge when this step
    lands on a multiple" — silently undercharges any move longer than one
    step, and the panel's clamped moves are exactly that.
    """
    free  = config.CIPHER_DIAL_FREE_STEPS
    block = config.CIPHER_DIAL_OVERAGE_BLOCK
    cost  = config.CIPHER_DIAL_OVERAGE_COST

    assert tools_bridge.step_overage_charge(0, free) == 0
    assert tools_bridge.step_overage_charge(free, free + 1) == cost
    assert tools_bridge.step_overage_charge(free + 1, free + block) == 0
    assert tools_bridge.step_overage_charge(free + block,
                                            free + block + 1) == cost
    # One move spanning three blocks pays three times.
    assert tools_bridge.step_overage_charge(free, free + 3 * block) == 3 * cost
    # And the sum of single steps matches one long move over the same span.
    piecewise = sum(tools_bridge.step_overage_charge(s, s + 1)
                    for s in range(0, free + 4 * block))
    assert piecewise == tools_bridge.step_overage_charge(0, free + 4 * block)


def test_the_countdown_never_lies_about_when_the_next_charge_lands():
    """steps_until_charge(n) must be exactly the presses left before a fee.

    It drives the footer, which is the only place the player can see the
    budget while their eyes are on the block — a readout that is off by one is
    worse than none at all.
    """
    for steps in range(0, config.CIPHER_DIAL_FREE_STEPS
                       + 3 * config.CIPHER_DIAL_OVERAGE_BLOCK):
        left = tools_bridge.steps_until_charge(steps)
        assert left >= 1
        walked = sum(tools_bridge.step_overage_charge(s, s + 1)
                     for s in range(steps, steps + left - 1))
        assert walked == 0, (
            f"at {steps} steps the footer promises {left} free presses, but a "
            f"charge lands inside them")
        assert tools_bridge.step_overage_charge(
            steps + left - 1, steps + left) == config.CIPHER_DIAL_OVERAGE_COST, (
            f"at {steps} steps the footer promises a charge in {left}, and "
            f"none arrives")


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


def test_every_hashcrack_kind_is_grouped_and_clustered_together():
    """Every kind Hashcrack reveals tracks on the CREDENTIAL board group.

    WEAK_ENCRYPTION reached this test the hard way: it was retiered
    DOSSIER -> HASHCRACK while its catalogue entry stayed under DOSSIER, so the
    board filed it under a group whose tool no longer revealed it.

    REPHRASED 2026-09-15, and the rephrasing is the point. This used to assert
    a hardcoded list of "the five credential violations", with UNSALTED_STORAGE
    among them as a documented group/tier mismatch. UNSALTED_STORAGE has since
    moved to the DOSSIER group to sit with the evidence that reveals it, so a
    hardcoded list would now just be a second copy of the catalogue that has to
    be edited in step with it — a test that can only ever restate the thing it
    is testing.

    Asserted as the RULE instead: the CREDENTIAL group is exactly the set of
    kinds whose revealing tool is Hashcrack. That still catches the original
    bug (a kind whose group and tool disagree), and it keeps working when kinds
    move, without anyone updating a literal.
    """
    from gameengine.core.models import ToolName

    want = {k for k, (tool, _sev) in candidate_gen._SEVERITY_REVEAL.items()
            if tool is ToolName.HASHCRACK}
    assert want, "guard is inert — no Hashcrack-tier kind exists"

    grouped = {k for g, k, _lbl in rules_content.VIOLATION_CATALOG
               if g == "CREDENTIAL"}
    assert grouped == want, (
        f"CREDENTIAL group is {sorted(k.name for k in grouped)}, but the kinds "
        f"Hashcrack reveals are {sorted(k.name for k in want)}")

    clustered = {k for g, _cid, _lbl, kinds in rules_content.VIOLATION_CLUSTERS
                 if g == "CREDENTIAL" for k in kinds}
    assert clustered == want, "board clusters disagree with the catalogue"

    # And the kind that left: UNSALTED_STORAGE must now be grouped where its
    # evidence is, with group and tier finally agreeing.
    us = DiscrepancyKind.UNSALTED_STORAGE
    assert candidate_gen._SEVERITY_REVEAL[us][0] is ToolName.DOSSIER
    assert any(g == "DOSSIER" and k is us
               for g, k, _lbl in rules_content.VIOLATION_CATALOG), (
        "UNSALTED_STORAGE is DOSSIER-tier but not in the DOSSIER group")


def test_unsalted_storage_is_documented_before_hashcrack_unlocks():
    """A kind must never be plantable and undocumented on the same day.

    UNSALTED_STORAGE is DOSSIER-tier, so it is plantable from day 1 while the
    CREDENTIAL tab stays locked until day 3. A day-1 player who meets the chip
    on the evidence board must have somewhere to look it up.

    WHERE that somewhere is moved on 2026-09-15. It used to be a violation
    table rendered on the LOCKED credentials tab; the kind now lives in the
    DOSSIER group and is documented on the DOSSIER tab, next to the plaintext
    that reveals it. The requirement is unchanged — only the address is — so
    this asserts the requirement and lets the address follow the catalogue.
    """
    day1 = load_day(1)
    dossier = rules_content.build_dossier_text(day1)
    assert "UNSALTED_STORAGE" in dossier, (
        "the DOSSIER tab does not document the one credential violation "
        "reachable without any tool, which is plantable from day 1")
    assert "UNSALTED" in dossier

    # The locked credentials tab must not spoil the kinds that ARE gated...
    locked = rules_content.build_creds_text(day1, set())
    for gated in ("LEAKED_PASSWORD", "CROSS_BREACH_REUSE", "WEAK_CREDENTIAL",
                  "WEAK_ENCRYPTION"):
        assert gated not in locked, (
            f"{gated} is documented on a locked tab before its tool exists")
    # ...and must point at where the un-gated one is, rather than going silent.
    assert "DOSSIER" in locked, (
        "the locked tab neither documents the dossier-tier credential kind nor "
        "says where it went")

    unlocked = rules_content.build_creds_text(load_day(5), {"hashcrack"})
    for kind in ("LEAKED_PASSWORD", "CROSS_BREACH_REUSE",
                 "WEAK_CREDENTIAL", "WEAK_ENCRYPTION"):
        assert kind in unlocked, f"{kind} missing from the unlocked tab"


def test_unsalted_storage_severity_steps_up_when_hashcrack_arrives():
    """Minor until day 3, major from day 3 (Nick, 2026-09-15).

    Before Hashcrack there is no credential economy for the finding to sit in
    and no tool to corroborate it with, so it files as a note. From the day the
    tool lands, the same finding is a real storage failure.

    Asserted on the PLANTED discrepancy as well as the table, because those are
    two different code paths — the generator stamps a severity onto each
    Discrepancy at plant time, and the rules page looks one up per kind. They
    drifting apart is exactly how a violation ends up filed one way on the
    evidence board and another on the rules page.
    """
    from gameengine.core.models import ToolName

    us = DiscrepancyKind.UNSALTED_STORAGE
    assert candidate_gen.severity_for(us, 1) == "minor"
    assert candidate_gen.severity_for(us, 2) == "minor"
    assert candidate_gen.severity_for(us, 3) == "major"
    assert candidate_gen.severity_for(us, 20) == "major"
    # No day in hand -> the settled weight, never the lower one.
    assert candidate_gen.severity_for(us, None) == "major"

    # A kind with no step is unaffected on every day.
    for d in (1, 3, 20, None):
        assert candidate_gen.severity_for(DiscrepancyKind.HOSTILE_CHAT, d) == \
            candidate_gen._SEVERITY_REVEAL[DiscrepancyKind.HOSTILE_CHAT][1]

    # The generator stamps the day's value onto the planted discrepancy.
    seen: dict[int, set[str]] = {}
    for day_number in (1, 8):
        day = load_day(day_number)
        for seed in range(60):
            for slot in range(day.candidate_count):
                c = candidate_gen.generate(seed, day, slot)
                for d in c.truth.discrepancies:
                    if d.kind is us:
                        seen.setdefault(day_number, set()).add(d.severity)
    assert seen.get(1), "guard is inert — no day-1 unsalted candidate"
    assert seen.get(8), "guard is inert — no day-8 unsalted candidate"
    assert seen[1] == {"minor"}, f"day 1 planted {seen[1]}"
    assert seen[8] == {"major"}, f"day 8 planted {seen[8]}"

    # And the rules table prints the day's value, not the settled one.
    early = rules_content.build_dossier_text(load_day(1))
    assert "UNSALTED_STORAGE" in early
    row = next(ln for ln in early.split("\n") if "UNSALTED_STORAGE" in ln)
    assert "minor" in row, f"day-1 rules row reads {row!r}"


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
    assert p.state == p.ENGAGED and p.cursor == block.start_cursor, (
        "the pad cursor does not start in the centre")

    tx, ty = block.align_true
    cx, cy = p.cursor
    p.move_cursor(tx - cx, 0)
    p.move_cursor(0, ty - cy)
    assert p.locked and p.cursor == block.align_true


def test_panel_cursor_is_clamped_to_the_pad():
    cand, block = _first_block(8, tier="medium", pre_revealed=False)
    p = _panel(cand)
    p.open_selector()
    p.apply_result(tools_bridge.apply_window(block, block.tier, _rich_state()))
    assert p.cursor == block.start_cursor
    p.move_cursor(-9999, -9999)
    assert p.cursor == (0, 0)
    p.move_cursor(9999, 9999)
    assert p.cursor == (block.align_span_x, block.align_span_y)


def test_panel_does_not_bill_steps_it_did_not_take():
    """A move that runs into an edge reports zero steps.

    The step counter is what the ⏱ fee is computed from, so counting a clamped
    move would charge the player for a cursor that never moved — holding a
    direction against the wall would quietly drain ⏱ while the screen showed
    nothing happening.
    """
    cand, block = _first_block(8, tier="medium", pre_revealed=False)
    p = _panel(cand)
    p.open_selector()
    p.apply_result(tools_bridge.apply_window(block, block.tier, _rich_state()))
    assert p.steps == 0
    # Walk to a corner first — the cursor now starts in the CENTRE, so no
    # single press is against a wall from there.
    p.move_cursor(-block.align_span_x, -block.align_span_y)
    assert p.cursor == (0, 0)
    at_corner = p.steps
    assert p.move_cursor(-1, 0) == 0, "stepping off the left edge counted"
    assert p.move_cursor(0, -1) == 0, "stepping off the top edge counted"
    assert p.steps == at_corner
    assert p.move_cursor(1, 0) == 1
    assert p.steps == at_corner + 1
    # A move partly clamped counts only the part that happened.
    p.move_cursor(block.align_span_x, 0)          # runs to the right edge
    at_edge = p.steps
    assert p.move_cursor(5, 0) == 0
    assert p.steps == at_edge


def test_unsalted_status_tag_gated_behind_cipher_id_hud():
    """#76: the Hashcrack page's own ⚠ UNSALTED status line was left
    unconditional when #74 gated the same tag on the dossier -- same bug,
    different panel. The block still resolves to plaintext glyphs with no
    upgrade (there is genuinely nothing to crack), only the label naming WHY
    is Cipher ID HUD's call, same as everywhere else it labels a tier.
    """
    cand, _block = _first_block(8, pre_revealed=True)

    p = _panel(cand, label_tier=False)
    status = "\n".join(p._status_lines())
    assert "UNSALTED" not in status, (
        "the UNSALTED tag showed on the Hashcrack page without Cipher ID HUD")
    assert "no window, no dial, nothing to spend" in status, (
        "the plaintext-resolved status line must still explain there's "
        "nothing to buy here, tag or no tag")

    p2 = _panel(cand, label_tier=True)
    status2 = "\n".join(p2._status_lines())
    assert "UNSALTED" in status2, (
        "Cipher ID HUD did not restore the UNSALTED tag on the Hashcrack page")


def test_panel_keeps_an_engaged_block_when_the_player_leaves():
    """Closing decrypt mode must not discard a purchase."""
    cand, block = _first_block(8, tier="medium", pre_revealed=False)
    p = _panel(cand)
    p.open_selector()
    p.apply_result(tools_bridge.apply_window(block, block.tier, _rich_state()))
    cx, cy = p.cursor
    p.move_cursor(3, 1)
    p.close()
    assert p.state == p.ENGAGED and p.cursor == (cx + 3, cy + 1), (
        "walking away reset a window the player already paid for")
    assert p.steps == 4, "leaving decrypt mode reset the step budget"
    p.open_selector()
    assert p.state == p.ENGAGED, "re-entering restarted stage 1 after a buy"


def test_panel_resets_between_candidates():
    day = _unconstrained_day(8)
    p = _panel(candidate_gen.generate(3, day, 0))
    p.open_selector()
    p.apply_result(tools_bridge.apply_window(
        p.block, p.block.tier, _rich_state()))
    p.move_cursor(2, 1)
    p.load_candidate(candidate_gen.generate(3, day, 1), 8)
    assert p.attempts == 0 and p.cursor == p.block.start_cursor
    assert p.steps == 0, (
        "the step budget carried over to the next candidate — one player's "
        "wandering would bill the next credential")
    assert p.state in (p.IDLE, p.LOCKED)


def test_the_hint_box_narrows_both_axes_without_covering_either():
    """The HUD box has to leave real searching to do on X AND on Y.

    The failure this exists for was live: a single flat half-width of 3
    positions was a genuine hint on a 28-wide X axis and covered the WHOLE of
    a 6-tall Y axis. The upgrade still looked correct — the box contained the
    key, it was wider than one square on both axes — while quietly handing the
    player one of the two coordinates outright. Only a proportion test catches
    that.
    """
    checked = 0
    for _cand, block in _crackable_blocks(8, seeds=40):
        checked += 1
        x0, y0, x1, y1 = tools_bridge.hint_band(
            block, {config.UPGRADE_HASH_HIGHLIGHT})
        span_x, span_y = block.align_span_x, block.align_span_y
        assert (x1 - x0) < span_x, (
            f"the hint box spans the whole X axis of the {block.tier} pad")
        assert (y1 - y0) < span_y, (
            f"the hint box spans the whole Y axis of the {block.tier} pad — "
            f"that coordinate is being given away, not hinted at")
        area = (x1 - x0 + 1) * (y1 - y0 + 1)
        pad = (span_x + 1) * (span_y + 1)
        assert 1 < area < pad * 0.45, (
            f"the hint box covers {area}/{pad} of the {block.tier} pad — "
            f"that is the answer, or no help at all")
    assert checked, "guard is inert"


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
    """The pad shows POSITION, never PROGRESS.

    A percentage readout would let the player hill-climb a number instead of
    reading the block, which is the one thing this stage exists for — and with
    two axes it would be even more decisive, since it would turn a search into
    two independent bisections.
    """
    cand, block = _first_block(8, tier="medium", pre_revealed=False)
    p = _panel(cand)
    p.open_selector()
    p.apply_result(tools_bridge.apply_window(block, block.tier, _rich_state()))
    spots = [(0, 0), block.start_cursor, block.align_true]
    for x, y in spots:
        cx, cy = p.cursor
        p.move_cursor(x - cx, y - cy)
        assert "%" not in p._content.text, (
            f"the panel printed a percentage at ({x}, {y}) — that replaces "
            f"reading the block with reading a number")


def test_panel_draws_the_pad_at_full_resolution():
    """One character per pad position, both axes.

    A scaled pad maps several coordinates onto one cell, so the marker stops
    moving on some presses and the hint box covers more ground than it marks.
    Both read as the control lying to the player, and neither would fail any
    other test here.
    """
    cand, block = _first_block(8, tier="medium", pre_revealed=False)
    p = _panel(cand)
    p.open_selector()
    p.apply_result(tools_bridge.apply_window(block, block.tier, _rich_state()))

    def marker_row_col():
        for r, line in enumerate(p._content.text.split("\n")):
            if "◆" in line:
                # Count only pad glyphs before the marker, not markup.
                head = line.split("◆")[0]
                return r, head.count("·") + head.count("▒")
        raise AssertionError("the pad marker is not drawn at all")

    r0, c0 = marker_row_col()
    p.move_cursor(1, 0)
    r1, c1 = marker_row_col()
    assert (r1, c1) == (r0, c0 + 1), (
        "one step along X did not move the marker exactly one cell right")
    p.move_cursor(0, 1)
    r2, c2 = marker_row_col()
    assert (r2, c2) == (r1 + 1, c1), (
        "one step along Y did not move the marker exactly one row down")
