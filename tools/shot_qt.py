"""Render the Qt window offscreen to a PNG so the UI can be reviewed without
opening a real window (works in headless sessions too)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def register_fonts() -> None:
    """The offscreen platform ships no font directory; borrow the system ones."""
    for path in (r"C:\Windows\Fonts\msyh.ttc",
                 r"C:\Windows\Fonts\msyhbd.ttc",
                 r"C:\Windows\Fonts\segoeui.ttf",
                 r"C:\Windows\Fonts\consola.ttf"):
        if Path(path).exists():
            QFontDatabase.addApplicationFont(path)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/ui-qt.png")
    out.parent.mkdir(parents=True, exist_ok=True)

    from app.backend import paths
    from app.backend.controller import CONTROLLER
    from app.ui.main_window import MainWindow

    paths.ensure_dirs()
    CONTROLLER.first_run_done = True          # skip the welcome dialog
    app = QApplication(sys.argv)
    register_fonts()
    win = MainWindow()
    win.resize(1080, 800)
    win.show()

    CONTROLLER.prepare()
    deadline = time.time() + 90
    while time.time() < deadline:
        app.processEvents()
        if CONTROLLER.state()["ready"]:
            break
        time.sleep(0.1)

    if "--start" in sys.argv:
        devs = __import__("app.backend.audio", fromlist=["audio"]).list_devices()
        CONTROLLER.start({
            "voice_id": CONTROLLER.voice_id,
            "input_index": devs["input"][0].index,
            "output_index": (__import__("app.backend.audio", fromlist=["audio"])
                             .find_default_cable_output().index),
            "monitor_index": None,
            "monitor_enabled": False,
        })
        t_end = time.time() + 4.5
        while time.time() < t_end:
            app.processEvents()
            time.sleep(0.05)

    for _ in range(20):                        # let one refresh tick land
        app.processEvents()
        time.sleep(0.05)

    win.grab().save(str(out))
    print(f"saved {out} ({out.stat().st_size} bytes)  ready="
          f"{CONTROLLER.state()['ready']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


