# Game World Movement — Research & Architecture Document

**Session**: 2026-06-14 (4) — Research phase for TODO item "Game world movement"

**Status**: Research complete; architecture decision made; ready for implementation Phase 1

---

## Summary

The RuneLite automation system currently supports **single-screen navigation** (camera rotation + minimap walking to nearby entities). To unblock multi-objective routines (e.g., mining site → bank → ore processing → repeat), we need **multi-region pathfinding and waypoint following**.

### Decision

**Implement Option 1: Hardcoded Waypoint Lists** as the beginner-tier solution.

- ✅ Unblocks iron/gold mining banking immediately
- ✅ Leverages existing SessionRecorder infrastructure
- ✅ Minimal implementation (~1-2 hours per routine)
- ⏭️ Can be extended to Option 3 (Dax HTTP API) later

See [Architecture Options](#architecture-options) for why Options 2-4 were deferred.

---

## Current State

### Working Navigation Infrastructure

#### 1. Camera Movement (`GameController.rotate_camera_to`, `rotate_camera`)
- Rotates camera using arrow keys (LEFT/RIGHT)
- **Calibrated speed**: ~0.56 yaw units/ms
  - Measured from 10 full rotations in 36.6s
  - Calibration in PLAN.md (2026-06-04 session)
- **Yaw convention**: OSRS counter-clockwise (0°=N, 512°=W, 1024°=S, 1536°=E)
- Currently only rotates yaw; pitch (UP/DOWN) not yet automated
- Used by `bring_entity_on_screen()` to face off-screen targets

#### 2. Minimap Walking (`GameController.click_minimap_entity`)
- Clicks pre-computed `minimapX`/`minimapY` of target entity
- `minimapX`/`minimapY` calculated in Java plugin via `Perspective.localToMinimap()`
- **Range**: ~20 tiles from player; beyond that, returns no minimap coordinates
- **Multi-tick settlement tracking** (prevents spam-clicking):
  1. **Registration** (2 ticks): allow animation/movement to register before checking idle
  2. **Idle detection**: wait for `game_state.player_idle()` (not animating + not moving)
  3. **Settling** (1 tick): wait one more tick for polled game state to reflect final position
  4. **Safety cap** (100 ticks): ~60s timeout if walk never settles
- Returns `True` if click issued; `False` if minimap coords unavailable or walk in progress
- See [GAMEBRIDGE.md](GAMEBRIDGE.md) "Minimap clicking via interfaces" example

#### 3. Field of View (FOV) Model (`fov.py`)
- **Shape**: trapezoid in camera-relative tile space (not a circle)
- **Pitch-based interpolation** between two empirical anchors:
  - **Pitch 229** (near-horizon): 3 tiles back, 6 tiles front, half-width 4-6
  - **Pitch 320** (overhead): 3 tiles back, 3 tiles front, half-width 5-7
  - Parameters interpolate linearly; clamped outside range
- **Rotation**: trapezoid rotated into world tile space by camera yaw
- Used by `decide_camera_action()` to determine if entity needs rotation, walk, or is already in view

#### 4. Available Game Data (`GAMEBRIDGE` plugin)
From `GAMEBRIDGE.md`:
- **`player`**: worldX, worldY, plane, animation, HP, prayer
- **`camera`**: yaw (0-2047), pitch, local coordinates (x/y/z), world tile base (baseX/baseY)
- **`objects`/`npcs`**: per-entity onScreen flag, canvasX/canvasY, worldX/worldY, minimapX/minimapY, hull (clickable polygon)
- **`interfaces`**: all visible UI widgets with bounding boxes (bounds: x, y, width, height)
- **`menu`**: right-click context menu with option/target text and clickable entry bounds

#### 5. Entity Query Helpers (`GameState`)
```python
objects_named(name: str) -> List[dict]      # all objects matching name
nearest_object(name: str) -> Optional[dict] # nearest by Manhattan distance
player_near(entity: dict, tiles: int) -> bool
is_occluded(canvas_x, canvas_y) -> bool     # check if behind UI panel
```

### Existing Routines (Limited World Movement)

**Files**: 
- `scripts/gamebridge/routines/examples/iron_mining.py`
- `scripts/gamebridge/routines/examples/gold_mining.py`
- `scripts/gamebridge/routines/examples/fish_and_cook.py`

**Pattern** (exemplified in IronMiningRoutine):
```
find_ore:
  - nearest_object("Iron rocks")
  - if visible: click it
  - state → "mining"
  
mining:
  - wait for animation + XP drop
  - state → "find_ore" or "walk_to_bank"
  
walk_to_bank:
  - nearest_object("Mine cart")
  - if not player_near(): click it (minimap walk)
  - state → "deposit"
  
deposit:
  - click deposit box button
  - inventory_free_slots() > 0 → "find_ore"
```

**Current Limitations:**
- ❌ Hardcoded target names ("Mine cart", "Deposit box")
- ❌ No pathfinding for multi-region distances
- ❌ Assumes bank is always reachable via single minimap click
- ❌ No obstacle navigation (doors, ladders, walls)
- ❌ No plane/building support (can't enter dungeons or climb stairs)
- ❌ No quest requirement checking
- ❌ No error recovery if player gets stuck

### Recording System (Existing Asset)

**File**: `scripts/gamebridge/recording/recorder.py`

Captures manual play sessions to JSONL format:
- **Session events**: start/end timestamps, player name
- **Tick events**: raw game state (objects, inventory, XP events, etc.)
- **Click events**: canvas X/Y, player world position, animation state, resolved target

**Reusable for waypoint extraction**:
1. Manual walk from ore site to bank
2. Extract recorded player (worldX, worldY) from idle ticks
3. Decimate waypoints (e.g., every 5th tick or K-means clustering)
4. Store as routine-specific route

---

## External Resources

### Runescape-Web-Walker-Engine (Dax Walker)

**Repository**: https://github.com/itsdax/Runescape-Web-Walker-Engine  
**Language**: Java  
**Used by**: TriBot (commercial botting client)

**Pathfinding Algorithm**:
- **A*** for actual path calculation
- **Dijkstra** for region culling (performance optimization)
- **Performance**: <200ms to generate any path in OSRS world (10M+ tiles, sparse 15000×15000×4 map)

**Features**:
- ✅ Shortcut handling: skill gates (Agility), ship chartering, portals, teleports
- ✅ Obstacle navigation: doors, ladders, one-way exits (directed nodes)
- ✅ Quest/skill requirement checking
- ✅ Account for player stats (Agility level for shortcuts, etc.)
- ✅ Directed nodes (e.g., one-way entrance/exit at Draynor Manor)
- ✅ Real-time collision/reachability visualization
- ✅ Coverage: ~90% of OSRS world
  - ✅ All cities (including Zeah)
  - ✅ Wilderness
  - ✅ Most dungeons (Slayer dungeons, Stronghold of Security, etc.)
  - ✅ Underground locations (Falador Mine, Varrock Sewers, etc.)
  - ❌ Lletya
  - ❌ Some elite/rare dungeons

**Access**:
- Included in TriBot installation (`~/.tribot/install/tribot-client/lib/`)
- API keys from https://admin.dax.cloud/ (free tier available)
- HTTP API support (server-side pathfinding + JSON response)

**Documentation**:
- JavaDocs: https://itsdax.github.io/Runescape-Web-Walker-Engine/
- README examples in repository

### Explv's Map

**URL**: https://explv.github.io/  
**Backend**: Dax Web Walker pathfinding service  
**Features**:
- Interactive browser-based RuneScape map
- Real-time pathfinding visualization
- Shows collision data, walkable tiles, obstacles
- Can query routes and view them on minimap
- Useful for understanding walkability and testing paths manually

---

## Integration Gaps

### Root Cause of TODO "Game world movement" Item

1. **No Java ↔ Python bridge**
   - Dax pathfinding is Java; scripts are Python
   - Would need JNI/subprocess/HTTP API to call from Python

2. **No waypoint-following in controller**
   - GameController has `click_minimap_entity()` for single entities
   - No `follow_path(waypoint_list)` that iterates through waypoints

3. **No route storage/loading**
   - No way to persist paths between routine runs
   - Each routine would need to hardcode or discover paths at runtime

4. **Single-screen distance assumption**
   - Routines assume bank/destination visible or minimap-reachable from current location
   - No multi-region awareness or distance checking

5. **No obstacle/plane handling**
   - No detection of blocked doors, requiring keystroke to open/pass through
   - No support for ladders, stairs (plane changes)
   - No handling of buildings/instanced areas

---

## Architecture Options (Increasing Complexity)

### Option 1: Hardcoded Waypoint Lists (RECOMMENDED — BEGINNER)

**Concept**: Manually record walk from ore → bank. Extract decimated waypoints. Follow via minimap clicks.

**Implementation**:
```python
# routines/paths.py
PATHS = {
    ("iron_mining", "to_bank"): [
        (3183, 3301),   # start (ore location)
        (3165, 3320),   # intermediate waypoint
        (3155, 3345),   # end (mine cart)
    ],
    ("iron_mining", "to_ore"): [
        (3155, 3345),   # start (mine cart)
        (3165, 3320),   # intermediate
        (3183, 3301),   # end (ore)
    ],
}

# controller.py
def follow_path(self, path: List[Tuple[int, int]], game_state) -> None:
    """Click minimap to each waypoint sequentially."""
    for wx, wy in path:
        while not game_state.player_near((wx, wy), tiles=2):
            # Create temporary entity at waypoint
            entity = {"worldX": wx, "worldY": wy, "minimapX": ..., "minimapY": ...}
            self.click_minimap_entity(entity, game_state)
            yield None  # wait a tick

# iron_mining.py
def walk_to_bank(self, game, ctrl):
    if game.inventory_empty():
        return "find_ore"
    
    # Use path instead of hardcoded mine cart click
    path = PATHS.get(("iron_mining", "to_bank"))
    if path:
        ctrl.follow_path(path, game)
    else:
        # fallback to old hardcoded behavior
        ...
```

**Pros**:
- ✅ Minimal implementation (~1-2 hours per routine)
- ✅ Leverages SessionRecorder for manual recording
- ✅ No external API calls or dependencies
- ✅ Deterministic and debuggable
- ✅ Can be version-controlled in git

**Cons**:
- ❌ Must manually record paths for each location pair
- ❌ Paths not adaptive (if tree falls or NPC blocks route, won't reroute)
- ❌ No shortcut/obstacle handling
- ❌ Limited to recorded locations

**Effort**: ~1-2 hours per routine to record + integrate

**Coverage**: Works for A→B linear routes; no branching or conditionals

**Next step** (if needed): Option 3 (Dax HTTP API) for dynamic pathfinding

---

### Option 2: Recorded Click Playback (BEGINNER+)

**Concept**: Replay click positions from recorded session.

Similar to Option 1, but instead of waypoints, store exact (canvasX, canvasY) clicks from recording.

**Pros**:
- ✅ Reproduces exact manual behavior
- ✅ Includes right-click menus, door openings, etc.
- ✅ More reliable for complex sequences

**Cons**:
- ❌ Fragile to screen resize or UI layout changes
- ❌ No adaptation to game state changes
- ❌ More complex than waypoints

**Effort**: ~2-3 hours per routine

**Verdict**: Deferred — unnecessary complexity over Option 1 for current needs.

---

### Option 3: HTTP API to Dax Pathfinding (INTERMEDIATE)

**Concept**: Query Dax API from Python to get dynamic paths. Cache locally.

**Implementation sketch**:
```python
import requests

# routines/paths.py
class DaxPathfinder:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cache = {}  # (src, dst, plane) -> path
    
    def get_path(self, src_x: int, src_y: int, dst_x: int, dst_y: int, plane: int = 0):
        key = (src_x, src_y, dst_x, dst_y, plane)
        if key in self.cache:
            return self.cache[key]
        
        # Query Dax API
        response = requests.post(
            "https://api.dax.cloud/pathfind",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"start": [src_x, src_y, plane], "end": [dst_x, dst_y, plane]}
        )
        path = response.json()["path"]
        self.cache[key] = path
        return path

# controller.py
def follow_dynamic_path(self, src, dst, game_state, ctrl):
    """Query Dax for path, then follow waypoints."""
    path = pathfinder.get_path(src[0], src[1], dst[0], dst[1], game_state.player["plane"])
    self.follow_path(path, game_state)
```

**Pros**:
- ✅ Dynamic pathfinding (doesn't require pre-recording)
- ✅ Handles obstacles and shortcuts automatically
- ✅ Covers ~90% of OSRS world
- ✅ Quest/skill requirement checking
- ✅ <200ms per path query

**Cons**:
- ❌ Requires API key (free tier has rate limits)
- ❌ External dependency (if API down, routines fail)
- ❌ Network latency (even <200ms adds to routine time)
- ❌ Cache invalidation if game world changes (rare)
- ❌ More complex error handling

**Effort**: ~4-6 hours (HTTP client, caching, error handling, testing)

**Verdict**: Defer until Option 1 proves insufficient. Better decision point: measure how often routines need to pathfind.

---

### Option 4: Embedded Pathfinding Engine (ADVANCED)

**Concept**: Port or reimplement A*/Dijkstra in Python or call Java subprocess.

**Approach A** (Python reimplement):
- Implement A* + Dijkstra from scratch in Python
- Build walkability map from game state (objects, collision data)
- Generate paths on-the-fly with no external API

**Approach B** (Java subprocess):
- Compile Dax as standalone JAR
- Call via subprocess, IPC, or JNDI

**Pros**:
- ✅ No external API or rate limits
- ✅ Offline / can work without connectivity
- ✅ Full control over algorithm

**Cons**:
- ❌ 2+ weeks effort for A* implementation + testing
- ❌ Collision data not currently exposed by plugin
- ❌ Would need to reverse-engineer walkability from observations
- ❌ Maintenance burden

**Verdict**: Defer indefinitely unless Option 3 proves infeasible.

---

## Recommended Implementation Path

### Phase 1: Route Infrastructure (1-2 hours)

1. **Create `routines/paths.py`**:
   ```python
   """Predefined routes for routines. Format: (routine_name, dest) -> [(worldX, worldY), ...]"""
   PATHS = {
       ("iron_mining", "to_bank"): [...],
       ("iron_mining", "to_ore"): [...],
       ("gold_mining", "to_bank"): [...],  # same as iron
       ("gold_mining", "to_ore"): [...],   # same as iron
   }
   ```

2. **Add `follow_path()` to `GameController`**:
   - Iterate waypoints
   - Create temporary entity for each waypoint
   - Call `click_minimap_entity()` until `player_near()`
   - Handle settlement tracking

3. **Modify `IronMiningRoutine.walk_to_bank()`**:
   - Replace hardcoded mine cart click with `follow_path(PATHS[...])`
   - Fallback to old behavior if path not found

4. **Test manually**:
   - Start iron mining
   - Verify walks to bank and back via path

### Phase 2: Path Recording & Documentation (1 hour)

1. **Manually record first path**:
   - In-game: stand at ore location
   - Dashboard: start recording
   - Manually walk to bank
   - Dashboard: stop recording
   - Extract player (worldX, worldY) from JSONL at idle ticks
   - Decimate to ~5-10 waypoints

2. **Populate `PATHS` dict** with recorded data

3. **Document recording workflow** in comments or wiki

### Phase 3: Expansion (1 hour each)

1. **Gold mining**: use same paths as iron (same locations)
2. **Other routines**: record their specific paths
3. **Consider Option 3 integration**: stub API calls for future use

### Phase 4: Future (Optional — Post-MVP)

1. **Implement Option 3** if:
   - Routines need to pathfind to dynamic locations (e.g., boss spawn points)
   - Manual path recording becomes a bottleneck
   - Multi-region complex routing needed

2. **Add error recovery**:
   - Detect stuck player (no progress toward waypoint after N ticks)
   - Reroute or notify operator

3. **Support plane changes**:
   - Add plane parameter to paths
   - Handle ladder climbing, dungeon entry/exit

---

## Code Locations

| File | Purpose |
|------|---------|
| `scripts/gamebridge/controller/controller.py` | Add `follow_path()` method |
| `scripts/gamebridge/routines/paths.py` | **NEW** — route storage |
| `scripts/gamebridge/routines/examples/iron_mining.py` | Modify `walk_to_bank()` state |
| `scripts/gamebridge/routines/examples/gold_mining.py` | Modify `walk_to_bank()` state |
| `scripts/gamebridge/recording/recorder.py` | Reuse for path extraction |
| `PLAN.md` | Update with session findings (already done) |

---

## Key Learnings

### Waypoint Following Must Account for Minimap Range
- Minimap coords only available for entities within ~20 tiles
- If waypoint is >20 tiles away, must navigate in hops:
  1. Click farthest visible minimap point toward waypoint
  2. Wait for player to settle
  3. Check proximity to waypoint; if not close, repeat

### Settlement Timing is Critical
- Re-clicking minimap before previous walk settles causes queued/cancelled walks
- Currently tracked in `_minimap_walk` state with 100-tick timeout
- Must respect this in `follow_path()` — don't advance to next waypoint until settled

### Player Position Updates Lag Slightly
- Polled game state reflects position ~1 tick after movement completes
- Settlement tracking accounts for this (1 tick "settling" delay)
- Checking `player_near()` immediately after move settles may false-positive

### Recording Provides Ground Truth
- Manual walks contain all navigation knowledge (camera angles, door timings, etc.)
- Extracting waypoints loses detail but captures essence
- First recording should be done carefully / multiple times to identify best path

---

## Next Steps (If Implementing Phase 1)

1. **Estimate**: 1-2 hours per routine to implement + 30 min per routine to record paths
2. **Iron mining first**: most straightforward, clearest ore ↔ bank route
3. **Record 2-3 runs** to identify consistent path; pick best/most efficient
4. **Validate**: run automated iron mining for 30 min; verify deposits succeed
5. **Expand**: gold mining (same paths), then other activities
6. **Monitor**: track failure rates to inform if Option 3 needed

---

## References

- **PLAN.md** (Session 2026-06-14 (4)): Full research findings
- **GAMEBRIDGE.md**: Plugin data format and camera/minimap sections
- **controller.py**: GameController, minimap walking, camera rotation
- **iron_mining.py**: Example routine using walk_to_bank
- **recorder.py**: SessionRecorder for manual path extraction
- **Dax Web Walker**: https://github.com/itsdax/Runescape-Web-Walker-Engine
- **Explv's Map**: https://explv.github.io/
