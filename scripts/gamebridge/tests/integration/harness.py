from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
from tkinter import ttk


def _log(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False), flush=True)


def _widget_box(widget: tk.Widget) -> dict[str, int]:
    left = widget.winfo_rootx()
    top = widget.winfo_rooty()
    right = left + widget.winfo_width()
    bottom = top + widget.winfo_height()
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
    }


def _on_entry_key_event(phase: str, event: tk.Event, entry: tk.Entry) -> None:
    _log({
        "type": "key",
        "phase": phase,
        "char": event.char,
        "keysym": event.keysym,
        "state": event.state,
        "text": entry.get(),
        "time": event.time,
    })


def _on_canvas_mouse_event(phase: str, event: tk.Event) -> None:
    _log({
        "type": "mouse",
        "phase": phase,
        "button": getattr(event, "num", None),
        "canvasX": event.x,
        "canvasY": event.y,
        "rootX": event.x_root,
        "rootY": event.y_root,
        "state": event.state,
        "time": event.time,
    })


def _watch_stdin(root: tk.Tk) -> None:
    for raw in sys.stdin:
        if raw.strip().upper() == "QUIT":
            root.after(0, root.quit)
            break


def main() -> None:
    root = tk.Tk()
    root.title("GameBridge Integration Harness")
    root.geometry("640x420+200+200")
    root.lift()
    root.attributes("-topmost", True)
    root.update()
    root.attributes("-topmost", False)

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)

    label = ttk.Label(frame, text="Keyboard and mouse harness for GameBridge integration tests.")
    label.pack(fill="x", pady=(0, 12))

    entry_label = ttk.Label(frame, text="Entry (keyboard target)")
    entry_label.pack(anchor="w")
    entry = ttk.Entry(frame, width=40)
    entry.pack(fill="x", pady=(0, 12))
    entry.focus_set()

    canvas_label = ttk.Label(frame, text="Canvas (mouse target)")
    canvas_label.pack(anchor="w")
    canvas = tk.Canvas(frame, width=520, height=240, bg="white", highlightthickness=1, highlightbackground="#666")
    canvas.pack(fill="both", expand=True)
    canvas.create_text(260, 20, text="Click or drag here", fill="#333", font=("Segoe UI", 12))

    root.update_idletasks()

    startup_payload = {
        "type": "startup",
        "hwnd": int(root.winfo_id()),
        "entry": _widget_box(entry),
        "canvas": _widget_box(canvas),
    }
    _log(startup_payload)

    entry.bind("<KeyPress>", lambda event: _on_entry_key_event("down", event, entry))
    entry.bind("<KeyRelease>", lambda event: _on_entry_key_event("up", event, entry))

    canvas.bind("<ButtonPress-1>", lambda event: _on_canvas_mouse_event("down", event))
    canvas.bind("<ButtonRelease-1>", lambda event: _on_canvas_mouse_event("up", event))
    canvas.bind("<ButtonPress-3>", lambda event: _on_canvas_mouse_event("down", event))
    canvas.bind("<ButtonRelease-3>", lambda event: _on_canvas_mouse_event("up", event))
    canvas.bind("<Motion>", lambda event: _on_canvas_mouse_event("move", event))

    watcher = threading.Thread(target=_watch_stdin, args=(root,), daemon=True)
    watcher.start()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
