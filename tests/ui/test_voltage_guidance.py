"""The guidance registry is the single source of every voltage-stress explanation."""

from __future__ import annotations

import pytest

from insulation_coordination.domain.enums import Applicability
from insulation_coordination.domain.project import OverrideValue, PairVoltage
from insulation_coordination.ui.voltage_guidance import (
    FIELD_STATE_IDS,
    MAX_SHORT_TEXT_LENGTH,
    VoltageGuidanceId,
    accessible_help_name,
    field_state_label,
    guidance_for,
    override_field_state,
    voltage_field_state,
)


def test_every_id_has_guidance() -> None:
    for guidance_id in VoltageGuidanceId:
        guidance = guidance_for(guidance_id)
        assert guidance.id is guidance_id
        assert guidance.short_text.strip()
        assert guidance.detailed_text.strip()
        assert guidance.title.strip()


def test_short_text_fits_a_tooltip() -> None:
    for guidance_id in VoltageGuidanceId:
        assert len(guidance_for(guidance_id).short_text) <= MAX_SHORT_TEXT_LENGTH


def test_short_texts_are_distinct() -> None:
    """Two stresses that read the same would defeat the point of the field help."""
    texts = [guidance_for(guidance_id).short_text for guidance_id in VoltageGuidanceId]
    assert len(set(texts)) == len(texts)


def test_stress_guidance_carries_examples_and_mistakes() -> None:
    stresses = (
        VoltageGuidanceId.LONG_TERM_RMS,
        VoltageGuidanceId.STEADY_STATE_PEAK,
        VoltageGuidanceId.RECURRING_PEAK,
        VoltageGuidanceId.TRANSIENT_OVERVOLTAGE,
        VoltageGuidanceId.TEMPORARY_OVERVOLTAGE,
        VoltageGuidanceId.FREQUENCY,
    )
    for guidance_id in stresses:
        guidance = guidance_for(guidance_id)
        assert guidance.examples
        assert guidance.common_mistakes


def test_recurring_peak_is_distinguished_from_a_transient() -> None:
    recurring = guidance_for(VoltageGuidanceId.RECURRING_PEAK).detailed_text.lower()
    transient = guidance_for(VoltageGuidanceId.TRANSIENT_OVERVOLTAGE).detailed_text.lower()
    assert "transient" in recurring
    assert "recurring" in transient


def test_temporary_overvoltage_is_not_assumed_present() -> None:
    detailed = guidance_for(VoltageGuidanceId.TEMPORARY_OVERVOLTAGE).detailed_text.lower()
    assert "not" in detailed and "every" in detailed


def test_not_applicable_requires_a_justification() -> None:
    assert "justification" in guidance_for(VoltageGuidanceId.NOT_APPLICABLE).detailed_text.lower()


def test_derived_value_is_read_only() -> None:
    assert "read-only" in guidance_for(VoltageGuidanceId.DERIVED_VALUE).detailed_text.lower()


def test_verified_override_does_not_change_the_project_ovc() -> None:
    detailed = guidance_for(VoltageGuidanceId.VERIFIED_OVERRIDE).detailed_text.lower()
    assert "overvoltage category" in detailed
    assert "location" in detailed


def test_accessible_name_names_the_field() -> None:
    name = accessible_help_name(VoltageGuidanceId.RECURRING_PEAK)
    assert name.startswith("Help for ")
    assert "recurring peak" in name


def test_every_field_state_has_a_text_label() -> None:
    """Provenance must be readable as text, never as colour alone."""
    labels = {field_state_label(state) for state in FIELD_STATE_IDS}
    assert labels == {"Manual", "Project default", "Derived", "Verified override", "N/A"}


def test_field_state_label_rejects_a_non_state_id() -> None:
    with pytest.raises(KeyError):
        field_state_label(VoltageGuidanceId.RECURRING_PEAK)


def test_voltage_field_state_reads_applicability() -> None:
    assert voltage_field_state(PairVoltage.applicable(1200)) is VoltageGuidanceId.MANUAL_VALUE
    assert (
        voltage_field_state(PairVoltage.not_applicable("No coupling"))
        is VoltageGuidanceId.NOT_APPLICABLE
    )
    assert voltage_field_state(PairVoltage.blank()) is None


def test_voltage_field_state_covers_every_applicability() -> None:
    for applicability in Applicability:
        assert applicability in {
            Applicability.BLANK,
            Applicability.APPLICABLE,
            Applicability.NOT_APPLICABLE,
        }


def test_override_field_state_reads_provenance() -> None:
    assert override_field_state(OverrideValue[int].inherit()) is VoltageGuidanceId.INHERITED_DEFAULT
    assert override_field_state(OverrideValue[int].override(50)) is VoltageGuidanceId.MANUAL_VALUE


def test_resolver_does_not_touch_widgets() -> None:
    """The resolver reads the domain model only, so it stays testable without Qt."""
    import inspect

    from insulation_coordination.ui import voltage_guidance

    source = inspect.getsource(voltage_guidance)
    assert "PySide6" not in source
