# RuneLite Client — CLAUDE.md

## Research Protocol

After any research session (reading source files, exploring the codebase, investigating APIs), update `PLAN.md` with new findings. Add concrete details: file paths, class names, how mechanisms work, open questions, and next steps. Keep `PLAN.md` as a living document that accumulates knowledge across sessions.

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

## Jagex Launcher Integration (TODO — research in progress)

The Jagex Launcher can be pointed at a custom client via its configuration. The exact mechanism (registry key, config file path, launcher arguments) still needs to be confirmed. See PLAN.md for status.

---

## Conventions Observed in This Codebase

- BSD 2-clause license header on every `.java` file.
- Allman brace style.
- Tabs for indentation.
- `@Slf4j` (Lombok) for logging — `log.info(…)` preferred over `System.out.println`.
- Plugin packages are flat (no sub-packages unless the plugin is large).
- Tests go in the matching `src/test/java/…` path.
