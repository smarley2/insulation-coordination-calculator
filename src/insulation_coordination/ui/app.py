from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QEvent, Signal
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication


class DesktopApplication(QApplication):
    file_open_requested = Signal(object)

    def __init__(self, argv: Sequence[str]) -> None:
        super().__init__(list(argv))
        self._pending_open_paths: list[Path] = []

    def event(self, event: QEvent) -> bool:
        if isinstance(event, QFileOpenEvent):
            path = Path(event.file())
            self._pending_open_paths.append(path)
            self.file_open_requested.emit(path)
            return True
        return super().event(event)

    def take_pending_open_paths(self) -> tuple[Path, ...]:
        paths = tuple(self._pending_open_paths)
        self._pending_open_paths.clear()
        return paths


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Create and return the QApplication for the desktop shell."""
    if argv is None:
        argv = []
    app = QApplication.instance()
    if app is None:
        app = DesktopApplication(argv)
    if not isinstance(app, QApplication):
        raise TypeError("Existing QApplication is not a QApplication")
    return app
