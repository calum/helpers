"""
GameBridge client entry point.

Modes
─────
    --dashboard   Full TUI dashboard (default — recommended)
    --watch       Print one line per tick, no routine, no input
    --routine X   Headless automation — run a routine without the dashboard

Examples
────────
    python -m scripts.gamebridge.main
    python -m scripts.gamebridge.main --dashboard
    python -m scripts.gamebridge.main --watch
    python -m scripts.gamebridge.main --routine iron_mining
    python -m scripts.gamebridge.main --routine iron_mining --port 7071
    python -m scripts.gamebridge.main --debug
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_LOG_FILE = Path.home() / ".gamebridge" / "gamebridge.log"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATEFMT = "%H:%M:%S"


def _configure_logging(debug: bool = False) -> None:
    """Set up console (INFO) and optional file (DEBUG) handlers on the root logger."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
    root.addHandler(console)

    if debug:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
        root.addHandler(fh)
        log.debug("Debug logging enabled → %s", _LOG_FILE)


def main() -> None:
    parser = argparse.ArgumentParser(description="GameBridge Python client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7070)
    parser.add_argument(
        "--debug",
        action="store_true",
        help=f"Enable DEBUG-level logging to {_LOG_FILE}",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dashboard",
        action="store_true",
        default=True,
        help="Launch the TUI dashboard (default)",
    )
    mode.add_argument(
        "--watch",
        action="store_true",
        help="Print game state each tick to stdout; no routine, no input",
    )
    mode.add_argument(
        "--routine",
        metavar="NAME",
        help="Run a routine headlessly (no dashboard)",
    )

    args = parser.parse_args()

    _configure_logging(debug=args.debug)

    # ── Dashboard (default) ──────────────────────────────────────────
    if not args.watch and not args.routine:
        from .dashboard import run as run_dashboard
        run_dashboard(host=args.host, port=args.port)
        return

    if args.watch:
        from .client import stream
        log.info("Watch mode — press Ctrl-C to stop.")
        try:
            for msg in stream(host=args.host, port=args.port):
                p = msg.get("player", {})
                print(
                    f"tick={msg['tick']:7d}  "
                    f"({p.get('worldX')},{p.get('worldY')})  "
                    f"hp={p.get('hp')}  anim={p.get('animation')}  "
                    f"npcs={len(msg.get('npcs', []))}  "
                    f"objs={len(msg.get('objects', []))}"
                )
        except KeyboardInterrupt:
            log.info("Stopped.")
        return

    # ── Headless routine mode ────────────────────────────────────────
    from .client import stream
    from .human.emulator import HumanEmulator
    from .human.mood import WeatherMoodSeeder
    from .human.interruptions import InterruptionScheduler, build_configs_from_settings
    from .controller.controller import GameController
    from .decision.engine import DecisionEngine
    from .routines.examples.iron_mining import IronMiningRoutine
    from . import settings as _settings

    ROUTINES = {
        "iron_mining": IronMiningRoutine,
    }

    if args.routine not in ROUTINES:
        parser.error(f"Unknown routine '{args.routine}'. Choices: {list(ROUTINES)}")

    hb = _settings.get("human_behaviour") or {}
    location = hb.get("weather_location", "auto")
    mood_profile = WeatherMoodSeeder().seed(location=location)

    human = HumanEmulator()
    human.apply_mood(mood_profile)
    log.info("Session mood: %s (cold_hands=%s)", mood_profile.mood.value, mood_profile.cold_hands)

    interruptions_enabled = hb.get("enable_interruptions", True)
    configs = build_configs_from_settings(hb.get("interruptions", {}))
    scheduler = InterruptionScheduler(configs=configs) if interruptions_enabled else None
    if scheduler is not None and mood_profile.cold_hands:
        scheduler.prime_cold_hands(mood_profile.cold_hands_duration_s)

    ctrl = GameController(human=human)

    if not ctrl.refresh_window():
        log.error("RuneLite window not found. Launch the client first.")
        sys.exit(1)

    engine = DecisionEngine(ctrl=ctrl, human=human, scheduler=scheduler)
    engine.set_routine(ROUTINES[args.routine]())
    log.info("Running '%s' headlessly — Ctrl-C to stop.", args.routine)

    try:
        for msg in stream(host=args.host, port=args.port):
            engine.process_tick(msg)
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
