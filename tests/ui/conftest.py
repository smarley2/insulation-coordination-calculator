from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep every UI test out of the real user settings store.

    MainWindow reads preferences during construction, so any test that builds one
    would otherwise see whatever the developer's own registry or plist holds - a
    skipped update version, for example, silently changes what the window does.
    """
    from PySide6.QtCore import QSettings

    from insulation_coordination.ui import main_window as main_window_module

    path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        main_window_module,
        "_settings",
        lambda: QSettings(path, QSettings.Format.IniFormat),
    )
