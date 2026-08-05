"""Option lists shared by the project defaults page and the pair editor.

A pair override must offer exactly the values a project default offers, so both
pages read these lists rather than keeping their own copies.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtWidgets import QComboBox

IMPULSE_OPTIONS: tuple[tuple[str, Decimal], ...] = (
    ("0.33 kV", Decimal(330)),
    ("0.40 kV", Decimal(400)),
    ("0.50 kV", Decimal(500)),
    ("0.60 kV", Decimal(600)),
    ("0.80 kV", Decimal(800)),
    ("1.0 kV", Decimal(1000)),
    ("1.2 kV", Decimal(1200)),
    ("1.5 kV", Decimal(1500)),
    ("2.0 kV", Decimal(2000)),
    ("2.5 kV", Decimal(2500)),
    ("3.0 kV", Decimal(3000)),
    ("4.0 kV", Decimal(4000)),
    ("5.0 kV", Decimal(5000)),
    ("6.0 kV", Decimal(6000)),
    ("8.0 kV", Decimal(8000)),
    ("10 kV", Decimal(10000)),
    ("12 kV", Decimal(12000)),
    ("15 kV", Decimal(15000)),
    ("20 kV", Decimal(20000)),
    ("25 kV", Decimal(25000)),
    ("30 kV", Decimal(30000)),
    ("40 kV", Decimal(40000)),
    ("50 kV", Decimal(50000)),
    ("60 kV", Decimal(60000)),
    ("80 kV", Decimal(80000)),
    ("100 kV", Decimal(100000)),
)
POLLUTION_OPTIONS: tuple[tuple[str, int], ...] = (("1", 1), ("2", 2))
MATERIAL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("I", "I"),
    ("II", "II"),
    ("IIIa", "IIIa"),
    ("IIIb", "IIIb"),
)


def impulse_display(value: Decimal) -> str:
    return f"{value / Decimal(1000):g} kV"


def populate_combo(combo: QComboBox, options: tuple[tuple[str, Any], ...]) -> None:
    """Fill a combo with the options, preceded by a blank meaning "not set"."""
    combo.addItem("", None)
    for text, value in options:
        combo.addItem(text, value)


def select_combo_value(
    combo: QComboBox,
    options: tuple[tuple[str, Any], ...],
    value: Any,
    legacy_display: str | None,
) -> None:
    """Show ``value``, appending it as a legacy entry when it is off the list.

    A project saved before an option list changed must still round-trip, so an
    unknown value is offered back rather than silently dropped.
    """
    combo.clear()
    populate_combo(combo, options)
    if value is None:
        combo.setCurrentIndex(0)
        return
    # Not QComboBox.findData: it does not match a Decimal stored as item data, so a
    # listed value like 1200 V would be offered back as a legacy entry.
    index = next(
        (position for position in range(combo.count()) if combo.itemData(position) == value),
        -1,
    )
    if index < 0:
        if legacy_display is None:
            raise ValueError("Legacy combo value requires a display label")
        combo.addItem(f"{legacy_display} (legacy)", value)
        index = combo.count() - 1
    combo.setCurrentIndex(index)
