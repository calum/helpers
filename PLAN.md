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

## Session: 2026-06-07 (6) — first-move "freeze then snap" caused by uncapped move_speed distance scaling

### Problem

User-reported symptom: every time a routine or debug command starts, the
*first* mouse movement is slow and wobbly, then appears to freeze in place
for several seconds ("never works"), then suddenly snaps onto the target —
after which all subsequent movements are fast and normal.

### Root cause

`HumanEmulator.plan_click()` (`scripts/gamebridge/human/emulator.py`) derives
`move_speed` directly from the raw cursor-to-target distance:

```python
base_speed = max(0.05, dist / 800.0)
move_speed = min(1.0, base_speed * (1.0 + self.fatigue * 0.3))
```

The comment above it says the divisor is "tuned so typical in-game clicks
(100–400 px) land in 0.1–0.5 range" — i.e. the formula assumes `dist` is
always an in-viewport hop. That assumption holds for every click *after* the
first, because each new `dist` is measured from the previous click's landing
spot (entities cluster within the game canvas). It does **not** hold for the
very first move of a session: `dist` there is measured from wherever the OS
cursor happens to be — typically resting over a dashboard button or terminal,
hundreds of pixels outside the game viewport (often 800–2000+ px away).

That saturates `move_speed` at `1.0`. In `wind_mouse()`
(`scripts/gamebridge/input/mouse.py`), `move_speed = 1.0` produces:
- the smallest steps (`step = max_step * max(0.4, 1 - move_speed*0.6)` → `3.6px`)
- the longest per-step waits (`wait *= 1 + move_speed * 1.5` → up to `2.5×`)

So the very first move crawls the *entire* long distance in tiny, slow,
wind-perturbed steps (the "wobble"), and the algorithm's "fine approach"
phase (`dist < target_area`, steps shrinking by `/sqrt5` each iteration) makes
the final ~12 px take many more tiny, slow steps still — perceived as a
"freeze" right before the destination. The loop then exits and
`move_to(dest_x, dest_y)` jumps the cursor exactly onto the target — the
"snap". Every later click starts close to the previous landing spot, so
`dist` is back in the tuned 100–400 px range, `move_speed` is small, and
movement looks fast and normal — matching "every time… first move… then fine".

### Fix

Cap the distance fed into the `move_speed` formula at 400 px (the upper end
of the documented "typical in-game click" range) before dividing:

```python
capped_dist = min(dist, 400.0)
base_speed = max(0.05, capped_dist / 800.0)
```

Rationale: a human's deliberateness when clicking reflects how precisely they
need to land on the target, not how far the cursor physically had to travel
to arrive there — so a long "homing" hop shouldn't be paced more cautiously
than any normal in-game click. `move_speed` is now bounded the same way for
both 400 px and 2000 px starting distances.

### Tests

Added `TestPlanClickMoveSpeed` in `scripts/gamebridge/tests/test_emulator.py`:
- typical 100/400 px clicks still land in the documented 0.1–0.5 range,
- a 1500 px "homing" move is paced identically to a 400 px move (not maxed),
- distances beyond the 400 px cap all collapse to the same `move_speed`.

### Open questions / follow-ups

- Could also "warm up" the cursor near the game window on controller init so
  the very first real move is always a normal in-viewport hop — not done here
  since capping the pacing formula is the smaller, more general fix (it also
  protects against any other long-distance outlier, e.g. after a missed click
  lands the cursor somewhere unusual).

---

## Session: 2026-06-07 (5) — bring_entity_on_screen one-tick on-screen settle buffer

### Problem

Logs showed routines (e.g. `find_ore`/`walk_to_bank` in `iron_mining.py`,
reused by `GoldMiningRoutine`) clicking an entity immediately on the tick
`bring_entity_on_screen` first reported it `on_screen` after a camera
rotation or minimap walk, then missing:

```
15:10:52 Clicked Gold rocks at screen (410, 277)
15:10:52 [GoldMiningRoutine] find_ore → mining  (tick 6204)
15:10:54 Mining ended after 3.0s (xp=False, timeout=True)   ← no XP — the click missed
```

Root cause: the tick `decide_camera_action` first returns `"on_screen"`
right after a rotation/walk completes, the polled `canvasX`/`canvasY` can
still reflect a transient mid-adjustment frame — the projection hasn't
settled to its final resting position yet. Clicking on that stale
coordinate misses the entity.

### Fix

`GameController.bring_entity_on_screen` (`controller.py`) now tracks
`_on_screen_since_tick` and requires the entity to have reported
`"on_screen"` for at least `ON_SCREEN_SETTLE_TICKS` (= 1) consecutive ticks
before returning `True`. The first `"on_screen"` tick after any rotation or
minimap walk returns `False` (caller waits one more tick); tracking resets
to `None` whenever a fresh adjustment is issued, so a later rotation always
forces a re-settle. This mirrors the existing `_idle_since_tick` /
`_minimap_walk` settle-buffer patterns already used elsewhere in the
controller and routines.

This is a generic fix at the `bring_entity_on_screen` level — it benefits
every routine that calls it (`find_ore`, `walk_to_bank`, `GoldMiningRoutine`,
etc.) without each routine needing its own settle bookkeeping.

### Open question / future work

The user noted the underlying cause is partly that the Java plugin only
emits one tick snapshot per ~600 ms game tick — sending state at a finer
granularity (e.g. every half-tick) would shrink or eliminate this settle
window. Not pursued here; the 1-tick buffer is the pragmatic fix "for now,
working at this slower pace" (user's words).

### Tests

Added to `TestBringEntityOnScreen` in `test_controller.py`:
`test_on_screen_first_tick_not_yet_settled_returns_false`,
`test_on_screen_settles_after_settle_ticks_then_returns_true`,
`test_on_screen_settle_tracking_persists_across_calls`,
`test_rotation_resets_on_screen_settle_tracking`. Existing
`bring_entity_on_screen` tests updated to pass a `tick`-bearing game-state
mock (the new code reads `game_state.tick`).

---

## Session: 2026-06-07 (4) — minimap-walk throttling (non-blocking, after a livelock false-start) + removed pitch (UP/DOWN) adjustment

### User feedback acted on

1. **Minimap clicking was "spam clicking"** — `bring_entity_on_screen` called
   `click_minimap_entity` every tick the target was still off-screen, even
   while the player was already mid-walk from a previous click, queuing up
   redundant walk requests (a human never does this — they click once and
   wait for the walk to resolve). Requested behaviour: wait ~2 ticks for the
   walk to begin, then wait until the player stops animating AND stops
   moving, then wait 1 more tick for the game state to catch up, before
   allowing another click.

2. **Pitch (UP/DOWN) camera adjustment removed entirely** — minimap walking
   gets the player close enough that LEFT/RIGHT yaw rotation
   (`rotate_camera_to`) alone is sufficient; constantly nudging pitch added
   complexity without enough benefit. Deleted `adjust_camera_pitch_for`,
   `_ideal_pitch`, and the `_PITCH_*`/`CAMERA_PITCH_SPEED` constants from
   `controller.py` — `bring_entity_on_screen` now only calls `rotate_camera_to`.
   Zoom in/out via the scroll wheel is the planned future replacement for
   "see further" (see TODO.md "Camera Movement"). CAMERA_FOV.md §13 updated
   to flag this as a deliberate removal (was previously listed as "do not change").
   This part shipped clean on the first pass.

### ⚠️ False start: a *blocking* settle-wait livelocked the engine

My first implementation of (1) made `click_minimap_entity` **block**:
issue the click, then `self.wait_ticks(game_state, MINIMAP_WALK_START_TICKS)`
→ `self.wait_for(lambda: game_state.player_idle(), timeout=MINIMAP_WALK_IDLE_TIMEOUT)`
→ `self.wait_ticks(game_state, MINIMAP_WALK_SETTLE_TICKS)`, all built on
`time.sleep`-based polling (`wait`/`wait_for`/`wait_ticks`, `controller.py:496-520`).

The user tested this live and hit a severe livelock: the bot walked to the
gold rocks successfully, then **kept clicking the exact same dead minimap
spot forever**, logging `wait_for timed out after 3.0 s / 1.5 s / 60.0 s` and
"Routine cleared — engine is idle." The entity stayed reported as "not
visible" indefinitely even though the player had physically arrived.

**Root cause** — confirmed by reading `decision/engine.py` and
`main.py`/`dashboard.py`: the whole bridge is a **single-threaded,
message-driven loop**:

```python
def process_tick(self, msg: dict) -> None:
    self._game.update(msg)        # <-- only place game_state is refreshed
    ...
    self._routine.tick(self._game, self._ctrl)   # <-- runs SYNCHRONOUSLY, same thread
```

`for msg in stream(...): engine.process_tick(msg)` never advances to the next
message until `process_tick` returns. Since `routine.tick()` →
`bring_entity_on_screen()` → `click_minimap_entity()` ran on that same call
stack, blocking inside it (via `time.sleep` polling) **starves
`self._game.update(msg)` of new messages** — `game_state.tick`,
`player_idle()`, `nearest_object()` all freeze on stale data, so the bot
faithfully keeps re-clicking the last (now-invalid) `minimapX`/`minimapY` it
saw. This is the canonical "click the same dead spot forever" failure mode —
exactly what feedback (1) was trying to *prevent*, caused by the fix itself.

This mirrors a pattern already known in this codebase: `_idle_since_tick` in
`iron_mining.py` and the `_last_entity_click`/`min_click_interval` throttle in
`click_entity` both solve "wait across ticks" via **non-blocking, tick-tracked
instance state** checked once per `tick()` call — never via blocking sleeps —
specifically *because* `routine.tick()` must return promptly every message.

### Final fix: non-blocking, tick-tracked walk throttle

Replaced the blocking settle-wait with `self._minimap_walk: Optional[dict]`
(`{"clicked_tick", "idle_since_tick"}`, `None` when no walk is tracked) and a
pure, non-blocking `_minimap_walk_in_progress(game_state) -> bool` that
inspects the *already-updated* `game_state` handed in on the current tick —
the same `game_state` the engine just refreshed via `self._game.update(msg)`
moments earlier, so it's never stale:

- **registration** (ticks `clicked_tick .. clicked_tick+START_TICKS-1`):
  assume the walk is just starting, don't check idle yet, don't re-click
  (matches the user's "wait 2 ticks for the player to begin moving");
- **walking**: once registration elapses, wait for `game_state.player_idle()`
  (stopped animating AND stopped moving — `game_state.py:137-160`, no new
  plumbing needed); the idle streak resets to `None` if the player starts
  moving again (e.g. continuing along a multi-tile path);
- **settling**: once idle, require `MINIMAP_WALK_SETTLE_TICKS` consecutive
  idle ticks (the user's "wait 1 more tick for the game state to catch up")
  before clearing `_minimap_walk` and allowing a re-click;
- **safety cap**: `MINIMAP_WALK_MAX_TICKS` (~100 ticks / 60 s) abandons the
  tracked walk and allows a re-click if it never settles (e.g. blocked path)
  — replaces the old seconds-based `MINIMAP_WALK_IDLE_TIMEOUT`.

`click_minimap_entity` now checks `_minimap_walk_in_progress` first and
returns `True` (without clicking) while a walk is being tracked, or issues a
fresh click and starts tracking when it isn't. Net effect: one click per walk,
zero blocking, `game_state` keeps refreshing every message no matter how long
the walk takes.

### Files touched

- `scripts/gamebridge/controller/controller.py` — `click_minimap_entity` takes
  `game_state`, checks `_minimap_walk_in_progress` before clicking, and tracks
  `self._minimap_walk` across calls; new non-blocking `_minimap_walk_in_progress`;
  deleted the old blocking `_wait_for_minimap_walk_to_settle`;
  `MINIMAP_WALK_IDLE_TIMEOUT` (seconds) replaced by `MINIMAP_WALK_MAX_TICKS` (ticks);
  `adjust_camera_pitch_for`/`_ideal_pitch`/pitch constants deleted;
  `bring_entity_on_screen` no longer adjusts pitch
- `scripts/gamebridge/diagnostics.py` — `describe_click_minimap` takes `game`
  and forwards it; reworded the result message ("won't re-click until the walk
  settles") since the mechanism is throttling, not blocking/waiting
- `scripts/gamebridge/dashboard.py` — `_run_test_click_minimap` passes
  `self._engine.game`
- `scripts/gamebridge/tests/test_controller.py` — removed `TestAdjustCameraPitchFor`;
  replaced the blocking-oriented `TestMinimapWalkSettle` with
  `TestMinimapWalkInProgress` (a `_WalkGameState` stub drives `tick`/`player_idle`
  across calls to exercise registration → walking → settling → re-click, idle-streak
  reset, and the `MAX_TICKS` safety cap — all asserted via observable outputs:
  click counts and `_minimap_walk` contents, never internal sleep/poll mocks);
  updated `TestClickMinimapEntity`/`TestBringEntityOnScreen` for the new design
- `scripts/gamebridge/tests/test_diagnostics.py` — `TestDescribeClickMinimap`
  passes `game`
- `CAMERA_FOV.md` — §13 "What NOT to change" updated to record the pitch removal

Full suite: 470 passed.

### Next steps

- Watch live behaviour: confirm the bot now clicks the minimap once per walk
  and resumes mining/banking promptly once `_minimap_walk` clears.
- If a real walk legitimately exceeds `MINIMAP_WALK_MAX_TICKS` (~60 s, e.g. a
  very long bank route), the safety cap will issue a premature re-click —
  raise the constant rather than reintroducing any blocking wait.
- When zoom in/out is implemented (TODO.md "Camera Movement"), wire it in as
  the replacement for "seeing further" rather than reintroducing pitch control.
- **General rule for this codebase, learned the hard way**: never block
  (`time.sleep`, `wait`/`wait_for`/`wait_ticks`) inside `routine.tick()` or
  anything it calls (`controller` methods included) — `process_tick` is a
  single-threaded `game.update()` → `routine.tick()` chain, and blocking
  there starves game-state updates and livelocks the bot on stale data.
  Always use non-blocking, tick-tracked instance state instead (see
  `_idle_since_tick`, `_last_entity_click`/`min_click_interval`, `_minimap_walk`).

---

## Session: 2026-06-07 (3) — is_occluded still false-positiving on chrome; switched registry to a whitelist

### Problem confirmed (live, via dashboard debug menu)

After session (2)'s fix, the dashboard's "is occluded?" check still reported
e.g. `'Gold rocks' at canvas (387, 196) is occluded by a UI panel.` with
nothing actually on top of it. Root cause: `interfaces.occludes()` defaulted
**unknown/unregistered** group IDs to `True` ("better safe than sorry"). But
the live `interfaces` array is full of always-on chrome groups (orbs, xp
counters, minimap decorations, world-map button, etc.) that were never added
to `INTERFACES` and whose widgets visually overlap the canvas without ever
blocking a click — so any of those being present made nearby entities register
as occluded, exactly like the original group-161 bug but for a long tail of
other groups instead of just the toplevel container.

### Fix — flipped the registry from a blacklist to a whitelist

`scripts/gamebridge/state/interfaces.py::occludes()` now defaults **unknown
groups to `False`** (was `True`). `is_occluded` therefore only checks bounds
for widgets whose group is *explicitly* registered with `occludes=True` (real
panels — bank, inventory, chatbox, ...); every unregistered group (plus
explicitly-registered `occludes=False` viewport roots) is ignored outright.
This is the opposite tradeoff from before: instead of "assume unknown chrome
blocks clicks" (→ false positives for the long tail of chrome groups) we now
"assume unknown chrome doesn't block clicks" (→ would only false-negative if
some *new, real* panel appears that hasn't been registered yet — which is
self-correcting, since you'd notice the bot clicking through a panel and add
it to `INTERFACES`).

Updated the module docstring and the `occludes()`/`is_occluded` docstrings to
explain the whitelist model and when an `occludes=False` entry is still useful
(documenting a friendly `name` for `is_interface_open` on chrome you never
want to treat as blocking — it's no longer *required* for correctness since
unregistered groups are non-occluding by default).

### Files touched

- `scripts/gamebridge/state/interfaces.py` — `occludes()` default flipped
  False→only-if-registered; docstrings rewritten for the whitelist model
- `scripts/gamebridge/state/game_state.py` — `is_occluded` docstring updated
  to describe whitelist behaviour
- `scripts/gamebridge/tests/test_interfaces.py` —
  `test_unknown_group_defaults_to_occluding` →
  `test_unknown_group_defaults_to_non_occluding` (asserts `False`)

Full suite: 470 passed.

### Next steps

- Watch for false *negatives* now (entity reported clear but actually behind
  an unregistered panel) — if seen, add that group to `INTERFACES` with
  `occludes=True` per the module docstring. This is expected to be rare since
  routines mostly interact with a known, small set of panels.

---

## Session: 2026-06-07 (2) — Interface registry & is_occluded false-positive fix

### Problem confirmed

`GameState.is_occluded` was scanning the *entire* `interfaces` list — including the
toplevel viewport container (`groupId: 161`, `ToplevelOsrsStretch` — see the table in
the session above). That group's widgets are part of the always-loaded UI chrome and
get reported in the `interfaces` array right alongside real panels (bank, inventory,
chatbox, ...), so every on-screen entity was being reported as occluded regardless of
whether a panel was actually in the way. `contract.json`'s captured `interfaces` array
is a 2-entry real-world example: `{groupId: 161, bounds: (1631,767,190,261)}` (toplevel
container — must NOT occlude) and `{groupId: 160, bounds: (1754,8,146,151)}` (a real
panel — should occlude). The old `test_interface_is_occluded_with_known_widget` blindly
asserted `interfaces[0]` (the 161 entry) was occluding — i.e. the test was itself
written under the same misconception the user spotted.

### Fix — `scripts/gamebridge/state/interfaces.py`

New module: a small registry `INTERFACES: Dict[groupId, InterfaceInfo(name, occludes)]`
plus lookup helpers (`occludes`, `info_for`, `name_for`, `group_id_for`). Deliberately
*not* a port of all 27,263 `InterfaceID.java` constants (or even the ~159 names in
`interfaces.toml`) — just a curated set seeded with the toplevel/viewport containers
(161 `resizable_viewport`, 548 `fixed_viewport`, 164, 165 — registered `occludes=False`)
and panels currently in use (12 bank, 149 inventory, 387 equipment, 162 chatbox, 160
"minimap"/orbs, 6 silver_crafting). The module's docstring documents exactly how to add
more: look the group's numeric ID up in `InterfaceID.java` (auto-generated, comprehensive)
or `interfaces.toml` (friendlier names, ~159 hand-documented groups), then add an entry
with `occludes=True` for normal panels or `occludes=False` only for full-canvas
viewport/root containers.

`GameState.is_occluded` now skips any widget whose `groupId` is registered
`occludes=False`. New `GameState.is_interface_open(name)` resolves a friendly name to
its group ID via the registry and checks the live `interfaces` list — enabling routine
checks like `if game.is_interface_open("silver_crafting"): ...`.

**Caveat carried over from the session above:** the numeric groupId for "the minimap"
specifically is still not 100% pinned down — `interfaces.toml` says 160, the session-1
table above suggests 160 is actually `Orbs` and the minimap draw area is a *child* of
161 (`MINIMAP` = childId 30). The registry's `160 -> "minimap"` entry may need renaming
once confirmed live via the dashboard's Interfaces tab — it doesn't affect correctness
of `occludes()` (160 occludes either way), only the friendly name used by
`is_interface_open`.

### Files touched

- `scripts/gamebridge/state/interfaces.py` (new)
- `scripts/gamebridge/state/game_state.py` — `is_occluded` filters by `occludes()`;
  added `is_interface_open`
- `scripts/gamebridge/tests/test_interfaces.py` (new)
- `scripts/gamebridge/tests/test_game_state.py` — is_occluded fixtures moved off group
  161 onto 149 (a real registered panel); added regression tests for the toplevel
  exclusion and `is_interface_open`
- `scripts/gamebridge/tests/test_diagnostics.py`, `test_iron_mining.py` — renamed
  `MINIMAP_PANEL` (groupId 161 — wrong, that's the toplevel container) to
  `OCCLUDING_PANEL` (groupId 149)
- `scripts/gamebridge/tests/test_contract.py` — `test_interface_is_occluded_with_known_widget`
  now asserts the toplevel widget (161) is excluded AND the real panel widget (160)
  occludes, using the captured `contract.json` data directly

### Next steps

- Confirm live which numeric groupId the minimap draw area actually reports as in
  `interfaces` (per the open caveat in the session-1 table) and rename the registry
  entry if it differs from 160.
- As new routines need `is_interface_open` checks for specific panels (e.g. crafting
  interfaces), add them to `INTERFACES` in `state/interfaces.py` per its docstring.

---

## Session: 2026-06-07 — Minimap/interface wiring (TODO "Minimap and interface detection")

### Goal

Finish the 5 "What still needs to happen" items for minimap/interface detection in TODO.md.

### Done this session

1. **Occlusion guards** — `IronMiningRoutine.find_ore`, `walk_to_bank`, and `deposit` now call
   `game.is_occluded(canvasX, canvasY)` (guarded by `entity.get("onScreen")` to avoid `None`
   comparisons — `decide_camera_action` can report `"on_screen"` via the FOV trapezoid even when
   the engine's `onScreen` flag/canvas coords are still `None`) before clicking, and re-invoke
   `bring_entity_on_screen` to nudge the camera when an entity is hidden behind a panel.
   `GoldMiningRoutine` inherits this for free. See `scripts/gamebridge/routines/examples/iron_mining.py`
   and `TestOcclusionGuard` in `test_iron_mining.py`.

2. **Minimap walking fallback** — `GameController.bring_entity_on_screen` (controller.py) now
   inspects the `decide_camera_action` verdict directly: for `"walk"` (too far / too far
   off-bearing — rotation alone would never converge) it calls `click_minimap_entity(entity)`
   first, only falling back to rotate+pitch if the entity has no minimap coordinates (beyond
   the ~20-tile minimap radius, e.g. distant bank). This required updating
   `test_walk_action_calls_rotation_returns_false` → split into
   `test_walk_action_clicks_minimap_and_skips_rotation` /
   `test_walk_action_falls_back_to_rotation_without_minimap_coords` in `test_controller.py`
   (the old test asserted the pre-minimap "always rotate" behaviour, which is now superseded).

3. **Interface group IDs** — derived statically from `runelite-api/.../gameval/InterfaceID.java`
   (cross-checked against the `groupId: 161` example already in `GAMEBRIDGE.md`'s Interfaces
   section, which matches `ToplevelOsrsStretch` below). Group ID = upper 16 bits of the constant
   (`0x00xx_yyyy` → group `0x00xx`, child `0xyyyy`):

   | Panel | groupId | Notes |
   |---|---|---|
   | Minimap (clickable draw area) | **161** (`0x00a1`, class `ToplevelOsrsStretch`) | `MINIMAP` = childId **30** (`0x1e`); `MAP_MINIMAP` = childId **22** (`0x16`, the rendered map graphic — bounds may differ slightly from the clickable area); `COMPASSCLICK` = childId 31; `ORBS` = childId 33 |
   | Inventory panel root | **149** (`0x0095`, class `Inventory`) | `ITEMS` = childId **0** — matches the `groupId: 149` already hardcoded in `WIDGET_GROUPS` |
   | HP / Prayer / Run / Spec orbs | **160** (`0x00a0`, class `Orbs`) | `ORB_HEALTH` = childId 7, `ORB_PRAYER` = childId 18, `ORB_RUNENERGY` = childId 26, `ORB_SPECENERGY` = childId 34 |

   **Caveat — not yet confirmed live.** The actual `groupId` reported in the `interfaces` array
   depends on which top-level interface variant the client loads for the player's resize mode
   (`Toplevel`, `ToplevelPreEoc`, `ToplevelOsrsStretch`, `ToplevelOsrsFixed` all define their own
   `MINIMAP`/`ORBS` children at different group IDs — e.g. `0xa1`/`0xa4`/`0x224`/`0x259` were all
   seen in `InterfaceID.java`). `is_occluded()` doesn't care which one is active since it scans
   the whole `interfaces` list, but if you want to *target* the minimap specifically (e.g. to
   avoid clicking it, or to read its bounds), confirm the live `groupId` via the dashboard's
   **Interfaces** tab first — click on the minimap/orbs/inventory in-game and read off the
   `groupId`/`childId` that lights up, the same way the known `149`/`12`/`387`/`192` widget
   groups were discovered (see ARCHITECTURE.md "Known widget group IDs").

4. **Practical occlusion test** — requires a live game session standing next to a rock partially
   covered by the minimap (TODO item 4). This is manual playtesting of the actual bot against the
   live client — not something that can be exercised from this environment. **Still open** — the
   user should run `IronMiningRoutine` near such a rock and confirm the routine either rotates
   the camera clear or walks via the minimap rather than clicking through the UI chrome.

5. **Dashboard testing menu** — added a "Testing" tab to `dashboard.py` (`_make_testing_tab`)
   with a free-text entity-name input and one button per check (move into view / move towards /
   click minimap to move towards / is occluded? / is on screen? / is on minimap?), each appending
   a result line to an output log. New checks are added by appending to the `_TEST_ACTIONS` list
   of `(label, handler)` pairs — no layout changes required.

### Next steps

- Confirm the live `groupId` for the minimap/orbs/inventory panels via the new dashboard
  Interfaces tab and update the table above (and `GAMEBRIDGE.md` if any code starts depending on
  a specific group ID rather than scanning all `interfaces`).
- Run the iron-mining routine near a partially-occluded rock in-game and verify recovery
  (TODO item 4) — update this section with the observed behaviour.

---

## Session: 2026-06-04 — Camera/FOV audit (RIPER-5 RESEARCH)

### Confirmed bugs

| Bug | File | Line | Fix |
|-----|------|------|-----|
| `camera_yaw_to` uses CW convention — East/West swapped | `game_state.py` | 272 | `atan2(dx,dy)` → `atan2(-dx,dy)` |
| Test asserts East≈512 (wrong) | `test_game_state.py` | 681 | Change expected range to 1490–1580 |
| Minimap angle not negated — direction tick reversed | `dashboard.py` | 482 | Prepend `angle = -(yaw/2048)*2π` |
| `CAMERA_YAW_SPEED=0.256` likely 2× too slow | `controller.py` | 27 | Calibrate empirically (~0.55 expected) |

### Confirmed correct — do not change

- LEFT/RIGHT key assignment in `rotate_camera_to` (LEFT=CW, RIGHT=CCW) ✓
- UP/DOWN key assignment in `adjust_camera_pitch_for` ✓
- `_yaw_dir` compass table in dashboard.py ✓
- `_ideal_pitch` interpolation direction ✓

### Key findings

- OSRS yaw is CCW: 0=N, 512=W, 1024=S, 1536=E.
- Camera x/y/z (scene units) already streamed. `baseX`/`baseY` are NOT streamed but
  are available via `client.getBaseX()` / `client.getBaseY()` — needed for accurate
  FOV cone apex. See CAMERA_FOV.md §8 for the Java change required.
- `pitch_to_visibility_tiles` code is correct; the inline comment was backward.
- Full FOV implementation spec is in CAMERA_FOV.md — that file is now the single source
  of truth for all camera work.

### Next steps

Follow the ordered checklist in CAMERA_FOV.md §12 (Steps 1–10).
Steps 1–4 are pure Python, safe to do in one PR.
Step 5–6 require live game calibration.
Step 7 is a small Java change (add baseX/baseY to camera map).

---

## Session: 2026-06-04 — Camera Movement (TODO item 1)

### Goal

When a target object/NPC is off-screen (i.e. `entity["onScreen"] == False`), rotate the
camera using arrow keys until the entity becomes visible, then proceed with normal interaction.

### Findings

#### What already exists

| Component | File | Detail |
|---|---|---|
| `camera_yaw_to(entity)` | `scripts/gamebridge/state/game_state.py:267` | Returns ideal yaw (0–2047) to face entity via `atan2(dx, dy)` |
| `camera` dict | `game_state.py:65` | Updated every tick: `yaw`, `pitch`, `x`, `y`, `z` |
| `press_key(key, hold_ms=50.0)` | `scripts/gamebridge/input/keyboard.py:89` | Accepts hold duration; `Key.LEFT`/`Key.RIGHT` mapped |
| `GameController.press_key(key)` | `scripts/gamebridge/controller/controller.py:272` | Does NOT forward `hold_ms` — always taps at 50ms |
| Off-screen placeholder | `scripts/gamebridge/routines/examples/iron_mining.py:88` | Currently just `return None` (wait) |

#### What is missing

1. **`GameController.hold_key(key, hold_ms)`** — hold an arrow key for a calibrated duration with
   human randomness (±10–20% jitter). Calls `kb_input.press_key(key, hold_ms)`.

2. **`HumanEmulator.plan_key_hold(intended_hold_ms)` → `KeyHoldIntent`** (NEW):
   Following the same pattern as `plan_click` / `plan_typing`, the emulator owns all randomness.
   A new `KeyHoldIntent` dataclass carries:
   - `hold_ms` — intended duration × Gaussian jitter (σ ≈ 12%), clamped to ±30%
   - `pre_hold_pause` — reaction time before starting (log-normal, fatigue-scaled, same as clicks)
   - `post_hold_pause` — brief hesitation after release via `random_pause(0.02, 0.08)`
   The controller calls `human.plan_key_hold()` and consumes the intent — it never applies
   raw timing itself, consistent with how `click_entity` works.

3. **`GameController.rotate_camera_to(entity, game_state, timeout_s=5.0)`** — the main new method:
   - Compute `target_yaw = game.camera_yaw_to(entity)`
   - Compute `current_yaw = game.camera.get("yaw", 0)`
   - Compute `delta = (target_yaw - current_yaw + 2048) % 2048` (0–2047)
   - If `delta > 1024`, rotate LEFT (shorter arc, actual delta = 2048 − delta); else rotate RIGHT
   - Compute `intended_hold_ms = actual_delta / CAMERA_YAW_SPEED` (≈ 0.256 yaw-units/ms)
   - Call `self._human.plan_key_hold(intended_hold_ms)` to get human-randomised intent
   - Sleep `intent.pre_hold_pause`, hold the key for `intent.hold_ms`, sleep `intent.post_hold_pause`
   - Returns `True` if entity is on-screen (checked after hold), `False` on timeout

4. **Calibration constant** (`CAMERA_YAW_SPEED = 0.256`):
   - OSRS camera rotates approximately **256 yaw-units per second** per arrow key hold
   - Stored as a module-level constant so it is easy to tune empirically
   - Approximate — may need adjustment after first deployment

5. **Routine integration**: replace `return None` on off-screen with a call to
   `ctrl.rotate_camera_to(entity, game)`, then re-check `onScreen` next tick.

#### Open questions

- Does OSRS actually use 256 yaw/s for arrow key rotation? Needs empirical measurement.
  (Watch `game.camera["yaw"]` before/after a timed arrow key hold to calibrate.)
- Should `rotate_camera_to` block (synchronous hold) or schedule across ticks?
  → Blocking is simpler and the hold duration is short (< 2 seconds); prefer blocking.
- Is there a "centre on screen" definition? TODO says "close to the centre of the field of view
  within a tolerance". Suggest: `onScreen` is sufficient for now; canvas-centre check is future work.

#### Test plan (new tests required)

- `test_controller.py` — `TestRotateCameraTo`:
  - Calls `hold_key` with RIGHT when delta <= 1024
  - Calls `hold_key` with LEFT when delta > 1024
  - Returns `True` when entity becomes `onScreen` after one call
  - Returns `False` on timeout (entity never `onScreen`)
  - Hold duration is proportional to yaw delta
  - Human jitter is applied (hold_ms within ±30% of expected)
- `test_game_state.py` — `camera_yaw_to` already tested; no changes needed
- `test_iron_mining.py` — `find_ore` rotates camera when ore is off-screen

### Next steps

1. Enter PLAN mode to define the exact implementation checklist.
2. Enter EXECUTE mode after plan approval.
3. After execution, run `python -m pytest scripts/gamebridge/tests/ -v`.
