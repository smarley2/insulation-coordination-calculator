"""Which electrodes a dielectric test is applied between, and when two applications are one.

A pair says which two net classes an insulation sits between. A test says which *conductors*
are tied together and raised, and which are tied together and held at the reference. The two
are not the same statement, and this module is the translation.

*The high side is a group, not a net.* Circuits inside one galvanic domain are not isolated
from each other, so a test between "the circuit" and an accessible part puts every circuit net
of that domain on the high side. Where the supply propagation has already worked out which
domains form one electrical set - domains a barrier records no isolation between - that wider
set is what groups, because re-deriving it here would be a second answer free to disagree with
the one the stresses were propagated through. Without a propagation the declared domain stands
on its own; that is #35's own statement about the project, not a guess about it.

Grouping is what makes deduplication mean anything. Two pairs are always two different net
pairs, so applications keyed on a pair could never coincide; applications keyed on the
*electrode sets* coincide exactly when the same physical test would be performed twice, and
that is the duplicate a schedule must not carry. Every pair that was folded in is kept in
:attr:`~insulation_coordination.domain.verification.TestApplication.covered_pair_ids`, so a
reader still finds their pair in the schedule.

*Identity is :func:`~insulation_coordination.domain.verification.build_test_id` and nothing
else.* Two applications are the same test when that id agrees. A second identity computed here
would be free to disagree with the one a report quotes. Where two applications share an id and
still differ - the same electrodes verified from two pairs, one of which carries a verified
impulse override - the merge keeps the more severe answer and says so, rather than letting
whichever was generated first silently win.

No rule is read here and no normative value appears. The preparation instructions this module
writes are this application's own words for connecting the equipment; every instruction that
comes from the standard arrives on a procedure rule and is appended by the caller.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final
from uuid import UUID

from insulation_coordination.calculation.stress_propagation import DomainStressMap
from insulation_coordination.domain.enums import NetClassType
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.topology import domain_for_net
from insulation_coordination.domain.trace import CalculationWarning
from insulation_coordination.domain.verification import (
    TestApplicability,
    TestApplication,
    TestReferenceKind,
)

#: The warning raised when two applications share an identity and disagree about what is
#: applied. A code rather than prose at the call site, so a report can group them.
CONFLICTING_APPLICATION_WARNING: Final = "verification_test_application_conflict"

#: What the low side of a test is, for each non-circuit net type. A circuit on both sides is
#: the one relationship this mapping cannot state, because it is decided by the *pair* rather
#: than by either net - see :func:`reference_kind_for`.
_LOW_SIDE_KINDS: Final[Mapping[NetClassType, TestReferenceKind]] = {
    NetClassType.PE_BONDED_CONDUCTIVE_PART: TestReferenceKind.PE_BONDED_ACCESSIBLE_PART,
    NetClassType.ACCESSIBLE_CONDUCTIVE_PART: TestReferenceKind.ACCESSIBLE_CONDUCTIVE_PART,
    NetClassType.ACCESSIBLE_INSULATING_SURFACE: (
        TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL
    ),
}

#: How settled each applicability is. A merge keeps the least settled of the answers it folds
#: together: a test one pair needs an engineering input for is not settled by another pair
#: happening to have supplied one.
_APPLICABILITY_ORDER: Final[Mapping[TestApplicability, int]] = {
    TestApplicability.NOT_APPLICABLE: 0,
    TestApplicability.NOT_REQUIRED: 1,
    TestApplicability.REQUIRED: 2,
    TestApplicability.ENGINEERING_INPUT_REQUIRED: 3,
}


class TestSubject(FrozenModel):
    """One pair, restated as the electrodes a test is applied between.

    ``high_side_net_ids`` is the whole live group and always contains the pair's circuit net.
    ``low_side_net_ids`` is the reference net, grouped the same way when it is itself a
    circuit and left alone when it is not: nothing in the project states that two accessible
    parts are bonded to each other, and assuming it would plan a test nobody described.
    """

    pair_id: UUID
    pair_key: str
    reference_kind: TestReferenceKind
    high_side_net_ids: tuple[UUID, ...]
    low_side_net_ids: tuple[UUID, ...]
    preparation_steps: tuple[str, ...] = ()


def reference_kind_for(first: NetClassType, second: NetClassType) -> TestReferenceKind | None:
    """What the pair of these two net types is, as a test relationship, in either order.

    ``None`` where neither side is a circuit: there is no live part to raise, so no dielectric
    test exists between them. ``WITHIN_CIRCUIT`` is deliberately never returned - it is not a
    relationship between two net classes but a question asked about one net on its own, and it
    reaches the schedule through a working-voltage determination whose target is a net.
    """

    circuits = (first is NetClassType.CIRCUIT) + (second is NetClassType.CIRCUIT)
    if circuits == 2:
        return TestReferenceKind.ADJACENT_CIRCUIT
    if circuits == 0:
        return None
    reference = second if first is NetClassType.CIRCUIT else first
    return _LOW_SIDE_KINDS[reference]


def live_group(
    project: Project,
    net_id: UUID,
    domain_stresses: DomainStressMap | None = None,
) -> tuple[UUID, ...]:
    """Every circuit net that is tied to ``net_id`` on the high side of a test.

    A net outside every declared domain answers with itself alone. That is the state a project
    predating the topology model is in, and it is not an error: nothing has been said about
    what that net is connected to, so nothing is connected to it here.
    """

    domain = domain_for_net(project, net_id)
    if domain is None:
        return (net_id,)
    stress = None if domain_stresses is None else domain_stresses.for_domain(domain.id)
    group = {domain.id} if stress is None else set(stress.component_domain_ids)
    return tuple(
        net.id
        for net in project.net_classes
        if net.net_type is NetClassType.CIRCUIT and net.galvanic_domain_id in group
    )


def subjects_for(
    project: Project,
    domain_stresses: DomainStressMap | None = None,
) -> tuple[TestSubject, ...]:
    """Every pair of ``project`` that a dielectric test is applied to, in project order.

    A pair recorded as never adjacent is skipped: it carries a decision with a justification
    already, and planning a test for insulation the engineer excluded would ask for work
    nobody asked for. A pair of two non-circuit nets is skipped because there is nothing to
    raise between them.

    Two circuits of one electrical set are the one case where nothing is grouped: each side's
    group is the other's, so grouping either would put the same conductor on both sides of the
    test. Their insulation is between those two nets and nowhere else, and that is what is
    planned.
    """

    net_types = {net.id: net.net_type for net in project.net_classes}
    subjects: list[TestSubject] = []
    for pair in project.pairs:
        if pair.is_excluded:
            continue
        kind = reference_kind_for(net_types[pair.net_a], net_types[pair.net_b])
        if kind is None:
            continue
        high_net, low_net = (
            (pair.net_a, pair.net_b)
            if net_types[pair.net_a] is NetClassType.CIRCUIT
            else (pair.net_b, pair.net_a)
        )
        high = live_group(project, high_net, domain_stresses)
        low = (
            live_group(project, low_net, domain_stresses)
            if net_types[low_net] is NetClassType.CIRCUIT
            else (low_net,)
        )
        if set(high) & set(low):
            high, low = (high_net,), (low_net,)
        subjects.append(
            TestSubject(
                pair_id=pair.id,
                pair_key=pair.key,
                reference_kind=kind,
                high_side_net_ids=high,
                low_side_net_ids=low,
                preparation_steps=_preparation(project, kind, high, low),
            )
        )
    return tuple(subjects)


def deduplicate(
    applications: Iterable[TestApplication],
) -> tuple[tuple[TestApplication, ...], tuple[CalculationWarning, ...]]:
    """One application per identity, every covered pair retained, in a stable order.

    Applications sharing a ``test_id`` are the same physical test, so they are folded into one
    that names every pair it covers. Where they disagree about what is applied - the same
    electrodes reached from two pairs, one carrying a verified impulse override - the fold
    keeps the more severe voltage and the least settled applicability, and returns a warning
    naming both figures. Nothing is dropped silently: a schedule that quietly kept the first
    of two answers would be indistinguishable from one where they agreed.
    """

    merged: dict[str, TestApplication] = {}
    warnings: list[CalculationWarning] = []
    for application in applications:
        existing = merged.get(application.test_id)
        if existing is None:
            merged[application.test_id] = application
            continue
        merged[application.test_id] = _fold(existing, application, warnings)
    return tuple(sorted(merged.values(), key=_sort_key)), tuple(warnings)


def _fold(
    existing: TestApplication,
    arriving: TestApplication,
    warnings: list[CalculationWarning],
) -> TestApplication:
    """Combine two applications of one identity, losing nothing either of them states."""

    voltage = existing.voltage
    if arriving.voltage is not None and (voltage is None or arriving.voltage.value > voltage.value):
        voltage = arriving.voltage
    if (
        existing.voltage is not None
        and arriving.voltage is not None
        and existing.voltage.value != arriving.voltage.value
    ):
        warnings.append(
            CalculationWarning(
                code=CONFLICTING_APPLICATION_WARNING,
                message=(
                    f"Test {existing.test_id} is applied between the same conductors by more "
                    f"than one pair, and they state different voltages "
                    f"({existing.voltage.value} {existing.voltage.unit} and "
                    f"{arriving.voltage.value} {arriving.voltage.unit}). The more severe "
                    "figure is planned; a value recorded against one pair of a connected "
                    "group does not lower the test the group as a whole is given."
                ),
            )
        )
    return existing.model_copy(
        update={
            "covered_pair_ids": _ordered((*existing.covered_pair_ids, *arriving.covered_pair_ids)),
            "voltage": voltage,
            "applicability": max(
                (existing.applicability, arriving.applicability),
                key=lambda item: _APPLICABILITY_ORDER[item],
            ),
            "preparation_steps": _unique(
                (*existing.preparation_steps, *arriving.preparation_steps)
            ),
            "unresolved_inputs": _unique(
                (*existing.unresolved_inputs, *arriving.unresolved_inputs)
            ),
            "source_rule_ids": _unique((*existing.source_rule_ids, *arriving.source_rule_ids)),
            "trace_steps": (*existing.trace_steps, *arriving.trace_steps),
        }
    )


def _sort_key(application: TestApplication) -> tuple[str, str, str, str, str]:
    """Test kind, then classification, then the canonical net sets, then the identity.

    Stable across runs and independent of the order the pairs happened to be generated in,
    which is what lets two schedules of one project be compared line by line.
    """

    return (
        application.test_kind.value,
        ",".join(item.value for item in application.classifications),
        ",".join(str(item) for item in application.high_side_net_ids),
        ",".join(str(item) for item in application.low_side_net_ids),
        application.test_id,
    )


def _preparation(
    project: Project,
    kind: TestReferenceKind,
    high_side_net_ids: Sequence[UUID],
    low_side_net_ids: Sequence[UUID],
) -> tuple[str, ...]:
    """This application's own connection instructions for one topology.

    Everything the standard says about preparing a specimen arrives on a procedure rule and is
    appended by the caller. What is written here is how *this project's* conductors are tied
    together, which no clause can state because no clause has seen the project.
    """

    names = {net.id: net.name for net in project.net_classes}
    steps = [*_side_steps(names, high_side_net_ids, "high")]
    if kind is TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL:
        steps.append(
            f"Wrap {names[low_side_net_ids[0]]} in conductive foil and connect the foil as the "
            "low side. Record the foil's area and location with the test result."
        )
    else:
        steps.extend(_side_steps(names, low_side_net_ids, "low"))
    return tuple(steps)


def _side_steps(names: Mapping[UUID, str], net_ids: Sequence[UUID], side: str) -> tuple[str, ...]:
    """How one side's conductors are connected, and what has to be bridged to reach them all."""

    if len(net_ids) == 1:
        return (f"Connect {names[net_ids[0]]} as the {side} side.",)
    joined = ", ".join(names[net_id] for net_id in net_ids)
    return (
        (
            f"Connect the live parts of {joined} together as the {side} side: no galvanic "
            "barrier separates them, so they are one conductor for this test."
        ),
        (
            f"Bridge or open every contact and semiconductor between the {side}-side live "
            "parts, so the whole group is at test potential rather than only the part nearest "
            "the source."
        ),
    )


def _ordered(values: Iterable[UUID]) -> tuple[UUID, ...]:
    return tuple(sorted(set(values), key=str))


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = [
    "CONFLICTING_APPLICATION_WARNING",
    "TestSubject",
    "deduplicate",
    "live_group",
    "reference_kind_for",
    "subjects_for",
]
