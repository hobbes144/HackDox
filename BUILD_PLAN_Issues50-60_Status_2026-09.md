# Status audit: issues #50, #51, #53, #54, #56, #57, #58, #59, #60

Date: 2026-09-14. Base checked: `main` @ `f6d9e5f` (merge of PR #66, Sep 11 2026).
Every finding below is grounded in a live GitHub compare/commit page or a grep against the
staged working copy of the file in question — not inferred from commit messages alone.

## Headline: all nine are implemented and already merged to `main`. None of this is a build plan for new work — it's a housekeeping gap.

Project memory (`planning_sprint.md`, `playtest_fixes.md`) describes these as shipped on
branch `batch-2-difficulty-curve-replayablity`, and repeatedly flags that branch as **"not
pushed."** That note is stale. `github.com/hobbes144/HackDox/compare/main...<sha>` returns
*"main is up to date with all commits from `<sha>`"* for all four Batch-3 commits not already
visible in `main`'s own commit log:

| Issue | Commit | Compare vs `main` |
|---|---|---|
| #50 | `a06309a` | main is up to date — merged |
| #51 | `253d77b` | main is up to date — merged |
| #53 | `242a88d` | main is up to date — merged |
| #54 | `9a63146` | main is up to date — merged |
| #56 | `54b3200` | visible directly in `main`'s commit log (Aug 17) |
| #57 | `6820956` | visible directly in `main`'s commit log (Aug 17) |
| #58 | `6c71752` | visible directly in `main`'s commit log (Aug 17) |
| #59 | `7d2f19f` | visible directly in `main`'s commit log (Aug 17) |
| #60 | `7fb43b3` | visible directly in `main`'s commit log (Aug 17) |

All nine issues are still showing **Open / In progress** on the GitHub board despite this —
that's the actual gap. Nobody closed them out after the merge.

## Per-issue: what shipped, and what I verified directly against the code

### #50 — Separation of General Rules from Dossier Rules
Shipped comment on the issue documents the split (`build_rules_text` 226 lines → Rules 123 /
Dossier 57 / OSINT 71 / Creds 55 / Logs 72 / Stego 55) plus tab-follows-page and per-tab scroll
persistence. **Verified:** `gameengine/ui/tui/rules_content.py:888` defines `build_dossier_text`
— the new tab exists in the working tree, not just in the commit message.

### #51 — Relocate Missing Public Profile (sub-issue of #50)
`MISSING_PUBLIC_PROFILE` retiered Dossier → Ghostscan. **Verified:**
`gameengine/content/days/day_01.json:113-115` — `rule_missing_public_profile` predicate
`has_discrepancy:missing_public_profile`, present and wired to a real rule.

### #53 — Typosquat Handle Violation Rework
Handle now actually typosquats a listed affiliation (Levenshtein 1-2), demoted to minor,
Sneaky Bugger gained a minor budget slot. **Verified:** `candidate_gen.py:803` `_ELITE_ORG_HANDLE`
dict, `:1242` `handle_squats` field, `:563` `TYPOSQUAT_HANDLE → (GHOSTSCAN, "minor")`, and
`day_01.json` now carries `rule_typosquat_handle` (line 173-175) — the gap Nick's own shipped-log
comment flagged as *not yet fixed* ("day_01.json has no rule_typosquat at all") is closed by #60's
later rule pass, confirmed in the same file.

### #54 — Stegotool Tweak (clumped carriers, buffered hint tint)
Base tier tints nothing; Spectral Lens tints a buffered region. **Verified:**
`tools_bridge.py:2454-2604` — `hint_region` computed from `config.STEGO_HINT_BUFFER`, separate
from the exact `zone`.

### #56 — Standardize the affiliation violations
Four distinct kinds, four distinct tiers. **Verified:** `candidate_gen.py:539-548` —
`AFFILIATION_NOT_STATED → (DOSSIER, minor)`, `AFFILIATION_UNLISTED → (GHOSTSCAN, minor)`,
`AFFILIATION_MISMATCH → (GHOSTSCAN, major)`. All three distinctly named and tiered, matching the
issue's acceptance criteria table exactly.

### #57 — Disposable-domain lists drifted
**Verified:** `candidate_gen.py:137-142` — `DOMAINS_DISPOSABLE` now includes `tempmail.org` and
`sharklasers.com`. `tools_bridge.py:28,196` — `_GS_SUSPICIOUS_DOMAINS = frozenset(_DISPOSABLE_DOMAINS)`,
imported directly from `candidate_gen`. The drift is now structurally impossible, per the issue's
own acceptance criteria ("derive one list from the other").

### #58 — Privacy-provider hint told the player to flag a non-existent kind
**Verified:** `tools_bridge.py:377` — the old "privacy provider — flag if other issues present"
string survives only as an explanatory code comment; the live string was reworded.

### #59 — Weak Encryption vs Weak Credential overlap
**Verified:** `candidate_gen.py:591-635` — `WEAK_ENCRYPTION` is explicitly excluded from
`_CREDENTIAL_ARTIFACT_KINDS` (comment: "deliberately left: it is a [derived] artifact fact, not a
choice"), and `:1359-1383` derive it after hash selection rather than rolling it — exactly the
orthogonality the issue asked for.

### #60 — Ground truth diverges from the ruleset (13 unruled violations)
**Verified:** `day_01.json` now contains rules for `missing_public_profile`,
`affiliation_mismatch`, `disposable_email`, `typosquat_handle`, `after_hours_access` (spot-checked
5 of the 13; all present at lines 113-181) — matching the issue's proposed rule table.

## What's genuinely still open (not part of these nine, but adjacent)

1. **The dossier-tier evidence guard blind spot.** Both #51's and #57's own shipped-log comments
   name this explicitly: the automated guard in `test_engine_foundation.py` that catches
   "planted-but-unobservable" violations deliberately skips DOSSIER-tier kinds (their evidence is
   "structural," so the guard can't check it generically) — and that blind spot is *how* #51 and
   #57 slipped through undetected in the first place. Nobody has gone back to close it with "a
   different test shape," per both comments. This isn't a regression in #50-60; it's a
   process gap the two fixes exposed but didn't resolve. Worth its own tracked issue so a future
   dossier-tier mistiering doesn't repeat the same silent failure.
2. **Project memory is stale beyond just "pushed" status.** `batch5_plan.md` (dated 2026-09-12)
   says Batch 5 (#37/#39-#42) "Stage 5 never started." But `main`'s branch list shows a `Campaign`
   branch 17 commits ahead of `main`, and issue #60's GitHub timeline shows a later commit
   (`fca6e88`, "Author day 12: the scripted White Hat encounter (#41, Phase 4)") referencing it —
   meaning Batch 5 work has continued past what memory records, on a differently-named branch.
   That's outside the scope of what was asked here, but the discrepancy is worth knowing about
   before trusting `batch5_plan.md`'s "not built" framing for anything else.

## Recommendation

There is no code to write for #50, #51, #53, #54, #56, #57, #58, #59, #60 — they're done and
merged. The only grouping that makes sense is administrative:

- **Group A — close out now:** all nine issues, one comment each (or one shared comment
  cross-posted) pointing at the verified commit + compare-to-main evidence above, then move the
  board column to Done.
- **Group B — new issue, not urgent:** track the dossier-tier evidence-guard gap as its own
  ticket so it doesn't get rediscovered a third time.
- **Group C — separate from this ask, flag only:** reconcile `batch5_plan.md` against the
  `Campaign` branch's actual state before planning any further Batch 5 work.
