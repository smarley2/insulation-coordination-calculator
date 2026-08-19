"""Whether one pair's solid insulation has to be verified for partial discharge.

Applicability only. This module never calculates a thickness, never approves one, and never
produces a partial-discharge test voltage of its own: what it decides is whether the test is
owed, and what is still missing before that can be said.

*The scope is the clause's, and the procedure is Table 30's.* Clause 4.4.7.10.3 is what says
which pairs this test reaches: it asks the partial-discharge test of the solid insulation of
double insulation and of reinforced insulation, in addition to the impulse and the AC or DC
test, on the two conditions it states about the recurring-peak working voltage across the
insulation and the electric stress derived from it. Table 30 says how the test is performed.
Reading applicability off the procedure is how a pair that the clause never reached came to be
told a test was owed of it, so the two are asked in that order here: the selected protective means
first, and the procedure only for pairs the clause scopes.

*A pair the clause does not reach is not applicable rather than unresolved.* Where the project
already holds the deciding input - the engineer's own selection of a protective means that is
neither double nor reinforced insulation - answering "required, and here is what is missing"
would ask for an input that could not change the answer. Ignorance is still reported as
ignorance: an unselected means, and an undeclared thickness, layer count or material, are all
engineering inputs.

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
   declared`` is a declaration about the test, and the project records solid-insulation
   thickness, layers and material but no test voltage. Until a schema bump adds one, an established
   recurring-peak working voltage stands in for it: that is the quantity the test voltage is
   set from, so a pair that has one has the input the test needs and a pair that has none does
   not. The substitution is stated on every assessment it decides.

.. note::

   **The clause's two conditions have no rule in the approved package.** 4.4.7.10.3 states
   them, and the package's own applicability route is projected from Table 30's test-voltage
   row rather than from that clause, so nothing here can be asked whether a pair exceeds them.
   The comparison is therefore recorded as a named unresolved input on every pair the clause
   scopes, which is why a scoped pair is never settled as required here. Restating the two
   values as constants would put licensed figures in application code and would let this
   module decide an applicability the standard reserves to the rules it states.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

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
    ProtectionImplementation,
    SolidInsulationTestData,
    TestApplicability,
    TestClassification,
)
from insulation_coordination.rules.evaluator import evaluate_decision

#: The clause identifier this module's scope, classification and threshold statements all come
#: from. Named once so a reader of any of the sentences below can find the one clause behind
#: them, and so none of them has to spell it out twice.
APPLICABILITY_CLAUSE: Final = "4.4.7.10.3"

#: The two constructions the applicability clause is scoped to, which is what its own heading
#: names. Nothing else reaches it: the remaining means of enhanced protection are not solid
#: insulation of double or reinforced insulation, and basic, supplementary and functional
#: insulation are routed by 4.4.7.10.1 to the sibling clause, which asks for no
#: partial-discharge test at all.
IN_SCOPE_IMPLEMENTATIONS: Final[frozenset[ProtectionImplementation]] = frozenset(
    {
        ProtectionImplementation.DOUBLE_INSULATION,
        ProtectionImplementation.REINFORCED_INSULATION,
    }
)

#: The trace identifier of the electric stress the applicability clause defines - the
#: recurring-peak working voltage over the distance between the two parts of different
#: potential, which for a declared construction is its minimum thickness. Not a semantic rule
#: id: the quotient is this module's sum, and labelling it with a package identifier would
#: credit the package with a figure it never stated. Reported because it is one of the two
#: quantities the clause's conditions are about; nothing here compares it against anything,
#: because no approved rule states what to compare it against.
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
    #: What kind of test the applicability clause states this is, for a pair it scopes whose
    #: layer count is declared. Empty for every other pair: a classification is a statement
    #: about a test that is owed, and the clause's sample-test condition is asked about a
    #: layer count nobody supplied.
    classifications: tuple[TestClassification, ...] = ()
    preparation_steps: tuple[str, ...] = ()
    unresolved_inputs: tuple[str, ...] = ()
    #: Nothing raises one today. The high-frequency review this assessment used to carry now
    #: belongs to the insulation design, which is where the annex that owns that boundary
    #: applies; the field stays because the plan collects it and a partial-discharge warning
    #: that is genuinely about the test has somewhere to go.
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

    ``effective`` is the resolved calculation case of the pair. Nothing is read off it today:
    the review a pair above the high-frequency boundary owes is raised where the insulation is
    dimensioned, not against this test, because the annex that owns that boundary governs
    clearance, creepage distance and solid insulation alike while this procedure is specified
    at power frequency. The parameter stays because the caller has it and the assessment is the
    natural place for a further per-pair stress to be read from.
    """

    out_of_scope = _out_of_scope(pair, gated, recurring_peak_v)
    if out_of_scope is not None:
        return out_of_scope
    declared = pair.solid_insulation
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
        )
    stress, stress_steps = _electric_stress(declared, recurring_peak_v)
    unresolved = list(_undeclared(pair, declared))
    applicability, gate_steps, gate_unresolved = _gate_outcome(pair, gated, recurring_peak_v)
    unresolved.extend(gate_unresolved)
    unresolved.append(_threshold_gap(pair, gated))
    # Unconditional while that gap line is, which is until the clause's own conditions have a
    # rule. The gate is still asked and its answer still governs the moment they do, which is
    # why this stays a test of the list rather than a straight assignment.
    if unresolved:
        applicability = TestApplicability.ENGINEERING_INPUT_REQUIRED
    return PartialDischargeOutcome(
        applicability=applicability,
        recurring_peak_v=recurring_peak_v,
        electric_stress_v_per_mm=stress,
        classifications=_classifications(declared),
        preparation_steps=_classification_steps(declared),
        unresolved_inputs=tuple(unresolved),
        source_rule_ids=(gated.procedure.id, gated.applicability.id),
        trace_steps=(*stress_steps, *gate_steps),
    )


def _out_of_scope(
    pair: PairCase, gated: GatedProcedure, recurring_peak_v: Decimal | None
) -> PartialDischargeOutcome | None:
    """The answer for a pair the applicability clause does not reach, or ``None`` if it does.

    Read off the protective means the engineer selected, which is the only thing the clause's
    scope turns on. One of the three answers here is settled and two are not, and the
    difference is whether the project stated something: a means that is not double or
    reinforced insulation is a statement that puts the pair outside the clause, whereas no
    means at all - and a means approved by a review this application never saw - is nobody
    having said yet which clause applies.

    Every answer carries the procedure identifier, because that is the inventory row against
    which the applicability clause is recorded: the sentences below restate what that clause
    obliges, and a restatement with no rule behind it is this application's own opinion.
    """

    implementation = pair.protection_implementation
    if implementation in IN_SCOPE_IMPLEMENTATIONS:
        return None
    if implementation is None:
        return PartialDischargeOutcome(
            applicability=TestApplicability.ENGINEERING_INPUT_REQUIRED,
            recurring_peak_v=recurring_peak_v,
            unresolved_inputs=(
                (
                    f"Pair {pair.key} has no protective means selected, and clause "
                    f"{APPLICABILITY_CLAUSE} scopes the partial-discharge test by the means: it "
                    "asks it of the solid insulation of double insulation and of reinforced "
                    "insulation. Until a means is selected, whether the test applies cannot be "
                    "answered."
                ),
            ),
            source_rule_ids=(gated.procedure.id,),
        )
    if implementation is ProtectionImplementation.OTHER_REVIEWED_MEANS:
        return PartialDischargeOutcome(
            applicability=TestApplicability.ENGINEERING_INPUT_REQUIRED,
            recurring_peak_v=recurring_peak_v,
            unresolved_inputs=(
                (
                    f"Pair {pair.key} is protected by other reviewed means, and nothing "
                    "recorded here says whether that construction is realised as the solid "
                    f"insulation of double or reinforced insulation, which is what clause "
                    f"{APPLICABILITY_CLAUSE} is scoped to. Whether the partial-discharge test "
                    "applies belongs to the review that approved the means."
                ),
            ),
            source_rule_ids=(gated.procedure.id,),
        )
    return PartialDischargeOutcome(
        applicability=TestApplicability.NOT_APPLICABLE,
        recurring_peak_v=recurring_peak_v,
        preparation_steps=(
            (
                f"Pair {pair.key} is protected by {implementation.value}, and clause "
                f"{APPLICABILITY_CLAUSE} asks the partial-discharge test only of the solid "
                "insulation of double insulation and of reinforced insulation. The pair is "
                "outside that clause by rule, so no input of this pair's could make the test "
                "apply to it."
            ),
        ),
        source_rule_ids=(gated.procedure.id,),
    )


def _threshold_gap(pair: PairCase, gated: GatedProcedure) -> str:
    """The one thing about applicability the approved package cannot be asked.

    Stated per pair rather than once per plan because it is the reason *this* pair's answer is
    unsettled, and a reviewer reads the reason beside the answer.
    """

    return (
        f"Clause {APPLICABILITY_CLAUSE} asks the partial-discharge test of pair {pair.key} only "
        "where both the recurring-peak working voltage across the insulation and the electric "
        "stress derived from it exceed the values that clause states. The active package states "
        f"no rule for either condition - its {gated.applicability.id} is projected from the "
        "procedure's test-voltage row and answers a different question - so the comparison is "
        "an engineering judgement recorded here rather than made here. Both quantities are "
        "reported on this assessment."
    )


def _classifications(declared: SolidInsulationTestData) -> tuple[TestClassification, ...]:
    """What kind of test the applicability clause states this is for ``declared``.

    The clause asks it as a type test on the components, sub-assemblies and printed wiring
    boards, and *in addition* as a sample test where the insulation consists of a single layer
    of material. So the type test follows from the pair being in scope at all and the sample
    test follows from the declared layer count - which is why an undeclared layer count leaves
    the classification empty rather than assuming a construction.
    """

    if declared.layer_count is None:
        return ()
    if declared.layer_count == 1:
        return (TestClassification.TYPE, TestClassification.SAMPLE)
    return (TestClassification.TYPE,)


def _classification_steps(declared: SolidInsulationTestData) -> tuple[str, ...]:
    """Why the classification above came out the way it did, for the schedule to carry."""

    classifications = _classifications(declared)
    if not classifications:
        return ()
    if TestClassification.SAMPLE in classifications:
        return (
            (
                "The insulation is declared as a single layer of material, so clause "
                f"{APPLICABILITY_CLAUSE} asks a sample test in addition to the type test on "
                "the components, sub-assemblies and printed wiring boards."
            ),
        )
    return (
        (
            f"The insulation is declared as {declared.layer_count} layers, so clause "
            f"{APPLICABILITY_CLAUSE} asks the type test on the components, sub-assemblies and "
            "printed wiring boards; its additional sample test is conditioned on a single "
            "layer of material and is not owed here."
        ),
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
                f"The electric stress clause {APPLICABILITY_CLAUSE} defines: the "
                "recurring-peak working voltage over the distance between the two parts of "
                "different potential, which for a declared construction is its minimum "
                "thickness. "
                "Reported because the clause's second condition is about it; nothing here "
                "compares it against a value, and this application neither dimensions nor "
                "approves a thickness."
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
            f"Pair {pair.key} declares solid insulation but no layer count, so whether clause "
            f"{APPLICABILITY_CLAUSE}'s additional sample test is owed of it is unresolved."
        )
    if declared.material_pd_exempt is None:
        missing.append(
            f"Pair {pair.key} declares solid insulation but does not say whether its material "
            "is exempt from partial-discharge testing, and an unanswered exemption is not one."
        )
    return tuple(missing)


__all__ = [
    "APPLICABILITY_CLAUSE",
    "ELECTRIC_STRESS_TRACE_ID",
    "GATE_INPUT_TRACE_ID",
    "IN_SCOPE_IMPLEMENTATIONS",
    "PartialDischargeOutcome",
    "assess_partial_discharge",
]
