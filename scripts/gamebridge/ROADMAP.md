# GameBridge Python Client — Roadmap

Status legend:  ✅ Done today  🔜 Planned  💡 Future idea

---

## Milestone 1 — Core architecture  ✅

All items below were implemented in the initial session.

| # | Feature | File(s) | Status |
|---|---------|---------|--------|
| 1.1 | TCP client — connect, stream, reconnect | `client.py` | ✅ |
| 1.2 | In-memory game state model | `state/game_state.py` | ✅ |
| 1.3 | Update state from every tick field (player, camera, npcs, objects, events) | `state/game_state.py` | ✅ |
| 1.4 | Inventory, equipment, XP, varbit, chat, interacting events | `state/game_state.py` | ✅ |
| 1.5 | Convenience queries (nearest_object, inventory_full, player_near, …) | `state/game_state.py` | ✅ |

---

## Milestone 2 — Human emulator  ✅

| # | Feature | File(s) | Status |
|---|---------|---------|--------|
| 2.1 | Reaction time model (log-normal distribution) | `human/emulator.py` | ✅ |
| 2.2 | Click precision model (Gaussian offset from target) | `human/emulator.py` | ✅ |
| 2.3 | Move-speed model (distance-proportional, fatigue-scaled) | `human/emulator.py` | ✅ |
| 2.4 | Typing speed model (WPM-based with per-key jitter) | `human/emulator.py` | ✅ |
| 2.5 | Fatigue accumulation and recovery | `human/emulator.py` | ✅ |
| 2.6 | Break scheduling model (`should_take_break`, `break_duration`) | `human/emulator.py` | ✅ |
| 2.7 | Occasional double-click model (misclick at high fatigue) | `human/emulator.py` | ✅ |
| 2.8 | Optional mouse-path waypoints (incidental UI glancing) | `human/emulator.py` | ✅ |

---

## Milestone 3 — Hardware input  ✅

| # | Feature | File(s) | Status |
|---|---------|---------|--------|
| 3.1 | WindMouse — realistic curved mouse movement | `input/mouse.py` | ✅ |
| 3.2 | Windows ctypes SendInput (absolute coords, DPI-safe) | `input/mouse.py` | ✅ |
| 3.3 | Left-click / right-click | `input/mouse.py` | ✅ |
| 3.4 | `get_position()` — read current cursor position | `input/mouse.py` | ✅ |
| 3.5 | Unicode keyboard input (SendInput KEYEVENTF_UNICODE) | `input/keyboard.py` | ✅ |
| 3.6 | Named key presses (Enter, Escape, F-keys, arrows, …) | `input/keyboard.py` | ✅ |

---

## Milestone 4 — Controller  ✅

| # | Feature | File(s) | Status |
|---|---------|---------|--------|
| 4.1 | `click_entity(entity)` — human-emulated left-click on game entity | `controller/controller.py` | ✅ |
| 4.2 | `right_click_entity(entity)` | `controller/controller.py` | ✅ |
| 4.3 | `click_at(canvas_x, canvas_y)` — click by canvas coord | `controller/controller.py` | ✅ |
| 4.4 | `type_text(text)` — human-paced typing | `controller/controller.py` | ✅ |
| 4.5 | `press_key(key)` — single named/char key | `controller/controller.py` | ✅ |
| 4.6 | `wait_for(condition, timeout)` — tick-aligned polling | `controller/controller.py` | ✅ |
| 4.7 | `wait_ticks(n)` — wait for N game ticks | `controller/controller.py` | ✅ |
| 4.8 | RuneLite window auto-detection (FindWindowW + ClientToScreen) | `controller/controller.py` | ✅ |

---

## Milestone 5 — Routine system  ✅

| # | Feature | File(s) | Status |
|---|---------|---------|--------|
| 5.1 | `Routine` base class — method-per-state machine | `routines/base.py` | ✅ |
| 5.2 | `@initial_state` decorator | `routines/base.py` | ✅ |
| 5.3 | State transition logging | `routines/base.py` | ✅ |
| 5.4 | `reset()` — return to initial state | `routines/base.py` | ✅ |
| 5.5 | `ticks_in_state()` — time-in-state guard | `routines/base.py` | ✅ |
| 5.6 | Iron Mining example routine (find → mine → bank → deposit → repeat) | `routines/examples/iron_mining.py` | ✅ |

---

## Milestone 6 — Decision engine  ✅

| # | Feature | File(s) | Status |
|---|---------|---------|--------|
| 6.1 | `DecisionEngine` — drives a Routine one tick at a time | `decision/engine.py` | ✅ |
| 6.2 | Non-blocking break scheduling (timestamp-based, doesn't block UI) | `decision/engine.py` | ✅ |
| 6.3 | `on_break` / `break_remaining` properties (for dashboard display) | `decision/engine.py` | ✅ |
| 6.4 | Hot-swap routine at any time with `set_routine()` | `decision/engine.py` | ✅ |

---

## Milestone 7 — GUI Dashboard  ✅

| # | Feature | File(s) | Status |
|---|---------|---------|--------|
| 7.1 | Qt GUI app (`GameBridgeApp`) | `dashboard.py` | ✅ |
| 7.2 | Player stats panel (name, pos, hp, prayer, animation, interacting) | `dashboard.py` | ✅ |
| 7.3 | ASCII minimap (15×15 tile grid centred on player) | `dashboard.py` | ✅ |
| 7.4 | Inventory summary panel | `dashboard.py` | ✅ |
| 7.5 | Camera panel (yaw + compass direction, pitch, position) | `dashboard.py` | ✅ |
| 7.6 | Routine control panel (dropdown, Start / Stop / Reset buttons) | `dashboard.py` | ✅ |
| 7.7 | Session timer + fatigue bar | `dashboard.py` | ✅ |
| 7.8 | Break status display | `dashboard.py` | ✅ |
| 7.9 | NPCs DataTable (sorted by distance, on-screen indicator) | `dashboard.py` | ✅ |
| 7.10 | Objects DataTable (sorted by distance) | `dashboard.py` | ✅ |
| 7.11 | Skills/XP DataTable | `dashboard.py` | ✅ |
| 7.12 | Debug log (RichLog — every tick, events highlighted) | `dashboard.py` | ✅ |
| 7.13 | Toggle debug log on/off with `d` key | `dashboard.py` | ✅ |
| 7.14 | Keyboard shortcuts: `s` start, `x` stop, `r` reset, `q` quit | `dashboard.py` | ✅ |
| 7.15 | Connection status in header subtitle | `dashboard.py` | ✅ |

---

## Milestone 8 — Build & tooling  ✅

| # | Feature | File(s) | Status |
|---|---------|---------|--------|
| 8.1 | Python 3.12 pinned in mise | `mise.toml` | ✅ |
| 8.2 | `mise run gamebridge-setup` — installs pip deps | `mise.toml` | ✅ |
| 8.3 | `mise run gamebridge` — launches dashboard | `mise.toml` | ✅ |
| 8.4 | `mise run gamebridge-watch` — headless watch mode | `mise.toml` | ✅ |

---

## Milestone 9 — Routine library  🔜

These are the next routines to write.  Each follows the same method-per-state pattern as `IronMiningRoutine`.

| # | Routine | Notes | Status |
|---|---------|-------|--------|
| 9.1 | Gold mining | Subclass of iron mining for gold rock areas | ✅ |
| 9.2 | Woodcutting (oaks/willows) | Find tree → chop → drop or bank | 🔜 |
| 9.3 | Fishing (fly-fishing, cage) | Find spot → fish → drop or bank | 🔜 |
| 9.4 | Combat (melee/ranged) | Find NPC → attack → loot → repeat | 🔜 |
| 9.5 | Smithing (anvil) | Walk to anvil → smith → repeat | 🔜 |
| 9.6 | Agility (Gnome Stronghold course) | Follow waypoints, click obstacles | 🔜 |
| 9.7 | Crafting (pottery / glass-blowing) | Use item on table, craft all | 🔜 |

---

## Milestone 10 — Controller improvements  🔜

| # | Feature | Notes | Status |
|---|---------|-------|--------|
| 10.1 | Context-menu selection | After right-click, scan the menu and click the right option by text | 🔜 |
| 10.2 | Minimap click-to-walk | Click the minimap dot for out-of-screen destinations | ✅ |
| 10.3 | Camera rotation | Turn camera by holding middle-click and dragging | ✅ |
| 10.4 | Drag and drop | For bank rearranging, spell-casting on items, etc. | 🔜 |
| 10.5 | Scroll wheel | Zoom and interface scrolling | 🔜 |

---

## Milestone 11 — Dashboard improvements  🔜

| # | Feature | Notes | Status |
|---|---------|-------|--------|
| 11.1 | Manual break scheduler in dashboard | "Take a break in X minutes" button | 🔜 |
| 11.2 | Routine history log | What state transitions happened and when | 🔜 |
| 11.3 | Inventory item name resolution | Look up item names by ID (requires item DB or wiki scrape) | 🔜 |
| 11.4 | HP / Prayer bar visualisation | `████░░` bar for HP and Prayer | 🔜 |
| 11.5 | Event feed panel | Chat, XP drops, interacting changes in a live feed | 🔜 |
| 11.6 | On-screen entity overlay | Draw bounding boxes over NPCs/objects (requires transparent window) | 💡 |
| 11.7 | Multiple routine tabs | Queue and switch between routines | 💡 |

---

## Milestone 12 — Human emulator improvements  🔜

| # | Feature | Notes | Status |
|---|---------|-------|--------|
| 12.1 | Session behaviour profile (e.g. "casual player", "grinder") | Presets for reaction time, break frequency, click accuracy | 🔜 |
| 12.2 | Time-of-day awareness | Slower in the morning, faster in the afternoon | 💡 |
| 12.3 | Random afk micro-pauses | 0.5–3 s random idle moments between actions | 🔜 |
| 12.4 | Mouse drift while reading chat | Cursor moves slightly during long wait periods | 💡 |

---

## Milestone 13 — State model improvements  🔜

| # | Feature | Notes | Status |
|---|---------|-------|--------|
| 13.1 | Item ID → name mapping | Load from RuneLite cache or wiki JSON dump | 🔜 |
| 13.2 | NPC ID → name mapping | Same — for resolving nameless NPCs | 🔜 |
| 13.3 | World point → region ID | For detecting which area the player is in | 🔜 |
| 13.4 | Bank value tracking | Sum item values from GE price data | 💡 |
| 13.5 | XP rate tracking | XP/hour computed over a rolling window | 🔜 |

---

## End-to-end test plan (today)

- [ ] `mise run gamebridge-setup` installs `textual` without error
- [ ] `mise run gamebridge-watch` connects and prints one line per tick
- [ ] `mise run gamebridge` opens the GUI dashboard without crashing
- [ ] Dashboard shows live player position, HP, prayer
- [ ] NPCs table populates with entities visible in-game
- [ ] Objects table populates
- [ ] Debug log shows one line per tick with event types
- [ ] `d` key toggles the debug log off and on
- [ ] `s` key (or Start button) launches `iron_mining` routine
- [ ] `Gold Mining` appears in the routine dropdown and can start
- [ ] Routine state label updates as states transition
- [ ] `x` key (or Stop button) halts the routine
- [ ] No Python exceptions in the terminal
