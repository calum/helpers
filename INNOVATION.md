# GameBridge — Innovation Ideas

A living list of ideas for evolving the system. Grouped by theme; no particular priority order.

---

## Testing & Quality

### Record & Replay (your idea)
Record a real play session by capturing the raw TCP stream to a `.jsonl` file (one tick per line).
Sanity-check the recording (run it through the contract validator), then commit it as a fixture.
Tests can feed the recording through `GameState.update()` tick-by-tick and assert on derived state.

**Fragility note:** recordings are tied to the wire format version. When the plugin schema changes you
need to re-record or write a migration. Mitigate by storing the plugin version (or a schema hash) as
the first line of the recording file so tests can fail loudly with a useful message instead of
silently passing with stale data.

**Implementation sketch:**
```python
# scripts/gamebridge/tools/recorder.py
import json, sys
from scripts.gamebridge.client import BridgeClient

with open("recording.jsonl", "w") as f:
    for msg in BridgeClient().stream():
        f.write(json.dumps(msg) + "\n")
        if msg["tick"] >= START_TICK + 600:   # ~6 minutes
            break
```

---

### Routine Dry-Run / Simulation Mode
Feed a recording through the full `DecisionEngine + Routine` stack without sending any real inputs
— replace `GameController` with a `NullController` stub that records every action it *would* have
taken. You get a deterministic log of `(tick, state, action)` triples you can assert against.

This lets you verify that `IronMiningRoutine` would have clicked the correct ore rock on tick 42
of a recording without touching the game. Fast, reproducible, no game window needed.

---

### Schema Fuzzing
Mutate `contract.json` programmatically — remove fields, change types, add unknown keys — and feed
each mutation through `GameState.update()`. The expectation is that the parser either silently
ignores unknown keys or raises a well-formed error, never silently producing wrong state.

`hypothesis` (property-based testing library) could generate the mutations automatically.

---

### Tick-Level Regression Snapshots
After each recording session, snapshot the `GameState` after tick N as JSON and commit it.
A regression test re-plays the recording and diffs the final state. If a refactor accidentally
changes query semantics the diff will catch it immediately.

---

## Observability & Debugging

### Decision Logger
Every state transition that the `Routine` makes is already logged as a line at `INFO`. Extend this
to write a structured `decision_log.jsonl` alongside each recording: `{tick, routine, from_state,
to_state, action_type, target_name, screen_pos}`. Post-mortem analysis becomes trivial — just grep
for the tick where something went wrong and inspect the full chain of events that led there.

---

### State Machine Visualizer (Dashboard tab)
Add a "Routine" tab to the PyQt6 dashboard that renders the routine as a graph:
- Nodes = states; current state highlighted.
- Directed edges = observed transitions (built up live as the routine runs).
- Edge labels = how many times that transition has fired.

`networkx` + `matplotlib` embedded in a `FigureCanvasQTAgg` is the path of least resistance.
No external dependencies beyond what the project probably already has.

---

### Conditional Breakpoints
Add a `DebugHook` to `DecisionEngine.process_tick()` — a callable that receives `(game, routine)`
before each tick. From the dashboard you can install a lambda like:

```python
engine.debug_hook = lambda g, r: breakpoint() if g.player_hp() < 30 else None
```

This is the automation equivalent of a debugger watchpoint — the routine pauses the moment an
interesting condition is met without you having to add temporary `print` statements.

---

### Replay Scrubber
A dashboard widget that loads a `.jsonl` recording and lets you scrub through it like a video —
drag a slider to any tick, see the full `GameState` rendered in the existing state panel. Useful
for understanding exactly what the plugin was seeing when something went wrong.

---

## Performance & Protocol

### Tick Delta Encoding
The current plugin sends the full world state every tick (~600ms). Most of it is unchanged:
the 20 NPCs and 40 objects usually don't move. Instead of resending everything, send a
`"delta": true` flag and only include keys whose values changed from the previous tick.

The Python side merges deltas onto a base snapshot. Reduces payload size by ~80% on a stable
scene. Particularly valuable if the widget tree is large.

---

### Schema Versioning
Add `"_schema": 1` to every tick message (bump the integer whenever the contract changes).
The Python consumer checks this on connect and rejects unknown schema versions with a clear error
rather than silently misinterpreting fields. Recordings embed the schema version so the replay
tool can detect stale recordings immediately.

---

### Binary / MessagePack Transport
Replace JSON with [MessagePack](https://msgpack.org/) — same key/value structure, 2–3× smaller
on the wire, 3–5× faster to serialise/parse. Java has `msgpack-java`; Python has `msgpack`.
The contract file stays as JSON (human-readable), but the live stream uses binary frames.

Practical only once the system is mature — adds complexity to debugging since you can't
`nc localhost 7070` and read the output directly.

---

### WebSocket Transport
Replace the raw TCP framing with WebSocket. This opens the door to a browser-based dashboard
(plain HTML + JS, no PyQt6 required) and makes the protocol firewall-friendly. `java-websocket`
handles the server side; `websockets` handles the Python client.

---

## Automation Intelligence

### Adaptive HumanEmulator Calibration
Record 30 minutes of real human play (mouse positions + timestamps from a passive listener).
Fit the `reaction_mean`, `reaction_std`, `click_error_px`, `wpm` parameters to the observed
distributions using `scipy.optimize.curve_fit` or maximum likelihood estimation.
The emulator then produces timing that matches your own play style rather than hand-tuned
constants.

---

### Anomaly Detection / Safe Shutdown
Before every `Routine.tick()` call, run a checklist of "shouldn't happen" conditions:

- HP below threshold (maybe dying)
- Inventory changed unexpectedly (maybe a drop/steal)
- Player teleported more than N tiles in one tick (disconnected / world hop)
- Routine stuck in same state for more than K ticks (infinite loop)
- No tick received for more than 5 seconds (game frozen)

On a hit: pause the routine, play a system alert sound, send a desktop notification, and optionally
log out via the keyboard shortcut. Far cheaper than a ban.

---

### Routine Composition (Pre/Post conditions)
Right now switching routines requires code. Add a lightweight combinator layer:

```python
engine.set_routine(
    If(lambda g: g.inventory_full(), BankRoutine())
    .else_(IronMiningRoutine())
)
```

`If` wraps two routines and delegates `tick()` based on the predicate. Routines stay simple and
single-purpose; the engine handles the policy. No new framework needed — just a few small wrapper
classes on top of `Routine`.

---

### XP Rate & Session Statistics (Dashboard)
Track XP deltas per skill over time and display:
- XP/hr for the active skill (rolling 5-min average)
- Actions per hour (bank trips, ore mined, etc.)
- Session length and estimated remaining time to level

All derivable from the existing `GameState.xp` and `GameState.tick` data. Persist to
`~/.gamebridge/session_history.jsonl` so you can review past sessions.

---

### World Map Overlay (Dashboard)
Render a canvas widget showing the player's position as a dot with NPCs and objects around them
as labelled icons (tile coordinates → pixel coordinates with a zoom/pan control). Update live
from each tick. Useful for verifying that the routine is navigating correctly without having
to watch the game window. Optionally overlay the planned mouse path before it is executed.

---

### Hot-Reload Routines
Watch the `scripts/gamebridge/routines/` directory for file changes (`watchdog` library). On a
change, reimport the module and swap the active routine instance in the engine without restarting
the process. Useful during development — edit a state method and see the change take effect on
the next tick without losing the current session.

---

## Infrastructure

### Plugin Health Metrics Endpoint
Add a `/metrics` text endpoint on a second port (e.g. 7071) that returns plaintext Prometheus-
compatible metrics:

```
gamebridge_tick_total 12345
gamebridge_connected_clients 1
gamebridge_serialise_ms_last 3.2
gamebridge_objects_serialised_last 47
```

The Python dashboard (or any Prometheus scraper) can poll this independently of the tick stream.
Useful for spotting serialisation slowdowns or dropped clients.

---

### Multi-Account Fan-Out
Run two game clients on the same machine. The plugin already handles multiple TCP clients
(`CopyOnWriteArrayList<ClientEntry>`). The Python side needs a `MultiAccountEngine` that maps
each connection to its own `GameState + Routine` pair and ticks them independently.
Primary use case: one account mines, another banks.

---

## Game Logic Integration

### Varbit-Driven Activity Automation
The `varbit` event stream exposes the same low-level signals RuneLite plugins use internally to
track minigame and skilling-activity state (Giant's Foundry, Blast Furnace, Wintertodt, etc.).
Rather than reimplementing the visual pattern-matching those plugins do, capture the relevant
varbit IDs for an activity and build a minimal Python state machine that mirrors the plugin's
logic:

```python
# Giant's Foundry: varbit 13948 tracks the current stage (0=start, 1=trip, 2=pour, ...)
def foundry_stage(game: GameState) -> int:
    return game.get_varbit(varp_id=0, varbit_id=13948) or 0
```

Use the RuneLite **Devtools** plugin to read varbit IDs live while playing the activity.
No Java changes required — the plugin already emits every varbit change when `exposeVarbits` is on.

---

### Chat-Pattern Confirmation Signals
Use `game.last_chat_matching(substring)` within routines as a lightweight confirmation that a
game action succeeded, rather than relying purely on animation or position state:

- `"You chop some logs."` → woodcutting click was accepted by the server
- `"You've been poisoned."` → trigger antidote sub-routine
- `"You do not have enough"` → inventory/rune check failed; abort and restock
- `"Welcome to"` → world-hop or login just completed; delay next action

This is complementary to `animation_started()` / `player_idle()` — chat confirms the server
processed the action, not just that the client played an animation. Cap lookback with
`game.chat_since_tick(game.tick - 5)` to avoid false positives from old messages.

---

### Routine State Persistence (Crash Recovery)
If the Python process crashes mid-run, the routine always restarts from its `@initial_state`.
For long loops (e.g., a 2-hour mining session with 40 bank trips), this can waste significant
setup time.

On every state transition, serialize `{routine_class, current_state, state_enter_tick, custom_vars}`
to `~/.gamebridge/routine_state.json`. On startup, offer to restore from this file if it exists
and is less than N minutes old:

```python
# routines/base.py addition
def save_checkpoint(self, game: GameState, extra: dict = {}):
    path = Path.home() / ".gamebridge" / "routine_state.json"
    path.write_text(json.dumps({
        "routine": self.name,
        "state": self.current_state,
        "tick": game.tick,
        **extra,
    }))
```

The engine checks for a checkpoint file at startup and restores state if the user confirms.
Particularly useful when the break timer fires a Ctrl+Shift+Q and the session was almost done.
