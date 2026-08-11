"""Every explanation shown beside a voltage-stress field, in one place.

Four voltage stresses that look alike on a form behave nothing alike in an
insulation calculation, and the value in a box may have been typed, inherited,
derived, or declared absent. Both questions are answered from this registry so
that no page constructor carries its own wording, and so the same sentence
appears wherever the field does.

The text is engineering guidance written for this application. It paraphrases
nothing from a standard and replaces no clause of one: the active rule package
remains the authority for every number.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from insulation_coordination.domain.enums import Applicability
from insulation_coordination.domain.project import FrozenModel, OverrideValue, PairVoltage

#: A tooltip that runs past this stops being read, so a short text may not exceed it.
MAX_SHORT_TEXT_LENGTH = 160


class VoltageGuidanceId(StrEnum):
    STEADY_STATE_PEAK = "steady_state_peak"
    RECURRING_PEAK = "recurring_peak"
    TRANSIENT_OVERVOLTAGE = "transient_overvoltage"
    TEMPORARY_OVERVOLTAGE = "temporary_overvoltage"
    LONG_TERM_RMS = "long_term_rms"
    FREQUENCY = "frequency"
    MANUAL_VALUE = "manual_value"
    INHERITED_DEFAULT = "inherited_default"
    DERIVED_VALUE = "derived_value"
    VERIFIED_OVERRIDE = "verified_override"
    NOT_APPLICABLE = "not_applicable"


class VoltageGuidance(FrozenModel):
    """One field's explanation: a tooltip line plus the long form behind it."""

    id: VoltageGuidanceId
    #: Names the field in running text, for accessible names and dialog titles.
    title: str
    short_text: str
    detailed_text: str
    examples: tuple[str, ...] = ()
    common_mistakes: tuple[str, ...] = ()


_GUIDANCE: Mapping[VoltageGuidanceId, VoltageGuidance] = {
    guidance.id: guidance
    for guidance in (
        VoltageGuidance(
            id=VoltageGuidanceId.LONG_TERM_RMS,
            title="long-term RMS voltage",
            short_text="RMS voltage continuously or repeatedly present for creepage evaluation.",
            detailed_text=(
                "The RMS working voltage this insulation carries continuously, or often "
                "enough that tracking has time to develop. Creepage is dimensioned "
                "against it, so it is the value that must reflect normal operation "
                "rather than a worst case that occurs once.\n\n"
                "Short excursions do not belong here. A peak that appears for "
                "microseconds raises the transient overvoltage, not the long-term RMS."
            ),
            examples=(
                "A 400 V AC mains conductor pair: the long-term RMS is the supply voltage.",
                "A DC link held at 800 V: the long-term RMS equals the DC value.",
            ),
            common_mistakes=(
                "Entering a peak value where an RMS value is asked for.",
                "Entering the highest voltage ever measured, not the one normally present.",
            ),
        ),
        VoltageGuidance(
            id=VoltageGuidanceId.STEADY_STATE_PEAK,
            title="steady-state peak voltage",
            short_text="Continuously present waveform peak.",
            detailed_text=(
                "The peak of the waveform that is present all the time under normal "
                "operation. For a sinusoid it is the RMS value times the square root of "
                "two; for a DC link it is the DC value itself.\n\n"
                "It describes the same steady operating condition as the long-term RMS, "
                "seen at the top of the waveform rather than averaged. Anything that "
                "only appears while switching belongs in the recurring peak."
            ),
            examples=(
                "230 V AC mains: the steady-state peak is about 325 V.",
                "An 800 V DC link: the steady-state peak is 800 V.",
            ),
            common_mistakes=(
                "Adding switching overshoot into the steady-state peak.",
                "Leaving it blank because the RMS value was already entered.",
            ),
        ),
        VoltageGuidance(
            id=VoltageGuidanceId.RECURRING_PEAK,
            title="recurring peak voltage",
            short_text="Repeated PWM, ringing, or periodic overshoot.",
            detailed_text=(
                "The peak of a stress that repeats every cycle or every switching "
                "period: PWM edges, ringing after a commutation, the periodic overshoot "
                "on a transformer winding.\n\n"
                "Repetition is what separates it from a transient overvoltage. A "
                "recurring peak arrives millions of times over the life of the product, "
                "so partial discharge and ageing are dimensioned against it. An "
                "occasional switching surge or a fault impulse is not recurring, however "
                "high it is — enter that as the transient overvoltage instead.\n\n"
                "Enter the frequency of this stress alongside it when the repetition "
                "rate is above the low-frequency range the base rules assume."
            ),
            examples=(
                "A hard-switched inverter output: DC link voltage plus the overshoot.",
                "A transformer winding whose every switching edge overshoots the same way.",
            ),
            common_mistakes=(
                "Recording a once-per-fault surge as a recurring peak.",
                "Ignoring the overshoot and entering only the DC link voltage.",
            ),
        ),
        VoltageGuidance(
            id=VoltageGuidanceId.TRANSIENT_OVERVOLTAGE,
            title="transient overvoltage",
            short_text="Occasional switching, load-dump, surge, or fault impulse.",
            detailed_text=(
                "A short, non-repetitive overvoltage: a lightning or switching surge "
                "arriving from the supply, a load dump, an impulse produced by a fault "
                "elsewhere in the system. It lasts microseconds and clearance is "
                "dimensioned against it.\n\n"
                "It is not a recurring peak. If the same overshoot appears on every "
                "switching cycle it is recurring, and belongs in that field. A transient "
                "is the event the system sees rarely and must survive without breakdown."
            ),
            examples=(
                "A mains-borne surge attenuated by the installation's overvoltage category.",
                "An automotive load dump reaching the pair through the supply.",
            ),
            common_mistakes=(
                "Entering the PWM overshoot here as well as in the recurring peak.",
                "Assuming the supply's transient level applies unchanged behind a barrier.",
            ),
        ),
        VoltageGuidance(
            id=VoltageGuidanceId.TEMPORARY_OVERVOLTAGE,
            title="temporary overvoltage",
            short_text="Relatively long-duration fault overvoltage, commonly lasting seconds.",
            detailed_text=(
                "An overvoltage that persists far longer than an impulse — commonly "
                "seconds — because a fault elsewhere has raised the potential of this "
                "conductor. A lost neutral or an earth fault in the supply network is "
                "the usual cause.\n\n"
                "It is not present in every system. A temporary overvoltage arrives from "
                "the supply network, so a pair fed from an isolated, non-mains source "
                "may genuinely have none. Do not assume one exists; declare the field "
                "not applicable and record why.\n\n"
                "Because it lasts, it stresses insulation more like a working voltage "
                "than like an impulse."
            ),
            examples=(
                "A lost neutral raising a line-to-earth voltage for the whole fault.",
            ),
            common_mistakes=(
                "Entering an impulse level here because both are called overvoltages.",
                "Leaving the field blank when the answer is a considered 'none' plus a reason.",
            ),
        ),
        VoltageGuidance(
            id=VoltageGuidanceId.FREQUENCY,
            title="frequency",
            short_text="Repetition rate of the recurring working-voltage stress on this insulation.",
            detailed_text=(
                "How often the recurring working voltage stresses this insulation. It "
                "selects whether the high-frequency rules apply, so it changes the "
                "required clearance and creepage.\n\n"
                "It is the frequency of the stress, not of an unrelated clock. A "
                "controller running at a high switching frequency matters here only when "
                "that switching is what appears across this pair; if the pair carries "
                "mains at line frequency, the line frequency is the value to enter."
            ),
            examples=(
                "A mains-connected pair: enter the supply frequency.",
                "A pair across a switching-bridge output: enter the switching frequency.",
            ),
            common_mistakes=(
                "Entering the processor or gate-driver clock rate.",
                "Leaving the project default on a pair stressed at another frequency.",
            ),
        ),
        VoltageGuidance(
            id=VoltageGuidanceId.MANUAL_VALUE,
            title="a manually entered value",
            short_text="Entered by hand for this pair.",
            detailed_text=(
                "Somebody typed this value for this pair. It takes precedence over the "
                "project default, and nothing recalculates it: if the design changes, it "
                "changes only when it is edited again.\n\n"
                "Clear the entry to fall back to the project default."
            ),
        ),
        VoltageGuidance(
            id=VoltageGuidanceId.INHERITED_DEFAULT,
            title="a project default value",
            short_text="Inherited from the project defaults; no pair value is set.",
            detailed_text=(
                "No value was entered for this pair, so the project default is used. "
                "Editing the project default moves this field with it.\n\n"
                "Enter a value here to override the default for this pair alone."
            ),
        ),
        VoltageGuidance(
            id=VoltageGuidanceId.DERIVED_VALUE,
            title="a derived value",
            short_text="Read-only result of the project topology and supply rules.",
            detailed_text=(
                "This value was not typed. It is a read-only result computed from the "
                "project's supply configuration and topology by the active rule package, "
                "which is why the field cannot be edited.\n\n"
                "The calculation trace shows which rules produced it and from which "
                "source value."
            ),
        ),
        VoltageGuidance(
            id=VoltageGuidanceId.VERIFIED_OVERRIDE,
            title="a verified override",
            short_text="A documented, verified local reduction; it applies only at this location.",
            detailed_text=(
                "A reduced stress has been claimed here on the strength of documented "
                "evidence — a verified barrier, an attenuating transformer, a "
                "surge-protective device.\n\n"
                "It does not change the project's overvoltage category and it does not "
                "propagate. The reduction applies only at the location it was documented "
                "for; every other part of the project still sees the unreduced value, "
                "and the evidence must remain valid for the override to stand."
            ),
        ),
        VoltageGuidance(
            id=VoltageGuidanceId.NOT_APPLICABLE,
            title="a not-applicable stress",
            short_text="Declared not present here; a justification is stored with the pair.",
            detailed_text=(
                "This stress was declared absent for this pair. That is a decision, not "
                "missing data, so it carries a justification explaining why the stress "
                "cannot reach this insulation.\n\n"
                "A blank field means nobody has answered yet and the calculation will "
                "refuse it. A not-applicable field means somebody answered 'none' and "
                "said why."
            ),
        ),
    )
}

#: The states a value can be in, as opposed to the stresses a field can hold.
FIELD_STATE_IDS: tuple[VoltageGuidanceId, ...] = (
    VoltageGuidanceId.MANUAL_VALUE,
    VoltageGuidanceId.INHERITED_DEFAULT,
    VoltageGuidanceId.DERIVED_VALUE,
    VoltageGuidanceId.VERIFIED_OVERRIDE,
    VoltageGuidanceId.NOT_APPLICABLE,
)

_FIELD_STATE_LABELS: Mapping[VoltageGuidanceId, str] = {
    VoltageGuidanceId.MANUAL_VALUE: "Manual",
    VoltageGuidanceId.INHERITED_DEFAULT: "Project default",
    VoltageGuidanceId.DERIVED_VALUE: "Derived",
    VoltageGuidanceId.VERIFIED_OVERRIDE: "Verified override",
    VoltageGuidanceId.NOT_APPLICABLE: "N/A",
}


def guidance_for(guidance_id: VoltageGuidanceId) -> VoltageGuidance:
    return _GUIDANCE[guidance_id]


def accessible_help_name(guidance_id: VoltageGuidanceId) -> str:
    """What a screen reader announces for the help control beside a field."""
    return f"Help for {guidance_for(guidance_id).title}"


def field_state_label(state: VoltageGuidanceId) -> str:
    """The badge text for a value state, so provenance never relies on colour."""
    return _FIELD_STATE_LABELS[state]


def voltage_field_state(voltage: PairVoltage) -> VoltageGuidanceId | None:
    """The state of a pair voltage, or ``None`` while nobody has answered.

    A blank stress deliberately gets no badge: there is nothing to explain about a
    field that is still waiting for an answer, and labelling it would make missing
    data look like a decision.
    """
    if voltage.applicability is Applicability.NOT_APPLICABLE:
        return VoltageGuidanceId.NOT_APPLICABLE
    if voltage.applicability is Applicability.APPLICABLE:
        return VoltageGuidanceId.MANUAL_VALUE
    return None


def override_field_state(value: OverrideValue[Any]) -> VoltageGuidanceId:
    """Whether a defaultable field carries its own value or the project's."""
    return (
        VoltageGuidanceId.MANUAL_VALUE if value.is_override else VoltageGuidanceId.INHERITED_DEFAULT
    )
