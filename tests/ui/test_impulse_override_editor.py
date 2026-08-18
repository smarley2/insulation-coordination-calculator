"""The verified impulse override editor: create, edit, inspect evidence, and clear."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from insulation_coordination.calculation.impulse_override import (
    OverrideOutcome,
    OverrideRefusal,
    OverrideRefusalCode,
    SpdMonitoringDependency,
)
from insulation_coordination.domain.supply import (
    ImpulseOverrideBasis,
    ReductionVerificationMethod,
    SpdDevicePlacement,
    VerifiedImpulseOverride,
)
from insulation_coordination.domain.trace import CalculationWarning
from insulation_coordination.ui.impulse_override_editor import (
    APPLIED_PREFIX,
    NO_OVERRIDE_TEXT,
    REFUSED_PREFIX,
    ImpulseOverrideEditor,
    outcome_text,
)


def _override(**overrides: object) -> VerifiedImpulseOverride:
    fields: dict[str, object] = {
        "value_v": Decimal(120),
        "basis": ImpulseOverrideBasis.VERIFIED_CIRCUIT_CHARACTERISTIC,
        "verification_method": ReductionVerificationMethod.TEST,
        "justification": "Measured on the assembled unit",
        "evidence_reference": "SYN-EVIDENCE-1",
        "affected_location": "Primary to enclosure at the input filter",
    }
    fields.update(overrides)
    return VerifiedImpulseOverride(**fields)


@pytest.fixture
def editor(qtbot) -> ImpulseOverrideEditor:
    widget = ImpulseOverrideEditor()
    qtbot.addWidget(widget)
    return widget


def test_an_empty_editor_says_the_derived_value_stands(editor) -> None:
    assert editor.override is None
    assert editor.status_text == NO_OVERRIDE_TEXT


def test_an_override_round_trips_through_the_form(editor) -> None:
    emitted: list[object] = []
    editor.override_changed.connect(emitted.append)
    override = _override()

    editor.set_override(override)
    assert editor.record_override() is True

    assert emitted == [override]


def test_a_device_reduction_keeps_its_placement_and_degradability(editor) -> None:
    emitted: list[object] = []
    editor.override_changed.connect(emitted.append)
    override = _override(
        basis=ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER,
        spd_device_placement=SpdDevicePlacement.INTERNAL_TO_EQUIPMENT,
        spd_device_degradable=True,
    )

    editor.set_override(override)
    assert editor._placement_combo.isEnabled()
    assert editor._degradable_check.isEnabled()
    assert not editor._frequency_edit.isEnabled()
    editor.record_override()

    assert emitted == [override]


def test_a_transformer_claim_keeps_its_frequency(editor) -> None:
    emitted: list[object] = []
    editor.override_changed.connect(emitted.append)
    override = _override(
        basis=ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER,
        transformer_frequency_hz=Decimal(40000),
    )

    editor.set_override(override)
    assert editor._frequency_edit.isEnabled()
    assert not editor._placement_combo.isEnabled()
    editor.record_override()

    assert emitted == [override]


def test_an_override_the_model_refuses_is_not_emitted(editor, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    refusals: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: refusals.append(args[-1]))
    emitted: list[object] = []
    editor.override_changed.connect(emitted.append)
    editor.set_override(_override())
    editor._location_edit.clear()

    assert editor.record_override() is False

    assert emitted == []
    assert refusals and "names the pair or location" in refusals[0]


def test_clearing_removes_the_override_and_empties_the_form(editor) -> None:
    emitted: list[object] = []
    editor.set_override(_override())
    editor.override_changed.connect(emitted.append)

    editor.clear_override()

    assert emitted == [None]
    assert editor.override is None
    assert editor._value_edit.text() == ""
    assert editor._evidence_edit.text() == ""
    assert editor.status_text == NO_OVERRIDE_TEXT


def test_clearing_an_empty_editor_changes_nothing(editor) -> None:
    emitted: list[object] = []
    editor.override_changed.connect(emitted.append)

    editor.clear_override()

    assert emitted == []


# --- what the resolution made of it --------------------------------------------------


def _outcome(**overrides: object) -> OverrideOutcome:
    fields: dict[str, object] = {"override": _override(), "applied": True}
    fields.update(overrides)
    return OverrideOutcome(**fields)


def test_an_applied_override_reports_the_value_it_produced() -> None:
    text = outcome_text(_outcome(effective_impulse_v=Decimal(120)))

    assert text.startswith(APPLIED_PREFIX)
    assert "120 V" in text


def test_a_refused_override_says_the_derived_value_stands() -> None:
    text = outcome_text(
        _outcome(
            applied=False,
            refusals=(
                OverrideRefusal(
                    code=OverrideRefusalCode.WRONG_LOCATION,
                    message="This override was recorded against another location.",
                ),
            ),
        )
    )

    assert text.startswith(REFUSED_PREFIX)
    assert "another location" in text


def test_the_obligations_of_a_reduction_stay_across_a_refresh(editor) -> None:
    outcome = _outcome(
        effective_impulse_v=Decimal(120),
        warnings=(
            CalculationWarning(
                code="supply_spd_reduction_obligations",
                message="The reduction must be verified by the impulse withstand test.",
            ),
        ),
        spd_monitoring_dependency=SpdMonitoringDependency(
            pair_id=UUID(int=7),
            affected_location="Primary to enclosure",
            device_placement=SpdDevicePlacement.INTERNAL_TO_EQUIPMENT,
            device_degradable=True,
            monitoring_required=True,
            status_indication_required=True,
        ),
    )

    editor.set_outcome(outcome)
    first = editor.status_text
    editor.set_outcome(outcome)

    assert "impulse withstand test" in first
    assert "type test" in first
    assert editor.status_text == first
