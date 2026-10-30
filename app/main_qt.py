"""Desktop entry point: a normal Qt window, no browser involved."""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "app"

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


def main() -> int:
    from app.backend import paths
    from app.backend.controller import CONTROLLER
    from app.ui.main_window import MainWindow

    t0 = time.perf_counter()
    paths.ensure_dirs()
    # Windows: give the app its own taskbar identity so the icon is right.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "io.openvc.voicechanger")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("OpenVC 实时变声器")
    app.setOrganizationName("OpenVC")

    win = MainWindow()
    win.show()

    # Start loading the model right away; the UI stays responsive.
    CONTROLLER.prepare()

    try:
        elapsed = time.perf_counter() - t0
        (paths.LOG_DIR / "startup.log").write_text(
            f"window shown in {elapsed:.2f}s\n", "utf-8")
    except Exception:
        pass
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        detail = traceback.format_exc()
        try:
            from app.backend import paths
            paths.ensure_dirs()
            (paths.LOG_DIR / "ui_crash.log").write_text(detail, "utf-8")
        except Exception:
            pass
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "OpenVC 启动失败",
                                 "启动失败，详情见 data\\logs\\ui_crash.log\n\n"
                                 + detail[-800:])
        except Exception:
            pass
        raise SystemExit(1)


