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

from collections.abc import Iterable, Sequence
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
from insulation_coordination.domain.enums import Applicability, InsulationType, ReviewState
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.project import (
    EffectiveCase,
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
from insulation_coordination.domain.supply import MAINS_SUPPLY_KINDS, DerivedSupplyScenario
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

_VOLTAGE_UNIT: Final = "V"

#: The five constructions the standard offers for an enhanced level of protection. Enhanced
#: protection is a reliability level rather than a voltage class, so this is a property of the
#: *implementation* an engineer selected and never of the pair's decisive voltage class.
ENHANCED_PROTECTION_IMPLEMENTATIONS: Final[frozenset[ProtectionImplementation]] = frozenset(
    {
        ProtectionImplementation.REINFORCED_INSULATION,
        ProtectionImplementation.DOUBLE_INSULATION,
        ProtectionImplementation.PROTECTIVE_SCREEN_PLUS_BASIC,
        ProtectionImplementation.PROTECTIVE_IMPEDANCE,
        ProtectionImplementation.OTHER_REVIEWED_MEANS,
    }
)

#: Warning codes a report can group on without matching a message.
ENHANCED_SPACING_MISMATCH_WARNING: Final = "verification_enhanced_protection_not_dimensioned"
SPD_MONITORING_OWED_WARNING: Final = "verification_internal_spd_monitoring_owed"

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

        generated: list[TestApplication] = []
        assessments: list[PairVerificationAssessment] = []
        warnings: list[CalculationWarning] = []
        for subject in subjects:
            pair = pairs[subject.pair_id]
            effective, resolution = resolve_supply_effective_case(project, pair, supply)
            applications, assessment = _plan_pair(
                project, pair, subject, effective, resolution, rule_set, revision, warnings
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
    recurring_peak = _recurring_peak(project, pair, effective)
    dielectric = _dielectric_applications(
        pair, subject, rules, revision, enhanced, mains, recurring_peak
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
        *monitoring,
    )
    return applications, PairVerificationAssessment(
        pair_id=pair.id,
        pair_key=pair.key,
        reference_kind=subject.reference_kind,
        protection_implementation=implementation,
        protection_review_state=pair.protection_review_state,
        enhanced_protection=enhanced,
        mains_connected=bool(mains),
        spd_monitoring_dependency=dependency,
        partial_discharge=discharge.applicability,
        recurring_peak_v=recurring_peak,
        routine_exemption=exemption,
        status=_pair_status(pair, applications),
        unresolved_inputs=tuple(unresolved),
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

    procedure = _impulse_procedure(rules, implementation, resolution)
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
    resolution: EffectivePairStressResolution | None,
) -> ProcedureRule | None:
    """Which of the impulse procedure's variants states the conditions for this pair.

    A pair whose impulse was reduced by a verified override is a transient-reduction case, and
    the variant the package projects for it states conditions the other two do not. It is
    selected in preference to the construction variants because it is the narrower statement:
    the reduction is the reason this pair's figure is what it is.
    """

    outcome = None if resolution is None else resolution.override_outcome
    if outcome is not None and outcome.applied and outcome.override.is_reduction:
        return rules.impulse_procedure.transient_reduction
    if implementation is None:
        return None
    if implementation in ENHANCED_PROTECTION_IMPLEMENTATIONS:
        return rules.impulse_procedure.insulation_reinforced
    return rules.impulse_procedure.insulation_basic


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
) -> tuple[TestApplication, ...]:
    """The routine and type dielectric applications, in both voltage forms the package states.

    A mains-connected circuit is looked up in the mains table on the system voltage its supply
    resolved to; every other circuit is looked up in the non-mains table on its recurring-peak
    working voltage. A circuit reached by more than one supply is mains-connected if any of
    them is, and the most severe of their system voltages is what keys the row.

    The routine test and the basic-protection type test share one route because the package's
    own route says it covers both. The enhanced-protection type test is read from its own
    route and is never taken from the other one: reusing a value across the two would assert
    an equality the source was not asked for.
    """

    tables = rules.mains_dielectric_values if mains else rules.non_mains_dielectric_values
    row, row_reason, row_unresolved = _row_value(pair, mains, recurring_peak_v)
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


def _row_value(
    pair: PairCase,
    mains: Sequence[DerivedSupplyScenario],
    recurring_peak_v: Decimal | None,
) -> tuple[Decimal | None, str, tuple[str, ...]]:
    """The voltage that keys the dielectric table's row axis, and where it came from.

    For a mains circuit that is the system voltage of the supply, which the derivation already
    resolved to the measure the package named for that arrangement. For every other circuit it
    is the recurring-peak working voltage.
    """

    if mains:
        highest = max(scenario.system_voltage_for_impulse_v for scenario in mains)
        names = ", ".join(sorted({scenario.configuration_name for scenario in mains}))
        return highest, f"system voltage {highest} V from {names}", ()
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


def _pair_status(pair: PairCase, applications: Sequence[TestApplication]) -> VerificationStatus:
    """How far this pair's verification has got.

    A selection nobody has confirmed is a review, not a plan: a protection implementation this
    application mapped during a migration is not a decision an engineer made, and a schedule
    that reported it as planned would hide that.
    """

    if any(
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


__all__ = [
    "DIELECTRIC_ROUTE_TRACE_ID",
    "ENHANCED_PROTECTION_IMPLEMENTATIONS",
    "ENHANCED_SPACING_MISMATCH_WARNING",
    "SPD_MONITORING_OWED_WARNING",
    "PairVerificationAssessment",
    "VerificationPlan",
    "VerificationPlanService",
]
