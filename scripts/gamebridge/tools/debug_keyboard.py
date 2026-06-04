"""
Keyboard debug tool.

Usage
-----
    python -m scripts.gamebridge.tools.debug_keyboard --sendinput
        Diagnoses why SendInput is failing.
        Open any old-school Win32 app (e.g. Task Manager, regedit) before
        running, and click on it during the 5-second countdown.

    python -m scripts.gamebridge.tools.debug_keyboard --runelite
        Prints the RuneLite child-window tree, then PostMessages Escape to
        each visible child one by one.  Open the deposit box first, watch
        which PostMessage closes it.

    python -m scripts.gamebridge.tools.debug_keyboard
        Runs both.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import time

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

INPUT_KEYBOARD    = 1
KEYEVENTF_KEYUP   = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_ESCAPE = 0x1B
VK_KEY_A  = 0x41
WM_KEYDOWN = 0x0100
WM_KEYUP   = 0x0101
WM_CHAR    = 0x0102


# ------------------------------------------------------------------ #
# SendInput structs
# ------------------------------------------------------------------ #

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT)]

class _INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT_UNION)]


def _send_vk(vk: int, key_up: bool) -> tuple[int, int]:
    """Returns (SendInput result, GetLastError)."""
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.dwFlags = KEYEVENTF_KEYUP if key_up else 0
    inp.ki.time = 0
    inp.ki.dwExtraInfo = None
    result = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    err    = kernel32.GetLastError()
    return result, err

def _send_unicode(char: str, key_up: bool) -> tuple[int, int]:
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = 0
    inp.ki.wScan = ord(char)
    inp.ki.dwFlags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
    inp.ki.time = 0
    inp.ki.dwExtraInfo = None
    result = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    err    = kernel32.GetLastError()
    return result, err


# ------------------------------------------------------------------ #
# PostMessage
# ------------------------------------------------------------------ #

def postmessage_escape(hwnd: int) -> None:
    lp_down = 1 | (0 << 16)
    lp_up   = 1 | (0 << 16) | (1 << 30) | (1 << 31)
    d = user32.PostMessageW(hwnd, WM_KEYDOWN, VK_ESCAPE, lp_down)
    time.sleep(0.06)
    u = user32.PostMessageW(hwnd, WM_KEYUP,   VK_ESCAPE, lp_up)
    err = kernel32.GetLastError()
    print(f"    PostMessage(0x{hwnd:08X}) down={d} up={u}  err={err}  (1/1/0 = success)")


# ------------------------------------------------------------------ #
# Window helpers
# ------------------------------------------------------------------ #

def _title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value

def _cls(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value

def _children(parent: int) -> list[int]:
    out: list[int] = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_size_t)
    def _cb(h: int, _: int) -> bool:
        out.append(h)
        return True
    user32.EnumChildWindows(parent, _cb, 0)
    return out

def _find_top(prefix: str) -> int:
    found = ctypes.c_size_t(0)
    buf = ctypes.create_unicode_buffer(256)
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_size_t)
    def _cb(h: int, _: int) -> bool:
        user32.GetWindowTextW(h, buf, 256)
        if buf.value.startswith(prefix):
            found.value = h
            return False
        return True
    user32.EnumWindows(_cb, 0)
    return found.value


# ------------------------------------------------------------------ #
# SendInput diagnostics
# ------------------------------------------------------------------ #

def test_sendinput() -> None:
    print("\n=== SENDINPUT DIAGNOSTICS ===")

    # Struct size — Windows expects 28 bytes on 64-bit; wrong size = instant fail
    inp = _INPUT()
    sz = ctypes.sizeof(inp)
    print(f"sizeof(_INPUT) = {sz}  (expected 28 on 64-bit Windows)")

    # Current foreground window
    fg = user32.GetForegroundWindow()
    print(f"Current foreground: 0x{fg:08X}  title={_title(fg)!r}  class={_cls(fg)!r}")

    # Send a single keystroke RIGHT NOW to whatever has focus
    print("\nSending 'A' key-down to current foreground window:")
    r, err = _send_vk(VK_KEY_A, key_up=False)
    print(f"  SendInput result={r}  GetLastError={err}")
    if err == 5:
        print("  *** ERROR_ACCESS_DENIED (5): UIPI is blocking injection.")
        print("      This process is at lower IL than the target, or you are")
        print("      running inside Windows Terminal (AppContainer).")
        print("      Try: run this script from a plain cmd.exe prompt, or as admin.")
    elif err == 0 and r == 0:
        print("  *** result=0 err=0: SendInput may be blocked by BlockInput() or")
        print("      an anti-cheat/security tool.  Try running as administrator.")
    elif r == 1:
        print("  OK — SendInput is working.")
    time.sleep(0.05)
    _send_vk(VK_KEY_A, key_up=True)

    # Countdown — let user click a Win32 app (Task Manager, regedit, etc.)
    print("\nOpen any classic Win32 app (Task Manager, regedit, File Explorer)")
    print("and CLICK on it.  You have 5 seconds:")
    for i in range(5, 0, -1):
        print(f"  {i}…", end="\r", flush=True)
        time.sleep(1.0)
    print()

    fg2 = user32.GetForegroundWindow()
    print(f"Foreground now: 0x{fg2:08X}  title={_title(fg2)!r}  class={_cls(fg2)!r}")

    print("Typing 'AAA' via SendInput:")
    for _ in range(3):
        r, err = _send_vk(VK_KEY_A, key_up=False)
        time.sleep(0.05)
        r2, err2 = _send_vk(VK_KEY_A, key_up=True)
        print(f"  down={r}/{err}  up={r2}/{err2}")
        time.sleep(0.1)

    print("Pressing Escape via SendInput:")
    r, err = _send_vk(VK_ESCAPE, key_up=False)
    time.sleep(0.06)
    r2, err2 = _send_vk(VK_ESCAPE, key_up=True)
    print(f"  down={r}/{err}  up={r2}/{err2}")

    print("\nDid 'AAA' appear in the target app?  If no:")
    print("  err=5   → run from plain cmd.exe (not Windows Terminal) or as admin")
    print("  err=0, r=0 → BlockInput is active or antivirus is blocking injection")
    print("  err=0, r=1 → SendInput worked; if nothing appeared the app uses a")
    print("               custom input stack (like WinUI3) — try a different app")


# ------------------------------------------------------------------ #
# RuneLite PostMessage test
# ------------------------------------------------------------------ #

def test_runelite() -> None:
    print("\n=== RUNELITE WINDOW TREE ===")
    hwnd = _find_top("RuneLite")
    if not hwnd:
        print("ERROR: RuneLite not found — is the client running?")
        return

    print(f"Top-level  0x{hwnd:08X}  class={_cls(hwnd)!r}  title={_title(hwnd)!r}")
    kids = _children(hwnd)
    print(f"\nAll children ({len(kids)}):")
    for k in kids:
        vis = bool(user32.IsWindowVisible(k))
        print(f"  0x{k:08X}  class={_cls(k)!r:35s}  visible={vis}  title={_title(k)!r}")

    print("\nOpen the deposit box in-game now.")
    input("Press Enter when the deposit box is visible…")

    visible = [k for k in kids if user32.IsWindowVisible(k)]
    print(f"\nPosting Escape to {len(visible)} visible children + top-level (0.7 s apart):")
    print("Watch the game — note which class closes the deposit box.\n")

    for k in visible:
        print(f"  → 0x{k:08X}  class={_cls(k)!r}")
        postmessage_escape(k)
        time.sleep(0.7)

    print(f"\n  → top-level 0x{hwnd:08X}  class={_cls(hwnd)!r}")
    postmessage_escape(hwnd)

    print("\nWhich class name printed just before the deposit box closed?")
    print("(If none worked, PostMessage is also blocked — we'll need a different approach.)")


# ------------------------------------------------------------------ #

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sendinput", action="store_true", help="Diagnose SendInput failure")
    p.add_argument("--runelite",  action="store_true", help="PostMessage Escape to RuneLite children")
    args = p.parse_args()
    if not args.sendinput and not args.runelite:
        args.sendinput = True
        args.runelite  = True
    if args.sendinput:
        test_sendinput()
    if args.runelite:
        test_runelite()

if __name__ == "__main__":
    main()
