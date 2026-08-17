"""Option lists shared by the project defaults page and the pair editor.

A pair override must offer exactly the values a project default offers, so both
pages read these lists rather than keeping their own copies.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtWidgets import QComboBox

from insulation_coordination.domain.rules import RulePackage

#: Row-axis identifier an approved package publishes the selectable impulse levels
#: under. The levels themselves belong to the package, never to this module.
IMPULSE_AXIS_ID = "impulse_withstand_kv"

#: Offered in place of the impulse levels while no approved package can supply them, so
#: the field reads as unavailable rather than as an empty list of legitimate choices.
IMPULSE_UNAVAILABLE_TEXT = "Unavailable - load an approved rules package"

POLLUTION_OPTIONS: tuple[tuple[str, int], ...] = (("1", 1), ("2", 2))
MATERIAL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("I", "I"),
    ("II", "II"),
    ("IIIa", "IIIa"),
    ("IIIb", "IIIb"),
)


def impulse_display(value: Decimal) -> str:
    return f"{value / Decimal(1000):g} kV"


def impulse_options(package: RulePackage | None) -> tuple[tuple[str, Decimal], ...]:
    """The impulse levels an approved package offers, in volts.

    Empty whenever no approved and compatible package publishes the axis, which puts
    the field into its unavailable state. There is deliberately nothing to fall back
    to: a level the active package does not carry is not a level this build may offer.
    """
    if package is None or not package.manifest.approved or not package.manifest.compatible:
        return ()
    volts = sorted(
        {
            _volts(value)
            for table in package.tables
            if table.row_axis.id == IMPULSE_AXIS_ID and table.row_axis.unit == "kV"
            for value in table.row_axis.values
        }
    )
    return tuple((impulse_display(value), value) for value in volts)


def _volts(kilovolts: Decimal) -> Decimal:
    """Convert an axis coordinate to volts, keeping a whole number whole.

    A project stores what the combo hands it, so ``1.2 kV`` must land as ``1200``
    rather than as ``1200.0``: the same level saved by two builds has to compare and
    serialise identically.
    """
    volts = kilovolts * 1000
    integral = volts.to_integral_value()
    return integral if volts == integral else volts


def populate_combo(
    combo: QComboBox,
    options: tuple[tuple[str, Any], ...],
    *,
    blank: bool = True,
    unavailable_text: str | None = None,
) -> None:
    """Fill a combo with the options.

    ``blank`` prepends an empty entry meaning "not set", which a project default
    needs. A pair override must not offer it: a pair value is either an override or
    inherited, so an empty choice would be a third state the model cannot hold — and
    picking it would look like a change while silently leaving the value alone.

    ``unavailable_text`` replaces the whole list when a rule-backed field has no
    options, so the field says why it is empty instead of looking like a list that
    happens to have run out.
    """
    if not options and unavailable_text is not None:
        combo.addItem(unavailable_text, None)
        return
    if blank:
        combo.addItem("", None)
    for text, value in options:
        combo.addItem(text, value)


def select_combo_value(
    combo: QComboBox,
    options: tuple[tuple[str, Any], ...],
    value: Any,
    legacy_display: str | None,
    *,
    blank: bool = True,
    unavailable_text: str | None = None,
) -> None:
    """Show ``value``, appending it as a legacy entry when it is off the list.

    A project saved before an option list changed must still round-trip, so an
    unknown value is offered back rather than silently dropped. That holds while the
    options are unavailable too: the stored value stays visible and saveable without
    joining the choices the active package approves.
    """
    combo.clear()
    populate_combo(combo, options, blank=blank, unavailable_text=unavailable_text)
    unavailable = not options and unavailable_text is not None
    if value is None:
        # No blank entry to land on: show nothing rather than inventing a value, so
        # the missing input fails the calculation instead of passing silently.
        combo.setCurrentIndex(0 if blank or unavailable else -1)
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
