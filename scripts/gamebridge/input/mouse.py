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
from typing import Callable

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
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

WHEEL_DELTA = 120  # standard Windows mouse wheel notch size

# AWT button identifiers (java.awt.event.MouseEvent.BUTTON1/2/3) — kept
# consistent with input.bridge_input.BUTTON_LEFT/MIDDLE/RIGHT so button_down/
# button_up/drag_to accept the same values regardless of active backend.
BUTTON_LEFT = 1
BUTTON_MIDDLE = 2
BUTTON_RIGHT = 3

_DOWN_FLAGS = {
    BUTTON_LEFT: MOUSEEVENTF_LEFTDOWN,
    BUTTON_MIDDLE: MOUSEEVENTF_MIDDLEDOWN,
    BUTTON_RIGHT: MOUSEEVENTF_RIGHTDOWN,
}
_UP_FLAGS = {
    BUTTON_LEFT: MOUSEEVENTF_LEFTUP,
    BUTTON_MIDDLE: MOUSEEVENTF_MIDDLEUP,
    BUTTON_RIGHT: MOUSEEVENTF_RIGHTUP,
}


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

_cached_screen_size: tuple[int, int] | None = None


def _screen_size() -> tuple[int, int]:
    global _cached_screen_size
    if _cached_screen_size is None:
        u32 = ctypes.windll.user32
        _cached_screen_size = (u32.GetSystemMetrics(0), u32.GetSystemMetrics(1))
    return _cached_screen_size


def _to_absolute(x: float, y: float) -> tuple[int, int]:
    """Convert pixel coordinates to the 0–65535 range required by SendInput."""
    w, h = _screen_size()
    ax = int(round(x * 65535 / max(1, w - 1)))
    ay = int(round(y * 65535 / max(1, h - 1)))
    return ax, ay


# ------------------------------------------------------------------ #
# Pluggable transport — see GameController.use_bridge_input()
# ------------------------------------------------------------------ #
# get_position()/move_to()/click_left()/click_right() delegate here when set.
# wind_mouse()/wind_mouse_to_prediction() never check this directly — they
# only ever call the four functions above, so swapping the backend here is
# the only change needed to retarget the whole WindMouse algorithm at a
# different transport (OS SendInput vs. Game Bridge canvas injection).
_backend = None


def set_backend(backend) -> None:
    """Route get_position/move_to/click_left/click_right through `backend`
    instead of OS-level SendInput. `backend` must implement the same four
    functions with identical signatures (see input.bridge_input.BridgeInputBackend).
    """
    global _backend
    _backend = backend


def clear_backend() -> None:
    """Revert to OS-level SendInput (the default)."""
    global _backend
    _backend = None


# ------------------------------------------------------------------ #
# Low-level helpers
# ------------------------------------------------------------------ #

def _send_mouse_event(flags: int, dx: int = 0, dy: int = 0, mouse_data: int = 0) -> None:
    inp = _INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.mouseData = mouse_data
    inp.mi.dwFlags = flags
    inp.mi.time = 0
    inp.mi.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def get_position() -> tuple[int, int]:
    """Return current cursor position in screen pixels."""
    if _backend is not None:
        return _backend.get_position()
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_to(x: float, y: float) -> None:
    """Instantly move the cursor to screen position (x, y)."""
    if _backend is not None:
        _backend.move_to(x, y)
        return
    ax, ay = _to_absolute(x, y)
    _send_mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay)


def click_left(x: float | None = None, y: float | None = None) -> None:
    """Left-click at the current position (or at (x, y) if given)."""
    if _backend is not None:
        _backend.click_left(x, y)
        return
    if x is not None and y is not None:
        move_to(x, y)
    _send_mouse_event(MOUSEEVENTF_LEFTDOWN)
    time.sleep(random.uniform(0.040, 0.090))
    _send_mouse_event(MOUSEEVENTF_LEFTUP)


def click_right(x: float | None = None, y: float | None = None) -> None:
    """Right-click at the current position (or at (x, y) if given)."""
    if _backend is not None:
        _backend.click_right(x, y)
        return
    if x is not None and y is not None:
        move_to(x, y)
    _send_mouse_event(MOUSEEVENTF_RIGHTDOWN)
    time.sleep(random.uniform(0.040, 0.090))
    _send_mouse_event(MOUSEEVENTF_RIGHTUP)


def button_down(button: int = BUTTON_LEFT) -> None:
    """Press and hold a mouse button — pair with `button_up` to release it.

    Used by `drag_to` to bracket a WindMouse move with a held button, the
    same way a real click-and-drag works.
    """
    if _backend is not None:
        _backend.button_down(button)
        return
    flags = _DOWN_FLAGS.get(button)
    if flags is not None:
        _send_mouse_event(flags)


def button_up(button: int = BUTTON_LEFT) -> None:
    """Release a mouse button previously held down with `button_down`."""
    if _backend is not None:
        _backend.button_up(button)
        return
    flags = _UP_FLAGS.get(button)
    if flags is not None:
        _send_mouse_event(flags)


def drag_to(
    start_x: float,
    start_y: float,
    dest_x: float,
    dest_y: float,
    button: int = BUTTON_LEFT,
    **wind_mouse_kwargs,
) -> None:
    """Click-and-drag from (start_x, start_y) to (dest_x, dest_y).

    Holds `button` down, moves along a WindMouse path, then releases —
    no new movement/physics code, this just brackets `wind_mouse` with
    `button_down`/`button_up`.
    """
    button_down(button)
    wind_mouse(start_x, start_y, dest_x, dest_y, **wind_mouse_kwargs)
    button_up(button)


def scroll(amount: int) -> None:
    """Scroll the mouse wheel by `amount` notches.

    Follows AWT's wheelRotation convention (matching the Game Bridge wire
    format and InputEventDispatcher): negative = up/away, positive =
    down/toward — regardless of which backend (OS SendInput or Game Bridge
    canvas injection) is active. Windows' own MOUSEEVENTF_WHEEL mouseData
    uses the opposite sign convention, so it is negated here.
    """
    if _backend is not None:
        _backend.scroll(amount)
        return
    _send_mouse_event(MOUSEEVENTF_WHEEL, mouse_data=-amount * WHEEL_DELTA)


# ------------------------------------------------------------------ #
# WindMouse — realistic curved trajectory
# ------------------------------------------------------------------ #

# Per-step probability of a "stutter" wait — a real HID device's polling
# isn't perfectly uniform; USB scheduling hiccups occasionally produce a much
# longer gap between reports. A uniform ±12% jitter alone never produces
# this, so a rare multiplicative spike is layered on top.
STUTTER_CHANCE = 0.04
STUTTER_MULT_RANGE = (2.0, 4.0)


def _step_wait(
    progress: float,
    move_speed: float,
    rng: random.Random,
    *,
    min_wait_ms: float = 3.0,
    max_wait_ms: float = 11.0,
) -> float:
    """Compute the inter-step wait (ms) for one WindMouse step.

    Ease-in-out: slow at the start and near the target, fast through the
    middle — `progress` (0..1) is how far along the path the cursor is, and
    the bell curve peaks at 0.5. `move_speed` (0.0 = fast, 1.0 = slow/
    deliberate) scales the whole wait up. A small per-step Gaussian jitter
    plus a rare stutter (see STUTTER_CHANCE/STUTTER_MULT_RANGE) round out
    the timing so it doesn't look like a uniform synthetic cadence.
    """
    ease = 4.0 * progress * (1.0 - progress)
    wait = max_wait_ms - (max_wait_ms - min_wait_ms) * ease
    wait *= 1.0 + move_speed * 1.5
    wait += rng.gauss(0.0, wait * 0.12)
    if rng.random() < STUTTER_CHANCE:
        wait *= rng.uniform(*STUTTER_MULT_RANGE)
    return max(0.001, wait)


def wind_mouse(
    start_x: float,
    start_y: float,
    dest_x: float,
    dest_y: float,
    gravity: float = 5.0,
    wind: float = 6.0,
    min_wait_ms: float = 3.0,
    max_wait_ms: float = 11.0,
    max_step: float = 9.0,
    target_area: float = 12.0,
    move_speed: float = 0.3,
    rng: random.Random | None = None,
) -> None:
    """
    Move the mouse from (start_x, start_y) to (dest_x, dest_y) using the
    WindMouse algorithm.

    The algorithm applies two forces each step:
      • Gravity — pulls toward the destination
      • Wind    — adds noise that decays as the cursor nears the target

    move_speed (0.0 = fast, 1.0 = slow/deliberate) scales max step size down
    and inter-step waits up, producing a more careful approach at higher values.
    """
    if rng is None:
        rng = random

    sqrt3 = math.sqrt(3)
    sqrt5 = math.sqrt(5)

    cx, cy = float(start_x), float(start_y)
    wx, wy = 0.0, 0.0
    vx, vy = 0.0, 0.0
    # Slower move_speed → smaller steps → more detailed, deliberate path
    step = max_step * max(0.4, 1.0 - move_speed * 0.6)

    total_dist = math.hypot(dest_x - cx, dest_y - cy)

    dist = total_dist
    steps = 0
    while dist > 1.0 and steps < 10_000:
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
        steps += 1

        dist = math.hypot(dest_x - cx, dest_y - cy)
        move_to(cx, cy)

        progress = 1.0 - dist / max(1.0, total_dist)
        wait = _step_wait(progress, move_speed, rng, min_wait_ms=min_wait_ms, max_wait_ms=max_wait_ms)
        time.sleep(wait / 1000.0)

    move_to(dest_x, dest_y)


# ------------------------------------------------------------------ #
# WindMouse variant — moving destination, re-evaluated mid-flight
# ------------------------------------------------------------------ #

def wind_mouse_to_prediction(
    start_x: float,
    start_y: float,
    predict: Callable[[float], tuple[float, float]],
    gravity: float = 5.0,
    wind: float = 6.0,
    min_wait_ms: float = 3.0,
    max_wait_ms: float = 11.0,
    max_step: float = 9.0,
    target_area: float = 12.0,
    move_speed: float = 0.3,
    rng: random.Random | None = None,
) -> None:
    """
    Like wind_mouse, but aims at a moving destination instead of a fixed point.

    `predict(at_time)` returns the best-estimate destination (x, y) for a
    given wall-clock instant (a time.monotonic()-based float — see
    state.moving_target.MovingTarget.predict). It is re-evaluated on every
    step of the approach, so the cursor continuously re-aims at where the
    target is expected to be by the time it arrives — the way a human
    visually re-tracks a moving target while reaching for it — rather than
    chasing wherever it was when the move was planned.

    The noisy wind+gravity approach (identical physics to wind_mouse) runs
    until the cursor is within `target_area` of the latest prediction. At
    that point — rather than letting the algorithm's noisy fine-approach
    phase keep chasing a still-moving point all the way to dist < 1.0, which
    would be slow and could overshoot a target that has since changed
    direction — it performs one final, precise "lock-on" correction: a fresh
    prediction, landed on directly via move_to().
    """
    if rng is None:
        rng = random

    sqrt3 = math.sqrt(3)
    sqrt5 = math.sqrt(5)

    cx, cy = float(start_x), float(start_y)
    wx, wy = 0.0, 0.0
    vx, vy = 0.0, 0.0
    step = max_step * max(0.4, 1.0 - move_speed * 0.6)

    dest_x, dest_y = predict(time.monotonic())
    total_dist = math.hypot(dest_x - cx, dest_y - cy)

    dist = total_dist
    steps = 0
    while dist > target_area and steps < 10_000:
        dest_x, dest_y = predict(time.monotonic())

        w_mag = min(wind, dist)
        wx = wx / sqrt3 + (rng.random() * 2.0 - 1.0) * w_mag / sqrt5
        wy = wy / sqrt3 + (rng.random() * 2.0 - 1.0) * w_mag / sqrt5

        vx += wx + gravity * (dest_x - cx) / dist
        vy += wy + gravity * (dest_y - cy) / dist

        v_mag = math.hypot(vx, vy)
        if v_mag > step:
            rand_step = step / 2.0 + rng.random() * step / 2.0
            vx = vx / v_mag * rand_step
            vy = vy / v_mag * rand_step

        cx += vx
        cy += vy
        steps += 1

        dist = math.hypot(dest_x - cx, dest_y - cy)
        move_to(cx, cy)

        progress = 1.0 - dist / max(1.0, total_dist)
        wait = _step_wait(progress, move_speed, rng, min_wait_ms=min_wait_ms, max_wait_ms=max_wait_ms)
        time.sleep(wait / 1000.0)

    # Lock-on correction: re-predict one last time and land precisely on the
    # freshest estimate, rather than the (possibly now-stale) point the
    # approach was converging toward.
    final_x, final_y = predict(time.monotonic())
    move_to(final_x, final_y)
