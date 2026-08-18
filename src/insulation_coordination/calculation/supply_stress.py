"""Derives one supply configuration's stresses, and picks the worst across a whole project.

Two questions, kept apart because the standard keeps them apart:

*Which voltage of this arrangement is the system voltage?* Answered by the package's own
resolution rule, which names a **measure** and never a calculation. This module asks it once
for the impulse question and once, independently, for the temporary-overvoltage question -
a three-phase IT arrangement answers them differently - and then reads the value the
configuration states for the named measure. It never converts one measure into another. There
is no phase-to-neutral division here and no place one could be added: a measure whose value
the configuration does not state blocks, and that is the whole of the fallback behaviour.

*What does that system voltage require?* Answered by the package's two lookups. The impulse
lookup selects a band and the temporary-overvoltage lookup may interpolate between them, which
is a difference the rule adapter has already enforced on the package's shape before this module
sees it - see :mod:`~insulation_coordination.calculation.supply_rules`. Neither prohibition is
re-checked here, and neither can be bypassed here either, because the only way to a value is
through the reviewed formula the adapter resolved.

Nothing in this module is a fallback. Every failure is a typed
:class:`~insulation_coordination.domain.supply.SupplyDerivationBlock` naming what was missing,
carried on an :class:`~insulation_coordination.domain.supply.UnresolvedSupplyScenario` beside
the scenarios that did derive. Every value that does come out carries the trace steps and the
rule ids it came from.

No IEC value appears here. The identifiers below are the neutral vocabulary the importer's
own public modules declare for these rules' inputs, outputs and table columns; which
arrangement resolves to which measure, and what any band contains, stays in the package.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from typing import Final, NamedTuple
from uuid import UUID

from insulation_coordination.calculation.supply_rules import (
    SupplyForm,
    SupplyLookup,
    SupplyRuleSet,
)
from insulation_coordination.domain.supply import (
    MAINS_SUPPLY_KINDS,
    DerivedSupplyScenario,
    EarthingArrangement,
    GoverningSupplyStress,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    SupplyConfiguration,
    SupplyDerivationBlock,
    SupplyDerivationBlockCode,
    SupplyKind,
    UnresolvedSupplyScenario,
    completeness_problems,
    validate_supply_configurations,
)
from insulation_coordination.domain.trace import CalculationWarning, Quantity, TraceStep
from insulation_coordination.rules.evaluator import (
    EvaluationError,
    evaluate_decision,
    evaluate_formula,
)

_VOLTAGE_UNIT: Final = "V"
_MEASURE_OUTPUT: Final = "system_voltage_measure"

#: The two questions the resolution rule distinguishes. Asked separately and never derived
#: from one another: an arrangement is allowed to answer them with different measures, and
#: several do.
IMPULSE_PURPOSE: Final = "impulse"
TOV_PURPOSE: Final = "temporary_overvoltage"

#: The column each overvoltage category selects from the impulse table, and the column each
#: temporary-overvoltage basis selects from its own. These are the data columns' declared
#: identifiers, built by the importer recipe rather than published in ``semantic_ids``; a
#: table that carries none of them blocks rather than being read positionally.
_IMPULSE_COLUMNS: Final[Mapping[OvervoltageCategory, str]] = {
    OvervoltageCategory.I: "impulse_ovc_1_v",
    OvervoltageCategory.II: "impulse_ovc_2_v",
    OvervoltageCategory.III: "impulse_ovc_3_v",
    OvervoltageCategory.IV: "impulse_ovc_4_v",
}
TOV_RMS_COLUMN: Final = "temporary_overvoltage_rms_v"
TOV_PEAK_COLUMN: Final = "temporary_overvoltage_peak_v"

#: The warning a mains configuration in the lowest overvoltage category always carries. It
#: cannot be dismissed because nothing stores a dismissal: every warning here is recomputed
#: from the configuration, so it is present exactly while the category is selected.
OVERVOLTAGE_CATEGORY_I_WARNING: Final = "supply_overvoltage_category_i"

#: The resolution rule's declared input vocabulary, mapped from this application's own. A
#: combination with no counterpart is absent rather than approximated, and blocks: the rule
#: cannot be asked a question in words it does not declare, and asking it a neighbouring one
#: would answer about an arrangement the user did not describe.
_TOPOLOGIES: Final[Mapping[InputTopology, str]] = {
    InputTopology.DIRECT_INPUT: "direct",
    InputTopology.RECTIFIED_FROM_AC: "rectified_dc",
    InputTopology.SERIES_CONNECTED_RECTIFIER_BRIDGES: "series_rectifier_bridges",
    # A custom reviewed configuration is deliberately absent. It describes an arrangement
    # nobody has stated a rule for, so there is nothing to resolve and no honest default.
}

#: An earthing arrangement this application offers as one choice can cover more than one of
#: the states the rule distinguishes. Both are asked, and they have to agree - see
#: :func:`_resolve_system_voltage`.
_EARTHINGS: Final[Mapping[EarthingArrangement, tuple[str, ...]]] = {
    EarthingArrangement.TN_STAR_POINT_EARTHED: ("tn",),
    EarthingArrangement.TT_STAR_POINT_EARTHED: ("tt",),
    EarthingArrangement.IT_THREE_PHASE: ("it",),
    EarthingArrangement.IT_SINGLE_PHASE: ("it",),
    EarthingArrangement.TN_TT_CORNER_EARTHED_DELTA: ("tn", "tt"),
    EarthingArrangement.TN_TT_HIGH_LEG_DELTA: ("tn", "tt"),
    EarthingArrangement.NOT_APPLICABLE: ("unspecified",),
}

#: The rule's phase-system input carries the conductor arrangement, not just the phase count,
#: so it is resolved from the phase system and the earthing arrangement together.
_THREE_PHASE_ARRANGEMENTS: Final[Mapping[EarthingArrangement, str]] = {
    EarthingArrangement.TN_STAR_POINT_EARTHED: "three_phase_star",
    EarthingArrangement.TT_STAR_POINT_EARTHED: "three_phase_star",
    EarthingArrangement.IT_THREE_PHASE: "three_phase_it",
    EarthingArrangement.TN_TT_CORNER_EARTHED_DELTA: "three_phase_delta",
    EarthingArrangement.TN_TT_HIGH_LEG_DELTA: "three_phase_delta",
    EarthingArrangement.NOT_APPLICABLE: "unspecified",
}
_SINGLE_PHASE_ARRANGEMENTS: Final[Mapping[EarthingArrangement, str]] = {
    EarthingArrangement.TN_STAR_POINT_EARTHED: "single_phase",
    EarthingArrangement.TT_STAR_POINT_EARTHED: "single_phase",
    EarthingArrangement.IT_SINGLE_PHASE: "single_phase_it",
    EarthingArrangement.NOT_APPLICABLE: "single_phase",
}


def supply_form(configuration: SupplyConfiguration) -> SupplyForm:
    """Which of the two parallel system-voltage axes this configuration is looked up on.

    A supply that is DC all the way back to its source is looked up on the DC axis. Everything
    else, a rectified mains input included, resolves to an AC RMS measure taken before any
    rectifier, so it is looked up on the AC axis.
    """

    return "dc" if configuration.supply_kind is SupplyKind.NON_MAINS_DC else "ac"


class _Derivation:
    """One configuration's derivation in progress, collecting steps, warnings and blocks."""

    def __init__(self, configuration: SupplyConfiguration, rules: SupplyRuleSet) -> None:
        self.configuration = configuration
        self.rules = rules
        self.form = supply_form(configuration)
        self.steps: list[TraceStep] = []
        self.warnings: list[CalculationWarning] = []
        self.blocks: list[SupplyDerivationBlock] = []
        self.rule_ids: list[str] = []
        self._reporting_warnings = False

    def block(
        self,
        code: SupplyDerivationBlockCode,
        message: str,
        *,
        semantic_rule_id: str | None = None,
    ) -> None:
        if self._reporting_warnings:
            self.warnings.append(
                CalculationWarning(
                    code=f"supply_{code.value}",
                    message=message,
                    semantic_rule_id=semantic_rule_id,
                )
            )
            return
        self.blocks.append(
            SupplyDerivationBlock(
                configuration_id=self.configuration.id,
                code=code,
                message=message,
                semantic_rule_id=semantic_rule_id,
            )
        )

    @contextmanager
    def reporting_warnings(self) -> Iterator[None]:
        """Inside this block a failure warns instead of blocking.

        Used for the temporary overvoltage, which a scenario is allowed to be without. The
        reason is still recorded in full and still names the rule it came from; only its
        severity differs, because an impulse the package refuses leaves nothing to compare and
        a temporary overvoltage it refuses leaves a scenario that is simply silent about one.
        """

        self._reporting_warnings = True
        try:
            yield
        finally:
            self._reporting_warnings = False

    def note_rule(self, rule_id: str) -> None:
        if rule_id not in self.rule_ids:
            self.rule_ids.append(rule_id)

    def unresolved(self) -> UnresolvedSupplyScenario:
        return UnresolvedSupplyScenario(
            configuration_id=self.configuration.id,
            configuration_name=self.configuration.name,
            blocks=tuple(self.blocks),
            trace_steps=tuple(self.steps),
        )


def _arrangement_inputs(
    configuration: SupplyConfiguration,
    earthing: str,
) -> dict[str, Decimal | str | bool] | None:
    """This configuration stated in the resolution rule's own words, or ``None`` if it cannot be."""

    phase = configuration.phase_system
    if phase is None:
        arrangement: str | None = "unspecified"
    elif phase is PhaseSystem.THREE_PHASE:
        arrangement = _THREE_PHASE_ARRANGEMENTS.get(configuration.earthing_arrangement)
    else:
        arrangement = _SINGLE_PHASE_ARRANGEMENTS.get(configuration.earthing_arrangement)
    topology = _TOPOLOGIES.get(configuration.input_topology)
    if arrangement is None or topology is None:
        return None
    return {
        "supply_kind": "mains" if configuration.supply_kind in MAINS_SUPPLY_KINDS else "non_mains",
        "phase_system": arrangement,
        "earthing_arrangement": earthing,
        "input_topology": topology,
    }


def _resolve_system_voltage(
    derivation: _Derivation,
    purpose: str,
) -> tuple[str, Decimal] | None:
    """The measure that applies to ``purpose``, and the voltage the configuration states for it.

    Every state the configuration's earthing choice covers is asked, and all of them have to
    resolve to the same measure. One choice here can stand for two of the rule's own states,
    and picking either one of them because it happened to be first would answer for an
    arrangement nobody described.
    """

    configuration = derivation.configuration
    rule = derivation.rules.system_voltage_resolution
    derivation.note_rule(rule.id)
    measures: list[str] = []
    source = None
    for earthing in _EARTHINGS[configuration.earthing_arrangement]:
        inputs = _arrangement_inputs(configuration, earthing)
        if inputs is None:
            derivation.block(
                SupplyDerivationBlockCode.UNSUPPORTED_ARRANGEMENT,
                f"The active package's resolution rule states nothing about a "
                f"{configuration.input_topology.value} {configuration.supply_kind.value} supply "
                f"with {configuration.earthing_arrangement.value} earthing.",
                semantic_rule_id=rule.id,
            )
            return None
        inputs["calculation_purpose"] = purpose
        try:
            result = evaluate_decision(rule, inputs)
        except EvaluationError as error:
            derivation.block(
                SupplyDerivationBlockCode.UNSUPPORTED_ARRANGEMENT,
                f"The active package's resolution rule cannot be asked about this "
                f"arrangement: {error}",
                semantic_rule_id=rule.id,
            )
            return None
        measure = next(
            (
                value.categorical
                for value in result.values
                if value.name == _MEASURE_OUTPUT and value.categorical is not None
            ),
            None,
        )
        if result.status != "matched" or measure is None:
            derivation.block(
                SupplyDerivationBlockCode.SYSTEM_VOLTAGE_UNRESOLVED,
                f"The active package states no {purpose} system voltage measure for this "
                f"arrangement ({result.status}).",
                semantic_rule_id=rule.id,
            )
            return None
        measures.append(measure)
        source = result.source
    if len(set(measures)) != 1:
        derivation.block(
            SupplyDerivationBlockCode.AMBIGUOUS_ARRANGEMENT,
            f"The {configuration.earthing_arrangement.value} arrangement covers states the "
            f"active package gives different {purpose} system voltage measures for: "
            f"{', '.join(sorted(set(measures)))}.",
            semantic_rule_id=rule.id,
        )
        return None
    measure = measures[0]
    value = configuration.declared_voltage(measure)
    if value is None:
        derivation.block(
            SupplyDerivationBlockCode.MISSING_DECLARED_VOLTAGE,
            f"The {purpose} system voltage of this arrangement is its {measure}, and the "
            f"configuration states no voltage for that measure.",
            semantic_rule_id=rule.id,
        )
        return None
    derivation.steps.append(
        TraceStep(
            semantic_rule_id=rule.id,
            operation="system_voltage_resolution",
            symbolic=f"U_sys({purpose})",
            substituted=f"{measure} = {value} {_VOLTAGE_UNIT}",
            inputs=(),
            source_reference=source,
            output=Quantity(value=value, unit=_VOLTAGE_UNIT),
            unrounded_value=value,
            reason=f"the {purpose} system voltage of this arrangement is its {measure}",
        )
    )
    return measure, value


class LookupOutcome(NamedTuple):
    """One reviewed lookup's answer, or the typed reason it gave none.

    Returned rather than raised so a caller can decide whether an absent value blocks its own
    result or only warns about part of it - the two callers here do different things with the
    same refusal.
    """

    value: Decimal | None
    steps: tuple[TraceStep, ...]
    rule_id: str
    code: SupplyDerivationBlockCode | None = None
    message: str = ""


def _lookup_cell(
    lookup: SupplyLookup,
    system_voltage: Decimal,
    column_label: str,
) -> LookupOutcome:
    """One cell of one reviewed lookup, selected by system voltage and column label.

    The column is found by its declared label and passed to the reviewed formula as that
    column's own axis coordinate, so a table whose columns are ordered differently still
    answers the question that was asked rather than the one that happens to sit in that
    position.
    """

    table = lookup.table
    if column_label not in table.column_axis.labels:
        return LookupOutcome(
            None,
            (),
            lookup.formula.id,
            SupplyDerivationBlockCode.MISSING_LOOKUP_COLUMN,
            f"The active package's {table.id} carries no {column_label} column.",
        )
    column = table.column_axis.values[table.column_axis.labels.index(column_label)]
    try:
        evaluated = evaluate_formula(
            lookup.formula,
            {
                table.row_axis.id: Quantity(value=system_voltage, unit=table.row_axis.unit),
                table.column_axis.id: Quantity(value=column, unit=table.column_axis.unit),
            },
            {table.id: table},
        )
    except EvaluationError as error:
        return LookupOutcome(
            None,
            (),
            lookup.formula.id,
            SupplyDerivationBlockCode.LOOKUP_REFUSED,
            f"The active package refused {table.id} at {system_voltage} {_VOLTAGE_UNIT}: {error}",
        )
    return LookupOutcome(evaluated.value, evaluated.steps, lookup.formula.id)


def select_impulse(
    rules: SupplyRuleSet,
    form: SupplyForm,
    system_voltage: Decimal,
    category: OvervoltageCategory,
) -> LookupOutcome:
    """The rated impulse this package states for one system voltage and one category.

    Public because propagation asks the same question of the same table at a *transferred*
    category, and re-deriving the column identifiers beside it would be a second place for
    them to drift from the ones a scenario is derived through.
    """

    return _lookup_cell(rules.impulse.for_form(form), system_voltage, _IMPULSE_COLUMNS[category])


def _select(
    derivation: _Derivation,
    lookup: SupplyLookup,
    system_voltage: Decimal,
    column_label: str,
) -> Decimal | None:
    """One cell, recorded onto a derivation in progress: steps kept, refusals blocked."""

    outcome = _lookup_cell(lookup, system_voltage, column_label)
    derivation.note_rule(outcome.rule_id)
    if outcome.code is not None:
        derivation.block(outcome.code, outcome.message, semantic_rule_id=outcome.rule_id)
        return None
    derivation.steps.extend(outcome.steps)
    return outcome.value


def _derive_temporary_overvoltage(
    derivation: _Derivation,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """The temporary-overvoltage system voltage and its two measures, any of which may be absent.

    An absent temporary overvoltage is a warning rather than a block: the scenario's impulse is
    what makes it a scenario, and an arrangement the package states no temporary overvoltage
    for is a reviewed answer, not a gap. The reason is always recorded, and the RMS and peak
    values are read as two independent columns because that is how the package states them.
    """

    with derivation.reporting_warnings():
        resolved = _resolve_system_voltage(derivation, TOV_PURPOSE)
        if resolved is None:
            return None, None, None
        _measure, system_voltage = resolved
        lookup = derivation.rules.temporary_overvoltage.for_form(derivation.form)
        rms = _select(derivation, lookup, system_voltage, TOV_RMS_COLUMN)
        peak = _select(derivation, lookup, system_voltage, TOV_PEAK_COLUMN)
    return system_voltage, rms, peak


def _warn_about_the_lowest_category(derivation: _Derivation) -> None:
    """Attach the standing warning a mains supply in the lowest category always carries.

    Limiting the transient alone does not make a supply that category: the temporary
    overvoltage has to be limited too, and nothing in a configuration can show that it is. So
    this is a warning on every derived scenario that selects it, on every recomputation, and
    there is no dismissal to store.

    It does not block. The active package declares no evidence fields for the claim - see the
    adapter's resolved rule set - so there is nothing for a configuration to be incomplete
    *against*, and refusing to derive a scenario the package answers happily would be this
    application inventing a requirement.
    """

    configuration = derivation.configuration
    if (
        not configuration.is_mains
        or configuration.overvoltage_category is not OvervoltageCategory.I
    ):
        return
    derivation.warnings.append(
        CalculationWarning(
            code=OVERVOLTAGE_CATEGORY_I_WARNING,
            message=(
                f"{configuration.name} is a mains supply in overvoltage category "
                f"{OvervoltageCategory.I.value}. Limiting transients alone does not place a "
                "supply in that category: the temporary overvoltage must be limited as well, "
                "and this application cannot show that it is. Record the evidence for both."
            ),
            semantic_rule_id=derivation.rules.system_voltage_resolution.id,
        )
    )


class SupplyStressService:
    """Derives supply stresses from configurations and one resolved set of supply rules.

    Pure and free of any user interface: it reads models and rules and returns typed results.
    The rules arrive already resolved as a :class:`SupplyRuleSet` rather than as a whole
    package, because whether a package can answer these questions at all is the rule adapter's
    decision and is made once, not per configuration.
    """

    def derive_scenario(
        self,
        configuration: SupplyConfiguration,
        rules: SupplyRuleSet,
    ) -> DerivedSupplyScenario | UnresolvedSupplyScenario:
        """One configuration's scenario, or the typed reasons it has none.

        An incomplete row is refused before any rule is asked about it. The refusal is here,
        at the entry point, rather than only in :meth:`derive_all`: a row missing the earthing
        arrangement the resolution rule asks about would otherwise be asked as *unspecified*
        and answered, and the answer would be about an arrangement nobody described. Every
        caller reaches the rules through this method, so guarding it guards all of them, and
        the completeness question itself stays where it already lived - see
        :func:`~insulation_coordination.domain.supply.completeness_problems`, which the
        project-page report calls too, so both refuse the same rows for the same reasons.

        Incompleteness is reported and never raised: what comes back is an
        :class:`~insulation_coordination.domain.supply.UnresolvedSupplyScenario` carrying its
        blocks, exactly as every other refusal here does.

        The impulse result is what a scenario is: without it there is nothing to compare
        against another configuration, so a configuration that cannot produce one comes back
        unresolved. The temporary overvoltage is resolved independently and may legitimately
        be absent from a scenario that is otherwise complete.
        """

        derivation = _Derivation(configuration, rules)
        for problem in completeness_problems(configuration):
            derivation.block(SupplyDerivationBlockCode.CONFIGURATION_INCOMPLETE, problem.message)
        if derivation.blocks:
            return derivation.unresolved()
        resolved = _resolve_system_voltage(derivation, IMPULSE_PURPOSE)
        category = configuration.overvoltage_category
        if category is None:
            derivation.block(
                SupplyDerivationBlockCode.CONFIGURATION_INCOMPLETE,
                "An impulse withstand voltage is selected by overvoltage category, and this "
                "configuration has none.",
            )
        if resolved is None or category is None:
            return derivation.unresolved()
        _measure, impulse_system_voltage = resolved
        outcome = select_impulse(rules, derivation.form, impulse_system_voltage, category)
        derivation.note_rule(outcome.rule_id)
        if outcome.value is None:
            assert outcome.code is not None
            derivation.block(outcome.code, outcome.message, semantic_rule_id=outcome.rule_id)
            return derivation.unresolved()
        impulse = outcome.value
        derivation.steps.extend(outcome.steps)
        _warn_about_the_lowest_category(derivation)
        tov_system_voltage, tov_rms, tov_peak = _derive_temporary_overvoltage(derivation)
        return DerivedSupplyScenario(
            configuration_id=configuration.id,
            configuration_name=configuration.name,
            supply_kind=configuration.supply_kind,
            system_voltage_for_impulse_v=impulse_system_voltage,
            system_voltage_for_tov_v=tov_system_voltage,
            source_ovc=category,
            rated_impulse_v=impulse,
            temporary_overvoltage_rms_v=tov_rms,
            temporary_overvoltage_peak_v=tov_peak,
            warnings=tuple(derivation.warnings),
            trace_steps=tuple(derivation.steps),
            source_rule_ids=tuple(derivation.rule_ids),
        )

    def derive_all(
        self,
        configurations: tuple[SupplyConfiguration, ...],
        rules: SupplyRuleSet,
    ) -> GoverningSupplyStress:
        """Every enabled configuration evaluated, and the worst of each quantity across them.

        Disabled configurations take no part. Every enabled one is evaluated whether or not an
        earlier one failed, so the result reports all of the reasons at once instead of the
        first. Impulse, temporary-overvoltage peak and temporary-overvoltage RMS are selected
        independently and may each be governed by a different configuration.

        The set is validated as a set before any row is derived, because a duplicate name is a
        property of the set that no single row can see. A row's own completeness is refused by
        :meth:`derive_scenario` as well, and reaching it through here cannot change what a row
        is refused for: the same question is asked of the same row either way.
        """

        problems: dict[UUID, list[str]] = {}
        for problem in validate_supply_configurations(configurations):
            problems.setdefault(problem.configuration_id, []).append(problem.message)
        scenarios: list[DerivedSupplyScenario] = []
        unresolved: list[UnresolvedSupplyScenario] = []
        for configuration in configurations:
            if not configuration.enabled:
                continue
            stated = problems.get(configuration.id)
            if stated:
                unresolved.append(
                    UnresolvedSupplyScenario(
                        configuration_id=configuration.id,
                        configuration_name=configuration.name,
                        blocks=tuple(
                            SupplyDerivationBlock(
                                configuration_id=configuration.id,
                                code=SupplyDerivationBlockCode.CONFIGURATION_INCOMPLETE,
                                message=message,
                            )
                            for message in stated
                        ),
                    )
                )
                continue
            result = self.derive_scenario(configuration, rules)
            if isinstance(result, DerivedSupplyScenario):
                scenarios.append(result)
            else:
                unresolved.append(result)
        derived = tuple(scenarios)
        impulse = _govern(derived, lambda item: item.rated_impulse_v, "impulse")
        peak = _govern(
            derived,
            lambda item: item.temporary_overvoltage_peak_v,
            "temporary overvoltage peak",
        )
        rms = _govern(
            derived,
            lambda item: item.temporary_overvoltage_rms_v,
            "temporary overvoltage rms",
        )
        return GoverningSupplyStress(
            impulse_v=impulse.value,
            impulse_configuration_id=impulse.configuration_id,
            tov_peak_v=peak.value,
            tov_configuration_id=peak.configuration_id,
            tov_rms_v=rms.value,
            tov_rms_configuration_id=rms.configuration_id,
            scenarios=derived,
            unresolved=tuple(unresolved),
            trace_steps=tuple(
                step for step in (impulse.step, peak.step, rms.step) if step is not None
            ),
        )


class _Governing(NamedTuple):
    """The winner of one quantity, and the step that says why it won."""

    value: Decimal | None
    configuration_id: UUID | None
    step: TraceStep | None


#: The trace identifier of the project-level comparison. Not a semantic rule id: choosing the
#: worst of several derived scenarios is this application's arithmetic, not a reading of any
#: clause, and labelling it with a package identifier would credit the package with a decision
#: it did not make.
GOVERNING_TRACE_ID: Final = "supply.governing_scenario"


def _govern(
    scenarios: Sequence[DerivedSupplyScenario],
    quantity: Callable[[DerivedSupplyScenario], Decimal | None],
    label: str,
) -> _Governing:
    """The largest value of ``quantity`` across ``scenarios``, and the step that explains it.

    Ties are broken by the lowest configuration identifier, which is stable across runs and
    independent of the order a project happens to list its rows in, and every tied scenario is
    named in the step so a reader can see the choice was between equals.
    """

    candidates = tuple(
        (scenario, value) for scenario in scenarios if (value := quantity(scenario)) is not None
    )
    if not candidates:
        return _Governing(None, None, None)
    highest = max(value for _scenario, value in candidates)
    tied = sorted(
        (scenario for scenario, value in candidates if value == highest),
        key=lambda scenario: scenario.configuration_id,
    )
    winner = tied[0]
    reason = f"{winner.configuration_name} governs the {label}"
    if len(tied) > 1:
        names = ", ".join(scenario.configuration_name for scenario in tied[1:])
        reason += f"; it is tied with {names}, and the lowest configuration identifier is selected"
    step = TraceStep(
        semantic_rule_id=GOVERNING_TRACE_ID,
        operation="max",
        symbolic=rf"\max({label})",
        substituted=", ".join(
            f"{scenario.configuration_name} = {value} {_VOLTAGE_UNIT}"
            for scenario, value in candidates
        ),
        inputs=tuple(Quantity(value=value, unit=_VOLTAGE_UNIT) for _scenario, value in candidates),
        source_reference=None,
        output=Quantity(value=highest, unit=_VOLTAGE_UNIT),
        unrounded_value=highest,
        reason=reason,
    )
    return _Governing(highest, winner.configuration_id, step)


__all__ = [
    "GOVERNING_TRACE_ID",
    "IMPULSE_PURPOSE",
    "OVERVOLTAGE_CATEGORY_I_WARNING",
    "TOV_PEAK_COLUMN",
    "TOV_PURPOSE",
    "TOV_RMS_COLUMN",
    "LookupOutcome",
    "SupplyStressService",
    "select_impulse",
    "supply_form",
]
