# RuneLite Custom Client

## Goal

Add a plugin to RuneLite that logs game object events (e.g. Tree spawns), build a custom client, and wire it to the Jagex Launcher so it runs as the default client.

**Status: Complete.** Plugin runs, Jagex Launcher launches our custom build. `mise run full-build` handles the full deploy.

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
| `runelite-client/…/plugins/objectlogger/ObjectLoggerPlugin.java` | Our custom plugin |
| `runelite-client/…/plugins/objectlogger/ObjectLoggerConfig.java` | Plugin config interface |
| `runelite-client/src/main/resources/…/runelite.properties` | Version/URL config baked into the jar at build time |
| `gradle.properties` | Project version (stamped by build script before each deploy) |
| `scripts/Launcher.java` | Thin entry-point wrapper injected into the deployed jar |
| `scripts/full-build.ps1` | Full build and deploy script |
| `mise.toml` | Pins JDK to Temurin 11; defines `full-build` task |
| `C:\Users\Calum\AppData\Local\RuneLite\config.json` | Jagex Launcher JVM configuration (not in repo) |
| `C:\Users\Calum\AppData\Local\RuneLite\RuneLite.jar.bak` | Backup of original launcher bootstrap (not in repo) |
| `~/.runelite/object-logger.log` | Plugin output log |
