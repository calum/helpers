# PLAN.md — Living Research & Planning Document

Updated after each session. Add findings at the top of each section; never delete history.

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
