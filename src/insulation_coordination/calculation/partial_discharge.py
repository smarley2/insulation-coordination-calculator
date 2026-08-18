"""Whether one pair's solid insulation has to be verified for partial discharge.

Applicability only. This module never calculates a thickness, never approves one, and never
produces a partial-discharge test voltage of its own: what it decides is whether the test is
owed, and what is still missing before that can be said.

Three properties are why it is shaped this way.

*Nothing unknown becomes "not required".* A pair that has declared nothing about its solid
insulation gets :attr:`~insulation_coordination.domain.verification.TestApplicability.
ENGINEERING_INPUT_REQUIRED` together with the list of what it has not declared. The two
settled answers each need a positive statement from the engineer behind them - that there is
no solid insulation here at all, or that the material is exempt and here is the reference -
and neither can be reached by leaving a field blank. The package's own gate is built the same
way: its outcome vocabulary offers "required" and "an input is missing", and no third option,
because the source states its exemptions in prose the gate does not tabulate.

*The gate is asked, not second-guessed.* Which of its outcomes applies is
:func:`~insulation_coordination.calculation.verification_rules.read_verification_rules`'
business and the package's; this module supplies the one input the gate declares and reads the
one output it declares. An outcome the package states and this application has no name for is
reported unresolved rather than rounded to the nearest one it does know.

*The recurring peak is what the test voltage is set from.* The gate asks whether a
partial-discharge test voltage is declared, and the project has nowhere to record one of its
own - see the module note below. The recurring-peak working voltage the pair has established
is what answers it, and the trace says so in as many words, so a reader is never left thinking
the package decided something this application decided.

.. note::

   **The gate's input has no home in the project model.** ``partial_discharge_test_voltage_
   declared`` is a declaration about the test, and schema 6 records solid-insulation thickness,
   layers and material but no test voltage. Until a schema bump adds one, an established
   recurring-peak working voltage stands in for it: that is the quantity the test voltage is
   set from, so a pair that has one has the input the test needs and a pair that has none does
   not. The substitution is stated on every assessment it decides.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from insulation_coordination.calculation.high_frequency import PART4_FREQUENCY_THRESHOLD_HZ
from insulation_coordination.calculation.verification_rules import (
    PARTIAL_DISCHARGE_GATE_INPUT,
    PARTIAL_DISCHARGE_GATE_OUTPUT,
    PARTIAL_DISCHARGE_OUTCOMES,
    GatedProcedure,
)
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.project import EffectiveCase, PairCase
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.trace import CalculationWarning, Quantity, TraceStep
from insulation_coordination.domain.verification import (
    SolidInsulationTestData,
    TestApplicability,
)
from insulation_coordination.rules.evaluator import evaluate_decision

#: Raised above the frequency at which IEC 60664-4 takes over. Partial-discharge behaviour is
#: one of the things that part treats differently, and this application dimensions nothing
#: from it: the warning exists so the reader knows a review is owed, not so a plan can skip it.
HIGH_FREQUENCY_REVIEW_WARNING: Final = "verification_partial_discharge_high_frequency_review"

#: The trace identifier of this application's own arithmetic on the declared thickness. Not a
#: semantic rule id: dividing a working voltage by a thickness is this module's sum, and
#: labelling it with a package identifier would credit the package with a figure it never
#: stated. Reported so a reviewer can see the stress the insulation is under; nothing here
#: compares it against anything.
ELECTRIC_STRESS_TRACE_ID: Final = "verification.partial_discharge_electric_stress"
#: The trace identifier of the substitution the module note describes.
GATE_INPUT_TRACE_ID: Final = "verification.partial_discharge_gate_input"

_VOLTAGE_UNIT: Final = "V"
_STRESS_UNIT: Final = "V/mm"


class PartialDischargeOutcome(FrozenModel):
    """What the partial-discharge assessment concluded for one pair, and on what.

    ``applicability`` is the answer; everything else is why. ``unresolved_inputs`` is never
    empty when the answer is ``ENGINEERING_INPUT_REQUIRED`` and is always empty when it is
    settled, which is what keeps a schedule row's applicability and its unresolved list from
    telling a reader two different things.
    """

    applicability: TestApplicability
    #: The working voltage the test voltage would be set from, where one is established.
    recurring_peak_v: DecimalValue | None = None
    #: The recurring peak over the declared minimum thickness. Reported, never a criterion.
    electric_stress_v_per_mm: DecimalValue | None = None
    preparation_steps: tuple[str, ...] = ()
    unresolved_inputs: tuple[str, ...] = ()
    warnings: tuple[CalculationWarning, ...] = ()
    source_rule_ids: tuple[str, ...] = ()
    trace_steps: tuple[TraceStep, ...] = ()


def assess_partial_discharge(
    pair: PairCase,
    effective: EffectiveCase,
    gated: GatedProcedure,
    *,
    recurring_peak_v: Decimal | None,
) -> PartialDischargeOutcome:
    """Whether pair ``pair`` owes a partial-discharge test, and what is missing if nobody knows.

    ``recurring_peak_v`` is the working voltage the plan already established for this pair -
    the governing approved evidence, or the figure recorded on the pair, whichever the
    evidence service resolved. It is passed in rather than resolved here so that one pair has
    one working voltage across the whole plan, whatever reads it.
    """

    declared = pair.solid_insulation
    warnings = _high_frequency_warnings(pair, effective)
    if declared is None or declared.present is None:
        return PartialDischargeOutcome(
            applicability=TestApplicability.ENGINEERING_INPUT_REQUIRED,
            recurring_peak_v=recurring_peak_v,
            unresolved_inputs=(
                (
                    f"Pair {pair.key} has not declared whether solid insulation separates its "
                    "conductors, so whether a partial-discharge test applies to it cannot be "
                    "answered."
                ),
            ),
            warnings=warnings,
        )
    if not declared.present:
        return PartialDischargeOutcome(
            applicability=TestApplicability.NOT_APPLICABLE,
            recurring_peak_v=recurring_peak_v,
            preparation_steps=(
                (
                    f"Pair {pair.key} is declared to have no solid insulation between its "
                    "conductors, so there is none to verify for partial discharge."
                ),
            ),
            warnings=warnings,
        )
    if declared.material_pd_exempt:
        # The model refuses a claimed exemption without a reference, so there is one to name.
        return PartialDischargeOutcome(
            applicability=TestApplicability.NOT_REQUIRED,
            recurring_peak_v=recurring_peak_v,
            preparation_steps=(
                (
                    f"Pair {pair.key} claims a material exemption from partial-discharge "
                    f"testing on the evidence of {declared.material_reference}. The exemption "
                    "is the engineer's declaration and is reproduced here, not verified."
                ),
            ),
            warnings=warnings,
        )
    stress, stress_steps = _electric_stress(declared, recurring_peak_v)
    unresolved = list(_undeclared(pair, declared))
    applicability, gate_steps, gate_unresolved = _gate_outcome(pair, gated, recurring_peak_v)
    unresolved.extend(gate_unresolved)
    if not gated.procedure.classifications:
        unresolved.append(
            f"The active package's {gated.procedure.id} states no test classification, so "
            f"whether pair {pair.key} owes this as a type test or a sample test is unresolved."
        )
    if unresolved:
        applicability = TestApplicability.ENGINEERING_INPUT_REQUIRED
    return PartialDischargeOutcome(
        applicability=applicability,
        recurring_peak_v=recurring_peak_v,
        electric_stress_v_per_mm=stress,
        preparation_steps=_layer_steps(declared),
        unresolved_inputs=tuple(unresolved),
        warnings=warnings,
        source_rule_ids=(gated.procedure.id, gated.applicability.id),
        trace_steps=(*stress_steps, *gate_steps),
    )


def _gate_outcome(
    pair: PairCase,
    gated: GatedProcedure,
    recurring_peak_v: Decimal | None,
) -> tuple[TestApplicability, tuple[TraceStep, ...], tuple[str, ...]]:
    """Ask the package's applicability gate, and report whatever it will not settle."""

    declared_voltage = recurring_peak_v is not None
    result = evaluate_decision(
        gated.applicability, {PARTIAL_DISCHARGE_GATE_INPUT: declared_voltage}
    )
    step = _gate_input_step(pair, recurring_peak_v, declared_voltage)
    if result.status != "matched":
        return (
            TestApplicability.ENGINEERING_INPUT_REQUIRED,
            (step,),
            (
                (
                    f"The active package's {gated.applicability.id} settles no outcome for "
                    f"pair {pair.key}, so whether a partial-discharge test applies to it is "
                    "an open engineering question rather than a no."
                ),
            ),
        )
    stated = next(
        (item.categorical for item in result.values if item.name == PARTIAL_DISCHARGE_GATE_OUTPUT),
        None,
    )
    applicability = None if stated is None else PARTIAL_DISCHARGE_OUTCOMES.get(stated)
    if applicability is None:
        return (
            TestApplicability.ENGINEERING_INPUT_REQUIRED,
            (step,),
            (
                (
                    f"The active package's {gated.applicability.id} answers {stated!r}, which "
                    "this application has no reading for; the outcome is reported rather than "
                    "translated into the nearest one it knows."
                ),
            ),
        )
    if applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED:
        # The gate settled on "an input is missing", which is an answer and not a refusal. It
        # still needs a line of its own: an application whose applicability says an input is
        # required and whose unresolved list is empty tells a reader two different things.
        return (
            applicability,
            (step,),
            (
                (
                    f"The active package's {gated.applicability.id} answers that pair "
                    f"{pair.key} owes an engineering input before a partial-discharge test can "
                    "be settled, because no partial-discharge test voltage is established "
                    "for it."
                ),
            ),
        )
    return applicability, (step,), ()


def _gate_input_step(pair: PairCase, recurring_peak_v: Decimal | None, declared: bool) -> TraceStep:
    """Say out loud which figure answered the gate's question, and that it is a stand-in."""

    value = Decimal(0) if recurring_peak_v is None else recurring_peak_v
    return TraceStep(
        semantic_rule_id=GATE_INPUT_TRACE_ID,
        operation="select",
        symbolic=rf"\operatorname{{declared}}(\text{{{PARTIAL_DISCHARGE_GATE_INPUT}}})",
        substituted=f"{PARTIAL_DISCHARGE_GATE_INPUT} = {declared}",
        inputs=(),
        source_reference=None,
        output=Quantity(value=value, unit=_VOLTAGE_UNIT),
        unrounded_value=value,
        reason=(
            f"The project records no partial-discharge test voltage of its own, so pair "
            f"{pair.key}'s established recurring-peak working voltage answers the gate: it is "
            "the quantity the test voltage is set from, and its absence is what leaves the "
            "gate unsettled."
        ),
    )


def _electric_stress(
    declared: SolidInsulationTestData, recurring_peak_v: Decimal | None
) -> tuple[Decimal | None, tuple[TraceStep, ...]]:
    """The recurring peak over the declared thickness, where both are known.

    Reported because a reviewer judging partial discharge is judging a field strength, not a
    voltage. Nothing here compares it against anything: no inception value is held in this
    application, and dimensioning solid insulation is explicitly not what this feature does.
    """

    thickness = declared.minimum_thickness_mm
    if recurring_peak_v is None or thickness is None:
        return None, ()
    stress = recurring_peak_v / thickness
    return stress, (
        TraceStep(
            semantic_rule_id=ELECTRIC_STRESS_TRACE_ID,
            operation="divide",
            symbolic=r"E = \frac{U_{rp}}{d}",
            substituted=f"{recurring_peak_v} V / {thickness} mm = {stress} {_STRESS_UNIT}",
            inputs=(
                Quantity(value=recurring_peak_v, unit=_VOLTAGE_UNIT),
                Quantity(value=thickness, unit="mm"),
            ),
            source_reference=None,
            output=Quantity(value=stress, unit=_STRESS_UNIT),
            unrounded_value=stress,
            reason=(
                "The electric stress in the declared solid insulation, reported for review. "
                "This application neither dimensions nor approves a thickness."
            ),
        ),
    )


def _undeclared(pair: PairCase, declared: SolidInsulationTestData) -> tuple[str, ...]:
    """Everything the assessment was not told, one line each.

    The thickness, the layer count and the material each have their own line because a
    reviewer fixes them one at a time, and a single "solid insulation data is incomplete"
    would not say which field to go and fill in.
    """

    missing: list[str] = []
    if declared.minimum_thickness_mm is None:
        missing.append(
            f"Pair {pair.key} declares solid insulation but no minimum thickness, so the "
            "electric stress its insulation is under cannot be reported."
        )
    if declared.layer_count is None:
        missing.append(
            f"Pair {pair.key} declares solid insulation but no layer count, so how the test "
            "is applied to it is unresolved."
        )
    elif declared.layer_count > 1 and declared.separately_testable_layers is None:
        missing.append(
            f"Pair {pair.key} declares {declared.layer_count} insulation layers but does not "
            "say whether they can be tested separately, so how the test is applied to them "
            "is unresolved."
        )
    if declared.material_pd_exempt is None:
        missing.append(
            f"Pair {pair.key} declares solid insulation but does not say whether its material "
            "is exempt from partial-discharge testing, and an unanswered exemption is not one."
        )
    return tuple(missing)


def _layer_steps(declared: SolidInsulationTestData) -> tuple[str, ...]:
    """How a declared multi-layer construction is presented to the test."""

    if (
        declared.layer_count is None
        or declared.layer_count <= 1
        or (declared.separately_testable_layers is None)
    ):
        return ()
    if declared.separately_testable_layers:
        return (
            (
                f"The {declared.layer_count} declared insulation layers can be tested "
                "separately; test each layer as well as the assembled construction."
            ),
        )
    return (
        (
            f"The {declared.layer_count} declared insulation layers cannot be tested "
            "separately, so the test is applied to the assembled construction and no result "
            "is attributable to one layer."
        ),
    )


def _high_frequency_warnings(
    pair: PairCase, effective: EffectiveCase
) -> tuple[CalculationWarning, ...]:
    """The review a pair above the Part 4 frequency owes, whatever else was concluded.

    Attached to every outcome, including the settled ones: a pair that declared no solid
    insulation at this frequency is still a pair whose partial-discharge behaviour was
    assessed against a part of the standard this application does not apply.
    """

    frequency = effective.frequency_hz.value
    if frequency is None or frequency <= PART4_FREQUENCY_THRESHOLD_HZ:
        return ()
    return (
        CalculationWarning(
            code=HIGH_FREQUENCY_REVIEW_WARNING,
            message=(
                f"Pair {pair.key} operates at {frequency} Hz, above the "
                f"{PART4_FREQUENCY_THRESHOLD_HZ} Hz boundary where IEC 60664-4 governs. Its "
                "partial-discharge assessment needs review under that part, which this "
                "application does not apply."
            ),
        ),
    )


__all__ = [
    "ELECTRIC_STRESS_TRACE_ID",
    "GATE_INPUT_TRACE_ID",
    "HIGH_FREQUENCY_REVIEW_WARNING",
    "PartialDischargeOutcome",
    "assess_partial_discharge",
]
