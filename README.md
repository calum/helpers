![](https://runelite.net/img/logo.png)

# RuneLite Helpers — Custom Plugin Fork

A personal fork of [RuneLite](https://runelite.net/) for writing small,
focused custom plugins: testing new game content, QA/assistive tooling,
event and object loggers, overlays. Built and deployed to a real Jagex
Launcher install so plugins run against the live game client.

## Project Structure

| Component | Location | Purpose |
|---|---|---|
| **RuneLite Client** | `runelite-api/`, `runelite-client/` | Java; forked from RuneLite. Compiled to a custom jar and deployed to the Jagex Launcher. |
| **Example helper plugin** | `runelite-client/…/plugins/helperexample/` | Minimal reference plugin — copy this package to start a new helper. |

## Quick Start

### Prerequisites

- Windows with a JDK (pinned via `mise.toml` to Temurin 11)
- Jagex Launcher with RuneLite installed

### Build & deploy

```powershell
# Build and deploy the custom client to the Jagex Launcher
mise run full-build

# Run tests
mise run test

# Development build (does not update gradle.properties version)
mise exec -- ./gradlew.bat :client:shadowJar
```

After `mise run full-build`, launch RuneLite as normal via the Jagex
Launcher — no extra steps needed.

## Writing a new plugin

1. Copy `runelite-client/src/main/java/net/runelite/client/plugins/helperexample/` to a new package under `runelite-client/src/main/java/net/runelite/client/plugins/<name>/`.
2. Rename the class, update `@PluginDescriptor`, and change the event subscriptions/logic for what you need.
3. Plugins are auto-discovered via classpath scanning — no registration step required.
4. Add a matching test under `runelite-client/src/test/java/net/runelite/client/plugins/<name>/`.
5. Build and deploy with `mise run full-build`, then enable the plugin from the in-game Plugins panel.

See [CLAUDE.md](CLAUDE.md) for the full plugin-system rundown (event bus,
DI, plugin skeleton) and [ARCHITECTURE.md](ARCHITECTURE.md) for how the
Jagex Launcher integration and build/deploy pipeline actually work
under the hood.

## Conventions

- BSD 2-clause license header on every `.java` file.
- Allman braces, tabs for indentation.
- `@Slf4j` (Lombok) for logging — `log.info(…)` preferred over `System.out.println`.
- Plugin packages are flat (no sub-packages unless the plugin is large).
- Tests go in the matching `src/test/java/…` path; every new public method/behaviour needs a test.

## Resources

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — RuneLite internals: plugin system, event bus, mixins, Jagex Launcher integration, build pipeline
- **[CLAUDE.md](CLAUDE.md)** — Development notes, working methodology, conventions
- **[PLAN.md](PLAN.md)** — Living research/session log

## License

RuneLite is licensed under the BSD 2-clause license. See the license header in each `.java` file.

## Development

Join the upstream [Discord](https://runelite.net/discord) for general RuneLite questions or discussion.
