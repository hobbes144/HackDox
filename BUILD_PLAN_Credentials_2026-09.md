# BUILD PLAN — credential model, evidence honesty, pad polish

**Scope:** GitHub issues #77, #78, #73 + six direct asks from Nick (2026-09-15)
**Repo:** `hobbes144/HackDox` · working copy `A:\Personal\HackDox`
**Base:** the current cipher-block branch, HEAD = the round-3 alignment-pad work
**Status:** every claim below was verified against the working tree and measured
by generating real candidates. Numbers are from 400 seeds × days 1–20 =
**72,400 candidates** unless stated otherwise.

---

## TL;DR

| # | What it really is | Touches generator? | Size |
|---|---|---|---|
| A | **#78** dossier image giveaway — perfect 1.000 correlation, zero decoys | yes, 1 line | XS |
| B | **#77** hostile chat vs ground truth — 58.1% false positives | yes | S |
| C | Ghostscan BREACH_HIT under CROSS_BREACH_REUSE — absent 75.7% of the time | yes | S |
| D | UNSALTED_STORAGE → DOSSIER group + day-scaled severity | yes | M |
| E | WEAK_CREDENTIAL → `cred-storage` cluster | no | XS |
| F | **Unsalted vs weak-encryption coherence** — 100% co-occurrence, contradictory | yes | M |
| G | **#73** dossier-tier evidence guard blind spot | test only | M |
| H | Pad: centre start + distance meter | no | S |

**A, B and E are contained.** C, D, F are genuine model changes and interact.
G is a test-infrastructure task whose value goes *up* after D lands.

### Dependency order

```
F (what unsalted means)  ─┬─►  D (group + severity)  ─►  E  ─►  G
                          └─►  A, B, C, H   (independent, ship first)
```

**F gates D.** If unsalted means "plaintext, no algorithm", WEAK_ENCRYPTION must
be suppressed on those candidates — which changes what D's cluster move is even
moving. Doing D first means doing it twice.

**G must land after D,** not before: D makes UNSALTED_STORAGE a genuinely
DOSSIER-group *and* DOSSIER-tier kind, which is exactly the shape #73's guard is
meant to cover. Written first, the guard would be written against a model that
is about to change.

---

## Phase A — #78, the dossier image giveaway

**Symptom (Nick, via the issue):** "the mere presence/absence of an image field
is a free giveaway that a candidate carries a stego payload, without ever having
to run Stegotool."

**Root cause** — `gameengine/core/candidate_gen.py:1321-1328`:

```python
_has_st = any(d.kind in (STEGO_PAYLOAD_PRESENT, COVERT_C2_CHANNEL,
                         ENCRYPTED_PAYLOAD) for d in discrepancies)
submitted_image_path = _rng_st.choice(_st_images) if _has_st else None
```

`submitted_image_path` is derived **from** `discrepancies`, so a non-`None` value
is a literal boolean readout of "carries a stego violation", rendered free on
`DossierPanel` (`widgets/dossier.py:37,54`) and on `CondensedDossier`
(`:87,101`) — which is on screen on *every* tool page.

**Measured:** 7,541 candidates have an image; 7,541 carry a stego violation;
**correlation 1.000, zero decoys in either direction across 72,400 samples.**

The file's own design comment at `candidate_gen.py:640-646` already asserts the
opposite invariant — "Every candidate submits exactly ONE image" — so the code
contradicts its own documented intent. 89.6% of candidates submit zero.

**Implementation**
1. Drop the `if _has_st else None` gate; always choose a filename.
2. Grow `_st_images` beyond its four entries — with every candidate drawing from
   it, a 4-name pool repeats ~1.5× per 6-slot roster and the *filename* becomes
   the new pattern. Target ≥ 16 names of mixed shape.
3. No renderer change needed: `tools_bridge.py:1780` and `:2211` already fall
   back to `"image.png"`, and `build_stego_image` computes suspicion from ground
   truth (`:1772-1778`), never from the filename.
4. Fix the stale comment at `:640-646` to describe what the code now does.

**Acceptance criteria**
- [ ] Every candidate has a non-null `submitted_image_path`; no `(none)` on either dossier widget.
- [ ] Non-carriers open in Stegotool to a clean image, no payload.
- [ ] Carriers render their payload exactly as today.
- [ ] A guard asserts the correlation between "has an image" and "has a stego violation" is **not** 1.0 across a large sample — i.e. the giveaway cannot silently return.

---

## Phase B — #77, hostile chat vs ground truth

**Symptom (Nick, via the issue):** a Bad Actor's chat was marked hostile by the
Sentiment Scanner "even though HOSTILE_CHAT does not appear anywhere in that
candidate's ground-truth discrepancies."

**Root cause** — chat text is keyed on **archetype**, ground truth on the
**planted discrepancy**. `candidate_gen.py:388-392` hard-wires
`tone="hostile"`, `chat_pool=_CHAT_HOSTILE` for BAD_ACTOR, and `_build_chat`
tags every pool line `tag=spec.tone` at `:1146` — before it ever looks at
`discrepancies`. Only the single spliced line at `:1152-1156` consults the roll.
`widgets/typewriter.py:273-280` then gates the ⚠ marker on `tag == "hostile"`,
which cannot tell flavour from evidence.

**Measured:** 7,200 BAD_ACTORs. **100%** have hostile text and `tag="hostile"`
on every line. **41.9%** carry HOSTILE_CHAT. **58.1% (4,186) are the bug.**

**Worse than the issue states — it is 0% on the whole endgame.** Days 13–20 are
`band=hard`, and `candidate_gen.py:1025-1026` sorts DOSSIER-tier kinds *last*
under `DIFFICULTY_BANDS_TOOL_BIASED`. HOSTILE_CHAT is the only DOSSIER-tier kind
in BAD_ACTOR's eligible set, so it never wins a slot: **0 / 3,200 hard-band Bad
Actors carry it, while 3,200 / 3,200 still talk hostile.** The 20 HD$ Sentiment
Scanner is a pure false-positive generator for the last eight days of the
campaign.

**Implementation** (follows the issue's own prescription)
1. `_build_chat`: tag base pool lines `"hostile"` only when `has_hostile`;
   otherwise a distinct `"hostile_flavor"`.
2. When `has_hostile` *is* true, tag the base lines too — so a genuinely hostile
   candidate reads as flagged throughout, not just on the spliced line.
3. Add `"hostile_flavor"` to `_TAG_STYLE` with today's hostile *look* but no
   participation in the `tag == "hostile"` evidence checks.
4. Check the post-verdict reaction path (`typewriter.py:296-300`) for the same
   conflation.
5. **Beyond the issue:** the hard-band sort means a fix to the tagging alone
   leaves the endgame with zero hostile Bad Actors. Recommend exempting
   HOSTILE_CHAT from the DOSSIER-last sort, *or* giving BAD_ACTOR a second minor
   slot. Flagged as open question 5.

**Acceptance criteria**
- [ ] A Bad Actor without HOSTILE_CHAT never shows the ⚠ marker on any line.
- [ ] A Bad Actor with HOSTILE_CHAT shows it consistently across base lines.
- [ ] Without the upgrade, Bad Actor chat still reads hostile — no regression to neutral.
- [ ] Other archetypes' tone tags untouched.
- [ ] A guard measures the false-positive rate across many seeds and asserts it is zero.

---

## Phase C — BREACH_HIT under credential-corpus kinds

**Ask (Nick):** "ensure the ghostscan BREACH_HIT exists whenever there is a
leaked password or a cross breach on the hashcrack tool."

**Current state — half true.**

| | carriers | without BREACH_HIT |
|---|---|---|
| LEAKED_PASSWORD | 3,310 | **0 (0%)** |
| CROSS_BREACH_REUSE | 4,513 | **3,415 (75.7%)** |

LEAKED_PASSWORD ⇒ BREACH_HIT holds with zero exceptions, via `_IMPLIED_KINDS`
(`candidate_gen.py:950-952`). CROSS_BREACH_REUSE was **deliberately removed**
from that table — the comment at `:939-949` says #61(d) moved it to
`scoring.board_accuracy_bonus` instead, because `breach_dbs_for_candidate`
already renders the breach rows and scoring credits a BREACH_HIT *flag* against
a CROSS_BREACH_REUSE *violation* (`scoring.py:122-135`,
`test_breach_hit_flag_credited_against_cross_breach_reuse`).

**Every one of the missing cases is `sneaky_bugger`** — BREACH_HIT is simply not
in that archetype's `eligible_kinds` (`:406-430`), so it can never roll one.

So the **evidence** the player sees is already 100% present. What is absent is
the ground-truth kind. Which of those Nick means is **open question 2** — the
two readings need different fixes and one of them reverses a shipped design.

---

## Phase D — UNSALTED_STORAGE to the dossier

**Ask (Nick):** "move the unsalted password to the dossier because that's going
to be where it's first and most readily exposable… also make that a minor rule
until day three, until the hashcrack tool is introduced."

**Already half-done.** UNSALTED_STORAGE is *already* DOSSIER-tier in
`_SEVERITY_REVEAL` (`candidate_gen.py:598`) and the dossier already prints
`⚠ UNSALTED` with the plaintext (`shared.py:360-367`). What is still
CREDENTIAL is its **group and cluster** — `VIOLATION_CATALOG:81` and the
`cred-storage` cluster (`rules_content.py:247-249`). That split was deliberate
last round; Nick is now asking to collapse it toward DOSSIER.

**Severity — cheaper than it looks.** Discrepancy severity is **never used in
scoring**. Its only consumers are presentational (evidence-board chip colour,
the rules table's SEVERITY column, credit-reveal, debug) plus one semantic use
in `rules_engine.py:50` (`has_severity`). But `_SEVERITY` is derived as a flat
import-time dict in two places (`rules_content.py:93`, `shared.py:34`), so a
day-varying severity needs a day parameter threaded to those consumers.

**Implementation**
1. Move UNSALTED_STORAGE's catalogue entry to the `DOSSIER` group, into a
   cluster — destination is **open question 3**.
2. Introduce a day-scaled severity: minor before day 3, its current major from
   day 3. Thread `day` into `_SEVERITY` lookups rather than adding a second
   flat table.
3. Cascade: evidence board, rules page CREDENTIALS + DOSSIER tabs, catch hints,
   cluster-integrity guards.

---

## Phase E — WEAK_CREDENTIAL to `cred-storage`

**Ask (Nick):** "move the weak credential violation to the hashcrack credential
storage subcategory, just for balancing and organization."

One-line move in `VIOLATION_CLUSTERS`. Combined with D it leaves a clean 2/2:

```
cred-storage   WEAK_ENCRYPTION, WEAK_CREDENTIAL
cred-exposure  LEAKED_PASSWORD, CROSS_BREACH_REUSE
```

**Noted, not blocking:** "weak credential" is a property of the password the
user chose, not of how the site stored it, so "Storage" is a slightly loose fit.
The 2/2 balance is worth more than the taxonomy purity; proceeding as asked.

---

## Phase F — can WEAK_ENCRYPTION and UNSALTED_STORAGE coexist?

**Nick's question:** "I thought unsalted meant that it didn't have an encryption
to be weak."

**Answer: they coexist on 100% of unsalted candidates from day 3 on, and the
game currently tells the player two contradictory things about it.**

Mechanically:

- An unsalted candidate **does** get a real MD5 digest of a weak plaintext —
  `candidate_gen.py:1369-1371`. Verified: `d8578edf8458ce06fbc5bb76a58c5ca4` =
  `md5("qwerty")`.
- WEAK_ENCRYPTION is **not rolled, it is derived**: any rolled instance is
  deleted at `:1362-1363`, then re-added purely from hash shape at `:1411-1422`
  — *every* 32-hex candidate gets it, with no check for `_has_unsalt`. The
  comment at `:1399` says so outright.
- Measured: **1,792 of 2,192 unsalted candidates (81.8%) carry both**, and the
  400 exceptions are all day 1, excluded only because
  `intro_day(WEAK_ENCRYPTION) == 3`. **On every day ≥ 3 the rate is 100%.**

Domain-wise Nick's instinct is half right. "Unsalted" in the real world means
*hashed without a salt* — the hash exists, it is just trivially reversible by
rainbow table. MD5-without-salt is genuinely two separate findings, so
coexistence is defensible.

**But that is not what the game shows.** `shared.py:360-367` returns early for
unsalted candidates and prints the **plaintext with no hash at all**, explicitly
so it doesn't "read as still needs cracking". Meanwhile the Hashcrack page's
block header still prints `digest: 32 hex characters` from the same hidden MD5.
So the dossier says *"there is no crypto here"* and Hashcrack says *"here is an
MD5 digest"*, about the same candidate, and the player is scored on both
violations.

That is the incoherence Nick sensed. It is **open question 1**, and it gates D.

---

## Phase G — #73, the dossier-tier evidence guard

**Still applicable — more so after D.** The existing tier guard skips
DOSSIER-tier kinds on the reasoning that their evidence is "structural". Four
kinds sit in that blind spot today (HOSTILE_CHAT, AFFILIATION_NOT_STATED,
DISPOSABLE_EMAIL, UNSALTED_STORAGE), and phase D deliberately makes
UNSALTED_STORAGE a full DOSSIER-group member — moving it *further* into the gap
rather than out of it.

Phase B is also a live instance of the same class: HOSTILE_CHAT is DOSSIER-tier,
and its "evidence" is a chat tag that fires identically whether or not the kind
was planted. A matched-pair guard would have caught it.

**Implementation:** generate matched pairs (kind planted / kind absent, all else
equal), render the dossier panel for each, and diff. If nothing differs, the kind
is unflaggable. Verify by reverting #51's or #57's fix in a scratch copy and
confirming red, per the project's convention.

---

## Phase H — pad polish (centre start + distance meter)

**Ask (Nick):** "display a meter for how much distance the player has used on the
hashcrack page so they know how far they have traveled, and have the player's
point start in the center of the grid."

**Consequence worth stating:** a centre start **halves the worst-case direct
walk**, from `span_x + span_y` (36 on the medium pad) to roughly half that (18).
`test_a_direct_walk_is_always_free` asserts the free allowance clears that worst
case, so it keeps passing — with much more headroom than before. That means the
current 45 free steps is now *very* generous relative to a correct walk, and the
overage fee will fire even less often than the round-3 simulation showed. I will
re-run `sim_pad.py` against a centre start and report whether the budget wants
retuning; I will not change the numbers without saying so.

The step counter already exists on the panel and footer; this adds the **visual
meter** (a filled bar against the free allowance, turning amber past it).

---

## Open questions

Numbered; each with a recommendation. 1–3 gate implementation.

1. **What does UNSALTED_STORAGE mean?** (gates D and F)
2. **BREACH_HIT under CROSS_BREACH_REUSE — evidence, or ground truth?** (gates C)
3. **Which cluster does UNSALTED_STORAGE move into?** (gates D)
4. **Branch and commit granularity.**
5. **The hard-band sort starves HOSTILE_CHAT to 0% on days 13–20.** Fixing the
   tag without fixing the sort leaves the endgame with hostile-sounding Bad
   Actors who never carry the violation. Recommend exempting HOSTILE_CHAT from
   the DOSSIER-last sort. Taking silence as assent unless told otherwise.

### Assumptions I am proceeding on unless corrected

- **Severity target for UNSALTED_STORAGE from day 3 = `major`** (its value
  today). Only the pre-day-3 value changes, to `minor`.
- **WEAK_CREDENTIAL → `cred-storage`** exactly as asked, despite the loose
  taxonomy fit noted in phase E.
- **`_st_images` grows to ≥ 16 names.** The issue raises this as a "consider";
  with every candidate drawing from it, a 4-name pool is a new pattern.

---

# SHIPPED — 2026-09-15

All phases landed on the current branch. **509 tests pass** (the one failure is
the sandbox missing the `.wav` assets, not a code fault). No new lint debt: the
only ruff findings on touched files are at pre-existing line numbers and match
the codebase's established style.

Answers given at the gate: unsalted means **plaintext**, suppress
WEAK_ENCRYPTION · BREACH_HIT via **sneaky_bugger eligibility**, not an
implication · UNSALTED_STORAGE into **DOSSIER / Personal** · **one commit per
phase**, current branch.

## What each phase actually moved

| phase | measured before | measured after |
|---|---|---|
| A · #78 image giveaway | image↔stego correlation **1.000**, 89.6% of candidates had no image | every candidate has one; 18 filenames; correlation broken |
| B · #77 hostile chat | 58.1% of Bad Actors flagged without the violation; **0%** carried it on days 13–20 | **0** false positives, **0** false negatives; hard band back to 52% |
| C · BREACH_HIT | absent from **75.7%** of CROSS_BREACH_REUSE carriers | **0%** |
| F · unsalted + weak encryption | co-occurred on **100%** of unsalted candidates from day 3 | **0** |
| G · #73 dossier guard | four kinds in the blind spot, unchecked | both directions checked, and it **found a live bug** |
| H · pad | worst direct walk 36 steps from a corner | 18 from the centre; budget retuned 45/10 → 28/8 |

## The bug phase G found on its first run

`AFFILIATIONS_THIN` contained the literal string `"(none listed)"` — which *is*
`NO_AFFILIATION_STATED`, the sentinel that means AFFILIATION_NOT_STATED. Any
thin-pool archetype drew the evidence marker about one time in five **without
carrying the violation**: 344 of 4,315 non-carriers, across clumsy_cutie,
bad_actor, dark_web, the_incompatible and white_hat.

A player reading the one dossier field the rules page tells them to read got a
false positive, and denying on it was punished. This is #51's exact shape, and
it survived #56's "make the affiliation evidence real rather than implied" pass
because nothing ever checked the other direction. Fixed by removing the string
from the pool; the sentinel is now reachable only by planting the kind.

That is the argument for #73 being worth doing, made by #73 itself.

## Guard verification

Every new or rewritten guard was checked by breaking the thing it guards:

| mutation | result |
|---|---|
| #51 revert — sentinel back in the thin pool | **RED** |
| #57 revert — detector list drifts from the generator | **RED** |
| #77 revert — every Bad Actor line tagged hostile | **RED** |
| unsalted evidence removed from the dossier | **RED** |
| a new DOSSIER-tier kind added with no predicate | **RED** |
| *adding domains to the generator pool* | *green — no-op, see below* |

The one green is honest rather than a dead guard. `_GS_SUSPICIOUS_DOMAINS =
frozenset(_DISPOSABLE_DOMAINS)` — the detector list is *derived from* the
generator's, so they are one source of truth and #57's drift is structurally
impossible today. Mutating the generator moves both sides at once. The opposite
mutation, which simulates the two genuinely separating, goes red.

Worth noting: an earlier draft of that predicate read the **generator's** list,
and this revert check is what caught it. Reading the detector — the list the
rules page actually shows the player — is the whole point.

## Commit messages

One per phase, in this order (F before D — D's cluster move only makes sense
once unsalted no longer carries a second credential violation):

```
A  Give every candidate a submitted image (#78)

   The dossier's Image field was a free, perfect readout of ground truth.
   submitted_image_path was derived from the candidate's discrepancies, so a
   filename meant "carries a stego violation" and "(none)" meant clean:
   measured at a correlation of 1.000 across 72,400 candidates, with zero
   decoys in either direction. Once Stegotool unlocked on day 5 the player
   never had to open it.

   candidate_gen's own design comment already asserted the opposite invariant
   — "every candidate submits exactly ONE image" — and the code had never
   honoured it; 89.6% submitted none. Now it does.

   The filename pool grows from 4 to 18. With only ~10% of candidates drawing
   from it, four names were plenty; with every candidate drawing, four collide
   inside a single six-slot roster and a shared filename becomes the next
   pattern to read. Shapes are mixed so no one shape is a tell either.

   No renderer change needed: both stego paths already fell back to a synthetic
   filename, and build_stego_image computes suspicion from ground truth rather
   than from the filename.

B  Separate hostile VOICE from hostile EVIDENCE in chat (#77)

   Bad Actor's archetype tone is literally the string "hostile", every pool
   line was tagged with it, and the chat widget gates the Sentiment Scanner's
   red ⚠ on tag == "hostile". So every Bad Actor was marked as carrying
   HOSTILE_CHAT whether or not they had rolled it: 58.1% of them had not.

   Worse than the issue describes. Days 13-20 are the hard band, where the
   tool-biased sort pushes DOSSIER-tier kinds to the back of the queue, and
   HOSTILE_CHAT is the only DOSSIER-tier kind in Bad Actor's eligible set. It
   never won a slot: 0 of 3,200 hard-band Bad Actors carried it while 3,200 of
   3,200 still talked hostile. A 20 HD$ upgrade reported a violation that did
   not exist for the last eight days of the campaign.

   Two changes. A candidate whose archetype voice is hostile but whose ground
   truth is not now tags "hostile_flavor", which styles identically and no
   evidence check looks at — the dialogue must still read hostile or the prose
   itself becomes the tell. And HOSTILE_CHAT is exempted from the DOSSIER-last
   sort, which is not special-pleading: that lever exists to push FREE evidence
   behind the tool economy, and this is the one dossier-tier kind already gated
   behind a paid upgrade. Hard band goes 0% -> 52%.

   Both hostile tags share the Scanner's colour gate. Styling flavour red while
   evidence stayed neutral for an unupgraded player would have inverted the
   tell — the candidates without the violation would be the ones glowing.

   The post-verdict reaction path was checked and is unaffected: it takes its
   colour from reactions.pick() and never reads a tag.

C  Corroborate cross-breach reuse with a Ghostscan breach hit

   A password cannot recur across breach corpora unless the account is in those
   corpora, but BREACH_HIT was missing from 75.7% of CROSS_BREACH_REUSE
   carriers — and every single one of those was a Sneaky Bugger, for no better
   reason than BREACH_HIT not being in that archetype's eligible_kinds.

   Fixed as a COMPANION PREFERENCE rather than an implication. #61(d)
   deliberately removed CROSS_BREACH_REUSE from _IMPLIED_KINDS so the two stay
   distinct kinds in ground truth, reconciled at scoring time; re-adding it
   there would have undone that. A preference only reorders the candidates for
   a slot the archetype already has, so the companion still costs budget and
   still loses to a forced violation. Eligibility alone got the gap from 75.7%
   to 59% — one minor slot against four competitors — so the preference is what
   closes it. Now 0%.

F  Unsalted storage has no encryption to be weak

   An unsalted credential is stored in the clear, so WEAK_ENCRYPTION on one is
   a category error rather than a second finding. The generator still builds
   them an md5 internally because the cipher block needs something to key off,
   but the player never sees it: the dossier returns early for unsalted
   candidates and prints the plaintext with no hash, precisely so it doesn't
   read as "still needs cracking".

   Before this the game told the player two contradictory things about one
   candidate — the dossier said "no crypto here" while the Hashcrack header
   said "digest: 32 hex characters" — and scored them on both violations.
   1,792 of 2,192 unsalted candidates carried both, and 100% of them on every
   day from 3 onward.

D  Move unsalted storage to the dossier, and scale its severity by day

   UNSALTED_STORAGE was always DOSSIER-TIER — its evidence is the plaintext on
   the dossier, readable on day 1 with no tool — but it was GROUPED under
   CREDENTIAL, which put the chip on a board tab whose evidence the player
   could not yet see. Group and tier now agree, and it files under DOSSIER /
   Personal: storing your password in the clear is something this person did,
   not a property of the site.

   Severity now steps with the campaign: a note until Hashcrack arrives on day
   3, a major violation after. Before the tool there is no credential economy
   for the finding to sit in and nothing to corroborate it with. Implemented as
   severity_for(kind, day) rather than a second table, applied both at plant
   time and on the rules page so the two surfaces cannot disagree.

   The locked CREDENTIALS tab no longer renders a violation table — every
   remaining kind there needs Hashcrack, and a header over an empty table tells
   the player something exists without saying what. It now points at the
   DOSSIER tab instead.

E  Rebalance the credential clusters

   WEAK_CREDENTIAL moves Exposure -> Storage, leaving a clean 2/2 split now
   that unsalted storage has left for DOSSIER. The line is "what the credential
   IS" versus "where it has already been": a weak algorithm and a weak password
   are both properties of the artifact in front of you, readable off one
   cracked block, while a leak and a reuse are facts about the outside world
   that need the breach corpus. That also matches how each pair is found.

G  Close the dossier-tier evidence blind spot (#73)

   EVIDENCE_TOKENS covers the tool tiers and deliberately skipped DOSSIER-tier
   kinds, on the reasoning that their evidence is "structural". Two shipped
   bugs came through that exemption (#51, #57) and each fix repaired one kind
   and left the gap open.

   Adds DOSSIER_EVIDENCE: per dossier-tier kind, a predicate over the free
   surfaces — the rendered dossier panel plus the chat script — asserted in
   both directions across a sweep. True-for-every-carrier catches "planted but
   never rendered" (#51); false-for-every-other catches "rendered for everyone",
   which is a free giveaway. A completeness check fails when a new DOSSIER-tier
   kind arrives without a predicate, so the next one is caught by default
   rather than by memory.

   It found a live bug on its first run. AFFILIATIONS_THIN contained the
   literal string "(none listed)", which IS the NO_AFFILIATION_STATED sentinel,
   so a thin-pool archetype showed the evidence marker about one time in five
   without carrying the violation — 344 of 4,315 non-carriers. A player reading
   the field the rules page points them at got a false positive. Removed from
   the pool; the sentinel is now reachable only by planting the kind.

   Verified by reverting #51's and #57's fixes in a scratch copy and confirming
   the guard goes red, per the project's convention.

H  Start the alignment pad in the centre, and meter the distance walked

   The cursor started at (0, 0). A corner start gives away information — three
   of the four directions are walls, so the first press is never a real choice
   — and it doubles the worst-case walk. From the centre every direction is
   live and the player has to read the block to pick one.

   The step budget is retuned 45/10 -> 28/8 to match. Halving the distances
   halved the step counts, and at the old numbers the fee had gone nearly
   inert: a careless player paid nothing 99% of the time, so the budget priced
   nothing. 28/8 reproduces the profile 45/10 had from a corner — a clean or
   humanly-noisy walk pays nothing on 100% of blocks with 55% headroom, a
   careless one pays nothing 77% of the time, a wandering one 40%.

   The panel gains a travelled-distance meter: a bar that fills across the free
   allowance and then continues in amber. It measures distance TRAVELLED, not
   remaining — a meter counting down to zero would be a readout of how far the
   key is, which is the one thing the pad must never tell the player.
```

## Not done, deliberately

- **60 multi-line `[dim]` spans on the Logwatch and Stegotool rules tabs.**
  The rules page is validated per line, and these open a tag on one line and
  close it on another. They render correctly at runtime (the tab is parsed as
  one string), so these are a style-convention violation rather than a bug, and
  they are outside this batch. I fixed the two that sat next to edits I was
  already making.
- **`intake.py` defines `_publish_recovered_password` twice** (identical
  bodies, left over from the round-2 cipher rework), and
  `CIPHER_GRID_BASE["strong"]` is 52 columns against a `CIPHER_GRID_MAX` of 50,
  so that value is dead. Both flagged previously, both still unaddressed.
