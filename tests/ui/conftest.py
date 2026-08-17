from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import RulePackage, Table, TableAxis, TableCell

#: Made-up levels in kV, chosen to sit nowhere near any published series, so a test that
#: reads them back proves the options came from the package and from nowhere else.
SYNTHETIC_IMPULSE_KV = (Decimal("0.11"), Decimal("2.2"), Decimal("7.7"), Decimal(33))

#: The same levels in volts, which is what the combo hands to the project model.
SYNTHETIC_IMPULSE_V = tuple(level * 1000 for level in SYNTHETIC_IMPULSE_KV)


def with_synthetic_impulse_axis(package: RulePackage) -> RulePackage:
    """Add a clearance table publishing synthetic selectable impulse levels.

    Borrows the host package's own provenance so the addition stays as synthetic as
    the package it joins.
    """
    source = package.tables[0].source
    table = Table(
        id="synthetic-impulse-clearance",
        unit="mm",
        row_axis=TableAxis(
            id="impulse_withstand_kv",
            unit="kV",
            values=SYNTHETIC_IMPULSE_KV,
            labels=tuple(f"synthetic-level-{index}" for index in range(len(SYNTHETIC_IMPULSE_KV))),
        ),
        column_axis=TableAxis(
            id="synthetic_branch",
            unit="1",
            values=(Decimal(1),),
            labels=("synthetic-branch",),
        ),
        cells=tuple(
            TableCell(row=index, column=0, value=Decimal("9.99"), unit="mm", source=source)
            for index in range(len(SYNTHETIC_IMPULSE_KV))
        ),
        source=source,
    )
    return package.model_copy(update={"tables": (*package.tables, table)})


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
