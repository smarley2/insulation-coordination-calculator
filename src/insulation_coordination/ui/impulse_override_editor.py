"""Recording, inspecting and clearing one pair's verified impulse override.

An override is the only route to a value below the derived and propagated one, so this editor
collects the evidence the model requires and refuses anything it cannot: the model's own
message is what a user reads, rather than a second copy of its rules written out here.

Clearing is a first-class action and not a blank field. It removes the recorded evidence and
restores the derived value, with nothing copied into any entry on the way out - which is why
the button says so and why the panel beside this one goes back to showing the derived figure
by itself.

The obligations that come with a reduction - the impulse withstand test, the monitoring a
degradable device owes, the type test an internal one depends on - are read back from the
resolution rather than restated here, and they stay on screen for as long as the override that
raises them is recorded.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.impulse_override import OverrideOutcome
from insulation_coordination.domain.supply import (
    ImpulseOverrideBasis,
    ReductionVerificationMethod,
    SpdDevicePlacement,
    VerifiedImpulseOverride,
)
from insulation_coordination.ui.value_options import populate_combo

#: Shown while no override is recorded against the pair, so an empty form reads as a state
#: rather than as data somebody deleted.
NO_OVERRIDE_TEXT = "No verified override is recorded for this pair; the derived value stands."

#: Shown after one was recorded and the resolution refused to apply it. The derived value
#: stands in that case too, which is the half a user would otherwise have to infer.
REFUSED_PREFIX = "Not applied — the derived value stands: "

APPLIED_PREFIX = "Applied: "


def _wrapping_label(text: str) -> QLabel:
    """A label that wraps, and that never widens the column it sits in.

    An ignored horizontal size policy is the point: these labels carry whole sentences, and a
    sentence's unwrapped width would otherwise become the pair editor's minimum width and
    squeeze every input beside it. Height still follows the width it is given.
    """

    label = QLabel(text)
    label.setWordWrap(True)
    policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    return label


def _words(member: StrEnum) -> str:
    return member.value.replace("_", " ")


def _options(enum: type[StrEnum]) -> tuple[tuple[str, str], ...]:
    return tuple((_words(member), member.value) for member in enum)


def outcome_text(outcome: OverrideOutcome | None) -> str:
    """What became of the recorded override, and everything it obliges.

    The warnings are part of the answer, not a footnote to it: a reduction claimed on a
    surge-protective device carries obligations that hold for as long as the override does,
    and they are re-read here on every refresh so that nothing dismisses them but removing
    their cause.
    """

    if outcome is None:
        return NO_OVERRIDE_TEXT
    lines = []
    if outcome.applied:
        lines.append(f"{APPLIED_PREFIX}{outcome.effective_impulse_v} V.")
    else:
        lines.append(REFUSED_PREFIX + "; ".join(refusal.message for refusal in outcome.refusals))
    lines.extend(f"• {warning.message}" for warning in outcome.warnings)
    dependency = outcome.spd_monitoring_dependency
    if dependency is not None:
        lines.append(
            f"• This reduction depends on the type test {dependency.required_type_test_semantic_id}."
        )
    return "\n".join(lines)


class ImpulseOverrideEditor(QWidget):
    """Create, edit, inspect and clear the verified override recorded against one pair."""

    override_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._override: VerifiedImpulseOverride | None = None

        group = QGroupBox("Verified impulse override")
        outer = QVBoxLayout(group)
        form = QFormLayout()

        self._value_edit = QLineEdit()
        form.addRow("Impulse value (V):", self._value_edit)
        self._basis_combo = QComboBox()
        populate_combo(self._basis_combo, _options(ImpulseOverrideBasis), blank=False)
        self._basis_combo.currentIndexChanged.connect(lambda _index: self._show_basis_fields())
        form.addRow("Basis:", self._basis_combo)
        self._method_combo = QComboBox()
        populate_combo(self._method_combo, _options(ReductionVerificationMethod), blank=False)
        form.addRow("Verification method:", self._method_combo)
        self._justification_edit = QLineEdit()
        form.addRow("Justification:", self._justification_edit)
        self._evidence_edit = QLineEdit()
        form.addRow("Evidence reference:", self._evidence_edit)
        self._location_edit = QLineEdit()
        self._location_edit.setPlaceholderText("Where at this pair the override applies")
        form.addRow("Affected location:", self._location_edit)
        self._frequency_edit = QLineEdit()
        form.addRow("Transformer frequency (Hz):", self._frequency_edit)
        self._placement_combo = QComboBox()
        populate_combo(self._placement_combo, _options(SpdDevicePlacement), blank=False)
        form.addRow("Device placement:", self._placement_combo)
        self._degradable_check = QCheckBox("Device degrades in service")
        form.addRow("", self._degradable_check)
        outer.addLayout(form)

        buttons = QHBoxLayout()
        self._record_button = QPushButton("Record override")
        self._record_button.setAutoDefault(False)
        self._record_button.clicked.connect(self.record_override)
        buttons.addWidget(self._record_button)
        self._clear_button = QPushButton("Clear override")
        self._clear_button.setAutoDefault(False)
        self._clear_button.setToolTip(
            "Remove the recorded evidence and restore the derived value. Nothing is copied "
            "into the pair's own fields."
        )
        self._clear_button.clicked.connect(self.clear_override)
        buttons.addWidget(self._clear_button)
        buttons.addStretch(1)
        outer.addLayout(buttons)

        self._status = _wrapping_label(NO_OVERRIDE_TEXT)
        self._status.setObjectName("_override_status")
        outer.addWidget(self._status)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(group)
        self._show_basis_fields()
        self.set_override(None)

    @property
    def override(self) -> VerifiedImpulseOverride | None:
        return self._override

    @property
    def status_text(self) -> str:
        return self._status.text()

    def set_override(self, override: VerifiedImpulseOverride | None) -> None:
        """Show ``override``, or an empty form for a pair that has none."""

        self._override = override
        widgets: tuple[QWidget, ...] = (
            self._value_edit,
            self._basis_combo,
            self._method_combo,
            self._justification_edit,
            self._evidence_edit,
            self._location_edit,
            self._frequency_edit,
            self._placement_combo,
            self._degradable_check,
        )
        for widget in widgets:
            widget.blockSignals(True)
        if override is None:
            for edit in (
                self._value_edit,
                self._justification_edit,
                self._evidence_edit,
                self._location_edit,
                self._frequency_edit,
            ):
                edit.clear()
            self._basis_combo.setCurrentIndex(0)
            self._method_combo.setCurrentIndex(0)
            self._placement_combo.setCurrentIndex(0)
            self._degradable_check.setChecked(False)
            self._status.setText(NO_OVERRIDE_TEXT)
        else:
            self._value_edit.setText(str(override.value_v))
            _select(self._basis_combo, override.basis)
            _select(self._method_combo, override.verification_method)
            self._justification_edit.setText(override.justification)
            self._evidence_edit.setText(override.evidence_reference)
            self._location_edit.setText(override.affected_location)
            self._frequency_edit.setText(
                ""
                if override.transformer_frequency_hz is None
                else str(override.transformer_frequency_hz)
            )
            _select(self._placement_combo, override.spd_device_placement)
            self._degradable_check.setChecked(bool(override.spd_device_degradable))
        for widget in widgets:
            widget.blockSignals(False)
        self._clear_button.setEnabled(override is not None)
        self._show_basis_fields()

    def set_outcome(self, outcome: OverrideOutcome | None) -> None:
        """Report what the resolution made of the recorded override, obligations included."""

        self._status.setText(outcome_text(outcome))

    def record_override(self) -> bool:
        """Build an override from the fields and emit it, or refuse and explain why not.

        The refusal is the domain model's own: this editor knows which fields a basis needs
        only in the sense of showing them, and every rule about what one may contain is
        enforced where it is written down.
        """

        basis = ImpulseOverrideBasis(str(self._basis_combo.currentData()))
        device = basis is ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER
        transformer = basis is ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER
        try:
            override = VerifiedImpulseOverride(
                value_v=Decimal(self._value_edit.text().strip()),
                basis=basis,
                verification_method=ReductionVerificationMethod(
                    str(self._method_combo.currentData())
                ),
                justification=self._justification_edit.text().strip(),
                evidence_reference=self._evidence_edit.text().strip(),
                affected_location=self._location_edit.text().strip(),
                transformer_frequency_hz=(
                    Decimal(self._frequency_edit.text().strip()) if transformer else None
                ),
                spd_device_placement=(
                    SpdDevicePlacement(str(self._placement_combo.currentData())) if device else None
                ),
                spd_device_degradable=self._degradable_check.isChecked() if device else None,
            )
        except (InvalidOperation, ValueError) as error:
            QMessageBox.warning(self, "Verified impulse override", str(error))
            return False
        self._override = override
        self._clear_button.setEnabled(True)
        self.override_changed.emit(override)
        return True

    def clear_override(self) -> None:
        """Remove the override. The derived value returns; nothing is copied out of it."""

        if self._override is None:
            return
        self.set_override(None)
        self.override_changed.emit(None)

    def _show_basis_fields(self) -> None:
        """Offer only the fields the selected basis carries, because it carries no others."""

        basis = ImpulseOverrideBasis(str(self._basis_combo.currentData()))
        device = basis is ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER
        transformer = basis is ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER
        self._frequency_edit.setEnabled(transformer)
        self._placement_combo.setEnabled(device)
        self._degradable_check.setEnabled(device)


def _select(combo: QComboBox, value: StrEnum | None) -> None:
    if value is None:
        combo.setCurrentIndex(0)
        return
    combo.setCurrentIndex(
        next(
            (index for index in range(combo.count()) if combo.itemData(index) == value.value),
            0,
        )
    )


__all__ = [
    "APPLIED_PREFIX",
    "NO_OVERRIDE_TEXT",
    "REFUSED_PREFIX",
    "ImpulseOverrideEditor",
    "outcome_text",
]
