from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QApplication


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Create and return the QApplication for the desktop shell."""
    if argv is None:
        argv = []
    app = QApplication.instance()
    if app is None:
        app = QApplication(list(argv))
    if not isinstance(app, QApplication):
        raise TypeError("Existing QApplication is not a QApplication")
    return app
