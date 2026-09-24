# BUILD_PLAN — Issues #73, #74, #75, #77 (2026-09)

Scope: the four issues Nick asked to sprint on 2026-09-23 — gating the unsalted-credential
reveal behind Cipher ID HUD (#74), two new Ghostscan auto-confirm upgrades (#75), the Bad
Actor hostile-chat false-positive (#77), and the dossier-tier evidence guard's structural
blind spot (#73).

Branch: `Stego-Shapes` (current HEAD `64e96d9`, working tree clean, up to date with
`origin/Stego-Shapes`). Repo: `hobbes144/HackDox`. Everything below was verified against this
branch's working tree, not against `main` — no diffing against `main` was done as part of this
audit.

**Headline finding: two of the four issues are already fully implemented and tested.** #73 and
#77 both shipped in commit `b215ab2` ("Tweaks and Fixes", 2026-09-15) — nine days before this
issue was filed against them. Their GitHub issue bodies have been rewritten with the evidence
(file:line, test names, a live pytest run) and an open question about whether to close them.
Only #74 and #75 have real implementation work left.

## TL;DR

| Issue | What it really is | Touches DB? | Estimate |
|---|---|---|---|
| #73 | **Already shipped & tested** (`b215ab2`). No build. Decide: close now or on merge? | No | 0 |
| #77 | **Already shipped & tested** (`b215ab2`). No build. One optional named regression test (currently covered only by the general dossier-tier sweep). | No | 0–15 min |
| #74 | Real fix, small: one early-return branch in `_password_markup()` needs to read the `upgrades` param it's already given. Existing test needs updating, one new case added. | No | 20–30 min |
| #75 | Real build: two new upgrades, two new optional params threaded through `_ghostscan_sweep_lines`/`run_ghostscan_shared`, one new test. **Blocked on a design decision** — see Open Questions. | No | 45–60 min |

No database is touched by any of these four issues (this is a local-save Textual TUI, not the
GOATGENE web app — no Supabase involved).

## Dependency callout

- #74 and #75 are independent of each other and of #73/#77. Any order works; #74 is smaller
  and unblocked, so it's the natural one to build first if you approve the sprint today.
- #75 cannot start until you answer the Open Question below (the critical-forum loop's shared
  reveal condition). Everything else in #75's plan is unblocked and could be built up to that
  branch point, but the actual gating logic depends on the answer.
- #73/#77 have no build dependency on anything — they're a documentation/issue-hygiene action
  (rewrite done; closing is your call).

## Per-issue detail

### #73 — Dossier-tier evidence guard blind spot

**Status: shipped and tested, not just written.** The guard exists in
`gameengine/tests/test_engine_foundation.py`:
- `DOSSIER_EVIDENCE` (~line 7191) — kind → (description, predicate) map for every DOSSIER-tier
  kind: `HOSTILE_CHAT`, `AFFILIATION_NOT_STATED`, `DISPOSABLE_EMAIL`, `UNSALTED_STORAGE`.
- `test_every_dossier_tier_kind_has_a_declared_evidence_predicate` — completeness check,
  mirrors the tool-tier guard's own completeness test.
- `test_dossier_tier_evidence_is_present_for_carriers_and_absent_for_others` — sweeps 25 seeds
  × 20 days of real generated candidates, asserts the predicate is true for every carrier and
  false for every non-carrier.

Ran `pytest -k "dossier_tier or hostile"` against `Stego-Shapes` — **5 passed**.

**Not independently re-verified this session:** the AC's own suggested check (revert #51 or
#57's fix in a scratch copy, confirm the guard goes red). The guard's shape makes this very
likely to hold, but it wasn't mechanically re-run.

**No build needed.** Issue rewritten with this evidence; open question posted asking whether
to close it now or on merge to `main`.

### #77 — Bad Actor hostile-chat false positive

**Status: shipped and tested.** Also `b215ab2`:
- `_build_chat()` (`candidate_gen.py`) splits `spec.tone` from evidence: base-pool lines get
  `"hostile_flavor"` instead of `"hostile"` when the archetype's tone is hostile but this
  instance didn't roll `HOSTILE_CHAT`. When it did roll, the base lines carry the real
  `"hostile"` tag too (not just the spliced closing line) — AC #2's "ideally the hostile-toned
  base lines too" is satisfied, not just the minimum bar.
- `ChatPanel._TAG_STYLE`/`_EVIDENCE_TAG`/`_HOSTILE_TAGS` (`typewriter.py`) style both tags
  identically but gate the ⚠ marker on `_EVIDENCE_TAG` alone.
- `post_reaction()` (post-verdict path, AC #4) was checked — it doesn't use the chat tag at all,
  so the conflation doesn't apply there; the code comment explains this is deliberate.

Ran `test_typewriter.py::test_hostile_chat_color_gated_behind_sentiment_scanner` and the same
dossier-tier sweep from #73 (which covers `HOSTILE_CHAT` specifically) — both pass.

**One real gap, not blocking:** no test specifically constructs/finds a non-hostile Bad Actor
and asserts `"hostile_flavor"` + no ⚠ marker. The general sweep proves it at scale but there's
no named regression test pinned to this exact bug report. Optional 15-minute addition if
belt-and-suspenders coverage matters to you.

**No build needed.** Issue rewritten with this evidence; same open question as #73.

### #74 — Gate the unsalted-credential reveal behind Cipher ID HUD

**One correction to the issue's premise, doesn't change the fix:** the "WEAK/MEDIUM/STRONG
chip" the issue says `UPGRADE_CRYPTO_ID` already gates on the dossier no longer exists — the
2026-09-14 cipher-block rework removed it and retiered `WEAK_ENCRYPTION` to HASHCRACK
(`_password_markup`'s own docstring, `shared.py:443`, and `test_dossier_never_labels_the_
encryption_tier` cover this). `UPGRADE_CRYPTO_ID` now only labels the cipher block's algorithm
on the Hashcrack page. The reason to gate the unsalted reveal is consistency with the HUD's
role elsewhere, not "it already governs two chips on this field."

**The wiring already exists — only one branch is missing the check:**
- `_password_markup(dossier, cracked_password, upgrades=None, prefix_len=14)` already takes
  `upgrades`.
- Both call sites (`DossierPanel.render`, `CondensedDossier.render` in `widgets/dossier.py`)
  already pass `upgrades=self.upgrades`, sourced from real `GameState.upgrades`
  (`intake.py:525/535`).
- The `credential_unsalted` early-return (`shared.py:470-478`) is the only branch that ignores
  `upgrades` — it always appends `"⚠ UNSALTED"`.

**Fix:**
```python
if dossier.credential_unsalted:
    head = f"[b #e8f0f8]{dossier.password_plain}[/]"
    if config.UPGRADE_CRYPTO_ID in upgrades:
        head += "  [#ff5470][b]⚠ UNSALTED[/][/]"
    return head, ""
```
`#e8f0f8` is already the same neutral identity-field color used for a recovered password, so
the ungated plaintext won't stand out by color — only the tag needs suppressing.

**Test changes:** `test_unsalted_password_shows_plaintext_directly_no_crack_prompt`
(`test_engine_foundation.py` ~3346) currently asserts `"UNSALTED" in head` with
`upgrades=set()` — that assertion inverts under the fix. Update it, and add a second case with
`upgrades={config.UPGRADE_CRYPTO_ID}` asserting the tag *does* appear — same shape as
`test_dossier_never_labels_the_encryption_tier`'s upgrade-set sweep.

**No open question.** Unambiguous, ready to build.

### #75 — Ghostscan sock-puppet / threat-forum auto-confirm upgrades

Nothing built yet (confirmed via grep — zero matches for the proposed constants/params). Close
mirror of `UPGRADE_BREACH_AUTO`:
- `_ghostscan_sweep_lines()` already takes `show_breach: bool | None = None`, defaulting to
  `show_forums` when not passed (`tools_bridge.py:688`) — the exact shape the issue asks
  `show_sock`/`show_forum_match` to follow.
- `run_ghostscan_shared()` already computes `_breach_auto` from `state.upgrades` and threads it
  through — the template for `_sock_auto`/`_forum_auto`.
- `has_sock`/`has_forum` are already computed per-candidate (lines 484/486).

**Correction to the issue's description of where these kinds render** (this is what the open
question below is about): the issue says SOCK_PUPPET_ACCOUNTS is revealed only in the
advisory-forum loop and THREAT_FORUM_MATCH only in the critical-forum loop. In the actual code,
the **critical-forum loop reveals a row when `has_sock or has_forum`** (either kind, one shared
`show_forums` check) — so a SOCK_PUPPET_ACCOUNTS carrier already lights up the critical loop
too, today, under the paid filter. The advisory loop is SOCK_PUPPET_ACCOUNTS-only, gated to one
specific forum.

## Open Questions

**#1 (blocks #75) — how should the critical-forum loop's shared reveal condition split between
the two new upgrades?**

Since a candidate can carry both kinds, and the critical loop currently reveals per-row for
`has_sock or has_forum` combined, owning only one new upgrade needs a decision for a candidate
that has the *other* kind on that same row.

- **Recommended:** gate per-kind — `show_forums or (has_forum and show_forum_match) or (has_sock and show_sock)`.
  Each upgrade governs its own kind independently (matches AC #2/#3's wording), and keeps
  "own the upgrade" equivalent to "pay for the filter" per-kind, same as Breach Feed Sync
  already does for BREACH_HIT. Side effect: the sock-puppet upgrade ends up revealing a
  SOCK_PUPPET_ACCOUNTS carrier's critical-forum row too, not just the advisory row — broader
  than the issue's AC #2 states, but consistent with what the paid filter already does for that
  kind today.
- **Alternative:** keep the critical loop tied to `show_forum_match` only, and let the
  sock-puppet upgrade affect only the advisory loop, matching the issue's AC #2 literally. This
  means the sock-puppet upgrade under-delivers relative to the paid filter for the exact kind
  it's supposed to auto-confirm (filter reveals both loops for a sock-puppet carrier; the
  upgrade would only reveal one).

Recommendation: the first option. Waiting on your answer before touching `tools_bridge.py`.

**#2 (doesn't block anything) — close #73 and #77 now, or hold until `Stego-Shapes` merges to `main`?**

Both are fully shipped and tested on this branch. No further action needed from me either way —
just say which you'd like.

## Recommended sequencing

Everything here is small — this isn't really a multi-week sequencing problem. Suggested order
in one sitting:

1. **#74** (20–30 min) — unblocked, unambiguous, smallest.
2. **#75** (45–60 min) — once you answer Open Question #1.
3. **#73 / #77** — no build; just tell me whether to close them (and whether you want the one
   optional named regression test for #77).

Each ships as its own commit (one commit per issue, per your usual convention) once you give the
go-ahead on Open Question #1 and confirm branch/commit granularity.

## Cross-cutting risks

- Both #74 and #75 touch files that recent batches (2, 3, 4, 5) have all touched repeatedly
  (`tools_bridge.py`, `shared.py`) — low collision risk here since neither touches
  `candidate_gen.py` or day-content files, but worth being aware `tools_bridge.py` is a
  high-churn file.
- No mobile counterpart exists for HackDox (this is single-repo, TUI-only) — no mobile impact
  to track.
- No DB/migration risk — this repo has no Supabase/database layer.

## Verification plan (once you approve Open Question #1)

- `npx`... n/a (Python project). Run targeted pytest first (`-k` filters shown above), then the
  full suite in chunks per the project's own environment notes (mount is slow; `device_bash` is
  capped at 180s).
- For #74: run the updated `test_unsalted_password_shows_plaintext_directly_no_crack_prompt`
  plus a `-k unsalted` sweep.
- For #75: run the new sock/forum test plus the existing `test_breach_auto_upgrade_confirms_
  hit_on_base_ghostscan_run` to confirm no regression to the breach-only gating.
- Full suite re-run before considering either issue done, matching this repo's own convention
  (baseline is 503 passed / 2 known-failing audio-asset tests as of the 2026-09-14 health check).

## SHIPPED (2026-09-23)

All four issues are resolved on `Stego-Shapes`. Nick's decisions: per-kind
gating for #75 (Open Question #1's recommended option); close #73 and #77
now rather than holding for merge (Open Question #2); skip the optional
named regression test for #77; build #74 and #75 in one sitting, one commit
each.

| Issue | Outcome | Commit |
|---|---|---|
| #73 | No build — already shipped in `b215ab2`. Issue rewritten with the evidence and **closed**. | n/a (closed via comment on GitHub) |
| #77 | No build — already shipped in `b215ab2`. Issue rewritten with the evidence and **closed**. | n/a (closed via comment on GitHub) |
| #74 | Gated the dossier `⚠ UNSALTED` tag behind Cipher ID HUD (`UPGRADE_CRYPTO_ID`). Also repaired a knock-on break this caused in #73's own dossier-tier evidence guard (`_free_surface()` now renders with the upgrade "owned" so the guard can still observe the now-gated tag). | `2b0690d` |
| #75 | Added `UPGRADE_SOCK_AUTO` ("Sockpuppet Tracer") and `UPGRADE_FORUM_AUTO` ("Forum Watch"), each auto-confirming its own kind (`SOCK_PUPPET_ACCOUNTS` / `THREAT_FORUM_MATCH`) on the free base Ghostscan run — per-kind gating per Nick's answer to Open Question #1. Mirrors `UPGRADE_BREACH_AUTO`'s existing shape. | `cbf0508` |

### Smoke-test checklist (once this branch is played, not just tested)

- [ ] Buy Cipher ID HUD, find an UNSALTED_STORAGE candidate, confirm the
      dossier shows the plaintext password either way but the `⚠ UNSALTED`
      tag only appears with the upgrade owned.
- [ ] Buy Sockpuppet Tracer only, find a SOCK_PUPPET_ACCOUNTS candidate, run
      the free base Ghostscan (no filter) — confirm the `[AUTO] Sockpuppet
      Tracer` banner and the critical/advisory forum rows for that candidate
      are revealed without running the filter.
- [ ] With only Sockpuppet Tracer owned, confirm a THREAT_FORUM_MATCH
      candidate's forum row stays blended (unlabeled) on the base run.
- [ ] Buy Forum Watch only and repeat the same check in reverse.
- [ ] Confirm the Bad Actor hostile-chat marker (⚠) never appears on a
      candidate that doesn't carry HOSTILE_CHAT, even when the archetype's
      voice is hostile-toned (this is #77's fix, already shipped — a replay
      sanity check, not new work).

### Verification run (this session)

Full test suite run in chunks against `Stego-Shapes` at `cbf0508`:
`test_engine_foundation.py` (330 passed), `test_cipher_block.py` +
`test_damage_glitch.py` + `test_evidence_board_chips.py` + `test_lab_cli.py`
(127 passed), `test_logwatch_page.py` + `test_logwatch_report.py` +
`test_rules_page.py` + `test_transitions.py` (82 passed),
`test_typewriter.py` + `test_unlock_ui.py` + `test_verdict_reveal.py` +
`test_audio.py` (64 passed). **603 passed, 0 failed** across the full suite.

Not pushed — per convention, Nick pushes.
