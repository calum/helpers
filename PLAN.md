# Understand the Runelite Game Client

This is an experiment to understand how the game client works.

My ultimate goal is to be able to add a simple hook to runelite and then build the client and hook it up to the Jagex Launcher so that it runs by default. The hook would simply log an event to console to prove that I have succeeded. For example, the event could simply be that a new object of name 'Tree' has appeared.

---

## Status: Plugin Written — Ready to Build & Test

### Findings (2026-06-03)

**Project layout**

| Module | Path | Purpose |
|---|---|---|
| `runelite-api` | `runelite-api/` | Java interfaces mirroring the RS game engine. No implementation — real classes injected at runtime via Mixins. |
| `runelite-client` | `runelite-client/` | Desktop application. Plugins, UI, event bus, config system. |
| `cache` | `cache/` | Cache reading utilities. Not needed for this task. |
| `runelite-gradle-plugin` | `runelite-gradle-plugin/` | Build plugin. Not needed for this task. |

Build system: Gradle composite build. Entry point: `./gradlew.bat`. Run: `./gradlew.bat :client:run`.

**Plugin system**

- All plugins extend `net.runelite.client.plugins.Plugin` and are annotated `@PluginDescriptor(name="…")`.
- Plugins live in `runelite-client/…/client/plugins/<name>/`.
- Dependency injection via Guice — `@Inject` for `Client`, `ConfigManager`, etc.
- Event subscriptions via `@Subscribe` on methods (e.g. `onGameObjectSpawned`).
- ~137 built-in plugins already in the `plugins/` directory.
- **PluginManager uses classpath scanning** — new plugin classes in the right package are auto-discovered at startup. No explicit registration needed.
  - Key file: `runelite-client/src/main/java/net/runelite/client/plugins/PluginManager.java`

**Event bus**

- API-level game events: `runelite-api/…/api/events/` — includes `GameObjectSpawned`, `GameObjectDespawned`, `NpcSpawned`, `GameTick`, `StatChanged`, and many more.
- Client-level events: `runelite-client/…/client/events/` — `ConfigChanged`, `PluginChanged`, etc.

**Event flow (detailed)**

```
Jagex game binary → Callbacks.java (interface in runelite-api/hooks/)
                  → Hooks.java (implementation, runelite-client/callback/)
                  → EventBus.post()
                  → all @Subscribe methods on all registered plugins
```

Key files:
- `runelite-api/src/main/java/net/runelite/api/hooks/Callbacks.java` — interface the game binary calls
- `runelite-client/src/main/java/net/runelite/client/callback/Hooks.java` — implements Callbacks, posts to EventBus
- `runelite-client/src/main/java/net/runelite/client/eventbus/EventBus.java` — core dispatch

**Mixins/byte-code weaving**

- Mixins are NOT present in this repo. The game client binary (downloaded from Jagex at runtime by `ClientLoader`) has the mixin hooks woven in. We cannot modify the mixin layer from this repo.
- `runelite-client/src/main/java/net/runelite/client/rs/ClientLoader.java` — downloads the game client from Jagex servers each run.

**Relevant events for our hook**

- `GameObjectSpawned` — fired when any world object appears (trees, rocks, doors, etc.)
- `GameObjectDespawned` — fired when removed
- `ObjectComposition` — resolved via `client.getObjectDefinition(id)`, provides `.getName()`

**Minimal plugin pattern** (see `ChatFilterPlugin.java` as a reference)

```java
@PluginDescriptor(name = "Tree Logger", enabledByDefault = true)
public class TreeLoggerPlugin extends Plugin {
    @Inject private Client client;

    @Subscribe
    public void onGameObjectSpawned(GameObjectSpawned event) {
        ObjectComposition comp = client.getObjectDefinition(event.getGameObject().getId());
        if ("Tree".equals(comp.getName())) {
            log.info("Tree spawned at {}", event.getGameObject().getWorldLocation());
        }
    }
}
```

Use `@Slf4j` (Lombok) rather than `System.out.println` — Lombok is available in the project.

**Coding conventions observed**

- BSD 2-clause license header on every `.java` file.
- Allman brace style (opening `{` on its own line for methods/classes).
- Tabs for indentation.
- No comments unless non-obvious.

---

### Findings (2026-06-03) — Deeper Research

**Q1: Is the plugin system the best injection point?**

Yes — the plugin system is the correct and cleanest approach. Alternatives are either impossible or require invasive changes:

1. **Mixin layer** — Not in this repo. The woven hooks live in the Jagex game binary downloaded by `ClientLoader`. Cannot be modified from here.
2. **Hooks.java directly** — Could register a subscriber on the raw `EventBus` by modifying `RuneLite.java` startup, but this is strictly worse than a plugin: loses DI, config, enable/disable lifecycle, and requires modifying core startup code.
3. **Scene iteration (GameEventManager style)** — `runelite-client/…/util/GameEventManager.java` iterates tiles and re-fires events for catch-up when a plugin loads, but this is not a real-time hook.
4. **Plugin (recommended)** — Classpath scanning auto-discovers any class annotated `@PluginDescriptor` in `net.runelite.client.plugins.*`. Drop in a new package, no registration needed.

**Q2: Are there integrity checks?**

No significant checks exist within RuneLite itself. A custom build runs freely.

| Check | Present? | Detail |
|---|---|---|
| Jar signature verification | No | Nothing in `RuneLite.java` or startup verifies the jar |
| SHA/hash check on client | No | `Updater.java` checksums only apply to `RuneLiteSetup.exe` (the launcher installer), not the client jar |
| Version blacklist | Soft only | `RuntimeConfig` fetches `https://static.runelite.net/config.json`; `outdatedClientVersions` field shows an error message but does not prevent startup. Can be overridden with `-Drunelite.rtconf=<local-file>` |
| Launcher version tracking | Yes (benign) | System property `runelite.launcher.version` is logged and used to decide when to offer launcher upgrades — not an integrity gate |
| Auto-update (client) | No | RuneLite does not self-update the client jar. Only the launcher executable (`RuneLite.exe`) is updated by `Updater.java` |

Key files:
- `runelite-client/src/main/java/net/runelite/client/Updater.java` — launcher update logic (checksums only for launcher exe)
- `runelite-client/src/main/java/net/runelite/client/RuneLiteProperties.java` — properties loading, launcher version property
- `runelite-client/src/main/java/net/runelite/client/RuntimeConfig.java` — server-side config with version blacklist field
- `runelite-client/src/main/resources/net/runelite/client/runelite.properties` — URLs and display strings only

**Unknown: Jagex Launcher behaviour**

The Jagex Launcher (RuneLite.exe) is a separate binary not in this repo. Whether it performs its own hash check on the RuneLite jar before launching it is unknown. Two likely scenarios:
- It simply passes `-jar <path>` to the JVM — no hash check.
- It stores a hash of the expected jar alongside it, rejecting mismatches.

This is the one open question that requires either empirical testing (replace the jar and see if the launcher runs) or inspecting the launcher binary.

---

## Build & Test Commands

All Gradle commands must be prefixed with `mise exec --` so the correct JDK (Temurin 11, pinned in `mise.toml`) is used. The Gradle wrapper (`.\gradlew.bat`) is used directly — no separate Gradle install needed.

```powershell
# Run all unit tests across all subprojects
mise exec -- .\gradlew.bat testAll

# Build a fat/shadow jar (output: runelite-client/build/libs/client-<version>-shaded.jar)
mise exec -- .\gradlew.bat :client:shadowJar

# Build everything (all subprojects, including shadow jar)
mise exec -- .\gradlew.bat assembleAll

# Run the client directly (no Gradle 'run' task exists — must build then launch manually)
mise exec -- .\gradlew.bat :client:shadowJar
mise exec -- java -jar runelite-client\build\libs\client-<version>-shaded.jar

# Clean all build outputs
mise exec -- .\gradlew.bat cleanAll
```

> **Note on `:client:run`:** The application plugin is not applied in `runelite-client/build.gradle.kts`, so no `run` task exists. The shadow jar has `Main-Class = net.runelite.client.RuneLite` set in its manifest, so launching it directly with `java -jar` is the correct approach.

> **Note:** `mise.toml` at the repo root pins `java = "temurin-11"`. Running `mise install` in the repo root installs it. Tests pass with this configuration (verified 2026-06-03, BUILD SUCCESSFUL in ~2m 23s).

---

## Installed RuneLite Location

The current official RuneLite installation lives at:

```
C:\Users\Calum\AppData\Local\RuneLite\
├── RuneLite.exe          # Jagex Launcher / native wrapper
├── RuneLite.jar          # The actual RuneLite client jar (~2.4 MB)
├── launcher_amd64.dll    # Native launcher DLL
├── jre\                  # Bundled JRE used by the launcher
├── config.json           # Launcher configuration
├── settings.json         # RuneLite user settings
├── install_id.txt
├── unins000.exe
└── unins000.dat
```

`RuneLite.jar` is the artifact to replace when testing a custom build. The launcher (`RuneLite.exe`) invokes `jre\bin\java.exe -jar RuneLite.jar` (or similar) — whether it validates the jar hash before doing so is still an open question.

---

## Plugin Implementation (2026-06-03)

Plugin written at:
- `runelite-client/src/main/java/net/runelite/client/plugins/objectlogger/ObjectLoggerPlugin.java`
- `runelite-client/src/main/java/net/runelite/client/plugins/objectlogger/ObjectLoggerConfig.java`

**Design decisions:**

- Generic object logger (not tree-specific) — tracks any named object.
- Uses `client.getObjectDefinition(id).getName()` to resolve names. Follows the impostor chain (`getImpostor()`) so varbit-dependent objects (e.g. doors) show their contextual name rather than the base object name.
- Appends to a log file (default: `~/.runelite/object-logger.log`). Relative paths are resolved against `runeLiteDir` (injected via `@Named("runeLiteDir")`). Absolute paths are used as-is.
- `trackedObjects` config: comma-separated list of names (case-insensitive). Empty = log all objects.
- `logDespawns` config: boolean toggle, default off.
- `enabledByDefault = false` — must be manually enabled in the Plugins panel to avoid flooding the log.
- Log line format: `[yyyy-MM-dd HH:mm:ss] SPAWN id=<id> name="<name>" location=WorldPoint{x=…,y=…,plane=…}`
- Plugin is auto-discovered by classpath scanning — no registration needed.

**Key API facts confirmed:**
- `GameObject` extends `TileObject`, which provides `getWorldLocation()` returning `WorldPoint`.
- `ObjectComposition.getName()` returns the display name string.
- `runeLiteDir` binding: `RuneLiteModule` binds `File` annotated `@Named("runeLiteDir")` to `RuneLite.RUNELITE_DIR` (`~/.runelite`).

---

## Next Steps

1. ~~**Write the plugin**~~ — Done. See `objectlogger/` package above.
2. ~~**Build the client**~~ — Done. `mise exec -- .\gradlew.bat :client:shadowJar` produces `runelite-client\build\libs\client-<version>-shaded.jar`.
3. ~~**Test with direct jar launch**~~ — Done. `mise exec -- java -jar runelite-client\build\libs\client-<version>-shaded.jar` confirmed working (2026-06-03).
4. **Jagex Launcher integration** — Locate where the launcher stores the RuneLite jar on disk and attempt to replace it. Observe whether the launcher validates the jar or simply runs it.

---

## Open Questions

- Does the Jagex Launcher perform a hash check on the RuneLite jar before starting it? (Empirical test needed: replace the jar and see if it runs.)
- Where on disk does the Jagex Launcher store the RuneLite jar? (Likely `%LOCALAPPDATA%\RuneLite\` or similar.)
- Does the launcher re-download RuneLite on every launch, which would overwrite a custom jar?
