# Camera, Yaw Convention, and Field-of-View

This document is the authoritative reference for camera control in the GameBridge Python layer.
It supersedes any earlier notes and reflects findings from a thorough code audit conducted 2026-06-04.

---

## 1. OSRS Yaw Convention — confirmed counter-clockwise

OSRS yaw increases **counter-clockwise** when viewed from above (North is up).

| Direction | Yaw value |
|-----------|-----------|
| North     | 0         |
| West      | 512       |
| South     | 1024      |
| East      | 1536      |

The `_yaw_dir` function in [dashboard.py:263](scripts/gamebridge/dashboard.py#L263) already encodes this correctly.
User observation confirms it: when facing West the current minimap tick points East — a bug caused
by the formula using the wrong (CW) convention (see §3).

**The range is 0–2047.** One full counter-clockwise revolution = 2048 yaw units.

---

## 2. OSRS Pitch Convention

Pitch is measured in **JAU (Jagex Angle Units)** where 1024 JAU = one full revolution.
Higher pitch = more overhead (top-down). Lower pitch = more horizontal.

| View              | Approximate pitch |
|-------------------|-------------------|
| Straight overhead | 512               |
| Default login     | ~320–380          |
| Near horizon      | ~128–160          |
| Hard minimum      | ~128 (engine floor) |

The controller constants `_PITCH_OVERHEAD = 450` and `_PITCH_HORIZON = 200` in
[controller.py:35](scripts/gamebridge/controller/controller.py#L35) are reasonable starting values
pending empirical calibration (see §7).

**Key mapping:**
- `UP` arrow → pitch **increases** → more overhead
- `DOWN` arrow → pitch **decreases** → more horizontal (see further)

---

## 3. Bug: minimap direction tick is reversed

### Location
[dashboard.py:482](scripts/gamebridge/dashboard.py#L482)

### Current (wrong)
```python
angle = (yaw / 2048.0) * 2 * math.pi
dx = math.sin(angle) * tick
dy = -math.cos(angle) * tick
```

At yaw=512 (West): `angle = π/2 → dx = +tick` → tick points **right** (East). Wrong.

### Fix
```python
angle = -(yaw / 2048.0) * 2 * math.pi   # negate to match CCW convention
dx = math.sin(angle) * tick
dy = -math.cos(angle) * tick
```

Verification:
- yaw=0 (N): angle=0 → dx=0, dy=−tick → points **up** ✓
- yaw=512 (W): angle=−π/2 → dx=−tick, dy=0 → points **left** ✓
- yaw=1024 (S): angle=−π → dx=0, dy=+tick → points **down** ✓
- yaw=1536 (E): angle=−3π/2 → dx=+tick, dy=0 → points **right** ✓

---

## 4. Bug: `camera_yaw_to` returns the wrong convention

### Location
[game_state.py:272](scripts/gamebridge/state/game_state.py#L272)

### Current (wrong)
```python
return int(math.atan2(dx, dy) / (2 * math.pi) * 2048 + 2048) % 2048
```

`atan2(dx, dy)` computes a **clockwise** bearing from North. OSRS uses CCW.
North and South happen to be correct (symmetry); East and West are swapped by 1024 units.

| Entity direction | Returns | Should return |
|-----------------|---------|--------------|
| North           | 0       | 0   ✓        |
| East            | **512** | **1536** ✗   |
| South           | 1024    | 1024 ✓       |
| West            | **1536**| **512** ✗    |

### Fix
```python
return int(math.atan2(-dx, dy) / (2 * math.pi) * 2048 + 2048) % 2048
```

Negating `dx` converts from clockwise to counter-clockwise bearing, matching OSRS convention.

### Also fix the test

[test_game_state.py:681](scripts/gamebridge/tests/test_game_state.py#L681) currently asserts
`450 <= yaw <= 570` for an entity due East, with the comment "East is approximately yaw=512".
This comment and range are wrong. After the fix:

```python
def test_camera_yaw_to_east(self):
    g = GameState()
    g.update(_base_msg(player=_player(x=3200, y=3200)))
    yaw = g.camera_yaw_to({"worldX": 3205, "worldY": 3200})
    # East = yaw≈1536 in OSRS CCW convention (0=N, 512=W, 1024=S, 1536=E)
    assert 1490 <= yaw <= 1580

def test_camera_yaw_to_west(self):
    g = GameState()
    g.update(_base_msg(player=_player(x=3200, y=3200)))
    yaw = g.camera_yaw_to({"worldX": 3195, "worldY": 3200})
    # West = yaw≈512
    assert 450 <= yaw <= 570
```

---

## 5. Key mapping in `rotate_camera_to` — correct, do not change

[controller.py:320](scripts/gamebridge/controller/controller.py#L320):
```python
if delta > 1024:
    key = Key.LEFT    # CW (yaw decreases)
else:
    key = Key.RIGHT   # CCW (yaw increases)
```

In OSRS:
- `RIGHT` arrow → **counter-clockwise** → yaw **increases**
- `LEFT` arrow → **clockwise** → yaw **decreases**

The logic is correct: compute the CCW arc from current to target, and if the CCW arc is
longer than half a revolution (delta > 1024) take the shorter CW path instead.
**Do not swap LEFT and RIGHT.**

---

## 6. Effect of the `camera_yaw_to` bug on rotation

The two bugs (wrong `camera_yaw_to` + correct key mapping) do **not** cancel out.

**Example — entity is 10 tiles East, camera facing North (yaw=0):**

With the current buggy `camera_yaw_to`:
1. `camera_yaw_to` returns 512 (West) instead of 1536 (East)
2. `delta = (512 − 0 + 2048) % 2048 = 512`
3. delta ≤ 1024 → press `RIGHT` (CCW, yaw increases by 512)
4. Camera now faces **West** (yaw=512). Entity is East. Catastrophically wrong.

With the fixed `camera_yaw_to`:
1. Returns 1536 (East) ✓
2. `delta = (1536 − 0 + 2048) % 2048 = 1536`
3. delta > 1024 → press `LEFT` (CW), actual_delta = 512
4. Camera now faces **East** (0 − 512 mod 2048 = 1536). ✓

For North/South targets the bug accidentally produced correct results (both conventions
agree for 0 and 1024). This is why the iron mining routine worked but gold mining at a
different compass bearing failed.

---

## 7. Calibration tasks

All of these require the game to be running with the dashboard connected.

### 7a. Confirm yaw convention empirically (one-time sanity check)

Stand at a landmark facing due East (e.g. walk East until the minimap road runs left-right).
Read `camera.yaw` from the dashboard Camera card. Expected: approximately **1536**.
If you see ~512, the CCW convention is not matching reality and `_yaw_dir` also needs updating.

### 7b. Calibrate `CAMERA_YAW_SPEED`

[controller.py:27](scripts/gamebridge/controller/controller.py#L27) — current value: `0.256`

**Method:** Note `camera.yaw` at tick T. Hold `RIGHT` arrow for exactly 1000 ms (use a
stopwatch). Note `camera.yaw` at tick T+2. Compute `speed = delta_yaw / 1000`.

The current constant was based on a full circle ≈ 8 seconds.
A measured circle time of ~3.7 s implies actual speed ≈ `2048 / 3700 ≈ 0.554 units/ms`
— roughly **2× faster** than the current constant. This causes all rotations to overshoot
by approximately double. Calibrate empirically; the hold-for-1000-ms method is more reliable
than timing a full circle.

### 7c. Calibrate pitch range

Note the pitch value from the dashboard Camera card at:
- Maximum overhead (scroll wheel fully up)
- Near-horizon (scroll wheel fully down, still playable)
- Default login position

Update `_PITCH_OVERHEAD` and `_PITCH_HORIZON` in
[controller.py:35](scripts/gamebridge/controller/controller.py#L35).

### 7d. Calibrate `FOV_HALF_ANGLE_DEG`

Stand facing North (yaw≈0). Find the furthest entity to the East or West that still shows
`onScreen=True` in the Objects/NPCs tab. Compute its yaw offset using `camera_yaw_to`.
`FOV_HALF_ANGLE_DEG ≈ offset_units / 2048 * 360`.
Expected: approximately **35°** (a common reported value for OSRS at default zoom).

### 7e. Calibrate `pitch_to_visibility_tiles`

At a known pitch (read from the Camera card), find the furthest object showing `onScreen=True`
and record its tile distance. Repeat at two or three different pitches to build a calibration
table, then adjust the interpolation constants in the FOV proposal (§9).

---

## 8. Camera position data

The Java plugin already streams the camera's scene coordinates every tick:

```json
"camera": { "yaw": 512, "pitch": 380, "x": 6784, "y": 6912, "z": 400 }
```

`x`, `y`, `z` are **scene (local) coordinates** in game units where **1 tile = 128 units**.

To convert to world tile coordinates:
```
world_tile_x = baseX + camera.x / 128
world_tile_y = baseY + camera.y / 128
```

`baseX` / `baseY` (the world tile coords of the south-west corner of the loaded scene) are
**not currently sent by the plugin**. They are available via `client.getBaseX()` and
`client.getBaseY()` in the RuneLite API.

### Why this matters — the cone apex problem

The author of the original FOV proposal used `player.worldX/Y` as the apex of the viewing cone.
This is **only correct when the camera is directly overhead** (pitch≈512). At lower pitch the
camera moves away from the player (forward/backwards along the look direction), so the true
cone apex can be several tiles away from the player position.

**For a first implementation, player position as apex is an acceptable approximation** — it is
accurate enough at mid-range pitches (300–450) and the error rarely changes which action
`decide_camera_action` chooses. But for a precise minimap overlay, add `baseX`/`baseY` to the
plugin message and compute the real apex.

### Adding `baseX`/`baseY` to the plugin (small change)

In [GameBridgePlugin.java:308](runelite-client/src/main/java/net/runelite/client/plugins/gamebridge/GameBridgePlugin.java#L308), inside `buildCameraMap()`:
```java
m.put("x", client.getCameraX());
m.put("y", client.getCameraY());
m.put("z", client.getCameraZ());
m.put("baseX", client.getBaseX());   // add this
m.put("baseY", client.getBaseY());   // add this
```

Then the Python cone apex:
```python
base_x = game.camera.get("baseX", 0)
base_y = game.camera.get("baseY", 0)
apex_world_x = base_x + game.camera["x"] / 128
apex_world_y = base_y + game.camera["y"] / 128
```

Remember to update GAMEBRIDGE.md if this change is made (per the CLAUDE.md maintenance rule).

---

## 9. The field-of-view proposal

**Superseded by empirical calibration — see §9a below.**

The original cone model (fixed half-angle + depth) has been replaced by a trapezoid model
calibrated from direct in-game observations. See `scripts/gamebridge/fov.py` for the
implementation, `scripts/gamebridge/tests/test_fov.py` for tests.

### 9a. Calibrated trapezoid model

Two empirical anchor pitches (at the user's preferred zoom level, facing North):

| Pitch | Back boundary | Front boundary | Half-width back | Half-width front |
|-------|--------------|----------------|-----------------|-----------------|
| 229   | −3 tiles     | +6 tiles       | 4 tiles         | 6 tiles         |
| 320   | −3 tiles     | +3 tiles       | 5 tiles         | 7 tiles         |

Camera positions recorded alongside: pitch=229 → (5824, 5492, −1362); pitch=320 → (5815, 5634, −1937).

The FOV is a **trapezoid** in camera-relative (right, forward) tile space that widens toward
the far end. Parameters interpolate linearly between anchors; clamped outside the range.
The trapezoid rotates with yaw into world tile coordinates for containment tests.

Key insight: the back boundary (−3 tiles) is constant across pitches — it reflects the fixed
distance the camera sits behind the player in the orbital model. The front and width
vary with pitch as the camera tilts between overhead and horizontal.

See `scripts/gamebridge/fov.py` for:
- `_fov_params(pitch)` — interpolated trapezoid parameters
- `fov_polygon_world(pitch, yaw, px, py)` — 4 world-tile vertices
- `entity_in_fov(entity, game)` — point-in-trapezoid containment test
- `angular_offset(a, b)` — shortest yaw distance
- `decide_camera_action(entity, game)` — on_screen / rotate / walk decision

---

## 10. Minimap FOV cone overlay

Once §3 is fixed (minimap angle negated), the cone can be drawn in `MinimapWidget.paintEvent`
in [dashboard.py](scripts/gamebridge/dashboard.py).

```python
# After the direction-tick drawing block (around line 500):
if self._game and self._game.camera:
    cam = self._game.camera
    yaw  = cam.get("yaw", 0)
    pitch = cam.get("pitch", 300)

    bearing = -(yaw / 2048.0) * 2 * math.pi        # same negation as direction tick
    half_fov = math.radians(FOV_HALF_ANGLE_DEG)
    depth_tiles = pitch_to_visibility_tiles(pitch)
    depth_px = depth_tiles * cell

    # Two rays bounding the cone
    for side in (-1, +1):
        ray_angle = bearing + side * half_fov
        rx = math.sin(ray_angle) * depth_px
        ry = -math.cos(ray_angle) * depth_px
        p.setPen(QPen(_qc("#58a6ff40"), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(cx_p, cy_p), QPointF(cx_p + rx, cy_p + ry))

    # Arc closing the cone at the far end
    fov_rect = QRectF(
        cx_p - depth_px, cy_p - depth_px,
        depth_px * 2, depth_px * 2,
    )
    # QPainter angles are in 1/16° units, measured clockwise from 3 o'clock.
    # Convert bearing + half_fov to that system.
    def _qt_angle(rad: float) -> int:
        deg = math.degrees(rad)
        # QPainter 0° = East (3 o'clock), CCW positive
        qt_deg = 90.0 - deg          # screen-space: north is up, y inverted
        return int(qt_deg * 16)

    start_qt = _qt_angle(bearing - half_fov)
    span_qt  = int(math.degrees(2 * half_fov) * 16)
    p.setPen(QPen(_qc("#58a6ff80"), 1))
    p.drawArc(fov_rect, start_qt, span_qt)
```

Import `FOV_HALF_ANGLE_DEG` and `pitch_to_visibility_tiles` from wherever you place §9.

---

## 11. Routine state machine — integrating FOV decisions

Current pattern in [iron_mining.py:88](scripts/gamebridge/routines/examples/iron_mining.py#L88):
```python
if not ore.get("onScreen"):
    ctrl.rotate_camera_to(ore, game)
    ctrl.adjust_camera_pitch_for(ore, game)
    return None
```

Improved pattern using `decide_camera_action`:
```python
if not ore.get("onScreen"):
    action = decide_camera_action(ore, game)
    if action == "rotate":
        ctrl.rotate_camera_to(ore, game)
        ctrl.adjust_camera_pitch_for(ore, game)
    elif action == "walk":
        # Walk toward the ore — camera follows the player automatically.
        # On the next few ticks the ore will enter the FOV cone.
        _walk_toward(ore, game, ctrl)
    return None
```

### The `walk_toward` problem

`walk_toward` needs to click a ground tile 4–6 tiles ahead in the entity's direction.
The current plugin only exposes canvas coordinates for **entities with convex hulls** — it
does not project arbitrary world tile positions to canvas. Two options:

**Option A — Add a `localPoint` endpoint to the plugin (preferred)**

The RuneLite API has `Perspective.localToCanvas(client, LocalPoint, int)`.
Add a new JSON endpoint that accepts a world tile coordinate and returns its canvas x/y, or
expose the scene base coords and let Python do the projection (harder without the full
projection matrix).

**Option B — Walk using the compass only (interim)**

If the ore is due East and the camera is already facing East (after rotation), clicking
the screen centre-bottom area walks roughly forward. This is fragile and not recommended
for production.

For now, the safe fallback is to keep `rotate_camera_to` as the only off-screen handler and
accept that very far or very off-bearing entities will require multiple rotation attempts
(each tick converges closer). Once `camera_yaw_to` is fixed, convergence will be reliable
for all directions.

---

## 12. Ordered implementation checklist

Do these in order — each step unblocks the next.

- [x] **Step 1** — Fix `camera_yaw_to` in [game_state.py:272](scripts/gamebridge/state/game_state.py#L272):
  change `atan2(dx, dy)` → `atan2(-dx, dy)`

- [x] **Step 2** — Update `test_camera_yaw_to_east` in [test_game_state.py:681](scripts/gamebridge/tests/test_game_state.py#L681):
  change expected range from `450–570` to `1490–1580` and fix the comment.
  Add a matching `test_camera_yaw_to_west` asserting `450–570`.

- [x] **Step 3** — Fix minimap angle in [dashboard.py:482](scripts/gamebridge/dashboard.py#L482):
  add negation `angle = -(yaw / 2048.0) * 2 * math.pi`

- [x] **Step 4** — Run the full test suite to confirm nothing else broke:
  `python -m pytest scripts/gamebridge/tests/ -v`
  *Result: 385 passed.*

- [x] **Step 5** — Calibrate `CAMERA_YAW_SPEED` empirically (§7b) and update
  [controller.py:27](scripts/gamebridge/controller/controller.py#L27).
  *Expected new value: ~0.50–0.60 based on the ~3.7 s circle measurement.*
  I calcualted 10 full rotations to be 36.6 seconds, so 3.66 seconds per rotation.

- [x] **Step 6** — Calibrate `_PITCH_OVERHEAD`, `_PITCH_HORIZON`, and
  `CAMERA_PITCH_SPEED` empirically (§7c).

- [x] **Step 7** — Add `baseX`/`baseY` to the Java plugin camera map (§8) and update
  GAMEBRIDGE.md. This enables accurate cone apex calculations.

- [x] **Step 8** — Implement the FOV helpers from §9 in `scripts/gamebridge/fov.py`.
  Tests in `scripts/gamebridge/tests/test_fov.py`: entity inside cone → `on_screen`,
  entity outside angle but close → `rotate`, entity far away → `walk`. 385/385 pass.

- [x] **Step 9** — Add the minimap FOV trapezoid overlay to [dashboard.py](scripts/gamebridge/dashboard.py).
  Draws a dashed blue polygon using the calibrated trapezoid model, updated each tick.
  Requires visual verification against the running game.

  Observed information:
    * my personal favourite zoom and pitch leads to the camera values (when facing directly north):
        ```
        Yaw: 2045 (N)
        Pitch: 320
        Pos: (5815, 5634, -1937)
        ```
    I feel quite comfortable playing with pitch between around 260 and 500.
    As a polygon where x=0 and y=0 is my player character position the field of view cone is:
        ```
        (-5, -3)
        (+5, -3) [in game inventory can obscure some of these though]
        (-7, +3)
        (+7, +3) [in game minimap does obscure some of these tiles though]
        ```

    * the default view is
        ```
        Yaw: 0 (N)
        Pitch: 229
        Pos: (5824, 5492, -1362)
        ```
    At the default view, facing north, I would like the field of view to contain the following tiles:
        ```
        3 tiles south
        6 tiles north
        
        As a polygon where x=0 and y=0 is my player character position:
        (-4, -3)
        (+4, -3) [in game inventory can obscure some of these though]
        (+6, +6)
        (-6, +6)
        ```
    Does that help you work out how to compute the field of view cone and project it onto the minimap on the dashboard and hold it in the game state? So given a set of camera settings, can you calculate the field of view cone?

- [ ] **Step 10 (optional)** — Integrate `decide_camera_action` into the routines (§11)
  and implement `walk_toward` once the canvas-projection infrastructure is available.

---

## 13. What NOT to change

- **`rotate_camera_to` key logic** — LEFT/RIGHT assignment is correct.
- **`_yaw_dir` in dashboard.py** — the CCW label table is correct.

> **2026-06-07 update — pitch (UP/DOWN) adjustment removed.** `adjust_camera_pitch_for`
> and `_ideal_pitch` (and the `_PITCH_*`/`CAMERA_PITCH_SPEED` constants) have been
> deleted from `controller.py` per user feedback: minimap-based walking gets the
> player close enough that LEFT/RIGHT yaw rotation alone is sufficient, and
> constantly nudging pitch added complexity without enough benefit. `bring_entity_on_screen`
> now only calls `rotate_camera_to`. Zoom in/out via the scroll wheel is the planned
> replacement for "see further" (TODO.md "Camera Movement") — do not reintroduce
> UP/DOWN pitch control.
