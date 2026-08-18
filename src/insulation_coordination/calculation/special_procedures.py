"""The three package procedures a dielectric schedule carries besides its tests.

A monitoring test one recorded impulse reduction depends on; the preconditioning a test is
performed after; and the conductive foil an accessible insulating surface has to be wrapped in
before there is anything to connect the low side to. None of the three verifies the insulation
between two conductors, which is why only one of them produces a schedule row and the other
two arrive as preparation on the rows they precede.

*The monitoring dependency is consumed, never re-derived.* Whether a device inside the
equipment owes a dedicated monitoring type test is a question issue #36's override resolution
already asked the package, and it recorded the answer against the pair. This module reads that
record and states the test the issue asks for. Asking a rule the same question a second time
would let two answers exist, over a reduction that is already in the plan's voltages.

*Preconditioning is asked of the package, in the package's own words.* The gate discriminates
on a context and a purpose whose vocabularies the package declares, and neither is written out
here: the context that selects the electrical route is read off the gate's own rows, and the
purpose is the package's name for the classification of the test being preconditioned. A
classification the gate declares no purpose for is reported unresolved rather than mapped onto
the nearest one, because a source that settles three purposes is a source declining to settle
a fourth.

*The foil substitution is recorded and never acted on.* The gate states what it permits in
place of the classification the surrounding test carries, as a categorical this application
has no reading of. It goes into the preparation verbatim, exactly as the monitoring
dependency's verification reference does, and no classification is changed by it: substituting
a sample test for a routine one on the strength of a string nothing here understands would be
removing a routine test on a guess.

.. note::

   **The material preconditioning route is resolved and unreachable from here.** Its gate
   contexts each name one specific solid-insulation requirement, and which of them a project
   is meeting is not something a dielectric test schedule knows. The electrical context is the
   only honest question this plan has, so the material route's steps never reach a row.
   Nothing is dropped by that - no test loses a step it would otherwise have carried - but the
   route is a contract gap of the same class as Table 27's positional columns.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from insulation_coordination.calculation.impulse_override import SpdMonitoringDependency
from insulation_coordination.calculation.verification_rules import (
    CLASSIFICATION_NAMES,
    FOIL_GATE_INPUT,
    FOIL_SUBSTITUTION_OUTPUT,
    FOIL_WRAP_OUTPUT,
    PRECONDITIONING_CONTEXT_INPUT,
    PRECONDITIONING_ELECTRICAL_ROUTE,
    PRECONDITIONING_PURPOSE_INPUT,
    PRECONDITIONING_REQUIRED_OUTPUT,
    PRECONDITIONING_ROUTE_OUTPUT,
    GatedProcedure,
    PreconditioningRules,
)
from insulation_coordination.domain.rules import DecisionRule, ProcedureRule
from insulation_coordination.domain.verification import (
    TestApplicability,
    TestApplication,
    TestKind,
    TestReferenceKind,
)
from insulation_coordination.rules.evaluator import evaluate_decision

#: Which of this plan's rows the electrical-test preconditioning context is a fair question
#: about. The three dielectric strength tests, and deliberately not the partial-discharge row
#: or the monitoring row: the package's other preconditioning context names specific
#: solid-insulation requirements, and asking the electrical gate about a test of the solid
#: insulation would be this application deciding which of the two clauses covers it.
ELECTRICAL_TEST_KINDS: Final[frozenset[TestKind]] = frozenset(
    {TestKind.IMPULSE_WITHSTAND, TestKind.AC_DIELECTRIC, TestKind.DC_DIELECTRIC}
)

#: Which applicabilities a preparation instruction is worth attaching to. A test the plan has
#: settled as not applying needs neither preconditioning nor foil, and decorating one would
#: put an unresolved input on a row that has nothing outstanding.
_LIVE_APPLICABILITIES: Final[frozenset[TestApplicability]] = frozenset(
    {TestApplicability.REQUIRED, TestApplicability.ENGINEERING_INPUT_REQUIRED}
)

#: What a decoration adds to one row: preparation, rule ids, and what it could not settle.
#: Kept together so a merge into a row cannot pick up half of it. Not a domain model - it
#: never leaves this module and never reaches a report.
_Decoration = tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]

_NOTHING: Final[_Decoration] = ((), (), ())


def monitoring_preparation(
    dependency: SpdMonitoringDependency, procedure: ProcedureRule
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The preparation and the rule ids of the monitoring test one reduction depends on.

    Returned as parts rather than as a built application because the identity of a generated
    test belongs to one function in the plan, and a second module constructing one would be a
    second place a test id could come from.

    Every step the package states is carried: the simulated failure states and the detection
    or indication expected of each are what the procedure's steps say, and a schedule row has
    nowhere else to put them. The reduction the test underwrites is named on the row too, so a
    reader who found the monitoring test can find the override it answers for.
    """

    indication = (
        "The recorded reduction requires a status indication as well as detection."
        if dependency.status_indication_required
        else "The recorded reduction requires detection; it requires no status indication."
    )
    reference = (
        ()
        if dependency.verification_reference is None
        else (
            (
                "The monitoring route states the showing is accepted against "
                f"{dependency.verification_reference}."
            ),
        )
    )
    steps = (
        (
            f"This test underwrites the impulse reduction recorded at "
            f"{dependency.affected_location!r}, whose device is "
            f"{dependency.device_placement.value} and is recorded as "
            f"{'degradable' if dependency.device_degradable else 'not degradable'}."
        ),
        indication,
        *(step.text for step in procedure.preparation_steps),
        *(step.text for step in procedure.procedure_steps),
        *reference,
    )
    return steps, (procedure.id, *dependency.monitoring_rule_ids)


def decorate(
    applications: Iterable[TestApplication],
    *,
    reference_kind: TestReferenceKind,
    preconditioning: PreconditioningRules,
    foil: GatedProcedure,
) -> tuple[TestApplication, ...]:
    """The same applications, carrying the preparation the package's procedures state for them.

    Identity is untouched:
    :func:`~insulation_coordination.domain.verification.build_test_id` does not read a
    preparation step, so decorating rows after they are built cannot move one. Applicability
    moves in one direction only - an added unresolved input makes a row an engineering input -
    so a decoration can raise a question and can never answer one.
    """

    wrap = _foil_decoration(reference_kind, foil)
    return tuple(_decorated(application, wrap, preconditioning) for application in applications)


def _decorated(
    application: TestApplication,
    wrap: _Decoration,
    preconditioning: PreconditioningRules,
) -> TestApplication:
    if application.applicability not in _LIVE_APPLICABILITIES:
        return application
    precondition = (
        _preconditioning_decoration(application, preconditioning)
        if application.test_kind in ELECTRICAL_TEST_KINDS
        else _NOTHING
    )
    steps, rule_ids, unresolved = _merged(wrap, precondition)
    if not (steps or rule_ids or unresolved):
        return application
    outstanding = _unique((*application.unresolved_inputs, *unresolved))
    return application.model_copy(
        update={
            # What the package states comes before this application's own connection
            # instructions: a specimen is preconditioned and wrapped before it is wired up.
            "preparation_steps": _unique((*steps, *application.preparation_steps)),
            "source_rule_ids": _unique((*application.source_rule_ids, *rule_ids)),
            "unresolved_inputs": outstanding,
            "applicability": (
                TestApplicability.ENGINEERING_INPUT_REQUIRED
                if outstanding
                else application.applicability
            ),
        }
    )


def _foil_decoration(reference_kind: TestReferenceKind, foil: GatedProcedure) -> _Decoration:
    """What the accessible-surface gate says about a test against an insulating surface.

    Asked only where the project declares such a surface on the low side. Everywhere else the
    gate's own condition is not met, and asking with a false input would either match a row the
    source did not write for that case or match none at all - neither of which is a fact about
    the equipment.
    """

    if reference_kind is not TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL:
        return _NOTHING
    result = evaluate_decision(foil.applicability, {FOIL_GATE_INPUT: True})
    rule_ids = (foil.procedure.id, foil.applicability.id)
    if result.status != "matched":
        return (
            (),
            rule_ids,
            (
                (
                    f"The active package's {foil.applicability.id} settles nothing for an "
                    "accessible insulating surface, so how this test reaches that surface is "
                    "unresolved."
                ),
            ),
        )
    values = {item.name: item for item in result.values}
    wrap = values.get(FOIL_WRAP_OUTPUT)
    if wrap is None or not wrap.boolean:
        return (), rule_ids, ()
    substitution = values.get(FOIL_SUBSTITUTION_OUTPUT)
    permitted = (
        ()
        if substitution is None or substitution.categorical is None
        else (
            (
                f"The active package's {foil.applicability.id} permits "
                f"{substitution.categorical!r} for this test. It is recorded as permitted and "
                "is not applied: this plan substitutes no classification for another, and the "
                "row's classification stays the one the surrounding test carries."
            ),
        )
    )
    return (
        (
            *(step.text for step in foil.procedure.preparation_steps),
            *(step.text for step in foil.procedure.procedure_steps),
            *permitted,
        ),
        rule_ids,
        (),
    )


def _preconditioning_decoration(
    application: TestApplication, rules: PreconditioningRules
) -> _Decoration:
    """What the preconditioning gate says about this row, asked once per classification.

    A row with no classification is asked nothing and says so: the gate discriminates on what
    the test is for, and a purpose this application invented would be a preconditioning
    sequence nobody specified.
    """

    context = _electrical_context(rules.applicability)
    if context is None:
        return (
            (),
            (rules.applicability.id,),
            (
                (
                    f"The active package's {rules.applicability.id} states no context that "
                    "selects the electrical-test preconditioning route, so whether this test "
                    "is preconditioned cannot be asked."
                ),
            ),
        )
    if not application.classifications:
        return (
            (),
            (rules.applicability.id,),
            (
                (
                    f"The active package's {rules.applicability.id} discriminates on what a "
                    "test is for, and this row carries no classification, so whether it is "
                    "preconditioned is unresolved."
                ),
            ),
        )
    purposes = _declared_values(rules.applicability, PRECONDITIONING_PURPOSE_INPUT)
    routes = {rules.electrical_tests.id: rules.electrical_tests, rules.material.id: rules.material}
    steps: list[str] = []
    unresolved: list[str] = []
    for classification in application.classifications:
        purpose = CLASSIFICATION_NAMES[classification]
        if purpose not in purposes:
            unresolved.append(
                f"The active package's {rules.applicability.id} states no purpose for a "
                f"{classification.value} test, so whether one is preconditioned is unresolved."
            )
            continue
        result = evaluate_decision(
            rules.applicability,
            {PRECONDITIONING_CONTEXT_INPUT: context, PRECONDITIONING_PURPOSE_INPUT: purpose},
        )
        if result.status != "matched":
            unresolved.append(
                f"The active package's {rules.applicability.id} settles nothing for a "
                f"{classification.value} test in the electrical-test context, so whether it "
                "is preconditioned is unresolved."
            )
            continue
        values = {item.name: item for item in result.values}
        required = values.get(PRECONDITIONING_REQUIRED_OUTPUT)
        if required is None or not required.boolean:
            continue
        selected = values.get(PRECONDITIONING_ROUTE_OUTPUT)
        route = None if selected is None else routes.get(selected.categorical or "")
        if route is None:
            unresolved.append(
                f"The active package's {rules.applicability.id} requires preconditioning "
                f"before a {classification.value} test but names no route this application "
                "resolved, so the steps it asks for are unknown."
            )
            continue
        steps.append(
            f"Precondition the specimen before the {classification.value} test, following "
            f"{route.id}."
        )
        steps.extend(step.text for step in route.preparation_steps)
        steps.extend(step.text for step in route.procedure_steps)
    return tuple(steps), (rules.applicability.id,), tuple(unresolved)


def _electrical_context(gate: DecisionRule) -> str | None:
    """Which of the gate's declared contexts selects the electrical-test route.

    Read off the gate's own rows rather than written out here. The package names its contexts
    in a vocabulary of its own, and a name restated in application code is one this
    application could get wrong the day a package renames it. The row that points at the
    electrical route is the package saying which context that is, and it cannot disagree with
    itself.
    """

    for row in gate.rows:
        route = next(
            (item for item in row.values if item.name == PRECONDITIONING_ROUTE_OUTPUT), None
        )
        if route is None or route.categorical != PRECONDITIONING_ELECTRICAL_ROUTE:
            continue
        matcher = next(
            (item for item in row.matchers if item.input == PRECONDITIONING_CONTEXT_INPUT), None
        )
        if matcher is not None and matcher.values:
            return matcher.values[0]
    return None


def _declared_values(gate: DecisionRule, name: str) -> tuple[str, ...]:
    declared = next((item for item in gate.inputs if item.name == name), None)
    return () if declared is None else declared.allowed_values


def _merged(first: _Decoration, second: _Decoration) -> _Decoration:
    return ((*first[0], *second[0]), (*first[1], *second[1]), (*first[2], *second[2]))


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = ["ELECTRICAL_TEST_KINDS", "decorate", "monitoring_preparation"]
