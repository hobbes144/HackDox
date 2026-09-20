"""Logwatch Activity Report (2026-09-19 overhaul) — engine invariants.

The report is the Logwatch page's free tier. These tests pin the reveal-tier
table from core/logwatch_report.py's docstring against ground truth across the
real campaign days, and pin the rule that makes the table trustworthy: the
report is computed from the log alone.
"""

from __future__ import annotations

import copy
from functools import lru_cache

import pytest

from gameengine import config
from gameengine.core import candidate_gen, tools_bridge
from gameengine.core.content_loader import load_day
from gameengine.core.logwatch_report import (SENSITIVE_PATHS,
                                             build_logwatch_report, in_shift)
from gameengine.core.models import DiscrepancyKind as K

# Logwatch unlocks on day 4; sample every authored day from there.
_DAYS = tuple(range(config.TOOL_UNLOCK_DAY["logwatch"], 21))
_SEEDS = (0, 1, 2)


@lru_cache(maxsize=None)
def _sample():
    """[(candidate, kinds, report, day_log)] across days × seeds × slots."""
    out = []
    for dn in _DAYS:
        day = load_day(dn)
        for seed in _SEEDS:
            log = tools_bridge.generate_day_log(seed, day)
            for slot in range(day.candidate_count):
                c = candidate_gen.generate(seed, day, slot)
                kinds = frozenset(d.kind for d in c.truth.discrepancies)
                out.append((c, kinds, build_logwatch_report(log, c), log))
    return tuple(out)


def _carriers(kind):
    return [(c, r) for c, ks, r, _ in _sample() if kind in ks]


def _all():
    return [(c, ks, r) for c, ks, r, _ in _sample()]


# ── The reveal-tier table ───────────────────────────────────────────────────

def test_attack_alert_fires_exactly_for_brute_force_and_stuffing():
    """Detected but unclassified: the alert is the SAME for both attacks."""
    attacks = {K.BRUTE_FORCE_IN_LOG, K.CREDENTIAL_STUFFING}
    for c, ks, r in _all():
        assert r.burst_alert == bool(ks & attacks), (
            f"{c.archetype.value}: alert={r.burst_alert} peak={r.peak_burst} "
            f"kinds={sorted(k.name for k in ks)}")
    assert _carriers(K.BRUTE_FORCE_IN_LOG) and _carriers(K.CREDENTIAL_STUFFING)


def test_brute_force_and_stuffing_look_alike_on_the_report():
    """Both show a hostile origin in a resolvable city — neither prefix nor
    'unresolved' may give the attack type away before the log is opened."""
    city_names = {city for _p, city in tools_bridge._LW_CITIES}
    for kind in (K.BRUTE_FORCE_IN_LOG, K.CREDENTIAL_STUFFING):
        for c, r in _carriers(kind):
            hostile = [o for o in r.origins if o.hostile]
            assert hostile, f"{kind.name}: no hostile origin on {c.id}"
            assert all(o.place in city_names for o in hostile), (
                f"{kind.name}: hostile origin place {[o.place for o in hostile]}")


def test_low_and_slow_stays_under_the_alert_but_shows_failures():
    carriers = _carriers(K.LOW_AND_SLOW)
    assert carriers, "no LOW_AND_SLOW carriers sampled — guard is inert"
    for c, r in carriers:
        if not r.burst_alert:    # (a co-planted brute/stuff may still alert)
            assert r.peak_burst < config.LW_BURST_ALERT
        assert r.out_of_range("failures"), (
            f"{c.id}: low-and-slow should push the failures bar out of range "
            f"({r.linked_failures} linked failures)")


def test_claimed_ip_mismatch_iff_claimed_ip_never_seen():
    for c, ks, r in _all():
        assert (not r.claimed_ip_seen) == (K.CLAIMED_IP_MISMATCH in ks), c.id
    assert _carriers(K.CLAIMED_IP_MISMATCH)


def test_impossible_travel_iff_travel_pair():
    for c, ks, r in _all():
        assert bool(r.travel) == (K.IMPOSSIBLE_TRAVEL in ks), (
            c.id, [(t.place_a, t.place_b, t.minutes) for t in r.travel])
    for c, r in _carriers(K.IMPOSSIBLE_TRAVEL):
        assert all(t.minutes * 60 <= config.LW_TRAVEL_REPORT_WINDOW for t in r.travel)


def test_insider_shows_as_counts_only():
    for c, ks, r in _all():
        insider = K.INSIDER_BEHAVIOR in ks
        assert (r.privileged > 0) == insider, c.id
        assert (r.files_sensitive > 0) == insider, c.id
    assert _carriers(K.INSIDER_BEHAVIOR)


def test_off_hours_iff_after_hours_or_insider():
    """Honest daytime activity must stay inside the shift, or every clean
    candidate reads as an after-hours worker."""
    for c, ks, r in _all():
        expected = bool(ks & {K.AFTER_HOURS_ACCESS, K.INSIDER_BEHAVIOR})
        assert (r.off_hours > 0) == expected, (c.id, r.off_hours,
                                               sorted(k.name for k in ks))


# ── The report is computed from the log ─────────────────────────────────────

def test_report_ignores_engine_only_row_fields():
    """Blank every engine-only verdict field; the report must not change."""
    for c, _ks, r, log in _sample()[::7]:
        stripped = copy.deepcopy(log)
        for e in stripped:
            e.is_suspicious = False
            e.violation_kind = None
        assert build_logwatch_report(stripped, c) == r, c.id


def test_report_sensitive_paths_match_generator():
    assert SENSITIVE_PATHS == frozenset(tools_bridge._LW_SENSITIVE_PATHS)


# ── Honest noise & the breach-row removal ───────────────────────────────────

def test_benign_typo_exists_and_never_reads_as_an_attack():
    typos = 0
    for c, ks, r, log in _sample():
        own_typos = [e for e in log if e.owner_id == c.id
                     and e.violation_kind == "benign_typo"]
        typos += len(own_typos)
        assert len(own_typos) <= 1
        for e in own_typos:
            assert in_shift(e.ts_secs), e.ts_str
    assert typos, "no benign typos generated — honest noise is inert"


def test_logwatch_carries_no_breach_rows():
    for _c, _ks, _r, log in _sample()[:: max(1, len(_sample()) // 40)]:
        assert not any(e.event == "BREACH_MATCH" for e in log)


def test_profile_header_fields_are_populated():
    for c, _ks, r in _all()[:50]:
        assert r.location in candidate_gen.OFFICE_CITIES
        assert r.role and r.role != "Unlisted"
        assert r.claimed_ip == c.dossier.claimed_ip


def test_office_cities_never_collide_with_attack_cities():
    attack = {city for _p, city in tools_bridge._LW_CITIES}
    assert not attack & set(candidate_gen.OFFICE_CITIES)


@pytest.mark.parametrize("key", sorted(config.LW_PROFILE_METRICS))
def test_profile_metric_config_is_sane(key):
    label, ceiling, scale = config.LW_PROFILE_METRICS[key]
    assert label and 0 <= ceiling < scale


# ── Rendering (P2) ──────────────────────────────────────────────────────────

_LW_KINDS = (K.BRUTE_FORCE_IN_LOG, K.CREDENTIAL_STUFFING, K.LOW_AND_SLOW,
             K.IMPOSSIBLE_TRAVEL, K.INSIDER_BEHAVIOR, K.AFTER_HOURS_ACCESS,
             K.CLAIMED_IP_MISMATCH)
# Words that would classify a violation before the filter is bought.
_NAMING = tuple(k.name for k in _LW_KINDS) + (
    "brute", "stuffing", "insider", "impossible", "low-and-slow", "low and slow",
    "▲ ")


def _state(upgrades=()):
    from gameengine.core.models import GameState
    s = GameState(seed=0, current_day=20, compute_hours=10_000)
    s.upgrades = set(upgrades)
    return s


def test_free_and_base_tiers_never_name_a_violation():
    from gameengine.core.logwatch_report import render_report
    for c, _ks, r, log in _sample()[::3]:
        outs = [render_report(r, log_state="sealed"),
                render_report(r, log_state="open", hud=True),
                tools_bridge.get_logwatch_log_lines(
                    log, c, _state({config.UPGRADE_LOG_HIGHLIGHT}))]
        for lines in outs:
            text = "\n".join(lines).lower()
            for w in _NAMING:
                assert w.lower() not in text, (c.id, w)


def test_filter_names_every_logwatch_kind_the_candidate_carries():
    for c, ks, _r, log in _sample():
        owned = ks & set(_LW_KINDS)
        if not owned:
            continue
        res = tools_bridge.run_logwatch_filtered_shared(log, c, _state())
        text = "\n".join(res.report_lines)
        for k in owned:
            assert f"▲ {k.name}" in text, (c.id, k.name)


def test_every_rendered_line_is_valid_markup():
    from rich.text import Text
    for c, _ks, _r, log in _sample()[::5]:
        st = _state({config.UPGRADE_LOG_HIGHLIGHT})
        for lines in (tools_bridge.get_logwatch_shared(log, c, state=st),
                      tools_bridge.run_logwatch_shared(log, c, st).report_lines,
                      tools_bridge.run_logwatch_shared(log, c, st).raw_lines,
                      tools_bridge.run_logwatch_filtered_shared(log, c, st).report_lines,
                      tools_bridge.run_logwatch_filtered_shared(log, c, st).raw_lines):
            for ln in lines:
                Text.from_markup(ln)   # raises MarkupError on bad markup


def test_report_fits_its_column():
    """Every report line fits LW_REPORT_WIDTH (+ the 2-char indent) except the
    free-text footers/confirmations, which may wrap."""
    from rich.text import Text
    from gameengine.core.logwatch_report import render_report
    limit = config.LW_REPORT_WIDTH + 2
    for _c, _ks, r, _log in _sample()[::4]:
        lines = render_report(r, log_state="sealed", hud=True)
        body = lines[:-1]                  # the footer hint may wrap
        for ln in body:
            assert Text.from_markup(ln).cell_len <= limit, ln


def test_logwatch_tunables_are_coherent():
    """Plain-English guards for config retunes (see the TUNING CHEAT-SHEET)."""
    assert config.LW_BURST_ALERT <= config.LW_BRUTE_BURST_SIZE[0], (
        "LW_BURST_ALERT is above the smallest brute-force burst — some brute "
        "force candidates would never trip the report's alert")
    assert config.LW_BURST_ALERT <= config.LW_STUFFING_SPRAY_SIZE, (
        "LW_BURST_ALERT is above the credential-stuffing spray size — stuffing "
        "would never trip the report's alert")
    assert config.LW_BURST_WINDOW < config.LW_SLOW_GAP[0], (
        "LW_BURST_WINDOW is wider than the low-and-slow gap — low-and-slow "
        "could trip the alert it is designed to stay under")
    assert config.LW_SHIFT_START <= config.LW_WORKDAY_WINDOW[0], (
        "the workday starts before the shift — honest logins read as off-hours")
    assert config.LW_HOSTILE_ORIGIN_FAILS >= 2, (
        "a single benign typo would mark the user's own origin hostile")
    assert set(config.LW_PROFILE_METRICS) == {
        "logins", "failures", "origins", "files", "privileged", "off_hours"}
