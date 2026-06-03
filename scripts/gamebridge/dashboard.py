"""
GameBridge TUI Dashboard — Textual app.

Shows a live model of the game world, controls routines, and provides a
scrollable debug log of every incoming tick.

Usage
-----
    python -m scripts.gamebridge.dashboard
    python -m scripts.gamebridge.main --dashboard
"""
from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Optional, Type

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from .client import stream as tcp_stream
from .state.game_state import GameState
from .human.emulator import HumanEmulator
from .controller.controller import GameController
from .decision.engine import DecisionEngine
from .routines.base import Routine
from .routines.examples.iron_mining import IronMiningRoutine

# Registry — add new routines here and they appear in the dropdown automatically
ROUTINES: dict[str, Type[Routine]] = {
    "iron_mining": IronMiningRoutine,
}

# ------------------------------------------------------------------ #
# Rendering helpers
# ------------------------------------------------------------------ #

_MINIMAP_R = 7  # tiles radius; yields a 15×15 grid


def _minimap(game: GameState) -> str:
    """
    ASCII minimap centred on the player.
    Uses Rich markup for colour; rendered inside a Static widget.

    Coordinate system: RS y+ = north → map row decrements as worldY increases.
    """
    px, py = game.player_pos
    r = _MINIMAP_R
    size = r * 2 + 1
    grid: list[list[str]] = [["[dim]·[/]"] * size for _ in range(size)]

    for obj in game.objects:
        dc, dr = obj["worldX"] - px, py - obj["worldY"]
        c, row = r + dc, r + dr
        if 0 <= c < size and 0 <= row < size:
            grid[row][c] = "[yellow]O[/]"

    for npc in game.npcs:
        dc, dr = npc["worldX"] - px, py - npc["worldY"]
        c, row = r + dc, r + dr
        if 0 <= c < size and 0 <= row < size:
            grid[row][c] = "[bold red]N[/]" if npc.get("onScreen") else "[dim red]n[/]"

    grid[r][r] = "[bold green]@[/]"
    return "\n".join(" ".join(cells) for cells in grid)


def _hms(seconds: float) -> str:
    td = timedelta(seconds=int(max(0.0, seconds)))
    h = td.seconds // 3600
    m = (td.seconds % 3600) // 60
    s = td.seconds % 60
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m:02d}m{s:02d}s"


def _fatigue_bar(f: float, w: int = 12) -> str:
    filled = round(f * w)
    return "[green]" + "█" * filled + "[/][dim]" + "░" * (w - filled) + "[/]"


def _yaw_dir(yaw: int) -> str:
    for threshold, label in [(64, "N"), (192, "NE"), (320, "E"), (448, "SE"),
                              (576, "S"), (704, "SW"), (832, "W"), (960, "NW"),
                              (1088, "N"), (1216, "NE"), (1344, "E"), (1472, "SE"),
                              (1600, "S"), (1728, "SW"), (1856, "W"), (1984, "NW"),
                              (2048, "N")]:
        if yaw < threshold:
            return label
    return "N"


# ------------------------------------------------------------------ #
# App
# ------------------------------------------------------------------ #

class GameBridgeApp(App[None]):
    """Live TUI dashboard for the GameBridge RuneLite plugin."""

    TITLE = "GameBridge"

    CSS = """
    Screen {
        layout: horizontal;
    }

    /* ---- Left column ---- */

    #left {
        width: 46;
        height: 100%;
    }

    .panel {
        height: auto;
        border: round $primary-darken-3;
        padding: 0 1 1 1;
        margin: 0 0 1 0;
    }

    .panel-title {
        text-style: bold;
        color: $primary-lighten-1;
        padding: 0;
        margin: 0 0 0 0;
    }

    /* ---- Right column ---- */

    #right {
        width: 1fr;
        height: 100%;
    }

    #control-panel {
        height: auto;
        border: round $accent-darken-2;
        padding: 0 1 1 1;
        margin: 0 0 1 0;
    }

    #control-title {
        text-style: bold;
        color: $accent-lighten-1;
    }

    #routine-select {
        width: 1fr;
        margin: 1 0 0 0;
    }

    #routine-state-label {
        margin: 0 0 1 0;
        height: 1;
    }

    .btn-row {
        height: 3;
    }

    #btn-start { width: 12; margin-right: 1; }
    #btn-stop  { width: 12; margin-right: 1; }
    #btn-reset { width: 12; }

    #session-stats {
        color: $text-muted;
        margin-top: 1;
    }

    #nearby-tabs {
        height: 1fr;
        min-height: 12;
        border: round $primary-darken-3;
        margin: 0 0 1 0;
    }

    #debug-log {
        height: 11;
        border: round $warning-darken-3;
    }

    #debug-log.hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("d",   "toggle_debug",   "Debug",  show=True),
        Binding("s",   "start_routine",  "Start",  show=True),
        Binding("x",   "stop_routine",   "Stop",   show=True),
        Binding("r",   "reset_routine",  "Reset",  show=False),
        Binding("q",   "quit",           "Quit",   show=True),
    ]

    def __init__(self, host: str = "127.0.0.1", port: int = 7070):
        super().__init__()
        self._host = host
        self._port = port
        self._human = HumanEmulator()
        self._ctrl = GameController(human=self._human)
        self._engine = DecisionEngine(ctrl=self._ctrl, human=self._human)
        self._session_start = time.monotonic()
        self._connected = False
        self._debug_on = True
        self._last_tick = 0

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal():

            # ── Left column ──────────────────────────────────────────
            with VerticalScroll(id="left"):

                with Vertical(classes="panel"):
                    yield Label("PLAYER", classes="panel-title")
                    yield Static("—", id="player-stats")

                with Vertical(classes="panel"):
                    yield Label(
                        "MINIMAP   [bold green]@[/]=you  [bold red]N[/]=npc(visible)  "
                        "[dim red]n[/]=npc  [yellow]O[/]=object",
                        classes="panel-title",
                        markup=True,
                    )
                    yield Static("", id="minimap-text")

                with Vertical(classes="panel"):
                    yield Label("INVENTORY", classes="panel-title")
                    yield Static("—", id="inventory-text")

                with Vertical(classes="panel"):
                    yield Label("CAMERA", classes="panel-title")
                    yield Static("—", id="camera-text")

            # ── Right column ─────────────────────────────────────────
            with Vertical(id="right"):

                # Routine control
                with Vertical(id="control-panel"):
                    yield Label("ROUTINE CONTROL", id="control-title")
                    yield Select(
                        [(k.replace("_", " ").title(), k) for k in ROUTINES],
                        id="routine-select",
                        allow_blank=False,
                        value=next(iter(ROUTINES)),
                    )
                    yield Static("State: —", id="routine-state-label")
                    with Horizontal(classes="btn-row"):
                        yield Button("▶ Start", id="btn-start", variant="success")
                        yield Button("■ Stop",  id="btn-stop",  variant="error")
                        yield Button("↺ Reset", id="btn-reset")
                    yield Static("", id="session-stats")

                # Nearby entities
                with TabbedContent(id="nearby-tabs"):
                    with TabPane("NPCs", id="tab-npcs"):
                        t = DataTable(id="npc-table", zebra_stripes=True)
                        t.add_columns("Name", "Lvl", "Pos", "Dist", "⊙")
                        yield t
                    with TabPane("Objects", id="tab-objects"):
                        t = DataTable(id="obj-table", zebra_stripes=True)
                        t.add_columns("Name", "Pos", "Dist", "⊙")
                        yield t
                    with TabPane("Skills/XP", id="tab-xp"):
                        t = DataTable(id="xp-table", zebra_stripes=True)
                        t.add_columns("Skill", "Lvl", "Boosted", "XP")
                        yield t

                # Debug log (toggle with 'd')
                yield RichLog(
                    id="debug-log",
                    highlight=True,
                    markup=True,
                    max_lines=500,
                )

        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self.sub_title = "○ Disconnected"
        threading.Thread(target=self._background_loop, daemon=True).start()
        self.set_interval(1.0, self._update_session_panel)

    # ------------------------------------------------------------------
    # Background thread — TCP read + engine execution
    # ------------------------------------------------------------------

    def _background_loop(self) -> None:
        """
        Daemon thread.  Reads every tick message from the GameBridge plugin,
        runs the engine (which may perform hardware input actions), then
        schedules a UI refresh on the main thread.
        """
        for msg in tcp_stream(host=self._host, port=self._port):
            if not self._connected:
                self._connected = True
                self.call_from_thread(self._on_connected)

            try:
                self._engine.process_tick(msg)
            except Exception:
                pass  # logged by engine

            self.call_from_thread(self._refresh_ui, dict(msg))

    # ------------------------------------------------------------------
    # UI refresh (main thread)
    # ------------------------------------------------------------------

    def _on_connected(self) -> None:
        self.sub_title = "● Connected"

    def _refresh_ui(self, raw: dict) -> None:
        g = self._engine.game
        tick = raw.get("tick", self._last_tick)
        self._last_tick = tick
        self.title = f"GameBridge   tick {tick:,}"

        # Player
        p = g.player
        if p:
            px, py = g.player_pos
            anim = p.get("animation", -1)
            interacting = (
                f"\n[dim]→ {g.interacting_with}[/dim]" if g.interacting_with else ""
            )
            self.query_one("#player-stats", Static).update(
                f"[bold]{p.get('name', '—')}[/bold]\n"
                f"Pos    ({px}, {py})   plane {g.plane}\n"
                f"HP     {p.get('hp', '—')}      Prayer  {p.get('prayer', '—')}\n"
                f"Anim   {'idle' if anim == -1 else anim}"
                + interacting
            )
            self.query_one("#minimap-text", Static).update(_minimap(g))

        # Inventory
        filled = [s for s in g.inventory if s["itemId"] != -1]
        free = g.inventory_free_slots()
        if filled:
            lines = [
                f"slot {s['slot']:2d}  id {s['itemId']:6d}  ×{s['qty']}"
                for s in filled[:12]
            ]
            more = f"\n[dim]… {len(filled)-12} more[/dim]" if len(filled) > 12 else ""
            self.query_one("#inventory-text", Static).update(
                "\n".join(lines) + more + f"\n[dim]{free}/28 free slots[/dim]"
            )
        else:
            self.query_one("#inventory-text", Static).update(
                f"[dim]empty — {free}/28 free[/dim]"
            )

        # Camera
        cam = g.camera
        if cam:
            yaw = cam.get("yaw", 0)
            self.query_one("#camera-text", Static).update(
                f"Yaw   {yaw:4d}  ({_yaw_dir(yaw)})\n"
                f"Pitch {cam.get('pitch', '—')}\n"
                f"Pos   ({cam.get('x','—')}, {cam.get('y','—')}, {cam.get('z','—')})"
            )

        # Routine state label
        rout = self._engine.routine
        if rout:
            if self._engine.on_break:
                label = f"[yellow]⏸ break  {_hms(self._engine.break_remaining)}[/yellow]"
            else:
                label = f"[green]{rout.current_state}[/green]"
            self.query_one("#routine-state-label", Static).update(f"State: {label}")

        # NPC table
        nt = self.query_one("#npc-table", DataTable)
        nt.clear()
        for npc in sorted(g.npcs, key=lambda n: g.distance_to(n))[:30]:
            nt.add_row(
                npc.get("name", "?"),
                str(npc.get("combatLevel", "—")),
                f"{npc['worldX']},{npc['worldY']}",
                str(g.distance_to(npc)),
                "✓" if npc.get("onScreen") else " ",
            )

        # Object table
        ot = self.query_one("#obj-table", DataTable)
        ot.clear()
        for obj in sorted(g.objects, key=lambda o: g.distance_to(o))[:30]:
            ot.add_row(
                obj.get("name", "?"),
                f"{obj['worldX']},{obj['worldY']}",
                str(g.distance_to(obj)),
                "✓" if obj.get("onScreen") else " ",
            )

        # XP table
        if g.xp:
            xt = self.query_one("#xp-table", DataTable)
            xt.clear()
            for skill in sorted(g.xp):
                xt.add_row(
                    skill,
                    str(g.levels.get(skill, "—")),
                    str(g.boosted_levels.get(skill, "—")),
                    f"{g.xp[skill]:,}",
                )

        # Debug log
        if self._debug_on:
            events = raw.get("events", [])
            ev_parts = []
            for e in events:
                t = e["type"]
                if t == "xp":
                    ev_parts.append(f"[cyan]{t}[/]:{e['skill']}+{e.get('xp',0):,}")
                elif t == "container":
                    ev_parts.append(f"[magenta]{t}[/]:{e.get('containerId')}")
                elif t == "chat":
                    ev_parts.append(f"[yellow]{t}[/]:{e.get('message','')[:30]}")
                else:
                    ev_parts.append(f"[dim]{t}[/]")
            ev_str = "  " + "  ".join(ev_parts) if ev_parts else ""
            self.query_one("#debug-log", RichLog).write(
                f"[dim]{tick:7,}[/]  "
                f"({g.player_pos[0]},{g.player_pos[1]})  "
                f"npcs={len(g.npcs)}  objs={len(g.objects)}"
                + ev_str
            )

    def _update_session_panel(self) -> None:
        """Runs every second to update the session timer and fatigue bar."""
        elapsed = time.monotonic() - self._session_start
        f = self._human.fatigue
        break_line = (
            f"[yellow]⏸ break — {_hms(self._engine.break_remaining)} remaining[/yellow]"
            if self._engine.on_break
            else "[dim]no break active[/dim]"
        )
        self.query_one("#session-stats", Static).update(
            f"Session  {_hms(elapsed)}\n"
            f"Fatigue  {_fatigue_bar(f)}  {int(f*100)}%\n"
            + break_line
        )

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    @on(Button.Pressed, "#btn-start")
    def _on_start_btn(self) -> None:
        self.action_start_routine()

    @on(Button.Pressed, "#btn-stop")
    def _on_stop_btn(self) -> None:
        self.action_stop_routine()

    @on(Button.Pressed, "#btn-reset")
    def _on_reset_btn(self) -> None:
        self.action_reset_routine()

    # ------------------------------------------------------------------
    # Bound actions
    # ------------------------------------------------------------------

    def action_start_routine(self) -> None:
        sel = self.query_one("#routine-select", Select)
        name = sel.value
        if not isinstance(name, str) or name not in ROUTINES:
            self.notify("Select a routine first.", severity="warning")
            return
        if not self._ctrl.refresh_window():
            self.notify("RuneLite window not found — launch the client first.", severity="error")
            return
        self._engine.set_routine(ROUTINES[name]())
        self.notify(f"Started: {name.replace('_', ' ').title()}", severity="information")

    def action_stop_routine(self) -> None:
        self._engine.stop()
        self.query_one("#routine-state-label", Static).update("State: [dim]—[/dim]")
        self.notify("Routine stopped.", severity="warning")

    def action_reset_routine(self) -> None:
        if self._engine.routine:
            self._engine.routine.reset()
            self.notify("Routine reset to initial state.")

    def action_toggle_debug(self) -> None:
        self._debug_on = not self._debug_on
        log_w = self.query_one("#debug-log", RichLog)
        if self._debug_on:
            log_w.remove_class("hidden")
        else:
            log_w.add_class("hidden")
        self.notify(f"Debug log {'shown' if self._debug_on else 'hidden'}.")


# Allow running as a script: python -m scripts.gamebridge.dashboard
if __name__ == "__main__":
    GameBridgeApp().run()
