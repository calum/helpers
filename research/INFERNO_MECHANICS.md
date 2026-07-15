# Inferno Mechanics — Reference & Live Plugin Design Notes

This document explains the Inferno line-of-sight and attack mechanics as
reverse-engineered in `research/AUTOZUK/index.html` (the "sim-core" script
block, lines 365–1315), and sketches how that knowledge should be adapted
for a **live, reactive** RuneLite plugin — as opposed to AUTOZUK's own
offline, autoretaliate-assuming solver.

It draws on two sources in this repo:

- **AUTOZUK** (`research/AUTOZUK/index.html`) — a from-scratch JS
  reimplementation of Inferno wave mechanics, used to precompute an optimal
  starting tile and prayer cycle for a wave. All line numbers below refer
  to this file.
- **inferno-scouter** (`research/inferno-scouter/src/main/java/com/infernoscouter/InfernoScouterPlugin.java`)
  — a working RuneLite plugin that already reads live wave/pillar/NPC state
  via the event bus. Its coordinate mapping and pillar/NPC tracking
  patterns are the right foundation to build on.

---

## Part 1 — Inferno Mechanics

### Coordinate system

AUTOZUK works in a local **Inferno arena grid**, not raw world coordinates:

```
ARENA_X_MIN=1, ARENA_X_MAX=29, ARENA_Y_MIN=1, ARENA_Y_MAX=30   (index.html:369)
```

Every entity (player, NPC, pillar) is stored as its **south-west tile**
(`x`, `y`) plus a `size` (its footprint is `size × size`, growing north
and east from that SW corner). The 9 wave spawn tiles are a fixed array,
and the 3 pillars sit at fixed locations:

```js
SPAWN_LOCATIONS = [{x:2,y:6},{x:23,y:6},{x:4,y:12},{x:24,y:13},{x:17,y:18},
                   {x:6,y:24},{x:24,y:26},{x:2,y:29},{x:16,y:29}]        // index.html:371
PILLAR_LOCS = {S:{x:11,y:24,size:3}, W:{x:1,y:10,size:3}, N:{x:18,y:8,size:3}}  // index.html:372
```

**This is the same grid inferno-scouter already converts to/from real
`WorldPoint`s.** Don't re-derive the mapping — reuse it:

- Region → grid: `gridX = worldPoint.getRegionX() - 17`, `gridY = 46 - worldPoint.getRegionY()`
  (`InfernoScouterPlugin.java:556-557`, `REGION_X_OFFSET=17`, `REGION_Y_OFFSET=46`).
- The plugin's `pillarSlotFor()` (`InfernoScouterPlugin.java:818-838`) already
  matches game objects/NPCs to `PillarSlot.WEST/NORTH/SOUTH` at grid
  coordinates `(0,9)`, `(17,7)`, `(10,23)` — offset by one from AUTOZUK's
  `PILLAR_LOCS` because inferno-scouter's slot coordinate is the *NW*
  corner convention rather than SW; when porting AUTOZUK's LOS math, pick
  one corner convention and convert consistently rather than mixing them.

### Line of sight

LOS is computed against a **precomputed blocked-tile bitmap**, not a live
polygon/vector check — this is the key implementation trick worth copying:

```js
let blocked = new Uint8Array(4096); // 64×64 grid, index = (x<<6)|y   (index.html:597)
```

Only pillars (and the arena's outer wall ring) are marked blocked
(`createRegion`, `index.html:588-601`). NPCs and the player are **not**
LOS blockers — only movement-collision blockers. Destroying a pillar
immediately clears its 3×3 footprint from the blocked grid
(`removePillarCollision`, `index.html:603-607`), which is why LOS through a
collapsed pillar opens up the instant it dies, not after some delay.

`hasLineOfSight(region, x1, y1, x2, y2, s, r, isNPC)` (`index.html:490-497`):

1. Rejects immediately if either endpoint tile is itself blocked, or if
   the two footprints already overlap (`collisionMath`).
2. **Melee (`r===1`)**: uses a closed-form "is target tile directly
   adjacent (non-diagonal) to this footprint" check
   (`isWithinMeleeRange`, `index.html:508`) — no raycast needed, since
   melee never needs to see around a corner, only be beside the target.
3. **NPC vs player (`isNPC` true)**: recurses using the *closest point on
   the player's own footprint* to the mob (`closestTileTo`,
   `index.html:437`), because for a 1×1 player rechecking from the mob's
   perspective is equivalent and simpler.
4. **Ranged/magic (`r>1`)**: first does a cheap Chebyshev bounding-box
   reject (`Math.abs(dx)>r`), then calls `raycast()`.

`raycast(region, x1, y1, x2, y2)` (`index.html:499-504`) is a fixed-point
(16.16) Bresenham-style walk along the longer axis. The important detail
for a faithful Java port: **at every step it checks both the tile the ray
enters, and the tile it visually clips through when crossing a diagonal
boundary** on the minor axis. This reproduces OSRS's real projectile-clip
rule — a ray can be blocked by a corner pillar tile even if neither the
start nor end tile is blocked, because the line passes across the corner
of a blocking tile.

```
mobHasLOS(region, mob, target)   → melee range uses isWithinMeleeRange, else hasLineOfSight   (index.html:506)
playerHasLOS(region, px, py, mob, range) → symmetric check from the player's side   (index.html:507)
```

### Per-NPC-type attack profiles

`MOB_DEFS` (`index.html:375-385`):

| Type | Letter | Size | HP | Attack speed (ticks) | Range | Style | Special |
|---|---|---|---|---|---|---|---|
| Mager (Jal-Zek) | M | 4×4 | 220 | 4 | 15 | magic | revive/flicker |
| Ranger (Jal-Xil) | R | 3×3 | 125 | 4 | 15 | range | — |
| Meleer (Jal-ImKot) | X | 4×4 | 75 | 4 | 1 (melee-adjacent only) | melee | dig-to-player |
| Blob (Jal-Ak) | B | 3×3 | 40 | 3 (`atkSpeed`), but see below — real attack-to-attack cadence is 6 | 15 | mage/range, reactive to your prayer | scan-then-fire |
| Bat (Jal-MejRah) | Y | 2×2 | 25 | 3 | 4 | range | — |
| Nibbler | N | 1×1 | 10 | 4 | 1 | melee | pillar-attacker |

Protection prayer mapping is a direct string match: `magic → Protect from
Magic`, `range → Protect from Missiles`, `melee → Protect from Melee`
(`calcSimDamage`, `index.html:1211-1220` compares `atk.style` against the
prayer active on that tick).

**Secondary melee** — mager, ranger, and blob (not bat) each have a **50%
chance per attack, only when the player is directly adjacent to their
footprint (including diagonally)**, to instead throw a melee hit using a
separate accuracy/max-hit table (`canUseSecondaryMelee`,
`isWithinSecondaryMeleeRange`, `index.html:509-516`; rolled in
`hlFireAttack`, `index.html:925`). This means standing next to a ranged/mage
NPC does not guarantee their attacks stay ranged/magic — always be ready
for a melee proc if you're in melee range of one of these three types.

**Blob scan-then-fire** (`hlMobAttack`, `index.html:909-913`): a blob
attacks on a **6-tick cycle**, not its `atkSpeed=3`. Firing sets
`attackDelay=atkSpeed(3)`; once that expires it doesn't fire again
immediately — it re-enters a **"scan"** state (`blobScanPrayer='scanned'`)
which sets `attackDelay=atkSpeed(3)` again, and only fires once *that*
expires. So the fire→scan→fire loop is 3 ticks + 3 ticks = 6 ticks between
attacks, with the scan always starting exactly 3 ticks before the next hit
— matching the wiki's "attacks every 6 ticks; 3 ticks before each attack it
detects your protection prayer."

Style resolution is **reactive to the player's active protection prayer at
scan time**, not a blind 50/50 roll, per the wiki: the blob picks whichever
style your current prayer *doesn't* block (protect-mage up → it fires
range; protect-range up → it fires magic; no relevant prayer up → style is
effectively random). This reactive rule is what `calcSimDamage`
(`index.html:1211-1214`) actually encodes when scoring a candidate prayer
sequence: `atkStyle = (prayerOnScanTick === 'mage') ? 'range' : 'magic'`,
i.e. it evaluates "what would the blob have chosen against this specific
sequence." Note `hlMobAttack`/`hlFireAttack` (`index.html:911, 921`) record
a **blind random roll** (`S.rng()<0.5`) for `mob.currentStyle` when
generating the raw attack log during a headless sim run — that placeholder
roll is discarded and never used for scoring; only `calcSimDamage`'s
prayer-reactive resolution feeds into the actual optimization. Also note
the same adjacent-melee-proc chance (`canUseSecondaryMelee`,
`index.html:514-516`) applies to blobs too, exactly as to rangers/magers:
if you're melee-adjacent and not praying melee, a "mage/range" blob attack
can still come in as melee instead.

Practically for a live plugin: once a blob is seen scanning, you have
exactly 3 ticks before the hit resolves, and whichever protection prayer
you're holding *at the scan tick* (not the fire tick) determines which
style the blob throws — so the decision point is the scan tick, not the
moment the projectile is visibly launched.

**Mager revive/flicker** (`hasFlicker`, `index.html:903-907`): on each
eligible attack tick, a mager has a 10% chance to instead revive a
previously-killed mob (from the wave's dead-mob queue) at half its max HP,
at a random empty tile, at the cost of a doubled attack delay
(`mob.attackDelay = mob.atkSpeed*2`) instead of attacking that cycle. The
`mob.flickering` flag (used only for animation in AUTOZUK) is set the tick
*before* the mager fires (`mob.attackDelay===1 && mob.hasLOS`) — this is a
one-tick "tell" that a mager is about to act.

**Meleer dig-to-player** (`hasDig`, `index.html:860, 871`): if a meleer
has no LOS to the player (typically because you're standing behind a
pillar it can't path around), it accumulates a negative attack-delay
counter. Once `attackDelay <= -38` there's a 10%/tick chance to start a
6-tick "dig" (guaranteed at `attackDelay <= -50`); on completion it
teleports to a tile adjacent to the player's *current* position and
freezes for 2 ticks. This means hiding behind a pillar from a meleer only
buys a bounded amount of time before it relocates next to you.

**Projectile travel time** — attacks don't land the tick they're thrown.
`MONSTER_PROJECTILE_HIT_TICKS` (`index.html:446-452`) gives, per distance
from the NPC's projectile origin tile, which tick (relative to a tick-1
throw) the hitsplat lands:

```
bat:       [2,2,2,3,3]                       (dist 1..5)
ranger:    [3,3,3,3,3,4,4,4,4,5,5,5,6,6,6,6]  (dist 1..16)
mager:     [2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,6]
blobRange: [2,2,2,3,3,3,3,4,4,4,5,5,5,5,6,6]
blobMage:  [2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,6]
```

Melee attacks always resolve with `delay=1` (`monsterProjectileDelay`,
`index.html:467`). The projectile *origin* tile is not always the mob's SW
tile — e.g. a mager's origin is offset to `(mob.x+2, mob.y-2)`, the NE
tile of its central 2×2 (`monsterProjectileOrigin`, `index.html:458-464`).
This delay table is exactly what a "ticks until this hit lands" countdown
needs.

### Pillars

Pillars have HP (`PILLAR_MAX_HP=255`, `index.html:574`) and can be
targeted by nibblers (`assignNibblersToRandomPillar`,
`index.html:627-631`), which deal `floor(rand()*5)` damage per hit
(`hlMobAttack`, `index.html:900`). At 0 HP a pillar **collapses**
(`beginPillarCollapse`, `index.html:617-622`) one tick later, dealing
`floor(hp/2)`-style damage to adjacent mobs (nibblers die outright) and to
the player if they were standing adjacent when it collapsed. **The
important consequence for a live plugin: the moment a pillar's HP hits 0,
LOS through its tiles opens immediately** (`removePillarCollision`,
`index.html:603-607`) — any NPC that previously couldn't see the player
around that pillar may suddenly gain LOS the same tick.

inferno-scouter already tracks per-pillar alive/dead state and an
estimated HP percentage live (`pillarHpBySlot`, `alivePillars`,
`updatePillarHpFromNpcs`, `InfernoScouterPlugin.java:859-893`) by reading
the pillar's associated NPC health ratio — this is exactly the pillar
state a live LOS engine needs, and doesn't need to be reimplemented.

### What's *not* modeled

Despite the "AUTOZUK" name, there is no Jad-style flinch mechanic and no
JalTok-Jad/Zuk boss simulation anywhere in the code — it only models the
standard wave roster (mager/ranger/meleer/blob/bat/nibbler/bloblets) and
pillar mechanics. Don't assume boss-wave coverage exists if referencing
this code for boss-fight tooling.

---

## Part 2 — Plugin Design Notes

These are outline-level notes to inform a future implementation session —
not an implementation plan.

### Why AUTOZUK's algorithm doesn't transfer directly

AUTOZUK's `optimizePrayer()` (`index.html:1040-1112`) does **not** compute
a live per-tick decision. It runs many full headless simulations of a wave
in advance (assuming a fixed start tile and autoretaliate combat), records
every attack event with its `tick`, and then picks a single **static
4-tick prayer loop** — `sequence[tick % 4]` — that minimizes average
damage across those simulated replays (`calcSimDamage`,
`index.html:1121-1259`). It works because autoretaliate + a fixed starting
tile makes NPC attack timing fall into a predictable, repeating pattern.

A manual-play plugin breaks that assumption: the player moves and picks
targets freely, so which NPCs have LOS, which are in range, and their
attack-cycle phase relative to real time are all in flux. The plugin needs
a **live, per-tick reactive check** instead: every `GameTick`, recompute
which NPCs currently threaten the player and how soon, rather than reading
from a precomputed cycle.

**Multi-attacker overlap is a real limitation, not an edge case to
special-case away.** Because LOS/range change every tick, it's entirely
possible for two NPCs of different styles to both threaten the player on
overlapping ticks (e.g. a ranger and a mager both about to land a hit one
tick apart). A single prayer recommendation cannot cover two simultaneous
mismatched styles. The design should surface this honestly — e.g. flag
"no fully safe prayer this tick" or prioritize the higher-expected-damage
threat — rather than silently picking one threat and hiding the other.

### Reusable pieces (port to Java)

- **`hasLineOfSight` / `raycast`** (`index.html:490-505`) — port the
  blocked-tile-grid + fixed-point raycast approach, but drive the
  "blocked" set from live `Scene`/`Tile` pillar state (via
  inferno-scouter's `pillarSlotFor`/`alivePillars`) instead of JS's
  precomputed array. This is the core "does NPC X currently see me"
  primitive the plugin needs every tick.
- **`MOB_DEFS`** (`index.html:375-385`) — the attack-speed/range/style
  table can be hardcoded identically in Java (these are static game
  constants, not something to read live).
- **Projectile delay tables** (`MONSTER_PROJECTILE_HIT_TICKS`,
  `index.html:446-478`) — needed verbatim for the tick-countdown UI once
  an attack is detected/predicted.
- **Secondary-melee / blob-scan / mager-flicker / meleer-dig rules**
  (`index.html:509-516`, `909-913`, `903-907`, `860,871`) — encode as-is;
  these determine *which* style to actually expect, not just whether an
  NPC is "in range."

### What the plugin needs that AUTOZUK doesn't have

AUTOZUK never needs to predict *when* an NPC will next attack in real
time — it just replays pre-rolled simulated events. The live plugin does
need this, to produce the tick countdown the user asked for. That means
tracking, per live NPC:

- Ticks since its last attack vs. its `atkSpeed` (from `MOB_DEFS`), to
  know how many ticks until it's next attack-eligible.
- Its current LOS/range state (recomputed every tick via the ported LOS
  check above) — an NPC that's attack-eligible but has no LOS/range poses
  no threat yet.
- Whichever "tell" mechanics apply (blob scan tick, mager flicker tick) to
  refine the countdown once a special state is observed.

inferno-scouter's `HitsplatApplied` and `GameTick` subscriptions
(`InfernoScouterPlugin.java:340-366`) are the closest existing pattern in
this repo for observing NPC attack cadence live, and its pillar tracking
gives LOS-relevant state for free.

### Suggested rough shape (illustrative, not binding)

An overlay-based plugin that, every `GameTick`:

1. Reuses inferno-scouter's tile-grid conversion and pillar/NPC tracking
   as a foundation rather than re-deriving it.
2. Recomputes LOS (ported `hasLineOfSight`) from the player's current tile
   to every live NPC, using current pillar-alive state.
3. For each NPC with LOS and in range, estimates ticks-until-next-attack
   from its attack-speed timer, applying the special-mechanic caveats
   above (blob scan, secondary melee chance, mager flicker).
4. Surfaces the required prayer (or "no safe prayer" when styles
   conflict) and a tick countdown to next required activation, as an
   overlay near the player.
