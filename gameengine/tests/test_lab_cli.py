"""Tests for the `hackdox lab` controlled-generation command (issue #52).

Driven through typer's CliRunner so the tests exercise the real command,
including argument parsing and the exit codes — a lab tool that silently
generates the wrong thing is worse than no lab tool.
"""

from __future__ import annotations

from typer.testing import CliRunner

from gameengine import config
from gameengine.core import candidate_gen
from gameengine.core.models import Archetype, DiscrepancyKind, ToolName
from gameengine.hackdox import _lab_day, app

runner = CliRunner()


# ─── The constrained Day (#52) ───────────────────────────────────────────────


def test_lab_day_pins_archetypes_and_whitelists_violations():
    day = _lab_day(5, ["sneaky_bugger", "clumsy_cutie"],
                   ["typosquat_handle"], count=2)
    assert day.number == 5
    assert day.candidate_count == 2
    assert day.forced_includes == {0: Archetype.SNEAKY_BUGGER,
                                   1: Archetype.CLUMSY_CUTIE}
    assert day.allowed_violations == (DiscrepancyKind.TYPOSQUAT_HANDLE,)
    # The pinned archetypes must exist in the mix or _pick_archetype_for_slot
    # cannot account for them.
    assert day.archetype_mix[Archetype.SNEAKY_BUGGER] >= 1


def test_lab_day_honours_the_requested_constraints_in_generation():
    day = _lab_day(5, ["sneaky_bugger"], ["typosquat_handle"], count=1)
    found = False
    for seed in range(200):
        c = candidate_gen.generate(seed, day, 0)
        assert c.archetype == Archetype.SNEAKY_BUGGER, "forced slot not honoured"
        kinds = {d.kind for d in c.truth.discrepancies}
        # The whitelist intersects with the tier gate, so a candidate may carry
        # nothing — but never a kind outside the whitelist.
        assert kinds <= {DiscrepancyKind.TYPOSQUAT_HANDLE}, kinds
        if DiscrepancyKind.TYPOSQUAT_HANDLE in kinds:
            found = True
    assert found, "the whitelisted violation never appeared in 200 seeds"


# ─── The command (#52) ───────────────────────────────────────────────────────


def test_lab_reports_a_reproducible_seed():
    r = runner.invoke(app, ["lab", "-a", "sneaky_bugger",
                            "-v", "typosquat_handle", "--day", "5"])
    assert r.exit_code == 0, r.output
    assert "reproduce with --seed" in r.output, r.output
    assert "typosquat_handle" in r.output


def test_lab_is_deterministic_for_a_fixed_seed():
    args = ["lab", "-a", "clumsy_cutie", "--tool", "hashcrack",
            "--day", "4", "--seed", "7"]
    a = runner.invoke(app, args)
    b = runner.invoke(app, args)
    assert a.exit_code == b.exit_code == 0
    assert a.output == b.output, "same seed must reproduce the case exactly"


def test_lab_tool_flag_selects_that_tools_violations_without_listing_them():
    """--tool alone should mean 'any violation this tool reveals', so the caller
    doesn't have to remember the kind-to-tool mapping."""
    r = runner.invoke(app, ["lab", "-a", "sneaky_bugger",
                            "--tool", "stegotool", "--day", "6"])
    assert r.exit_code == 0, r.output
    stego_kinds = [k.value for k, (t, _s) in candidate_gen._SEVERITY_REVEAL.items()
                   if t == ToolName.STEGOTOOL]
    assert any(k in r.output for k in stego_kinds), r.output
    assert "stegotool — filtered" in r.output


def test_lab_shows_ground_truth_beside_the_tools_real_output():
    """The pairing is the point: a violation that is planted but invisible — or
    contradicted — is only obvious when both are on screen together."""
    r = runner.invoke(app, ["lab", "-a", "sneaky_bugger",
                            "-v", "typosquat_handle", "--day", "5"])
    assert r.exit_code == 0
    assert "Correct verdict:" in r.output      # ground truth
    assert "Revealed by" in r.output           # the discrepancy table
    assert "ghostscan — filtered" in r.output  # what the player would see


def test_lab_rejects_bad_names_with_a_useful_message():
    r = runner.invoke(app, ["lab", "-a", "not_an_archetype"])
    assert r.exit_code == 1
    assert "Unknown archetype" in r.output
    assert "sneaky_bugger" in r.output, "should list the valid values"

    r = runner.invoke(app, ["lab", "--tool", "nosuchtool"])
    assert r.exit_code == 1
    assert "Unknown tool" in r.output


def test_lab_explains_an_unsatisfiable_constraint():
    """Asking for a stego violation on Day 1 cannot work — stegotool is gated
    until day 5 by #31. The failure should name that, not just shrug."""
    r = runner.invoke(app, ["lab", "-a", "sneaky_bugger",
                            "-v", "covert_c2_channel", "--day", "1"])
    assert r.exit_code == 1
    assert "No seed" in r.output
    assert "tier gate" in r.output or "unlock day" in r.output, r.output


def test_lab_day_uses_the_real_synthesizer():
    """Built on content_loader.synthesize_day (#17), not a parallel Day builder —
    a lab that doesn't exercise the same path as play can show a case that works
    in the lab and breaks in a shift."""
    day = _lab_day(12, ["sneaky_bugger"], [], count=2)
    assert day.difficulty_band == config.difficulty_band_for_day(12)
    assert day.rules, "synthesized day must carry a ruleset"
