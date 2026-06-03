"""
Hardware mouse emulation for Windows via ctypes SendInput.

Key points
──────────
• wind_mouse() produces a realistic curved path (wind + gravity physics).
• All movement goes through SendInput with MOUSEEVENTF_ABSOLUTE, so it
  works correctly regardless of DPI or display scaling.
• No external dependencies required.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import math
import random
import time

# ------------------------------------------------------------------ #
# Windows INPUT structures
# ------------------------------------------------------------------ #

INPUT_MOUSE = 0

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT_UNION)]


# ------------------------------------------------------------------ #
# Screen helpers
# ------------------------------------------------------------------ #

def _screen_size() -> tuple[int, int]:
    u32 = ctypes.windll.user32
    return u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)


def _to_absolute(x: float, y: float) -> tuple[int, int]:
    """Convert pixel coordinates to the 0–65535 range required by SendInput."""
    w, h = _screen_size()
    ax = int(round(x * 65535 / max(1, w - 1)))
    ay = int(round(y * 65535 / max(1, h - 1)))
    return ax, ay


# ------------------------------------------------------------------ #
# Low-level helpers
# ------------------------------------------------------------------ #

def _send_mouse_event(flags: int, dx: int = 0, dy: int = 0) -> None:
    inp = _INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.mouseData = 0
    inp.mi.dwFlags = flags
    inp.mi.time = 0
    inp.mi.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def get_position() -> tuple[int, int]:
    """Return current cursor position in screen pixels."""
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_to(x: float, y: float) -> None:
    """Instantly move the cursor to screen position (x, y)."""
    ax, ay = _to_absolute(x, y)
    _send_mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay)


def click_left(x: float | None = None, y: float | None = None) -> None:
    """Left-click at the current position (or at (x, y) if given)."""
    if x is not None and y is not None:
        move_to(x, y)
    _send_mouse_event(MOUSEEVENTF_LEFTDOWN)
    time.sleep(random.uniform(0.040, 0.090))
    _send_mouse_event(MOUSEEVENTF_LEFTUP)


def click_right(x: float | None = None, y: float | None = None) -> None:
    """Right-click at the current position (or at (x, y) if given)."""
    if x is not None and y is not None:
        move_to(x, y)
    _send_mouse_event(MOUSEEVENTF_RIGHTDOWN)
    time.sleep(random.uniform(0.040, 0.090))
    _send_mouse_event(MOUSEEVENTF_RIGHTUP)


# ------------------------------------------------------------------ #
# WindMouse — realistic curved trajectory
# ------------------------------------------------------------------ #

def wind_mouse(
    start_x: float,
    start_y: float,
    dest_x: float,
    dest_y: float,
    gravity: float = 9.0,
    wind: float = 3.0,
    min_wait_ms: float = 2.0,
    max_wait_ms: float = 8.0,
    max_step: float = 12.0,
    target_area: float = 10.0,
    rng: random.Random | None = None,
) -> None:
    """
    Move the mouse from (start_x, start_y) to (dest_x, dest_y) using the
    WindMouse algorithm.

    The algorithm applies two forces each step:
      • Gravity — pulls toward the destination
      • Wind    — adds noise that decays as the cursor nears the target

    This produces the natural S-curve overshoot-and-correct pattern seen
    in real mouse movements.  Each intermediate position is delivered via
    move_to(), with a tiny inter-step sleep to produce real movement rather
    than a jump.
    """
    if rng is None:
        rng = random

    sqrt3 = math.sqrt(3)
    sqrt5 = math.sqrt(5)

    cx, cy = float(start_x), float(start_y)
    wx, wy = 0.0, 0.0
    vx, vy = 0.0, 0.0
    step = max_step

    total_dist = math.hypot(dest_x - cx, dest_y - cy)

    dist = total_dist
    while dist > 1.0:
        w_mag = min(wind, dist)

        if dist >= target_area:
            wx = wx / sqrt3 + (rng.random() * 2.0 - 1.0) * w_mag / sqrt5
            wy = wy / sqrt3 + (rng.random() * 2.0 - 1.0) * w_mag / sqrt5
        else:
            wx /= sqrt3
            wy /= sqrt3
            if step < 3.0:
                step = rng.random() * 3.0 + 3.0
            else:
                step /= sqrt5

        vx += wx + gravity * (dest_x - cx) / dist
        vy += wy + gravity * (dest_y - cy) / dist

        v_mag = math.hypot(vx, vy)
        if v_mag > step:
            rand_step = step / 2.0 + rng.random() * step / 2.0
            vx = vx / v_mag * rand_step
            vy = vy / v_mag * rand_step

        cx += vx
        cy += vy

        dist = math.hypot(dest_x - cx, dest_y - cy)
        move_to(cx, cy)

        # Slow down near the target; speed up in the middle of long moves
        progress = 1.0 - dist / max(1.0, total_dist)
        wait = min_wait_ms + (max_wait_ms - min_wait_ms) * (1.0 - progress)
        time.sleep(wait / 1000.0)

    move_to(dest_x, dest_y)
