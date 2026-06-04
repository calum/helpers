# RuneLite Client — CLAUDE.md

## Testing Requirements

Every code change — bug fix, new feature, or refactor — must include new or updated tests. A change is not complete until the relevant tests pass.

**Rules:**
- Any new public method, function, or behaviour gets at least one test covering the happy path and one covering each failure/edge case.
- Any modified behaviour must have its existing tests updated to match and new tests added for the changed logic.
- Tests must pass locally before considering the task done. Run with:
  ```powershell
  # Python (gamebridge scripts)
  python -m pytest scripts/gamebridge/tests/ -v

  # Java (RuneLite client)
  ./gradlew.bat :runelite-client:test
  ```
- Do not skip or comment out failing tests to make the suite green — fix the code or the test.
- Test the actual behaviour, not implementation details: assert on observable outputs (return values, logged messages, mock call counts/args), not on internal state.

---

## Research Protocol

After any research session (reading source files, exploring the codebase, investigating APIs), update `PLAN.md` with new findings. Add concrete details: file paths, class names, how mechanisms work, open questions, and next steps. Keep `PLAN.md` as a living document that accumulates knowledge across sessions.

## Game Bridge maintenance rule

`GAMEBRIDGE.md` is the Python developer guide for the Game Bridge plugin. It documents the exact JSON wire format, event types, field names, config keys, and code examples. **Whenever you modify any file in `runelite-client/…/plugins/gamebridge/`, you must also update `GAMEBRIDGE.md`** to keep the two in sync. Specifically:

- Adding or removing a field in a tick message → update the relevant section and its JSON example in `GAMEBRIDGE.md`
- Adding, removing, or renaming an event type → update the Events section
- Adding or removing a config item → update the Plugin config reference table
- Changing the hull filter matching logic → update the Hull filter section
- Changing the port default or protocol framing → update the Protocol section

The guide is the contract between the Java plugin and any Python tooling built against it. A silent schema change breaks Python consumers without any compile-time warning.

---

## Goal

Add a simple hook (plugin) to RuneLite that logs a console event when a `Tree` game object spawns, then build the client and wire it to the Jagex Launcher as the default client.

---

## Project Layout

| Module | Path | Purpose |
|---|---|---|
| `runelite-api` | `runelite-api/` | Java interfaces that mirror the RS game engine. No implementation; injected at runtime by Mixins. |
| `runelite-client` | `runelite-client/` | The actual desktop application. Contains plugins, UI, event bus, config system. |
| `cache` | `cache/` | Cache-reading utilities. Not needed for this task. |
| `runelite-gradle-plugin` | `runelite-gradle-plugin/` | Gradle plugin used by the build. Not needed for this task. |

Project root is a Gradle composite build. Gradle wrapper: `./gradlew.bat` (Windows).

---

## Key Concepts

### Event Bus

All game-to-plugin communication goes through an event bus (`runelite-client/…/eventbus/`).

- Game events live in `runelite-api/…/api/events/` — e.g. `GameObjectSpawned`, `GameObjectDespawned`, `GameTick`.
- Client-level events live in `runelite-client/…/client/events/` — e.g. `ConfigChanged`, `PluginChanged`.
- A plugin subscribes by annotating a method with `@Subscribe`.

### Plugin System

Every plugin:
1. Extends `net.runelite.client.plugins.Plugin`.
2. Is annotated with `@PluginDescriptor(name = "…")`.
3. Lives in its own package under `runelite-client/…/client/plugins/<name>/`.
4. Uses `@Inject` (Guice) to receive `Client`, `EventBus`, `ConfigManager`, etc.
5. Optionally provides a `@Config`-annotated interface and a `@Provides`-annotated factory method.

Minimal plugin skeleton:
```java
@PluginDescriptor(name = "Tree Logger", description = "Logs Tree spawns", enabledByDefault = true)
public class TreeLoggerPlugin extends Plugin {
    @Inject private Client client;

    @Subscribe
    public void onGameObjectSpawned(GameObjectSpawned event) {
        ObjectComposition comp = client.getObjectDefinition(event.getGameObject().getId());
        if ("Tree".equals(comp.getName())) {
            System.out.println("Tree spawned at " + event.getGameObject().getWorldLocation());
        }
    }
}
```

### How the Game Client starts

Entry point: `RuneLite.java` — sets up Guice, loads `RuneLiteModule`, discovers plugins via classpath scanning, then starts the game loop.

### API vs Implementation

`runelite-api` only contains **interfaces** (e.g. `Client.java`, `GameObject.java`). The real game classes that implement them are injected by the RS client at runtime via **Mixins** (byte-code weaving). You never instantiate these yourself.

---

## Relevant Files for Our Task

| File | Why |
|---|---|
| `runelite-api/…/api/events/GameObjectSpawned.java` | Event fired when a game object appears in the scene |
| `runelite-api/…/api/events/GameObjectDespawned.java` | Counterpart despawn event |
| `runelite-api/…/api/GameObject.java` | Interface for in-world objects |
| `runelite-api/…/api/ObjectComposition.java` | Holds the object's name, actions, etc. |
| `runelite-api/…/api/Client.java` | Main game client interface — `getObjectDefinition(id)` resolves composition |
| `runelite-client/…/client/plugins/` | Drop our new plugin here |
| `runelite-client/…/client/RuneLite.java` | Main entry point |

### Game Bridge plugin files

| File | Purpose |
|---|---|
| `runelite-client/…/plugins/gamebridge/GameBridgePlugin.java` | Plugin entry point — event subscriptions, tick batching, JSON serialisation |
| `runelite-client/…/plugins/gamebridge/GameBridgeConfig.java` | Config interface (port, category toggles, hull filter) |
| `runelite-client/…/plugins/gamebridge/BridgeServer.java` | Embedded TCP server — accept loop, broadcast |
| `runelite-client/…/plugins/gamebridge/HullFilter.java` | Parses ID/name filter CSV; answers `matches(id, name)` |
| `GAMEBRIDGE.md` | Python developer guide — **keep in sync with any schema changes** |

---

## Build & Run

```powershell
# Build everything
./gradlew.bat assembleAll

# Run the client directly (development mode)
./gradlew.bat :client:run

# Build a fat jar
./gradlew.bat :client:shadowJar
```

The shadow jar ends up in `runelite-client/build/libs/`.

---

## Jagex Launcher Integration

**`RuneLite.jar` in `%LOCALAPPDATA%\RuneLite\` is not the client** — it is a launcher bootstrap (`net.runelite.launcher.Launcher`). Replacing it with the shaded client jar breaks the launcher.

The launcher downloads all dependencies to `~/.runelite/repository2/` and constructs a classpath. The actual client jar is:
```
C:\Users\Calum\.runelite\repository2\client-<version>.jar
```

To integrate a custom build with the launcher:
1. Build the client: `mise exec -- .\gradlew.bat :client:shadowJar`
2. Extract just the client classes into a non-fat jar (or use `:client:jar`), replacing `client-<version>.jar` in `repository2/`.
3. Launch with `--skip-update` to prevent the launcher re-downloading the original:
   ```powershell
   & "C:\Users\Calum\AppData\Local\RuneLite\RuneLite.exe" --skip-update
   ```

Alternatively, bypass the launcher entirely using the bundled JRE and the shaded jar directly:
```powershell
& "C:\Users\Calum\AppData\Local\RuneLite\jre\bin\java.exe" -jar "path\to\client-<version>-shaded.jar"
```
This is confirmed working — see ARCHITECTURE.md for full details.

---

## Conventions Observed in This Codebase

- BSD 2-clause license header on every `.java` file.
- Allman brace style.
- Tabs for indentation.
- `@Slf4j` (Lombok) for logging — `log.info(…)` preferred over `System.out.println`.
- Plugin packages are flat (no sub-packages unless the plugin is large).
- Tests go in the matching `src/test/java/…` path.
