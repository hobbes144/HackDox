"""Dockside-voice guards (VOICE_GUIDE.md, 2026-09-24).

HackDox is "hack" + "docks": cybersecurity told as dock work, with the
Overseer presented to players as the Foreman. These tests hold the lines of
that voice that can be checked by machine:

* nothing banned (pirate talk, profanity) in any player-facing string;
* the dockside flavor is spread EVENLY across the candidate chat pools, so the
  idiom itself can never become a tell for an archetype (#78);
* rule text stays precise security language, with no dock idioms in it;
* no player-visible string still says "Overseer".

The glossary below is the machine-checked subset of VOICE_GUIDE.md §1. When
the guide's glossary grows, grow this list with it.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from gameengine import config
from gameengine.core import candidate_gen, overseer
from gameengine.ui.tui import reactions
from gameengine.ui.tui.screens import _narration

_ENGINE = Path(config.__file__).resolve().parent
_DAYS_DIR = _ENGINE / "content" / "days"
_NARRATIVES = _ENGINE / "content" / "narratives" / "overseer.json"

# Dock vocabulary — "is there any dockside flavor in this line?"
DOCK_GLOSSARY = re.compile(
    r"\b(pier|piers|dock|docks|dockside|waterfront|gate|boat|boats|whistle|"
    r"tides?|crate|crates|cargo|manifests?|cranes?|berth|hull|fog|logbook|"
    r"tally|clerk|clerks|long haul|gangway|moorings|shift|shifts|crew|"
    r"afloat|sunk|shed|salt|rust|contraband|harbou?r|lighthouse|"
    r"containers?|stevedores?|longshore\w*|hall)\b",
    re.IGNORECASE,
)

# Idioms that must never appear inside a rule's own text. Narrower than the
# glossary on purpose: "shift", "hold" or "gate" can be honest plain English in
# a precise rule, these cannot.
RULE_TEXT_IDIOMS = re.compile(
    r"\b(pier|dock|docks|boat|boats|whistle|tide|gangway|crate|cargo|"
    r"manifest|berth|hull|longshore\w*|stevedore|foreman|contraband|"
    r"harbou?r|off the boat)\b",
    re.IGNORECASE,
)

# VOICE_GUIDE §8 — not pirates, and PG.
BANNED = re.compile(
    r"\b(arr+|matey|ahoy|avast|shiver me timbers|landlubbers?|yo-ho|"
    r"walk the plank|scallywags?|booty|damn|hell|shit|crap|bastard|ass)\b",
    re.IGNORECASE,
)


# ─── Collectors ──────────────────────────────────────────────────────────────

def _narrative_lines() -> dict[str, str]:
    data = json.loads(_NARRATIVES.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _day_files() -> list[tuple[str, dict]]:
    return [(p.name, json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(_DAYS_DIR.glob("day_*.json"))]


def _day_copy() -> dict[str, str]:
    """Every player-facing prose field in the day files (not rule text)."""
    out: dict[str, str] = {}
    for name, day in _day_files():
        out[f"{name}:title"] = day.get("title", "")
        sheet = day.get("rule_sheet") or {}
        out[f"{name}:summary"] = sheet.get("summary", "")
        for i, note in enumerate(sheet.get("notes", ())):
            out[f"{name}:note{i}"] = note
        for rule in day.get("added_rules", ()):
            out[f"{name}:{rule['id']}:justification"] = rule.get("justification", "")
        for slot, lines in (day.get("forced_chat") or {}).items():
            for i, line in enumerate(lines):
                out[f"{name}:forced_chat[{slot}][{i}]"] = line
    return out


def _rule_texts() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, day in _day_files():
        for rule in (*day.get("rules", ()), *day.get("added_rules", ())):
            out[f"{name}:{rule['id']}"] = rule["text"]
    return out


def _chat_pools() -> dict[str, tuple[str, ...]]:
    return {name: value for name, value in vars(candidate_gen).items()
            if name.startswith("_CHAT_") and isinstance(value, tuple)}


def _reaction_lines() -> dict[str, str]:
    out: dict[str, str] = {}
    for arch, by_verdict in reactions.REACTIONS.items():
        for verdict, variants in by_verdict.items():
            for i, r in enumerate(variants):
                for j, line in enumerate(r.lines):
                    out[f"{arch.value}:{verdict.value}:{i}:{j}"] = line
    for verdict, r in reactions._FALLBACK.items():
        for j, line in enumerate(r.lines):
            out[f"fallback:{verdict.value}:{j}"] = line
    return out


def _narration_lines() -> dict[str, str]:
    out = {f"unlock:{k}": v for k, v in _narration._UNLOCK_LINES.items()}
    for kind, templates in _narration._RULE_CHANGE_PHRASINGS.items():
        for i, t in enumerate(templates):
            out[f"phrasing:{kind}:{i}"] = t
    for kind, templates in _narration._ENDLESS_RULE_CHANGE_PHRASINGS.items():
        for i, t in enumerate(templates):
            out[f"endless_phrasing:{kind}:{i}"] = t
    return out


def _ending_lines() -> dict[str, str]:
    out: dict[str, str] = {}
    for band, ending in overseer.ENDINGS.items():
        out[f"{band}:title"] = ending.title
        for i, para in enumerate(ending.paragraphs):
            out[f"{band}:p{i}"] = para
    return out


def _all_player_prose() -> dict[str, str]:
    out: dict[str, str] = {}
    out.update({f"overseer.json:{k}": v for k, v in _narrative_lines().items()})
    out.update(_day_copy())
    for pool, lines in _chat_pools().items():
        for i, line in enumerate(lines):
            out[f"{pool}[{i}]"] = line
    out.update(_reaction_lines())
    out.update(_narration_lines())
    out.update(_ending_lines())
    return out


def _ui_string_literals() -> dict[str, str]:
    """Every non-docstring string constant in the UI package and the CLI.

    Docstrings are developer prose; every other string literal in these files
    is, or can become, something drawn on screen.
    """
    files = [*sorted((_ENGINE / "ui").rglob("*.py")), _ENGINE / "hackdox.py"]
    out: dict[str, str] = {}
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docstrings.add(id(body[0].value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                # Key on line AND column: two literals on one line (a label and its
                # `classes=` argument) must not overwrite each other — that
                # collision once hid a leftover "Overseer:" speaker label.
                out[f"{path.relative_to(_ENGINE)}:{node.lineno}:{node.col_offset}"] = node.value
    return out


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_collectors_are_not_empty():
    """Guard the guards: an empty collector would make every test below
    pass vacuously."""
    assert len(_narrative_lines()) > 150
    assert len(_day_copy()) > 40
    assert len(_rule_texts()) > 25
    assert len(_chat_pools()) >= 10
    assert len(_reaction_lines()) > 40
    assert len(_ending_lines()) == 12
    assert len(_ui_string_literals()) > 500


def test_no_banned_words_in_player_prose():
    hits = {k: BANNED.search(v).group(0)
            for k, v in _all_player_prose().items() if BANNED.search(v)}
    assert not hits, f"banned words in player-facing copy: {hits}"


def test_rule_text_carries_no_dock_idioms():
    """Rule text is the precise layer the player acts on (VOICE_GUIDE §2).
    The flavor lives in summaries, notes and justifications — never here."""
    hits = {k: RULE_TEXT_IDIOMS.search(v).group(0)
            for k, v in _rule_texts().items() if RULE_TEXT_IDIOMS.search(v)}
    assert not hits, f"dock idioms inside rule text: {hits}"


def _pool_density(lines: tuple[str, ...]) -> float:
    return sum(1 for ln in lines if DOCK_GLOSSARY.search(ln)) / len(lines)


# Allowed spread between the saltiest and plainest chat pool. Pools are 3-5
# lines, so one line is worth 0.20-0.33 of density; 0.20 lets a 4-line pool
# sit at 1/4 beside a 5-line pool at 2/5 without letting any pool run
# noticeably saltier than the rest.
CHAT_DENSITY_TOLERANCE = 0.20


def test_dock_flavor_is_spread_evenly_across_chat_pools():
    """#78 broke the link between an archetype's VOICE and its ground truth.
    If one pool talked much more like a dockworker than another, the idiom
    itself would become the tell. Every pool gets some flavor, and none gets
    noticeably more than the others."""
    densities = {name: _pool_density(lines) for name, lines in _chat_pools().items()}
    unflavored = [name for name, d in densities.items() if d == 0]
    assert not unflavored, f"chat pools with no dockside flavor at all: {unflavored}"
    spread = max(densities.values()) - min(densities.values())
    assert spread <= CHAT_DENSITY_TOLERANCE, (
        f"dock-phrase density varies too much across chat pools "
        f"(spread {spread:.2f} > {CHAT_DENSITY_TOLERANCE}): "
        f"{ {k: round(v, 2) for k, v in densities.items()} }")


def test_foreman_dialogue_carries_the_voice_at_the_agreed_rate():
    """VOICE_GUIDE §2: about one dock phrase every two or three lines. Checked
    as a floor across the whole file, not per line — a line can be plain."""
    lines = list(_narrative_lines().values())
    rate = sum(1 for ln in lines if DOCK_GLOSSARY.search(ln)) / len(lines)
    assert rate >= 0.30, f"only {rate:.0%} of the Foreman's lines carry any dockside flavor"


def test_no_player_visible_string_still_says_overseer():
    """The Overseer is the Foreman to players (VOICE_GUIDE §6). Code
    identifiers keep the old name; nothing a player can read does."""
    prose = {k: v for k, v in _all_player_prose().items() if "Overseer" in v}
    assert not prose, f"player-facing copy still says Overseer: {prose}"
    # A bare identifier ("OverseerPanel" in an __all__ list) is code, not copy.
    ui = {k: v for k, v in _ui_string_literals().items()
          if "Overseer" in v and not v.isidentifier()}
    assert not ui, f"UI string literals still say Overseer: {ui}"


def test_the_foreman_is_never_it():
    """The script writes the Foreman as she/her (day 17, "What This Made of
    Her"). The endings used to call the Overseer "it"; don't let that back."""
    for key, text in _ending_lines().items():
        assert not re.search(r"\bForeman\b[^.]*\bit (didn't|needed|never)\b", text), key


# ─── Word banks (VOICE_GUIDE §5) ─────────────────────────────────────────────

# Real institutions the banks used to carry. Real consumer mail providers,
# breach corpora and platforms stay — they're the "every tool is real" layer —
# but a candidate's claimed EMPLOYER is always an in-world organisation.
_REAL_INSTITUTIONS = re.compile(
    r"\b(mit|csail|google|stanford|oxford|deepmind|carnegie|cmu|eth zurich|"
    r"cloudflare|mozilla|microsoft|apache)\b", re.IGNORECASE)


def test_claimed_affiliations_are_all_in_world_organisations():
    banks = (*candidate_gen.AFFILIATIONS_ELITE, *candidate_gen.AFFILIATIONS_LEGIT,
             *candidate_gen.AFFILIATIONS_THIN, *candidate_gen._ELITE_ORG_HANDLE)
    real = [a for a in banks if _REAL_INSTITUTIONS.search(a)]
    assert not real, f"real-world institutions in the affiliation banks: {real}"
    day_orgs = [a for k, a in _day_copy().items() if _REAL_INSTITUTIONS.search(a)]
    assert not day_orgs, f"real-world institutions named in day copy: {day_orgs}"


def test_exactly_the_elite_orgs_are_recognised_as_trusted():
    """The #56 guarantee ("a trusted org can't be faked") is about exactly the
    elite bank. It used to be a hand-kept keyword list ("mit", "stanford", …)
    that would have silently stopped matching when the orgs were renamed."""
    from gameengine.core import tools_bridge
    for org in candidate_gen.AFFILIATIONS_ELITE:
        assert tools_bridge.classify_affiliation(org) == "approved", org
    for org in (*candidate_gen.AFFILIATIONS_LEGIT, *candidate_gen.AFFILIATIONS_THIN):
        assert tools_bridge.classify_affiliation(org) != "approved", org


def test_every_elite_org_can_be_typosquatted():
    import random
    for org in candidate_gen.AFFILIATIONS_ELITE:
        handle = candidate_gen._ELITE_ORG_HANDLE[org]
        assert len(handle) >= 6, f"{org}'s handle {handle!r} is too short to squat"
        squat = candidate_gen._typosquat(random.Random(org), handle)
        assert squat != handle, f"no typosquat possible for {handle!r}"


def test_domain_categories_never_share_a_root():
    """VOICE_GUIDE §5: the NAME of an in-world domain tells the player its
    category. A root used in two categories (tidewater.net trusted beside a
    tidewater throwaway) would teach the wrong thing."""
    def roots(domains):
        return {d.split(".")[0] for d in domains}
    t = roots(candidate_gen.DOMAINS_TRUSTED)
    p = roots(candidate_gen.DOMAINS_PRIVACY)
    d = roots(candidate_gen.DOMAINS_DISPOSABLE)
    assert not (t & p or t & d or p & d), (t & p, t & d, p & d)
