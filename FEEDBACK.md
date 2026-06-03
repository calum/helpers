# Feedback from initial testing

## Runelite plugin


## Python GameBridge App

## Debug hull image shows the hull too high — FIXED 2026-06-03
The hull drawn in the debug image is always slightly too high. If I zoom right in, the gap is decreased, but a lot of clicks will still miss. It's like they are all offset by a fixed amount. In every angle, the hull is always too high in the Y axis, so it's like something in the window or calcs is offsetting it by +x pixels in the Y axis.

**Root cause:** `QScreen.grabWindow(hwnd)` captures the full OS window starting from the window's top-left, which includes the native Windows title bar + border chrome (~31 px on Windows 11 at 100% DPI). Hull coordinates from the Java plugin are in *canvas/client* space (origin = client area top-left, below the title bar). The hull was painted at those coordinates directly onto the full-window screenshot without applying the chrome offset, making it appear that many pixels too high.

**Fix:** `_capture_hull_debug` in `dashboard.py` now calls `GetWindowRect`, `GetClientRect`, and `ClientToScreen` to compute the exact client-area rectangle within the captured pixmap, then crops `raw` to that rectangle before painting. Hull points then align with the cropped client-area image.





