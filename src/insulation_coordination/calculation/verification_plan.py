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

#: How each test relationship reads as Table 3's ``target`` dimension. Three of the four are
#: one accessible part as far as the requirement is concerned; what differs between them is
#: what the test is applied to, which the topology already carries.
_REQUIREMENT_TARGETS: Final[Mapping[TestReferenceKind, str]] = {
    TestReferenceKind.ADJACENT_CIRCUIT: "adjacent_circuit",
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

#: Warning codes a report can group on without matching a message.
ENHANCED_SPACING_MISMATCH_WARNING: Final = "verification_enhanced_protection_not_dimensioned"
SPD_MONITORING_OWED_WARNING: Final = "verification_internal_spd_monitoring_owed"
PROTECTION_REQUIREMENT_UNMET_WARNING: Final = "verification_protection_requirement_not_met"

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

    impulse = _impulse_application(
        pair, subject, effective, resolution, rules, revision, implementation, enhanced, warnings
    )
    override = _verified_reduction(resolution)
    reduction = (
        () if override is None else (_reduction_application(subject, rules, revision, override),)
    )
    recurring_peak = _recurring_peak(project, pair, effective)
    dielectric = _dielectric_applications(
        pair,
        subject,
        rules,
        revision,
        enhanced,
        mains,
        recurring_peak,
        _overvoltage_present(effective, resolution),
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
    if subject.reference_kind is TestReferenceKind.ADJACENT_CIRCUIT:
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
        if subject.reference_kind is TestReferenceKind.ADJACENT_CIRCUIT:
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
    warnings: list[CalculationWarning],
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
    preparation = [*subject.preparation_steps, _ALTERNATIVE_METHOD_STEP, _CLEARANCE_SCOPE_STEP]
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
    unresolved.extend(_altitude_inputs(pair, effective))
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
            f"Pair {pair.key} is protected by a protective impedance, whose verification is a "
            "separately disclosed engineering item rather than a dimensioned spacing."
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
) -> TestApplication:
    """The type test that verifies a claimed reduction of the overvoltage does what is claimed.

    Owed in addition to the insulation impulse applications of the pairs the reduction affects
    and never instead of one: clause 5.2.3.2 states it as a further requirement, and the
    package's own variant of the procedure carries its own subject, preconditioning answer and
    power condition. Clause 4.4.7.3 asks for the same test where circuit characteristics
    rather than a device are what the reduction rests on, which is why this is generated for
    every applied reduction and not only for the ones that owe monitoring.

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


def _altitude_inputs(pair: PairCase, effective: EffectiveCase) -> tuple[str, ...]:
    """What the plan owes a reader about altitude, without correcting anything for it.

    The package's test-voltage altitude correction belongs to the test whose voltage it
    corrects and is resolved against that test, not up front - see ``RULES_READ_ELSEWHERE``
    in the rule adapter. Until it is, a planned voltage at an altitude above the reference is
    an uncorrected one, and saying so is the only honest thing to do with it.
    """

    altitude = effective.altitude_m.value
    if altitude is None:
        return (
            (
                f"No altitude is recorded for pair {pair.key}, so whether its planned test "
                "voltage needs an altitude correction cannot be answered."
            ),
        )
    if altitude > 0:
        return (
            (
                f"Pair {pair.key} is dimensioned at {altitude} m. The package's test-voltage "
                "altitude correction is not applied to the voltage planned here."
            ),
        )
    return ()


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
    """

    tables = rules.mains_dielectric_values if mains else rules.non_mains_dielectric_values
    row, row_reason, row_unresolved = _row_value(pair, mains, recurring_peak_v, overvoltage_present)
    routes: tuple[tuple[TestClassification, VoltageTablePair], ...] = (
        (TestClassification.ROUTINE, tables.routine_and_basic_type),
        (
            TestClassification.TYPE,
            tables.enhanced_type if enhanced else tables.routine_and_basic_type,
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
                    preparation_steps=subject.preparation_steps,
                    unresolved=(
                        *row_unresolved,
                        *unresolved,
                        (
                            f"The active package's {table.id} states no duration for this "
                            "test; it is read from the procedure the test is performed under."
                        ),
                    ),
                    source_rule_ids=(table.id,),
                    trace_steps=(*_route_step(table, classification, row, row_reason), *steps),
                )
            )
    return tuple(applications)


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
        f"recurring-peak working voltage {recurring_peak_v} V",
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


def _route_step(
    table: Table,
    classification: TestClassification,
    row: Decimal | None,
    row_reason: str,
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
            reason=(
                f"The {classification.value} test is read from {table.id}, which is the route "
                "the package states for it."
            ),
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
    "ENHANCED_PROTECTION_IMPLEMENTATIONS",
    "ENHANCED_SPACING_MISMATCH_WARNING",
    "PROTECTION_REQUIREMENT_UNMET_WARNING",
    "SPD_MONITORING_OWED_WARNING",
    "PairVerificationAssessment",
    "VerificationPlan",
    "VerificationPlanService",
]
