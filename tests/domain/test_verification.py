"""The verification models' own invariants. No IEC content: every value here is invented."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.verification import (
    EvidenceApprovalState,
    EvidenceTarget,
    ProtectionImplementation,
    RoutineTestExemptionEvidence,
    SolidInsulationTestData,
    TestApplicability,
    TestApplication,
    TestClassification,
    TestKind,
    TestReferenceKind,
    VerificationStatus,
    VoltageEvidence,
    VoltageEvidenceMethod,
    VoltageQuantityKind,
    WorkingVoltageDetermination,
    build_test_id,
)

RECORDED_AT = datetime(2026, 3, 4, tzinfo=UTC)


def evidence(**overrides: object) -> VoltageEvidence:
    fields: dict[str, object] = {
        "id": uuid4(),
        "pair_id": uuid4(),
        "quantity_kind": VoltageQuantityKind.AC_RMS,
        "value_v": Decimal(12),
        "method": VoltageEvidenceMethod.CALCULATION,
        "operating_condition": "synthetic normal operation",
        "source_reference": "synthetic-calc-1",
        "recorded_at": RECORDED_AT,
        "approval_state": EvidenceApprovalState.DRAFT,
    }
    return VoltageEvidence.model_validate(fields | overrides)


# --- protection implementation --------------------------------------------------------


def test_every_protection_implementation_is_a_separate_choice() -> None:
    members = tuple(ProtectionImplementation)

    assert len(members) == len({member.value for member in members})
    # Enhanced protection is a level, not a member: the implementations that can provide it
    # stay distinguishable, so double insulation never collapses into reinforced.
    assert (
        ProtectionImplementation.DOUBLE_INSULATION
        is not ProtectionImplementation.REINFORCED_INSULATION
    )
    assert ProtectionImplementation.PROTECTIVE_SCREEN_PLUS_BASIC in members
    assert ProtectionImplementation.PROTECTIVE_IMPEDANCE in members
    assert ProtectionImplementation.OTHER_REVIEWED_MEANS in members


def test_a_protection_implementation_is_never_inferred_from_an_insulation_type() -> None:
    # There is no mapping function here on purpose: migration is issue #37 Task 2's job and it
    # marks what it migrates as needing review. Nothing in this module converts one to the
    # other, so nothing can do it silently.
    from insulation_coordination.domain import verification

    assert not [name for name in dir(verification) if "insulation_type" in name]


# --- evidence validation --------------------------------------------------------------


def test_evidence_names_exactly_one_target() -> None:
    net_id = uuid4()

    assert evidence(pair_id=None, net_id=net_id).target == EvidenceTarget(net_id=net_id)

    with pytest.raises(ValidationError, match="exactly one"):
        evidence(pair_id=uuid4(), net_id=net_id)
    with pytest.raises(ValidationError, match="exactly one"):
        evidence(pair_id=None, net_id=None)


@pytest.mark.parametrize("field", ("operating_condition", "source_reference"))
def test_evidence_without_its_reviewable_context_is_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        evidence(**{field: ""})


@pytest.mark.parametrize(
    "measurement_points, uncertainty",
    (("", "+/- 1 %"), ("synthetic probe point", ""), ("", "")),
)
def test_a_measurement_states_where_and_to_what_uncertainty(
    measurement_points: str, uncertainty: str
) -> None:
    with pytest.raises(ValidationError, match="measured"):
        evidence(
            method=VoltageEvidenceMethod.MEASUREMENT,
            measurement_points=measurement_points,
            tolerance_or_uncertainty=uncertainty,
        )


def test_a_complete_measurement_is_accepted() -> None:
    entry = evidence(
        method=VoltageEvidenceMethod.MEASUREMENT,
        measurement_points="synthetic probe point",
        tolerance_or_uncertainty="+/- 1 %",
    )

    assert entry.method is VoltageEvidenceMethod.MEASUREMENT


def test_a_calculated_entry_needs_no_measurement_detail() -> None:
    assert evidence().measurement_points == ""


def test_superseding_an_approved_value_states_why() -> None:
    with pytest.raises(ValidationError, match="justification"):
        evidence(approval_state=EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION)

    superseded = evidence(
        approval_state=EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION,
        approval_justification="synthetic review record",
    )

    assert superseded.approval_state is EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION


def test_evidence_values_are_positive_decimals() -> None:
    with pytest.raises(ValidationError):
        evidence(value_v=Decimal(0))
    with pytest.raises(ValidationError):
        evidence(value_v=1.5)


def test_an_evidence_id_survives_a_round_trip() -> None:
    entry = evidence()

    assert VoltageEvidence.model_validate(entry.model_dump()).id == entry.id


def test_evidence_is_immutable() -> None:
    with pytest.raises(ValidationError):
        evidence().value_v = Decimal(1)  # type: ignore[misc]


# --- statuses -------------------------------------------------------------------------


def test_no_status_or_applicability_reads_silence_as_nothing_to_do() -> None:
    assert VerificationStatus.ENGINEERING_REVIEW_REQUIRED in tuple(VerificationStatus)
    assert TestApplicability.ENGINEERING_INPUT_REQUIRED in tuple(TestApplicability)
    # Not required and not applicable stay distinct from the state where nobody has answered.
    assert len({member.value for member in TestApplicability}) == 4


def test_a_determination_carries_its_unresolved_inputs_beside_its_status() -> None:
    determination = WorkingVoltageDetermination(
        id=uuid4(),
        target=EvidenceTarget(pair_id=uuid4()),
        required_quantities=(VoltageQuantityKind.AC_RMS, VoltageQuantityKind.RECURRING_PEAK),
        status=VerificationStatus.ENGINEERING_REVIEW_REQUIRED,
        unresolved_inputs=("synthetic missing input",),
        source_rule_ids=("synthetic.rule",),
    )

    assert determination.status is VerificationStatus.ENGINEERING_REVIEW_REQUIRED
    assert determination.unresolved_inputs == ("synthetic missing input",)


def test_a_determination_keeps_design_evidence_beside_a_measurement() -> None:
    pair_id = uuid4()
    simulated = evidence(pair_id=pair_id, method=VoltageEvidenceMethod.SIMULATION)
    measured = evidence(
        pair_id=pair_id,
        method=VoltageEvidenceMethod.MEASUREMENT,
        value_v=Decimal(9),
        measurement_points="synthetic probe point",
        tolerance_or_uncertainty="+/- 1 %",
    )

    determination = WorkingVoltageDetermination(
        id=uuid4(),
        target=EvidenceTarget(pair_id=pair_id),
        required_quantities=(VoltageQuantityKind.AC_RMS,),
        expected_values=(simulated, measured),
        status=VerificationStatus.MEASURED,
    )

    assert {item.method for item in determination.expected_values} == {
        VoltageEvidenceMethod.SIMULATION,
        VoltageEvidenceMethod.MEASUREMENT,
    }


# --- deterministic test identity ------------------------------------------------------

NET_A = UUID("00000000-0000-4000-8000-00000000000a")
NET_B = UUID("00000000-0000-4000-8000-00000000000b")
NET_C = UUID("00000000-0000-4000-8000-00000000000c")


def an_id(**overrides: object) -> str:
    fields: dict[str, object] = {
        "test_kind": TestKind.AC_DIELECTRIC,
        "reference_kind": TestReferenceKind.ADJACENT_CIRCUIT,
        "classifications": (TestClassification.TYPE,),
        "high_side_net_ids": (NET_A,),
        "low_side_net_ids": (NET_B,),
        "rule_revision": "synthetic-revision-1",
    }
    return build_test_id(**(fields | overrides))  # type: ignore[arg-type]


def test_the_same_test_gets_the_same_id_every_time() -> None:
    assert an_id() == an_id()


def test_the_caller_s_ordering_does_not_change_an_id() -> None:
    assert an_id(
        high_side_net_ids=(NET_A, NET_C),
        classifications=(TestClassification.TYPE, TestClassification.SAMPLE),
    ) == an_id(
        high_side_net_ids=(NET_C, NET_A),
        classifications=(TestClassification.SAMPLE, TestClassification.TYPE),
    )


def test_swapping_the_two_sides_is_a_different_test() -> None:
    assert an_id() != an_id(high_side_net_ids=(NET_B,), low_side_net_ids=(NET_A,))


@pytest.mark.parametrize(
    "overrides",
    (
        {"test_kind": TestKind.DC_DIELECTRIC},
        {"reference_kind": TestReferenceKind.PE_BONDED_ACCESSIBLE_PART},
        {"classifications": (TestClassification.ROUTINE,)},
        {"high_side_net_ids": (NET_C,)},
        {"low_side_net_ids": (NET_C,)},
        {"rule_revision": "synthetic-revision-2"},
    ),
    ids=("kind", "reference", "classification", "high-side", "low-side", "revision"),
)
def test_every_identity_ingredient_changes_the_id(overrides: dict[str, object]) -> None:
    assert an_id(**overrides) != an_id()


def test_an_id_names_its_kind_so_a_schedule_row_is_readable() -> None:
    assert an_id().startswith(f"{TestKind.AC_DIELECTRIC.value}-")


def test_covered_pairs_do_not_belong_to_a_test_identity() -> None:
    # Deduplication merges equivalent applications and keeps every covered pair. An id that
    # varied with that set would change when a second pair joined an unchanged test.
    application = TestApplication(
        test_id=an_id(),
        covered_pair_ids=(uuid4(),),
        test_kind=TestKind.AC_DIELECTRIC,
        classifications=(TestClassification.TYPE,),
        high_side_net_ids=(NET_A,),
        low_side_net_ids=(NET_B,),
        reference_kind=TestReferenceKind.ADJACENT_CIRCUIT,
        applicability=TestApplicability.REQUIRED,
    )
    merged = application.model_copy(
        update={"covered_pair_ids": (*application.covered_pair_ids, uuid4())}
    )

    assert merged.test_id == application.test_id


def test_a_test_application_needs_an_id() -> None:
    with pytest.raises(ValidationError):
        TestApplication(
            test_id="",
            test_kind=TestKind.IMPULSE_WITHSTAND,
            reference_kind=TestReferenceKind.WITHIN_CIRCUIT,
            applicability=TestApplicability.REQUIRED,
        )


# --- solid insulation and the routine exemption ---------------------------------------


def test_an_undeclared_solid_insulation_field_is_not_a_negative_answer() -> None:
    data = SolidInsulationTestData()

    assert data.present is None
    assert data.material_pd_exempt is None


def test_a_claimed_material_exemption_names_its_reference() -> None:
    with pytest.raises(ValidationError, match="material reference"):
        SolidInsulationTestData(material_pd_exempt=True)

    exempt = SolidInsulationTestData(
        material_pd_exempt=True, material_reference="synthetic material sheet"
    )

    assert exempt.material_reference == "synthetic material sheet"


def test_a_material_that_is_not_exempt_needs_no_reference() -> None:
    assert SolidInsulationTestData(material_pd_exempt=False).material_reference is None


def test_an_incomplete_exemption_record_is_constructible_so_it_can_be_reported() -> None:
    record = RoutineTestExemptionEvidence(subassemblies_routine_tested=True)

    assert record.subassemblies_routine_tested
    assert record.subassembly_evidence_reference == ""
    assert not record.assembled_type_test_passed
    assert record.reviewed_at is None
