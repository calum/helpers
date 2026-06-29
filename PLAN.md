# PLAN.md — Living Research & Planning Document

Updated after each session. Add findings at the top of each section; never delete history.

---

## Session: 2026-06-29 — Inline healing into Brutus's combat states (remove the dedicated "healing" state)

### Goal

User asked: does the "healing" state mean detection and the eat click happen
on different ticks? Yes — `Routine.tick()` (`scripts/gamebridge/routines/base.py`)
calls exactly one state method per incoming tick message and a returned state
name only takes effect on the *next* call, so `find_target`/`fighting`/
`looting` returning `"healing"` cost a full ~600ms tick of pure
detection-only delay before the eat click in the old `healing()` state ever
fired. Asked to rewrite so eating and the state's normal action (attack/dodge/
loot) both happen within the same tick when both are needed.

### Findings / Decisions

- **The engine does not enforce "one action per tick"** — that was purely an
  artifact of this routine's own state-machine design, not a constraint from
  `DecisionEngine`. `decision/engine.py`'s threaded mode (`ingest()`/`drive()`
  on separate threads) always has `drive()` react to the *latest* published
  `GameState` snapshot regardless of how long the previous `drive()` call
  blocked — so a state method calling two blocking controller actions
  (`click_inventory_item` then `click_live`) back-to-back is architecturally
  safe; it doesn't desync ticks or build a backlog, it just means no fresher
  telegraph data is read until both actions finish (the same exposure a
  single blocking click already has today).
- **Fix**: replaced the separate `healing` state with an inlined
  `_maybe_eat(game, ctrl) -> bool` helper, called at the top of
  `find_target()`/`fighting()`/`looting()` (after `set_attention_level`,
  before each state's own logic). It performs the same cooldown-gated
  (`EAT_COOLDOWN_TICKS`/`_last_eat_tick`) trout→salmon eat click the old
  `healing()` state did, then **falls through** into that same call's normal
  logic — so a low-HP tick now eats *and* attacks/dodges/loots in one call
  instead of freezing for a tick on detection.
- Removed `BrutusFighterRoutine.healing()` and the `_return_state` field
  entirely — no longer needed since there's no state to return to.
- No Java file under `runelite-client/.../plugins/gamebridge/` was touched, so
  no `GAMEBRIDGE.md` update was needed (per CLAUDE.md's Game Bridge
  maintenance rule).

### Tests

Renamed `TestHealing` → `TestMaybeEat` in `test_brutus_fighter.py`, rewriting
its eat-click tests to call `r._maybe_eat(game, ctrl)` directly instead of the
removed `r.healing(game, ctrl)`. Replaced the three "redirects to healing"
tests (`find_target`/`fighting`/`looting`) with tests asserting *both* the eat
click and that state's own action (e.g. `click_entity`/`click_widget` for
looting) fire from a single call when a food-bearing inventory/widget fixture
is given. Removed the now-defunct `test_healing_sets_combat_attention`.
Full suite: 1422 passed, 10 skipped (`python -m pytest scripts/gamebridge/tests/ -v`).

---

## Session: 2026-06-29 — Fix: Brutus dodge cold-start miss (subscribe-then-immediately-read race)

### Goal

Live testing showed Brutus's special-attack dodge missing and landing real
damage even when the routine logged "dodging now" — production log included
`Dodge tile (10588, 2428) not yet on-screen — skipping this dodge click`.
User's first proposal was to pre-subscribe to every tile in a 6-tile radius
around the player/Brutus at fight start so clickboxes are always warm.

### Findings / Decisions

- **Hard cap discovered**: `GameBridgePlugin.MAX_SUBSCRIPTIONS_PER_CLIENT = 20`
  (`runelite-client/.../gamebridge/GameBridgePlugin.java:64`). Subscriptions
  past the cap are silently dropped server-side (`handleSubscribe`, only a
  `log.warn`) — Python receives no error/signal that a subscribe was
  rejected. A 6-tile radius is `(2*6+1)^2 = 169` tiles — ~8x over budget, so
  most of that radius would fail invisibly.
- **Per-subscription compute cost is cheap, not the binding constraint**:
  `TickMessageBuilder.findTile()` is a single `Perspective.getCanvasTilePoly`
  call per subscription per `ClientTick` (~20ms) — the 20-sub cap, not
  compute cost, is what rules out a wide radius.
- **`_compute_dodge_tile` only ever produces 4 possible tiles** (the corners
  3 tiles out from Brutus's centre along each diagonal) — a radius was never
  actually necessary; only those 4 ever get clicked.
- **Real root cause of the miss**: `_click_dodge_tile` previously called
  `ctrl.subscribe_to_tile(...)` and then immediately `ctrl.hull_update(...)`
  in the same call, at the exact moment a telegraph was first detected. The
  subscribe message and the first `hullUpdate` push are an async TCP round
  trip, so the very first dodge of every fight had zero lead time — the
  "not yet on-screen" skip was the existing safety check correctly firing on
  a subscription that had never had a chance to receive data.
- **Decision (user-confirmed)**: rather than a wide radius requiring a Java
  cap change, keep the 4 actual candidate dodge tiles (`DODGE_TILE_SUB_IDS`:
  `nw`/`ne`/`sw`/`se`) subscribed continuously every tick of `fighting()` —
  not just reactively inside the dodge-click gesture — well inside the
  20-sub budget (4 dodge tiles + Brutus NPC sub + click-target sub + tooltip
  placeholder ≈ 7 total). `_compute_dodge_tile` split into `_safe_tiles`
  (all 4 corners) + `_nearest_safe_tile_key` (picks one), with
  `_compute_dodge_tile` kept as a thin wrapper for backward compatibility.
- No Java file under `runelite-client/.../plugins/gamebridge/` was touched,
  so `GAMEBRIDGE.md`/`ARCHITECTURE.md` did not need updating (per CLAUDE.md's
  Game Bridge maintenance rule, scoped to Java-side schema changes only).

### Tests

Added `TestDodgeTileWarmup` (warm-up assertion across all 4 corners every
tick regardless of telegraph state, plus a regression test simulating several
no-telegraph ticks before the first telegraph to prove the cold-start miss no
longer reproduces) and `test_safe_tiles_returns_all_four_corners` /
`test_nearest_safe_tile_key_picks_nw_for_fixture_player_position` to
`TestComputeDodgeTile`. Updated existing click-plumbing tests to key off
`DODGE_TILE_SUB_IDS["nw"]` instead of the removed single `DODGE_TILE_SUB_ID`.
Full suite: 1420 passed, 10 skipped (`python -m pytest scripts/gamebridge/tests/ -v`).

### Open / next steps

- If Brutus ever moves significantly mid-fight (not yet observed), the 4
  corners are recomputed fresh every tick from his live position, so this
  should track him — but worth confirming against another recorded fight.

---

## Session: 2026-06-29 — Fix: Brutus dodge re-clicked every telegraph tick / lost time dodging; dodging→fighting doc & test fallout

### Goal

`BrutusFighterRoutine.fighting()` had two outstanding in-code TODOs from a
prior session's merge of a separate `"dodging"` state into `fighting()`:
1. The dodge-tile click fired on *every* tick the telegraph animation was
   showing (no debounce), and the routine never reached its wait/re-engage
   logic until the animation changed — "clicks the dodge tile twice"/"spends
   the whole snort sequence dodging".
2. The user's own attempted fix (gating the telegraph-detection branch itself
   on `not self._dodge_clicked`) caused Brutus's special to actually land.
3. The module docstring/state diagram still described a separate `"dodging"`
   state, and `test_brutus_fighter.py` (added in the same original commit as
   the routine) called a `dodging()` method that has never existed in this
   repo's history — 16 of its 48 tests were failing with `AttributeError`.

The user had already live-tested the merged design and confirmed it beats
Brutus successfully, so this session was about the two TODOs and the
doc/test cleanup, not re-validating the overall approach.

### Findings / Decisions

- **Root cause of the no-debounce bug**: the telegraph branch unconditionally
  clicked the dodge tile, set `_dodge_clicked = True`, and reset
  `_dodge_tick = game.tick` on *every* tick the animation was in
  `SPECIAL_TELL_ANIMS`, then unconditionally `return`ed — so the
  wait-then-reengage logic a few lines below was unreachable for as long as
  the animation kept showing.
- **Why the user's own `not self._dodge_clicked` fix missed dodges**: gating
  *entry* to the whole telegraph branch on that flag meant that once
  `_dodge_clicked` was set True on first sighting, every subsequent tick
  (even while the animation was still telegraphing) fell straight through to
  the wait/re-engage logic — which could count down and attempt to re-engage
  while the telegraph's danger window was still active, walking the player
  back into the hit.
- **Resolved the "wait until clear, or wait a fixed N ticks?" ambiguity with
  real data**: the user re-analysed a recorded fight and supplied exact
  per-tick `animation` values for both specials. Both telegraphs hold their
  animation for several consecutive ticks, then drop to `-1` briefly (Slam's
  telegraph — animation 13785 in this recording — then restarts for several
  pulses, matching the "repeated 3 times" framing). The user's own analysis:
  re-engaging is safe "on the tick the animation is back to `-1`" — i.e. wait
  for the telegraph animation to actually clear, with **no additional fixed
  buffer** needed afterward (the recording shows damage lands while the tell
  is still displaying, so by the time it clears it's already safe).
- **Fix** (`scripts/gamebridge/routines/examples/brutus_fighter.py::fighting`):
  - The telegraph branch now only fires `_click_dodge_tile` once per episode,
    gated on `if not self._dodge_clicked:` *inside* the branch (not gating
    branch entry) — so the branch still unconditionally `return`s `"fighting"`
    every tick the animation persists, correctly blocking the re-engage check
    below for the whole telegraph (and, for Slam, across its repeating
    pulses) without re-clicking the tile.
  - Removed `DODGE_WAIT_TICKS` (the fixed post-telegraph buffer) and
    `_dodge_tick` entirely — both became dead code once "wait for the
    telegraph branch to stop firing" is itself the correct wait condition.
    The re-engage check (`if self._dodge_clicked and self.click_live(...)`) now
    runs immediately on the first tick the animation leaves
    `SPECIAL_TELL_ANIMS`, retrying every tick thereafter until the click lands
    (unchanged retry semantics, just without the extra fixed delay first).
  - Updated the module docstring: removed the stale top-of-file TODO,
    collapsed the state diagram's separate `dodging` box into `fighting`'s own
    self-loop, dropped `dodging` from the `healing`-reachability list, and
    rewrote `fighting()`'s own docstring paragraph to describe the
    debounce/animation-clear behaviour instead of the old "why dodging can't
    be its own state" framing.
- **Test fallout** (`scripts/gamebridge/tests/test_brutus_fighter.py`):
  - Fixed 3 assertions in `TestFightingTelegraphDetection` expecting
    `result == "dodging"` → `"fighting"`; added
    `test_does_not_reclick_dodge_tile_while_telegraph_animation_persists` and
    `test_stays_dodging_no_matter_how_long_the_telegraph_persists`.
  - Replaced `TestDodging` (which called the nonexistent `dodging()` and had
    two pre-existing off-by-one bugs in its expected `_compute_dodge_tile`
    tuples, masked until now by the `AttributeError` firing first) with three
    focused classes: `TestComputeDodgeTile` (pure geometry, expected tuples
    corrected to the actual nearest-of-four-corners result),
    `TestDodgeTileClickPlumbing` (subscribe/click/skip-fallback behaviour,
    driven through `fighting()` with a telegraphing NPC), and
    `TestReengageAfterDodge` (immediate re-engage once the animation clears,
    retry-on-failed-click, and death-mid-dodge → `"looting"`, driven through
    `fighting()` with a non-telegraphing NPC and `_dodge_clicked` pre-seeded).
  - Retargeted `TestAttentionLevel.test_dodging_sets_combat_attention` →
    `test_fighting_sets_combat_attention_while_reengaging_after_a_dodge`.

### Tests

`python -m pytest scripts/gamebridge/tests/test_brutus_fighter.py -v` → 48
passed (was 32 passed / 16 failed before this session). Full suite:
`python -m pytest scripts/gamebridge/tests/ -q` → 1417 passed, 10 skipped
(unchanged from before this session — no regressions elsewhere).

### Open / next steps

- Still only verified at the unit-test level for the *timing* fix — the
  debounce behaviour itself was already confirmed live (user beat Brutus
  before this session), but the "no extra wait, re-engage immediately on
  animation clear" change removes a buffer that was previously masking any
  one-tick race between the animation clearing and Brutus actually being
  re-clickable. Worth a live re-test to confirm re-engagement still lands
  cleanly without the old buffer.
- The recording data the user supplied labels animation 13778 as the
  "Charge" tell and 13785 as "Slam" — the *opposite* pairing from the module
  docstring's prior growl/snort naming. Updated the docstring's animation-ID
  bullet list to drop the now-unverified growl/snort flavour text rather than
  guess at the correct mapping; doesn't affect behaviour since both IDs are
  handled identically via `SPECIAL_TELL_ANIMS`, but worth confirming the
  correct charge/slam↔anim-id pairing if it's ever needed for per-special
  logic.

---

## Session: 2026-06-28 — Real tile clickboxes (`"tile"` subscription kind) for Brutus dodge

### Goal

`BrutusFighterRoutine`'s dodge-click didn't move the player. Two prior fixes
(FOV/viewport-widget projection, then a Python-side geometric pixel estimate
anchored on Brutus's own hull) both failed in live play. User directed
switching to a real, plugin-computed tile clickbox: a new `"tile"` kind on
the existing GameBridge live-subscription protocol, reusing
`Perspective.getCanvasTilePoly` (already used internally by
`TickMessageBuilder.serializeGroundItem`). Full design rationale and the
rejected alternatives are recorded in
[`BRUTUS_TILE_CLICKBOX_PLAN.md`](BRUTUS_TILE_CLICKBOX_PLAN.md) at the repo
root (handoff doc from the session that hit the context-compaction boundary;
left in place for the historical record).

### Findings / Decisions

- **Java side** (`GameBridgePlugin.java` / `TickMessageBuilder.java`):
  - `Subscription` gained `worldX`/`worldY`/`plane` (nullable `Integer`)
    fields and an 8-arg constructor; `handleSubscribe` now branches on
    `kind == "tile"` to require `worldX`/`worldY` instead of `id`/`name`.
  - `TickMessageBuilder.findTile(subId, worldX, worldY, plane)` resolves
    `plane` to `client.getPlane()` when omitted, builds a `WorldPoint`,
    calls `LocalPoint.fromWorld(client, wp)` — `null` (wrong plane or out of
    loaded scene) collapses to `found: false`, same semantics as
    `findNearest`. On success it calls `Perspective.getCanvasTilePoly` and
    reuses the on-screen/centroid projection logic.
  - Extracted `applyHullFields`'s onScreen/centroid logic into a shared
    `projectHull` helper, used by both `applyHullFields` (npc/object/player/
    groundItem — still gated by `hullFilter`) and a new `applyTileHullFields`
    (tile — hull always populated when on-screen, since the hull is the
    entire point of a tile subscription).
  - `BridgeServer.ClientEntry` had its class-level `final` removed — purely
    for testability (Mockito 3.1.0 in this repo has no `mockito-inline`, so
    it cannot mock final classes; removing `final` has no behavioural
    effect, since equality/lookup was already default `Object` identity).
- **Python side**:
  - `BridgeConnection.subscribe()` gained optional `world_x`/`world_y`/
    `plane` kwargs, only included in the outgoing JSON when not `None` (kept
    the exact existing dict shape for the other kinds, verified against
    `test_client.py`'s pre-existing shape assertions).
  - `GameController.subscribe_to_tile(sub_id, world_x, world_y, plane=None,
    ttl_ticks=10)` added alongside `subscribe_to`.
  - `BrutusFighterRoutine._click_dodge_tile` rewritten: subscribes to
    `DODGE_TILE_SUB_ID` (a fixed, reused subId — re-subscribing each dodge
    just renews it) at the computed dodge-tile coordinates, reads back
    `ctrl.hull_update(...)`, and clicks `canvasX`/`canvasY` via
    `click_walk_target` only when `found`/`onScreen`. No minimap fallback —
    matches the prior round's already-agreed decision. Removed the rejected
    pixel-estimation helpers (`_pixels_per_tile_from_hull`,
    `_dodge_canvas_position`, `_live_brutus_canvas`); `_live_brutus_pos` was
    kept since `_compute_dodge_tile` (the tile-selection geometry, unrelated
    to canvas projection) still needs it.
- `GAMEBRIDGE.md` updated per the Game Bridge maintenance rule: subscribe
  message table, a `"tile"`-specific note + example, the `hullUpdate` tile
  entity shape (no `id`/`name`/`animation`/`combatLevel`, hull always
  populated when on-screen), and a Python usage snippet.

### Tests

- Java: added `findTile`-focused tests to `TickMessageBuilderTest`
  (out-of-scene, plane-mismatch, and plane-defaulting/explicit-plane via
  `ArgumentCaptor` on `client.findWorldViewFromWorldPoint`) — deliberately
  scoped to the mockable surface, consistent with `serializeGroundItem`
  having no dedicated unit test for its own hull-projection path. Added a
  new `GameBridgePluginTest` (first test file for this class) covering the
  subscribe/unsubscribe → `onClientTick` → `hullUpdate` wiring for `kind:
  "tile"`, via reflection-swapped `server`/`tickBuilder` mocks rather than a
  real socket. `./gradlew.bat :client:test` — full suite green (the
  project's actual Gradle path is `:client`, not `:runelite-client` as
  CLAUDE.md's example command says — worth fixing that doc).
- Python: added tests to `test_client.py` (`subscribe` tile kwargs),
  `test_controller.py` (`subscribe_to_tile` delegation/no-connection-warning/
  plane-default), and rewrote the dodge-click section of
  `test_brutus_fighter.py` (subscribe-with-computed-tile, click-on-found-
  onscreen, skip-on-not-found/not-onscreen/no-push-yet — replacing the three
  tests for the rejected canvas-estimation approach). `python -m pytest
  scripts/gamebridge/tests/ -v` — 1417 passed, 10 skipped (pre-existing
  skips, unrelated).

### Open / next steps

- Live smoke test against Brutus still outstanding — confirm the dodge click
  actually moves the player in real gameplay, which was the original
  unresolved symptom driving all three redesign attempts. Everything above
  is verified at the unit-test level only.
- Not implemented: the "pre-subscribe a speculative dodge tile before the
  telegraph is seen" latency optimization floated in the handoff doc — left
  for later, only worth it if the synchronous subscribe→poll→click flow
  proves too slow in live play.
- `BRUTUS_TILE_CLICKBOX_PLAN.md` can be deleted once the live smoke test
  above passes; it was a single-session handoff doc, not meant to be a
  permanent fixture.

---

## Session: 2026-06-27 — Fix: `RodFishingRoutine.cooking` stuck — missing `approach()` before clicking the Fire

### Goal

Address the `# TODO: Cooking phase is stuck not doing anything` left in
`scripts/gamebridge/routines/examples/rod_fishing.py` (`cooking()`), and
review the rest of the routine for other issues.

### Findings / Decisions

- The TODO's literal claim ("just left-click the Fire, don't use raw fish on
  it") was already true of the code — `cooking()` called
  `self.click_live(ctrl, fire, "object")` directly, no item-on-object step.
  The actual bug was that it was the **only** click site in this routine
  that skipped `self.approach(game, ctrl, entity)` first. Every sibling
  click site (`find_spot`, `open_bank`, `walk_to_entity`, and the analogous
  `Smelt`/`Smith` states in `smelting_bars.py`/`smithing_helms.py`) calls
  `approach()` before `click_live()` — it's what pans the camera/walks via
  minimap (`bring_entity_on_screen`), dodges UI occlusion, and waits for a
  one-tick idle settle before a click is safe.
- Without `approach()`, `click_live` → `ctrl.click_entity` → `
  _onscreen_canvas_pos` returns `None`/no-op whenever the Fire isn't already
  on-screen — which is the common case right after walking away from the
  fishing spot. The old code also ignored `click_live`'s return value and
  unconditionally stamped `self._cook_started_tick = game.tick`, so a missed
  click still entered the `COOKING_GESTURE_TICKS` wait, then retried the same
  no-op click forever. Net effect: the state never errors, never logs
  anything alarming, and never progresses — "stuck not doing anything."
- **Fix** (`rod_fishing.py::cooking`): gate the fire click behind
  `if not self.approach(game, ctrl, fire): return None`, and only stamp
  `_cook_started_tick` when `click_live(...)` actually returns `True`.
- Also fixed a stale comment on `COOKING_GESTURE_TICKS` ("min ticks between
  'use fish on fire' gestures" — leftover phrasing from a never-implemented
  use-item approach; the code has only ever clicked the Fire object).
- Reviewed the rest of the state machine (`banking`, `walk_to_fern`,
  `walk_to_tree`, `find_spot`, `fishing`, `drop_burnt`, `drop_and_return`,
  `walk_to_bank_tree`, `walk_to_bank_fern`, the minimap-waypoint helpers) —
  no other bugs found; each already follows the `approach()`-gated click
  pattern or has no click to gate.

### Tests

- `scripts/gamebridge/tests/test_rod_fishing.py` (`TestCooking`):
  - Updated `test_clicks_fire_directly_when_raw_fish_present` →
    `test_clicks_fire_directly_after_approach_settles` to call `cooking()`
    twice across two ticks (settle, then click), matching the
    `approach()`-gated pattern used by `TestFindSpot`.
  - Updated `test_fire_clicked_when_raw_fish_present_and_no_dialog`
    similarly.
  - Added `test_fire_off_screen_does_not_click_or_mark_gesture_started` —
    regression test pinning the actual bug: with
    `ctrl.bring_entity_on_screen.return_value = False`, `cooking()` must not
    call `ctrl.click_entity` or set `_cook_started_tick`. This is the
    scenario that would have caught the original bug (existing fixtures
    like `FIRE_NEAR` always set `onScreen: True`, which is why the bug
    shipped without a failing test).
  - Full suite: `python -m pytest scripts/gamebridge/tests/ -v` → 1143
    passed, 10 skipped.

### Open / next steps

- None — this was a self-contained bug fix. Worth keeping in mind for any
  *new* routine: any state that clicks a world entity (object/NPC) should
  route through `InteractionRoutine.approach()` first unless there's a
  specific reason not to (e.g. dialog button clicks, which fire in one tick
  with no approach needed, as seen in `Smelt`/`Smith`).

---

## Session: 2026-06-15 (6) — Diagnostic: instrument `ctrl.tooltip()` staleness with `tooltip_age()`

### Goal

Follow-up to session (5): the user reports that fix only *masked* the
problem — new logs show `find_ore` no longer falsely transitions to
`"mining"` (no more `xp=False, timeout=True`), but each `find_ore` cycle
still burns 1-3 retries (~1-2s each), cycling through stale-looking tooltips
("Walk here" → "Cancel" → "Examine Rocks") before finally matching "Examine
Tin rocks" and clicking. The user watched the live dashboard tooltip readout
during a run and states it was accurate/live at the moment the routine's log
showed a stale value, and is adamant the bug is a stale read of
`ctrl.tooltip()` inside `_verify_tooltip_and_act`, not a retry-convergence or
mouse-aim issue.

### Findings / Decisions

- Traced the full tooltip pipeline end-to-end:
  - `BridgeConnection.messages()` (`client.py`) intercepts every `hullUpdate`
    line, sets `self.tooltip = msg.get("tooltip", "")`, and does **not**
    yield it — only non-hullUpdate ("tick") messages are yielded.
  - `BridgeTicker.run()` (`bridge_ticker.py`, its own QThread) drives
    `conn.messages()` in a tight `for` loop independent of the
    `RoutineRunner` QThread that drives `routine.tick(game, ctrl)` — so
    `self.tooltip` is updated continuously (~20ms hullUpdate cadence)
    regardless of how long a routine's `tick()` call takes.
  - `GameController.tooltip()` (`controller.py`) is a direct, uncached
    passthrough: `return self._connection.tooltip`.
  - The dashboard and the routine share **one** `GameController` /
    `BridgeConnection` instance (`dashboard.py`), so the dashboard's tooltip
    label and `ctrl.tooltip()` inside `_verify_tooltip_and_act` read the
    literal same attribute.
  - `decision/engine.py` and `state/*.py` have **no** tooltip references — no
    snapshot/cache layer exists between `BridgeConnection.tooltip` and
    `_verify_tooltip_and_act`'s read.
  - No structural staleness bug found by code review. The only plausible
    mechanism for `self.tooltip` to lag the socket is GIL contention: if
    `RoutineRunner`'s thread holds the GIL for an extended CPU-bound stretch
    (e.g. inside `wind_mouse_to_prediction`'s movement loop in
    `move_to_entity`), `BridgeTicker` can't call `recv()`/advance its
    generator, so `self.tooltip` freezes at its last value until
    `BridgeTicker` is rescheduled — at which point it should immediately
    catch up to the latest buffered hullUpdate.
- Given the user's explicit, first-hand observation is treated as
  authoritative (per CLAUDE.md: don't paper over with a quick hack, and don't
  re-litigate a rejected theory without new evidence), and a "near miss" GIL
  explanation can't be confirmed or ruled out from static reading alone:
  **added direct instrumentation** rather than guessing at a fix.

- **Implemented** (`client.py` / `controller.py` / `interaction.py` /
  `dashboard.py`):
  - `BridgeConnection.__init__` now also sets `self.tooltip_updated_at: float
    = 0.0`; `messages()` stamps `self.tooltip_updated_at = time.monotonic()`
    in the same branch that sets `self.tooltip`.
  - New `GameController.tooltip_age() -> Optional[float]`: seconds since the
    last hullUpdate's tooltip was received, or `None` if no connection / no
    hullUpdate yet.
  - `_verify_tooltip_and_act` (`routines/interaction.py`) now logs
    `"Tooltip before click: %r (age=%s)"`, formatting `age` as `"NNNms"` when
    it's a real `float` and falling back to `%s` of whatever `tooltip_age()`
    returns otherwise (mock-safe — `MagicMock() % "%.3f"` raises `TypeError`,
    but `isinstance(MagicMock(), (int, float))` is `False` so the `%s` branch
    is taken).
  - Dashboard's tooltip label (`_tick_tooltip_label`) now appends `" (NNNms)"`
    when `tooltip_age()` is not `None`, so the live readout itself shows
    freshness.

### Tests

- `scripts/gamebridge/tests/test_client.py`: added
  `test_tooltip_updated_at_defaults_to_zero`,
  `test_hull_update_sets_tooltip_updated_at`,
  `test_hull_update_tooltip_updated_at_overwrites_on_repeat` (patches
  `scripts.gamebridge.client.time.monotonic`).
- `scripts/gamebridge/tests/test_controller.py`: added
  `test_tooltip_age_without_connection_returns_none`,
  `test_tooltip_age_returns_none_before_any_hull_update`,
  `test_tooltip_age_returns_seconds_since_last_update` (patches
  `scripts.gamebridge.controller.controller.time.monotonic`).
- `python -m pytest scripts/gamebridge/tests/ -q` → 915 passed, 10 skipped
  (was 909 passed before this session's 6 new tests).

### Open / next steps

- **Needs a live run** with debug logging enabled to capture the new
  `"Tooltip before click: %r (age=%s)"` lines alongside the dashboard's
  tooltip+age readout during a `find_ore` cycle that shows the
  "Walk here"/"Cancel"/"Examine Rocks" → "Examine Tin rocks" progression:
  - If `age` is large (tens-to-hundreds of ms) at the moment a stale tooltip
    is logged while the dashboard already shows the correct one: confirms a
    genuine pipeline staleness bug (likely the GIL-starvation mechanism
    above) — next step would be moving `move_to_entity`'s blocking
    `wind_mouse_to_prediction` work off the `RoutineRunner` thread, or making
    `BridgeTicker` higher-priority / non-blocking.
  - If `age` is consistently near-zero (single-digit ms) even when the
    *value* doesn't yet match what the dashboard shows: `ctrl.tooltip()` is
    returning the truly-latest value from the socket, so the mismatch is in
    what the **game client itself** reported as `currentTooltip()` at that
    ClientTick — points investigation at
    `GameBridgePlugin`/`TickMessageBuilder` (Java side) instead, e.g. a
    capture-ordering issue between the mouse-move event and the tooltip
    snapshot for that tick.

### Result (live run)

New logs from the user show `age` values of `16ms`, `31ms`, `0ms`, `0ms` for
the `_verify_tooltip_and_act` reads across one `find_ore` cycle (including the
"Cancel"/"Examine Rocks" → "Examine Tin rocks" progression). These are all
within ~1-2 ClientTicks (~20ms cadence) — i.e. `ctrl.tooltip()` is receiving
fresh socket data essentially in real time. **This empirically rules out a
stale-variable bug in the Python `BridgeConnection.tooltip`/`GameController.
tooltip()` pipeline** — the value Python holds is (within single-digit-to-low-
double-digit ms) the latest one the Java plugin has sent.

Also re-read `GameBridgePlugin.onClientTick` / `TickMessageBuilder.
currentTooltip()` (Java): `tooltip` is recomputed from `client.getMenuEntries()`
fresh every ClientTick (no caching), independent of the per-`Subscription`
`findNearest` loop — so there's no Java-side caching bug either as far as
static reading shows.

A brief side-investigation attempted a *different*, hull-based explanation
(stale `hull_updates[LIVE_HULL_SUB_ID]` entry from a previous same-named
subscription target, causing `_with_live_hull`/`_live_hull_canvas_pos` to aim
at the wrong instance) and added a `worldX`/`worldY`/`plane`-proximity check to
both. **The user rejected this**: clickboxes/hulls have been working correctly
and are explicitly out of scope — this conversation is about the `tooltip`
value specifically, via the dedicated `_tooltip` subscription, not
`hull_updates`. The `_same_world_tile` change was reverted in both
`routines/interaction.py` and `controller/controller.py` (back to 915 passed,
10 skipped).

### Open / next steps (revised)

- The `tooltip_age()` instrumentation stays (useful diagnostic, low risk,
  tested) but its data so far does not support a Python-side staleness bug.
- Still unresolved: the user maintains, from direct observation, that
  `_verify_tooltip_and_act` sometimes acts on a tooltip value that doesn't
  match what was visibly hovered at that moment — scoped specifically to the
  `tooltip`/`_tooltip` subscription pipeline, not `hull_updates`. Next
  research angle: re-examine `GameBridgePlugin`'s `onClientTick` handler and
  ordering relative to RuneLite's mouse-input processing for that frame (does
  `client.getMenuEntries()` reflect the *current* frame's cursor position, or
  the previous one?) — i.e. a one-ClientTick lag baked into
  `currentTooltip()` itself on the Java side, which a Python-side `age` of
  ~20ms couldn't distinguish from "correct".

---

## Session: 2026-06-15 (5) — Fix: find_ore wastes a 3s cycle when click_live falls back to moving the mouse

### Goal

Follow-up to session (4): the dashboard tooltip readout confirmed
`ctrl.tooltip()` is live/accurate, yet `OreMiningRoutine`'s first `find_ore`
attempt still logged `Tooltip before click: 'Cancel'`, didn't click, and
wasted a full `MINING_XP_TIMEOUT_MS` (3s) cycle before succeeding on the
second attempt.

### Findings / Decisions

- Root cause is a state-machine bug, not a tooltip-freshness bug:
  1. `TickMessageBuilder.currentTooltip()` (Java) doesn't check
     `client.isMenuOpen()` (unlike `MouseHighlightOverlay`, the real in-game
     hover tooltip, which returns `null` while a menu is open). So when a
     right-click context menu happens to be open at that ClientTick,
     `ctrl.tooltip()` returns that menu's top entry (e.g. `"Cancel"`) instead
     of a hover-preview tooltip for whatever the cursor is actually over.
  2. `_verify_tooltip_and_act` (`routines/interaction.py`) correctly sees
     `"Tin rocks"` / `"Iron rocks"` not in `"Cancel"` and calls
     `ctrl.move_to_entity(live)` instead of clicking — working as designed.
  3. But `click_live`/`right_click_live` previously returned `None`
     unconditionally, so `IronMiningRoutine.find_ore` had no way to know the
     click didn't fire — it set `mining_start_tick = game.tick` and
     transitioned to `"mining"` regardless. `mining` then timed out after 3s
     (no animation/XP ever started) before returning to `find_ore`, where the
     mouse (now near the ore from the earlier `move_to_entity`) finally
     produced a matching tooltip and the real click landed.
  - This explained exactly the user's log sequence: `find_ore` → `mining`
    (no click) → 3.0s timeout → `find_ore` → real click → `mining`.

- **Fix implemented** (`scripts/gamebridge/routines/interaction.py`):
  - `_verify_tooltip_and_act` now returns `bool` — `True` if `act(live)` (the
    click) ran, `False` if the mouse was moved towards `live` instead.
  - `click_live`/`right_click_live` now return that bool (previously `None`).
  - `IronMiningRoutine.find_ore` (`routines/examples/iron_mining.py`) only
    sets `mining_start_tick` and transitions to `"mining"` when
    `click_live(...)` returns `True`; otherwise it `return None`s and retries
    next tick. Worst case this costs one extra ~0.6s tick (the `approach`
    settle buffer restarting) instead of the full 3s mining timeout.
  - `OreMiningRoutine` inherits this fix unchanged (thin `ORE_NAME` subclass).

- Scope decision: did **not** change `walk_to_bank`/`deposit`
  (`iron_mining.py`), `melee_fighter.py`, or `fish_and_cook.py` call sites.
  - `walk_to_bank`/`deposit` already `return None` regardless of
    `click_live`'s outcome and re-evaluate `approach`/`player_near` from
    scratch next tick — self-correcting, no unconditional-success assumption.
  - `melee_fighter.py`'s `right_click_live` call sites set
    `_attack_target`/`_loot_target` and `return None`; the next tick's
    `verified_menu_click` reads the actual context menu (not the tooltip), so
    a moved-mouse tick just means no menu opened yet and the gesture retries
    naturally.
  - `fish_and_cook.py`'s `find_fire` (`click_live` then `return None`) is
    self-correcting the same way. `cooking`'s `click_live` (line ~319) does
    set `_cook_started_tick = game.tick` regardless, which would cost
    `COOKING_GESTURE_TICKS` (3 ticks, ~1.8s) extra on a moved-mouse tick — a
    much smaller version of the same class of issue, but out of scope for
    this fix (not the reported symptom; revisit if it causes problems).
  - Did **not** change `TickMessageBuilder.currentTooltip()` (Java) to check
    `isMenuOpen()` — the Python-side fix fully explains and resolves the
    reported symptom without touching the Java/GAMEBRIDGE.md contract. Still
    a candidate for a future, separate session if "Cancel"-style tooltips
    cause other issues.

### Tests

- `scripts/gamebridge/tests/test_interaction.py`: added
  `test_returns_false_when_name_not_in_tooltip` /
  `test_returns_true_when_name_in_tooltip` for both `click_live` and
  `right_click_live`.
- `scripts/gamebridge/tests/test_iron_mining.py`: added
  `TestFindOreTooltipVerification` with
  `test_stays_in_find_ore_when_click_live_only_moves_mouse` (tooltip
  `"Cancel"` → no click, `result is None`, `mining_start_tick` stays `None`)
  and `test_transitions_to_mining_once_tooltip_confirms_the_ore` (tooltip
  names the ore → clicks, transitions to `"mining"`,
  `mining_start_tick == game.tick`).
- `python -m pytest scripts/gamebridge/tests/ -q` → 909 passed, 10 skipped
  (was 903 passed before this session's 6 new tests).

### Open / next steps

- If "Cancel"-style stale-menu tooltips turn out to affect `fish_and_cook.py`
  `cooking` or other call sites in practice, apply the same `if not
  self.click_live(...): return None` pattern there.
- Consider (separately, lower priority) making
  `TickMessageBuilder.currentTooltip()` check `client.isMenuOpen()` and
  return `""` when a menu is open, to mirror `MouseHighlightOverlay` — would
  need `GAMEBRIDGE.md` + `TickMessageBuilderTest.java`/`ContractTest.java`
  updates and `./gradlew.bat :runelite-client:test`.

---

## Session: 2026-06-15 (4) — Dashboard: live tooltip readout next to Animation

### Goal

User reported `OreMiningRoutine`'s first `find_ore` never succeeds and
suspects the tooltip read by `click_live`/`right_click_live` is stale at the
moment it's checked. Add a live "Tooltip: …" readout to the dashboard's
Player card (next to "Animation: …") so the user can visually confirm what
`ctrl.tooltip()` reports in real time and compare it against what's actually
under the cursor in-game.

### Findings / Decisions

- `BridgeConnection.tooltip` (set in `client.py:messages()`) is updated on
  the `BridgeTicker` thread every time a `hullUpdate` message arrives
  (~20ms cadence) — independent of the once-per-~600ms `tick_received`
  signal that drives `_on_tick`. Refreshing the new label from `_on_tick`
  alone would still only show a per-tick snapshot, not the "constantly live"
  view requested.
- Added a second `QTimer` (`self._tooltip_timer`, 100ms) in
  `GameBridgeWindow.__init__` calling a new `_tick_tooltip_label()`, which
  sets `self._player_tooltip_lbl` from `self._ctrl.tooltip()` (`"—"` when
  empty). Reading a plain Python `str` attribute across threads is safe
  under the GIL — same assumption `ctrl.tooltip()` itself already relies on.
- New `self._player_tooltip_lbl` ("Tooltip: —") added to `_make_player_card`
  directly below `_player_anim_lbl`, matching the user's "under or next to
  Animation" request.

### Tests

- `dashboard.py` has no existing unit tests (PyQt6 `QMainWindow` — no
  headless-widget test harness set up in this repo yet), consistent with
  every other label/timer in this file (`_player_anim_lbl`,
  `_tick_session_panel`, etc.). No new test added for this thin UI binding;
  `python -m pytest scripts/gamebridge/tests/ -q` → 903 passed, 10 skipped
  (unchanged), confirms nothing else broke.
- No `GAMEBRIDGE.md` changes — pure dashboard UI, no plugin/wire-format
  changes.

### Open / next steps

- **Live-verify the actual hypothesis**: run `OreMiningRoutine`, watch the
  new "Tooltip:" readout during the first `find_ore` attempt, and confirm
  whether it lags behind the cursor's real in-game tooltip (the suspected
  root cause of the first-attempt failure). If confirmed stale, the next fix
  is likely in `InteractionRoutine._verify_tooltip_and_act` /
  `click_live`/`right_click_live` (routines/interaction.py) — e.g. waiting
  for at least one fresh `hullUpdate` after subscribing before trusting
  `ctrl.tooltip()`, since `LIVE_HULL_SUB_ID` subscriptions are only
  registered just-in-time and `hull_update()`/`tooltip()` return stale/empty
  data until the first push arrives for that subId.
- If the dashboard label itself looks fine (matches the cursor) but
  `find_ore` still fails on the first attempt, the bug is more likely in
  `find_ore`'s own state machine/gating than in tooltip freshness — revisit
  `routines/examples/iron_mining.py`'s `find_ore` (inherited by
  `OreMiningRoutine`).

---

## Session: 2026-06-15 (3) — Always-on tooltip subscription, decoupled from click_live/right_click_live

### Goal

User feedback: `ctrl.tooltip()` was only populated while `click_live`/
`right_click_live` happened to have an active `LIVE_HULL_SUB_ID`
("click_target") subscription — any routine state that didn't call those
(or whose subscription's `ttlTicks` lapsed between calls) got a stale or
empty tooltip. Requested: just always be subscribed so `ctrl.tooltip()`
works from connection time, regardless of what (if anything) a routine
subscribes to for live-hull tracking.

### Findings / Decisions

- Confirmed in `GameBridgePlugin.onClientTick`: `hullUpdate` (and its
  `tooltip` field) is only pushed `if subs != null && !subs.isEmpty()` for
  that connection — it doesn't matter *which* subId/entity the subscription
  targets, or whether it resolves `found: true`. So any always-present
  subscription is sufficient to keep `tooltip` flowing.
- Added `GameController.TOOLTIP_SUB_ID = "_tooltip"` and
  `TOOLTIP_SUB_TTL_TICKS = 1_000_000` (~7 days of game ticks — long enough
  to never need renewal for a session's lifetime, avoiding any cross-thread
  re-subscribe scheduling).
- `set_connection()` now calls
  `self.subscribe_to(TOOLTIP_SUB_ID, "player", id=-1, ttl_ticks=TOOLTIP_SUB_TTL_TICKS)`
  whenever a non-`None` connection is set. `id=-1` never matches a real
  player so this subscription's own `entities[]` result is always
  `found: false` — it exists purely as a keepalive. `set_connection` is
  already called once per connection attempt by both `main.py`'s
  `connect()` loop and the dashboard's `BridgeTicker.connection_changed`
  (see session 2026-06-15 (2)), so this fires automatically "on startup of
  any script" per the user's request, no new wiring needed.
- `click_live`/`right_click_live`'s `LIVE_HULL_SUB_ID` ("click_target")
  subscription is unchanged and still needed for its own purpose (live
  per-entity hull tracking for click prediction) — it's now just redundant
  for keeping `tooltip` alive, which the new keepalive subscription already
  guarantees.
- `GAMEBRIDGE.md` updated (Live clickbox subscriptions section) to document
  that `set_connection` registers this keepalive automatically.

### Tests

- `test_controller.py::TestSubscriptions`: new
  `test_set_connection_subscribes_to_tooltip_keepalive` (asserts
  `conn.subscribe` called with `TOOLTIP_SUB_ID`/`"player"`/`id=-1`/
  `TOOLTIP_SUB_TTL_TICKS`) and `test_set_connection_none_does_not_subscribe`.
  Updated `test_subscribe_to_delegates_to_connection` to
  `conn.subscribe.reset_mock()` after `set_connection(conn)`, since that
  call now also issues the keepalive subscribe.
- `python -m pytest scripts/gamebridge/tests/ -q` → **903 passed, 10
  skipped**.

### Open / next steps

- Not yet live-tested — confirm `ctrl.tooltip()` returns real text
  immediately after connecting, even before any routine calls
  `click_live`/`right_click_live`, and that `_with_live_hull`'s separate
  `LIVE_HULL_SUB_ID` subscription still works alongside the keepalive
  (different subIds, both within the 20-subscription cap).
- User noted they'll report back if this causes any performance issues
  (extra `hullUpdate` traffic at ~20ms cadence is already the existing
  cost of any single subscription — this just makes it permanent rather
  than intermittent).

---

## Session: 2026-06-15 (2) — Fix: dashboard's GameController never received a live BridgeConnection (tooltip always "")

### Goal

Live-tested the tooltip-verification feature from the session below and the
`OreMiningRoutine`/`IronMiningRoutine` always logged
`subscribe_to(click_target) called with no active connection` and
`Tooltip before click: ''`, so `click_live`/`right_click_live` always took
the "move instead of click" branch. Work out why, given the Java side
(`TickMessageBuilder.currentTooltip`, `GameBridgePlugin.onClientTick`) and the
Python `BridgeConnection`/`GameController.tooltip()` plumbing all already had
test coverage and looked correct.

### Findings / Decisions

- Root cause was entirely on the **dashboard wiring side**, not the
  Java plugin or the wire format — `GAMEBRIDGE.md` needs no changes.
- `dashboard.py`'s `GameBridgeWindow.__init__` builds `self._ctrl =
  GameController(...)` but **never called `ctrl.set_connection(...)`** —
  `BridgeTicker.run()` (old `bridge_ticker.py`) drove `client.stream()`,
  which internally calls `client.connect()` but only yields parsed tick
  dicts — the live `BridgeConnection` for the current attempt never escapes
  `stream()`. So `ctrl._connection` stayed `None` forever in the dashboard,
  making `subscribe_to`/`tooltip()` permanent no-ops (by design — see their
  docstrings/warnings). Headless `main.py --routine` mode was unaffected:
  it calls `client.connect()` directly and does `ctrl.set_connection(conn)`
  itself.
- Fix: `bridge_ticker.py` — `BridgeTicker` now drives `client.connect()`
  directly (mirrors `stream()`'s reconnect-on-drop loop, including the
  `RECONNECT_DELAY_S = 5.0` sleep) and gained a new `connection_changed =
  pyqtSignal(object)`, emitting the live `BridgeConnection` right after each
  `connect()` yield, and `None` when `conn.messages()` raises
  `OSError`/`ConnectionError` (before the retry sleep).
- `dashboard.py` — `_start_ticker` now also does
  `self._ticker.connection_changed.connect(self._ctrl.set_connection)`. One
  line; `set_connection`/`subscribe_to`/`tooltip()` were already covered by
  `test_controller.py`.
- `client.stream()` itself is unchanged and still used by `main.py --watch`.

### Tests

- New `tests/test_bridge_ticker.py` (PyQt6 required — installed into this
  env via `pip install PyQt6` since it wasn't present):
  `TestConnectionForwarding` covers `connection_changed` emitting the live
  connection, `tick_received`/`ingest` firing per message, and `connect()`
  being called with the configured host/port; `TestReconnection` covers
  `connection_changed.emit(None)` on `ConnectionError`/`OSError` from
  `conn.messages()`, the reconnect sleep, and resumption with the next
  connection.
- `python -m pytest scripts/gamebridge/tests/ -q` → **901 passed, 10
  skipped**.

### Open / next steps

- The client-log `NullPointerException`s from `watchdog`/`vineyardhelper`/
  `EasyEmpty`/`taskstracker` plugins are unrelated third-party plugins, not
  part of this repo's gamebridge code — noise, not a lead for this bug.
- Live-retest `OreMiningRoutine` against this dashboard fix to confirm
  `ctrl.tooltip()` now returns real text and `click_live`/`right_click_live`
  stop falling back to move-only.

---

## Session: 2026-06-15 — Tooltip verification before click_live/right_click_live, and "drop" check in drop_items_shift_click

### Goal

Add a pre-click tooltip-verification step to `click_live`/`right_click_live`:
if the entity has a `name`, confirm it appears in `ctrl.tooltip()` before
clicking, otherwise move the mouse towards the entity instead (so a later
call gets a fresher tooltip). Make this controllable via an argument so it
can be disabled for entities with no meaningful left-click tooltip. Always
log the full tooltip text at debug level right before any click action. Apply
the same idea to `drop_items_shift_click`, checking for "drop" before each
item's click and skipping items whose tooltip doesn't say "drop".

### Findings / Decisions

- Added `InteractionRoutine._verify_tooltip_and_act(ctrl, live, verify_tooltip, act)`
  in `routines/interaction.py` — shared by `click_live`/`right_click_live`.
  Always logs `log.debug("Tooltip before click: %r", tooltip)`. If
  `verify_tooltip` is True and `live["name"]` exists and its lowercase form
  isn't a substring of the lowercased tooltip, logs and calls
  `ctrl.move_to_entity(live)` instead of `act(live)`.
- `click_live`/`right_click_live` both gained `verify_tooltip: bool = True`
  (default **on** — matches "we should be able to *disable* this check").
  Pass `verify_tooltip=False` for entities with no left-click tooltip (e.g.
  some tiles).
- Added `GameController.move_to_widget(widget)` (controller/controller.py) —
  moves the cursor to the centre of a UI widget's bounds without clicking;
  the primitive needed for `drop_items_shift_click`'s "hover, check tooltip,
  then click" two-phase flow.
- `drop_items_shift_click` rewritten as a small state machine using two new
  `InteractionRoutine.__init__` fields, `_drop_pending: Optional[dict]` and
  `_drop_skipped: set` (alongside the existing `_drop_queue`):
  - `verify_tooltip=False` (**default** — preserves the original
    fire-and-forget behaviour that `fish_and_cook.py`'s dropping state
    already relies on): queue all matching widgets, hold Shift, click each
    once.
  - `verify_tooltip=True` (opt-in): each widget is handled across two calls —
    first call moves the mouse to the slot (`ctrl.move_to_widget`) and stashes
    it in `_drop_pending`; the next call logs
    `log.debug("Tooltip before drop click: %r", tooltip)`, and clicks the
    widget only if `"drop" in tooltip.lower()`. Otherwise the widget's
    `childId` is added to `_drop_skipped` (excluded from requeues until the
    queue empties and Shift is released, which also clears `_drop_skipped`).
- Default direction matters here: `click_live`/`right_click_live` default to
  **verify ON** (per the user's framing — "disable this check"), but
  `drop_items_shift_click` defaults to **verify OFF** to avoid changing
  existing callers' (`fish_and_cook.py`) behaviour/tests. Only opt in to the
  two-phase drop flow where a per-item "Drop" tooltip check is actually
  wanted.

### Tests

- `test_interaction.py`: `MATCHING_TOOLTIP = f"Mine {ENTITY['name']}"` set as
  `ctrl.tooltip.return_value` across existing `TestClickLive`/`TestRightClickLive`
  tests; new `TestClickLiveTooltipVerification`/`TestRightClickLiveTooltipVerification`
  classes cover: move-instead-of-click when name missing from tooltip,
  click when present, case-insensitivity, `verify_tooltip=False` bypass,
  entities without a `name` skip the check, and the tooltip is logged before
  every click. New `TestDropItemsShiftClick` covers both the `verify_tooltip=False`
  single-call batch path and the `verify_tooltip=True` two-phase
  move/check/click/skip/requeue/release flow, plus the debug log assertion.
- `test_controller.py`: new `TestMoveToWidget` covers bounds-centre movement,
  no-op when a widget has no `bounds`, and the out-of-viewport guard.
- **Pre-existing integration tests broke** because their `ctrl = MagicMock()`
  made `ctrl.tooltip()` return a bare `MagicMock()`, whose `__contains__`
  defaults to `False` — so `name.lower() not in tooltip.lower()` was always
  `True`, sending every `click_live`/`right_click_live` call down the
  move-instead-of-click branch. Fixed by adding a small `_AnyTooltip(str)`
  helper (overrides `__contains__` → `True` and `lower()` → `self`) to
  `test_fish_and_cook.py`, `test_iron_mining.py`, `test_melee_fighter.py`, and
  `test_gold_mining.py`, and setting `ctrl.tooltip.return_value = _ANY_TOOLTIP`
  in each file's `_ctrl()` helper (or inline for gold_mining's one affected
  test). This is duplicated per-file rather than factored into a shared
  conftest, matching this test suite's existing convention of per-file
  `_ctrl()`/`_entity()` helpers.
- `python -m pytest scripts/gamebridge/tests/ -q` → **895 passed, 10 skipped**.

### Open / next steps

- No Java/`GAMEBRIDGE.md` changes needed — this session only touched
  `scripts/gamebridge/routines/interaction.py`,
  `scripts/gamebridge/controller/controller.py`, and test files.
- `drop_item` (the older `DropMode`-based single-item helper) was not given
  tooltip verification — only the newer `drop_items_shift_click` batch path.
  If `drop_item`'s `SHIFT_CLICK` mode ever needs the same "drop" check, the
  `move_to_widget` + tooltip pattern here is reusable.

---

## Session: 2026-06-14 (5) — click_live/right_click_live: continuous live-hull tracking

### Goal

`InteractionRoutine.right_click_live`/`click_live` subscribed to a live
hullUpdate (~20ms cadence) but only used it for a single one-shot position
refresh (`_with_live_hull`) before handing off to
`GameController.click_entity`/`right_click_entity`. Those build a `predict`
closure (`_plan_moving_click`) that re-evaluates on every `wind_mouse_to_prediction`
step but extrapolates purely from `MovingTarget`'s tick-rate (~600ms) canvas
velocity — it never re-checks the live hullUpdate, so the "live" data was
stale by the time the click landed.

### Findings / Decisions

- `conn.messages()` only drains the socket (and thus refreshes
  `BridgeConnection.hull_updates`) between ticks. In headless `--routine`
  mode (`main.py`, single-threaded `for msg in conn.messages(): process_tick`)
  `hull_updates` is frozen during a click's `time.sleep`/mouse-move calls. In
  dashboard mode, `BridgeTicker` runs `ingest()` on a separate thread (see
  `decision/engine.py`), so `hull_updates` *does* keep updating mid-click —
  continuous tracking only pays off there, but degrades to today's behaviour
  elsewhere.
- Fix: added `GameController._live_hull_canvas_pos(sub_id, entity)` (returns
  the latest matching/on-screen live canvas pos, or `None`) and
  `_plan_live_click(entity, sub_id, cur_x, cur_y)` — same as
  `_plan_moving_click` but `predict()` polls `_live_hull_canvas_pos` on every
  call, falling back to `MovingTarget.predict` when no fresher live data
  exists.
- `click_entity`/`right_click_entity` gained an optional `sub_id` kwarg that
  switches them onto `_plan_live_click`. `click_live`/`right_click_live` now
  pass `sub_id=self.LIVE_HULL_SUB_ID`.

### Tests

`scripts/gamebridge/tests/test_controller.py::TestPlanLiveClick` (fallback on
no connection/no update/wrong entity/off-screen, tracks live position, and
re-polls on every `predict()` call — not just once). Updated
`test_interaction.py` and the routine tests
(`test_iron_mining.py`/`test_gold_mining.py`/`test_melee_fighter.py`/
`test_fish_and_cook.py`) for the new `sub_id=` kwarg on
`click_entity`/`right_click_entity` mocks. `python -m pytest
scripts/gamebridge/tests/ -q` → 871 passed, 10 skipped.

### Open / next steps

- Live tracking is currently a no-op outside dashboard mode (single-threaded
  headless `--routine` runner doesn't refresh `hull_updates` mid-click). If
  headless live-tracking matters, `main.py` would need its own ingest thread
  like the dashboard's `BridgeTicker`.

---

## Session: 2026-06-14 (4) — Game world movement research & innovation task

### Goal

Research and document a roadmap for implementing game world pathfinding and navigation. The routines currently only support minimap-walking to visible entities, but banking items and moving between objectives require multi-region navigation. Need to understand:
1. How existing camera/minimap/FOV navigation pieces fit together
2. External pathfinding resources (Explv's Map, Dax Web Walker Engine)
3. Integration options ranging from beginner (predefined routes) to advanced (dynamic pathfinding)

### Findings / Decisions

#### Current Navigation Infrastructure (VERIFIED WORKING)

**Camera Movement** (`GameController.rotate_camera_to`, `rotate_camera`):
- Uses arrow keys (LEFT/RIGHT) to rotate yaw
- Calibrated speed: ~0.56 yaw units/ms (measured from 10 full rotations in 36.6s)
- Computed from `camera_yaw_to()` which uses atan2(-dx, dy) for OSRS counter-clockwise yaw convention
- Only rotates yaw (LEFT/RIGHT); pitch (UP/DOWN) not yet automated

**Minimap Walking** (`GameController.click_minimap_entity`):
- Clicks precomputed minimapX/minimapY (from Java `Perspective.localToMinimap()`)
- Range: ~20 tiles from player; beyond that, no minimap coordinates (returns False)
- Multi-tick settlement tracking to prevent spam-clicking:
  - Registration: 2 ticks after click (animation/movement takes time to register)
  - Idle detection: waits for `player_idle()` (not animating + not moving)
  - Settling: 1 additional idle tick for polled game state to catch up
  - Safety cap: 100 ticks (~60s) timeout if walk never settles
- Returns True if click issued, False if minimap coords not available or walk already in progress

**Field of View (FOV)** (`fov.py`):
- Trapezoid model in camera-relative tile space
- Pitch-based interpolation between two empirically-calibrated anchors:
  - Pitch 229 (near-horizon): 3 tiles back, 6 tiles front, half-width 4-6
  - Pitch 320 (overhead): 3 tiles back, 3 tiles front, half-width 5-7
- Rotated into world tile space by camera yaw (counter-clockwise: 0=N, 512=W, 1024=S, 1536=E)

**Available Game Data** (GAMEBRIDGE plugin tick messages):
- `player`: position (worldX/worldY/plane), animation, HP, prayer
- `camera`: yaw, pitch, local coordinates (x/y/z), world tile base (baseX/baseY)
- `objects`/`npcs`: per-entity onScreen flag, canvasX/canvasY, worldX/worldY, minimapX/minimapY
- `interfaces`: list of all visible UI widgets with bounding boxes (supports occlusion detection)
- `menu`: right-click context menu with entry bounding boxes

**Entity Query Helpers** (`GameState`):
- `objects_named(name)`, `nearest_object(name)` — Manhattan distance to player
- `player_near(entity, tiles)` — exact tile distance check
- `is_occluded(canvas_x, canvas_y)` — check if canvas point is behind UI panels

#### Current Routines (LIMITED WORLD MOVEMENT)

Files: `scripts/gamebridge/routines/examples/{iron_mining,gold_mining,fish_and_cook}.py`

Pattern used in `IronMiningRoutine`:
1. `find_ore`: find nearest ore → click if visible via `approach()`
2. `mining`: wait for animation + XP drop
3. `walk_to_bank`: find mine cart → click to walk toward it (via minimap if far)
4. `deposit`: interact with deposit box → empty inventory

**Current Limitations:**
- Hardcoded target names ("Iron rocks", "Mine cart", "Mine cart deposit box")
- Assumes bank is always reachable via minimap click from anywhere on current screen
- No pathfinding for multi-screen/multi-region distances (e.g., mine site → separate bank region)
- No obstacle navigation (doors, ladders, walls)
- No support for entering/exiting buildings or changing planes
- No quest requirement checking

#### External Resources

**Runescape-Web-Walker-Engine** (github.com/itsdax/Runescape-Web-Walker-Engine):
- Java library for pathfinding (used by TriBot botting client)
- Algorithms: A* + Dijkstra (Dijkstra for region culling, A* for path)
- Performance: <200ms to generate any path in OSRS world
- Coverage: ~90% of game world (all cities, wilderness, major dungeons; missing only Lletya)
- Features:
  - Shortcut handling (skill gates, ship chartering, portals, teleports)
  - Obstacle navigation (doors, ladders, one-way exits)
  - Quest/skill requirement checking
  - Directed nodes (one-way passages)
  - Real-time collision/reachability visualization
- Access: Requires API key from https://admin.dax.cloud/
- Frontend: Explv's Map (https://explv.github.io/) — interactive pathfinding UI with Dax backend

**Explv's Map**:
- Interactive browser-based RuneScape map with Dax pathfinding integration
- Shows collision data, walkable tiles, paths on minimap
- Can query routes and visualize them in real-time

#### Recording System (EXISTING ASSET)

`scripts/gamebridge/recording/recorder.py` captures manual play sessions to JSONL:
- **Session events**: start/end timestamps, player name
- **Tick events**: raw game state (objects, inventory, xp, etc.)
- **Click events**: canvas X/Y, player world position, animation state, resolved target (object name/ID, menu entry, widget)

This is **reusable for manual waypoint recording**:
1. Player manually walks from mine to bank
2. Recorder captures every tick's player (worldX, worldY) plus interactions
3. Extract tick records where player was idle + moving
4. Decimated waypoint list (e.g., every 5th tick) or cluster-based reduction
5. Store as routine-specific route file

#### Integration Gaps (Root of TODO's "Game world movement" item)

1. **No Java ↔ Python bridge** — Dax pathfinding is Java-only; calling it from Python scripts would require JNI or HTTP API
2. **No pre-calculated route library** — each routine needs its destination paths curated manually or extracted from Dax
3. **No multi-region awareness** — routines don't know when they've left the current region or how far the destination is
4. **No dynamic path-following** — no code to consume a waypoint list and feed it to click_minimap_entity tick-by-tick
5. **No obstacle handling** — routines assume clear line-of-sight or minimap walkability
6. **No plane/building support** — can't navigate into dungeons, up ladders, or between floors

### Architecture Options (Increasing Complexity)

**Option 1: Hardcoded waypoint lists (Beginner)**
- Manually record walk from mine to bank using SessionRecorder
- Extract decimated (worldX, worldY) waypoint list from recording
- Store in Python dict/JSON alongside routine class
- Follow waypoints by: for each waypoint, `click_minimap_entity()` until player near, then next
- Effort: ~1-2 hours per routine
- Coverage: Works for linear A→B routes; no branching or conditional shortcuts

**Option 2: Recorded route playback (Beginner+)**
- Similar to Option 1, but replay click positions from recording instead of waypoints
- Leverages existing SessionRecorder infrastructure
- Effort: ~2-3 hours per routine
- Coverage: Exact reproduction of manual path; no adaptation

**Option 3: HTTP API to Dax pathfinding (Intermediate)**
- Query Dax API from Python (with API key) to get path A→B as list of (x, y) coordinates
- Cache paths locally to avoid repeated API calls
- Follow path via click_minimap_entity or mouse movement between waypoints
- Effort: ~4-6 hours (HTTP client, path caching, error handling)
- Coverage: Dynamic pathfinding for any source/dest; ~200ms latency per query

**Option 4: Embedded pathfinding engine (Advanced)**
- Port or reimplement A*/Dijkstra pathfinding to Python or call Java via subprocess
- Build local collision/walkability map from game state
- Generate paths on-the-fly with no external API
- Effort: 2+ weeks (significant algorithm implementation)
- Coverage: Offline, no API key needed; but requires collision data (not currently exposed by plugin)

### Recommended First Steps (Session Plan)

1. **Pick Option 1** (hardcoded waypoint lists) to unlock iron/gold mining banking:
   - Set up route file format: `routines/paths.py` with dict mapping (routine_name, dest_name) → [(worldX, worldY), ...]
   - Add `follow_path(path, game_state, ctrl)` helper in controller
   - Modify IronMiningRoutine `walk_to_bank` to use path instead of hardcoded mine cart click
   - Record 1-2 representative paths (mine site → bank, bank → mine site)
   - Test with mining routine

2. **Expand Option 1 to gold mining** — same paths as iron mining (same locations)

3. **Document Option 3** (Dax HTTP API) for future work — keep API key config, stub endpoints

4. **Leave Option 4** for later — only if Option 3 proves too costly or API becomes unavailable

### Open / next steps

- Decide on route file format (nested dict, JSON, protocol buffer?)
- Implement `follow_path()` in GameController
- Set up SessionRecorder-based path extraction (decimation algorithm?)
- Record first paths for testing
- Update TODO.md to reflect decisions and planned Implementation dates

---

## Session: 2026-06-14 (3) — Root cause found: keyboard `_INPUT` struct was the wrong size, SendInput rejected every key event

### Goal

The new `tests/integration/test_keyboard_integration.py` suite (added in the
previous session) was failing — 5 of 6 tests timed out waiting for key events
from the Tk harness, while the equivalent mouse integration tests all passed.
Investigate and fix.

### Root cause

Used the new `sendinput_diagnostics()` directly (focus the harness entry,
call it, then `press_key("a")`): `sendinput_result: 0, last_error: 87`
(`ERROR_INVALID_PARAMETER`) and `struct_size: 32`. **`SendInput` was rejecting
every keyboard event outright** — nothing was ever delivered, regardless of
foreground window or UIPI/BlockInput (the things the previous session's
diagnostics were built to detect).

The real Win32 `INPUT` union is sized to its **largest member**, `MOUSEINPUT`
(32 bytes on x64 — 5×4-byte fields + an 8-byte `dwExtraInfo` pointer, rounded
up to 8-byte alignment), giving `sizeof(INPUT) == 40` on 64-bit Windows.
`mouse.py`'s `_INPUT_UNION` only ever needed `mi: MOUSEINPUT`, so it
incidentally already had the correct 40-byte total size — which is why mouse
SendInput worked and keyboard didn't.

`keyboard.py`'s `_INPUT_UNION` only contained `ki: _KEYBDINPUT` (24 bytes on
x64), giving `sizeof(_INPUT) == 32`. `SendInput` validates the `cbSize`
parameter (`ctypes.sizeof(inp)`) against the *real* 40-byte `INPUT` size and
fails the whole call with `ERROR_INVALID_PARAMETER` if it doesn't match —
silently, with zero keys delivered.

Also found and fixed a **misleading red herring**: `diagnostics.py`'s
`describe_sendinput_diagnostics()` hardcoded the message `"sizeof(INPUT) = {N}
(expected 28 on 64-bit Windows)"`. 28 is actually the **32-bit** `sizeof(INPUT)`
(no 8-byte pointer alignment needed) — on 64-bit the correct expected value is
40. This wrong "expected" value is presumably why the original `_INPUT_UNION`
was never sized correctly in the first place.

### Fix

- `scripts/gamebridge/input/keyboard.py`: `_INPUT_UNION` now has a second
  field `("_padding", ctypes.c_byte * 32)` alongside `ki`, padding the union
  to `MOUSEINPUT`'s 32 bytes so `sizeof(_INPUT) == 40` on x64 (28 on 32-bit,
  matching `mouse.py`'s `_INPUT` which already had this size for free via
  `mi: MOUSEINPUT`).
- `scripts/gamebridge/diagnostics.py`: added `_EXPECTED_INPUT_SIZE = 40 if
  ctypes.sizeof(ctypes.c_void_p) == 8 else 28` (platform-aware) and used it in
  `describe_sendinput_diagnostics()`'s message; added a new `WARNING` line
  when `struct_size != _EXPECTED_INPUT_SIZE` — this is the check that would
  have immediately surfaced this exact bug.

### Verification

- Re-ran `sendinput_diagnostics()` after the fix: `struct_size: 40,
  sendinput_result: 1, last_error: 0`, and the Tk harness received the
  expected `Shift_L` down/up + `a` down/up key events.
- `GAMEBRIDGE_INTEGRATION=1 python -m pytest scripts/gamebridge/tests/ -v` →
  **871 passed** (up from 859; +10 integration tests now actually run and
  pass, +2 new diagnostics tests for the struct-size warning).

### Open / next steps

- This should also fix the in-game "keys not registering" issue from the
  previous two sessions — the `hold_key`(shift)+modifier-tracking question is
  now moot, since *no* scan-code key event was ever reaching any window. Worth
  a live playtest to confirm shift-click-to-drop etc. now work, but not
  required to close out this bug (covered by the integration suite).

---

## Session: 2026-06-14 (2) — Keyboard test/debug controls added to dashboard Testing tab

### Goal

The hardware keyboard emulation (scan-code `SendInput`, see session below) is
still not behaving correctly in practice. Rather than guess again, add
on-demand controls to the dashboard's Testing tab so the bot's keyboard
primitives can be triggered live against a running RuneLite client, with
debug output explaining exactly what was sent and why it might not have
landed.

### Findings / Decisions

- Added a "Keyboard" section to `ui/testing_tab.py` below the existing
  entity-diagnostics grid: a key-name `QLineEdit` plus **Press key / Hold
  key / Release key / Release all keys** buttons, a text `QLineEdit` plus
  **Type text** button, and a **SendInput diagnostics** button. All log to
  the existing output `QTextEdit` via the same `_log()` helper.
- New pure (`describe_*`) helpers in `diagnostics.py`, following the existing
  no-Qt pattern so they're unit-testable without a display:
  - `describe_press_key`/`describe_hold_key`/`describe_release_key`/
    `describe_release_all_keys`/`describe_type_text` wrap the corresponding
    `GameController` methods, reporting the resulting `_held_keys` set (or a
    "no-op" message for empty input / already-held / not-held).
  - `describe_sendinput_diagnostics` calls a new
    `input.keyboard.sendinput_diagnostics()` and turns the raw numbers into an
    explanation: reports the **foreground window** (title/class) — since
    `SendInput` delivers to whatever window has focus, a misdirected target
    is the most common "nothing happens" cause and isn't visible from the
    Java side at all — plus `SendInput`'s return value and `GetLastError`,
    flagging `ERROR_ACCESS_DENIED` (5, UIPI) vs. a `0`-with-no-error result
    (BlockInput/AV) vs. success. Compares the foreground title against the
    configured `window_name` setting to warn when RuneLite isn't focused.
- `input/keyboard.py`:
  - `sendinput_diagnostics()` — sends a harmless Shift down/up via the
    existing `_send_scan` path to the current foreground window and returns
    `struct_size`, `foreground_hwnd/title/class`, `sendinput_result`,
    `last_error`. Effectively a non-interactive, reusable version of the
    interactive checks that used to live in `tools/debug_keyboard.py`
    (removed in the "big clean up" commit).
  - `_send_scan` now returns `(SendInput result, GetLastError())` instead of
    `None` — additive, existing callers (`press_key`/`key_down`/`key_up`)
    ignore the return value.
- Tests: `test_keyboard.py` (`TestSendInputDiagnostics`,
  `TestSendScanReturnsResultAndError`, mocking `ctypes.windll`),
  `test_diagnostics.py` (one `TestDescribe*` class per new helper, including
  a `_make_ctrl()` stub whose `hold_key`/`release_key`/`release_all_keys`
  side-effect a real `_held_keys` set so messages reflect the resulting
  state). Full suite: `python -m pytest scripts/gamebridge/tests/ -v` → 859
  passed (up from 826).

### Open / next steps

- Use the new Testing-tab controls in-game to actually narrow down why
  scan-code injection (from the session below) still isn't registering —
  start with **SendInput diagnostics** to confirm RuneLite is the foreground
  window and `SendInput` itself isn't being blocked, then **Hold key**
  (shift) + alt-tab to RuneLite to check whether the client's modifier
  tracking picks it up.
- If `SendInput diagnostics` reports RuneLite focused and a clean
  result/error but the client still doesn't react, the next suspect is the
  RS client reading raw input via a different API (e.g. `GetRawInputData`)
  that scan-code `SendInput` doesn't satisfy — would need a packet-level
  capture to confirm.

---

## Session: 2026-06-14 — `keyboard.py` rewritten for hardware scan-code injection

### Goal

`drop_item`'s `DropMode.SHIFT_CLICK` (added in the session below) wasn't
working in practice: the bot logged "Holding key 'shift'" then
`click_widget`, but RuneLite still showed the default "Use" action instead of
"Drop" — i.e. the client never registered Shift as held.

### Findings / Decisions

- **Root cause**: `input/keyboard.py` used `pynput.keyboard.Controller`, whose
  Windows backend sends `SendInput` in **virtual-key mode** (`wVk=VK_LSHIFT`,
  `dwFlags` without `KEYEVENTF_SCANCODE`) for `Key.shift`. Windows itself
  updates global key-state (`GetAsyncKeyState`) for VK-mode injection, but
  the RS client's own held-modifier tracking does not — only **scan-code
  mode** injection (`wVk=0`, `KEYEVENTF_SCANCODE` set, `wScan` = PS/2 Set-1
  hardware scan code), i.e. what a real keyboard driver produces, registers
  as "held" for shift-click-to-drop. User confirmed empirically: holding
  physical Shift and alt-tabbing into RuneLite still shows "Drop" — the
  client checks real hardware modifier state, not just Windows' synthetic
  key-state.
- **Fix**: rewrote `input/keyboard.py` from scratch as a pure-ctypes module
  (no pynput), mirroring `input/mouse.py`'s raw `SendInput`/`KEYBDINPUT`/
  `INPUT` ctypes-struct pattern (`ctypes.windll` only touched inside
  functions, not at module scope, for cross-platform import safety).
  - `_NAMED_SCANCODES: dict[str, tuple[scan_code, is_extended]]` — PS/2 Set-1
    codes for every `Key.*` constant (escape=0x01, enter=0x1C,
    backspace=0x0E, tab=0x0F, space=0x39, shift=0x2A, ctrl=0x1D, alt=0x38,
    capslock=0x3A, F1-F10=0x3B-0x44, F11=0x57, F12=0x58). Navigation cluster
    (delete/home/end/pageup/pagedown/arrows) marked `is_extended=True` →
    `KEYEVENTF_EXTENDEDKEY` (0xE0-prefixed on real hardware).
  - `_char_scan(ch)` — layout-aware single-character resolution via
    `VkKeyScanW`/`MapVirtualKeyW(..., MAPVK_VK_TO_VSC)`; returns `(0, False)`
    for unmappable characters (`VkKeyScanW` returns -1).
  - `_resolve(key)` → `(scan, is_extended, needs_shift)` — named-key lookup
    (case-insensitive) falls back to `_char_scan` for arbitrary characters.
  - `_send_scan(scan, extended, key_up)` — the one `SendInput` call site.
  - `press_key`/`key_down`/`key_up`/`type_text` **signatures unchanged** —
    `press_key` wraps shifted characters (`needs_shift=True`, e.g. `"A"`,
    `"!"`) in an extra Shift down/up pair around the character's own
    down/up.
  - **Public API fully preserved** (`Key.*` constants, `press_key(key,
    hold_ms=50.0)`, `key_down`, `key_up`, `type_text(text, delays=None)`) —
    zero changes needed to `controller.py`, `interaction.py`, or any routine
    (`fish_and_cook.py`, `iron_mining.py`, `melee_fighter.py`); confirmed via
    grep that `_PYNPUT_MAP`/`_ctrl`/pynput were referenced nowhere else.
  - Removed `pynput>=1.7` from `scripts/gamebridge/requirements.txt` — no
    external keyboard/mouse dependency remains (both use raw ctypes
    `SendInput`).
- Tests: `test_keyboard.py` fully rewritten — `TestKeyConstants` (every
  `Key.*` has a `_NAMED_SCANCODES` entry, nav keys are extended),
  `TestResolve`, `TestCharScan` (mocks `ctypes.windll.user32` for
  `VkKeyScanW`/`MapVirtualKeyW`, covers lowercase/uppercase/unmappable),
  `TestPressKey`/`TestKeyDown`/`TestKeyUp`/`TestTypeText` (mock `_send_scan`
  and `press_key`, asserting call sequences/flags — including the
  shift-wrap-around-character sequence for uppercase chars). Full suite:
  `python -m pytest scripts/gamebridge/tests/ -v` → 828 passed, plus the new
  139 keyboard+controller tests pass; 6 pre-existing failures in
  `test_fish_and_cook.py` are unrelated (uncommitted in-progress changes to
  `fish_and_cook.py`'s state machine, untouched by this session).

### Open / next steps

- Verify in-game: run `drop_item(mode=DropMode.SHIFT_CLICK)` and confirm
  RuneLite now shows "Drop" as the left-click default while Shift is held via
  `key_down`/the new scan-code injection.
- The 6 failing `test_fish_and_cook.py` tests (find_fire/dropping state
  transitions returning wrong next-state) are pre-existing and unrelated —
  need their own follow-up session.

---

## Session: 2026-06-14 — Generic `drop_item` helper with persistent Shift-hold

### Goal

`fish_and_cook.py`'s `dropping()` state had its own right-click/verified-menu
"Drop" logic, duplicated nowhere else but the obvious next routine to need it
(any inventory-clearing step) would've copy-pasted it. Extract a generic
`InteractionRoutine.drop_item` helper, and switch the default gesture from
right-click-drop to **hold Shift + left-click** (RuneLite's shift-click default
is "Drop") — with Shift held continuously across the *whole* multi-item drop
sequence, the way a real player would, not tapped per click.

### Findings / Decisions

- New low-level primitives in `input/keyboard.py`: `key_down(key)` /
  `key_up(key)` — press-only / release-only, unlike `press_key` which does
  both. Backed `GameController.hold_key`/`release_key`/`release_all_keys`
  (`_held_keys: set[str]`, idempotent hold, no-op release if not held).
  - **Naming collision note**: an *unrelated* `GameController.hold_key` was
    mentioned in the 2026-06-04 "Camera Movement" entry below, but that was
    later refactored into `kb_input.press_key(key, hold_ms=...)` (see
    `rotate_camera`) — the name was free. Today's `hold_key`/`release_key` is
    a different API: a bare press/release pair with no duration, meant to
    stay down across several ticks.
- New `DropMode` enum (`routines/interaction.py`): `SHIFT_CLICK` (default) vs
  `RIGHT_CLICK` (the original verified-menu-click flow, preserved for cases
  where shift-click isn't appropriate).
- New `InteractionRoutine.drop_item(game, ctrl, item_ids, mode=SHIFT_CLICK,
  group_id=Inventory.GROUP) -> bool`. Finds the first inventory widget whose
  `itemId` is in `item_ids`:
  - `SHIFT_CLICK`: `ctrl.hold_key(Key.SHIFT)` + `ctrl.click_widget(widget)`,
    one item per tick, no menu verification needed (shift-click is
    instant/unambiguous). Returns `True` (stay) while a match remains;
    `False` once none do, after `ctrl.release_key(Key.SHIFT)`.
  - `RIGHT_CLICK`: original `right_click_widget` → `verified_menu_click(game,
    ctrl, "Drop", None)` flow via `self._drop_target` (moved from
    `FishAndCookRoutine` into `InteractionRoutine.__init__` since it's now
    shared state).
  - Callers loop: `if self.drop_item(...): return None` / `return
    "next_state"`.
- **Stuck-Shift safety nets** — a held modifier surviving past its intended
  scope is a real risk (physically stuck key in subsequent gameplay):
  - `Routine.tick()`'s exception handler (`routines/base.py`) now calls
    `ctrl.release_all_keys()` if a state raises mid drop-sequence. Guarded
    with `if ctrl is not None` — `test_routine.py`'s `_tick()` helper passes
    `ctrl=None` for several existing tests.
  - `DecisionEngine.set_routine()` (`decision/engine.py`) calls
    `ctrl.release_all_keys()` before swapping/clearing the routine, so an
    operator-triggered routine swap mid-drop can't leave Shift down.
- `fish_and_cook.py`'s `dropping()` is now just
  `self.drop_item(game, ctrl, self.DROP_ITEM_IDS, mode=DropMode.SHIFT_CLICK)`.
- Tests: `test_keyboard.py` (`TestKeyDown`/`TestKeyUp`), `test_controller.py`
  (`TestHoldKey`/`TestReleaseKey`/`TestReleaseAllKeys`, patching `kb_input`),
  `test_interaction.py` (`TestDropItemShiftClick`/`TestDropItemRightClick`),
  `test_fish_and_cook.py` (`TestDropping` rewritten for shift-click),
  `test_routine.py` (exception → `release_all_keys`), `test_decision_engine.py`
  (`_Ctrl` stub gained `release_all_keys`/counter + `set_routine` test). 826
  tests pass overall (up from 801).

### Open / next steps

- Only `fish_and_cook.py` calls `drop_item` so far; the generic helper is
  ready for any future "clear inventory of X" step (e.g. a banking routine
  dropping junk before depositing).
- `DropMode.RIGHT_CLICK` is exercised only via `test_interaction.py` now (no
  routine currently uses it) — fine, it's preserved for routines where
  shift-click's "Drop" isn't the desired left-click default action.

---

## Session: 2026-06-14 (3) — Windows SendInput integration harness and hardware-state tests

### Goal

Validate the GameBridge Windows SendInput path with a real GUI target window and OS-level key state assertions. Keep these checks gated behind `GAMEBRIDGE_INTEGRATION=1` so the default unit test run is unaffected.

### Findings / Decisions

- Mouse and keyboard SendInput differ fundamentally on Windows:
  - injected mouse events go to whatever window is under the cursor;
  - injected keyboard events go to whichever window currently has keyboard focus.
- Programmatic foreground-stealing (`SetForegroundWindow`, `AttachThreadInput`,
  ALT trick) is unreliable against a freshly created Tk window in this session.
- A real SendInput mouse click does transfer focus via normal click-to-focus
  behavior, so the test harness clicks the Entry first before sending
  keyboard input.
- The integration harness is a standalone Tkinter process with an Entry and a
  Canvas. It reports startup geometry plus every key and mouse event as JSON
  lines on stdout.
- The test launcher reads the harness stdout, computes absolute click points,
  and exercises the public `scripts.gamebridge.input.mouse` /
  `scripts.gamebridge.input.keyboard` functions.
- `press_key`/`key_down`/`key_up` now no-op cleanly when given an unknown key
  name, so invalid input does not generate spurious events.

### Open / next steps

- Run the new integration suite manually on Windows with
  `set GAMEBRIDGE_INTEGRATION=1 && python -m pytest scripts/gamebridge/tests/integration -v`.
- If these tests still fail due to focus loss, the harness should be extended
  to optionally show a visual click indicator and pause before keyboard input.

## Session: 2026-06-08 (8) — Extracted shared `InteractionRoutine` base class

### Goal

`iron_mining.py` and `melee_fighter.py` had grown three near-identical
tick-by-tick gating blocks (camera/occlusion/idle-settle, and "verify before
you click" menu confirmation). Extract the reusable parts into a shared base
so future routines (banking, questing, etc.) don't re-derive them.

### Findings / Decisions

- New module `routines/interaction.py` — `InteractionRoutine(Routine)` with
  two helpers, both designed to be called once per tick and never block:
  - **`approach(game, ctrl, entity) -> bool`** — collapses the
    bring-on-screen → occlusion-check → `player_idle()` → one-tick-settle-
    buffer chain that appeared in `find_ore`, `walk_to_bank`, and
    `find_target`. Returns `True` exactly once it's safe to click (and resets
    its own `_approach_idle_since_tick` buffer for the next cycle), so call
    sites collapse to `if not self.approach(game, ctrl, entity): return None`.
  - **`verified_menu_click(game, ctrl, verb, target_name) -> MenuClick`** —
    collapses the right-click-then-confirm-the-row flow shared by
    `find_target` (Attack) and `looting` (Take): returns a `MenuClick` enum
    (`CONFIRMED` / `ABANDONED` / `PENDING`, the last dismissing a stuck-open
    menu via `ctrl.dismiss_menu`).
- **Found and fixed a gating-order inconsistency**: `find_ore`/`find_target`
  checked camera/occlusion *before* `player_idle()`, but `walk_to_bank`
  checked idle *first*. No comment explained the difference — looked like
  incidental drift rather than a deliberate design choice, so `approach()`
  standardises on the camera-first order (2-of-3 sites already used it).
  Net effect: `walk_to_bank` now still calls `bring_entity_on_screen` while
  the player is mid-walk (previously skipped) — functionally equivalent
  (still won't click until idle), just consistent gating order everywhere.
  Updated `test_walk_to_bank_does_not_click_while_player_moving` accordingly.
- `IronMiningRoutine` and `MeleeFighterRoutine` now extend
  `InteractionRoutine`; their private `_idle_since_tick` fields were removed
  in favour of the shared `_approach_idle_since_tick` (tests renamed to match).
- New `tests/test_interaction.py` — unit-tests the two helpers in isolation
  (mocked `game`/`ctrl`) covering camera/occlusion/idle/settle-buffer gating
  and all three `verified_menu_click` outcomes. 685 tests pass overall.

### Open / next steps

- `_nearest_available_npc` (melee_fighter) and the ore/bank lookup in
  iron_mining weren't extracted — they're thin wrappers around
  `GameState.nearest_object`/`npcs_named` plus routine-specific filtering, not
  worth abstracting yet. Revisit if a third routine needs "nearest X excluding
  Y" with different exclusion predicates.

---

## Session: 2026-06-08 (7) — Live-play feedback: stuck menu fix + occlusion TOCTOU + reachability backlog

### Goal

Triage three issues the user observed running `MeleeFighterRoutine` live:
1. The bot got stuck with an empty/non-matching right-click menu open — had
   to manually wiggle the mouse to free it.
2. The bot sometimes tried to fight an NPC standing behind a door.
3. The bot sometimes right-clicked a Goblin that was occluded by a UI panel
   — is `is_occluded`/the occlusion guard buggy, or does the routine just
   not check?

### Findings

1. **Confirmed bug — stuck on a menu with no matching entry.** In both
   `find_target` and `looting`, the "menu open without a match" branch only
   handled two cases: a verified click (commit) or the menu having already
   *closed* (reset and retry). A menu that stays *open* with no matching row
   — e.g. the right-click landed on a tile/another entity instead of the
   NPC/item — fell through neither branch and the routine returned `None`
   forever. Right-click menus don't time out on their own in OSRS; nothing
   else would ever close it. → added `GameController.dismiss_menu()`
   (`controller.py`), which moves the cursor to whichever side of the menu's
   bounding box has more clearance so the client auto-closes it, and wired
   both routine branches to call it when stuck. Once the menu closes,
   the existing "closed without a match → reset and retry" path takes over.
2. **Occlusion check exists and is correct — this is a TOCTOU gap, not a
   missing/buggy check.** `find_target` *does* call
   `game.is_occluded(target["canvasX"], target["canvasY"])` immediately
   before issuing the right-click, on a freshly re-fetched `target` each
   tick (`melee_fighter.py:111`). The gap: `ctrl.right_click_entity()`
   then performs a real-time, animated mouse move
   (`wind_mouse_to_prediction`, governed by `HumanEmulator` move-speed —
   can take hundreds of ms of wall-clock time) *before* `click_right()`
   actually fires. A UI element (level-up box, chat overlay, random event,
   trade request, ...) can pop open and cover the target's canvas position
   during that window — passing the check, then having the physical click
   land on the new panel instead. `_onscreen_canvas_pos` (the shared guard
   inside `right_click_entity`/`click_entity`) checks on-screen + viewport
   bounds but has no occlusion awareness at all — occlusion is entirely the
   caller's responsibility, checked once, too early.
   → **Not fixed this session** (would need an occlusion re-check the
   instant before `click_right()`/`click_left()` fires inside
   `_onscreen_canvas_pos` or the click methods themselves — see Open/next
   steps).
3. **NPC-behind-a-door is a missing capability, not a bug** — the routine
   has no notion of walkability/pathing, so it can't tell "in line of sight
   and clickable" from "visible through a window/doorway but not actually
   reachable". Needs real plugin support (walkable-tile data isn't currently
   in the wire format) — see top-priority backlog item below.

### Fixes applied

- **`controller.py`**: added `GameController.dismiss_menu(game_state)` —
  moves the cursor to the more-spacious side of the open menu's bounding
  box (left/right midpoint) via the same `_human.plan_click` → `wind_mouse`
  path `click_at` uses, minus the click. Idempotent — safe to call every
  tick the menu remains stuck (cursor-already-there is a no-op move).
  4 new tests in `TestDismissMenu` (`test_controller.py`).
- **`melee_fighter.py`**: `find_target`/`looting` now call `dismiss_menu`
  when the menu is open but lacks the expected `Attack <NPC_NAME>`/
  `Take <item>` row, instead of waiting on it indefinitely. New tests
  `test_dismisses_menu_open_without_a_match` /
  `test_dismisses_menu_open_without_a_take_match`.

### Tests

`python -m pytest scripts/gamebridge/tests/test_controller.py
scripts/gamebridge/tests/test_melee_fighter.py -q` — 132 passed.
No GAMEBRIDGE.md changes — pure Python, no plugin/wire-format changes.

### Open / next steps — TOP PRIORITY: walkable tiles + `is_reachable`

- **Add walkable-tile data to the wire format and an `is_reachable(entity)` /
  `is_reachable(world_x, world_y)` helper to `GameState`.** This is the
  underlying fix for "NPC behind a door": today the routine can only ask
  "is it visible/on-screen/unoccluded", never "can I actually path to it".
  Sketch:
  - Plugin side (`TickMessageBuilder`/`GameBridgePlugin`): RuneLite's
    `Client` exposes per-tile collision data via `getCollisionMaps()` /
    `CollisionData.getFlags()` (bitmask of `CollisionDataFlag` — blocked
    movement directions, wall presence, etc.) for the loaded scene region.
    Need to figure out the right granularity to ship per tick (probably
    just the flags for tiles in/near the player's local area, not the
    whole loaded region — bandwidth) and add it as a new optional
    category (config-gated like `exposeMenu`/hull filter, default off
    until proven useful, given the payload size concern).
  - Python side: a reachability helper that walks the flag grid (simple
    BFS/flood-fill from the player's tile, bounded by render distance)
    rather than naive Chebyshev distance — "nearest by tile distance" is
    exactly what currently lets the routine target a Goblin one tile away
    through a wall.
  - Both `_nearest_available_npc` (melee_fighter) and any future
    object-interaction routine would gate target selection on
    `is_reachable(...)` the same way they already gate on
    `entity_near_other_player`.
  - Update `GAMEBRIDGE.md` per the Game Bridge maintenance rule — this is
    a wire-format addition (new tick category + config key).
- **Occlusion TOCTOU** (finding 2 above): move the `is_occluded` check (or
  an equivalent one) to fire immediately before the physical click inside
  `_onscreen_canvas_pos`/`right_click_entity`/`click_entity`, re-resolving
  the entity's *current* canvas position from a fresh game-state read right
  before `click_right()`/`click_left()` — not just once, early, by the
  caller. Lower priority than reachability (rarer — needs a UI panel to pop
  mid-gesture — and usually self-corrects via the existing miss-click/
  menu-verification retry paths), but a real, reproducible bug.
- **Still not live-tested**: the `dismiss_menu` fix is unit-tested but
  unverified against a real stuck-menu scenario in actual play — worth
  confirming in a follow-up session that nudging the cursor to the
  computed dismiss point reliably closes the native minimenu in practice
  (timing/distance may need tuning against real client behaviour).

---

## Session: 2026-06-08 (6) — Live recording analysis: fixed melee_fighter + resolver bug

### Goal

Analyse the first real recording made with the session recorder
(`recordings/killing-and-looting-two-goblins.jsonl` — 87 ticks, 9 clicks,
"attacked and looted two goblins"), use it to correct `MeleeFighterRoutine`
where its assumptions don't match real play, and fix whatever the recording
exposed in the recorder/resolver itself.

### Findings from the recording

1. **`NPC_NAME = "GoblinMeleeFighter"` doesn't exist.** The real NPCs are
   named `"Goblin"` (menu entry: `"Attack Goblin (level-2)"`). With the old
   constant, `npcs_named()` would return nothing and the routine would never
   find a target. → changed `NPC_NAME` to `"Goblin"` (and updated the
   `GOBLIN_ON_SCREEN`/`GOBLIN_OFF_SCREEN` test fixtures' `name` to match —
   `_nearest_available_npc` filters by `NPC_NAME` so a stale fixture name
   would silently break every find_target test).
2. **`LOOT_WINDOW_TICKS = 3` is too short for multi-item drops.** Goblin #1
   dropped two items (Body rune + Bones); the corpse vanished after tick 83
   (death detected tick 84), the rune was picked up at tick 85 (+1) but Bones
   not until tick 88 (+4) — one tick *past* where a 3-tick window would
   already have bailed back to `find_target`, abandoning the second item.
   → bumped to `LOOT_WINDOW_TICKS = 5`.
3. **Goblin index 2796 "dying" then reappearing 35 ticks later is a
   respawn reusing a recycled NPC slot index — expected RS behaviour**, not
   a routine bug. Confirms the `index`-based death-detection assumption is
   safe in practice (recycling happens with far more delay than the 3–5 tick
   loot window could ever collide with).
4. **The resolver swallowed every in-world click.** All 9 real clicks
   resolved as either `menuEntry` (when a context menu happened to already
   be open) or generic `widget G122:0` — *never* `npc`/`groundItem`, even
   though the player directly attacked a Goblin (left-click at tick 89,
   8px from NPC index 2797) and looted ground items. Root cause: RuneLite's
   `interfaces` dump always includes group 122 (`InterfaceID.XP_DROPS`,
   confirmed via `InterfaceID.java`) with bounds `(0,0,625,412)` — the full
   game canvas — present on 87/87 ticks. `resolve_click` checked
   `game.interfaces` (any group) before entity hulls, so this background
   overlay intercepted every click before the hull test ever ran. Unit
   tests never caught it because their fixtures only ever used small,
   specific widget rects (inventory slots etc.), never a full-viewport
   background pane.

### Fixes applied

- **`melee_fighter.py`**: `NPC_NAME` → `"Goblin"`, `LOOT_WINDOW_TICKS` 3 → 5
  (with a comment on why — multiple drops need more than one pickup gesture).
- **`melee_fighter.py` redesign (per explicit user request)**: both
  `find_target` and `looting` now use the documented "verify before you
  click" pattern from `Controller.click_menu_entry` — right-click the
  target/item, confirm an `"Attack <NPC_NAME>"` / `"Take <item name>"` entry
  is actually present in the context menu, then click that exact row, rather
  than blind-left-clicking via `click_entity`. New `_attack_target`/
  `_loot_target` instance vars track the in-flight gesture across ticks
  (mirrors the `_right_clicked` example in `click_menu_entry`'s docstring);
  a closed menu with no match resets and retries rather than abandoning.
  `test_melee_fighter.py` rewritten accordingly (39 tests).
- **`resolver.py`**: `resolve_click` now skips `interfaces` entries whose
  group doesn't pass `iface_registry.occludes(group_id)` — the same
  whitelist `GameState.is_occluded` already uses — so background/chrome
  groups (viewport roots, xp drops, ...) fall through to the entity-hull
  test instead of shadowing it. Registered group 122 in
  `state/interfaces.py` as `InterfaceInfo("xp_drops", occludes=False)`.
  Added regression tests in `test_recording_resolver.py` covering: a
  full-canvas background pane no longer shadows an entity hull beneath it,
  falls through to `viewport` when nothing's beneath it, and a *real*
  occluding panel (inventory) still correctly wins over an entity behind it.

### Tests

All 665 Python tests pass (`python -m pytest scripts/gamebridge/tests/ -q`).
No GAMEBRIDGE.md changes — no wire-format/plugin changes, pure Python fixes.

### Open / next steps

- **Still not live-tested with the new menu-verification flow** — the
  `right_click_entity`/`click_menu_entry` gesture sequencing in
  `find_target`/`looting` is unit-tested but unverified in a real session.
  Worth a follow-up recording run specifically targeting Goblins to confirm
  the gesture timing (right-click → menu populates → verify → click) holds
  up across ticks in practice, and that `LOOT_WINDOW_TICKS = 5` is enough
  headroom for the slightly-slower right-click+verify pickup path (the
  manual recording used menu-navigation throughout, so its timings are a
  reasonable but not perfect proxy for the routine's own gesture costs).
- Possible follow-up: audit other interface groups likely to share XP_DROPS'
  "always-loaded, full-canvas, no occludes flag" shape (orbs, world-map
  button, etc.) — they'd have the same swallowing effect on `resolve_click`
  if a click ever lands in their bounds, just less frequently than 122.

---

## Session: 2026-06-08 (5) — Session Recorder: capture manual play to reverse-engineer routines

### Goal

Add a "Record" feature to the dashboard: capture the full TCP tick stream plus
the user's real mouse clicks while they play manually, producing a file that
can be transcribed into a routine afterwards (per the user's request — they
want to record themselves performing an action sequence, then write the
equivalent `Routine` state machine from the recording).

### Design decision — resolve clicks against live game state at record time

Bare `(screen_x, screen_y, timestamp)` click logs would force whoever writes
the routine to manually cross-reference each click against the tick stream
after the fact (hulls/bounds/camera all change tick-to-tick, so this is
genuinely hard to do after the session ends). Instead, **`resolve_click()`
hit-tests the click's canvas coordinate against the *current* tick's geometry
at the moment it happens** — open menu entries → UI widgets/interfaces →
entity hulls (NPC/player/object/groundItem, ray-cast polygon test) → viewport
fallback — and the recorder writes the *resolved* description (e.g. `object
"Iron rocks" (id=11364) at world (3185,3304)` / `menu entry "Attack Goblin
(level-2)"`) alongside the raw coordinates. The output reads as an annotated
action log, close to routine pseudocode already.

### New files

- `recording/click_monitor.py` — daemon thread polling
  `GetAsyncKeyState(VK_LBUTTON/VK_RBUTTON)` + `GetCursorPos`, mirroring
  `hotkeys.py`'s no-extra-dependency pattern. Reports button-down transitions
  only (not held-button repeats), at 10ms poll interval (faster than the 50ms
  hotkey poll — clicks are short and position precision matters more).
- `recording/resolver.py` — `resolve_click(canvas_x, canvas_y, game) -> dict`.
  Always returns a dict (never None) with `kind` ∈ {menuEntry, widget, npc,
  player, object, groundItem, viewport} plus a human-readable `summary`.
  Duplicates `fov._point_in_polygon`'s ray-casting algorithm locally rather
  than importing the module-private helper across packages.
- `recording/recorder.py` — `SessionRecorder`. Writes JSONL to
  `~/.gamebridge/recordings/recording-<timestamp>.jsonl`: one `tick` record
  per tick (raw message verbatim — satisfies "record all the TCP events and
  game state objects"), one `click` record per resolved click (+ player
  context: position/animation/interacting-with), bookended by `session_start`/
  `session_end`. Thread-safe: `record_tick` runs on the GUI thread (via
  `BridgeTicker`'s queued signal), `record_click` on the click-monitor daemon
  thread — both serialise file writes through one `threading.Lock`.
- `ui/recording_tab.py` — new "Recording" dashboard tab: Start/End toggle
  button, live status (duration/tick-count/click-count), output path, and a
  scrolling log of resolved clicks as they occur (immediate confirmation that
  hit-testing is working as expected).

### Controller additions

`GameController` gained two small public coordinate helpers (alongside the
existing private `_canvas_to_screen`/`_is_canvas_coord_valid`):
- `screen_to_canvas(sx, sy)` — exact inverse of `_canvas_to_screen` (including
  the `hull_y_offset` calibration), so a raw OS click position can be
  hit-tested against `canvasX/Y`/`hull` geometry in the same coordinate space.
- `is_screen_point_in_window(sx, sy)` — filters out clicks made on other
  windows (the dashboard itself, browser, etc.) while recording; only in-game
  clicks are meaningful for reverse-engineering a routine.

### Wiring

`dashboard.py`: added the tab, one line in `_on_tick` (`self._recording_tab
.on_tick(msg)` — feeds the raw message, since `BridgeTicker` already
guarantees `self._engine.game` is the matching snapshot by the time `_on_tick`
fires), and `stop_if_recording()` in `closeEvent` so an in-progress recording
gets its `session_end` footer instead of being left truncated if the window
closes mid-session.

### Tests

- `test_recording_resolver.py` — priority ordering (menu > widget > entity >
  viewport fallback), correct field extraction per kind, hull-less entities
  skipped, closed-menu ignored.
- `test_recording_recorder.py` — JSONL structure round-trips
  (`session_start`/`tick`/`click`/`session_end`), counters match the returned
  summary, capture calls are safe no-ops outside an active session, file is
  closed (not locked) after `stop()`. Redirects `RECORDINGS_DIR` to `tmp_path`
  via monkeypatch — never touches the user's real `~/.gamebridge/recordings`.
- `test_controller.py` — added `TestScreenToCanvas` (round-trips with
  `_canvas_to_screen`, applies `hull_y_offset`, None when window missing) and
  `TestIsScreenPointInWindow` (inclusive top-left / exclusive bottom-right
  bounds, matching `_is_canvas_coord_valid`'s half-open convention).

All 656 Python tests pass (`python -m pytest scripts/gamebridge/tests/ -q`).

### Open / next steps

- **Not yet live-tested** — needs a real recording session in-game to confirm
  the click monitor fires correctly, hull hit-testing resolves real clicks as
  expected, and the JSONL is actually pleasant to transcribe from. Do this
  before relying on it to build a routine.
- No GAMEBRIDGE.md changes needed — this is pure Python tooling on the
  consumer side; the wire format/plugin config is untouched.
- Possible follow-up if recordings prove noisy: minimap-click resolution
  (currently falls through to generic `viewport`) and keyboard capture
  (currently mouse-only) if routines built from recordings need either.

---

## Session: 2026-06-08 (4) — Phase 4: wiring `MovingTarget` into the click path

### Goal

Connect Phases 2/3 to the actual click flow: make `GameController.click_entity`
/ `move_to_entity` / `right_click_entity` predict where a moving entity will be
by the time the cursor arrives — using `EntityTracker` velocity + `MovingTarget`
+ `wind_mouse_to_prediction` — instead of aiming at a one-shot, increasingly
stale `canvasX`/`canvasY` snapshot.

### Design decisions

- **`EntityTracker` ownership & thread safety** — the open question carried
  over from Phases 2/3. `GameController` now constructs and owns it
  (`self._tracker = EntityTracker()` in `__init__`, alongside `_minimap_walk`/
  `_on_screen_since_tick` — it already owns several other pieces of tick-driven
  tracking state). `DecisionEngine.drive()` feeds it once per cycle via a new
  `GameController.track_entities(game_state)`, called right after capturing
  `game = self._game` and *before* `routine.tick()` runs — so any prediction
  the routine triggers this tick sees this tick's velocity data.
  - **Critically, this keeps `EntityTracker` entirely on the routine-driver
    thread.** Unlike `GameState`, which is published as immutable `clone()`
    snapshots specifically so `ingest()` (BridgeTicker thread) and `drive()`
    (RoutineRunner thread) never race, `EntityTracker` is a plain mutable
    object with no such guarantee — `update()` mutates dicts in place.
    Feeding it from `ingest()` (as the Phase 3 PLAN.md draft speculated)
    would reintroduce exactly the cross-thread hazard `clone()` exists to
    prevent: a `drive()`-thread read racing an `ingest()`-thread write.
    Owning it on the controller and feeding it only from `drive()` sidesteps
    this entirely — no locking, no snapshotting, just single-thread ownership.
  - **This is correct, not lossy, even though `drive()` can skip snapshots**
    under load (see `DecisionEngine`'s module docstring on the ingest/drive
    split — `wait_for_snapshot()` collapses backlogs). `EntityTracker._velocity`
    already normalises by the *actual* tick delta between the two samples it
    has (`dt = current.tick - previous.tick`), so two-sample velocity stays a
    correct per-tick rate regardless of how many real ticks separate the
    `update()` calls `drive()` happens to make.
  - Tracking only runs while a routine is active (`if routine is None: return`
    precedes `track_entities`) — no routine means nothing will click, so
    there's no point spending the (tiny) cost of tracking.
- **Resolving "which `EntityTracker.*_velocity` do I call for an arbitrary
  entity dict?"** — `click_entity` et al. accept npcs, players, objects *and*
  ground items interchangeably (confirmed by grepping every call site:
  `iron_mining`/`melee_fighter`/`game_state.py` pass all four kinds through).
  Added a generic dispatcher, **`EntityTracker.velocity(entity, space)`**,
  that routes by which of three *mutually exclusive, kind-defining* fields the
  entity carries — straight from the GAMEBRIDGE.md field tables: NPCs alone
  have `index`, objects alone have `category`, ground items alone have
  `quantity`; whatever's left has the player shape (`id`/`combatLevel`/
  `animation`, no `index`). This keeps the "how do I identify/key this entity"
  knowledge centralised in the one module that already owns it, rather than
  leaking it into the controller.
  - **Ground items are deliberately not tracked** — extending `EntityTracker`
    to a fourth identity scheme (it would need its own `(id, worldX, worldY)`
    dict, mirroring `_objects`) for drops that are themselves stationary felt
    like unwarranted scope growth. `velocity()` returns `None` for them
    immediately. Crucially **this isn't a degradation**: `MovingTarget`
    already treats `None` velocity as "static", and a ground item *is* static
    — `None` is the *correct* answer here, the same one a freshly-spawned,
    not-yet-double-sampled object would also get.
  - Verified the dispatcher can't cross-contaminate id keyspaces: an object
    and an NPC that happen to share a numeric `id` are tracked completely
    independently because routing is by *shape* (which dict + which key
    function), never by the `id` value itself
    (`test_dispatch_does_not_cross_contaminate_id_keyspaces`).
- **Composing prediction with the existing human-emulator click-error jitter**
  — new private helper `GameController._plan_moving_click(entity, cur_x, cur_y)`
  returns `(intent, predict)`:
  - `intent` (pauses, `move_speed`, `double_click`) is planned *once*, against
    the target's *currently* predicted screen position — these are properties
    of how the human acts, not tied to a specific point in space, so a single
    `ClickIntent` for the whole multi-step action remains correct (exactly as
    it was pre-Phase-4, just planned against a `MovingTarget.predict(now)`
    point instead of the raw snapshot `canvasX`/`canvasY`).
  - `predict` is a screen-space closure that re-evaluates `MovingTarget.predict`
    on every call (continuous re-aiming — the whole point of Phase 3's
    `wind_mouse_to_prediction`), converts canvas → screen via
    `_canvas_to_screen`, and adds the human's Gaussian click error as a
    ***fixed offset*** captured once up front (`err = intent.actual_xy -
    predict(now)_screen`). This means the cursor consistently misses by the
    same personal "miss vector" relative to *wherever the target ends up* —
    not toward a stale snapshot point — which is the more human-like model of
    the two: a person tracking a moving target re-aims continuously but their
    characteristic imprecision stays roughly constant relative to the target.
  - `_clamp_to_window` is now applied **per-call inside `predict`**, rather
    than once on `(actual_x, actual_y)` before the move (as in the old code).
    This preserves the original "Gaussian error never carries the cursor
    outside the window" guarantee *and* doubles as a guard against
    `MovingTarget.predict`'s linear extrapolation running away to absurd
    values for a fast/erratic entity — the destination `wind_mouse_to_prediction`
    is ever handed always stays inside the game window
    (`test_predict_result_stays_clamped_to_window_as_target_moves`).
  - For the common case — an entity with no velocity data yet (`None`,
    `MovingTarget` static) — `predict(at_time)` returns the *exact same*
    constant point for every `at_time`, byte-for-byte equivalent to the old
    one-shot `(actual_x, actual_y)` aim point
    (`test_stationary_entity_predicts_a_fixed_point`). Phase 4 is additive:
    objects/furnaces/ore (the overwhelming majority of `click_entity` targets)
    behave identically to before; only entities the tracker has *actually*
    sampled twice with motion get the new predictive behaviour.
- **`click_at` / `click_widget` are untouched** — they take raw canvas
  coordinates, not an `entity` dict; there's nothing to look up in the tracker
  and no `MovingTarget` to build. Still use the original one-shot `wind_mouse`.

### Files touched

- `state/entity_tracker.py` — added `EntityTracker.velocity(entity, space)`.
- `controller/controller.py` — `EntityTracker`/`MovingTarget` imports,
  `self._tracker` in `__init__`, new `track_entities()` and
  `_plan_moving_click()`, rewired `move_to_entity`/`click_entity`/
  `right_click_entity` onto `wind_mouse_to_prediction`.
- `decision/engine.py` — `drive()` now calls `self._ctrl.track_entities(game)`
  before running the routine.

### Tests added

- `test_entity_tracker.py`: `TestGenericVelocityDispatch` (5 tests) — routes
  npc/player/object correctly by shape, ground items return `None`/untracked,
  no id-keyspace cross-contamination. Added a `_ground_item` fixture helper
  matching the GAMEBRIDGE.md ground-item shape.
- `test_controller.py`: extended `_entity()` with `id`/`index` (the dispatcher
  needs *some* identity field to route on without `KeyError` — an NPC shape is
  the most common real `click_entity` target). Updated every
  `wind_mouse`-asserting test for `click_entity`/`move_to_entity`/
  `right_click_entity` to assert on `wind_mouse_to_prediction` instead, and to
  pull the `predict` callable out of `call_args` and invoke it to inspect the
  resulting screen point (rather than reading fixed `actual_x`/`actual_y` args
  that no longer exist in the new call signature). Added `TestPlanMovingClick`
  (4 tests): tracker queried in `"canvas"` space with the exact clicked entity;
  stationary entities predict a constant point equal to the old aim point;
  moving entities extrapolate linearly by the tracker's reported per-tick
  velocity (`pytest.approx`, scaled by `TICK_DURATION_S`); predictions stay
  clamped to the window even under wild extrapolation.
- `test_decision_engine.py`: extended the `_Ctrl` stub with a recording
  `track_entities()`. Added 3 tests: `drive()` feeds the controller the exact
  current snapshot exactly once per cycle; it does *not* track while idle (no
  routine); and — using a small `_Recorder` routine that inspects
  `ctrl.tracked_states` from inside `tick()` — the feed happens *before* the
  routine runs, so in-tick predictions always see this tick's data.

Full suite: 582 passed (570 + 12 new), 8 pre-existing unrelated failures in
`test_melee_fighter.py` (identical WIP failures flagged in every session
above — confirmed unaffected once again).

### Open / next steps

- **Carried over from Phase 1, still open**: verify whether `canvasX`/
  `canvasY` is already the hull centroid, or whether `EntityTracker`/
  `MovingTarget` should track the hull centroid instead. Not investigated
  this session either — Phase 4 simply predicts forward whatever
  `canvasX`/`canvasY` already represents, so this remains an independent
  question about the *accuracy* of the base position, not the prediction
  built on top of it. Check `GAMEBRIDGE.md` / the Java hull computation
  (`runelite-client/…/plugins/gamebridge/`) when picking this up.
- **Live calibration, still open from the Phase 3 entry**: no live data yet
  to confirm `MovingTarget`'s linear-extrapolation model is a good fit for
  OSRS's tile-stepped (not continuous) movement. Worth observing a routine
  clicking a wandering NPC (melee_fighter is the natural candidate — it
  already calls `click_entity(target)` on NPCs) and checking whether clicks
  land cleanly on moving targets, or whether a per-tick step function would
  track better than linear pixel interpolation between samples.
- **The Phase 1→4 arc is now functionally complete**: identity tracking →
  velocity → prediction → wired into every entity-click path. Nothing further
  is "owed" to this chain; remaining work is tuning/validation against live
  play, which needs an actual game session rather than more code.

---

## Session: 2026-06-08 (3) — Phase 3: `MovingTarget` + predictive `wind_mouse` variant

### Goal

Build the prediction layer that Phase 2's `EntityTracker` velocity data feeds
into: a `MovingTarget.predict(at_time)` abstraction, plus a `wind_mouse`
variant that aims at — and continuously re-aims at — a moving destination
instead of the one-shot `canvasX`/`canvasY` snapshot `click_entity` currently
reads. Phase 4 (wiring this into the controller) is still a separate step.

### Design decisions

- **`MovingTarget`** lives in `state/moving_target.py` (`scripts/gamebridge/`),
  alongside `entity_tracker.py` — both are "derived-from-game-state"
  abstractions, keeping `controller.py` focused on orchestration/hardware
  driving rather than prediction math.
  - **Decoupled from `EntityTracker` by design**: it only stores
    `canvas_pos`, an optional `canvas_velocity` (px/tick), and `as_of` (a
    `time.monotonic()`-based wall-clock float) — all supplied by the caller.
    `from_entity(entity, canvas_velocity, as_of)` is a thin convenience
    constructor documenting the intended call shape
    (`tracker.npc_velocity(entity, "canvas")` → `MovingTarget.from_entity`),
    without importing `EntityTracker` itself. Mirrors `HumanEmulator`'s "pure,
    no side effects, no implicit `time.monotonic()`" style — `as_of` is always
    explicit, which is what makes `predict()` trivially deterministic to test.
  - **`predict(at_time)`** converts `at_time - as_of` (wall-clock seconds) to
    elapsed game ticks via a new `TICK_DURATION_S = 0.6` module constant, then
    extrapolates `canvas_pos + canvas_velocity * elapsed_ticks`. This is the
    *third* place `~600ms/tick` is encoded (`InterruptionScheduler
    .TICK_DURATION_S`, `iron_mining.py`'s inline `* 600`, now this) — noted
    in the docstring as a known duplication rather than introducing a shared
    constant module for one more caller (would be premature given the other
    two have stood alone this long).
  - **`canvas_velocity=None` → degrades to a static prediction** (just returns
    `canvas_pos`). Matches `EntityTracker`'s "`None` until two consecutive
    on-screen sightings" contract from Phase 2 — an entity with unknown
    velocity is treated as stationary, never guessed at.
- **`wind_mouse_to_prediction`** lives in `input/mouse.py` next to `wind_mouse`
  — it's fundamentally the same movement algorithm, just re-aimed each step.
  - Takes `predict: Callable[[float], tuple[float, float]]` rather than a
    `MovingTarget` directly, so the input layer (which currently has zero
    knowledge of game-state/prediction concepts — it only ever saw raw floats)
    stays decoupled; the controller passes `target.predict` as that callable.
  - **Re-evaluates the destination every step** via `predict(time.monotonic())`
    — both inside the approach loop and for the final correction — so the
    cursor continuously re-aims at where the target is *expected to be on
    arrival*, the way a human visually re-tracks a moving target while
    reaching for it.
  - **"Lock-on correction" replaces the noisy fine-approach phase**: the
    wind+gravity loop now runs until `dist <= target_area` (instead of
    `dist <= 1.0`), then does one final, precise `move_to()` on a freshly
    re-evaluated prediction. Letting the original algorithm's noisy,
    shrinking-step fine-approach (`dist < target_area` branch) keep chasing a
    still-moving point all the way to sub-pixel distance would be slow and
    could overshoot a target that changes direction mid-approach — a single
    accurate final snap is both simpler and more robust for a moving target.
  - Otherwise identical physics/parameters to `wind_mouse` (same gravity/wind/
    step/easing formulas) — deliberately not refactored to share code with
    the original, to avoid risking the well-tuned, already-shipped function;
    "a wind_mouse variant" per the Phase 3 plan means a new function, and the
    duplication is small and physically meaningful (the only real difference
    is *what* `dest_x`/`dest_y` are and when they're refreshed).

### Tests added

- `test_moving_target.py` (10 tests): `TestPredictWithoutVelocity` (static
  regardless of `at_time`), `TestPredictWithVelocity` (returns `canvas_pos` at
  `at_time == as_of`, extrapolates correctly for 1 and N ticks, and — as pure
  linear extrapolation with no special-casing — also for times *before*
  `as_of`), `TestFromEntity` (factory wiring + `None`-velocity passthrough).
- `test_mouse.py` (5 tests, **new file** — `wind_mouse`/hardware-input
  functions had no direct unit tests before this; mocking `move_to`/
  `time.sleep`/`time.monotonic` at module level via `unittest.mock.patch`
  made `wind_mouse_to_prediction` tractable to test directly, unlike the
  ctypes-`SendInput`-touching primitives it builds on, which remain only
  indirectly covered via the controller-level `mouse_input` mocks):
  lands on a stationary target; the final move matches `predict()`'s very
  *last* return value (proves the lock-on uses a fresh re-prediction, not a
  stale one); `predict` is queried far more than once (proves continuous
  re-evaluation, the whole point of the variant); `predict` receives
  `time.monotonic()`-sourced timestamps; terminates well within the
  `steps < 10_000` cap (regression guard against infinite re-chasing).

Full suite: 570 passed, 8 pre-existing failures in `test_melee_fighter.py`
(same WIP-file failures flagged unrelated in the two sessions above).

### Open / next steps

- **Phase 4** — wire `MovingTarget`/`wind_mouse_to_prediction` into
  `GameController.click_entity`/`move_to_entity`/`right_click_entity`,
  replacing the one-shot `canvasX`/`canvasY` reads. This is also where an
  `EntityTracker` instance's lifecycle finally gets decided (who constructs
  it, who calls `update()` each tick — likely `DecisionEngine.ingest()`
  alongside `GameState.clone()`+publish — and how the controller reaches it,
  e.g. `GameController(human=..., tracker=...)`).
- Carried over from Phase 1: first verify whether `canvasX`/`canvasY` is
  already the hull centroid, or whether `EntityTracker`/`MovingTarget` should
  track the centroid instead (check `GAMEBRIDGE.md` / the Java hull
  computation).
- Once wired in, watch live behaviour on a moving NPC (e.g. a wandering cow or
  a player-vs-player scenario) to confirm `predict()`'s linear extrapolation
  is a good enough model for OSRS movement (which is tile-stepped, not
  continuous) — if entities visibly "teleport" between tiles rather than
  glide, a per-tick step function might track better than linear pixel
  interpolation. Not addressed here — no live data to calibrate against yet.

---

## Session: 2026-06-08 (2) — Phase 2: entity identity & velocity tracking (`state/entity_tracker.py`)

### Goal

Per the Phase 2/3/4 roadmap noted in the session above: build a module that
tracks individual NPCs/players/objects across ticks by stable identity and
exposes their per-tick velocity — the data Phase 3's `MovingTarget.predict`
will need to aim `wind_mouse` at a moving target instead of a one-shot
`canvasX`/`canvasY` read.

### Design decisions

- **New standalone module**, not a `GameState` field. `GameState` is now
  published as immutable `clone()` snapshots across threads (see session
  above) — baking a mutable, in-place-updated tracker into it would
  reintroduce exactly the cross-thread corruption `clone()` exists to avoid.
  `EntityTracker` is fed snapshots externally via `update(game_state)`.
- **Identity keys** (documented in the module + GAMEBRIDGE.md cross-refs):
  - NPC -> `index` (per-instance world index; GAMEBRIDGE.md warns it "may be
    reused… only rely on it across short windows")
  - Player -> `id` (already a unique per-instance world index)
  - Object -> composite `(id, worldX, worldY)` — objects carry no per-instance
    index, but they're stationary, so id+tile is stable for as long as that
    exact instance exists, and *changes* the moment it's replaced (e.g. a
    chopped tree -> stump has a different `id` at the same tile — correctly
    tracked as a new entity, not a continuation).
  - Exposed as small pure functions `npc_key`/`player_key`/`object_key` —
    independently testable and reusable by routines wanting their own
    identity checks (GAMEBRIDGE.md's documented "did the Goblin I attacked
    die?" use case).
- **Two-sample delta, no smoothing.** Each tracked entity stores only its
  current and previous `_Sample` (`tick`, `world_pos`, `canvas_pos`) —
  mirrors the existing `GameState._prev_pos`/`_prev_animation` pattern, just
  keyed per-entity. Velocity = `(current - previous) / tick_delta`. Simplest
  thing that's correct; can add smoothing later if Phase 3 finds it noisy.
- **Velocity in per-tick units**, not per-second (`tiles/tick` world-space,
  `pixels/tick` canvas-space) — keeps the tracker independent of the ~600ms
  tick assumption; Phase 3's `predict(at_time)` does any tick<->wallclock
  conversion it needs.
- **`None` until two consecutive sightings**, and **any gap drops history**
  (an entity missing from a tick's list — despawn, or its key reused by a
  different instance — starts fresh on its next sighting). This directly
  implements the GAMEBRIDGE.md index-reuse caveat: stitching two unrelated
  sightings together would otherwise produce a bogus velocity spike.
- **Canvas velocity additionally requires both samples on-screen**
  (`canvasX`/`canvasY` not `None`); world velocity is unaffected by on-screen
  status (an entity can keep moving while off-screen).
- **API shape**: `npc_velocity(entity, space="world"|"canvas")`,
  `player_velocity(...)`, `object_velocity(...)` — three kind-specific entry
  points (mirroring `GameState`'s `nearest_npc`/`nearest_object`/
  `players_named` families) each with a `space` flag, rather than one
  `velocity_for(entity, kind)` (would need a string to disambiguate dict
  shape) or six separate `*_world_velocity`/`*_canvas_velocity` methods.

### Deliberately not done here

`EntityTracker` is **not wired into `DecisionEngine`, `GameController`, or the
dashboard** — building it as a standalone, independently fed/tested unit
avoids speculative integration. Phase 3 (`MovingTarget`) is what will actually
need live tracking data and will determine how an `EntityTracker` instance
gets owned/fed (e.g. inside `DecisionEngine.ingest()`, alongside
`GameState.clone()`+publish); Phase 4 wires `MovingTarget` into the click path.

### Tests added

`test_entity_tracker.py` (21 tests): `TestKeyFunctions` (identity key
correctness, including the same-id-different-tile and different-id-same-tile
object distinctions), `TestFirstSightingHasNoVelocity`, `TestWorldVelocity`
(correct delta across consecutive ticks, tick-gap robustness, duplicate-tick
-> `None`, stationary object -> `(0,0)`), `TestCanvasVelocity` (`None` when
either sample is off-screen, correct delta when both on-screen),
`TestIdentityResetOnGap` (despawn+reused-index/id starts fresh; an object
replaced in place is tracked as a new entity), `TestMultipleEntitiesTracked
Independently` (no cross-contamination between concurrently tracked entities).

Full suite: 557 passed, 8 pre-existing failures in `test_melee_fighter.py`
(same ones flagged unrelated in the session above — WIP file).

### Open / next steps

- **Phase 3** — `MovingTarget` abstraction (`predict(at_time)`) built on top
  of `EntityTracker.{npc,player,object}_velocity`, plus a `wind_mouse` variant
  that re-evaluates a moving destination mid-flight with a final lock-on
  correction. This is also where an `EntityTracker` instance's lifecycle
  (who constructs it, who calls `update()` each tick, how routines/controller
  reach it) gets decided.
- **Phase 4** — wire `MovingTarget` into `GameController.click_entity`/
  `move_to_entity`/`right_click_entity`, replacing the one-shot `canvasX`/
  `canvasY` read. First verify (per the carried-over open question) whether
  `canvasX`/`canvasY` is already the hull centroid, or whether the tracker/
  `MovingTarget` should follow the centroid instead.

---

## Session: 2026-06-08 — split GameState ingestion from routine driving (two-thread architecture, dashboard only)

### Problem

`DecisionEngine.process_tick()` ran both `GameState.update()` *and*
`routine.tick()` inline, on the same thread that reads the TCP stream
(`main.py`'s `for msg in stream(): engine.process_tick(msg)`, and the
dashboard's `BridgeTicker` → `_on_tick` → `process_tick`). `GameController`
click/move methods (`click_entity`, `move_to_entity`, `wind_mouse`, the
human-emulation pre/post pauses, `_after_click`'s scheduled-break sleep)
contain real `time.sleep()` calls totalling anywhere from ~0.5s to 30+s per
action. While any of that ran, `GameState.update()` could not be called —
the routine was acting on stale data, and (in the dashboard) queued tick
signals arrived in a burst once the block cleared, skipping intermediate
states entirely. `click_entity` also read `canvasX`/`canvasY` once at
click-issue time — a frozen snapshot — so a moving entity's hitbox could
have drifted well away from that point by the time `wind_mouse` arrived.

### Decisions made (with the user)

- Architecture: two threads — one whose only job is to ingest ticks into
  `GameState` (must never block), one that drives the routine off the latest
  published snapshot (may block for as long as human-like actions take).
- Scope: **dashboard only** — `main.py` is unused by the user; left untouched
  and noted as the unmaintained/legacy single-threaded path.
- Threading primitive: reuse `BridgeTicker`/`QThread` rather than bare
  `threading.Thread` — simpler to maintain alongside the existing Qt-based
  ingestion thread.
- Routine-swap timing: **finish the current tick, then swap** — matches how
  a human would behave (never abort mid-click), and needs no cancellation
  plumbing through `wind_mouse`/`time.sleep`.

### What changed

- `state/game_state.py`: added `GameState.clone()` — a snapshot copy safe to
  publish for cross-thread reading. `update()` already replaces most
  container fields wholesale each tick (sharing those references is safe);
  `clone()` gives fresh copies only of the fields `_apply_event()` mutates
  *in place* (`xp`, `levels`, `boosted_levels`, `varbits`, `last_xp_tick`,
  `chat_log`) — otherwise updating the original after cloning would corrupt
  the snapshot a concurrent reader still holds.
- `decision/engine.py`: split `process_tick()` into `ingest(msg)` (clone →
  `update()` → atomic publish via `self._game = new_state`, then
  `self._new_snapshot.set()`) and `drive()` (captures `routine = self._routine`
  once up front — this is what gives "finish current tick, then swap" for
  free, since a concurrent `set_routine()` only affects the *next* `drive()`
  call — then runs break/interruption bookkeeping + `routine.tick()`).
  Added `wait_for_snapshot(timeout)` (wraps a `threading.Event`) so the
  routine-driver loop can sleep until there's genuinely new state rather than
  polling. `process_tick()` is now just `ingest()` then `drive()` — kept for
  `main.py` and the existing single-threaded tests, which are unaffected.
- `bridge_ticker.py`: `BridgeTicker` now takes an `ingest` callable and calls
  it *inside its own `run()` loop*, before emitting `tick_received` — so
  ingestion can never be delayed by GUI work or by a routine mid-action; the
  signal exists purely so the UI can refresh, and by the time it fires
  `engine.game` already reflects the new tick. Added `RoutineRunner(QThread)`
  — loops on `engine.wait_for_snapshot()` → `engine.drive()`; if `drive()` is
  busy with a multi-tick action when several snapshots arrive, it simply
  picks up the latest on its next pass (never a backlog, never stale).
- `dashboard.py`: `_start_ticker` now wires `BridgeTicker(ingest=self._engine.ingest, ...)`
  and starts a `RoutineRunner`; `_on_tick` no longer calls `process_tick` (just
  refreshes the display from `self._engine.game`, which is already current);
  added `closeEvent` to stop `RoutineRunner` cleanly on window close
  (`BridgeTicker` has no equivalent — it blocks in a socket read with no
  clean interrupt — left to exit with the process, as before).

No GIL-unsafe sharing: `DecisionEngine` ends up needing **zero locks** —
`self._game`/`self._routine` are plain attribute assignments (atomic under
the GIL), `ingest` is single-writer (only `BridgeTicker` calls it), and
routines never mutate the `GameState` they're handed.

### Tests added

- `test_game_state.py::TestClone` — snapshot has equal values; later updates
  to either the original or the clone don't leak into the other, specifically
  covering the in-place-mutated fields (`xp`, `chat_log`) as well as the
  wholesale-replaced ones (`inventory`).
- `test_decision_engine.py::TestIngestDriveSplit` /
  `TestWaitForSnapshot` / `TestRoutineSwapTiming` — `ingest()` publishes a
  new snapshot without driving the routine, `drive()` runs against the latest
  published snapshot, `process_tick() == ingest()+drive()`, and a routine
  that calls `set_routine()` mid-`tick()` still completes its own call before
  the new routine takes over on the *next* `drive()`.
- No new tests for `BridgeTicker`/`RoutineRunner` themselves — they're thin
  QThread pass-throughs with no Qt-independent logic of their own (and no
  prior test file exercised Qt/QThread machinery in this codebase); the
  behaviour that matters is fully covered at the `DecisionEngine`/`GameState`
  level they call into.

### Open / next steps (per the original RIPER-5 plan)

- **Phase 2** — entity identity & velocity tracking (`state/entity_tracker.py`,
  keyed by NPC/player `index` or object `id`+world-pos).
- **Phase 3** — `MovingTarget` abstraction (`predict(at_time)`) + a
  `wind_mouse` variant that re-evaluates a moving destination mid-flight with
  a final lock-on correction.
- **Phase 4** — wire `MovingTarget` into `GameController.click_entity` /
  `move_to_entity` / `right_click_entity`, replacing the one-shot
  `canvasX`/`canvasY` read. First verify (check `GAMEBRIDGE.md`) whether
  `canvasX`/`canvasY` is already the hull centroid, or whether the tracker
  should follow the centroid instead.

---


## Earlier sessions (condensed 2026-06-08 — see git history for full detail)

The entries below summarise sessions that predate the Phase 1–4 `MovingTarget`
arc above. Full narrative detail (problem write-ups, false starts, line-by-line
fixes) was trimmed to keep this file manageable — `git log -p -- PLAN.md` has
the original text if needed.

### 2026-06-07 — first-move "freeze then snap" (`human/emulator.py`)

`HumanEmulator.plan_click()` derived `move_speed` from raw cursor-to-target
distance; the *first* move of a session starts hundreds of pixels outside the
game window, saturating `move_speed` at 1.0 and producing a slow, wobbly creep
followed by a snap onto the target. **Fix:** cap the distance fed into the
`move_speed` formula at 400px (the documented "typical in-game click" range)
before dividing. Added `TestPlanClickMoveSpeed` in `test_emulator.py`.

### 2026-06-07 — `bring_entity_on_screen` on-screen settle buffer (`controller.py`)

Routines clicked an entity the instant `bring_entity_on_screen` first reported
it on-screen after a camera rotation/minimap walk, then missed — the polled
`canvasX`/`canvasY` still reflected a transient mid-adjustment frame. **Fix:**
track `_on_screen_since_tick` and require `ON_SCREEN_SETTLE_TICKS` (=1)
consecutive on-screen ticks before returning `True`; resets on any new
adjustment. Mirrors the existing `_idle_since_tick`/`_minimap_walk` patterns.

### 2026-06-07 — minimap-walk throttling + removed pitch control (`controller.py`)

User feedback: minimap clicking was "spam clicking" — `bring_entity_on_screen`
re-issued a minimap click every tick the target stayed off-screen, even mid-walk.
**False start:** a *blocking* `wait_ticks`/`wait_for` settle-wait livelocked the
engine — `process_tick()` runs `game.update()` then `routine.tick()`
synchronously on one thread, so blocking inside `tick()` starves `GameState` of
new ticks and the bot re-clicks the same dead minimap spot forever ("Routine
cleared — engine is idle" / repeated `wait_for timed out`).
**Real fix:** non-blocking, tick-tracked `_minimap_walk` state machine
(`registration → walking → settling → safety cap`, driven off the
already-updated `game_state` handed to `tick()` each call — never a sleep).
**General rule learned the hard way (documented in CLAUDE.md's methodology
section now):** never block (`time.sleep`/`wait`/`wait_for`/`wait_ticks`)
inside `routine.tick()` or anything it calls — always non-blocking, tick-tracked
instance state (`_idle_since_tick`, `_last_entity_click`, `_minimap_walk`, …).
Also **deleted pitch (UP/DOWN) camera control** (`adjust_camera_pitch_for`,
`_ideal_pitch`, `_PITCH_*`/`CAMERA_PITCH_SPEED`) per user feedback — minimap
walking + yaw rotation alone gets the player close enough; zoom via scroll
wheel is the planned replacement for "seeing further" (TODO.md).

### 2026-06-07 — `is_occluded` false-positive fixes → whitelist registry (`state/interfaces.py`)

Two-part fix to `GameState.is_occluded`:
1. It scanned the *entire* `interfaces` list including the always-loaded
   toplevel viewport container (groupId 161), so every on-screen entity was
   reported occluded. Introduced `state/interfaces.py` — a curated
   `INTERFACES: Dict[groupId, InterfaceInfo(name, occludes)]` registry plus
   `occludes()`/`is_interface_open()`/etc. helpers, seeded with viewport
   containers (161/548/164/165, `occludes=False`) and real panels (12 bank,
   149 inventory, 387 equipment, 162 chatbox, 160 orbs, 6 silver_crafting).
2. Even after that, always-on chrome groups never added to `INTERFACES`
   (orbs, xp counters, minimap decorations, …) still false-positived because
   `occludes()` defaulted **unknown groups to `True`** ("better safe than
   sorry"). **Flipped the registry to a whitelist**: unknown groups now default
   to **non-occluding**; only explicitly-registered `occludes=True` panels
   block clicks. Trade-off: long-tail chrome no longer false-positives, at the
   cost of a (self-correcting, rare) false-negative if a *new* real panel
   appears before being registered.

### 2026-06-07 — Minimap/interface wiring (closed out TODO "Minimap and interface detection")

Wired the interface/minimap infrastructure into the routines:
1. **Occlusion guards** — `find_ore`/`walk_to_bank`/`deposit` in
   `iron_mining.py` now call `game.is_occluded(...)` before clicking and
   re-invoke `bring_entity_on_screen` when hidden.
2. **Minimap walking fallback** — `bring_entity_on_screen` now inspects
   `decide_camera_action`'s verdict directly: `"walk"` → `click_minimap_entity`
   first, falling back to rotation only if the entity has no minimap coords.
3. **Interface group IDs** derived statically from `InterfaceID.java`: minimap
   161 (`MINIMAP` childId 30), inventory 149, orbs 160 — *not yet confirmed
   live* (the active toplevel variant depends on resize mode; `is_occluded`
   doesn't care since it scans the whole list, but targeting the minimap
   specifically would need live confirmation via the dashboard's Interfaces tab).
4. Practical occlusion test (rock partially behind the minimap) — **still
   needs a live playtest**, not exercisable from this environment.
5. Added a **Testing tab** to the dashboard (`_make_testing_tab`,
   `_TEST_ACTIONS` list of `(label, handler)` pairs — easy to extend).

### 2026-06-04 — Camera/FOV audit

Confirmed via code audit: OSRS yaw is **counter-clockwise** (0=N, 512=W,
1024=S, 1536=E — not the CW convention `camera_yaw_to` originally used).
Fixed `camera_yaw_to` (`atan2(dx,dy)` → `atan2(-dx,dy)`), the minimap direction
tick (needed the same negation), and recalibrated `CAMERA_YAW_SPEED` (measured
~3.66s per full rotation ⇒ ~0.56 units/ms, roughly 2× the original constant).
Confirmed correct and **do not change**: `rotate_camera_to`'s LEFT/RIGHT
mapping, the `_yaw_dir` compass table. This audit is what the calibrated FOV
trapezoid model in `fov.py` (anchors: pitch 229 → 3 back/6 front/4-6 half-width;
pitch 320 → 3 back/3 front/5-7 half-width) is built on — see that module's
docstring for the full calibration numbers (previously duplicated in the
now-removed `CAMERA_FOV.md`).

### 2026-06-04 — Camera Movement (rotate camera to bring off-screen entities into view)

Implemented the first camera-control layer: `GameController.hold_key`,
`HumanEmulator.plan_key_hold` → `KeyHoldIntent` (hold duration + human jitter,
mirrors `plan_click`/`plan_typing`), and `GameController.rotate_camera_to`
(computes the shorter rotation arc via `camera_yaw_to`, holds the arrow key for
a duration derived from `CAMERA_YAW_SPEED`, blocking — acceptable since holds
are short, < 2s). This was the seed that the 2026-06-04 audit above and the FOV
trapezoid model (`fov.py`, `decide_camera_action`) were later built on top of.

### 2026-06-28 — Region-based pathing (RodFishingRoutine)

Replaced RodFishingRoutine's hand-coded Fern/Tree waypoint walking
(`walk_to_fern`/`walk_to_tree`/`walk_to_bank_tree`/`walk_to_bank_fern` +
`_resume_toward_bank`/`_resume_toward_spot`, each with its own
Manhattan-distance threshold) with generic region-chain travel:

1. **`scripts/gamebridge/regions.py`** (new) — `Region` (named polygon,
   `contains()` via ray-casting `point_in_polygon`, `centroid`, `bounds`,
   and `sample_point()` which rejection-samples points inside the polygon
   and picks a weighted-random one biased toward the centroid and,
   optionally, toward a `direction` vector) and `RegionRoute` (an ordered
   tuple of regions a routine commutes back and forth along — `locate()`,
   `next_region(current, toward_end)`).
2. **`InteractionRoutine.travel_route(game, ctrl, route, destination)`**
   (interaction.py) — generic "step one tick closer to `destination` along
   `route`" helper. Locates the player's current region, finds the adjacent
   region one step closer, and clicks a `Region.sample_point()` waypoint
   inside it (biased toward the region *beyond* that one, so a transit
   heads for the far side of a region rather than stalling at the first
   tile across its border). The sampled point is cached
   (`_travel_step_name`/`_travel_target_point`) until the player actually
   crosses into that next region, so one leg clicks one consistent
   waypoint instead of a new random tile every tick.
3. **`InteractionRoutine.synthetic_minimap_entity`** — the old
   `RodFishingRoutine._synthetic_minimap_entity` geometry (camera
   yawTarget/minimapZoom → minimap pixel offset, clamped to 90% of the
   minimap radius), generalised and moved here so `travel_route` can build
   a minimap click target for an arbitrary sampled world tile rather than
   only a named landmark. `widget_ids.Minimap.GROUP = 160` added alongside
   it. `RodFishingRoutine`'s old `_real_minimap_entity`/landmark-lookup path
   was dropped — region waypoints are arbitrary sampled tiles, not named
   entities, so there's no "real entity at this exact tile" case to prefer.
4. **`InteractionRoutine.outside_container(game, container)`** — safety-exit
   check (False before login, i.e. while `game.player` is still empty, so
   the (0,0) default position can't trip it).
5. **RodFishingRoutine** now defines `BANK_REGION`, `LOWER_EDGEVILLE` (Fern),
   `UPPER_BARBARIAN_VILLAGE` (Tree), `FISHING_REGION`, and `CONTAINER_REGION`
   as module-level `Region` polygons (coordinates supplied by the user) and
   `ROUTE = RegionRoute((BANK_REGION, LOWER_EDGEVILLE,
   UPPER_BARBARIAN_VILLAGE, FISHING_REGION))`. `resume`/`banking`/
   `drop_and_return` now call a `_travel_to(destination, arrival_state)`
   helper that sets `self._destination`/`self._arrival_state` and returns
   `"travelling"`; the single `travelling` state calls `travel_route` and
   transitions to the stored arrival state once arrived. `tick()` is
   overridden to check `outside_container(game, CONTAINER_REGION)` before
   each dispatch and jump to a terminal `stopped` state (releases held
   keys, logs CRITICAL once) if the player is ever found outside it — a
   Routine state method has no handle back to `DecisionEngine.set_routine`,
   so this terminal-state idiom is the only way a routine can stop itself
   from the inside; it does not unset itself as the engine's active
   routine.

Open: the region polygons are specific to this one bank↔fishing-spot
commute. If another routine wants the same region-chain approach, the
generic pieces (`regions.py`, `synthetic_minimap_entity`,
`outside_container`) are already reusable — only the route-specific
`Region`/`RegionRoute` instances would need defining per routine.
(Superseded for RodFishingRoutine's own travel by the 2026-06-28 (2)
session below — `travel_route` itself was removed since nothing else
ever called it.)

### 2026-06-28 (2) — Recorded-path travel (`Path`/`travel_path`), replacing `travel_route`'s random in-polygon sampling

#### Goal

`travel_route` (above) clicked a random, centre-biased point inside
whichever hand-drawn `Region` polygon was next along the chain. That's
fine for a region that's mostly open ground, but a polygon's straight-line
interior doesn't know about fences/buildings/water — nothing stops it from
sampling a point the player can't actually walk straight to. Replace the
click-target logic with a recorded, walkable `Path` (an actual manual walk
from bank to fishing spot, captured as world-tile coordinates), while
keeping `Region`/`RegionRoute`/`CONTAINER_REGION` for what they're already
good at — coarse landmarks and the safety exit.

#### Findings / Decisions

- **`scripts/gamebridge/regions.py`** — new `Path` dataclass (frozen, same
  style as `Region`/`RegionRoute`): `name: str`, `points: Tuple[Point, ...]`.
  - `Path.from_recording(name, raw_points, stride=1)` — classmethod that
    takes raw `(x, y, ...)` tuples (extra columns like `plane` are ignored),
    collapses consecutive-duplicate points (player stood still), then keeps
    every `stride`-th point — always force-keeping the final point even if
    it doesn't land on the stride, so the recorded endpoint is never lost.
  - `Path.nearest_index(x, y)` — index of the closest waypoint by Euclidean
    distance; always resolves to *some* index, unlike
    `RegionRoute.locate()` which can return `None` for "not on the route".
  - `Path.click_target(current_pos, rng, lookahead_range=(8,15),
    lateral_jitter=1.0, reverse=False)` — locate the nearest waypoint, step
    a randomised number of waypoints further along (forward by default,
    backward if `reverse`), clamping at whichever end is reached, then add
    a small jitter perpendicular to the local path direction (computed from
    the points either side of the target index) so it doesn't click the
    exact same tile every lap.
  - `Path.is_at_end(x, y, reverse=False, tolerance_tiles=3.0)` — arrival
    check against whichever end is the destination (the start if
    `reverse`, else the end).
- **`InteractionRoutine.travel_path(game, ctrl, path, reverse=False,
  arrival_tolerance=3)`** (`routines/interaction.py`) replaces
  `travel_route` — same `True`-on-arrival / `False`-while-travelling
  contract. Caches the clicked target keyed off `nearest_index`, only
  re-picking once the index has moved `PATH_RESAMPLE_WAYPOINTS` (3)
  waypoints — same anti-jitter pattern `travel_route` used (cache until the
  player crosses into the next region), just keyed off a waypoint index
  instead of a region name. Builds the click via the existing
  `synthetic_minimap_entity` (unchanged, still reused as-is).
- **Removed `travel_route` entirely** rather than keeping it as a generic
  fallback — grepped `routines/examples/` first and confirmed no routine
  other than `RodFishingRoutine` (the one being migrated) ever called it,
  so there was no actual fallback use case to preserve. `RegionRoute` the
  *class* stays in `regions.py` (still backs `ROUTE`/`CONTAINER_REGION`
  patterns generically), only the `travel_route` method and its
  `_travel_step_name`/`_travel_target_point` cache fields were dropped from
  `InteractionRoutine` (replaced by `_path_cached_index`/
  `_path_cached_target`).
- **`RodFishingRoutine`** (`routines/examples/rod_fishing.py`):
  - `BANK_FISHING_PATH = Path.from_recording("BANK_FISHING_PATH",
    _BANK_FISHING_RAW_POINTS)` — built from a real ~78-point manual walk
    (bank booth → fishing spot, plane 0 throughout, supplied by the user),
    deduped but not decimated (`stride=1`, the default) since 78 points is
    already a reasonable density.
  - `BANK_REGION`/`LOWER_EDGEVILLE`/`UPPER_BARBARIAN_VILLAGE`/
    `FISHING_REGION`/`ROUTE` are **kept but no longer drive travel** — they
    now exist only as coarse landmarks for `TestRegionDefinitions`'s sanity
    checks (e.g. "is BANK_POS inside BANK_REGION"). `CONTAINER_REGION` and
    the `tick()` safety-exit override are unchanged.
  - `_travel_to(reverse: bool, arrival_state: str)` replaces the old
    `_travel_to(destination: Region, arrival_state: str)` — `self
    ._destination: Optional[Region]` became `self._travel_reverse: bool`.
    `resume()`/`banking()`/`drop_and_return()` now pass `reverse=True` when
    heading back to the bank (the *start* of the recorded path) and
    `reverse=False` when heading out to the fishing spot (the *end*).
  - `travelling()` now calls `self.travel_path(game, ctrl,
    self.BANK_FISHING_PATH, reverse=self._travel_reverse)`.

#### Tests

- `test_regions.py`: new `TestPathFromRecording` (dedup, stride decimation,
  force-keeping the final point off-stride, extra-column tolerance, empty
  input), `TestPathNearestIndex` (exact match, off-path nearest, clamping
  beyond either end), `TestPathClickTarget` (lookahead respected
  forward/reverse, jitter bounded and perpendicular-only, clamping at both
  ends, integer return type), `TestPathIsAtEnd` (both ends, in/out of
  tolerance).
- `test_interaction.py`: `TestTravelRoute` removed (along with its
  `RA`/`RB`/`RC`/`TRAVEL_ROUTE` fixtures); new `TestTravelPath` mirrors its
  shape — arrival short-circuit (both directions), click-while-travelling,
  waypoint-index caching across calls, resampling once the index moves far
  enough, cache reset on arrival, reverse direction, custom
  `arrival_tolerance`, a player far off the path still gets a normal click
  (no "not on route" special case — this is the behavioural difference
  from `travel_route` that motivated keeping a dedicated test for it), and
  a no-minimap-widget tick skips the click without raising.
- `test_rod_fishing.py`: `TestResume`/`TestBanking`/`TestDropAndReturn`
  updated to assert `r._travel_reverse` instead of `r._destination is
  <Region>`; `TestTravelling` updated to drive `travel_path` against
  `BANK_FISHING_PATH`'s actual start/end points, plus a new
  reverse-arrival case. `TestRegionDefinitions` (polygon sanity) and
  `TestSafetyExit` (`CONTAINER_REGION`/`tick()` override) are untouched.
- Full suite: `python -m pytest scripts/gamebridge/tests/ -v` → **1335
  passed, 10 skipped** (up from the prior session's 1312 passed).

#### Open / next steps

- The lookahead range (8–15 waypoints) and lateral jitter (±1 tile) are
  starting guesses, not yet tuned against a live run — watch in-game
  whether the clicks look natural or overshoot/undershoot corners on the
  recorded path, and adjust `Path.click_target`'s defaults (or pass
  explicit `lookahead_range`/`lateral_jitter` from `travel_path` if a
  per-routine override turns out to be needed).
- `BANK_FISHING_PATH` was built with the default `stride=1` (no
  decimation) since the recording was already only ~78 points: if a future
  recording is much denser (e.g. captured at full tick rate over a long
  walk), `from_recording`'s `stride` param is there to thin it out.
- If another routine wants this same recorded-path approach, `Path`/
  `travel_path` are already generic — only a routine-specific
  `Path.from_recording(...)` call (and a manually recorded walk) would be
  needed, no further `interaction.py` changes.

### 2026-06-28 (3) — Click as far as the minimap allows, with a game-view click for short hops

#### Goal

Feedback on the recorded-path travel above: it barely moved before
re-clicking (the old fixed 8–15 *waypoint* lookahead, not a tile distance,
under-shot badly on a dense recording) and always clicked the minimap even
for a couple of tiles, which looks robotic. Wanted: click as far along the
path as the minimap's current zoom actually allows (with randomness so it's
not always the literal max), and for moves under ~10 tiles, click directly
in the game viewport instead of opening the minimap.

#### Findings

- The minimap can be projected exactly from a world-tile delta
  (`world_delta_to_minimap_offset`) because it's an **orthographic** top-down
  view — a fixed pixels-per-tile scale (`camera.minimapZoom`) regardless of
  pitch/distance. The 3D game viewport is a true **perspective** projection;
  the GameBridge Java plugin only computes canvas/hull coordinates for
  actual entities/objects (`Perspective.localToCanvas`/`getCanvasTilePoly`
  on a real `LocalPoint`), never for an arbitrary empty tile. There is no
  bridge capability to ask "what canvas pixel is world tile (x, y) at"
  directly.
- Asked the user how to handle this (Java-side tile-projection endpoint vs.
  a Python-only approximation vs. skipping the game-view click). They
  preferred reusing what's already there rather than touching the Java
  plugin.
- `fov.py` already has exactly the calibration needed for a Python-only
  approximation: `_fov_params(pitch)` gives the camera's near/far forward
  extents and half-widths (a trapezoid in camera-relative tile space),
  already used by `entity_in_fov`/`decide_camera_action` to decide
  rotate-vs-walk. That trapezoid *is* a perspective-foreshortening
  calibration — inverting it (world point → normalized position within the
  trapezoid → pixel position within the viewport's rectangle) gives an
  approximate canvas projection without any new Java code. Good enough for
  this use case: clicking a few pixels off on open ground still issues a
  "Walk here" toward roughly the right tile.

#### Decisions / changes

- `regions.py`: `Path.click_target` reworked from a fixed waypoint-count
  `lookahead_range` to a tile-distance-based `max_distance` — it walks
  forward/backward accumulating real tile distance from the nearest
  waypoint until `max_distance` is reached (or the path end is hit), then
  picks a *randomised fraction* (`min_fraction` to 1.0, default 0.4–1.0) of
  that reachable distance as the actual target, so it doesn't click the
  exact farthest point every single time. Always advances at least one
  waypoint even if `max_distance` doesn't reach the next one.
- `fov.py`: new `world_point_to_viewport_canvas(game, target_x, target_y,
  viewport_bounds)` — projects a world tile to an approximate viewport
  canvas pixel by inverting `_fov_params`'s trapezoid (camera-relative
  (right, forward) offset → normalized trapezoid position → pixel within
  `viewport_bounds`). Returns `None` if the target falls outside the
  calibrated trapezoid (too far/behind/to the side) — callers must fall
  back to a minimap click in that case. Explicitly documented as an
  approximation, not a true projection.
- `widget_ids.py`: new `Viewport` class (`GROUP_RESIZABLE = 161`,
  `GROUP_FIXED = 548`) — the game viewport's root container groups (see
  `state/interfaces.py`'s existing mapping), used to find the viewport's
  on-screen bounds the same way `Minimap.GROUP` is used for the minimap.
- `controller.py`: extracted `click_walk_target(canvas_x, canvas_y,
  game_state)` out of `click_minimap_entity` — the actual click + walk-settle
  tracking (`_minimap_walk`/`_minimap_walk_in_progress`) is identical
  whether the click landed on the minimap or directly in the game viewport,
  so both now share one non-blocking "don't spam-click mid-walk" tracker.
  `click_minimap_entity` is now a thin wrapper that resolves
  `minimapX`/`minimapY` and defers to `click_walk_target`.
- `interaction.py`:
  - `_largest_widget(game, group_ids)` — shared helper for "the biggest
    loaded interface widget across these group IDs", used by both the
    minimap and viewport lookups.
  - `_minimap_cap_tiles(game)` — converts the minimap's existing 90%-of-
    radius pixel cap (`synthetic_minimap_entity`) into a tile distance via
    the current `camera.minimapZoom`, used as `Path.click_target`'s
    `max_distance` so the click reaches as far as the *current* zoom level
    allows. Falls back to `PATH_DEFAULT_LOOKAHEAD_TILES = 12.0` without a
    minimap/camera yet.
  - `_viewport_click_canvas(game, target_x, target_y)` — finds the loaded
    viewport widget (`Viewport.GROUP_RESIZABLE`/`GROUP_FIXED`) and defers to
    `fov.world_point_to_viewport_canvas`; `None` without a viewport widget
    or outside the FOV.
  - `travel_path`: after resolving the cached click target, if it's closer
    than `GAME_VIEW_CLICK_MAX_TILES = 10.0` tiles, tries
    `_viewport_click_canvas` + `ctrl.click_walk_target` first; only falls
    back to the existing `synthetic_minimap_entity` + `ctrl
    .click_minimap_entity` flow if that returns `None` (no viewport widget,
    or the point is outside the calibrated FOV) or the target is farther
    than the threshold.

#### Tests

- `test_regions.py`: `TestPathClickTarget` rewritten for the
  distance-based API — reaches the full `max_distance` with
  `min_fraction=1.0` (forward/reverse), randomness sometimes picks less
  than the max, always advances at least one waypoint even when
  `max_distance` is tiny, jitter still bounded/perpendicular-only, clamping
  at both ends, integer return type.
- `test_fov.py`: new `TestWorldPointToViewportCanvas` — no camera, inside
  FOV returns a point within `viewport_bounds`, too far ahead/behind/to the
  side all return `None`, canvas x is centered for a point dead ahead and
  larger for a point to the right, farther-ahead points render higher on
  screen (smaller canvas y) than nearer ones.
- `test_interaction.py`: new `TestTravelPathGameViewClick` (game-view click
  used when close and facing the target; falls back to minimap when the
  close target is outside the FOV, when no viewport widget is loaded, and
  when the target is farther than the threshold even with a viewport
  widget present) and `TestMinimapCapTiles` (tile radius from zoom, smaller
  zoom value → larger radius, `None` without a widget/camera-zoom).
  Existing `TestTravelPath` cases needed no changes — they have no
  viewport widget in their fixtures, so `_viewport_click_canvas` always
  returns `None` there and every call falls through to the pre-existing
  minimap-click path unchanged.
- `test_controller.py`: new `TestClickWalkTarget` — clicks at given canvas
  coords and returns `True`, a second call while the walk is still settling
  doesn't re-click, and `click_minimap_entity`/`click_walk_target` share the
  same in-flight walk tracking (one doesn't double-click on top of the
  other's walk).
- Full suite: `python -m pytest scripts/gamebridge/tests/ -v` → **1356
  passed, 10 skipped** (up from this session's starting 1335 passed).

#### Open / next steps

- `world_point_to_viewport_canvas`'s trapezoid-inversion is an
  approximation, not a real perspective projection — it hasn't been
  verified against the actual client. Watch in-game whether game-view
  clicks land sensibly (especially near the FOV's edges) and reconsider a
  proper Java-side tile-projection endpoint if it's consistently
  inaccurate.
- `GAME_VIEW_CLICK_MAX_TILES` (10) and `min_fraction` (0.4) are starting
  guesses, same caveat as the lookahead/jitter constants from the previous
  session — tune after watching a live run.
- `PATH_DEFAULT_LOOKAHEAD_TILES` (12.0) only matters on the rare tick where
  no minimap widget/camera data is available yet; not expected to be hit in
  normal play.
