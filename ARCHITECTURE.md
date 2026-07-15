# RuneLite Internals — Architecture & Developer Guide

**Status:** Reference document. This fork is used to write small custom
RuneLite plugins for personal use (testing new game content, assistive
tools). This file captures how the underlying client actually works —
including several things reverse-engineered along the way that aren't
documented upstream — so that knowledge isn't lost between sessions.

---

## Purpose of this fork

A personal RuneLite build for writing lightweight helper plugins: things
like object/event loggers, overlays, and small QA aids for testing new game
content. See [`runelite-client/…/plugins/helperexample/`](runelite-client/src/main/java/net/runelite/client/plugins/helperexample/HelperExamplePlugin.java)
for the starting-point example — copy that package when starting a new
plugin.

---

## Project Layout

| Module | Path | Purpose |
|---|---|---|
| `runelite-api` | `runelite-api/` | Java interfaces mirroring the RS game engine. No implementation — real classes injected at runtime via Mixins. |
| `runelite-client` | `runelite-client/` | Desktop application. Plugins, UI, event bus, config system. |
| `cache` | `cache/` | Cache reading utilities (stock RuneLite submodule). Not needed for plugin work. |
| `runelite-gradle-plugin` | `runelite-gradle-plugin/` | Build plugin. Not needed for plugin work. |

Build system: Gradle composite build. Entry point: `.\gradlew.bat`. Version in `gradle.properties` (`project.build.version`).

---

## Plugin System

- All plugins extend `net.runelite.client.plugins.Plugin`, annotated `@PluginDescriptor(name="…")`.
- Plugins live in `runelite-client/…/client/plugins/<name>/`.
- Dependency injection via Guice — `@Inject` for `Client`, `ConfigManager`, etc.
- Event subscriptions via `@Subscribe` on methods.
- **PluginManager uses classpath scanning** — any class annotated `@PluginDescriptor` in the `net.runelite.client.plugins.*` package is auto-discovered at startup. No registration needed anywhere else (no central plugin list to edit).

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
- `GameTick` — fired once per game tick (~600 ms)
- `ObjectComposition` — resolved via `client.getObjectDefinition(id)`, provides `.getName()`

### Mixin layer

Mixins are NOT in this repo. The game client binary (downloaded from Jagex at runtime by `ClientLoader`) has the mixin hooks woven in. We cannot modify the mixin layer from this repo — `runelite-api` only contains **interfaces** (e.g. `Client.java`, `GameObject.java`); the real game classes that implement them are injected by the RS client at runtime via Mixins (byte-code weaving). You never instantiate these yourself.

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

Alternatively, bypass the launcher entirely using the bundled JRE and the shaded jar directly:
```powershell
& "C:\Users\Calum\AppData\Local\RuneLite\jre\bin\java.exe" -jar "path\to\client-<version>-shaded.jar"
```
This is confirmed working.

---

## Key Files

| File | Purpose |
|---|---|
| `runelite-client/…/plugins/helperexample/HelperExamplePlugin.java` | Starter/reference helper plugin — copy this package for new plugins |
| `runelite-client/src/main/resources/…/runelite.properties` | Version/URL config baked into the jar at build time |
| `gradle.properties` | Project version (stamped by build script before each deploy) |
| `scripts/Launcher.java` | Thin entry-point wrapper injected into the deployed jar |
| `scripts/full-build.ps1` | Full build and deploy script |
| `mise.toml` | Pins JDK to Temurin 11; defines `full-build` and `test` tasks |
| `C:\Users\Calum\AppData\Local\RuneLite\config.json` | Jagex Launcher JVM configuration (not in repo) |
| `C:\Users\Calum\AppData\Local\RuneLite\RuneLite.jar.bak` | Backup of original launcher bootstrap (not in repo) |
