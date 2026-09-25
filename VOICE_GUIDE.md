# HackDox Voice Guide — "Hack" + "Docks"

The single source of truth for how HackDox *sounds*. Every piece of player-facing
copy — the Foreman's lines, candidate chat, rule-sheet notes, word banks, image
filenames, achievement and shop names — is written against this file. The
`dockside-voice` subagent (`.claude/agents/dockside-voice.md`) enforces it.

Locked by Nick, 2026-09-24:

1. The Overseer is renamed **The Foreman** (player-facing only — see §6).
2. Real-world organisations become **made-up harbour organisations**.
3. Email domains are a **mix** of real consumer providers and in-world ones.
4. Intensity: **one dock phrase every two or three lines.**

Locked by Nick, 2026-09-25: the world (§0). Data moves by ship after an AI
disaster, and the player vets the couriers who carry it.

---

## 0. The world

This replaces the old premise ("the first internet service for cybersecurity
information, already compromised"). Nothing in player-facing copy should
describe HackDox as an online service any more.

**The Undertow.** Some years back, a machine mind got loose in the world's
networks and never came out. Nobody agrees on what it was, who built it or who
let it go; people call it the Undertow because you never see it, you just feel
the pull. Anything sent down a wire now might be read on the way, or arrive
saying something it didn't say when it left. Forged messages, rewritten
records, emptied accounts.

**Nobody trusts the wire, or the people who were good with it.** The wire still
runs: people still send mail, post and keep profiles on it. They just don't
trust it with anything that matters. Hackers are the other casualty. Nobody
knows any more whose side a clever keyboard is on: its owner's, a smuggler's,
or the Undertow's.

**So data moves by ship.** Anything that matters (records, keys, reports,
firmware) is written to sealed drives on machines that have never touched the
wire, locked in a case, and carried port to port by a **bonded courier** who
rides with it the whole way. A sealed drive is only as honest as the hands
carrying it.

**HackDox is the data docks.** It's the pier where sealed data freight is
loaded, and the gate where couriers are bonded. The pier moved ordinary cargo
before the Undertow; the Foreman worked it then too, which is where her "like
we did it before the machines" comes from.

**The player** is the clerk at the gate. Everyone at the gate is applying for a
**courier bond**, the right to carry sealed freight off this pier. Admit means
bond them; deny means turn them back. Their stated purpose is the run they
want.

**The gear works offline.** The gate terminal is air-gapped. It has never
touched the wire, and everything on it came in by boat: breach archives, a
snapshot of the open wire (profiles, handles, forums), the logbooks from every
terminal a courier has worked, and whatever they submit with their papers.
That's why the tools can be real security tools in a world that doesn't trust
computers:

| Tool | In-world, it reads… |
|---|---|
| Ghostscan | the shipped snapshot of the open wire, plus the breach archives |
| Hashcrack | the sealed credential they submit with their papers |
| Logwatch | the logbooks from the terminals they've worked, shipped in weekly |
| Stegotool | the image they submit with their papers, looking for a false bottom |

**What the other systems mean.**
- **Site Health** is how far other ports trust freight off this pier. Bond the
  wrong courier and a case gets opened, copied or swapped; if trust hits zero,
  no port will take a crate from HackDox again.
- **The Dark Web** kept its name after the wire went dark. It's the smuggling
  trade: people who want their own couriers bonded so they can read, copy or
  swap what's in the cases, and sell it. The Foreman owes them.
- **The White Hat** is working against the smugglers and needs a bond to get
  evidence off the pier.
- **HackDollar$** are the gate's own scrip, paid in the envelope at the whistle.

**Left open on purpose (Nick's call, not the copy's):** what the Undertow
actually is, whether it's still aware or still spreading, who released it, and
whether the smugglers have any connection to it. The Foreman doesn't know
either. She talks about the Undertow the way dockworkers talk about weather:
matter-of-fact, a bit superstitious, never explained. Don't answer these in
copy until Nick decides.

**Where the world gets explained.** The day-1 briefing carries the setup. Days
2 to 5 add one piece each, alongside the tool they introduce (the air gap, the
sealed credential, the logbooks, the false bottom). Day 6 names the smugglers.
After that the world is background: the Foreman refers to it, never explains
it again.

## 1. The frame

The job is told as dock work. The player works **the gate** of the data docks,
and every candidate is someone coming off the boat with papers, asking for a
courier bond.

| Game concept | Dock framing (use in dialogue, notes, flavor) | Keep precise (use in rule text / tool output) |
|---|---|---|
| The player | the clerk, the tally clerk, "the new hand" (early), "you" | analyst |
| HackDox desk | the gate, the data docks, the terminal, the pier, the desk | HackDox |
| A candidate | whoever's at the gate; someone after a courier bond, showing papers | candidate |
| Dossier | papers, their manifest | dossier |
| Admit / deny | bond them, clear them, wave them through / turn them back, send them back down the gangway | admit / deny |
| A day | a shift; the graveyard shift for late/grim days | day |
| End of day | the whistle; clocking out | end of day |
| Rules | the book, what's posted at the gate | rule, violation, severity |
| The tools | your gear; the scanner, the pry bar (Hashcrack), the logbook (Logwatch), the lamp (Stego) — sparingly | Ghostscan / Hashcrack / Logwatch / Stegotool |
| ⏱ compute hours | hours on the clock, time on the crane | compute hours (⏱) |
| HackDollar$ | pay, wages, the envelope | HackDollar$ (HD$) |
| Between-day shop | the hiring hall, the supply shed | shop, upgrade |
| Site Health | the state of the pier; "how the terminal's holding" | Site Health |
| Dark Web | the smugglers, the night crew, "our friends off the late boat" | Dark Web |
| The Foreman being compromised | on the take, looking the other way, owes somebody | — |
| White Hat | a straight shooter; someone who won't look the other way | White Hat |
| Stego payload | contraband in the hold, a false bottom | STEGO_PAYLOAD_PRESENT etc. |
| Credential breach | a leak in the hull, a busted seal | breach, leaked password |
| Auth log | the logbook, the tally sheet | auth log |
| Hash / cracking | a sealed crate / prying the lid | hash, crack |

The right column is not optional. **A rule must say exactly what it checks,**
in real security terms, because the player acts on it. The flavor lives around
the rules, not inside them.

## 2. Intensity — "salted, not soaked"

- **Dialogue (Foreman, candidates, Dark Web justifications):** one dock phrase
  every 2–3 lines. A line can be entirely plain. Three idioms in one sentence
  is always too many.
- **Rule-sheet `summary` and `notes`:** at most one light touch per summary;
  notes stay plain and precise.
- **Rule `text`, tool output, Rules pages, evidence names, the `VIOLATION_CATALOG`:**
  zero. These are the "every tool is real" layer.
- **UI chrome (menus, buttons, key hints):** plain. Shop/achievement *names* may
  carry flavor; their descriptions state exactly what they do.
- **Ramp:** the Foreman gets saltier as she gets hostile. Days 1–5 are a gruff
  old hand showing a new clerk the ropes; the late campaign is a tired woman on
  the take who talks like the pier is hers.

## 3. The Foreman

The Foreman is a woman: the existing script already writes her as "her" (day 17, "What This Made of Her"). Use she/her, never "it".

Twenty-odd years on this gate. Calloused, practical, funny in a dry way early
on. Believes the job is the job and the boats don't wait. By the corruption arc
she owes the night crew, and she dresses it up as "keeping the line moving" and
"everybody on this pier eats."

- **Early (1–5):** warm-gruff mentor. "Here's how we do it on this gate."
- **Middle (6–11):** pressure from upstairs, then the first favours asked.
- **Late (12–20):** hostile, manipulative, occasionally honest when tired.
  Alignment bands keep their existing meaning; only the voice changes.

- **Endless Mode (#7, 2026-09-25):** a separate game, and a different
  Foreman: the early-campaign mentor with no debt to anyone. She's on the
  clerk's side, practical and warm, and she reacts to how the *run* is going
  (the five-shift accuracy trend), never to a day number: encouraging when the
  tally rises, plain-spoken concern when it falls, straight talk near the 70%
  line. Rule changes come with a reason — casual for a rule easing off, a real
  explanation ("two ports sent cases back on exactly that") for a new hard
  deny. Never smugglers, never the arc. Keys: `endless_*` in `overseer.json`;
  phrasings: `_ENDLESS_RULE_CHANGE_PHRASINGS` in `_narration.py`.

Stock phrases (rotate them, never lean on one): *keep the line moving · boats
don't wait · clock's running · that's the job · mind your fingers · hang back
after the whistle · rough shift · long haul · I've seen worse come off worse
boats · don't make me find a new clerk · the tide doesn't care · dirty job,
somebody's got to.*

Examples (calibration, not final copy):

- Day 1 failed: *"Hang back after the whistle. You and me need to talk about
  what you let off the boat today."*
- Day 7 poor: *"Something walked off the boat today with nothing on its papers.
  That's not innocence — that's a gap in your read."*
- Late, Dark-Web-leaning pass: *"No hesitation anywhere in the stack. Line kept
  moving. I've stopped expecting anything else from you."*

## 4. Candidates

Everyone at the gate wants a courier bond (§0). They come from around the
port and beyond it: stevedores, crane operators, customs brokers, shipping
clerks, port IT, a night watchman, a student from the maritime college,
security people whose reports now travel by ship.

- **Flavor evenly across every archetype.** #78 broke the link between an
  archetype's voice and its ground truth. If honest candidates talk more like
  dockworkers than dishonest ones, the idiom itself becomes a tell. Each chat
  pool should carry roughly the same dock-phrase density (the subagent checks
  this; see §8).
- **Hint lines are evidence.** Where a chat line is the tell for a violation
  (`hint_lines`, `forced_chat`), rewrite the wrapping, never the clue.
- **Dark Web escalation stays:** early flippant ("lol, paperwork. who still
  checks manifests?"), mid bold, late open contempt ("we both know who actually
  runs this pier").
- Example warm line: *"hi — sorry, first time on this pier."*

## 5. Word banks

In-world organisations replace real ones. Real consumer email providers stay,
mixed with in-world ones. **Naming carries meaning**, so the player can learn a
category by its sound:

| Category | Naming convention | As shipped (2026-09-24) |
|---|---|---|
| Elite affiliations (unfakeable, quick admit) | Institutional, harbour-authority weight | Port Authority CERT · Tidewater Signals Lab · Bayside Naval Cyber Institute · Harbormaster's Office Network Defense · Meridian Shipping Security Operations · Northreach Maritime Research Institute · Lighthouse Foundation for Secure Systems |
| Ordinary affiliations (fakeable) | Local, unglamorous, dockside | Saltmarsh Community College CS Dept. · Westmore Maritime Polytechnic Security Lab · Pier Street Public Library Tech Branch · Aegir Cybersecurity Cooperative · Cordova Nautical College — Independent Study |
| Thin affiliations | Plain — they must read as thin | Freelance Security Researcher · Independent Hobbyist · Self-employed · Personal project · Between contracts |
| Trusted mail | Real consumer + ordinary port names | gmail.com · outlook.com · yahoo.com · icloud.com · hotmail.com · live.com · fastmail.io · portmail.net · harborline.com · pier9.net |
| Privacy mail | Real + fog / quiet names | protonmail.com · proton.me · pm.me · tutanota.com · fogbank.me · quietharbor.net |
| Disposable mail | Real + *thrown-overboard* names | mailinator.com · guerrillamail.com · yopmail.com · flotsam.io · jetsam.email · driftwood.mail · bilgebox.org · castoff.net |

Rules for the banks:

- **No in-world name may sound like another category.** Anything about junk,
  waste or castoffs is disposable. Fog and quiet are privacy. Ordinary place
  names are trusted. Never reuse a root across two categories (e.g. no
  `tidewater.net` domain while Tidewater Signals Lab is elite).
- **Every elite org needs a handle** in `_ELITE_ORG_HANDLE`, and the handle must
  stay long enough for `_typosquat` to produce a Levenshtein 1–2 lookalike.
- Word banks are **owned by `candidate_gen`, derived by `tools_bridge`**. A
  rename is a `rules-evidence` job; this guide supplies the names only.
- Request purposes and image filenames get the same treatment, at the same
  rate (about two in five of each pool, legit and suspect alike):
  *"escorting crane-control firmware between terminals," "a private shipment
  — can't say more,"* (a purpose is the courier run they want, §0; legit and
  suspect purposes share one grammatical shape so the phrasing isn't a tell)
  `manifest_scan.png`, `crane_cab.jpg`, `berth_7.jpg`, `bill_of_lading.png`.
- **Keep every list the generator draws from at its current length.**
  `rng.choice` over a list of a different length shifts every seeded candidate
  after the draw, so renames swap entries one for one: `DOMAINS_DISPOSABLE`
  (8), `_make_email`'s fallback pool (4), the commit-email `alt_domains` (4),
  `PURPOSES_*` (5 each), the stego filenames (18), every `_CHAT_*` pool, every
  `AFFILIATIONS_*` bank. Lists that are only *read* (`DOMAINS_TRUSTED`,
  `DOMAINS_PRIVACY`) can grow.
- The "trusted org" check in `tools_bridge` is **derived from
  `AFFILIATIONS_ELITE`** (exact match). It used to be a keyword list ("mit",
  "stanford", …) that the rename would have silently broken.
- Elite email domains keep a `.edu` / `.ac.uk` / `.gov` suffix where the old
  real one had it, because that suffix is what the sweep recognises.
- No real shipping companies, ports or unions by name, and no real institution
  as a claimed employer. **Real stays real** in the cybersecurity layer: breach
  corpora (RockYou, LinkedIn…), platforms (GitHub, Reddit…) and threat forums
  are the "every tool is real" material and are not renamed.

## 6. The rename — Overseer → The Foreman

- **Player-facing text only.** Every string a player can read says "the Foreman".
  That includes chat speaker labels, panel titles, Rules pages and the credits.
- **Code identifiers stay:** `core/overseer.py`, `overseer.json`,
  `overseer_intro_key`, `resolve_narrative` keys, test names. Renaming them is
  churn across saves, day files and tests for no player benefit. Add one
  comment at the top of `overseer.py` and `overseer.json` saying "the Overseer
  is presented to players as the Foreman."
- The docs (`CLAUDE.md`, `CONTENT_AUTHORING.md`, `UI_CATALOG.md`) note the
  mapping once.

## 7. Stego carrier art

The stego image stops being a gradient and becomes a simple harbour scene drawn
on the cell grid (30×12 up to 72×32).

**Motif library — both halves of the name, picked about equally:**
- *Docks (2026-09-24):* stacked shipping containers · a gantry-crane silhouette
  at dusk · harbour lights at night · a hull at the waterline · a lighthouse and
  its beam · fog rolling over a pier.
- *Hack (2026-09-25):* a server room with scattered status lights · an ops-room
  wall screen with operators in front · a data-centre aisle in perspective · a
  globe at night with city lights · a hooded figure at a laptop · a CCTV camera
  on a wall with its cone of view.

Screens and glows are soft fills, never text lines or scanlines; status lights
are single scattered cells, never a grid; the globe has no bright rim. (A
satellite dish was tried and cut — at 30×12 it reads as a tree.)

Hard constraints, because the image is a puzzle surface:

1. **Colour.** Stamped carrier cells are amber, crimson and violet; confirmed
   clean cells get a green wash. The base art uses a **muted** palette: dusk
   navy, steel grey, faded teal, dull brick, fog white. Measured as chroma
   (brightest channel minus dimmest): every reveal colour is 140 or more, every
   scene cell is at most `stego_scenes.MAX_CHROMA` (72), and no scene cell is
   green-dominant.
2. **Shape.** The special carriers are a **cross**, a **closed ring** and
   **parallel slashes**. No motif may contain those forms at a readable scale:
   no anchors, life rings, portholes, rope coils, rigging cross-hatching or
   diagonal crane arms. Crane silhouettes stay upright and blocky.
3. **Spectral Lens contrast.** The upgrade tints its region bluer. Scene blue
   is capped at `stego_scenes.BLUE_CEILING` (200) so the tint always lifts a
   cell by at least 45.
4. **Determinism.** Motif choice and its details draw from a **new, separately
   seeded RNG** (its own XOR constant). The existing `rng` draw order in
   `build_stego_image` must not change: `style`, `noise_grid`, the zone and the
   carrier must come out identical, so `hackdox lab` seeds keep reproducing.
5. **Carrier stays invisible until stamped.** The art lives only in `base_rgb`;
   nothing about it may correlate with where the zone sits.

Shipped as `core/stego_scenes.py` (twelve scenes: `DOCK_MOTIFS` then
`CYBER_MOTIFS` — append new ones, never reorder; `StegoImageData.motif`
names the one drawn). `tests/test_stego_scenes.py` holds all five rules,
including a pinned fingerprint of the payload layout taken from the
pre-scene generator.

## 8. PG and banned content

- Gritty is fine: long hours, sore backs, bad coffee, rust, salt, a dirty job.
  **No profanity.** Mild substitutes only: *for crying out loud, blasted,
  heck of a shift.*
- **Not pirates.** Banned: *arr, matey, ahoy, avast, shiver me timbers,
  landlubber, yo-ho, walk the plank, scallywag, booty.* Longshoremen are working
  people on a modern container terminal, not a costume.
- No slurs, no real people, no real companies, ports or unions by name.
- These checks are real tests in `tests/test_voice.py`: the banned-word list
  against all player-facing prose; dock-phrase density per chat pool within
  0.20 of the others (and none at zero); no dock idiom in any rule `text`; the
  Foreman's dialogue at or above a 30% flavor rate; no player-visible
  "Overseer"; only in-world organisations as claimed employers; exactly the
  elite orgs recognised as trusted; every elite handle typosquattable; no
  domain root shared across categories. The machine-checked glossary lives in
  that file — grow it when this guide's glossary grows.
