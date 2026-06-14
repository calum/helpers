from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any

from scripts.gamebridge.input import mouse as mouse_input


class HarnessProcess:
    def __init__(self, timeout: float = 5.0) -> None:
        harness_path = os.path.join(os.path.dirname(__file__), "harness.py")
        self._proc = subprocess.Popen(
            [sys.executable, harness_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._pending: list[dict[str, Any]] = []
        self._reader = threading.Thread(target=self._reader_main, daemon=True)
        self._reader.start()

        startup = self._wait_for_json(timeout)
        self.entry_box = startup["entry"]
        self.canvas_box = startup["canvas"]
        self.entry_screen_pos = (
            (self.entry_box["left"] + self.entry_box["right"]) / 2,
            (self.entry_box["top"] + self.entry_box["bottom"]) / 2,
        )
        self.canvas_screen_pos = (
            (self.canvas_box["left"] + self.canvas_box["right"]) / 2,
            (self.canvas_box["top"] + self.canvas_box["bottom"]) / 2,
        )

    def _reader_main(self) -> None:
        assert self._proc.stdout is not None
        for raw in self._proc.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._queue.put(payload)

    def _wait_for_json(self, timeout: float) -> dict[str, Any]:
        end = time.monotonic() + timeout
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for harness startup line")
            try:
                return self._queue.get(timeout=remaining)
            except queue.Empty:
                continue

    def _next_event(self, timeout: float) -> dict[str, Any] | None:
        end = time.monotonic() + timeout
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return None
            try:
                return self._queue.get(timeout=remaining)
            except queue.Empty:
                continue

    def read_events(self, predicate: Any, timeout: float) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        now = time.monotonic()
        end = now + timeout

        for event in list(self._pending):
            if predicate(event):
                matches.append(event)
                self._pending.remove(event)

        while time.monotonic() < end:
            event = self._next_event(end - time.monotonic())
            if event is None:
                break
            if predicate(event):
                matches.append(event)
            else:
                self._pending.append(event)
        return matches

    def wait_for_event(self, predicate: Any, timeout: float) -> dict[str, Any]:
        for event in list(self._pending):
            if predicate(event):
                self._pending.remove(event)
                return event

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            event = self._next_event(end - time.monotonic())
            if event is None:
                break
            if predicate(event):
                return event
            self._pending.append(event)
        raise TimeoutError("Timed out waiting for harness event")

    def focus_entry(self) -> None:
        x, y = self.entry_screen_pos
        mouse_input.click_left(x, y)
        time.sleep(0.2)

    def click_canvas_left(self, x: float, y: float) -> None:
        mouse_input.click_left(x, y)
        time.sleep(0.1)

    def click_canvas_right(self, x: float, y: float) -> None:
        mouse_input.click_right(x, y)
        time.sleep(0.1)

    def drag_canvas(self, start_x: float, start_y: float, end_x: float, end_y: float) -> None:
        mouse_input.move_to(start_x, start_y)
        mouse_input._send_mouse_event(mouse_input.MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.05)
        mouse_input.move_to(end_x, end_y)
        time.sleep(0.05)
        mouse_input._send_mouse_event(mouse_input.MOUSEEVENTF_LEFTUP)
        time.sleep(0.1)

    def close(self) -> None:
        if self._proc.stdin is not None and self._proc.poll() is None:
            try:
                self._proc.stdin.write("QUIT\n")
                self._proc.stdin.flush()
            except OSError:
                pass
        self._proc.wait(timeout=2.0)

    def __enter__(self) -> "HarnessProcess":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
