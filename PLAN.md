# PLAN.md — Living Research & Planning Document

Updated after each session. Add findings at the top of each section; never delete history.

This file was reset on 2026-07-15 when the project pivoted away from the
GameBridge bot/automation layer to writing small custom "helper" plugins.
The prior research log (bot routines, fight-tuning, pathfinding) is no
longer relevant and was removed; general RuneLite internals knowledge that's
still useful lives in [ARCHITECTURE.md](ARCHITECTURE.md) and [CLAUDE.md](CLAUDE.md).

Each session entry should follow this shape:

```
## Session: YYYY-MM-DD — <short title>

### Goal

### Findings / Decisions

### Tests

### Open / next steps
```

---

## Session: 2026-07-16 — Inferno Assistant debug logging + armed-warning

### Goal

Debug why Inferno Assistant's overlay showed "No threats" during a live
wave 4 run despite visible bats/blob, then act on what the debug log
revealed.

### Findings / Decisions

- Added `InfernoAssistantDebugLogger` — a dedicated file logger
  (`<RuneLite dir>/logs/inferno-assistant-debug.log`), gated by a new
  `debugLogging` config checkbox (`InfernoAssistantConfig`), wired through
  `InfernoAssistantPlugin`'s `onNpcSpawned`/`onNpcDespawned`/`onGameTick`.
- A wave 1 capture with debug logging on showed the plugin working as
  designed: NPCs get tracked, `hasLos`/`inRange` flip correctly, and
  predictions/queue resolve as expected. The `TzHaar-*` name spam early in
  the log is just the normal TzHaar Fight Cave/city NPCs outside the arena
  region (id 9043) being correctly ignored — not a bug.
- The real issue the user hit: an NPC (the bat) had its attack cooldown
  already expired well before it gained LOS, so the instant it saw the
  player it fired the *same tick* LOS was gained — the earliest possible
  warning the reactive-only model could give was "+1" (this tick, hit
  lands next tick), which isn't enough real-world reaction time. The
  plugin's model only starts predicting once `hasLos` is already true; it
  has no way to warn *before* LOS is gained without full movement
  prediction (explicitly out of scope for v1 per DESIGN.md).
- Fix implemented: a new "armed" warning surfaced whenever an NPC's attack
  timer has already expired (`ticksSinceLastAttack >= atkSpeed`) but it
  currently lacks LOS/range — i.e. "this NPC will hit you the instant it
  sees you." This is real advance warning obtainable without movement
  prediction, since the cooldown-expired state is already tracked.
  - `ThreatPrediction.armedWarning(...)` — new factory, `armed` field.
  - `ThreatPredictor.advanceStandard` — emits an armed warning instead of
    silently returning when out of LOS/range and cooldown expired.
    Excluded for `hasDig` mobs (meleer) since they already get a distinct
    "may relocate soon" warning from the dig-counter mechanic — showing
    both would be redundant.
  - `ConflictResolver`/`ConflictResolution` — armed warnings routed
    alongside `meleerDigWarnings` as a separate list, surfaced at tick 0.
  - `InfernoAssistantOverlay` — renders `"<MobType> armed (no LOS)"` lines.
- Did not touch `ProjectileHitTicks.delayFor`'s `hitTick - 1` math — no
  evidence from the log of an actual off-by-one there; the "+1 was too
  late" complaint is fully explained by the no-forward-LOS-warning gap
  above, not a delay-table bug. If this needs re-litigating, correlate
  `HitsplatApplied` tick numbers against predicted `ticksUntilHit` (not yet
  added — user asked to prioritize the armed-warning fix instead).

### Tests

- `InfernoAssistantDebugLoggerTest` — no-op before open, session
  header/footer + parent-dir creation on open, formatted writes, idempotent
  open, no-op close/log after close.
- `ThreatPredictorTest` — added `armedWarningSurfacedWhenCooldownExpiredButNoLosOrRange`,
  `armedWarningNotSurfacedWhenCooldownNotYetExpired`; updated
  `attackTimerNotResetWhenOutOfLosOrRange` (cooldown no longer expired in
  that fixture, since it now exercises the armed-warning path separately).
- `ConflictResolverTest` — added `armedWarningSurfacedAtTickZeroWithNoRecommendedStyle`,
  `armedWarningDoesNotSuppressActualAttackAtSameTick`.
- Full suite run by the user locally (not re-run in-session — gradle test
  startup is slow); user confirmed passing after the debug-logger addition.
  Re-run recommended after the armed-warning change before next live test.

### Open / next steps

- Re-test live in the Inferno with `debugLogging` on to confirm the armed
  warning actually gives usable advance notice for primed NPCs.
- If the "+1 felt too late" complaint persists even with armed warnings
  covering the primed-on-first-sight case, add `HitsplatApplied` debug
  logging to correlate predicted-hit ticks against actual hitsplat ticks
  and settle definitively whether `ProjectileHitTicks.delayFor` has a real
  off-by-one.
- Consider whether nibblers should be excluded from armed-warning noise
  (they target pillars, not the player) — left in for now since the
  existing model doesn't special-case nibbler targeting at all.
