"""Whether assembled equipment is excused its final routine test, and on exactly what grounds.

The source grants this exemption only where every one of its conditions holds, and the package
projects that as one decision row and no others: a combination it does not settle - including
one where a condition is simply not known - matches nothing. So the shape of this assessment is
fixed by the shape of the rule. It asks, and where the rule does not answer, the routine test
stays.

*Nothing is ever removed.* A permitted exemption does not delete a row from the schedule; it
marks the routine applications as not required and says which conditions carried it. A
schedule that dropped a test would be indistinguishable from one where nobody thought of it,
and this is the one place in the whole plan where a wrong answer takes work away rather than
adding it.

*Every condition is reported, in the order the source states them.* A reviewer's question is
never "is it exempt" alone - it is "what is still missing", and an assessment that answered
only the first would send them looking through a model to find out. Each condition carries the
engineer's answer, the evidence reference behind it, and one of four states, so a report can
render the trace without knowing anything about the rule.

*An answer with no evidence behind it is not an answer.* The rule's three conditions each have
a reference field beside them, and a condition ticked with an empty reference is
``EVIDENCE_MISSING`` rather than satisfied. So are the reviewer and the review date: nobody
signed a record that names nobody.

*Claiming nothing is not a gap.* A project that never asked for the exemption still gets the
full condition list, so a page can show the checklist without being asked, but it gets no
unresolved input: the routine test staying in the schedule is the ordinary state of affairs,
and reporting it as something outstanding would make every plan permanently incomplete for
having done nothing wrong. Only a record somebody started and left half-answered is reported.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from insulation_coordination.calculation.verification_rules import (
    EXEMPTION_CONDITION_INPUTS,
    EXEMPTION_OUTPUT,
)
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.project import PairCase
from insulation_coordination.domain.rules import DecisionRule
from insulation_coordination.domain.verification import RoutineTestExemptionEvidence
from insulation_coordination.rules.evaluator import evaluate_decision


class ExemptionConditionState(StrEnum):
    """How far one condition of the exemption has got.

    ``NOT_DECLARED`` is the state of a project that has no exemption record at all, and is
    deliberately distinct from ``NOT_SATISFIED``: one is a question nobody asked, the other is
    an engineer's answer of no, and a reviewer chasing the first does something different from
    a reviewer reading the second.
    """

    SATISFIED = "satisfied"
    EVIDENCE_MISSING = "evidence_missing"
    NOT_SATISFIED = "not_satisfied"
    NOT_DECLARED = "not_declared"


class ExemptionCondition(FrozenModel):
    """One condition of the exemption, and everything a reviewer needs to act on it.

    ``decision_input`` is the package's own name for the condition where the rule takes one as
    an input, and empty where the condition is a property of the record rather than of the
    equipment - a reviewer and a review date are not things the source's decision asks about,
    but an exemption without them is not one anybody granted.
    """

    decision_input: str = ""
    field_name: str
    state: ExemptionConditionState
    evidence_reference: str = ""
    detail: str

    @property
    def is_satisfied(self) -> bool:
        return self.state is ExemptionConditionState.SATISFIED


class RoutineExemptionAssessment(FrozenModel):
    """What the exemption assessment concluded for one pair, condition by condition.

    ``exemption_permitted`` is true only where every condition is satisfied *and* the package's
    own decision says the equipment is exempt. Either half failing keeps the routine test, and
    ``unresolved_inputs`` says which.
    """

    pair_key: str
    exemption_permitted: bool = False
    #: Every condition, in the order the source states them, followed by the record's own.
    conditions: tuple[ExemptionCondition, ...] = ()
    #: What the package's decision did when it was asked, or why it was not asked at all.
    decision_status: str = "not_asked"
    unresolved_inputs: tuple[str, ...] = ()
    source_rule_ids: tuple[str, ...] = ()

    @property
    def missing(self) -> tuple[ExemptionCondition, ...]:
        """Every condition that is not satisfied, which is what a reader asks for first."""

        return tuple(item for item in self.conditions if not item.is_satisfied)


#: How each of the rule's three condition inputs is answered and evidenced on the record. The
#: rule states the conditions; this says where the project keeps its answer to each, and the
#: two are joined by the package's own input name so a renamed input is a missing condition
#: rather than a silently unasked one.
_EVIDENCE_FIELDS: Final[dict[str, tuple[str, str, str]]] = {
    "sub_assembly_routine_test_performed": (
        "subassemblies_routine_tested",
        "subassembly_evidence_reference",
        "every subassembly was routine tested",
    ),
    "assembly_shown_not_to_compromise_insulation": (
        "assembly_cannot_compromise_insulation",
        "assembly_justification",
        "assembling them cannot compromise the insulation",
    ),
    "assembled_type_test_passed": (
        "assembled_type_test_passed",
        "assembled_type_test_reference",
        "the assembled equipment passed its type test",
    ),
}


def assess_routine_exemption(pair: PairCase, rule: DecisionRule) -> RoutineExemptionAssessment:
    """Whether ``pair`` may be excused its routine test, and the trace behind the answer.

    The decision is asked only once every condition is satisfied. That is not an optimisation:
    the rule carries the one row the source states and nothing else, so asking it with a false
    condition matches nothing and returns the same answer a reader would already have from the
    conditions themselves - with the difference that a bare "no match" says nothing about which
    condition failed.
    """

    evidence = pair.routine_exemption
    conditions = _conditions(evidence)
    # A project that never claimed the exemption is not a project with something outstanding:
    # the routine test staying in the schedule is the ordinary state, and reporting it as an
    # unresolved input would make every plan permanently incomplete for doing nothing wrong.
    # The conditions are still reported, so a page can show the checklist unprompted.
    unresolved = (
        []
        if evidence is None
        else [
            f"Pair {pair.key} cannot be excused its routine dielectric test: {item.detail}."
            for item in conditions
            if not item.is_satisfied
        ]
    )
    if evidence is None or unresolved:
        return RoutineExemptionAssessment(
            pair_key=pair.key,
            conditions=conditions,
            decision_status="not_asked",
            unresolved_inputs=tuple(unresolved),
            source_rule_ids=(rule.id,),
        )
    result = evaluate_decision(rule, dict.fromkeys(EXEMPTION_CONDITION_INPUTS, True))
    exempt = result.status == "matched" and any(
        item.name == EXEMPTION_OUTPUT and item.boolean for item in result.values
    )
    if not exempt:
        unresolved.append(
            f"Every condition the exemption needs is recorded for pair {pair.key}, and the "
            f"active package's {rule.id} still does not grant it. The routine test stays in "
            "the schedule."
        )
    return RoutineExemptionAssessment(
        pair_key=pair.key,
        exemption_permitted=exempt,
        conditions=conditions,
        decision_status=result.status,
        unresolved_inputs=tuple(unresolved),
        source_rule_ids=(rule.id,),
    )


def _conditions(
    evidence: RoutineTestExemptionEvidence | None,
) -> tuple[ExemptionCondition, ...]:
    """Every condition and its state, whether or not the project has a record at all.

    A project with no record still gets the full list. The assessment's job is to say what is
    missing, and "there is no record" said once tells a reviewer less than the three conditions
    they would have to answer.
    """

    return (
        *(
            _condition(name, evidence)
            for name in EXEMPTION_CONDITION_INPUTS
            if name in _EVIDENCE_FIELDS
        ),
        _reviewed("reviewer", evidence, "the reviewer who granted it"),
        _reviewed("reviewed_at", evidence, "the date it was reviewed"),
    )


def _condition(name: str, evidence: RoutineTestExemptionEvidence | None) -> ExemptionCondition:
    field, reference_field, description = _EVIDENCE_FIELDS[name]
    if evidence is None:
        return ExemptionCondition(
            decision_input=name,
            field_name=field,
            state=ExemptionConditionState.NOT_DECLARED,
            detail=f"nothing records that {description}",
        )
    reference = str(getattr(evidence, reference_field) or "").strip()
    if not getattr(evidence, field):
        return ExemptionCondition(
            decision_input=name,
            field_name=field,
            state=ExemptionConditionState.NOT_SATISFIED,
            evidence_reference=reference,
            detail=f"it is not recorded that {description}",
        )
    if not reference:
        return ExemptionCondition(
            decision_input=name,
            field_name=field,
            state=ExemptionConditionState.EVIDENCE_MISSING,
            detail=f"it is recorded that {description}, with nothing in {reference_field}",
        )
    return ExemptionCondition(
        decision_input=name,
        field_name=field,
        state=ExemptionConditionState.SATISFIED,
        evidence_reference=reference,
        detail=f"{description}, on the evidence of {reference}",
    )


def _reviewed(
    field: str, evidence: RoutineTestExemptionEvidence | None, subject: str
) -> ExemptionCondition:
    """The record's own two conditions, which the package's decision never asks about."""

    value = None if evidence is None else getattr(evidence, field)
    recorded = str(value or "").strip()
    if evidence is None:
        state = ExemptionConditionState.NOT_DECLARED
        detail = f"nothing records {subject}"
    elif not recorded:
        state = ExemptionConditionState.EVIDENCE_MISSING
        detail = f"the exemption record does not state {subject}"
    else:
        state = ExemptionConditionState.SATISFIED
        detail = f"{subject} is {recorded}"
    return ExemptionCondition(
        field_name=field, state=state, evidence_reference=recorded, detail=detail
    )


__all__ = [
    "ExemptionCondition",
    "ExemptionConditionState",
    "RoutineExemptionAssessment",
    "assess_routine_exemption",
]
