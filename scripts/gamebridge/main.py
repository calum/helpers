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
"""
from __future__ import annotations

import argparse
import logging
import sys

log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="GameBridge Python client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7070)

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

    # ── Dashboard (default) ──────────────────────────────────────────
    if not args.watch and not args.routine:
        from .dashboard import GameBridgeApp
        GameBridgeApp(host=args.host, port=args.port).run()
        return

    # ── Headless watch mode ──────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

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
    from .controller.controller import GameController
    from .decision.engine import DecisionEngine
    from .routines.examples.iron_mining import IronMiningRoutine

    ROUTINES = {
        "iron_mining": IronMiningRoutine,
    }

    if args.routine not in ROUTINES:
        parser.error(f"Unknown routine '{args.routine}'. Choices: {list(ROUTINES)}")

    human = HumanEmulator()
    ctrl = GameController(human=human)

    if not ctrl.refresh_window():
        log.error("RuneLite window not found. Launch the client first.")
        sys.exit(1)

    engine = DecisionEngine(ctrl=ctrl, human=human)
    engine.set_routine(ROUTINES[args.routine]())
    log.info("Running '%s' headlessly — Ctrl-C to stop.", args.routine)

    try:
        for msg in stream(host=args.host, port=args.port):
            engine.process_tick(msg)
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
