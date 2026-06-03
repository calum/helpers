![](https://runelite.net/img/logo.png)

# GameBridge — RuneLite Plugin + Python Automation

A custom RuneLite client with an embedded **Game Bridge** plugin that streams live RuneScape game state over a local TCP socket to a Python automation layer. Build game-aware bots, dashboards, and interactive tools.

## What is GameBridge?

The **Game Bridge** plugin captures a per-tick snapshot of game state (player, camera, NPCs, objects, inventory, widgets, varbits, events) and broadcasts it as newline-delimited JSON to any TCP client. The Python layer reads this stream, controls the game via mouse/keyboard automation, and executes scripted routines against live game state.

### Example: Iron Mining Routine

```python
from scripts.gamebridge.routines.examples.iron_mining import IronMiningRoutine

engine.set_routine(IronMiningRoutine())  # Mine, bank, repeat
```

The routine:
- Scans for the nearest iron ore rock
- Clicks and waits for a mining XP event (or 3-second timeout)
- Banks when inventory is full
- Repeats

See [iron_mining.py](scripts/gamebridge/routines/examples/iron_mining.py) and the [Game State API](scripts/gamebridge/state/game_state.py) for examples.

## Project Structure

| Component | Location | Purpose |
|---|---|---|
| **Custom RuneLite Client** | `runelite-api/`, `runelite-client/` | Java; forked from RuneLite. Compiled to a custom jar and deployed to the Jagex Launcher. |
| **Game Bridge Plugin** | `runelite-client/…/plugins/gamebridge/` | Java plugin; streams game state as JSON over TCP port 7070. |
| **Object Logger Plugin** | `runelite-client/…/plugins/objectlogger/` | Java plugin; logs world object spawns and despawns. |
| **Python Game State Model** | `scripts/gamebridge/state/game_state.py` | In-memory snapshot of the game world, updated from tick messages. |
| **Python Controller** | `scripts/gamebridge/controller/controller.py` | Mouse/keyboard input handler; bridges Python to the game window. |
| **Routine Engine** | `scripts/gamebridge/controller/engine.py` | State machine runtime for scripted bot routines. |
| **Dashboard** | `scripts/gamebridge/dashboard.py` | Qt6 GUI; shows live game state, runs/stops routines, hull debugging overlay. |
| **Wire Format Spec** | [GAMEBRIDGE.md](GAMEBRIDGE.md) | Full JSON schema, event types, config keys — the contract between Java and Python. |

## Quick Start

### Prerequisites

- Windows with Python 3.12+
- Jagex Launcher with RuneLite installed

### Setup

```powershell
# Install dependencies
mise run gamebridge-setup

# Build and deploy the custom client to the Jagex Launcher
mise run full-build

# Launch the GameBridge dashboard
mise run gamebridge
```

Once the dashboard opens, enable the **Game Bridge** plugin in RuneLite's Plugins panel. The dashboard will connect and start streaming game state.

### Development

```powershell
# Run all tests (Python + Java)
mise run test

# Watch live game state in the terminal
mise run gamebridge-watch

# Development build (does not update gradle.properties version)
mise exec -- ./gradlew.bat :client:shadowJar
```

## Wire Format

The Game Bridge plugin emits one JSON line per game tick (~600 ms):

```json
{
  "tick": 12345,
  "player": { "name": "Zezima", "worldX": 3200, "worldY": 3300, "hp": 99, "prayer": 99, "animation": -1 },
  "camera": { "yaw": 1024, "pitch": 512 },
  "npcs": [ { "id": 3106, "name": "Goblin", "worldX": 3210, "worldY": 3310, "onScreen": true, "hull": [[...]] } ],
  "objects": [ { "id": 1276, "name": "Oak tree", "worldX": 3195, "worldY": 3295, "onScreen": false } ],
  "inventory": [ { "slot": 0, "itemId": 440, "qty": 1 }, ... ],
  "events": [
    { "type": "xp", "skill": "WOODCUTTING", "xp": 1204050, "level": 70, "boostedLevel": 70 },
    { "type": "chat", "msgType": "GAMEMESSAGE", "message": "You chop some logs." }
  ]
}
```

For the full specification, see [GAMEBRIDGE.md](GAMEBRIDGE.md).

## Key Concepts

### Event Bus

All game-to-plugin communication flows through RuneLite's event bus. Plugins subscribe to game events (e.g., `GameObjectSpawned`, `GameTick`) and emit their own events. The Game Bridge plugin batches these into a single JSON message per tick.

### Plugin System

- All plugins extend `net.runelite.client.plugins.Plugin` and are auto-discovered via classpath scanning.
- Dependency injection via Guice — access `Client`, `ConfigManager`, `EventBus`, etc. via `@Inject`.
- Configuration via `@Config` interface + `@Provides` factory method.

### Python Automation

The Python layer reads the TCP stream, applies business logic to decide actions, and sends mouse/keyboard commands. A simple state machine (`Routine`) tracks which action to take next based on game state.

Example routine lifecycle:

```
find_ore → (ore found) → mining → (xp event) → find_ore (if not full)
                                              → walk_to_bank (if full)
         → walk_to_bank → (near bank) → deposit → find_ore
```

## Conventions

- **Java files**: BSD 2-clause license header, Allman braces, tabs, `@Slf4j` logging.
- **Python files**: PEP 8, type hints, docstrings.
- **Plugins**: Flat package structure under `runelite-client/…/client/plugins/<name>/`.
- **Tests**: Python uses pytest; Java uses JUnit.

## Jagex Launcher Integration

The custom client is built as a shaded jar and deployed to `%LOCALAPPDATA%\RuneLite\RuneLite.jar`. The Jagex Launcher reads `config.json` and invokes it with the bundled JRE. To build and deploy:

```powershell
mise run full-build
```

This script:
1. Fetches the current official RuneLite version from the bootstrap CDN
2. Builds the custom client with that version
3. Injects a launcher bootstrap class
4. Copies to the Jagex Launcher installation

After running, launch RuneLite as normal via the Jagex Launcher.

## Resources

- **[GAMEBRIDGE.md](GAMEBRIDGE.md)** — Wire-format contract and Python API reference
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — System design, Jagex Launcher integration, build pipeline
- **[CLAUDE.md](CLAUDE.md)** — Development notes and conventions

## License

RuneLite is licensed under the BSD 2-clause license. See the license header in each `.java` file.

## Development

Join our [Discord](https://runelite.net/discord) for questions or discussion.
