"""Which recorded voltage governs a target, and the plan for establishing one.

Two things live here because they are one subject. :class:`VoltageEvidenceService` answers
"what is this target's :class:`~insulation_coordination.domain.verification.VoltageQuantityKind`
worth, and on whose authority", and :func:`plan_working_voltage` turns that answer into the
determinations a verification plan carries. Splitting them would put the plan in one module
and the only question it asks in another.

Three properties are the whole point of the selection rule.

*Approval is a gate, not a label.* Only an entry an engineer approved for design is allowed to
govern. A draft sitting against a target does not quietly become the answer because it happens
to be the largest number recorded; it is reported as something awaiting a decision, and the
determination that reads it says review is required. An unapproved figure that behaved like an
approved one would be indistinguishable in a report from a value someone signed.

*Nothing is deleted to make room for a newer figure.* A later measurement joins the library
beside the calculation it disagrees with. A lower measured value cannot displace a higher
approved one by arriving later - the higher one has to be explicitly superseded, with a
justification, which is a recorded decision rather than an overwrite.

*A derived stress and a recorded figure never merge.* What issue #36 derived from the supply
arrangements is offered here for comparison and is reported as its own value. It is never
turned into a :class:`~insulation_coordination.domain.verification.VoltageEvidence` entry,
because evidence is what a person took responsibility for and a derivation is not.

Nothing here reads a normative value. The one rule it consumes is the working-voltage procedure,
resolved through
:func:`~insulation_coordination.calculation.verification_rules.read_verification_rules`, and it
is consumed for its identity and its preparation steps rather than for any number.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final
from uuid import NAMESPACE_URL, UUID, uuid5

from insulation_coordination.calculation.verification_rules import VerificationRuleSet
from insulation_coordination.domain.enums import NetClassType
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.trace import Quantity, TraceStep
from insulation_coordination.domain.verification import (
    EvidenceApprovalState,
    EvidenceTarget,
    VerificationStatus,
    VoltageEvidence,
    VoltageEvidenceMethod,
    VoltageQuantityKind,
    WorkingVoltageDetermination,
)

_VOLTAGE_UNIT: Final = "V"

#: The trace identifier of the selection among recorded entries. Not a semantic rule id:
#: choosing the largest approved figure is this application's arithmetic, and labelling it with
#: a package identifier would credit the package with a decision it did not make. The same
#: reasoning ``supply_stress`` applies to its own governing step.
GOVERNING_EVIDENCE_TRACE_ID: Final = "evidence.governing_value"
#: The trace identifier of the comparison between recorded evidence and a derived stress.
EFFECTIVE_VOLTAGE_TRACE_ID: Final = "evidence.effective_value"

#: The quantities a working-voltage determination has to establish. Impulse and temporary
#: overvoltage are deliberately absent: both are overvoltages the supply arrangements derive
#: and issue #36 already traces, and asking an engineer to measure them here would put a second
#: authority beside that derivation.
WORKING_VOLTAGE_QUANTITIES: Final[tuple[VoltageQuantityKind, ...]] = (
    VoltageQuantityKind.AC_RMS,
    VoltageQuantityKind.DC_MEAN,
    VoltageQuantityKind.RECURRING_PEAK,
)

#: The conditions every determination is planned under. All three are always listed, because a
#: plan naming a condition is asking for it to be considered rather than asserting that it
#: occurs; which of them a particular target actually sees is the engineering judgement the
#: determination exists to collect.
OPERATING_CONDITIONS: Final[tuple[str, ...]] = (
    "normal operation",
    "abnormal operation",
    "single fault",
)

#: Namespace for determination identities. Derived rather than written as a literal so the one
#: thing that must never drift is not a hand-copied UUID.
DETERMINATION_NAMESPACE: Final = uuid5(
    NAMESPACE_URL, "https://github.com/smarley2/insulation-coordination-calculator/determination"
)


class GoverningEvidenceResult(FrozenModel):
    """What one target's one quantity is worth, and everything that decided it.

    ``approved_value_v`` comes from recorded evidence alone and ``derived_value_v`` from the
    supply derivation alone; ``effective_value_v`` is the larger of whichever are present. The
    three are kept apart so a reader can always see which authority a number came from.
    """

    target: EvidenceTarget
    quantity: VoltageQuantityKind
    #: Every entry recorded against this target for this quantity, in descending value order,
    #: whatever its approval state.
    applicable: tuple[VoltageEvidence, ...] = ()
    #: The approved entries at the highest approved value. More than one where they tie: a tie
    #: is not broken here, because two approved figures that agree are two pieces of evidence
    #: for the same answer and a report has to name both.
    governing: tuple[VoltageEvidence, ...] = ()
    approved_value_v: DecimalValue | None = None
    derived_value_v: DecimalValue | None = None
    effective_value_v: DecimalValue | None = None
    unresolved_inputs: tuple[str, ...] = ()
    trace_steps: tuple[TraceStep, ...] = ()

    @property
    def awaiting_approval(self) -> tuple[VoltageEvidence, ...]:
        """Applicable entries still in draft. Non-empty means a decision is outstanding."""

        return tuple(
            entry
            for entry in self.applicable
            if entry.approval_state is EvidenceApprovalState.DRAFT
        )

    @property
    def superseded(self) -> tuple[VoltageEvidence, ...]:
        """Applicable entries stood down with a justification."""

        return tuple(
            entry
            for entry in self.applicable
            if entry.approval_state is EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION
        )


class VoltageEvidenceService:
    """Reads a project's evidence library and answers what governs.

    Pure and stateless: it holds no project and caches nothing, so two callers asking the same
    question of the same project always get the same answer.
    """

    def applicable(
        self,
        project: Project,
        target: EvidenceTarget,
        quantity: VoltageQuantityKind,
    ) -> tuple[VoltageEvidence, ...]:
        """Every entry recorded against ``target`` for ``quantity``, whatever its state.

        Ordered by value, largest first, then by id. Sorting rather than keeping the entry
        order means the answer cannot change because somebody re-entered a row, and the entry
        a reader is most likely looking for is first.

        Matching is exact. Evidence recorded against a net is not evidence about a pair that
        net belongs to: they are different questions, and a pair's working voltage is not
        anything about one of its nets on its own.
        """

        return tuple(
            sorted(
                (
                    entry
                    for entry in project.voltage_evidence
                    if entry.quantity_kind is quantity and entry.target == target
                ),
                key=lambda entry: (-entry.value_v, entry.id),
            )
        )

    def governing(
        self,
        project: Project,
        target: EvidenceTarget,
        quantity: VoltageQuantityKind,
        *,
        derived_v: DecimalValue | None = None,
        derived_source: str = "",
    ) -> GoverningEvidenceResult:
        """The value that governs ``target``'s ``quantity``, and the whole basis for it.

        ``derived_v`` is a stress issue #36 derived for this target, offered for comparison.
        It stays its own value throughout: the result reports it separately, and the effective
        value is the larger of it and the approved evidence rather than a merger of the two.
        A caller with no derivation to offer omits it and gets the evidence answer alone.
        """

        applicable = self.applicable(project, target, quantity)
        approved = tuple(
            entry
            for entry in applicable
            if entry.approval_state is EvidenceApprovalState.APPROVED_FOR_DESIGN
        )
        highest = max((entry.value_v for entry in approved), default=None)
        governing = tuple(entry for entry in approved if entry.value_v == highest)
        steps: list[TraceStep] = []
        if highest is not None:
            steps.append(_governing_step(quantity, applicable, governing, highest))
        effective = _larger(highest, derived_v)
        if derived_v is not None:
            steps.append(_effective_step(quantity, highest, derived_v, derived_source, effective))
        return GoverningEvidenceResult(
            target=target,
            quantity=quantity,
            applicable=applicable,
            governing=governing,
            approved_value_v=highest,
            derived_value_v=derived_v,
            effective_value_v=effective,
            unresolved_inputs=_unresolved(quantity, applicable, approved),
            trace_steps=tuple(steps),
        )


def plan_working_voltage(
    project: Project, rules: VerificationRuleSet
) -> tuple[WorkingVoltageDetermination, ...]:
    """One determination per subject whose working voltage has to be established.

    The subjects are every circuit net on its own - the working voltage *within* a circuit -
    and every pair with at least one circuit net in it, which covers a circuit against an
    adjacent circuit, against PE-bonded and accessible conductive parts, and against an
    accessible insulating surface. A pair of two non-circuit nets has no working voltage
    between them, and a pair recorded as never adjacent has a decision against it already;
    neither is planned.

    ``rules`` is a resolved rule set rather than a package: whether a package can answer these
    questions at all is the rule adapter's decision and is made once, before anything is
    planned, so nothing here has a fallback to reach for.

    A project with no enabled supply arrangement produces determinations naming none. That is
    reported by the supply validation rather than restated here - two places saying the same
    thing is how they come to disagree.
    """

    service = VoltageEvidenceService()
    circuits = {net.id for net in project.net_classes if net.net_type is NetClassType.CIRCUIT}
    configurations = tuple(item.id for item in project.supply_configurations if item.enabled)
    preparation = tuple(step.text for step in rules.working_voltage_determination.preparation_steps)
    targets = [EvidenceTarget(net_id=net.id) for net in project.net_classes if net.id in circuits]
    targets += [
        EvidenceTarget(pair_id=pair.id)
        for pair in project.pairs
        if not pair.is_excluded and ({pair.net_a, pair.net_b} & circuits)
    ]
    return tuple(
        _determination(project, service, target, configurations, preparation, rules)
        for target in targets
    )


def _determination(
    project: Project,
    service: VoltageEvidenceService,
    target: EvidenceTarget,
    configurations: tuple[UUID, ...],
    preparation: tuple[str, ...],
    rules: VerificationRuleSet,
) -> WorkingVoltageDetermination:
    results = tuple(
        service.governing(project, target, quantity) for quantity in WORKING_VOLTAGE_QUANTITIES
    )
    unresolved = tuple(message for result in results for message in result.unresolved_inputs)
    # The design-side figures the determination is compared against: everything approved that
    # is not itself a measurement. A measurement is the thing being planned, not the
    # expectation it is judged against.
    expected = tuple(
        entry
        for result in results
        for entry in result.governing
        if entry.method is not VoltageEvidenceMethod.MEASUREMENT
    )
    points = tuple(
        sorted(
            {
                entry.measurement_points
                for result in results
                for entry in result.governing
                if entry.method is VoltageEvidenceMethod.MEASUREMENT
            }
        )
    )
    return WorkingVoltageDetermination(
        id=_determination_id(target),
        target=target,
        required_quantities=WORKING_VOLTAGE_QUANTITIES,
        supply_configuration_ids=configurations,
        operating_conditions=OPERATING_CONDITIONS,
        measurement_points=points,
        preparation_steps=preparation,
        expected_values=expected,
        status=_status(results),
        unresolved_inputs=unresolved,
        source_rule_ids=(rules.working_voltage_determination.id,),
    )


def _status(results: tuple[GoverningEvidenceResult, ...]) -> VerificationStatus:
    """How far the determination has got, read off the evidence behind it.

    Draft evidence outranks everything else. An entry nobody has approved is an open decision,
    and a determination that reported ``DESIGN_EVIDENCE_AVAILABLE`` while one sat against its
    target would be letting an unapproved figure stand in for an approved one.
    """

    if any(result.awaiting_approval for result in results):
        return VerificationStatus.ENGINEERING_REVIEW_REQUIRED
    governed = tuple(result for result in results if result.governing)
    if not governed:
        return VerificationStatus.PLANNED
    if len(governed) < len(results):
        return VerificationStatus.DESIGN_EVIDENCE_AVAILABLE
    measured = tuple(result for result in results if _is_measured(result))
    if len(measured) == len(results):
        return VerificationStatus.COMPLETE
    if measured:
        return VerificationStatus.MEASURED
    return VerificationStatus.DESIGN_EVIDENCE_AVAILABLE


def _is_measured(result: GoverningEvidenceResult) -> bool:
    return any(entry.method is VoltageEvidenceMethod.MEASUREMENT for entry in result.governing)


def _determination_id(target: EvidenceTarget) -> UUID:
    """A stable identity for the determination of ``target``'s working voltage.

    Derived from the target, exactly as a generated test id is derived from what the test is:
    determinations are recomputed on every load and never persisted, so an identity drawn at
    random would make two runs of the same project look like two different plans and would
    leave a report with nothing to diff against the last one.

    The rule revision is deliberately not part of it - unlike a test id, which changes when the
    package it was planned from is re-approved. Which working voltage is being established is a
    fact about the target, not about the package, and an id that moved under a re-approval
    would break the reference from a recorded measurement back to what it measured.
    """

    subject = f"pair:{target.pair_id}" if target.pair_id is not None else f"net:{target.net_id}"
    return uuid5(DETERMINATION_NAMESPACE, subject)


def _unresolved(
    quantity: VoltageQuantityKind,
    applicable: tuple[VoltageEvidence, ...],
    approved: tuple[VoltageEvidence, ...],
) -> tuple[str, ...]:
    drafts = sum(1 for entry in applicable if entry.approval_state is EvidenceApprovalState.DRAFT)
    if not approved:
        if applicable:
            message = (
                f"No {quantity.value} evidence for this target is approved for design; "
                f"{len(applicable)} recorded {_entries(len(applicable))} await a decision."
            )
            return (message,)
        return (f"No {quantity.value} evidence is recorded for this target.",)
    if drafts:
        # Reported even though a value was found. A draft above the governing figure is the
        # case this whole rule exists for, and a reader who is not told about it would take
        # the lower approved value for the last word.
        message = (
            f"Not every recorded {quantity.value} entry is approved for design: "
            f"{drafts} of {len(applicable)} await a decision and do not govern."
        )
        return (message,)
    return ()


def _entries(count: int) -> str:
    return "entry" if count == 1 else "entries"


def _larger(first: Decimal | None, second: Decimal | None) -> Decimal | None:
    candidates = [value for value in (first, second) if value is not None]
    return max(candidates) if candidates else None


def _governing_step(
    quantity: VoltageQuantityKind,
    applicable: tuple[VoltageEvidence, ...],
    governing: tuple[VoltageEvidence, ...],
    highest: Decimal,
) -> TraceStep:
    reason = f"{governing[0].source_reference} governs the approved {quantity.value}"
    if len(governing) > 1:
        others = ", ".join(entry.source_reference for entry in governing[1:])
        reason += f"; it is tied with {others}, and both are retained"
    stood_down = tuple(
        entry
        for entry in applicable
        if entry.approval_state is EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION
        and entry.value_v > highest
    )
    if stood_down:
        names = ", ".join(entry.source_reference for entry in stood_down)
        reason += f"; a higher value ({names}) is superseded with justification"
    return TraceStep(
        semantic_rule_id=GOVERNING_EVIDENCE_TRACE_ID,
        operation="max",
        symbolic=rf"\max({quantity.value})",
        substituted=", ".join(
            f"{entry.source_reference} = {entry.value_v} {_VOLTAGE_UNIT} "
            f"({entry.approval_state.value})"
            for entry in applicable
        ),
        inputs=tuple(
            Quantity(value=entry.value_v, unit=_VOLTAGE_UNIT)
            for entry in applicable
            if entry.approval_state is EvidenceApprovalState.APPROVED_FOR_DESIGN
        ),
        source_reference=None,
        output=Quantity(value=highest, unit=_VOLTAGE_UNIT),
        unrounded_value=highest,
        reason=reason,
    )


def _effective_step(
    quantity: VoltageQuantityKind,
    approved: Decimal | None,
    derived: Decimal,
    derived_source: str,
    effective: Decimal | None,
) -> TraceStep:
    assert effective is not None  # a derived value is present, so there is always an answer
    origin = derived_source or "the supply derivation"
    recorded = "no approved evidence" if approved is None else f"approved evidence = {approved}"
    return TraceStep(
        semantic_rule_id=EFFECTIVE_VOLTAGE_TRACE_ID,
        operation="max",
        symbolic=rf"\max({quantity.value}_\text{{evidence}}, {quantity.value}_\text{{derived}})",
        substituted=f"{recorded} {_VOLTAGE_UNIT}, {origin} = {derived} {_VOLTAGE_UNIT}",
        inputs=tuple(
            Quantity(value=value, unit=_VOLTAGE_UNIT)
            for value in (approved, derived)
            if value is not None
        ),
        source_reference=None,
        output=Quantity(value=effective, unit=_VOLTAGE_UNIT),
        unrounded_value=effective,
        reason=(
            f"The derived stress from {origin} is compared with the approved evidence and "
            "neither replaces the other"
        ),
    )


__all__ = [
    "DETERMINATION_NAMESPACE",
    "EFFECTIVE_VOLTAGE_TRACE_ID",
    "GOVERNING_EVIDENCE_TRACE_ID",
    "OPERATING_CONDITIONS",
    "WORKING_VOLTAGE_QUANTITIES",
    "GoverningEvidenceResult",
    "VoltageEvidenceService",
    "plan_working_voltage",
]
