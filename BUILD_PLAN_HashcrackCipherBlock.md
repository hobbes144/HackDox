# BUILD PLAN — Hashcrack: the Cipher Block

Reworks the Hashcrack page into a **standalone two-stage decryption minigame**.
The player identifies the encryption algorithm from the block itself, chooses
the matching decryption window, and then fine-tunes an alignment dial until the
ciphertext resolves into the password.

Not a sibling of the stego stamp. There is no canvas to sweep and no spatial
search: the whole block decrypts at once, and the skill is *reading* the
credential and *tuning* the decrypt, not hunting for where something is hidden.

> **v2, 2026-09-14.** Supersedes the aperture-sweep design (moveable reveal
> windows, per-batch ⏱, coverage threshold). That version shipped and played
> wrong — it was a spatial hunt wearing a cryptography costume. Everything in
> §1 is new; §2's violation table carries Nick's redistribution; §3 is
> unchanged and already shipped.

---

## 0. Decisions

### Round 1 (mechanic scaffolding — still current)

| # | Decision | Chosen |
|---|---|---|
| 1 | The Hashcrack credential audit log | **Cut from the page.** Its evidence-bearing rows move into the Logwatch day log, which already is an audit log. *(Confirmed against the audit-list generator: Logwatch already generated its own AUTH_OK/AUTH_FAIL bursts for the kinds it owns, so only `HASH_SUBMIT` and `BREACH_MATCH` actually needed relocating — merging the rest would have double-printed every burst.)* |
| 2 | Corpus evidence for `LEAKED_PASSWORD` / `CROSS_BREACH_REUSE` | **The cipher block names the corpus itself** on resolve. Logwatch's relocated rows corroborate; they are not the sole evidence. |
| 3 | `WEAK_ENCRYPTION` tier | **Retier DOSSIER → HASHCRACK**, cascaded through every surface. |
| 4 | Reading the algorithm without spending | **Yes — the block is the free tell.** Its digest shape and glyph alphabet identify the algorithm before a single ⏱ is spent. |

### Round 2 (the two-stage mechanic + violation redistribution)

| # | Decision | Chosen |
|---|---|---|
| 5 | Stage 2's cost | **Free to move, live feedback.** One purchase buys the window; the dial then turns freely and the block sharpens as it approaches true. |
| 6 | Dial feedback | **The text itself sharpens — no numeric readout.** The player reads the block, not a percentage. |
| 7 | `UNSALTED_STORAGE` | **Regroup only.** Moves into the CREDENTIAL group on the evidence board and rules page, but keeps its DOSSIER tier gate — its evidence really is free on the dossier, and a full retier breaks day 1 at load. |
| 8 | `CROSS_BREACH_REUSE` → critical | **Moved off Clumsy Cutie** onto the deliberate-misconduct archetypes. Clumsy Cutie has no critical budget slot, so leaving it there would have deleted the kind from that archetype silently. |

---

## 1. The mechanic

### 1.0 What the player sees for free

The block renders the submitted credential as a grid of ciphertext glyphs, with
a header carrying three plain observations:

```
── cipher block ──────────────────────────────
40 × 6 cells  ·  hex glyphs
digest: 64 hex characters
  algorithm unidentified — match the digest shape against the reference table
```

Dimensions, glyph alphabet and digest shape are printed unconditionally,
because they are facts about the artifact rather than conclusions about it.
`UPGRADE_CRYPTO_ID` ("Cipher ID HUD") is what names the algorithm.

This free read is load-bearing twice over. It tells the player **which window
to choose**, and — separately — **whether the credential is worth opening at
all**. Those are different questions, and the second is the one with teeth.

### 1.1 Stage 1 — choose the decryption window

One command (`crack` / `h`, or `X` on the page) opens the window selector.
Three windows, one per algorithm family:

| Window | Matches | Outcome |
|---|---|---|
| **MD5** | a 32-hex digest | decrypt engages, dial unlocks |
| **SHA-256** | a 64-hex digest | decrypt engages, dial unlocks |
| **bcrypt** | a `$2b$` digest | decrypt engages, then **stalls** — key-stretched, 2¹² rounds, no completion possible |

Selecting a window charges the tool's base cost (`tools_bridge.tool_cost`, so
inflation and the Hashcrack Optimizer both still apply). Three outcomes:

- **Wrong window** — the block stays garbage. "No structure emerged." ⏱ spent.
  The player may pay again to try another.
- **Right window, crackable** — the block visibly engages and the alignment
  dial appears.
- **Right window, bcrypt** — the block engages and immediately stalls. ⏱ spent,
  and no dial will ever appear.

That last row is the whole point of decision 4. Correctly *identifying* bcrypt
is not the same as it being *viable*, and the only winning move is to not open
it. A player who reads the block spends nothing; a player who doesn't pays to
learn the same fact.

### 1.2 Stage 2 — the alignment dial

The decrypt has the right family but the wrong derived key. A dial
(`0 … CIPHER_ALIGN_RANGE`) tunes it. Moving the dial is **free** and updates
the block **live**.

Rendering is deterministic, which matters — a dial the player turns back and
forth must show the same picture at the same value:

- every cell carries a fixed per-cell tolerance, seeded off the candidate
- at dial distance `err = |dial − true|`, a cell shows its **plaintext** glyph
  when its tolerance clears `err`, and its **ciphertext** glyph otherwise
- beyond `CIPHER_ALIGN_TOLERANCE` no cell resolves at all — pure garbage

So the search has a real shape: spin until *anything* legible appears, then
climb. Within tolerance the text sharpens smoothly; at `err == 0` the block is
fully legible and **locks**.

**What the decrypted block actually says.** The plaintext grid is the password
**tiled across the whole block**, separated by a delimiter:

```
summer2021!·summer2021!·summer2021!·summ
er2021!·summer2021!·summer2021!·summer20
```

Tiling is a deliberate design choice, not filler. Partial alignment scrambles a
*different* subset of cells in each repeat, so a player at 70 % can read the
password by consensus across rows — which is exactly the "watching it come into
focus" feeling, and it makes the dial's last few steps satisfying rather than
fiddly.

**Resolve requires exact alignment.** At `err == 1` the block is ~90 % legible
and the password is usually already readable — but the tool only *confirms* it,
names the breach corpus, and emits the violation labels at `err == 0`. Reading
it early is a reward; landing it exactly is the completion.

**Per tier.** MD5 gets a short dial and a generous tolerance; SHA-256 a longer
dial and a tighter one. Same mechanic, honestly harder.

**UNSALTED_STORAGE** skips both stages: the block arrives decrypted and aligned.
No salt means the stored value is exposed outright, which is the violation.

### 1.3 Where the upgrades sit

| Upgrade | Job |
|---|---|
| `UPGRADE_CRYPTO_ID` — Cipher ID HUD | names the algorithm on the header, so stage 1 becomes a lookup instead of a read |
| `UPGRADE_HASH_HIGHLIGHT` — Credential HUD | marks a **band** on the dial containing the true value (±`CIPHER_HINT_BAND`). Narrows the search; never answers it — #54's lesson, and the base tier marks nothing |
| `UPGRADE_HC_VERDICT` — Crack Verdict Analyzer | the strength verdict on the recovered plaintext |

---

## 2. Violations

| Kind | Before | After | Evidence |
|---|---|---|---|
| `WEAK_ENCRYPTION` | DOSSIER · minor | **HASHCRACK** · minor | the digest shape in the block header |
| `WEAK_CREDENTIAL` | HASHCRACK · minor | unchanged | recovered plaintext is a dictionary word |
| `LEAKED_PASSWORD` | HASHCRACK · **critical** | HASHCRACK · **major** | resolve readout names the corpus |
| `CROSS_BREACH_REUSE` | HASHCRACK · **major** | HASHCRACK · **critical** | resolve readout names ≥ 2 corpora |
| `UNSALTED_STORAGE` | DOSSIER · major, **DOSSIER group** | DOSSIER · major, **CREDENTIAL group** | block arrives pre-decrypted; plaintext still on the dossier |
| `CREDENTIAL_STUFFING` | LOGWATCH | unchanged | relocated rows — now genuinely Logwatch-only |

### 2.1 The severity swap and its knock-on

Promoting `CROSS_BREACH_REUSE` to critical makes it **unreachable for Clumsy
Cutie**, whose budget is `minor=2, major=1` with no critical slot. That is not
a loud failure: `_roll_discrepancies` gates each forced kind against its own
severity's slot, and the `forced_violations` loader validates tier,
expressibility and whitelist but **never budget capacity** — so the kind would
simply stop appearing, on an archetype it was written for.

Per decision 8 it moves to the deliberate-misconduct archetypes: dropped from
Clumsy Cutie's `eligible_kinds`, added to Sneaky Bugger's (Bad Actor already
lists it). The story changes with it — reusing a known-breached credential
becomes misconduct rather than carelessness — and §4 carries that through the
day-3 tutorial.

### 2.2 Regrouping without retiering

`UNSALTED_STORAGE` moves group but not tier, which the code already supports:
`VIOLATION_CATALOG` names the board group explicitly, while `visible_catalog`
gates each kind by *its own* tool. So the kind shows under CREDENTIAL from day
1, because the dossier is never locked.

One gap this opens, and the fix: the rules page's CREDENTIAL tab is gated on
Hashcrack unlocking on day 3, so a day-1 player would meet a violation whose
documentation was locked. The locked tab therefore still renders the
dossier-tier credential kinds — a violation must never be plantable and
undocumented on the same day.

---

## 3. The Logwatch relocation *(shipped, unchanged)*

Only `HASH_SUBMIT` and `BREACH_MATCH` moved into `_lw_candidate_entries`. The
AUTH_OK/AUTH_FAIL bursts did **not** — Logwatch has always generated its own
for the kinds it owns, and merging would have printed every burst twice.

Both relocated row types are `is_suspicious=False`: they are context the player
reads, not findings Logwatch asserts. Logwatch owns no credential violation, so
a flagged row here would rebuild #62 on a new page.

---

## 4. Content consequences

- **Day 3, slot 2** forces `cross_breach_reuse` onto a `clumsy_cutie`. After
  §2.1 that pairing silently produces a candidate *without* the violation. The
  slot's archetype changes to `sneaky_bugger` (critical slot available), and
  the day's `_comment_script` is rewritten — the reuse lesson is now taught as
  deliberate misconduct, which is what the promotion to critical means.
- **Day 1** is untouched: decision 7 keeps `UNSALTED_STORAGE` dossier-tiered,
  so slot 3's forced violation still loads.

---

## 5. Phase order

1. `config.CIPHER_*` — replace the aperture knobs with window/dial knobs.
2. `tools_bridge` — the two-stage model, headless-testable.
3. Violation redistribution + the Clumsy Cutie / Sneaky Bugger move.
4. Day 3 content fix.
5. Cascade: board group, rules page (incl. the locked-tab gap), reference copy.
6. `CipherBlockPanel` + intake rewiring.
7. Tests, and revert-verify every guard.

---

## 6. Traps carried forward

- **Verify every guard by reverting its property and confirming red.** Round 1
  found three green-when-broken guards this way: one genuine tautology, one
  real gap, one bad mutation of my own. When a revert comes back green, decide
  which of the three it is before moving on.
- **`load_day(1)` is authored tutorial content**, never a generic day fixture.
- **Dataclass field order** — defaults last.
- **Assert against the rendered block, not against `password_strength()`** — a
  guard that reads a conclusion computed from the same ground truth it asserts
  cannot detect a missing observation.
- **The forced-violation loader does not check budget capacity.** Any severity
  change must be re-checked against every archetype's budget *and* against
  every day file that forces that kind.

---

## 7. SHIPPED — v2, 2026-09-14

Suite **312 passing** (`test_cipher_block.py` 31 + `test_engine_foundation.py`
281), plus the UI and content suites. The aperture model was removed wholesale
rather than adapted.

### Calibration (measured)

Sharpening curve at day 5, as the dial approaches the true value:

| err | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| **weak** (range 24, tol 10) | 100 % | 94 % | 84 % | 74 % | 66 % | 57 % | 45 % | 37 % | 24 % | 17 % |
| **medium** (range 40, tol 8) | 100 % | 88 % | 77 % | 66 % | 57 % | 44 % | 33 % | 23 % | 8 % | 0 % |

Finding the true value — coarse sweep, then walk in — costs a **median of 10
keypresses (max 15)**, flat across days 3 → 20. The dial is free, so its length
is texture rather than cost; what scales with the campaign is the window price
(3 ⏱ on day 3 → 8 ⏱ on day 20) and the size of the block being read.

### Two design bugs found by measurement, not taste

1. **`err = 1` rendered identically to `err = 0`.** Per-cell tolerance was drawn
   from `1..tol`, so every cell had a tolerance of at least one and the block
   went fully legible one step off true. The player would have seen a finished
   password with no way to know they were not there yet, and "fine-tune it
   exactly" would have meant nothing. Drawing from `0..tol` gives a share of
   cells that only settle at the exact value — those stubborn few characters
   *are* the lock. `test_exact_alignment_is_distinguishable_from_one_step_off`
   holds it.
2. **My own probe was clamping**, so the weak tier reported 100 % at every
   distance and looked broken when it was not. Worth recording because the
   first instinct was to "fix" correct code.

### Cascade — every surface the redistribution touched

- `VIOLATION_CATALOG` — `WEAK_ENCRYPTION` and `UNSALTED_STORAGE` moved into
  CREDENTIAL. `WEAK_ENCRYPTION` was **already wrong**: round 1 retiered it
  DOSSIER → HASHCRACK and left its catalogue entry behind, so the board filed it
  under a group whose tool no longer revealed it.
- `VIOLATION_CLUSTERS` — the emptied `dossier-password` cluster retired;
  CREDENTIAL split into **Credential Storage** (how it is kept) and **Credential
  Exposure** (whether it has already leaked). The cluster-integrity guard caught
  the group mismatch at import time, unprompted.
- `violation_table()` gained an `unlocked_tools` filter, so the **locked**
  CREDENTIAL tab documents `UNSALTED_STORAGE` without spoiling the three kinds
  that are genuinely gated.
- Severity colours and the rules tables update themselves — both read
  `_SEVERITY_REVEAL` — so the swap reached the player with no prose edited.
- Stale prose fixed: the dossier tab's encryption-chip section (the chip no
  longer exists), the Ghostscan tab's "Hashcrack audit log" reference and its
  "CROSS_BREACH_REUSE (major)" line, and five `_CATCH` hints.

### Content consequence worth knowing

Day 3's slot 2 moved from `clumsy_cutie` to `sneaky_bugger`, which changes that
slot's Site Health weight on a **wrong admit** from **−4 to −12**. Correct
denials are unaffected (they never damage health), and day 3 is the tutorial
that teaches exactly this violation with the evidence plainly present — but one
bad admit on day 3 now costs meaningfully more. Flagged rather than buried; it
is a one-line revert (`forced_includes["2"]`) if it plays badly.

Day 3 also loses its only Clumsy Cutie, and with it the only source of
`UNSALTED_STORAGE` on that day. Day 3 verified still fully solvable with
day-3 tools (`test_day_3_is_solvable_with_day_3_tools`).

### Guard verification — 16 mutations, 16 red

One came back GREEN on the first pass, and it was **the same mistake as round
1**: mutating only the `tier == "strong"` half of the bcrypt guard leaves
`plaintext` as `None`, so the early return still fires and nothing changes. The
guard was fine; the mutation was a no-op. Re-run with a real band and dial
forced onto the strong tier, two tests caught it.

A **new** guard, `test_every_eligible_kind_fits_its_archetypes_budget`, closes
the hole that made the day-3 break silent — it asserts no archetype lists a
violation its budget has no slot for. It immediately found a pre-existing,
*deliberate* instance (the White Hat's two minor kinds, documented in the spec
as "eligible but never actually rolled"), which is exempted by name so the
guard keeps its teeth for new mistakes.

The pre-existing `test_every_tutorial_day_actually_contains_its_scripted_violations`
also catches the day-3 break — the codebase's own guard was live and would have
caught it.
