"""The dielectric verification plan one project asks of one approved rule package.

Impulse and AC/DC dielectric applications are generated here, over the electrodes
:mod:`~insulation_coordination.calculation.test_topology` works out, from the stresses issue
#36 derived and the procedures and tables issue #34 published. What comes out is a schedule
somebody can perform, together with everything that stopped it from being complete.

Four properties are the reason this module is shaped the way it is.

*The supply is consumed, never re-derived.* The impulse a pair is tested at is the one the
supply arrangements produced, propagated across the project's barriers and adjusted by any
verified override recorded at that pair - already treated for the pair's insulation class, so
nothing here multiplies it again. Deriving a second figure here would give the schedule the
chance to disagree with the calculation it is verifying.

*The requirement is read, never derived from the implementation.* What level of protection a
pair needs comes from the package's own Table 3, asked for the classes on either side and the
relationship between them; what an engineer selected to provide it is a separate record. The
two are compared, and a construction that does not reach the level required is a finding the
plan reports. Deriving one from the other - which is what "enhanced" alone amounted to - would
mean a wrong implementation could never be detected, because the requirement would move to
meet it.

*Enhanced protection does not collapse into reinforced insulation.* Which construction an
engineer selected and which spacing path the clearance engine dimensioned are two separate
records, and where they disagree the plan says so instead of picking one. Double insulation is
two protective means; the combined requirement is what this plan can verify between the pair's
two nets, and the plan states outright that the constituents are not covered by it.

*Every value comes from the package's own lookup.* A dielectric test voltage is read from the
table the rule adapter resolved, through the evaluator, using the selection the table's own
reviewed interpolation permits. Nothing here carries a normative number and nothing here has a
fallback: a lookup the package refuses becomes an unresolved input naming the refusal.

*What is missing is reported, never assumed away.* An unselected protection implementation, a
working voltage nobody recorded, a duration no resolved rule states - each is an unresolved
input on the application it belongs to. There is no path from "nothing is known" to
``NOT_REQUIRED``.

*An obligation with no rule behind it is still stated.* Several subclauses oblige something the
recipe projects no rule for: the body of the AC/DC test subclause outside its two value tables,
the clearance and visual-inspection subclauses, the protective-impedance test. Each of those
reached the schedule as nothing at all,
which for a preparation instruction means a test performed wrongly rather than a test left
unplanned. They are restated here, in this application's own words, against the identifier that
obliges them - see :func:`_clause_obligations`. Where the deciding
input is one the project holds it narrows the statement; where it is not, the statement says so.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Final
from uuid import UUID

from insulation_coordination.calculation.clearance import CalculationError
from insulation_coordination.calculation.engine import (
    SupplyDerivation,
    resolve_supply_effective_case,
)
from insulation_coordination.calculation.high_frequency import (
    PART4_FREQUENCY_THRESHOLD_HZ,
    altitude_correction_band,
)
from insulation_coordination.calculation.impulse_override import SpdMonitoringDependency
from insulation_coordination.calculation.partial_discharge import (
    PartialDischargeOutcome,
    assess_partial_discharge,
)
from insulation_coordination.calculation.routine_exemption import (
    RoutineExemptionAssessment,
    assess_routine_exemption,
)
from insulation_coordination.calculation.special_procedures import (
    decorate,
    monitoring_preparation,
)
from insulation_coordination.calculation.stress_propagation import (
    EffectivePairStressResolution,
)
from insulation_coordination.calculation.test_topology import (
    TestSubject,
    deduplicate,
    subjects_for,
)
from insulation_coordination.calculation.verification_rules import (
    VerificationRuleSet,
    VoltageForm,
    VoltageTablePair,
    classifications_of,
    read_verification_rules,
)
from insulation_coordination.calculation.voltage_evidence import (
    VoltageEvidenceService,
    plan_working_voltage,
)
from insulation_coordination.domain.dvc import (
    ProtectionGuidance,
    ProtectionRequirement,
    protection_cells,
)
from insulation_coordination.domain.enums import (
    Applicability,
    DecisiveVoltageClass,
    FieldCondition,
    InsulationType,
    NetClassType,
    ReviewState,
)
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.project import (
    EffectiveCase,
    NetClass,
    PairCase,
    Project,
    RulePackageReference,
)
from insulation_coordination.domain.rules import (
    Literal,
    ProcedureRule,
    RulePackage,
    Table,
    TableSelect,
    Variable,
)
from insulation_coordination.domain.supply import (
    MAINS_SUPPLY_KINDS,
    DerivedSupplyScenario,
    ImpulseOverrideBasis,
    VerifiedImpulseOverride,
)
from insulation_coordination.domain.trace import CalculationWarning, Quantity, TraceStep
from insulation_coordination.domain.verification import (
    EvidenceTarget,
    ProtectionImplementation,
    TestApplicability,
    TestApplication,
    TestClassification,
    TestKind,
    TestReferenceKind,
    VerificationStatus,
    VoltageQuantityKind,
    WorkingVoltageDetermination,
    build_test_id,
)
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

_VOLTAGE_UNIT: Final = "V"

#: What each construction an engineer can select provides, in the same vocabulary the package
#: states a requirement in. This is the only place the two sides are put on one scale, and it
#: is what lets a wrong implementation be detected instead of being described.
#:
#: Supplementary insulation is deliberately absent. On its own it is insulation applied *in
#: addition to* basic insulation, and stating what level it provides by itself would be this
#: application settling an engineering question rather than reading one. A pair carrying it has
#: its comparison reported as an outstanding judgement, which is neither a pass nor a failure.
_IMPLEMENTATION_PROVIDES: Final[Mapping[ProtectionImplementation, ProtectionRequirement]] = {
    ProtectionImplementation.FUNCTIONAL_INSULATION: "none",
    ProtectionImplementation.BASIC_INSULATION: "basic_protection",
    ProtectionImplementation.DOUBLE_INSULATION: "enhanced_protection",
    ProtectionImplementation.REINFORCED_INSULATION: "enhanced_protection",
    ProtectionImplementation.PROTECTIVE_SCREEN_PLUS_BASIC: "enhanced_protection",
    ProtectionImplementation.PROTECTIVE_IMPEDANCE: "enhanced_protection",
    ProtectionImplementation.OTHER_REVIEWED_MEANS: "enhanced_protection",
}

#: How the three levels rank, so a requirement is met by a construction providing its level or
#: a higher one.
_PROTECTION_RANK: Final[Mapping[ProtectionRequirement, int]] = {
    "none": 0,
    "basic_protection": 1,
    "enhanced_protection": 2,
}

#: The five constructions the standard offers for an enhanced level of protection. Enhanced
#: protection is a reliability level rather than a voltage class, so this is a property of the
#: *implementation* an engineer selected and never of the pair's decisive voltage class.
#: Derived from the levels above rather than written out again, so the set that selects the
#: reinforced impulse variant and the set that satisfies an enhanced requirement cannot part.
ENHANCED_PROTECTION_IMPLEMENTATIONS: Final[frozenset[ProtectionImplementation]] = frozenset(
    item for item, level in _IMPLEMENTATION_PROVIDES.items() if level == "enhanced_protection"
)

#: The two constructions the homogeneous-field refusal is stated for.
#: Narrower than the enhanced set on purpose: the clause names double and reinforced insulation
#: specifically, and a protective impedance or another reviewed means reaches an enhanced level
#: without being either of them.
_DOUBLE_OR_REINFORCED: Final[frozenset[ProtectionImplementation]] = frozenset(
    {
        ProtectionImplementation.DOUBLE_INSULATION,
        ProtectionImplementation.REINFORCED_INSULATION,
    }
)

#: How each test relationship reads as Table 3's ``target`` dimension. Three of the four are
#: one accessible part as far as the requirement is concerned; what differs between them is
#: what the test is applied to, which the topology already carries.
_REQUIREMENT_TARGETS: Final[Mapping[TestReferenceKind, str]] = {
    TestReferenceKind.ADJACENT_CIRCUIT: "adjacent_circuit",
    TestReferenceKind.DVC_AS_ADJACENT_CIRCUIT: "adjacent_circuit",
    TestReferenceKind.PE_BONDED_ACCESSIBLE_PART: "accessible_part",
    TestReferenceKind.ACCESSIBLE_CONDUCTIVE_PART: "accessible_part",
    TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL: "accessible_part",
}

#: What the project states about an accessible part's relationship to PE, where it states it.
#: An insulating surface is left out rather than answered: nothing in the project says whether
#: it is bonded, and choosing one would narrow the lookup on a guess. Left out, every reviewed
#: column for an accessible part is a candidate and they have to agree before anything is
#: reported.
_REQUIREMENT_PE_RELATIONSHIPS: Final[Mapping[TestReferenceKind, str]] = {
    TestReferenceKind.PE_BONDED_ACCESSIBLE_PART: "connected_to_pe",
    TestReferenceKind.ACCESSIBLE_CONDUCTIVE_PART: "not_connected_to_pe",
}

#: Every relationship that puts one circuit against another. Both read Table 3 in both
#: directions and both take the other side's class as the adjacent one; what separates them is
#: how the *test* is keyed and columned, which is a question for the dielectric route.
_CIRCUIT_TO_CIRCUIT_KINDS: Final[frozenset[TestReferenceKind]] = frozenset(
    {TestReferenceKind.ADJACENT_CIRCUIT, TestReferenceKind.DVC_AS_ADJACENT_CIRCUIT}
)

#: Every relationship that puts a circuit against an accessible part rather than against
#: another circuit. Derived from the requirement targets so the two readings of "this is an
#: accessible part" cannot part company.
_ACCESSIBLE_PART_KINDS: Final[frozenset[TestReferenceKind]] = frozenset(
    kind for kind, target in _REQUIREMENT_TARGETS.items() if target == "accessible_part"
)

#: The topologies whose *type* test reads the enhanced column whatever construction the pair
#: carries. Both of them are an accessible surface that is non-conductive, or conductive and
#: not bonded to PE, and the package's own label for that column names the topology beside
#: enhanced protection. Selecting the column from the pair's ``ProtectionImplementation``
#: alone planned a basic-protection pair against such a surface at the lower column.
#:
#: A PE-bonded accessible part is deliberately absent: its test reads the basic column for
#: both classifications, which is what the plan already did for it.
_ENHANCED_COLUMN_TOPOLOGIES: Final[frozenset[TestReferenceKind]] = frozenset(
    {
        TestReferenceKind.ACCESSIBLE_CONDUCTIVE_PART,
        TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL,
        TestReferenceKind.DVC_AS_ADJACENT_CIRCUIT,
    }
)

#: Warning codes a report can group on without matching a message.
ENHANCED_SPACING_MISMATCH_WARNING: Final = "verification_enhanced_protection_not_dimensioned"
SPD_MONITORING_OWED_WARNING: Final = "verification_internal_spd_monitoring_owed"
PROTECTION_REQUIREMENT_UNMET_WARNING: Final = "verification_protection_requirement_not_met"
HF_TRANSFORMER_SHOWING_WARNING: Final = "verification_hf_transformer_showing_owed"

#: What a DVC A-s circuit's schedule rows say about the one place a single-fault consideration
#: reaches a spacing. A portion of such a circuit is allowed above the class limits when it is
#: protected against direct contact and the accessible portion still complies under single
#: fault - and the annex that allows it requires that portion's own voltages to go on
#: dimensioning the circuit's clearance and creepage to its surroundings. Stated wherever the
#: plan reports the DVC A-s case, because the same paragraph is the reason single fault is not
#: an operating condition of the working voltage and the reason it is not irrelevant either.
DVC_AS_HIGHER_PORTION_STEP: Final = (
    "Where a portion of this DVC A-s circuit exceeds the class limits, that portion's own "
    "voltages still dimension this circuit's clearance and creepage to its surroundings. The "
    "single fault that admits the portion does not raise the working voltage; the portion's "
    "voltages are what the spacing is taken from."
)

#: The trace identifier of this application's own selection of a dielectric route. Not a
#: semantic rule id: which of the package's four routes answers a pair's question is this
#: application's bookkeeping, and labelling it with a package identifier would credit the
#: package with a choice it did not make.
DIELECTRIC_ROUTE_TRACE_ID: Final = "verification.dielectric_route"

#: Which generated test each voltage form is. Both are planned wherever the package states
#: both, because a permitted DC equivalent is an alternative the engineer chooses between and
#: not one this plan picks for them.
_DIELECTRIC_KINDS: Final[dict[VoltageForm, TestKind]] = {
    "ac": TestKind.AC_DIELECTRIC,
    "dc": TestKind.DC_DIELECTRIC,
}

#: Stated on every impulse application. The alternative AC or DC verification some procedures
#: permit is an engineering choice, and this plan never makes it: an application that silently
#: planned an AC test where an impulse was expected would be indistinguishable from one the
#: standard required.
_ALTERNATIVE_METHOD_STEP: Final = (
    "Perform the impulse withstand test unless an alternative AC or DC verification is "
    "selected. This plan does not choose between them; record the selection, and read its "
    "voltage equivalence, duration, polarity, ramp and limitations from the procedure."
)
#: Stated on every impulse application too. A pair's clearance and its solid insulation are
#: two different things being verified, and a schedule that did not distinguish them would let
#: one result be read as evidence for both.
_CLEARANCE_SCOPE_STEP: Final = (
    "This application verifies the clearance between the connected conductors. Solid "
    "insulation between them is a separate verification and is not covered by this voltage."
)

# --- obligations the standard states and the package projects no rule for --------------------
#
# Every sentence below is this application's own statement of what a clause obliges, written
# for a reader of the schedule and carrying the clause identifier that obliges it. None of them
# is read from the package, because the package projects no rule that carries them: the body of
# the AC/DC test subclause is projected as its two value tables and nothing else, the clearance
# and visual-inspection subclauses are requirement clauses with no procedure to project, and the
# reinforced floor is a comparison the reduction recipe records as resolved and deliberately
# routes to no decision. Where a clause's own deciding input is something the project holds, the
# step is emitted only for the pairs it applies to; where it is not, the step states the
# condition and says the project does not answer it, rather than asserting or staying silent.

#: What requires the electrical tests at all, stated on every row that is one of them. The
#: requirement is gated rather than free-standing, and this plan over-plans deliberately: a test
#: planned where none was owed costs bench time, and one skipped on an input nobody supplied
#: costs the verification. Saying which clause asks, and which half of its gate this plan can
#: see, is what makes the row traceable instead of merely present.
_ELECTRICAL_TEST_GATE_STEP: Final = (
    "5.2.3.1 asks for this test, for the insulation classes it names, where 4.4.7.4 requires it "
    "of a clearance or 4.4.7.8 requires it of solid insulation. This plan holds the clearance "
    "requirement and holds nothing about this pair's solid insulation, so the row is planned "
    "rather than gated on the second half of that condition."
)

#: The layer removal 4.4.7.4.4 attaches to both tests it names. A layer that does not itself
#: reach basic insulation would carry part of the test voltage, and the clearance the test
#: exists to verify would not be verified. Stated with its own condition rather than gated,
#: because one half of that condition is a dimensioning outcome this plan does not hold.
_LAYER_REMOVAL_STEP: Final = (
    "Remove every insulation layer that does not reach at least basic insulation for the "
    "duration of this test, wherever the clearance under test was reduced on a known "
    "homogeneous field or was dimensioned on the working voltage or on the temporary "
    "overvoltage and came out below the tabulated distance (4.4.7.4.4). This plan does not "
    "hold this pair's dimensioned candidates, so which of the two situations applies is read "
    "from the clearance result, not from here."
)

#: The second of 5.2.2.1's two situations, which the project does not answer. The first is the
#: homogeneous-field one and is emitted from the project's own field condition; this one turns
#: on whether the distance can be measured or inspected at all, and nothing records that.
_NEAR_THE_DISTANCE_STEP: Final = (
    "5.2.2.1 also puts this test as close to the distance under test as the construction "
    "allows where that distance can be neither measured nor inspected and the construction "
    "documentation is what shows it complies. Nothing in the project records whether the "
    "distance can be measured, so apply the test at the distance wherever that is the case."
)

#: 5.2.3.4.4's enclosure condition, and the one relaxation it states. The relaxation is a
#: permission conditioned on the equipment's construction, so it is stated and never taken:
#: a plan that quietly performed the routine test open would report a result the schedule did
#: not describe.
_ENCLOSURE_CLOSED_STEP: Final = (
    "5.2.3.4.4 has this test performed on the equipment as it is used: doors shut, nothing "
    "unfastened, no cover set aside for access. It relaxes that for the routine test alone, and "
    "only for equipment whose construction leaves no opening giving access to the electrical "
    "connections; this plan states that relaxation and does not take it."
)

#: The test-side half of a screened construction. The screen is what makes the construction an
#: enhanced one, so a test performed with it disconnected verifies a construction the equipment
#: does not have.
_SCREEN_CONNECTED_STEP: Final = (
    "The construction selected for this pair is a screen combined with basic insulation. "
    "5.2.3.4.4 requires the screen's bond to the conductive accessible parts to be intact for "
    "the whole of this test, so do not lift it for the measurement: a test taken with the bond "
    "open verifies a construction the equipment does not have."
)

#: 5.2.3.4.3's first mandatory disconnection, for the case the project does record: a reducing
#: device somebody claimed a reduction on at this pair. It is the same device the reduction
#: verification is applied to, which is why the two rows are worth reading together.
_LIMITER_DISCONNECTION_STEP: Final = (
    "A device that reduces impulse voltages is recorded at this pair, and 5.2.3.4.3 has such a "
    "device out of circuit for the voltage test. Disconnect it, so that the test voltage arrives "
    "at the insulation instead of at the device, and so that the device operating is not "
    "mistaken for the insulation giving way."
)

#: The low-impedance case of the same subclause, with the step that makes it safe to have taken.
#: Conditioned on something a test house discovers rather than on anything recorded, so the
#: condition is stated with the obligation.
_SPD_OPEN_AND_RESTORE_STEP: Final = (
    "5.2.3.4.3 adds a second step where the assembled equipment cannot be tested at all because "
    "that device's impedance is too low to hold off the test voltage for as long as the test "
    "runs: open its connection first, and restore that connection with care once the test is "
    "over. The restoration is half of the instruction, not a tidying-up afterwards - equipment "
    "shipped with the connection still open has lost the protection the reduction rests on."
)

#: The protective-impedance case. Two routes, both permitted, so both are stated and neither is
#: selected - and the restoration belongs to the second exactly as it does to the SPD one.
_PROTECTIVE_IMPEDANCE_TEST_STEP: Final = (
    "A protective impedance is the means selected for this pair. 5.2.3.4.3 requires it either to "
    "be included in the test, or to have its connection to the protectively separated part of "
    "the circuit opened before the test and carefully restored afterwards. This plan states "
    "both routes and selects neither; record which was taken, and record the restoration with "
    "it."
)

#: The two tests a protective impedance owes in its own right. They are not dielectric tests and
#: no row of this schedule can carry them: the application's test-kind vocabulary has no member
#: for a current or an impedance measurement, and the package projects no procedure for the
#: subclause that states them. Named here so the obligation is in the plan rather than lost in
#: the phrase "a separately disclosed engineering item".
_PROTECTIVE_IMPEDANCE_TESTS_OWED: Final = (
    "4.4.5.5 with 5.2.3.6 owes two tests for a protective impedance beyond anything this "
    "schedule plans: a type test showing that the current through it stays within the limits "
    "4.4.5.5 states under normal operating conditions and under single fault, and a routine "
    "test verifying its value. Neither is a dielectric test, no test kind in this application "
    "names a current or an impedance measurement, and the active package projects no procedure "
    "for the subclause that states them, so they are recorded here and not as schedule rows."
)

#: The mandatory disconnection the project cannot narrow. Which nets belong to a monitoring or a
#: protection circuit, and which of those are built to sustain the test, is not something the
#: topology model records - so this is reported rather than emitted against particular nets.
_MONITORING_CIRCUIT_DISCONNECTION: Final = (
    "5.2.3.4.3 requires a monitoring or protection circuit to be taken out of the test where it "
    "was never built to hold off the test overvoltage for as long as the test runs. Nothing in "
    "the project says which nets belong to such a circuit, so this plan cannot name them: "
    "identify them before the test, rather than reading a monitoring circuit failing as the "
    "insulation failing."
)

#: The optional case of the same subclause, kept optional. The plan states the preference and
#: the recommendation that goes with it and decides neither: a component left in circuit is part
#: of the insulation under test, and removing it on this application's initiative would test
#: something else.
_VULNERABLE_COMPONENT_STEP: Final = (
    "5.2.3.4.3 prefers that individual components forming part of the insulation under test are "
    "left connected and unbridged wherever that is practicable, and recommends the DC form of "
    "the test where they are. Disconnecting or bridging a vulnerable component to protect it is "
    "a permission and not a requirement; record it where it is taken."
)

#: The sequencing 5.2.3.2 states for a component or device that provides enhanced protection.
#: A schedule that planned it on the assembled equipment would plan a test that cannot be
#: performed, and the classification the package already declares for the variant is the other
#: half of the same statement.
_BEFORE_ASSEMBLY_STEP: Final = (
    "Where the enhanced protection of this pair is provided by a component or a device rather "
    "than by the assembled construction, 5.2.3.2 has that component tested before it is "
    "assembled into the equipment, as a type test and a sample test. The classifications this "
    "row carries come from the procedure; the sequencing does not, and is stated here."
)


class PairVerificationAssessment(FrozenModel):
    """What one pair's verification asks for, and how far it has got.

    ``test_ids`` names the deduplicated applications that cover this pair, so a reader who
    started from a pair can find every row of the schedule that answers for it - including the
    rows it shares with the other pairs of its connected group.
    """

    pair_id: UUID
    pair_key: str
    reference_kind: TestReferenceKind
    protection_implementation: ProtectionImplementation | None = None
    protection_review_state: ReviewState = ReviewState.NEEDS_REVIEW
    #: The level of protection the package requires between these two, read from Table 3 for
    #: this pair's decisive voltage classes and relationship. ``None`` where the package could
    #: not be asked or would not answer, which is an unresolved input and never a pass.
    required_protection: ProtectionRequirement | None = None
    #: Which reviewed column or columns stated it, in this application's own words, so a
    #: reader can see what the requirement was read from.
    requirement_columns: str = ""
    #: Whether the selected implementation provides at least the required level. ``None``
    #: where either side is unknown - the requirement exists to be compared against, so a
    #: comparison that could not be made says so rather than reading as satisfied.
    protection_satisfied: bool | None = None
    enhanced_protection: bool = False
    mains_connected: bool = False
    test_ids: tuple[str, ...] = ()
    #: The dedicated monitoring type test one recorded impulse reduction depends on, exactly
    #: as issue #36 recorded it. Consumed, never re-derived: whether a device inside the
    #: equipment owes monitoring is a question the override resolution already asked the
    #: package, and asking it again here would let two answers exist.
    spd_monitoring_dependency: SpdMonitoringDependency | None = None
    #: What the partial-discharge assessment concluded for this pair. Carried on the
    #: assessment as well as on its schedule row because a pair page shows a status before it
    #: shows a schedule, and a reader asking "does this pair need a PD test" should not have
    #: to find the row to be told.
    partial_discharge: TestApplicability | None = None
    #: The recurring-peak working voltage the partial-discharge gate and the non-mains
    #: dielectric route were both answered from, or ``None`` where none is established. The
    #: figure, not just the applicability: a reader shown that a test applies and not the
    #: voltage behind it has to open the trace to learn what was assessed.
    recurring_peak_v: Decimal | None = None
    #: The assembled-equipment routine exemption, condition by condition, whether or not it
    #: was granted. Carried even when the project recorded nothing, because "which condition
    #: is missing" is the question a reader has and an absent assessment answers none of it.
    routine_exemption: RoutineExemptionAssessment | None = None
    status: VerificationStatus = VerificationStatus.PLANNED
    unresolved_inputs: tuple[str, ...] = ()


class VerificationPlan(FrozenModel):
    """Every dielectric verification one project asks for, against one approved package.

    Recomputed on every read and never persisted, which is why every identity in it is derived
    rather than drawn: two runs of one project produce one plan, and two plans of one project
    can be compared line by line.
    """

    rule_package: RulePackageReference
    working_voltage: tuple[WorkingVoltageDetermination, ...] = ()
    pair_assessments: tuple[PairVerificationAssessment, ...] = ()
    #: One row per distinct test, every covered pair retained. Trace references live on each
    #: row rather than being collected here, so a step is always beside what it explains.
    test_applications: tuple[TestApplication, ...] = ()
    warnings: tuple[CalculationWarning, ...] = ()
    unresolved_inputs: tuple[str, ...] = ()
    source_rule_ids: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        """Whether anything is outstanding. False is the ordinary state of a plan in progress."""

        return not self.unresolved_inputs and all(
            application.applicability is not TestApplicability.ENGINEERING_INPUT_REQUIRED
            for application in self.test_applications
        )


class VerificationPlanService:
    """Builds one project's verification plan. Pure, stateless and free of any Qt or I/O."""

    def build(
        self,
        project: Project,
        rules: RulePackage,
        supply: SupplyDerivation | None,
    ) -> VerificationPlan:
        """The plan ``project`` asks for, against ``rules`` and the stresses in ``supply``.

        ``supply`` is the project-level derivation the calculation pipeline already holds -
        the enabled arrangements' scenarios, the rules they were derived against, and the
        stress that reached each galvanic domain. The issue's signature names a
        ``ProjectSupplyResolution`` that issue #36 never shipped; this is the object that
        exists and answers for it, and the per-pair
        :class:`~insulation_coordination.calculation.stress_propagation.EffectivePairStressResolution`
        is resolved from it here rather than being passed in beside it, so a caller cannot
        hand over a pair resolution that came from a different derivation.

        ``None`` is the state of a project that enables no supply arrangement. It plans every
        test it can and reports the impulse as an engineering input, which is the honest
        answer: nothing has been derived, so there is no voltage to test at.
        """

        rule_set = read_verification_rules(rules)
        revision = rules.package_sha256
        if revision is None:
            raise CalculationError("a verification plan needs the rule package's SHA-256 identity")
        identity = RulePackageReference(
            package_id=str(rules.manifest.package_id),
            version=rules.manifest.version,
            sha256=revision,
        )
        determinations = plan_working_voltage(project, rule_set)
        subjects = subjects_for(project, None if supply is None else supply.domain_stresses)
        pairs = {pair.id: pair for pair in project.pairs}
        # Table 3 is read once per class the project assigns rather than once per pair: the
        # reading enumerates the rule's whole declared vocabulary, and a project's pairs stand
        # between far fewer classes than it has pairs.
        matrix = {
            dvc: protection_cells(rule_set.dvc_protection_matrix, dvc)
            for dvc in _assigned_classes(project)
        }

        band = _altitude_band(rules)
        generated: list[TestApplication] = []
        assessments: list[PairVerificationAssessment] = []
        warnings: list[CalculationWarning] = []
        for subject in subjects:
            pair = pairs[subject.pair_id]
            effective, resolution = resolve_supply_effective_case(project, pair, supply)
            applications, assessment = _plan_pair(
                project,
                pair,
                subject,
                effective,
                resolution,
                rule_set,
                revision,
                matrix,
                band,
                warnings,
            )
            generated.extend(applications)
            assessments.append(assessment)
        generated.extend(
            _working_voltage_applications(project, determinations, subjects, rule_set, revision)
        )

        applications, merge_warnings = deduplicate(generated)
        warnings.extend(merge_warnings)
        covering = _covering_test_ids(applications)
        assessments = [
            item.model_copy(update={"test_ids": covering.get(item.pair_id, ())})
            for item in assessments
        ]
        return VerificationPlan(
            rule_package=identity,
            working_voltage=determinations,
            pair_assessments=tuple(assessments),
            test_applications=applications,
            warnings=tuple(warnings),
            unresolved_inputs=_unique(
                (
                    *(item for entry in determinations for item in entry.unresolved_inputs),
                    *(item for entry in assessments for item in entry.unresolved_inputs),
                    *(item for entry in applications for item in entry.unresolved_inputs),
                )
            ),
            source_rule_ids=_unique(
                (
                    *(item for entry in determinations for item in entry.source_rule_ids),
                    *(item for entry in applications for item in entry.source_rule_ids),
                    # Asked of every pair there is, whether or not it answered. A project with
                    # no pair asked nothing.
                    *((rule_set.dvc_protection_matrix.id,) if assessments else ()),
                )
            ),
        )


def _plan_pair(
    project: Project,
    pair: PairCase,
    subject: TestSubject,
    effective: EffectiveCase,
    resolution: EffectivePairStressResolution | None,
    rules: VerificationRuleSet,
    revision: str,
    matrix: Mapping[DecisiveVoltageClass, tuple[ProtectionGuidance, ...]],
    band: tuple[Decimal, Decimal] | None,
    warnings: list[CalculationWarning],
) -> tuple[tuple[TestApplication, ...], PairVerificationAssessment]:
    """One pair's impulse and dielectric applications, and the assessment that summarises them."""

    implementation = pair.protection_implementation
    enhanced = implementation in ENHANCED_PROTECTION_IMPLEMENTATIONS
    mains = _mains_scenarios(resolution)
    unresolved: list[str] = []
    if implementation is None:
        unresolved.append(
            f"Pair {pair.key} has no protection implementation selected, so the plan cannot "
            "say which construction its tests verify."
        )
    required, columns, requirement_reasons = _required_protection(
        project, pair, subject, matrix, rules.dvc_protection_matrix.id
    )
    unresolved.extend(requirement_reasons)
    satisfied, finding = _protection_finding(pair, implementation, required)
    if finding:
        unresolved.append(finding)
    if satisfied is False:
        warnings.append(
            CalculationWarning(
                code=PROTECTION_REQUIREMENT_UNMET_WARNING,
                message=finding,
                semantic_rule_id=rules.dvc_protection_matrix.id,
            )
        )
    dependency = _spd_dependency(resolution)
    monitoring: tuple[TestApplication, ...] = ()
    if dependency is not None:
        message = (
            f"The impulse reduction recorded at {dependency.affected_location!r} depends on the "
            f"dedicated internal SPD monitoring type test "
            f"({dependency.required_type_test_semantic_id}). It is scheduled here and nothing "
            "records that it has been acknowledged, so the plan stays incomplete until it is."
        )
        unresolved.append(message)
        warnings.append(
            CalculationWarning(
                code=SPD_MONITORING_OWED_WARNING,
                message=message,
                semantic_rule_id=dependency.required_type_test_semantic_id,
            )
        )
        monitoring = (_monitoring_application(subject, rules, revision, dependency, message),)

    obligations = _clause_obligations(pair, effective, resolution, implementation, enhanced)
    unresolved.extend(obligations.pair_unresolved)
    warnings.extend(obligations.warnings)

    impulse = _impulse_application(
        pair,
        subject,
        effective,
        resolution,
        rules,
        revision,
        implementation,
        enhanced,
        band,
        warnings,
        obligations,
    )
    override = _verified_reduction(resolution)
    reduction = (
        ()
        if override is None
        else (
            _reduction_application(
                subject, rules, revision, override, obligations.reduction_preparation
            ),
        )
    )
    recurring_peak = _recurring_peak(project, pair, effective)
    adjacency = _dvc_as_adjacency(project, pair, subject)
    dielectric = _dielectric_applications(
        pair,
        subject,
        rules,
        revision,
        enhanced,
        mains,
        recurring_peak if adjacency is None else adjacency.row_v,
        _overvoltage_present(effective, resolution),
        _accessible_part_exception(project, pair, subject)
        or (None if adjacency is None else adjacency.not_applicable),
        row_label="recurring-peak working voltage" if adjacency is None else adjacency.row_label,
        extra_unresolved=(
            *(() if adjacency is None else adjacency.unresolved),
            *obligations.voltage_unresolved,
        ),
        extra_preparation=(
            *(() if adjacency is None else adjacency.preparation),
            *obligations.voltage_preparation,
        ),
    )
    discharge = assess_partial_discharge(
        pair, effective, rules.partial_discharge, recurring_peak_v=recurring_peak
    )
    warnings.extend(discharge.warnings)
    exemption = assess_routine_exemption(pair, rules.assembled_routine_exemption)
    unresolved.extend(exemption.unresolved_inputs)
    applications = (
        *_exempted(
            decorate(
                (
                    impulse,
                    *dielectric,
                    _discharge_application(subject, rules, revision, discharge),
                ),
                reference_kind=subject.reference_kind,
                preconditioning=rules.preconditioning,
                foil=rules.accessible_surface_foil,
            ),
            exemption,
        ),
        *reduction,
        *monitoring,
    )
    return applications, PairVerificationAssessment(
        pair_id=pair.id,
        pair_key=pair.key,
        reference_kind=subject.reference_kind,
        protection_implementation=implementation,
        protection_review_state=pair.protection_review_state,
        required_protection=required,
        requirement_columns=columns,
        protection_satisfied=satisfied,
        enhanced_protection=enhanced,
        mains_connected=bool(mains),
        spd_monitoring_dependency=dependency,
        partial_discharge=discharge.applicability,
        recurring_peak_v=recurring_peak,
        routine_exemption=exemption,
        status=_pair_status(pair, applications, tuple(unresolved)),
        unresolved_inputs=tuple(unresolved),
    )


# --- obligations no projected rule carries -----------------------------------------------


class _ClauseObligations(FrozenModel):
    """What one pair owes beyond what the package's procedures state, sorted by where it lands.

    Private and unexported, and shaped like :class:`_DvcAsAdjacency` and for the same reason:
    one pass over one pair answers every one of these questions, and four functions asking the
    same project the same things would be four places for the answers to differ.

    The split by destination is the load-bearing part. An impulse test and a voltage test are
    prepared differently - the enclosure condition and the disconnections belong to the voltage
    test, the sequencing and the distance belong to the impulse test - and a schedule that put
    every obligation on every row would tell a test house to disconnect a limiter for a test the
    clause never asked that of. ``pair_unresolved`` is what belongs to no row at all: an
    obligation this schedule cannot carry as a test, or a selection it has to question.
    """

    impulse_preparation: tuple[str, ...] = ()
    voltage_preparation: tuple[str, ...] = ()
    voltage_unresolved: tuple[str, ...] = ()
    reduction_preparation: tuple[str, ...] = ()
    pair_unresolved: tuple[str, ...] = ()
    warnings: tuple[CalculationWarning, ...] = ()


def _clause_obligations(
    pair: PairCase,
    effective: EffectiveCase,
    resolution: EffectivePairStressResolution | None,
    implementation: ProtectionImplementation | None,
    enhanced: bool,
) -> _ClauseObligations:
    """Every obligation this pair carries that no rule of the active package states.

    Each of them is a "shall" of the standard whose subclause the recipe projects no procedure
    or decision for - the AC/DC test's body, the clearance subclause, the visual-inspection
    subclause, the protective-impedance test - so none of them can be read from the package and
    all of them would otherwise reach the schedule as nothing at all. That is the failure this
    function exists to close: a test house working from a schedule that omitted them would
    perform the tests with an enclosure open, with a limiter still connected, and with a
    monitoring circuit taking the test voltage.

    Where the deciding input is one the project holds it is used, and three of them are: the
    pair's field condition decides the homogeneous-field case, the selected construction decides
    the screen and the protective-impedance cases, and the recorded override's basis decides
    both the reducing-device case and the transformer showing. Where it is not - which nets are
    a monitoring circuit, whether the distance can be measured, which axis dimensioned the
    clearance - the obligation is still stated and says what is missing, because a "shall"
    nobody can narrow is not a "shall" that goes away.
    """

    reduction = _verified_reduction(resolution)
    basis = None if reduction is None else reduction.basis
    homogeneous = effective.field_condition.value is FieldCondition.HOMOGENEOUS
    stronger = (
        effective.insulation_type.value is InsulationType.REINFORCED
        or implementation in _DOUBLE_OR_REINFORCED
    )

    impulse = [_ELECTRICAL_TEST_GATE_STEP, _LAYER_REMOVAL_STEP, _NEAR_THE_DISTANCE_STEP]
    voltage = [
        _ELECTRICAL_TEST_GATE_STEP,
        _LAYER_REMOVAL_STEP,
        _ENCLOSURE_CLOSED_STEP,
        _VULNERABLE_COMPONENT_STEP,
    ]
    voltage_unresolved = [_MONITORING_CIRCUIT_DISCONNECTION]
    pair_unresolved: list[str] = []
    warnings: list[CalculationWarning] = []
    reduction_preparation: list[str] = []

    if homogeneous and not stronger:
        impulse.append(_homogeneous_field_step(pair))
    if homogeneous and stronger:
        pair_unresolved.append(_homogeneous_stronger_reason(pair))
    if enhanced:
        impulse.append(_BEFORE_ASSEMBLY_STEP)
    if implementation is ProtectionImplementation.PROTECTIVE_SCREEN_PLUS_BASIC:
        voltage.append(_SCREEN_CONNECTED_STEP)
    if implementation is ProtectionImplementation.PROTECTIVE_IMPEDANCE:
        voltage.append(_PROTECTIVE_IMPEDANCE_TEST_STEP)
        pair_unresolved.append(_PROTECTIVE_IMPEDANCE_TESTS_OWED)
    if implementation is ProtectionImplementation.OTHER_REVIEWED_MEANS:
        pair_unresolved.append(_other_reviewed_means_reason(pair))
    if implementation is ProtectionImplementation.SUPPLEMENTARY_INSULATION:
        pair_unresolved.append(_supplementary_alone_reason(pair))
    if basis is ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER:
        voltage.extend((_LIMITER_DISCONNECTION_STEP, _SPD_OPEN_AND_RESTORE_STEP))
    if basis is ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER:
        assert reduction is not None  # a basis exists only where a reduction applied
        showing = _transformer_showing_reason(pair, reduction)
        reduction_preparation.append(showing)
        warnings.append(
            CalculationWarning(
                code=HF_TRANSFORMER_SHOWING_WARNING,
                message=showing,
                semantic_rule_id=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
            )
        )
    return _ClauseObligations(
        impulse_preparation=tuple(impulse),
        voltage_preparation=tuple(voltage),
        voltage_unresolved=tuple(voltage_unresolved),
        reduction_preparation=tuple(reduction_preparation),
        pair_unresolved=tuple(pair_unresolved),
        warnings=tuple(warnings),
    )


def _homogeneous_field_step(pair: PairCase) -> str:
    """What a clearance reduced on a known homogeneous field owes, on the impulse row.

    Both subclauses that state it state the same thing from two directions: the reduction is
    permitted at the price of an impulse test performed across the reduced clearance itself, and
    the visual-inspection subclause names the same situation as one where the test goes as near
    as possible to the distance. A test performed anywhere else verifies a distance nobody
    reduced.
    """

    return (
        f"The clearance of pair {pair.key} is dimensioned for a homogeneous field. 4.4.7.4.4 "
        "permits that reduction for basic or supplementary insulation only against an impulse "
        "withstand test performed across the reduced clearance itself, and 5.2.2.1 names the "
        "same situation as one that puts this test as close to that distance as the "
        "construction allows. Apply it there, not across whatever the assembled equipment "
        "offers."
    )


def _homogeneous_stronger_reason(pair: PairCase) -> str:
    """Why a homogeneous field and a double or reinforced construction do not go together.

    The subclause that permits the reduction names basic and supplementary insulation, and closes
    by stating outright that a reinforced clearance is not reduced for a homogeneous field. So
    this is a finding about the dimensioning rather than a test to plan, and it is reported: the
    plan neither reduces anything itself nor has anywhere to put a spacing correction.
    """

    return (
        f"Pair {pair.key} is dimensioned for a homogeneous field while the construction it "
        "carries is a double or reinforced one. 4.4.7.4.4 offers that reduction to basic and "
        "supplementary insulation and states that a reinforced clearance is not reduced for a "
        "homogeneous field, so the reduction is not available here. Record which insulation "
        "class the reduced clearance belongs to."
    )


def _other_reviewed_means_reason(pair: PairCase) -> str:
    """The obligation the "other means" permission attaches, which nothing else in the plan raises.

    The construction is not one of the means the enhanced-protection clause enumerates. What
    permits it is the protection-requirement clause's allowance for other means, and that
    allowance is conditional: the requirements have to be shown met by a failure analysis
    together with testing. Selecting the member without recording either would be an
    unevidenced construction reading in the schedule as a settled one.
    """

    return (
        f"Pair {pair.key} is protected by another reviewed means, which is not one of the "
        "constructions 4.4.5.1 enumerates. 4.4.2.7 permits other means only where a failure "
        "analysis under 4.2, together with testing, demonstrates that what 4.1 and 4.4 ask has "
        "been satisfied anyway. Record that analysis and that testing; this plan generates "
        "neither."
    )


def _supplementary_alone_reason(pair: PairCase) -> str:
    """Why supplementary insulation selected on its own is a question rather than a plan.

    4.4.4.5 defines it as an independent insulation applied *in addition to* basic insulation,
    and 4.4.4.1 requires a fault-protection means to be independent of and additional to basic
    protection. So a pair whose only recorded means is this one has not named the protection it
    is additional to, and the plan asks rather than planning from half a construction. The
    comparison against the required level says something adjacent - that this application ranks
    no level for it - and deliberately does not say this.
    """

    return (
        f"Supplementary insulation is the only means recorded for pair {pair.key}, and it is not "
        "a means of protection on its own: 4.4.4.5 defines it as an independent insulation "
        "applied in addition to basic insulation, and 4.4.4.1 requires a fault-protection means "
        "to be independent of and additional to basic protection. Record the basic insulation "
        "this is additional to, or record the combined construction instead."
    )


def _transformer_showing_reason(pair: PairCase, override: VerifiedImpulseOverride) -> str:
    """The showing a transformer attenuation owes, raised from the reduction that relies on it.

    The permission and the obligation are two halves of one clause: an insulation between the
    circuit and its surroundings may be determined from the working voltage where a
    high-frequency transformer provides the isolation, *and* the transformer's ability to hold
    impulse voltages below the withstand voltage associated with that working voltage has to be
    shown - by the impulse test, by simulation or by calculation. Issue #36 resolves the
    permission and records which showing was claimed; nothing raised the obligation, so a
    reduction could rest on a showing no schedule mentioned.

    Raised from the recorded basis rather than re-derived: which reduction rests on a transformer
    is a question the override resolution already answered, and asking it again here would let
    two answers exist.
    """

    return (
        f"The impulse reduction recorded at {override.affected_location!r} for pair {pair.key} "
        "rests on a high-frequency isolation transformer. 4.4.7.2.6 requires that transformer's "
        "ability to hold impulse voltages below the withstand voltage associated with the "
        "working voltage to be shown by the impulse test, by simulation or by calculation. The "
        f"project records a {_words(override.verification_method.value)} against "
        f"{override.evidence_reference}; the reduction holds only while that showing does, and "
        "this plan neither performs it nor chooses between the three."
    )


# --- the protection requirement ---------------------------------------------------------


def _assigned_classes(project: Project) -> frozenset[DecisiveVoltageClass]:
    """Every decisive voltage class the project actually assigns to a circuit.

    ``NOT_EVALUATED`` is not one of them: it is the absence of a class, no package declares it
    as a designation, and asking Table 3 for it would return nothing for a reason that reads
    like a package problem rather than a project one.
    """

    return frozenset(
        net.decisive_voltage_class
        for net in project.net_classes
        if net.decisive_voltage_class is not None
        and net.decisive_voltage_class is not DecisiveVoltageClass.NOT_EVALUATED
    )


def _required_protection(
    project: Project,
    pair: PairCase,
    subject: TestSubject,
    matrix: Mapping[DecisiveVoltageClass, tuple[ProtectionGuidance, ...]],
    rule_id: str,
) -> tuple[ProtectionRequirement | None, str, tuple[str, ...]]:
    """What the package requires for this pair, which columns said so, and what stopped it.

    The requirement is the whole point of reading Table 3 here: it is the thing an engineer's
    selected implementation is compared *against*. Deriving it from that implementation - which
    is what the plan did before this - means a wrong implementation can never be detected,
    because the requirement would move to meet it.

    A pair between two circuits is asked in both directions. Each circuit has to be protected
    from the other, both statements apply to the one insulation between them, and the more
    demanding of the two is what it has to provide. A pair against an accessible part is asked
    once, from the circuit towards the part.

    The lookup is narrowed only by what the project states: the classes on either side, the
    relationship, and whether an accessible part is bonded to PE where the project says so.
    Table 3's columns also distinguish an access context and a person scope, and nothing in a
    project records either, so every column carrying them stays a candidate and a requirement
    is reported only where they agree. Where they do not, or where no reviewed column carries
    the relationship at all, the answer is an unresolved input naming what is missing - never a
    silent pass and never the most convenient of the candidates.
    """

    nets = {net.id: net for net in project.net_classes}
    first, second = nets[pair.net_a], nets[pair.net_b]
    target = _REQUIREMENT_TARGETS[subject.reference_kind]
    directions: tuple[tuple[NetClass, NetClass], ...]
    if subject.reference_kind in _CIRCUIT_TO_CIRCUIT_KINDS:
        directions = ((first, second), (second, first))
    elif first.net_type is NetClassType.CIRCUIT:
        directions = ((first, second),)
    else:
        directions = ((second, first),)

    stated: list[ProtectionRequirement] = []
    columns: list[str] = []
    reasons: list[str] = []
    for circuit, other in directions:
        adjacent = None
        if subject.reference_kind in _CIRCUIT_TO_CIRCUIT_KINDS:
            adjacent = _designation(other)
            if adjacent is None:
                reasons.append(_no_class_reason(pair, other.name))
                continue
        designation = _designation(circuit)
        if designation is None:
            reasons.append(_no_class_reason(pair, circuit.name))
            continue
        candidates = tuple(
            cell
            for cell in matrix.get(designation, ())
            if cell.target == target
            and _REQUIREMENT_PE_RELATIONSHIPS.get(subject.reference_kind)
            in (None, cell.pe_relationship)
            and adjacent in (None, cell.adjacent_dvc)
        )
        requirements = {cell.requirement for cell in candidates}
        if not requirements:
            reasons.append(
                f"The active package's {rule_id} carries no reviewed column for "
                f"{circuit.name} against {other.name}, so the protection it requires between "
                "them cannot be read."
            )
            continue
        if len(requirements) > 1:
            reasons.append(
                f"The active package's {rule_id} states more than one requirement for "
                f"{circuit.name} against {other.name} "
                f"({', '.join(sorted(_words(item) for item in requirements))}), and the "
                "project does not record which of its reviewed columns applies: "
                f"{'; '.join(sorted({cell.label for cell in candidates}))}."
            )
            continue
        stated.append(requirements.pop())
        columns.extend(cell.label for cell in candidates)
    if reasons or not stated:
        return None, "", _unique(reasons)
    return (
        max(stated, key=lambda item: _PROTECTION_RANK[item]),
        "; ".join(dict.fromkeys(columns)),
        (),
    )


def _designation(net: NetClass) -> DecisiveVoltageClass | None:
    dvc = net.decisive_voltage_class
    return None if dvc is None or dvc is DecisiveVoltageClass.NOT_EVALUATED else dvc


def _no_class_reason(pair: PairCase, name: str) -> str:
    return (
        f"No decisive voltage class is assigned to {name}, so the protection required for "
        f"pair {pair.key} cannot be read from the package."
    )


def _protection_finding(
    pair: PairCase,
    implementation: ProtectionImplementation | None,
    required: ProtectionRequirement | None,
) -> tuple[bool | None, str]:
    """Whether the selected construction provides what the package requires, and the finding.

    A mismatch is reported, not raised: it is a design finding about a project, and a plan that
    refused to build for one would take away the schedule a reader needs in order to fix it.

    ``None`` is never a pass. A comparison missing either half is reported as outstanding,
    because a requirement nobody could read and an implementation nobody selected both look
    exactly like agreement if the answer is allowed to default to true.
    """

    if required is None or implementation is None:
        return None, ""
    provided = _IMPLEMENTATION_PROVIDES.get(implementation)
    if provided is None:
        return None, (
            f"Pair {pair.key} is protected by {_words(implementation.value)}, which this "
            "application does not rank as a level of protection on its own. The package "
            f"requires {_words(required)} here; whether that construction meets it is an "
            "engineering judgement this plan does not make."
        )
    if _PROTECTION_RANK[provided] >= _PROTECTION_RANK[required]:
        return True, ""
    return False, (
        f"The package requires {_words(required)} for pair {pair.key}, and the selected "
        f"{_words(implementation.value)} provides {_words(provided)}. The implementation does "
        "not meet the requirement stated for this relationship."
    )


# --- impulse ---------------------------------------------------------------------------


def _impulse_application(
    pair: PairCase,
    subject: TestSubject,
    effective: EffectiveCase,
    resolution: EffectivePairStressResolution | None,
    rules: VerificationRuleSet,
    revision: str,
    implementation: ProtectionImplementation | None,
    enhanced: bool,
    band: tuple[Decimal, Decimal] | None,
    warnings: list[CalculationWarning],
    obligations: _ClauseObligations,
) -> TestApplication:
    """The impulse withstand this pair asks for, at the stress issue #36 resolved for it.

    The voltage is the pair's insulation-treated effective impulse: what the supply produced,
    what propagation carried to it, what a verified override made of it, and what its
    insulation class asks of that. It is taken already treated and is never multiplied again -
    a reinforced pair tested at a treated figure that was treated twice would be tested at a
    voltage nothing asked for.
    """

    procedure = _impulse_procedure(rules, implementation)
    unresolved: list[str] = []
    preparation = [
        *subject.preparation_steps,
        _ALTERNATIVE_METHOD_STEP,
        _CLEARANCE_SCOPE_STEP,
        *obligations.impulse_preparation,
    ]
    if procedure is None:
        unresolved.append(
            f"Pair {pair.key} has no protection implementation selected, so the impulse "
            "procedure that applies to it cannot be resolved."
        )
    else:
        preparation.extend(step.text for step in procedure.preparation_steps)
    voltage = None
    treated = None if resolution is None else resolution.insulation_treated_impulse_v
    if treated is None:
        unresolved.append(
            f"No impulse stress is resolved for pair {pair.key}, so there is no voltage to "
            "plan this test at."
        )
    else:
        voltage = Quantity(value=treated, unit=_VOLTAGE_UNIT)
    altitude_unresolved, altitude_preparation = _altitude_inputs(pair, effective, band)
    unresolved.extend(altitude_unresolved)
    preparation.extend(altitude_preparation)
    if enhanced and effective.insulation_type.value is not InsulationType.REINFORCED:
        message = (
            f"Pair {pair.key} is protected by {implementation} and is dimensioned on the "
            f"{effective.insulation_type.value} spacing path, so the impulse figure carried "
            "here has not had the enhanced treatment applied to it. The combined "
            "enhanced-protection requirement needs its own test voltage."
        )
        warnings.append(CalculationWarning(code=ENHANCED_SPACING_MISMATCH_WARNING, message=message))
        unresolved.append(message)
    if implementation is ProtectionImplementation.DOUBLE_INSULATION:
        unresolved.append(
            f"Pair {pair.key} is protected by double insulation, which is two separately "
            "assessed protective means. This application verifies the combined requirement; "
            "the basic and supplementary means each need their own, and the project records "
            "no conductor between them to apply one against."
        )
    if implementation is ProtectionImplementation.PROTECTIVE_IMPEDANCE:
        unresolved.append(
            f"Pair {pair.key} is protected by a protective impedance, which is not a dimensioned "
            "spacing this test verifies. It owes two tests of its own, named on the pair rather "
            "than on this row: 4.4.5.5 with 5.2.3.6 asks for a type test of the current through "
            "it and a routine test of its value."
        )
    classifications = () if procedure is None else classifications_of(procedure)
    return _application(
        subject=subject,
        test_kind=TestKind.IMPULSE_WITHSTAND,
        classifications=classifications,
        revision=revision,
        voltage=voltage,
        waveform=None if procedure is None else procedure.waveform,
        polarity=None if procedure is None else procedure.polarity,
        duration=None if procedure is None else procedure.duration,
        repetitions=None if procedure is None else procedure.repetitions,
        preparation_steps=tuple(preparation),
        unresolved=tuple(unresolved),
        source_rule_ids=() if procedure is None else (procedure.id,),
        trace_steps=() if resolution is None else resolution.trace_steps,
    )


def _impulse_procedure(
    rules: VerificationRuleSet,
    implementation: ProtectionImplementation | None,
) -> ProcedureRule | None:
    """Which of the impulse procedure's variants states the conditions for this pair.

    The pair's construction, and nothing else. The package's third variant is not a third
    construction: it states the conditions for verifying a claimed reduction of the
    overvoltage, which is a separate test applied to the equipment. Selecting it here in
    preference to a construction variant took a pair's insulation impulse application away
    from it whenever somebody recorded a reduction - see :func:`_reduction_application`, which
    is where that test is generated instead, in addition to this one rather than in place of
    it.
    """

    if implementation is None:
        return None
    if implementation in ENHANCED_PROTECTION_IMPLEMENTATIONS:
        return rules.impulse_procedure.insulation_reinforced
    return rules.impulse_procedure.insulation_basic


def _verified_reduction(
    resolution: EffectivePairStressResolution | None,
) -> VerifiedImpulseOverride | None:
    """The reduction claim recorded at this pair that actually applied, if there is one."""

    outcome = None if resolution is None else resolution.override_outcome
    if outcome is None or not outcome.applied or not outcome.override.is_reduction:
        return None
    return outcome.override


def _reduction_application(
    subject: TestSubject,
    rules: VerificationRuleSet,
    revision: str,
    override: VerifiedImpulseOverride,
    obligations: tuple[str, ...] = (),
) -> TestApplication:
    """The type test that verifies a claimed reduction of the overvoltage does what is claimed.

    Owed in addition to the insulation impulse applications of the pairs the reduction affects
    and never instead of one: clause 5.2.3.2 states it as a further requirement, and the
    package's own variant of the procedure carries its own subject, preconditioning answer and
    power condition. Clause 4.4.7.3 asks for the same test where circuit characteristics
    rather than a device are what the reduction rests on, which is why this is generated for
    every applied reduction and not only for the ones that owe monitoring.

    ``obligations`` is how the showing a transformer attenuation owes reaches the schedule.
    4.4.7.2.6 lets an insulation be determined from the working voltage across such a
    transformer and obliges the transformer's attenuation to be shown - by this same test, by
    simulation or by calculation - so this row is where that obligation is named, whichever of
    the three the project recorded.

    The row stands between the pair's own electrodes, as the monitoring row does and for the
    same reason: the test is not measured there - it is applied to the equipment, which the
    preparation says - but it is what ties the test to the reduction it verifies, and it means
    two pairs of one connected group carrying one reduction produce one row rather than two.

    No voltage. The package states this variant's test voltage as one column of its impulse
    selection route, that route carries more than one column, and nothing in it says which
    applies here - the same refusal the dielectric lookup makes, for the same reason. It is
    emphatically not the pair's own reduced figure: the point of the test is to show the
    reduction holds when the unreduced stress arrives.
    """

    procedure = rules.impulse_procedure.transient_reduction
    return _application(
        subject=subject,
        test_kind=TestKind.TRANSIENT_OVERVOLTAGE_REDUCTION,
        classifications=classifications_of(procedure),
        revision=revision,
        voltage=None,
        waveform=procedure.waveform,
        polarity=procedure.polarity,
        duration=procedure.duration,
        repetitions=procedure.repetitions,
        preparation_steps=(
            (
                "Apply this test to the equipment, not between the conductors of one pair. "
                f"It verifies the reduction recorded at {override.affected_location!r}, on "
                f"the basis of {_words(override.basis.value)}, against "
                f"{override.evidence_reference}."
            ),
            *obligations,
            *(step.text for step in procedure.preparation_steps),
        ),
        unresolved=(
            (
                f"The active package states this test's voltage as one column of "
                f"{ids.TEST_IMPULSE_SELECTION}, that route states more than one column, and "
                "nothing in it says which one applies here. The reduced figure recorded at "
                f"{override.affected_location!r} is not it: this test exists to show the "
                "reduction holds, so planning it at the reduced value would verify nothing."
            ),
            (
                "The acceptance criterion compares the measured peak against the next lower "
                f"step of the same {ids.TEST_IMPULSE_SELECTION} column. Read it from that "
                "column once the column above is settled; this plan does not choose it."
            ),
        ),
        source_rule_ids=(procedure.id,),
        trace_steps=(),
    )


def _altitude_band(rules: RulePackage) -> tuple[Decimal, Decimal] | None:
    """The altitudes the package's clearance correction runs between, or nothing.

    Resolved once for the whole plan rather than once per pair: it is a question about the
    package, and a project's pairs all get the same answer. ``None`` is a package that states
    no correction, which is reported on the rows that needed it rather than raised - a
    schedule is still worth having without it.
    """

    try:
        return altitude_correction_band(rules)
    except CalculationError:
        return None


def _altitude_inputs(
    pair: PairCase,
    effective: EffectiveCase,
    band: tuple[Decimal, Decimal] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """What the plan owes a reader about altitude: what is uncorrected, and the alternative.

    *The correction is keyed on the altitude of the test, not on the altitude the pair is
    dimensioned for.* The procedure states it as applying when the test is carried out on a
    clearance below the reference altitude, and nothing in the project says where the test
    will be performed. So every planned impulse voltage is an uncorrected one, whatever
    altitude the pair was dimensioned at, and the row says so and names the correction to
    apply once the site is known. Raising the input from the pair's own altitude - and from
    "above zero", which is not a threshold anything states - answered a question nobody asked
    and stayed silent for the pair tested at sea level, which is the pair the correction is
    actually for.

    *The correction does not reach solid insulation.* The procedure excepts impulse testing of
    solid insulation from it outright, and this application covers the clearance alone, so the
    row says which of the two its statement is about.

    *A clearance dimensioned for the high-altitude band, or above the frequency threshold, has
    an alternative.* Its test voltage may instead be derived from the clearance itself by
    reading the correction backwards. That is a permission, so it is stated as a preparation
    step and never selected here: a plan that silently took the alternative would report a
    voltage nothing in the schedule explained.
    """

    altitude = effective.altitude_m.value
    frequency = effective.frequency_hz.value
    unresolved = [
        (
            "The test-voltage altitude correction is keyed on the altitude at which the test "
            "is carried out, and nothing records where that will be. The voltage planned here "
            f"is uncorrected; apply {ids.ALTITUDE_TEST_VOLTAGE_CORRECTION} to it once the test "
            "site is known. The correction is not applied to impulse testing of solid "
            "insulation, which this application does not cover."
        )
    ]
    if band is None:
        unresolved.append(
            "The active rule package states no approved clearance altitude correction, so "
            f"whether pair {pair.key} was dimensioned in the high-altitude band - and with it "
            "whether its test voltage may instead be derived from its clearance - cannot be "
            "answered."
        )
    elif altitude is None:
        unresolved.append(
            f"No altitude is recorded for pair {pair.key}, so whether it was dimensioned in "
            "the high-altitude band cannot be answered."
        )
    reasons = []
    if band is not None and altitude is not None and altitude > band[0]:
        reasons.append(
            f"at {altitude} m, above the altitude the package's clearance correction is referred to"
        )
    if frequency is not None and frequency > PART4_FREQUENCY_THRESHOLD_HZ:
        reasons.append("for a working voltage above the high-frequency threshold")
    # The pair is deliberately not named: the statement is about the clearance under test, and
    # two pairs of one connected group produce one row whose preparation should read once.
    preparation = (
        (
            f"This clearance is dimensioned {' and '.join(reasons)}. Its test voltage may "
            "instead be derived from the clearance itself, by reading "
            f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION} in reverse. This plan states the "
            "alternative and does not choose it; record the selection with the result."
        ),
    )
    return tuple(unresolved), preparation if reasons else ()


# --- AC and DC dielectric --------------------------------------------------------------


def _dielectric_applications(
    pair: PairCase,
    subject: TestSubject,
    rules: VerificationRuleSet,
    revision: str,
    enhanced: bool,
    mains: Sequence[DerivedSupplyScenario],
    recurring_peak_v: Decimal | None,
    overvoltage_present: bool | None,
    not_applicable: str | None,
    *,
    row_label: str,
    extra_unresolved: tuple[str, ...] = (),
    extra_preparation: tuple[str, ...] = (),
) -> tuple[TestApplication, ...]:
    """The routine and type dielectric applications, in both voltage forms the package states.

    A mains-connected circuit is looked up in the mains table on the system voltage its supply
    resolved to. A circuit reached by more than one supply is mains-connected if any of them
    is, and the most severe of their system voltages is what keys the row.

    A non-mains circuit has two routes, not one, and which of them applies is decided by
    whether a temporary overvoltage is present on it. The package's non-mains table is the
    route for a circuit that has none, keyed on its recurring-peak working voltage; a circuit
    that has one takes its test voltage from that overvoltage instead, and reading the table
    for it would plan the test under what is required. A circuit nobody has answered the
    question for reads neither.

    The routine test and the basic-protection type test share one route because the package's
    own route says it covers both. The enhanced-protection type test is read from its own
    route and is never taken from the other one: reusing a value across the two would assert
    an equality the source was not asked for.

    *Which column the type test reads is a question about the topology as well as about the
    construction.* The routine test always reads the basic column. The type test reads the
    enhanced one where the pair is protected by enhanced protection **or** where the low side
    is an accessible surface that is non-conductive, or conductive and not bonded to PE -
    which is the second case the package's own label for that column names. Reading the
    column from the selected implementation alone planned a basic-protection pair against
    such a surface at the lower of the two.

    ``not_applicable`` is the one condition that stops a row being planned at all. It states
    why, the rows are generated anyway so a reader can tell an excepted test from one nobody
    planned, and none of them carries a voltage.
    """

    if not_applicable is not None:
        return _not_applicable_applications(subject, revision, not_applicable)
    tables = rules.mains_dielectric_values if mains else rules.non_mains_dielectric_values
    row, row_reason, row_unresolved = _row_value(
        pair, mains, recurring_peak_v, overvoltage_present, row_label
    )
    enhanced_column = enhanced or subject.reference_kind in _ENHANCED_COLUMN_TOPOLOGIES
    routes: tuple[tuple[TestClassification, VoltageTablePair], ...] = (
        (TestClassification.ROUTINE, tables.routine_and_basic_type),
        (
            TestClassification.TYPE,
            tables.enhanced_type if enhanced_column else tables.routine_and_basic_type,
        ),
    )
    applications: list[TestApplication] = []
    for classification, pair_tables in routes:
        for form, test_kind in _DIELECTRIC_KINDS.items():
            table = pair_tables.for_form(form)
            voltage, steps, unresolved = _dielectric_value(table, row)
            applications.append(
                _application(
                    subject=subject,
                    test_kind=test_kind,
                    classifications=(classification,),
                    revision=revision,
                    voltage=voltage,
                    waveform=None,
                    polarity=None,
                    duration=None,
                    repetitions=None,
                    preparation_steps=(*subject.preparation_steps, *extra_preparation),
                    unresolved=(
                        *extra_unresolved,
                        *row_unresolved,
                        *unresolved,
                        (
                            f"The active package's {table.id} states no duration for this "
                            "test; it is read from the procedure the test is performed under."
                        ),
                    ),
                    source_rule_ids=(table.id,),
                    trace_steps=(
                        *_route_step(
                            table,
                            classification,
                            row,
                            row_reason,
                            _column_reason(classification, subject.reference_kind, enhanced),
                        ),
                        *steps,
                    ),
                )
            )
    return tuple(applications)


def _not_applicable_applications(
    subject: TestSubject,
    revision: str,
    reason: str,
) -> tuple[TestApplication, ...]:
    """The dielectric rows of a pair the topology rule excepts from the test.

    Generated rather than omitted, exactly as the partial-discharge row is: a pair the rule
    settles is a different thing from a pair nobody planned, and a schedule showing only the
    required rows could not tell them apart. None of them carries a voltage, a route or an
    unresolved input - there is nothing outstanding about a test that is not owed.
    """

    return tuple(
        _application(
            subject=subject,
            test_kind=test_kind,
            classifications=(classification,),
            revision=revision,
            voltage=None,
            waveform=None,
            polarity=None,
            duration=None,
            repetitions=None,
            preparation_steps=(*subject.preparation_steps, reason),
            unresolved=(),
            source_rule_ids=(),
            trace_steps=(),
            applicability=TestApplicability.NOT_APPLICABLE,
        )
        for classification in (TestClassification.ROUTINE, TestClassification.TYPE)
        for test_kind in _DIELECTRIC_KINDS.values()
    )


def _accessible_part_exception(
    project: Project, pair: PairCase, subject: TestSubject
) -> str | None:
    """Why a DVC A-s circuit is given no voltage test against an accessible part.

    The topology rule states the test against an earthed conductive accessible part and the
    test against an accessible surface for each circuit in turn *except* a DVC A-s one, and
    settles that circuit's case separately as a test against its adjacent circuits. Planning
    the excepted test anyway asks a test house for work no rule asks for, and reporting it as
    required-with-something-unresolved reads in a schedule exactly like a test nobody could
    settle.

    The active package projects the two dielectric value tables and no rule for the topology
    clause that routes a pair to them, so this reading is stated here rather than read from
    it. A pair whose circuit side carries no decisive voltage class is not excepted: the
    absence of a class is reported by the requirement lookup, and treating it as a DVC A-s
    would take a test away on the strength of something nobody said.
    """

    if subject.reference_kind not in _ACCESSIBLE_PART_KINDS:
        return None
    if _circuit_side_class(project, pair) is not DecisiveVoltageClass.DVC_AS:
        return None
    return (
        f"Pair {pair.key} stands between a DVC A-s circuit and an accessible part. The "
        "voltage test between a circuit and an accessible part is stated for each circuit "
        "except a DVC A-s one, whose case is settled as a test against its adjacent circuits "
        f"instead, so no voltage is planned here. {DVC_AS_HIGHER_PORTION_STEP}"
    )


class _DvcAsAdjacency(FrozenModel):
    """What the plan makes of a pair with a DVC A-s circuit on one side of it.

    Private and unexported: it exists so :func:`_dvc_as_adjacency` can answer four things at
    once about one pair without four functions asking the same question of the same project.
    """

    #: The working voltage that keys the row, which is the higher-voltage circuit's and not
    #: the pair's. ``None`` where it could not be established for both circuits.
    row_v: Decimal | None = None
    row_label: str = "recurring-peak working voltage"
    unresolved: tuple[str, ...] = ()
    not_applicable: str | None = None
    preparation: tuple[str, ...] = ()


def _dvc_as_adjacency(
    project: Project, pair: PairCase, subject: TestSubject
) -> _DvcAsAdjacency | None:
    """How clause 5.2.3.4.4 c) keys the test between a DVC A-s circuit and an adjacent circuit.

    Two things separate this test from every other circuit-to-circuit one, and the plan applied
    neither before the relationship had a name.

    *The row is keyed on the higher-voltage circuit of the two*, not on the circuit under test.
    The same principle is stated generally for insulation between circuits: the more severe of
    the two sides, or the working voltage between them, whichever is more severe. The two
    circuits' own working voltages are what decides which is higher, so both have to be
    established; where either is not, the row is refused and the missing one is named. Reading
    the pair's own figure in their place would answer a question nobody asked and could land
    below the row the source states.

    *Functional insulation between two DVC A-s circuits need not be tested, while basic
    insulation between DVC A-s circuits must be.* That distinction turns on the construction
    the engineer selected, which the project holds, so it is applied rather than reported.

    A mains circuit is unaffected: its row axis is the supply's system voltage, and the plan
    already keys it on the most severe measure across every supply reaching either side, which
    is the same principle applied to the axis that route actually has.
    """

    if subject.reference_kind is not TestReferenceKind.DVC_AS_ADJACENT_CIRCUIT:
        return None
    nets = {net.id: net for net in project.net_classes}
    first, second = nets[pair.net_a], nets[pair.net_b]
    both = (
        _designation(first) is DecisiveVoltageClass.DVC_AS
        and _designation(second) is DecisiveVoltageClass.DVC_AS
    )
    if both and pair.protection_implementation is ProtectionImplementation.FUNCTIONAL_INSULATION:
        return _DvcAsAdjacency(
            not_applicable=(
                f"Pair {pair.key} is functional insulation between two adjacent DVC A-s "
                "circuits, which need not be voltage tested. Basic insulation between DVC A-s "
                "circuits does have to be, so this answer follows the construction selected "
                f"for this pair and no other pair of the group. {DVC_AS_HIGHER_PORTION_STEP}"
            )
        )
    service = VoltageEvidenceService()
    figures = {
        net.name: service.governing(
            project, EvidenceTarget(net_id=net.id), VoltageQuantityKind.RECURRING_PEAK
        ).effective_value_v
        for net in (first, second)
    }
    missing = sorted(name for name, value in figures.items() if value is None)
    keying = (
        f"This test is keyed on the higher-voltage of {first.name} and {second.name} rather "
        "than on the circuit under test, because one of them is a DVC A-s circuit."
    )
    steps = (keying, DVC_AS_HIGHER_PORTION_STEP)
    if missing:
        return _DvcAsAdjacency(
            unresolved=(
                (
                    f"Pair {pair.key} is tested between a DVC A-s circuit and an adjacent "
                    "circuit, whose row is keyed on the higher-voltage of the two. No "
                    f"recurring-peak working voltage is established for {', '.join(missing)}, "
                    "so which of them is the higher cannot be decided. The pair's own figure "
                    "is not read in their place: it is a voltage across the insulation and not "
                    "either circuit's own."
                ),
            ),
            preparation=steps,
        )
    highest = max(figures, key=lambda name: figures[name] or Decimal(0))
    return _DvcAsAdjacency(
        row_v=figures[highest],
        row_label=f"recurring-peak working voltage of {highest}, the higher-voltage circuit,",
        preparation=steps,
    )


def _circuit_side_class(project: Project, pair: PairCase) -> DecisiveVoltageClass | None:
    """The decisive voltage class of the circuit side of a pair, where one is assigned."""

    nets = {net.id: net for net in project.net_classes}
    first, second = nets[pair.net_a], nets[pair.net_b]
    return _designation(first if first.net_type is NetClassType.CIRCUIT else second)


def _recurring_peak(project: Project, pair: PairCase, effective: EffectiveCase) -> Decimal | None:
    """The recurring-peak working voltage established for one pair, or nothing.

    Whichever is more severe of the entries approved in the evidence library and the figure
    recorded on the pair itself. The pair's own entry is offered for comparison rather than
    turned into evidence - it is a dimensioning input somebody typed, not a figure anybody
    signed for.

    Resolved once per pair and handed to everything that reads it, so a dielectric row and a
    partial-discharge assessment of the same pair can never be looking at two different
    working voltages.
    """

    entry = effective.voltages.recurring_peak_v
    stated = entry.value if entry.applicability is Applicability.APPLICABLE else None
    governing = VoltageEvidenceService().governing(
        project,
        EvidenceTarget(pair_id=pair.id),
        VoltageQuantityKind.RECURRING_PEAK,
        derived_v=stated,
        derived_source=f"the recurring peak recorded on pair {pair.key}",
    )
    return governing.effective_value_v


def _overvoltage_present(
    effective: EffectiveCase,
    resolution: EffectivePairStressResolution | None,
) -> bool | None:
    """Whether a temporary overvoltage is present on this pair. ``None`` means nobody said.

    Three states, not two, because the non-mains dielectric route turns on exactly this
    question and "nothing is recorded" is not an answer of "no". The pair's own entry is asked
    first and an exclusion recorded on it stands over a derived value, which is the precedence
    the stress resolution already applies - the disagreement is surfaced there rather than
    being settled twice, differently, in two places.
    """

    entry = effective.voltages.temporary_overvoltage_peak_v
    if entry.applicability is Applicability.NOT_APPLICABLE:
        return False
    if entry.applicability is Applicability.APPLICABLE:
        return True
    if resolution is not None and resolution.temporary_overvoltage.applies:
        return True
    return None


def _non_mains_route_gap(pair: PairCase, overvoltage_present: bool | None) -> str:
    """Why a non-mains pair that is not on the no-overvoltage route gets no voltage here."""

    if overvoltage_present is None:
        return (
            f"Nothing establishes whether a temporary overvoltage is present on pair "
            f"{pair.key}, and the two non-mains routes differ by exactly that. Record whether "
            "the nature of its supply produces one; a circuit nobody has answered for is not "
            "read as a circuit that has none."
        )
    return (
        f"Pair {pair.key} is a non-mains circuit carrying a temporary overvoltage, so its "
        "test voltage is derived from that overvoltage and not read from a table row. The "
        f"active package's {ids.TEST_NON_MAINS_DIELECTRIC_VALUES} projects only the route for "
        "a circuit that has none, and nothing in it states the derivation or the factor the "
        "enhanced-protection and accessible-surface tests apply to it."
    )


def _mains_row_value(
    mains: Sequence[DerivedSupplyScenario],
) -> tuple[Decimal | None, str, tuple[str, ...]]:
    """The most severe temporary-overvoltage system voltage across the supplies that reach here.

    A supply whose temporary-overvoltage measure the derivation did not resolve contributes
    nothing and is named, rather than contributing its impulse measure. The two are separate
    questions the package answers separately, and substituting the answer to one for the
    answer to the other is what this function was fixed for.
    """

    unresolved = tuple(
        (
            f"{scenario.configuration_name} resolved no temporary-overvoltage system voltage, "
            "and that measure is what keys the mains dielectric row. Its impulse system "
            "voltage is a different measure of the supply and is not read in its place."
        )
        for scenario in mains
        if scenario.system_voltage_for_tov_v is None
    )
    resolved = {
        scenario.configuration_name: scenario.system_voltage_for_tov_v
        for scenario in mains
        if scenario.system_voltage_for_tov_v is not None
    }
    if not resolved:
        return None, "no temporary-overvoltage system voltage", unresolved
    highest = max(resolved.values())
    names = ", ".join(sorted(resolved))
    return highest, f"system voltage {highest} V from {names}", unresolved


def _row_value(
    pair: PairCase,
    mains: Sequence[DerivedSupplyScenario],
    recurring_peak_v: Decimal | None,
    overvoltage_present: bool | None,
    row_label: str,
) -> tuple[Decimal | None, str, tuple[str, ...]]:
    """The voltage that keys the dielectric table's row axis, and where it came from.

    For a mains circuit that is the system voltage of the supply, at the measure the
    derivation resolved for the *temporary-overvoltage* question and not the impulse one. The
    two are different measures of one supply for at least one arrangement the package
    distinguishes, and this test is a test of withstand under temporary overvoltage
    conditions, so the temporary-overvoltage measure is the one that keys it. On the
    arrangement where they differ the impulse measure is the lower, which is what made reading
    it a plan under the row the package states.

    A non-mains circuit is keyed on its recurring-peak working voltage only where no temporary
    overvoltage is present on it, because that is the condition the package's non-mains route
    is stated for. The other two states return no row at all: one is a circuit whose test
    voltage comes from somewhere this package does not project, and the other is a circuit
    nobody has answered the question for. Neither is a reason to read the route anyway.
    """

    if mains:
        return _mains_row_value(mains)
    if overvoltage_present is not False:
        return (
            None,
            "no non-mains route resolved",
            (_non_mains_route_gap(pair, overvoltage_present),),
        )
    if recurring_peak_v is None:
        return (
            None,
            "no recurring-peak working voltage",
            (
                (
                    f"No recurring-peak working voltage is established for pair {pair.key}, "
                    "so the non-mains dielectric table cannot be read for it."
                ),
            ),
        )
    return (
        recurring_peak_v,
        f"{row_label} {recurring_peak_v} V",
        (),
    )


def _dielectric_value(
    table: Table, row: Decimal | None
) -> tuple[Quantity | None, tuple[TraceStep, ...], tuple[str, ...]]:
    """Read one dielectric route at ``row``, or say why the package would not answer.

    The row is selected the way the table's own reviewed interpolation permits: linearly where
    the source states interpolation is allowed, and otherwise at the band the value falls in,
    whose axis is the band's upper bound. Whether interpolation is permitted is the package's
    statement and is read off the table rather than restated here.

    A route stating more than one column is refused. The package labels a dielectric column by
    the source column it came from, so nothing in it says which of several applies to this
    test, and choosing one would be this application inventing a reading of the source.
    """

    if row is None:
        return None, (), ()
    columns = table.column_axis.values
    if len(columns) != 1:
        return (
            None,
            (),
            (
                (
                    f"The active package's {table.id} states {len(columns)} columns and "
                    "nothing in it says which one applies to this test."
                ),
            ),
        )
    expression = TableSelect(
        table_id=table.id,
        row=Variable(name="row"),
        column=Literal(value=columns[0]),
        row_mode="linear" if table.interpolation == "linear" else "ceiling",
        column_mode="exact",
    )
    try:
        evaluated = evaluate_formula(
            expression,
            {"row": Quantity(value=row, unit=_VOLTAGE_UNIT)},
            {table.id: table},
        )
    except EvaluationError as error:
        return None, (), (f"The active package's {table.id} cannot be read at {row} V: {error}",)
    return (
        Quantity(value=evaluated.value, unit=evaluated.unit),
        evaluated.steps,
        (),
    )


def _column_reason(
    classification: TestClassification,
    reference_kind: TestReferenceKind,
    enhanced: bool,
) -> str:
    """Why this classification reads the column it reads, in one clause of a sentence."""

    if classification is not TestClassification.TYPE:
        return "every routine test reads the basic column"
    if enhanced:
        return "the type test of a pair protected by enhanced protection reads the enhanced column"
    if reference_kind is TestReferenceKind.DVC_AS_ADJACENT_CIRCUIT:
        return (
            "the type test between a DVC A-s circuit and an adjacent circuit reads the "
            "enhanced column whatever the pair's construction"
        )
    if reference_kind in _ENHANCED_COLUMN_TOPOLOGIES:
        return (
            "the type test against an accessible surface that is non-conductive, or "
            "conductive and not bonded to PE, reads the enhanced column whatever the pair's "
            "construction"
        )
    return "the type test reads the basic column"


def _route_step(
    table: Table,
    classification: TestClassification,
    row: Decimal | None,
    row_reason: str,
    column_reason: str,
) -> tuple[TraceStep, ...]:
    """Which route answers this classification, and what the row axis was keyed on.

    Empty where no row key was established: there is nothing to explain about a lookup that
    was never attempted, and the unresolved input on the application already says why.
    """

    if row is None:
        return ()
    return (
        TraceStep(
            semantic_rule_id=DIELECTRIC_ROUTE_TRACE_ID,
            operation="select",
            symbolic=rf"\operatorname{{route}}(\text{{{classification.value}}})",
            substituted=f"{table.id} keyed on {row_reason}",
            inputs=(),
            source_reference=table.source,
            output=Quantity(value=row, unit=_VOLTAGE_UNIT),
            unrounded_value=row,
            reason=(f"The {classification.value} test is read from {table.id}: {column_reason}."),
        ),
    )


# --- the assembled-equipment routine exemption -----------------------------------------------


def _exempted(
    applications: Iterable[TestApplication],
    exemption: RoutineExemptionAssessment,
) -> tuple[TestApplication, ...]:
    """The same rows, with the routine ones marked where the exemption was granted.

    Marked, never removed. A schedule that dropped the row would be indistinguishable from one
    where nobody planned the test in the first place, and this is the only place in the plan
    where getting it wrong takes work away rather than adding it. The row stays, its
    applicability becomes not required, and the conditions that carried the exemption are
    written onto it so whoever signs the schedule reads the grounds beside the row they are
    not performing.

    Whatever the row still had outstanding stays on it. What is unknown about *performing* a
    test - a duration no resolved rule states, a table that could not be read - does not become
    known by not performing it, and deleting those lines because the test was excused would
    lose the only record that the plan never fully resolved this row.

    Deduplication makes this conservative across a connected group without any help: it keeps
    the least settled applicability of the rows it folds, so one pair's exemption cannot excuse
    another pair of the group that has not earned one.
    """

    if not exemption.exemption_permitted:
        return tuple(applications)
    grounds = (
        f"The assembled-equipment routine test exemption is granted for pair "
        f"{exemption.pair_key} under {', '.join(exemption.source_rule_ids)}, on these grounds: "
        + "; ".join(item.detail for item in exemption.conditions)
        + ". The row is retained and marked; it is not removed from the schedule."
    )
    return tuple(
        application.model_copy(
            update={
                "applicability": TestApplicability.NOT_REQUIRED,
                "preparation_steps": (*application.preparation_steps, grounds),
                "source_rule_ids": _unique(
                    (*application.source_rule_ids, *exemption.source_rule_ids)
                ),
            }
        )
        if TestClassification.ROUTINE in application.classifications
        else application
        for application in applications
    )


# --- internal SPD monitoring ---------------------------------------------------------------


def _monitoring_application(
    subject: TestSubject,
    rules: VerificationRuleSet,
    revision: str,
    dependency: SpdMonitoringDependency,
    owed: str,
) -> TestApplication:
    """The dedicated monitoring type test one recorded impulse reduction depends on.

    Generated only where the resolution recorded a dependency, which it does only for a
    reduction a device inside the equipment justifies. A device that reduces nothing is not a
    device this schedule tests.

    The row stands between the pair's own electrodes. That is not where the monitoring is
    measured - it is a function of the device, not of the insulation - but it is what ties the
    test to the reduction it underwrites, and it means two pairs of one connected group
    carrying the same reduction produce one row rather than two.

    ``owed`` is carried as the row's unresolved input, so the schedule stays incomplete until
    somebody acknowledges the test. There is nowhere in the project to record that
    acknowledgement yet, which is exactly why the row says so rather than reading as done.
    """

    procedure = rules.internal_spd_monitoring
    steps, rule_ids = monitoring_preparation(dependency, procedure)
    return _application(
        subject=subject,
        test_kind=TestKind.INTERNAL_SPD_MONITORING,
        classifications=classifications_of(procedure),
        revision=revision,
        voltage=None,
        waveform=procedure.waveform,
        polarity=procedure.polarity,
        duration=procedure.duration,
        repetitions=procedure.repetitions,
        preparation_steps=steps,
        unresolved=(owed,),
        source_rule_ids=rule_ids,
        trace_steps=(),
    )


# --- partial discharge -------------------------------------------------------------------


def _discharge_application(
    subject: TestSubject,
    rules: VerificationRuleSet,
    revision: str,
    outcome: PartialDischargeOutcome,
) -> TestApplication:
    """One schedule row for the partial-discharge test, whatever the assessment concluded.

    The row exists even where the test does not apply. A pair whose solid insulation was
    assessed and found to need nothing is a different thing from a pair nobody assessed, and a
    schedule that showed only the required tests could not tell them apart.

    Its applicability comes from the assessment rather than from whether anything is
    unresolved, because this is the one test whose rule can settle "not required" - and the
    settled answers carry no unresolved inputs, so the two never contradict each other.
    """

    procedure = rules.partial_discharge.procedure
    return _application(
        subject=subject,
        test_kind=TestKind.PARTIAL_DISCHARGE,
        classifications=classifications_of(procedure),
        revision=revision,
        voltage=None,
        waveform=procedure.waveform,
        polarity=procedure.polarity,
        duration=procedure.duration,
        repetitions=procedure.repetitions,
        preparation_steps=(
            *subject.preparation_steps,
            *(step.text for step in procedure.preparation_steps),
            *outcome.preparation_steps,
        ),
        unresolved=outcome.unresolved_inputs,
        source_rule_ids=outcome.source_rule_ids,
        trace_steps=outcome.trace_steps,
        applicability=outcome.applicability,
    )


# --- working voltage -------------------------------------------------------------------


def _working_voltage_applications(
    project: Project,
    determinations: Iterable[WorkingVoltageDetermination],
    subjects: Sequence[TestSubject],
    rules: VerificationRuleSet,
    revision: str,
) -> tuple[TestApplication, ...]:
    """One schedule row per working-voltage determination.

    A determination's reference kind is read off its target, because
    :class:`~insulation_coordination.domain.verification.WorkingVoltageDetermination` carries
    none: a determination whose target is a net is the working voltage *within* that circuit,
    and one whose target is a pair takes the pair's own relationship. That is the only place
    ``WITHIN_CIRCUIT`` enters the schedule, and it is why the topology module never returns it.
    """

    by_pair = {subject.pair_id: subject for subject in subjects}
    procedure = rules.working_voltage_determination
    applications: list[TestApplication] = []
    for determination in determinations:
        if determination.target.pair_id is not None:
            subject = by_pair.get(determination.target.pair_id)
            if subject is None:
                continue
            high, low, kind = (
                subject.high_side_net_ids,
                subject.low_side_net_ids,
                subject.reference_kind,
            )
            covered: tuple[UUID, ...] = (subject.pair_id,)
            preparation = subject.preparation_steps
        else:
            net_id = determination.target.net_id
            assert net_id is not None  # an EvidenceTarget names exactly one subject
            high, low, kind = (net_id,), (), TestReferenceKind.WITHIN_CIRCUIT
            covered = ()
            name = next(net.name for net in project.net_classes if net.id == net_id)
            preparation = (f"Establish the working voltage within {name}.",)
        applications.append(
            _application(
                subject=None,
                test_kind=TestKind.WORKING_VOLTAGE_DETERMINATION,
                classifications=classifications_of(procedure),
                revision=revision,
                voltage=None,
                waveform=procedure.waveform,
                polarity=procedure.polarity,
                duration=procedure.duration,
                repetitions=procedure.repetitions,
                preparation_steps=(
                    *preparation,
                    *determination.preparation_steps,
                ),
                unresolved=determination.unresolved_inputs,
                source_rule_ids=determination.source_rule_ids,
                trace_steps=(),
                reference_kind=kind,
                high_side_net_ids=high,
                low_side_net_ids=low,
                covered_pair_ids=covered,
            )
        )
    return tuple(applications)


# --- shared ----------------------------------------------------------------------------


def _application(
    *,
    subject: TestSubject | None,
    test_kind: TestKind,
    classifications: tuple[TestClassification, ...],
    revision: str,
    voltage: Quantity | None,
    waveform: str | None,
    polarity: str | None,
    duration: str | None,
    repetitions: str | None,
    preparation_steps: tuple[str, ...],
    unresolved: tuple[str, ...],
    source_rule_ids: tuple[str, ...],
    trace_steps: tuple[TraceStep, ...],
    reference_kind: TestReferenceKind | None = None,
    high_side_net_ids: tuple[UUID, ...] = (),
    low_side_net_ids: tuple[UUID, ...] = (),
    covered_pair_ids: tuple[UUID, ...] | None = None,
    applicability: TestApplicability | None = None,
) -> TestApplication:
    """One application, with the only identity a generated test is allowed to have.

    Applicability is decided by whether anything is missing: an application with an unresolved
    input is an engineering input, never a ``NOT_REQUIRED`` that reads the same in a schedule
    and means the opposite to whoever signs it.

    ``applicability`` overrides that for the one test whose own rule can settle the question
    both ways. It still cannot state a settled answer over an unresolved input: anything
    outstanding makes the application an engineering input whatever the caller passed, so the
    two halves of a row can never say different things.
    """

    if subject is not None:
        reference_kind = subject.reference_kind
        high_side_net_ids = subject.high_side_net_ids
        low_side_net_ids = subject.low_side_net_ids
        covered_pair_ids = (subject.pair_id,)
    assert reference_kind is not None  # every caller supplies a subject or a reference kind
    return TestApplication(
        test_id=build_test_id(
            test_kind=test_kind,
            reference_kind=reference_kind,
            classifications=classifications,
            high_side_net_ids=high_side_net_ids,
            low_side_net_ids=low_side_net_ids,
            rule_revision=revision,
        ),
        covered_pair_ids=covered_pair_ids or (),
        test_kind=test_kind,
        classifications=classifications,
        high_side_net_ids=high_side_net_ids,
        low_side_net_ids=low_side_net_ids,
        reference_kind=reference_kind,
        voltage=voltage,
        waveform=waveform,
        polarity=polarity,
        duration=duration,
        repetitions=repetitions,
        preparation_steps=preparation_steps,
        applicability=(
            TestApplicability.ENGINEERING_INPUT_REQUIRED
            if unresolved
            else applicability or TestApplicability.REQUIRED
        ),
        unresolved_inputs=_unique(unresolved),
        source_rule_ids=source_rule_ids,
        trace_steps=trace_steps,
    )


def _mains_scenarios(
    resolution: EffectivePairStressResolution | None,
) -> tuple[DerivedSupplyScenario, ...]:
    """Every mains supply that *supplies* either side of the pair, in configuration order.

    Read from the domains' own sources and never from stresses that arrived across verified
    isolation, exactly as a mains temporary overvoltage is. A circuit behind a barrier is not
    a mains circuit: the barrier is what makes the non-mains table the one that applies to it,
    and folding a transferred supply in here would send every circuit of the project to the
    mains table.

    Deliberately not the ``mains_supplied`` question the override resolution asks, which does
    count a transferred supply. That one selects which reduction route a limiter's monitoring
    is asked of - what reaches the device - while this one asks what the circuit is connected
    to. Two questions, two answers, and no reason for either to borrow the other's.
    """

    if resolution is None:
        return ()
    found: dict[UUID, DerivedSupplyScenario] = {}
    for side in (resolution.side_a, resolution.side_b):
        if side.stress is None:
            continue
        for source in side.stress.own:
            if source.scenario.supply_kind in MAINS_SUPPLY_KINDS:
                found[source.scenario.configuration_id] = source.scenario
    return tuple(found.values())


def _spd_dependency(
    resolution: EffectivePairStressResolution | None,
) -> SpdMonitoringDependency | None:
    outcome = None if resolution is None else resolution.override_outcome
    return None if outcome is None else outcome.spd_monitoring_dependency


def _pair_status(
    pair: PairCase,
    applications: Sequence[TestApplication],
    unresolved: Sequence[str],
) -> VerificationStatus:
    """How far this pair's verification has got.

    A selection nobody has confirmed is a review, not a plan: a protection implementation this
    application mapped during a migration is not a decision an engineer made, and a schedule
    that reported it as planned would hide that.

    ``unresolved`` is what the pair itself has outstanding rather than what its tests have. A
    requirement that could not be read, and an implementation that does not meet the one that
    was, are findings about the pair that no individual test row carries - and a pair reported
    as planned while one of them stands would be a plan nobody should sign.
    """

    if unresolved or any(
        item.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED for item in applications
    ):
        return VerificationStatus.ENGINEERING_REVIEW_REQUIRED
    if pair.protection_review_state is not ReviewState.USER_CONFIRMED:
        return VerificationStatus.ENGINEERING_REVIEW_REQUIRED
    return VerificationStatus.PLANNED


def _covering_test_ids(
    applications: Iterable[TestApplication],
) -> dict[UUID, tuple[str, ...]]:
    covering: dict[UUID, list[str]] = {}
    for application in applications:
        for pair_id in application.covered_pair_ids:
            covering.setdefault(pair_id, []).append(application.test_id)
    return {pair_id: tuple(ids) for pair_id, ids in covering.items()}


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _words(token: str) -> str:
    """One vocabulary token as prose. The tokens are neutral names, so opening them is enough."""

    return token.replace("_", " ")


__all__ = [
    "DIELECTRIC_ROUTE_TRACE_ID",
    "DVC_AS_HIGHER_PORTION_STEP",
    "ENHANCED_PROTECTION_IMPLEMENTATIONS",
    "ENHANCED_SPACING_MISMATCH_WARNING",
    "HF_TRANSFORMER_SHOWING_WARNING",
    "PROTECTION_REQUIREMENT_UNMET_WARNING",
    "SPD_MONITORING_OWED_WARNING",
    "PairVerificationAssessment",
    "VerificationPlan",
    "VerificationPlanService",
]
