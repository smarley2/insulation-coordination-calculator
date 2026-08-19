"""What a dielectric verification plan is made of, before anything computes one.

Issue #37 separates four things the existing calculator conflated into one insulation type:
the *protection requirement* the standard places on a pair, the *physical implementation* an
engineer chose to meet it, the *spacing path* the clearance engine already dimensions, and the
*tests* that verify the result. This module carries the vocabulary and the records for the
last three; the requirement itself is read from the approved package.

Nothing here reads a rule, computes a plan, or holds a normative value. Every enum member is
this application's own neutral name for a choice a user makes or a state a record is in, and
every model is a container the engine in later slices fills. That is deliberate: a model that
knew a test voltage would be a second place for the standard to live.

Two properties are load-bearing and are enforced here rather than left to the engine.

*Evidence is auditable.* A :class:`VoltageEvidence` entry names one target, one quantity and
one method, and it cannot be constructed without the operating condition and source reference
that make it reviewable. A measurement additionally carries where it was measured and to what
uncertainty, because a measured number without those is not evidence of anything. A record
that supersedes an approved value has to say why.

*A generated test identity is derived, never drawn.* :func:`build_test_id` is the only way a
test application should get its id, so the same test planned twice from the same package is
the same test - a schedule that changed identity on every recomputation could not be
compared against the last one, and no report could be diffed.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.quantities import PositiveDecimal
from insulation_coordination.domain.trace import Quantity, TraceStep


class ProtectionImplementation(StrEnum):
    """The physical means an engineer selected to meet a protection requirement.

    Never derived from a decisive voltage class or from topology: the standard states what
    level of protection is required, and which construction provides it is an engineering
    decision this application records rather than makes.

    ``DOUBLE_INSULATION`` stays two separately assessed protective means and is never
    collapsed into ``REINFORCED_INSULATION``; ``PROTECTIVE_SCREEN_PLUS_BASIC`` needs explicit
    screen topology and a separate assessment per side; and ``PROTECTIVE_IMPEDANCE`` produces
    no spacing result at all, so its verification stays a separately disclosed engineering
    item rather than an invented dimension.
    """

    FUNCTIONAL_INSULATION = "functional_insulation"
    BASIC_INSULATION = "basic_insulation"
    SUPPLEMENTARY_INSULATION = "supplementary_insulation"
    DOUBLE_INSULATION = "double_insulation"
    REINFORCED_INSULATION = "reinforced_insulation"
    PROTECTIVE_SCREEN_PLUS_BASIC = "protective_screen_plus_basic"
    PROTECTIVE_IMPEDANCE = "protective_impedance"
    OTHER_REVIEWED_MEANS = "other_reviewed_means"


class VoltageEvidenceMethod(StrEnum):
    """How one voltage figure was arrived at.

    Deliberately not
    :class:`~insulation_coordination.domain.enums.VerificationMethod`, which answers a
    different question: that enum says how a *requirement* was verified and includes a
    document review, while this one says where a *number* came from and has to distinguish an
    engineering estimate from a measurement. Design evidence and measured evidence coexist;
    neither erases the other.
    """

    ENGINEERING_ESTIMATE = "engineering_estimate"
    CALCULATION = "calculation"
    SIMULATION = "simulation"
    MEASUREMENT = "measurement"


class VoltageQuantityKind(StrEnum):
    """Which voltage quantity a figure states. Two figures of different kinds never compare."""

    AC_RMS = "ac_rms"
    DC_MEAN = "dc_mean"
    RECURRING_PEAK = "recurring_peak"
    IMPULSE = "impulse"
    TEMPORARY_OVERVOLTAGE = "temporary_overvoltage"


class EvidenceApprovalState(StrEnum):
    """Whether one evidence entry may govern a design value.

    Only ``APPROVED_FOR_DESIGN`` entries are considered when a governing value is chosen.
    ``SUPERSEDED_WITH_JUSTIFICATION`` is how a higher approved value is stood down so a lower
    one can govern - it is a recorded decision with a reason attached, never a deletion.
    """

    DRAFT = "draft"
    APPROVED_FOR_DESIGN = "approved_for_design"
    SUPERSEDED_WITH_JUSTIFICATION = "superseded_with_justification"


class VerificationStatus(StrEnum):
    """How far one verification item has got.

    ``ENGINEERING_REVIEW_REQUIRED`` is what a missing input produces. There is no status that
    means "nothing needed because nothing is known": an unanswered question is reported, not
    resolved optimistically.
    """

    PLANNED = "planned"
    DESIGN_EVIDENCE_AVAILABLE = "design_evidence_available"
    MEASURED = "measured"
    ENGINEERING_REVIEW_REQUIRED = "engineering_review_required"
    COMPLETE = "complete"


class TestApplicability(StrEnum):
    """Whether one test applies to one pair.

    ``NOT_APPLICABLE`` means the rule settles that the test cannot apply here.
    ``ENGINEERING_INPUT_REQUIRED`` means the rule needs something nobody has supplied yet, and
    is never reported as ``NOT_REQUIRED``: the two look the same in a schedule and mean
    opposite things to whoever has to sign it.
    """

    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    ENGINEERING_INPUT_REQUIRED = "engineering_input_required"
    NOT_APPLICABLE = "not_applicable"


class TestClassification(StrEnum):
    """Whether a test is performed on a type, on every unit, or on a sample.

    These are this application's names. An approved package states the same three in its own
    vocabulary, and the mapping between the two lives at the rule-package seam so this module
    stays free of any package's naming.
    """

    TYPE = "type"
    ROUTINE = "routine"
    SAMPLE = "sample"


class TestKind(StrEnum):
    """What one generated test application does."""

    WORKING_VOLTAGE_DETERMINATION = "working_voltage_determination"
    IMPULSE_WITHSTAND = "impulse_withstand"
    #: Verification that a claimed reduction of the overvoltage does what is claimed for it.
    #: Its own kind rather than a variant of the impulse withstand test: it is applied to the
    #: equipment rather than between one pair's electrodes, it is judged on what the reduction
    #: measures rather than on whether the insulation held, and a schedule that folded the two
    #: together would let one result be read as the other.
    TRANSIENT_OVERVOLTAGE_REDUCTION = "transient_overvoltage_reduction"
    AC_DIELECTRIC = "ac_dielectric"
    DC_DIELECTRIC = "dc_dielectric"
    PARTIAL_DISCHARGE = "partial_discharge"
    INTERNAL_SPD_MONITORING = "internal_spd_monitoring"


class TestReferenceKind(StrEnum):
    """What the low side of a test application is, as a topology relationship.

    Not :class:`~insulation_coordination.domain.enums.NetClassType`, which classifies a net on
    its own: two circuit nets can stand in two different relationships, and the test topology
    has to tell a within-circuit application apart from a circuit-to-adjacent-circuit one.
    ``ACCESSIBLE_INSULATING_SURFACE_FOIL`` is named for the preparation it implies, because a
    test against an insulating surface only exists once conductive foil is wrapped around it.

    ``DVC_AS_ADJACENT_CIRCUIT`` is its own relationship rather than a flavour of
    ``ADJACENT_CIRCUIT`` because the standard tests it differently: a DVC A-s circuit is
    excepted from the tests against accessible parts and is verified against its adjacent
    circuits instead, its row is keyed on the higher-voltage circuit of the two rather than on
    the circuit under test, and its type test reads the stronger column. A plan that could not
    name the case could not apply any of that.
    """

    WITHIN_CIRCUIT = "within_circuit"
    ADJACENT_CIRCUIT = "adjacent_circuit"
    DVC_AS_ADJACENT_CIRCUIT = "dvc_as_adjacent_circuit"
    PE_BONDED_ACCESSIBLE_PART = "pe_bonded_accessible_part"
    ACCESSIBLE_CONDUCTIVE_PART = "accessible_conductive_part"
    ACCESSIBLE_INSULATING_SURFACE_FOIL = "accessible_insulating_surface_foil"


class EvidenceTarget(FrozenModel):
    """The one thing a voltage figure or a determination is about: a pair, or a net.

    Exactly one is set. A target that named both would make "the governing value for this
    target" ambiguous, and one that named neither could not be looked up at all.
    """

    pair_id: UUID | None = None
    net_id: UUID | None = None

    @model_validator(mode="after")
    def _exactly_one_subject(self) -> Self:
        if (self.pair_id is None) == (self.net_id is None):
            raise ValueError("A target names exactly one of a pair or a net")
        return self


class VoltageEvidence(FrozenModel):
    """One recorded voltage figure, with everything a reviewer needs to judge it.

    The id is immutable and is carried into reports: an entry a reader queries in a report has
    to be findable in the project that produced it.
    """

    id: UUID
    pair_id: UUID | None = None
    net_id: UUID | None = None
    quantity_kind: VoltageQuantityKind
    value_v: PositiveDecimal
    method: VoltageEvidenceMethod
    operating_condition: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    measurement_points: str = ""
    tolerance_or_uncertainty: str = ""
    recorded_at: datetime
    approval_state: EvidenceApprovalState
    approval_justification: str = ""
    notes: str = ""

    @property
    def target(self) -> EvidenceTarget:
        return EvidenceTarget(pair_id=self.pair_id, net_id=self.net_id)

    @model_validator(mode="after")
    def _is_reviewable(self) -> Self:
        # Constructing the target is the check: it refuses both and neither, in the one place
        # that rule is written.
        _ = self.target
        if self.method is VoltageEvidenceMethod.MEASUREMENT and not (
            self.measurement_points.strip() and self.tolerance_or_uncertainty.strip()
        ):
            raise ValueError("A measurement states where it was measured and to what uncertainty")
        if (
            self.approval_state is EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION
            and not self.approval_justification.strip()
        ):
            raise ValueError("Superseding an approved value states the justification")
        return self


class WorkingVoltageDetermination(FrozenModel):
    """The plan for establishing one working voltage, and how far it has got.

    ``expected_values`` holds the design-side figures the determination is compared against.
    They are evidence entries like any other, so a later measurement sits beside them rather
    than overwriting them.
    """

    id: UUID
    target: EvidenceTarget
    required_quantities: tuple[VoltageQuantityKind, ...]
    supply_configuration_ids: tuple[UUID, ...] = ()
    #: The conditions the working voltage itself is established under. The standard scopes it
    #: to the rated worst operating conditions of intended use and names nothing else.
    operating_conditions: tuple[str, ...] = ()
    #: The conditions that are *not* operating conditions of the working voltage, and whose
    #: voltages are collected as their own quantity. They belong to the decisive-voltage-class
    #: and protection-requirement determination, which the standard states under normal,
    #: abnormal and single-fault conditions alike. Kept beside the working voltage rather than
    #: dropped: an abnormal figure nobody asked for is one nobody records, and the class limits
    #: are judged against it.
    class_limit_conditions: tuple[str, ...] = ()
    measurement_points: tuple[str, ...] = ()
    preparation_steps: tuple[str, ...] = ()
    expected_values: tuple[VoltageEvidence, ...] = ()
    status: VerificationStatus
    unresolved_inputs: tuple[str, ...] = ()
    source_rule_ids: tuple[str, ...] = ()


class TestApplication(FrozenModel):
    """One test, applied between one set of high-side nets and one set of low-side nets.

    ``covered_pair_ids`` is what survives deduplication: two pairs whose test is identical
    produce one application naming both, so a reader can still see that their pair was tested.
    ``test_id`` comes from :func:`build_test_id` and is stable across recomputation.
    """

    test_id: str = Field(min_length=1)
    covered_pair_ids: tuple[UUID, ...] = ()
    test_kind: TestKind
    classifications: tuple[TestClassification, ...] = ()
    high_side_net_ids: tuple[UUID, ...] = ()
    low_side_net_ids: tuple[UUID, ...] = ()
    reference_kind: TestReferenceKind
    voltage: Quantity | None = None
    waveform: str | None = None
    polarity: str | None = None
    duration: str | None = None
    repetitions: str | None = None
    preparation_steps: tuple[str, ...] = ()
    applicability: TestApplicability
    unresolved_inputs: tuple[str, ...] = ()
    source_rule_ids: tuple[str, ...] = ()
    trace_steps: tuple[TraceStep, ...] = ()


class SolidInsulationTestData(FrozenModel):
    """What an engineer has declared about a pair's solid insulation, if anything.

    Every field is optional and ``None`` means "not declared", which is a different answer
    from ``False``: the partial-discharge assessment reports a missing declaration as an
    engineering input rather than reading it as an exemption.

    This application does not calculate or approve a thickness. The thickness is recorded so a
    procedure that asks for it has an answer, not so anything can be dimensioned from it.
    """

    present: bool | None = None
    minimum_thickness_mm: PositiveDecimal | None = None
    material_pd_exempt: bool | None = None
    layer_count: int | None = Field(default=None, ge=1)
    separately_testable_layers: bool | None = None
    material_reference: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _exemption_is_evidenced(self) -> Self:
        if self.material_pd_exempt and not (self.material_reference or "").strip():
            raise ValueError("A claimed material exemption names its material reference")
        return self


class RoutineTestExemptionEvidence(FrozenModel):
    """The engineer's answers to the conditions an assembled-equipment routine exemption needs.

    Half-answered on purpose: nothing here is required, because the assessment's job is to say
    *which* condition is missing and keep the routine test in the schedule until none is. A
    model that refused an incomplete record would leave that assessment with nothing to read.
    """

    subassemblies_routine_tested: bool = False
    subassembly_evidence_reference: str = ""
    assembly_cannot_compromise_insulation: bool = False
    assembly_justification: str = ""
    assembled_type_test_passed: bool = False
    assembled_type_test_reference: str = ""
    reviewer: str = ""
    reviewed_at: datetime | None = None


#: Separates the parts of the canonical string :func:`build_test_id` digests. A character no
#: identifier, UUID or enum value in the canonical form can contain, so two different inputs
#: cannot canonicalise to one string.
_ID_SEPARATOR = "|"


def build_test_id(
    *,
    test_kind: TestKind,
    reference_kind: TestReferenceKind,
    classifications: Iterable[TestClassification],
    high_side_net_ids: Iterable[UUID],
    low_side_net_ids: Iterable[UUID],
    rule_revision: str,
) -> str:
    """A stable identity for one generated test application.

    Derived, never drawn: the same test planned twice from the same package gets the same id,
    so two schedules can be compared and a report can be diffed against the last one. A random
    UUID would make every recomputation look like a different test.

    The two net sides are sorted independently - which side is high is part of what the test
    is - and the classifications are sorted too, so the caller's ordering cannot change an
    identity. ``rule_revision`` is the caller's identity for the governing rules, normally the
    approved package's hash: the same topology verified against a re-approved package is a
    different test, and saying so is the point.

    ``covered_pair_ids`` is deliberately absent. Deduplication merges equivalent applications
    and keeps every covered pair, so an id that varied with the covered set would change the
    moment a second pair joined a test that had not otherwise changed.
    """

    parts = (
        test_kind.value,
        reference_kind.value,
        ",".join(sorted(item.value for item in classifications)),
        ",".join(sorted(str(item) for item in high_side_net_ids)),
        ",".join(sorted(str(item) for item in low_side_net_ids)),
        rule_revision,
    )
    digest = sha256(_ID_SEPARATOR.join(parts).encode("utf-8")).hexdigest()
    # The kind stays readable so a schedule row can be recognised without a lookup; the digest
    # carries the rest. Truncated because an id is read by people, and a collision would need
    # two different canonical forms to agree over 64 bits.
    return f"{test_kind.value}-{digest[:16]}"


__all__ = [
    "EvidenceApprovalState",
    "EvidenceTarget",
    "ProtectionImplementation",
    "RoutineTestExemptionEvidence",
    "SolidInsulationTestData",
    "TestApplicability",
    "TestApplication",
    "TestClassification",
    "TestKind",
    "TestReferenceKind",
    "VerificationStatus",
    "VoltageEvidence",
    "VoltageEvidenceMethod",
    "VoltageQuantityKind",
    "WorkingVoltageDetermination",
    "build_test_id",
]
