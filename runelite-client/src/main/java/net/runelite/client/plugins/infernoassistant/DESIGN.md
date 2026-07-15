# Inferno Assistant — Design

Status: design only, no implementation yet. This document is the concrete
plan referenced by `research/INFERNO_MECHANICS.md`'s Part 2 ("outline-level
notes ... not an implementation plan"); it turns those notes into an
actionable design for a real plugin.

## 1. Goal & Scope

A live, reactive RuneLite overlay that tells the player which protection
prayer to have active *right now*, keeps that recommendation up to date as
the player and NPCs move, and shows a short predictive queue of upcoming
prayer switches with tick countdowns — prioritizing the highest-damage
threat when two NPCs attack on conflicting, overlapping ticks.

**In scope (v1):**
- Standard Inferno wave roster only: mager, ranger, meleer, blob, bat,
  nibbler (per `MOB_DEFS` in `research/AUTOZUK/index.html:375-385`).
- Per-tick recomputation of LOS, range, and attack-eligibility for every
  live NPC.
- A 6-tick lookahead prediction window.
- Conflict resolution by highest expected damage, with unmitigated threats
  explicitly surfaced rather than hidden.
- Single in-world overlay box, config-driven colors/toggles.

**Out of scope (v1) — explicitly deferred, not silently dropped:**
- JalTok-Jad / Zuk boss-fight mechanics (AUTOZUK doesn't model these
  either — see `INFERNO_MECHANICS.md`, "What's not modeled").
- Tick-perfect prayer-flick optimization (activate-on-tick-X for 1-tick
  flicks to save prayer points). v1 only recommends holding a prayer.
- Audio/visual alert cues on switch or on conflict.
- Any auto-activation of prayers — this fork has no automation layer
  (see root `CLAUDE.md` "Goal"); the plugin only ever *displays* a
  recommendation, it never presses a prayer for the player.

## 2. Architecture Overview

```
GameTick
   │
   ▼
[1] Refresh NPC + pillar state       (ported from inferno-scouter)
   │
   ▼
[2] LOS check: player ↔ each live NPC (ported raycast/blocked-grid from AUTOZUK)
   │
   ▼
[3] Per-NPC attack-eligibility timer  (ticks-since-last-attack vs atkSpeed,
   │                                   + special-mechanic state machines)
   ▼
[4] Build threat list: NPCs with LOS + in range + attack-eligible soon,
   │  each as (ticksUntilHit, style, expectedDamage)
   ▼
[5] Conflict resolution: for each tick in the 6-tick window, if multiple
   │  conflicting styles land, pick highest-expectedDamage style to
   │  recommend; mark the rest "unmitigated"
   ▼
[6] Overlay render: current required prayer (or conflict line) + queue
```

Steps [1] and parts of [2] reuse `inferno-scouter`'s existing tracking
rather than being re-derived (see §3). Steps [2]-[6] are new.

## 3. Reused Foundations

Do not re-derive these — port/reuse the existing, working logic:

- **NPC identification & coordinate mapping** — `typeFor()`
  (`InfernoScouterPlugin.java:1066-1086`), `ALLOWED_NPC_IDS`
  (`InfernoScouterPlugin.java:81-89`), region→grid conversion via
  `REGION_X_OFFSET=17` / `REGION_Y_OFFSET=46`
  (`InfernoScouterPlugin.java:59-60`), and `pillarSlotFor()`
  (`InfernoScouterPlugin.java:818-838, 840-857`).
- **Pillar alive/HP tracking** — `alivePillars`, `pillarHpBySlot`,
  `updatePillarHpFromNpcs()` (`InfernoScouterPlugin.java:110-111, 859-893`),
  and `pillarHpFor()` (`InfernoScouterPlugin.java:928-953`), which reads live
  HP off the pillar's associated NPC health ratio — no need to reimplement
  pillar-collapse detection.
- **`MOB_DEFS` attack table** (`research/AUTOZUK/index.html:375-385`) —
  size, HP, attack speed, range, style, per NPC type. Static game constants;
  port verbatim as a Java enum/lookup, not read live.
- **LOS engine** — `hasLineOfSight`/`raycast`
  (`research/AUTOZUK/index.html:490-505`): blocked-tile bitmap approach,
  driven from live pillar-alive state instead of AUTOZUK's precomputed
  array; melee uses the closed-form adjacency check
  (`isWithinMeleeRange`, `index.html:508`), ranged/magic use the
  fixed-point Bresenham raycast with the corner-clip rule described in
  `INFERNO_MECHANICS.md` ("Line of sight").
- **Projectile delay tables** — `MONSTER_PROJECTILE_HIT_TICKS`
  (`research/AUTOZUK/index.html:446-452`), needed verbatim for the
  ticks-until-hit-lands countdown.
- **Special-mechanic rules** — secondary melee proc
  (`canUseSecondaryMelee`/`isWithinSecondaryMeleeRange`,
  `index.html:509-516`), blob scan/fire 6-tick cycle
  (`hlMobAttack`, `index.html:909-913`), mager flicker tell
  (`hasFlicker`, `index.html:903-907`), meleer dig-to-player
  (`hasDig`, `index.html:860, 871`) — all encoded as-is per
  `INFERNO_MECHANICS.md`.

## 4. Data Model

Per live NPC, track:

```
NpcThreatState {
  npcIndex, mobType (enum: MAGER/RANGER/MELEE/BLOB/BAT/NIBBLER)
  footprint (SW tile + size)
  ticksSinceLastAttack
  hasLos: boolean               // recomputed every GameTick
  inRange: boolean              // Chebyshev distance <= MOB_DEFS[type].range
  // special-mechanic state
  blobPhase: SCAN | FIRE | null // only for BLOB, drives reactive style pick
  blobPhaseTicksRemaining
  magerFlickerTell: boolean     // one-tick "about to act" flag
  meleerDigCounter: int         // negative attackDelay accumulator when no LOS
}
```

Player-side per-tick state: current tile (SW corner, size 1), current
active protection prayer (read from `Client` prayer state).

## 5. Threat Prediction Algorithm

Each `GameTick`:

1. For every tracked NPC, recompute `hasLos` and `inRange` against the
   player's current tile using the ported LOS engine (§3).
2. Advance each NPC's `ticksSinceLastAttack`; if it reaches
   `MOB_DEFS[type].atkSpeed` and `hasLos && inRange`, it's eligible to fire
   this tick — reset the counter and schedule a predicted hit at
   `now + MONSTER_PROJECTILE_HIT_TICKS[type][distance]`.
3. Apply special-mechanic caveats to refine the predicted style/timing:
   - **Blob**: does not use `atkSpeed` for cadence — model explicitly as
     a 6-tick scan(3)→fire(3) loop. The style shown for a predicted blob
     hit is resolved **at the scan tick** using the *currently held*
     protection prayer at that moment (whichever style it does *not*
     block), not a coin flip — matching `calcSimDamage`'s reactive rule.
   - **Secondary melee**: for mager/ranger/blob, if the player is
     footprint-adjacent (including diagonally) at prediction time, flag the
     predicted attack as "may resolve as melee instead" (50% chance) rather
     than asserting the base style with certainty.
   - **Mager flicker**: when `attackDelay == 1 && hasLos` (the one-tick
     tell), surface this NPC as "about to act" one tick before the
     prediction fires, since 10% of the time it revives another mob instead
     of attacking (doubled delay) — the overlay should not treat a missed
     prediction here as a bug.
   - **Meleer dig**: if `!hasLos`, accumulate `meleerDigCounter` downward;
     once it passes the dig thresholds from `INFERNO_MECHANICS.md`, surface
     a "meleer may relocate next to you soon" warning instead of a normal
     countdown, since hiding behind a pillar only buys bounded time.
4. Collect all predicted hits landing within the next 6 ticks into the
   threat list: `(ticksUntilHit, mobType, style, expectedDamage)`.
   `expectedDamage` = the style's max hit from `MOB_DEFS` (a static
   per-type constant used purely for ranking, not a real accuracy roll).

## 6. Conflict Resolution Rule

For each tick `t` in the 6-tick window:

- If all predicted hits at `t` share one style → recommend that
  protection prayer for tick `t`.
- If predicted hits at `t` span multiple styles → recommend the prayer
  matching the **highest expectedDamage** style; every other conflicting
  style at that tick is added to an `unmitigated` list for that tick entry
  and rendered, never dropped silently (per `INFERNO_MECHANICS.md`: "a
  single prayer recommendation cannot cover two simultaneous mismatched
  styles ... surface this honestly").

## 7. Overlay Spec

Single info-box overlay (RuneLite `OverlayPanel`, anchored near the player
— same rendering approach as `InfernoStartTileOverlay` in inferno-scouter):

```
┌─────────────────────────────┐
│ Protect from Magic           │  ← current tick's recommendation
│ (Bat unmitigated — 25 dmg)   │  ← only shown when a conflict exists
├─────────────────────────────┤
│ +2  Protect from Missiles    │  ← lookahead queue, nearest first
│ +4  Protect from Melee       │
│ +5  no safe prayer (M+R)     │
└─────────────────────────────┘
```

- Top section: current required prayer, or a conflict line if the current
  tick has multiple styles.
- Queue section: up to 6 ticks ahead, each line = countdown + required
  prayer, or a flagged conflict line.
- Per-style color coding reusing `InfernoScouterConfig`'s existing
  bat/blob/melee/ranger/mager `Color` config pattern
  (`InfernoScouterPlugin.java:139-145`), applied to prayer icons/text
  instead of mob markers.

## 8. Config Options

Mirroring `InfernoScouterConfig`'s existing shape:

- `showOverlay` (boolean, default true)
- `queueLength` (int, default 6 ticks — matches the fixed lookahead window)
- `showUnmitigatedWarnings` (boolean, default true)
- Per-style colors: `mageColor`, `rangeColor`, `meleeColor` (reuse existing
  color-picker config pattern)

## 9. Testing Strategy

Per root `CLAUDE.md`'s testing rule ("every change gets new/updated tests,
happy path + edge cases"), split by testability:

**Pure, unit-testable without a live client** (write these first once
implementation starts):
- LOS raycast / blocked-grid logic — test against known pillar
  configurations (all pillars up, one destroyed, LOS through a collapsed
  pillar's tile opening immediately).
- Attack-timer countdown math — test `ticksSinceLastAttack` reaching
  `atkSpeed` produces a scheduled hit at the correct
  `MONSTER_PROJECTILE_HIT_TICKS` offset for a given distance.
- Blob scan/fire 6-tick cycle state machine — test the reactive style
  resolution against a held prayer at the scan tick, including the case
  where no relevant prayer is held.
- Secondary-melee adjacency flagging — test footprint-adjacency
  (including diagonal) triggers the "may resolve as melee" flag.
- Conflict-resolution ranking — test that mixed-style ticks pick the
  higher-`expectedDamage` style and populate `unmitigated` with the rest.

**Needs manual in-game verification** (not unit-testable):
- Overlay rendering/positioning.
- Live `NpcSpawned`/`GameTick`/`HitsplatApplied` event wiring against the
  real client.
- End-to-end accuracy of a live wave run (compare plugin recommendation
  against actual required prayer, wave by wave).

Concrete test classes/cases will be listed against actual method
signatures once implementation begins (this section describes coverage
intent, not final test names).

## 10. Open Questions / Phased Follow-Ups

Deferred, not dropped:

- **Tick-perfect flick mode** — a future toggle that shows
  activate-on-tick-X timing (using the projectile-delay tables already
  ported in §3) instead of a hold recommendation, for players who want to
  save prayer points via 1-tick flicks.
- **Audio/visual alerts** — a distinct sound cue for the "no safe prayer"
  conflict case specifically, since that's the highest-risk moment to miss
  visually.
- **Boss-wave extension** (Jad/Zuk) — would require modeling mechanics
  not present anywhere in the current AUTOZUK reference and is explicitly
  out of scope until a dedicated research pass is done.

## References

- `research/INFERNO_MECHANICS.md` — mechanics research and Part 2 outline
  notes this design implements.
- `research/AUTOZUK/index.html` (lines 365–1315) — source LOS/attack-cadence
  algorithms being ported.
- `research/inferno-scouter/src/main/java/com/infernoscouter/InfernoScouterPlugin.java`
  — existing NPC/pillar tracking foundation being reused.
