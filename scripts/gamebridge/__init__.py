"""
GameBridge Python client — connects to the RuneLite TCP bridge and drives
game automation routines using realistic human-emulated input.

Architecture
────────────
  client.py          TCP socket → raw tick messages
  state/             In-memory game world model
  human/             Human behaviour model (timing, precision, fatigue)
  input/             Hardware-level mouse/keyboard (Windows ctypes SendInput)
  controller/        High-level game actions (click entity, type, wait)
  decision/          Drives a Routine each tick
  routines/          State-machine routines; add your own under routines/

Quick start
-----------
  python -m scripts.gamebridge.main --routine iron_mining
"""
