# RuneLite Custom Client — Architecture & Developer Guide

**Status: Core system complete.** Plugin runs, Jagex Launcher launches our custom build. `mise run full-build` handles the full deploy.

---

## Goal

A RuneLite plugin (Game Bridge) that streams a per-tick JSON snapshot of game state over a local TCP socket to a Python automation layer. The Python side reads the stream, controls the mouse/keyboard, and runs scripted routines against the live game.

---

## Project Layout

| Module | Path | Purpose |
|---|---|---|
| `runelite-api` | `runelite-api/` | Java interfaces mirroring the RS game engine. No implementation — real classes injected at runtime via Mixins. |
| `runelite-client` | `runelite-client/` | Desktop application. Plugins, UI, event bus, config system. |
| `cache` | `cache/` | Cache reading utilities. Not needed for this project. |
| `runelite-gradle-plugin` | `runelite-gradle-plugin/` | Build plugin. Not needed for this project. |

Build system: Gradle composite build. Entry point: `.\gradlew.bat`. Version in `gradle.properties` (`project.build.version`).

---

## Plugin System

- All plugins extend `net.runelite.client.plugins.Plugin`, annotated `@PluginDescriptor(name="…")`.
- Plugins live in `runelite-client/…/client/plugins/<name>/`.
- Dependency injection via Guice — `@Inject` for `Client`, `ConfigManager`, etc.
- Event subscriptions via `@Subscribe` on methods.
- **PluginManager uses classpath scanning** — any class annotated `@PluginDescriptor` in the `net.runelite.client.plugins.*` package is auto-discovered at startup. No registration needed.

### Event flow

```
Jagex game binary → Callbacks.java (runelite-api/hooks/)
                  → Hooks.java (runelite-client/callback/)
                  → EventBus.post()
                  → all @Subscribe methods on all registered plugins
```

### Relevant events

- `GameObjectSpawned` — fired when any world object appears (trees, rocks, doors, etc.)
- `GameObjectDespawned` — fired when removed
- `ObjectComposition` — resolved via `client.getObjectDefinition(id)`, provides `.getName()`

### Mixin layer

Mixins are NOT in this repo. The game client binary (downloaded from Jagex at runtime by `ClientLoader`) has the mixin hooks woven in. We cannot modify the mixin layer from this repo.

---

## ObjectLoggerPlugin

**Location:**
- `runelite-client/src/main/java/net/runelite/client/plugins/objectlogger/ObjectLoggerPlugin.java`
- `runelite-client/src/main/java/net/runelite/client/plugins/objectlogger/ObjectLoggerConfig.java`

**Behaviour:**
- Subscribes to `GameObjectSpawned` and optionally `GameObjectDespawned`.
- Resolves object names via `client.getObjectDefinition(id)`, following the impostor chain for varbit-dependent objects (e.g. doors).
- Appends to a log file (default: `~/.runelite/object-logger.log`).
- Config: `trackedObjects` (comma-separated names, case-insensitive; empty = log all), `logDespawns` (boolean), `verboseLogging` (boolean), `chatMessages` (show in-game chat).
- `enabledByDefault = false` — must be enabled manually in the Plugins panel.

**Log line format:**
```
[yyyy-MM-dd HH:mm:ss] SPAWN id=<id> name="<name>" location=WorldPoint{x=…,y=…,plane=…}
```

---

## Game Bridge Plugin

See `GAMEBRIDGE.md` for the full wire-format contract between the Java plugin and Python consumers.

**Key design decisions:**
- One JSON line per game tick (~600 ms) broadcast to all connected TCP clients.
- Objects list includes all four tile object categories: `GameObject`, `WallObject`, `GroundObject`, `DecorativeObject`.
- Names are impostor-resolved (varbit-dependent objects show their current name, not `"null"`).
- Convex hull polygons are computed in screen-pixel coordinates and included per entity.

---

## Jagex Launcher Architecture

Discovered empirically on 2026-06-03.

### File layout

```
C:\Users\Calum\AppData\Local\RuneLite\
├── RuneLite.exe          # Native wrapper — reads config.json, invokes java
├── RuneLite.jar          # Entry-point jar — WE REPLACE THIS with our custom build
├── config.json           # Tells RuneLite.exe exactly what JVM command to run
└── jre\                  # Bundled JRE
```

### config.json

```json
{
  "classPath": ["RuneLite.jar"],
  "mainClass": "net.runelite.launcher.Launcher",
  "vmArgs": [
    "-XX:+DisableAttachMechanism",
    "-Drunelite.launcher.nojvm=true",
    "-Drunelite.launcher.blacklistedDlls=...",
    "-Xmx768m", "-Xss2m", "-XX:CompileThreshold=1500"
  ]
}
```

`RuneLite.exe` constructs: `jre\bin\java.exe <vmArgs> -cp RuneLite.jar net.runelite.launcher.Launcher`

### Key findings

| Question | Answer |
|---|---|
| Does Jagex Launcher validate RuneLite.jar? | **No.** Confirmed by replacing it with a trivial jar — no error. |
| Are credentials passed via args or env vars? | **No.** Args are empty; only the `runelite.launcher.*` system properties are set. |
| Is there a named pipe for auth? | **No.** `\\.\pipe\JagexLauncher` does not exist. |
| How does auth work? | The RuneLite client reads stored credentials from disk (`read 5 credentials from disk` in logs). Jagex auth is handled entirely within the client, not by the launcher. |
| Does our build report as modified to Jagex? | **No.** All Jagex game server communication goes through `injected-client`, downloaded unmodified from RuneLite's CDN at runtime. Our code runs above that layer. |

### Why `net.runelite.launcher.Launcher` is needed

`config.json` hardcodes `mainClass=net.runelite.launcher.Launcher`. The RuneLite client shaded jar does not contain this class (its own main class is `net.runelite.client.RuneLite`). The build script injects a thin wrapper class that delegates immediately:

```java
// scripts/Launcher.java — injected into the deployed jar
public class Launcher {
    public static void main(String[] args) throws Exception {
        net.runelite.client.RuneLite.main(args);
    }
}
```

### Why the version must match the official release

`runelite.properties` bakes `${project.version}` into the plugin hub URL and API base URL:
```
runelite.pluginhub.version=${project.version}   → https://repo.runelite.net/plugins/<version>/
runelite.api.base=https://api.runelite.net/runelite-${project.version}
```

A SNAPSHOT version causes 404s on those endpoints. The build script fetches the current official version from `https://static.runelite.net/bootstrap.json` before each build and stamps it into `gradle.properties`.

---

## Build & Deploy

### One command

```powershell
mise run full-build
```

This script (`scripts/full-build.ps1`):
1. Fetches the current official RuneLite version from `https://static.runelite.net/bootstrap.json`
2. Updates `gradle.properties` with that version
3. Runs `.\gradlew.bat :client:shadowJar`
4. Compiles `scripts/Launcher.java` against the shaded jar
5. Injects the wrapper class into a copy of the shaded jar
6. Copies it to `%LOCALAPPDATA%\RuneLite\RuneLite.jar`

After running, launch RuneLite via the Jagex Launcher as normal.

### Manual steps (for reference)

```powershell
# Build only (uses whatever version is in gradle.properties)
mise exec -- .\gradlew.bat :client:shadowJar

# Run tests
mise exec -- .\gradlew.bat testAll

# Clean
mise exec -- .\gradlew.bat cleanAll
```

### Note on gradle.properties

`gradle.properties` keeps `project.build.version=1.12.28-SNAPSHOT` as the development default. `mise run full-build` overwrites it to the current official version before building, so the deployed jar is always compatible with the plugin hub. If you want to check what version was used for the last deploy, look at `gradle.properties`.

---

## Key Files

| File | Purpose |
|---|---|
| `runelite-client/…/plugins/gamebridge/GameBridgePlugin.java` | Game Bridge plugin — tick batching, JSON serialisation, event subscriptions |
| `runelite-client/…/plugins/gamebridge/GameBridgeConfig.java` | Game Bridge config interface |
| `runelite-client/…/plugins/gamebridge/BridgeServer.java` | Embedded TCP server |
| `runelite-client/…/plugins/gamebridge/HullFilter.java` | ID/name filter for convex hull data |
| `runelite-client/…/plugins/objectlogger/ObjectLoggerPlugin.java` | Object spawn/despawn logger plugin |
| `runelite-client/…/plugins/objectlogger/ObjectLoggerConfig.java` | Object logger config interface |
| `runelite-client/src/main/resources/…/runelite.properties` | Version/URL config baked into the jar at build time |
| `gradle.properties` | Project version (stamped by build script before each deploy) |
| `scripts/Launcher.java` | Thin entry-point wrapper injected into the deployed jar |
| `scripts/full-build.ps1` | Full build and deploy script |
| `mise.toml` | Pins JDK to Temurin 11; defines `full-build` task |
| `scripts/gamebridge/` | Python automation layer (controller, routines, dashboard) |
| `GAMEBRIDGE.md` | Wire-format contract between the Java plugin and Python consumers |
| `C:\Users\Calum\AppData\Local\RuneLite\config.json` | Jagex Launcher JVM configuration (not in repo) |
| `C:\Users\Calum\AppData\Local\RuneLite\RuneLite.jar.bak` | Backup of original launcher bootstrap (not in repo) |
| `~/.runelite/object-logger.log` | Object logger plugin output |

---

## Known Issues & Backlog

### ✅ [Java] Object list performance — restrict by filter

**Resolved 2026-06-03.**

New config keys: `objectFilter` (CSV), `sendAllNamedObjects` (bool), `debugAllObjects` (bool). Default behaviour now sends **no objects** unless the filter is set or a toggle is on. See `GAMEBRIDGE.md` — Object filtering section.

**Open:** Widget `actions` field is not yet serialised (Widget.getActions() returns String[]). Add if right-click menu automation is needed.

---

### ✅ [Java] Interface / UI element exposure

**Resolved 2026-06-03.**

New `exposeWidgets` config (default off). When on, a `widgets` array is included in every tick message containing visible slot data (groupId, childId, itemId, quantity, screen bounds, text) for widget groups 149 (Inventory), 12 (Bank), 387 (Equipment), 192 (Deposit box).

The scanner walks two levels deep per group: dynamic children of the root (item slots), static children of the root (structural sub-containers and individual slots like equipment), and dynamic children of each static child (e.g. bank slots nested under `Bankmain.ITEMS` at child 12).

#### How to add a new widget group

1. Find the interface ID. Look up the constant in `runelite-api/…/gameval/InterfaceID.java` — the top-level `public static final int FOO = N;` line gives the group ID.
2. Add it to `WIDGET_GROUPS` in `GameBridgePlugin.java`:
   ```java
   private static final int[] WIDGET_GROUPS = {149, 12, 387, 192, N};
   ```
3. No other Java changes needed. `collectVisibleWidgets` handles the scanning automatically.
4. Update `GAMEBRIDGE.md` — add the new group ID to the `groupId` field description in the Widgets section.

#### Known widget group IDs

| Group ID | Interface | Notes |
|---|---|---|
| 149 | Inventory | Always present in-game |
| 12 | Bank | Only when bank is open |
| 387 | Equipment (Wornitems) | Always present |
| 192 | Deposit box | Only when deposit box is open |

To find an ID for a new interface: search `InterfaceID.java` for a recognisable name (e.g. `GRAND_EXCHANGE`, `PRAYER`, `SKILLS`), or use RuneLite's built-in **Widget Inspector** plugin to click on any UI element and read off the group/child IDs live.

---

### ✅ [Python] Configurable RuneLite window name in dashboard

**Resolved 2026-06-03.**

Settings persisted to `~/.gamebridge/settings.json`. Window name editable via the dashboard Settings tab. `_find_runelite_window` in `controller.py` reads from settings and falls back to prefix-matching via `EnumWindows` if an exact match fails.

---

### ✅ [Python] Keyboard shortcut to stop a running routine / emergency shutdown

**Resolved 2026-06-03.**

Global hotkeys registered via a `GetAsyncKeyState` polling daemon thread (no extra dependencies):
- **F10** — stop the running routine cleanly
- **Ctrl+Shift+Q** — hard-kill the dashboard via `os._exit(0)`

Hotkeys are shown in the status bar and documented in the Settings tab.

---

### ✅ [Python] Convex hull debugging overlay in dashboard

**Resolved 2026-06-03. UI updated 2026-06-03.**

The **Hull Debug** tab in the dashboard captures a screenshot of the RuneLite window and overlays hull/bounds data using `QScreen.grabWindow(hwnd)` + `QPainter` — no extra dependencies.

**Controls:**

| Control | Description |
|---|---|
| **NPC / Object / Widget dropdowns** | Select which entity to highlight. Each dropdown is populated from live game data sorted by distance (NPCs/Objects) or group+child (Widgets), with on-screen status shown. |
| **❄ Freeze** | Pauses dropdown repopulation so you can browse and select without the list jumping every tick. Game data and the screenshot capture itself still use the latest tick. Click again (▶ Live) to resume. |
| **☐ Show All Widgets** | Overlays every visible widget's bounds on the screenshot, colour-coded by group (blue=Inventory/149, green=Bank/12, yellow=Equipment/387, purple=DepositBox/192) with `G{groupId}:{childId}` labels. The widget selected in the dropdown is highlighted brighter. |
| **📷 Capture Hull** | Takes the screenshot and draws the overlay. If no entity is selected and Show All Widgets is off, falls back to the nearest on-screen NPC or object with a hull. |

**Hull Y-offset bug fixed 2026-06-03.** `grabWindow(hwnd)` captures the full OS window including the native title bar/border, but hull coordinates are in canvas (client area) space. The captured pixmap is cropped to the client area rectangle via `GetWindowRect + GetClientRect + ClientToScreen` before hull points are drawn, so the overlay aligns correctly regardless of window chrome height.
