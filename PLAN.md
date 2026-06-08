# PLAN.md — Living Research & Planning Document

Updated after each session. Add findings at the top of each section; never delete history.

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
