# RuneLite Client — CLAUDE.md

## Testing Requirements

Every code change — bug fix, new feature, or refactor — must include new or updated tests. A change is not complete until the relevant tests pass.

**Rules:**
- Any new public method, function, or behaviour gets at least one test covering the happy path and one covering each failure/edge case.
- Any modified behaviour must have its existing tests updated to match and new tests added for the changed logic.
- Tests must pass locally before considering the task done. Run with:
  ```powershell
  ./gradlew.bat :runelite-client:test
  ```
- Do not skip or comment out failing tests to make the suite green — fix the code or the test.
- Test the actual behaviour, not implementation details: assert on observable outputs (return values, logged messages, mock call counts/args), not on internal state.

---

## Working Methodology — Research, Plan, Execute, Review

Distilled from the old RIPER-5 protocol (now removed — its rigid `[MODE: ...]`
declarations and transition commands were never actually used in practice, but
the underlying discipline is worth keeping as a lightweight checklist):

1. **Research first.** Before proposing or making a change, read the relevant
   source, understand existing patterns, and identify dependencies — especially
   for legacy/unfamiliar code. Don't skip straight to an implementation guess.
2. **Plan before large changes.** For anything non-trivial (new subsystems,
   refactors touching multiple files, architectural decisions), sketch the
   concrete steps — exact files, functions, and the shape of the change —
   before writing code. Small, obvious fixes don't need this ceremony.
3. **Execute the plan**, but don't be afraid to stop and re-plan if you hit
   something the research missed — never paper over a wrong assumption with a
   quick hack.
4. **Review afterward.** Run the tests (see Testing Requirements above),
   re-read the diff against the original goal, and note any deviations or
   follow-ups. This is what feeds the "Open / next steps" section of `PLAN.md`.

This mirrors the structure each `PLAN.md` session entry already follows
(Goal → Findings/Decisions → Tests → Open/next steps) — keep using that shape.

## Research Protocol

After any research session (reading source files, exploring the codebase, investigating APIs), update `PLAN.md` with new findings. Add concrete details: file paths, class names, how mechanisms work, open questions, and next steps. Keep `PLAN.md` as a living document that accumulates knowledge across sessions.

---

## Goal

This is a personal RuneLite fork for writing small, focused custom plugins —
testing new game content, assistive QA tooling, event/object loggers,
overlays. There's no bot or automation layer here. When starting a new
plugin, copy the pattern from `runelite-client/…/plugins/helperexample/`
(see below).

---

## Project Layout

| Module | Path | Purpose |
|---|---|---|
| `runelite-api` | `runelite-api/` | Java interfaces that mirror the RS game engine. No implementation; injected at runtime by Mixins. |
| `runelite-client` | `runelite-client/` | The actual desktop application. Contains plugins, UI, event bus, config system. |
| `cache` | `cache/` | Cache-reading utilities. Not needed for plugin work. |
| `runelite-gradle-plugin` | `runelite-gradle-plugin/` | Gradle plugin used by the build. Not needed for plugin work. |

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

This is essentially what `runelite-client/…/plugins/helperexample/HelperExamplePlugin.java`
does (with `log.info` instead of `System.out.println`, per the logging
convention below, and the name-match logic pulled into a testable static
method) — copy that package as the starting point for a new plugin.

### How the Game Client starts

Entry point: `RuneLite.java` — sets up Guice, loads `RuneLiteModule`, discovers plugins via classpath scanning, then starts the game loop.

### API vs Implementation

`runelite-api` only contains **interfaces** (e.g. `Client.java`, `GameObject.java`). The real game classes that implement them are injected by the RS client at runtime via **Mixins** (byte-code weaving). You never instantiate these yourself.

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

Or use `mise run full-build` for the one-command version — see [ARCHITECTURE.md](ARCHITECTURE.md) for full details, including the reverse-engineered Jagex Launcher findings.

---

## Conventions Observed in This Codebase

- BSD 2-clause license header on every `.java` file.
- Allman brace style.
- Tabs for indentation.
- `@Slf4j` (Lombok) for logging — `log.info(…)` preferred over `System.out.println`.
- Plugin packages are flat (no sub-packages unless the plugin is large).
- Tests go in the matching `src/test/java/…` path.
