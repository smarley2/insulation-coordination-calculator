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
told a test was owed of it, so the questions are asked in the clause's own order here: the
selected protective means first, because the clause states its scope in its heading, and its two
conditions only for the pairs that heading names.

*A pair the clause does not reach is not applicable rather than unresolved.* Where the project
already holds the deciding input - the engineer's own selection of a protective means that is
neither double nor reinforced insulation - answering "required, and here is what is missing"
would ask for an input that could not change the answer. Ignorance is still reported as
ignorance: an unselected means, and an undeclared thickness, layer count or material, are all
engineering inputs.

*Nothing unknown becomes "not required".* A pair that has declared nothing about its solid
insulation gets :attr:`~insulation_coordination.domain.verification.TestApplicability.
ENGINEERING_INPUT_REQUIRED` together with the list of what it has not declared. The two
settled answers each need a positive statement behind them - the engineer's, that there is no
solid insulation here at all or that the material is exempt and here is the reference, or the
rule's, that the clause's two conditions are or are not met - and none of them can be reached
by leaving a field blank.

*The clause's own conditions are asked of the rule projected from it.* The package states them
as one decision taking the recurring-peak working voltage across the insulation and the voltage
stress on it, and answering whether the test is owed. This module supplies what the project
holds, reads the one output the rule declares, and reports both a settled yes and a settled no.
It never compares a quantity against a value of its own: the two thresholds are the source's,
and a constant here would be a licensed figure in application code deciding an applicability
the standard reserves to the rule that states it.

*The procedure table's own gate answers a different question and is not asked.* That route is
projected from Table 30's test-voltage row - whether a partial-discharge test *voltage* has
been declared - and reading it as the applicability of the test is how a basic-insulation pair
with a fully declared solid insulation came to be told a test was owed of it.

.. note::

   **The voltage stress has no home in the project model.** The clause defines it as the
   recurring peak divided by the distance between the two parts of different potential, and
   nothing in the project records that distance: the solid-insulation record holds the
   *thickness* of the insulation, which is that distance only where the insulation fills the
   whole gap, and nobody has been asked whether it does. So the stress is not supplied to the
   rule and the rule reports it missing, which every scoped pair carries as one unresolved
   input. It is a missing measurement, not a missing rule, and the wording says so - the
   figure this module reports beside it is the quotient over the declared thickness, reported
   for a reader and never offered as the clause's quantity.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from insulation_coordination.calculation.verification_rules import (
    SOLID_PARTIAL_DISCHARGE_PEAK_INPUT,
    SOLID_PARTIAL_DISCHARGE_REQUIRED_OUTPUT,
    SOLID_PARTIAL_DISCHARGE_SAMPLE_OUTPUT,
    SOLID_PARTIAL_DISCHARGE_SINGLE_LAYER_INPUT,
    SOLID_PARTIAL_DISCHARGE_STRESS_INPUT,
    SOLID_PARTIAL_DISCHARGE_TYPE_OUTPUT,
    GatedProcedure,
    SolidInsulationPartialDischargeRules,
)
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.project import EffectiveCase, PairCase
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import DecisionRule
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

#: The trace identifier of the recurring peak over the declared minimum thickness. Not a
#: semantic rule id: the quotient is this module's sum, and labelling it with a package
#: identifier would credit the package with a figure it never stated. Reported for a reader
#: judging a field strength rather than a voltage, and not offered to the applicability rule -
#: the clause divides by the distance between the two parts of different potential, and the
#: thickness is that distance only where the insulation fills the gap, which nothing records.
ELECTRIC_STRESS_TRACE_ID: Final = "verification.partial_discharge_electric_stress"

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
    clause: SolidInsulationPartialDischargeRules,
    *,
    recurring_peak_v: Decimal | None,
) -> PartialDischargeOutcome:
    """Whether pair ``pair`` owes a partial-discharge test, and what is missing if nobody knows.

    ``gated`` is the procedure and the test-voltage gate the procedure table projects; only the
    procedure is read. ``clause`` is the pair of decisions the applicability subclause projects,
    and they are what settle whether the test is owed and how it is classified.

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

    out_of_scope = _out_of_scope(pair, clause.applicability.id, recurring_peak_v)
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
    applicability, rule_unresolved = _rule_outcome(pair, clause.applicability, recurring_peak_v)
    unresolved.extend(rule_unresolved)
    classifications, classification_unresolved = _classifications(
        pair, clause.classification, declared
    )
    unresolved.extend(classification_unresolved)
    # A settled answer with something outstanding beside it would tell a reader two different
    # things, so anything unresolved makes the answer the engineering input it depends on.
    if unresolved:
        applicability = TestApplicability.ENGINEERING_INPUT_REQUIRED
    rule_ids = [gated.procedure.id, clause.applicability.id]
    if declared.layer_count is not None:
        rule_ids.append(clause.classification.id)
    return PartialDischargeOutcome(
        applicability=applicability,
        recurring_peak_v=recurring_peak_v,
        electric_stress_v_per_mm=stress,
        classifications=classifications,
        preparation_steps=_classification_steps(declared, classifications),
        unresolved_inputs=tuple(unresolved),
        source_rule_ids=tuple(rule_ids),
        trace_steps=stress_steps,
    )


def _out_of_scope(
    pair: PairCase, clause_rule_id: str, recurring_peak_v: Decimal | None
) -> PartialDischargeOutcome | None:
    """The answer for a pair the applicability clause does not reach, or ``None`` if it does.

    Read off the protective means the engineer selected, which is the only thing the clause's
    scope turns on. One of the three answers here is settled and two are not, and the
    difference is whether the project stated something: a means that is not double or
    reinforced insulation is a statement that puts the pair outside the clause, whereas no
    means at all - and a means approved by a review this application never saw - is nobody
    having said yet which clause applies.

    Every answer carries the identifier of the decision the applicability clause projects,
    because the sentences below restate what that clause obliges and a restatement with no
    rule behind it is this application's own opinion. Scope is not an input to that decision -
    the clause states it in its own heading - so it is settled here and the rule is asked only
    about the pairs the heading names.
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
            source_rule_ids=(clause_rule_id,),
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
            source_rule_ids=(clause_rule_id,),
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
        source_rule_ids=(clause_rule_id,),
    )


def _rule_outcome(
    pair: PairCase,
    rule: DecisionRule,
    recurring_peak_v: Decimal | None,
) -> tuple[TestApplicability, tuple[str, ...]]:
    """Ask the applicability clause's own decision, and report whatever it will not settle.

    Two inputs are declared and one of them can be supplied. The recurring-peak working
    voltage is the figure the plan established for this pair; the voltage stress is the
    recurring peak over the distance between the two parts of different potential, and no
    field of this project records that distance - see the module note. So the stress is left
    out, the evaluator answers that an input is required and names it, and this reports that
    as one missing measurement rather than inventing a distance to divide by.

    A rule that settles no row is an open question and never a no, which is the direction this
    module falls in everywhere: a package with nothing to say about a pair must not read as a
    permission to skip the test.
    """

    inputs: dict[str, Decimal | str | bool] = {}
    if recurring_peak_v is not None:
        inputs[SOLID_PARTIAL_DISCHARGE_PEAK_INPUT] = recurring_peak_v
    result = evaluate_decision(rule, inputs)
    if result.status == "input_required":
        return TestApplicability.ENGINEERING_INPUT_REQUIRED, tuple(
            _missing_input(pair, rule, name) for name in result.missing_inputs
        )
    if result.status != "matched":
        return (
            TestApplicability.ENGINEERING_INPUT_REQUIRED,
            (
                (
                    f"The active package's {rule.id} settles no outcome for pair {pair.key}, "
                    "so whether a partial-discharge test applies to it is an open engineering "
                    "question rather than a no."
                ),
            ),
        )
    required = next(
        (
            item.boolean
            for item in result.values
            if item.name == SOLID_PARTIAL_DISCHARGE_REQUIRED_OUTPUT
        ),
        None,
    )
    if required is None:
        return (
            TestApplicability.ENGINEERING_INPUT_REQUIRED,
            (
                (
                    f"The active package's {rule.id} answered pair {pair.key} without stating "
                    f"{SOLID_PARTIAL_DISCHARGE_REQUIRED_OUTPUT}, so nothing it said settles "
                    "whether the test applies."
                ),
            ),
        )
    if required:
        return TestApplicability.REQUIRED, ()
    return TestApplicability.NOT_REQUIRED, ()


def _missing_input(pair: PairCase, rule: DecisionRule, name: str) -> str:
    """One line naming what the applicability decision was not given, and why not.

    The stress line is the one that matters: it names a measurement nobody has taken, which is
    a much narrower thing to fix than the whole rule being absent, and a reviewer reading it
    should be able to tell those two states apart at a glance.
    """

    if name == SOLID_PARTIAL_DISCHARGE_STRESS_INPUT:
        return (
            f"The active package's {rule.id} asks the voltage stress on pair {pair.key}'s "
            f"insulation, and clause {APPLICABILITY_CLAUSE} defines it as the recurring-peak "
            "working voltage over the distance between the two parts of different potential. "
            "No field of this project records that distance - the declared minimum thickness "
            "is the thickness of the insulation, which is the same distance only where the "
            "insulation fills the whole gap, and nothing says it does. The measurement is "
            "missing, not the rule, and until it is recorded this condition cannot be tested."
        )
    if name == SOLID_PARTIAL_DISCHARGE_PEAK_INPUT:
        return (
            f"No recurring-peak working voltage is established for pair {pair.key}, and the "
            f"active package's {rule.id} states clause {APPLICABILITY_CLAUSE}'s first "
            "condition on it, so whether the test applies cannot be answered."
        )
    return (
        f"The active package's {rule.id} declares the input {name!r}, which this application "
        f"has nothing to supply for pair {pair.key}."
    )


def _classifications(
    pair: PairCase, rule: DecisionRule, declared: SolidInsulationTestData
) -> tuple[tuple[TestClassification, ...], tuple[str, ...]]:
    """What kind of test the package says this is, for a declared layer count.

    The clause states its classification on one construction question - whether the insulation
    consists of a single layer of material - and the package projects that as its own decision.
    An undeclared layer count is not asked: answering it either way would state a construction
    nobody declared, and the applicability question above takes different inputs and is still
    answerable without it.
    """

    if declared.layer_count is None:
        return (), ()
    result = evaluate_decision(
        rule, {SOLID_PARTIAL_DISCHARGE_SINGLE_LAYER_INPUT: declared.layer_count == 1}
    )
    if result.status != "matched":
        return (), (
            (
                f"The active package's {rule.id} states no classification for pair "
                f"{pair.key}'s declared construction, so what kind of test this would be is "
                "unresolved."
            ),
        )
    stated = {item.name: item.boolean for item in result.values}
    return tuple(
        classification
        for name, classification in (
            (SOLID_PARTIAL_DISCHARGE_TYPE_OUTPUT, TestClassification.TYPE),
            (SOLID_PARTIAL_DISCHARGE_SAMPLE_OUTPUT, TestClassification.SAMPLE),
        )
        if stated.get(name)
    ), ()


def _classification_steps(
    declared: SolidInsulationTestData, classifications: tuple[TestClassification, ...]
) -> tuple[str, ...]:
    """Why the classification the rule answered with came out the way it did."""

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


def _electric_stress(
    declared: SolidInsulationTestData, recurring_peak_v: Decimal | None
) -> tuple[Decimal | None, tuple[TraceStep, ...]]:
    """The recurring peak over the declared thickness, where both are known.

    Reported because a reviewer judging partial discharge is judging a field strength, not a
    voltage. It is not the clause's quantity and is not offered to the rule that asks for it:
    the clause divides by the distance between the two parts of different potential, and the
    thickness is that distance only where the insulation fills the whole gap. Nothing here
    compares it against anything either - no inception value is held in this application, and
    dimensioning solid insulation is explicitly not what this feature does.
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
                "The recurring-peak working voltage over the declared minimum thickness of "
                f"the insulation. Clause {APPLICABILITY_CLAUSE}'s second condition is about "
                "the stress over the distance between the two parts of different potential, "
                "which this is only where the insulation fills the whole gap; nothing records "
                "that, so this figure is reported for a reader rather than supplied to the "
                "rule. Nothing here compares it against a value, and this application neither "
                "dimensions nor approves a thickness."
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
    "IN_SCOPE_IMPLEMENTATIONS",
    "PartialDischargeOutcome",
    "assess_partial_discharge",
]
