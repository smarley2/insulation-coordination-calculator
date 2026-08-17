"""What the clearance engine does with a derived supply stress, and what it does without one.

Two packages meet here for the first time: the Part 1 clearance rules the engine has always
read and the supply rules issue #36 added. Every value in both is invented for the test suite,
and the merged fixture below is a field-wise union of the two - no content is added, only the
one shape a whole-package validation needs that a supply-only fixture never had to carry.

What is asserted is behaviour at the seam. A project that declares no supply arrangement is
dimensioned from exactly the numbers it was entered with, byte for byte. A project that does
declare one is dimensioned from the derived stress instead, that stress reaches the engine
untreated, the insulation treatment is applied once by the engine and reported once beside it,
and the altitude correction happens where it always did - after the governing candidate is
chosen, and to a distance rather than to a voltage.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.clearance import (
    _PREFERRED_IMPULSE_V,
    apply_reinforced_stress_treatment,
)
from insulation_coordination.calculation.engine import (
    SUPERSEDED_ENTRY_WARNING,
    calculate_pair,
    calculate_project_pair,
    derive_project_supply,
    resolve_supply_effective_case,
)
from insulation_coordination.calculation.stress_propagation import TemporaryOvervoltageSource
from insulation_coordination.calculation.supply_rules import SupplyRulesUnavailable
from insulation_coordination.domain.enums import (
    CircuitSourceRelationship,
    ConstructionType,
    FieldCondition,
    InsulationType,
    Provenance,
)
from insulation_coordination.domain.project import (
    PairCase,
    PairVoltage,
    PairVoltages,
    Project,
    ProjectDefaults,
)
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.supply import (
    DeclaredSystemVoltage,
    EarthingArrangement,
    ImpulseOverrideBasis,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    ReductionVerificationMethod,
    SupplyConfiguration,
    SupplyKind,
    VerifiedImpulseOverride,
)
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from tests.fixtures.supply_topologies import (
    COVER,
    ENCLOSURE,
    VERIFIED,
    circuit_id,
    pair_between,
    supply_topology,
)
from tests.fixtures.synthetic_rules import synthetic_supply_rule_package

#: The top of the supply fixture's synthetic band axis, which runs 11 V to 33 V in three
#: bands. The highest band is chosen so the derived stresses land inside the clearance
#: fixture's own supported ranges - both sets of numbers are invented, and they only have to
#: overlap for one package to answer both questions.
IN_BAND = Decimal(33)

#: The pair's own entered temporary overvoltage. Below what the fixture derives, so a
#: circuit-to-surroundings pair is a case of the derivation governing rather than a tie.
ENTERED_TOV_PEAK_V = Decimal(250)


def _merged(
    clearance_rules: RulePackage,
    tmp_path: Path,
    *,
    name: str = "merged",
    supply: RulePackage | None = None,
) -> RulePackage:
    """One package answering both the clearance questions and the supply ones.

    A real installation carries them together; the two fixtures are separate only because the
    slices that built them were. Written and reloaded so the archive recomputes the checksums
    the engine's whole-package gate compares against.
    """
    supply = supply if supply is not None else synthetic_supply_rule_package()
    documents = {
        document.id: document
        for document in (
            *clearance_rules.manifest.source_documents,
            *supply.manifest.source_documents,
        )
    }
    candidate = clearance_rules.model_copy(
        update={
            "manifest": clearance_rules.manifest.model_copy(
                update={"source_documents": tuple(documents.values())}
            ),
            "tables": (*clearance_rules.tables, *supply.tables),
            "formulas": (*clearance_rules.formulas, *supply.formulas),
            "decisions": (*clearance_rules.decisions, *supply.decisions),
            "checksums": {},
            "package_sha256": None,
        }
    )
    path = tmp_path / f"{name}.icrules"
    write_rule_package(path, candidate)
    return load_rule_package(path)


@pytest.fixture
def supply_and_clearance_rules(semantic_annex_g_rules: RulePackage, tmp_path: Path) -> RulePackage:
    return _merged(semantic_annex_g_rules, tmp_path)


def _configuration(**overrides: object) -> SupplyConfiguration:
    fields: dict[str, object] = {
        "id": UUID(int=1),
        "enabled": True,
        "name": "Synthetic mains",
        "supply_kind": SupplyKind.AC_MAINS,
        "nominal_voltage_v": IN_BAND,
        "phase_system": PhaseSystem.THREE_PHASE,
        "earthing_arrangement": EarthingArrangement.TN_STAR_POINT_EARTHED,
        "overvoltage_category": OvervoltageCategory.IV,
        "input_topology": InputTopology.DIRECT_INPUT,
        "declared_system_voltages": (
            DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=IN_BAND),
        ),
    }
    fields.update(overrides)
    return SupplyConfiguration(**fields)


def _project(
    *configurations: SupplyConfiguration,
    insulation: InsulationType = InsulationType.BASIC,
    altitude_m: Decimal = Decimal(0),
    entered_impulse_v: Decimal | None = None,
    entered_tov_peak_v: Decimal = ENTERED_TOV_PEAK_V,
) -> Project:
    """A two-domain topology with dimensionable stresses on every pair.

    The manual stresses are the same whether or not a configuration is enabled, which is what
    lets one project answer both halves of the comparison.
    """
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))
    defaults = ProjectDefaults(
        frequency_hz=Decimal(50),
        impulse_v=entered_impulse_v,
        insulation_type=insulation,
        field_condition=FieldCondition.INHOMOGENEOUS,
        altitude_m=altitude_m,
        pollution_degree=2,
        construction_type=ConstructionType.PRINTED_WIRING,
        cti_or_material_group="I",
    )
    return project.model_copy(
        update={
            "defaults": defaults,
            "supply_configurations": configurations,
            "pairs": tuple(_dimensionable(pair, entered_tov_peak_v) for pair in project.pairs),
        }
    )


def _dimensionable(pair: PairCase, tov_peak_v: Decimal = ENTERED_TOV_PEAK_V) -> PairCase:
    """Give every stress a value, so nothing is blank and nothing is excluded."""
    return pair.model_copy(
        update={
            "voltages": PairVoltages(
                long_term_rms_v=PairVoltage.applicable(Decimal(500)),
                steady_state_peak_v=PairVoltage.applicable(Decimal(300)),
                recurring_peak_v=PairVoltage.applicable(Decimal(400)),
                temporary_overvoltage_peak_v=PairVoltage.applicable(tov_peak_v),
            )
        }
    )


def _circuit_to_surroundings(project: Project) -> PairCase:
    return pair_between(project, circuit_id(0), ENCLOSURE)


def _circuit_to_circuit(project: Project) -> PairCase:
    return pair_between(project, circuit_id(0), circuit_id(1))


# --- an existing project is untouched -----------------------------------------------------


def test_a_project_declaring_no_supply_arrangement_derives_nothing(
    supply_and_clearance_rules: RulePackage,
) -> None:
    project = _project(entered_impulse_v=Decimal(600))

    assert derive_project_supply(project, supply_and_clearance_rules) is None


def test_a_project_with_no_enabled_arrangement_is_dimensioned_exactly_as_before(
    supply_and_clearance_rules: RulePackage,
) -> None:
    """The whole guarantee for existing projects, asserted on the result rather than the flow.

    A disabled row is persisted and takes no part, so this is also the state a user reaches by
    switching every configuration off: the manual entries come straight back, with no derived
    value copied into them on the way.
    """
    project = _project(_configuration(enabled=False), entered_impulse_v=Decimal(600))
    pair = _circuit_to_surroundings(project)

    supply = derive_project_supply(project, supply_and_clearance_rules)
    through_the_new_path = calculate_project_pair(
        project, pair, supply_and_clearance_rules, supply=supply
    )
    as_before = calculate_pair(
        resolve_effective_case(project.defaults, pair), supply_and_clearance_rules
    )

    assert supply is None
    assert through_the_new_path == as_before
    assert through_the_new_path.effective_inputs.impulse_v.value == Decimal(600)
    assert through_the_new_path.effective_inputs.impulse_v.provenance is Provenance.PROJECT_DEFAULT


def test_a_project_without_arrangements_needs_no_supply_rules_at_all(
    semantic_annex_g_rules: RulePackage,
) -> None:
    """A package carrying no supply content cannot block a project that asks it nothing."""
    project = _project(entered_impulse_v=Decimal(600))
    pair = _circuit_to_surroundings(project)

    with pytest.raises(SupplyRulesUnavailable):
        derive_project_supply(
            project.model_copy(update={"supply_configurations": (_configuration(),)}),
            semantic_annex_g_rules,
        )

    assert derive_project_supply(project, semantic_annex_g_rules) is None
    assert calculate_project_pair(project, pair, semantic_annex_g_rules).clearance_mm > 0


# --- a derived stress reaches the engine --------------------------------------------------


def test_the_derived_impulse_becomes_the_pair_input_and_says_where_it_came_from(
    supply_and_clearance_rules: RulePackage,
) -> None:
    project = _project(_configuration())
    pair = _circuit_to_surroundings(project)
    supply = derive_project_supply(project, supply_and_clearance_rules)
    assert supply is not None

    effective, resolution = resolve_supply_effective_case(project, pair, supply)

    assert resolution is not None
    assert effective.impulse_v.value == supply.governing.impulse_v
    assert effective.impulse_v.provenance is Provenance.DERIVED_SUPPLY
    assert resolution.verified_effective_impulse_v == supply.governing.impulse_v


def test_a_derived_impulse_replacing_an_entered_one_says_so(
    supply_and_clearance_rules: RulePackage,
) -> None:
    project = _project(_configuration(), entered_impulse_v=Decimal(600))
    pair = _circuit_to_surroundings(project)
    supply = derive_project_supply(project, supply_and_clearance_rules)

    result = calculate_project_pair(project, pair, supply_and_clearance_rules, supply=supply)

    superseded = [
        warning
        for warning in result.warnings
        if warning.code == SUPERSEDED_ENTRY_WARNING and "impulse" in warning.message
    ]
    assert len(superseded) == 1
    assert "600" in superseded[0].message
    assert result.warnings == result.trace.warnings


def test_a_derived_impulse_equal_to_the_entered_one_is_not_reported_as_replacing_it(
    supply_and_clearance_rules: RulePackage,
) -> None:
    project = _project(_configuration())
    supply = derive_project_supply(project, supply_and_clearance_rules)
    assert supply is not None
    assert supply.governing.impulse_v is not None
    assert supply.governing.tov_peak_v is not None
    agreeing = _project(
        _configuration(),
        entered_impulse_v=supply.governing.impulse_v,
        entered_tov_peak_v=supply.governing.tov_peak_v,
    )

    result = calculate_project_pair(
        agreeing, _circuit_to_surroundings(agreeing), supply_and_clearance_rules, supply=supply
    )

    superseded = [
        warning.message for warning in result.warnings if warning.code == SUPERSEDED_ENTRY_WARNING
    ]
    assert superseded == []


def test_a_mains_temporary_overvoltage_reaches_circuit_to_surroundings_and_not_two_circuits(
    supply_and_clearance_rules: RulePackage,
) -> None:
    project = _project(_configuration())
    supply = derive_project_supply(project, supply_and_clearance_rules)
    assert supply is not None

    surroundings, _ = resolve_supply_effective_case(
        project, _circuit_to_surroundings(project), supply
    )
    between_circuits, resolution = resolve_supply_effective_case(
        project, _circuit_to_circuit(project), supply
    )

    derived_peak = supply.governing.tov_peak_v
    assert derived_peak is not None
    assert surroundings.voltages.temporary_overvoltage_peak_v.value == derived_peak
    assert derived_peak > ENTERED_TOV_PEAK_V
    # The pair's own entry stands between two circuits, and nothing copies the project figure.
    assert between_circuits.voltages.temporary_overvoltage_peak_v.value == ENTERED_TOV_PEAK_V
    assert resolution is not None
    assert resolution.temporary_overvoltage.source is not TemporaryOvervoltageSource.DERIVED_MAINS


def test_the_supply_trace_leads_the_pair_trace_and_carries_no_pair_identity(
    supply_and_clearance_rules: RulePackage,
) -> None:
    """Grouping hashes every result value but the pair's identity, so none may hide in a step."""
    project = _project(_configuration())
    pair = _circuit_to_surroundings(project)
    supply = derive_project_supply(project, supply_and_clearance_rules)

    result = calculate_project_pair(project, pair, supply_and_clearance_rules, supply=supply)

    supply_steps = [
        step for step in result.trace.steps if step.semantic_rule_id.startswith("supply.")
    ]
    assert supply_steps
    assert result.trace.steps[: len(supply_steps)] == tuple(supply_steps)
    rendered = " ".join(f"{step.substituted} {step.reason}" for step in result.trace.steps)
    assert str(pair.id) not in rendered
    assert pair.key not in rendered


# --- reinforced treatment, exactly once ---------------------------------------------------


def test_the_engine_treats_a_derived_impulse_once_and_the_resolution_reports_that_same_value(
    supply_and_clearance_rules: RulePackage,
) -> None:
    project = _project(_configuration(), insulation=InsulationType.REINFORCED)
    pair = _circuit_to_surroundings(project)
    supply = derive_project_supply(project, supply_and_clearance_rules)
    assert supply is not None
    derived = supply.governing.impulse_v
    assert derived is not None

    _effective, resolution = resolve_supply_effective_case(project, pair, supply)
    result = calculate_project_pair(project, pair, supply_and_clearance_rules, supply=supply)

    once, _step = apply_reinforced_stress_treatment(
        derived, kind=InsulationType.REINFORCED, treatment="impulse"
    )
    twice, _again = apply_reinforced_stress_treatment(
        once, kind=InsulationType.REINFORCED, treatment="impulse"
    )
    candidate = next(
        item for item in result.trace.clearance_candidates if item.candidate_id == "impulse"
    )
    assert candidate.stress.value == derived, "the engine is handed the untreated stress"
    assert candidate.treated_stress is not None
    assert candidate.treated_stress.value == once
    assert candidate.treated_stress.value != twice
    assert resolution is not None
    assert resolution.insulation_treated_impulse_v == candidate.treated_stress.value
    treatments = [
        step for step in candidate.steps if step.operation == "reinforced_stress_treatment"
    ]
    assert len(treatments) == 1


def test_the_derived_temporary_overvoltage_and_the_recurring_peak_are_treated_once_each(
    supply_and_clearance_rules: RulePackage,
) -> None:
    """The periodic candidates, which take the other treatment branch.

    The temporary overvoltage one is the case that matters here: its stress is derived rather
    than entered, so a substitution that handed the engine an already-treated figure would
    show up as a second application on exactly this candidate.
    """
    project = _project(_configuration(), insulation=InsulationType.REINFORCED)
    pair = _circuit_to_surroundings(project)
    supply = derive_project_supply(project, supply_and_clearance_rules)
    assert supply is not None
    derived_peak = supply.governing.tov_peak_v
    assert derived_peak is not None

    result = calculate_project_pair(project, pair, supply_and_clearance_rules, supply=supply)

    candidates = {item.candidate_id: item for item in result.trace.clearance_candidates}
    for candidate_id, stress in (
        ("temporary_overvoltage_peak", derived_peak),
        ("recurring_peak", Decimal(400)),
    ):
        candidate = candidates[candidate_id]
        once, _step = apply_reinforced_stress_treatment(
            stress, kind=InsulationType.REINFORCED, treatment="periodic"
        )
        assert candidate.stress.value == stress
        assert candidate.treated_stress is not None
        assert candidate.treated_stress.value == once
        treatments = [
            step for step in candidate.steps if step.operation == "reinforced_stress_treatment"
        ]
        assert len(treatments) == 1


def test_a_basic_pair_treats_the_derived_impulse_not_at_all(
    supply_and_clearance_rules: RulePackage,
) -> None:
    project = _project(_configuration(), insulation=InsulationType.BASIC)
    pair = _circuit_to_surroundings(project)
    supply = derive_project_supply(project, supply_and_clearance_rules)
    assert supply is not None

    _effective, resolution = resolve_supply_effective_case(project, pair, supply)
    result = calculate_project_pair(project, pair, supply_and_clearance_rules, supply=supply)

    candidate = next(
        item for item in result.trace.clearance_candidates if item.candidate_id == "impulse"
    )
    assert resolution is not None
    assert resolution.insulation_treated_impulse_v == supply.governing.impulse_v
    assert candidate.treated_stress == candidate.stress


def test_a_derived_impulse_at_a_preferred_level_steps_up_exactly_one_level(
    semantic_annex_g_rules: RulePackage, tmp_path: Path
) -> None:
    """The other reinforced branch: a step along the preferred levels, taken once.

    The impulse cells are shifted so the lookup lands on the first preferred level rather than
    near it. Only the fixture's own invented cell values move; the level itself is read from
    the engine's declared sequence rather than written out here.
    """
    lowest, next_level = _PREFERRED_IMPULSE_V[0], _PREFERRED_IMPULSE_V[1]
    rules = _merged(
        semantic_annex_g_rules,
        tmp_path,
        name="preferred",
        supply=_supply_with_impulse_cells(lowest),
    )
    project = _project(_configuration(), insulation=InsulationType.REINFORCED)
    pair = _circuit_to_surroundings(project)
    supply = derive_project_supply(project, rules)
    assert supply is not None
    assert supply.governing.impulse_v == lowest

    result = calculate_project_pair(project, pair, rules, supply=supply)

    candidate = next(
        item for item in result.trace.clearance_candidates if item.candidate_id == "impulse"
    )
    assert candidate.stress.value == lowest
    assert candidate.treated_stress is not None
    assert candidate.treated_stress.value == next_level


def _supply_with_impulse_cells(value: Decimal) -> RulePackage:
    """The supply fixture with every impulse cell set to ``value``.

    Only the fixture's own invented cell values move, and they move to a level the engine
    already declares - so the test names no number of its own.
    """
    package = synthetic_supply_rule_package()
    tables = tuple(
        table.model_copy(
            update={
                "cells": tuple(cell.model_copy(update={"value": value}) for cell in table.cells)
            }
        )
        if table.id.startswith(ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC)
        else table
        for table in package.tables
    )
    return package.model_copy(update={"tables": tables})


# --- altitude stays where it was ----------------------------------------------------------


def test_altitude_corrects_the_distance_and_never_the_derived_source_stress(
    supply_and_clearance_rules: RulePackage,
) -> None:
    """Altitude is a clearance correction applied after the governing candidate is chosen.

    Two projects differing only in altitude derive the same supply stresses and hand the
    engine the same impulse; only the distance that comes out differs, and only after the
    maximum has been taken.
    """
    at_base = _project(_configuration(), altitude_m=Decimal(0))
    up_high = _project(_configuration(), altitude_m=Decimal(4400))
    pair = _circuit_to_surroundings(at_base)

    low = derive_project_supply(at_base, supply_and_clearance_rules)
    high = derive_project_supply(up_high, supply_and_clearance_rules)
    low_result = calculate_project_pair(at_base, pair, supply_and_clearance_rules, supply=low)
    high_result = calculate_project_pair(up_high, pair, supply_and_clearance_rules, supply=high)

    assert low is not None and high is not None
    assert low.governing.impulse_v == high.governing.impulse_v
    assert low_result.effective_inputs.impulse_v == high_result.effective_inputs.impulse_v
    assert high_result.trace.altitude_correction_applied
    assert high_result.trace.pre_altitude_clearance_mm == low_result.clearance_mm
    assert high_result.clearance_mm > high_result.trace.pre_altitude_clearance_mm


# --- a verified override at the pair ------------------------------------------------------


def test_a_verified_override_recorded_on_the_pair_is_what_the_engine_dimensions_from(
    supply_and_clearance_rules: RulePackage,
) -> None:
    project = _project(_configuration())
    pair = _circuit_to_surroundings(project)
    raised = pair.model_copy(
        update={
            "impulse_override": VerifiedImpulseOverride(
                value_v=Decimal(900),
                basis=ImpulseOverrideBasis.CONSERVATIVE_INCREASE,
                verification_method=ReductionVerificationMethod.CALCULATION,
                justification="Margin held for a later variant",
                evidence_reference="",
                affected_location="Primary circuit to enclosure",
            )
        }
    )
    with_override = project.model_copy(
        update={"pairs": tuple(raised if item.id == pair.id else item for item in project.pairs)}
    )
    supply = derive_project_supply(with_override, supply_and_clearance_rules)

    effective, resolution = resolve_supply_effective_case(with_override, raised, supply)

    assert resolution is not None
    assert resolution.override_outcome is not None
    assert resolution.override_outcome.applied
    assert resolution.verified_effective_impulse_v == Decimal(900)
    assert effective.impulse_v.value == Decimal(900)
    assert effective.impulse_v.provenance is Provenance.DERIVED_SUPPLY


# --- a supply nothing declares as its source ----------------------------------------------


def test_a_pair_no_supply_reaches_keeps_its_entered_impulse(
    supply_and_clearance_rules: RulePackage,
) -> None:
    """An enabled arrangement that reaches no domain leaves every pair's manual entry alone."""
    project = supply_topology(
        ("Primary", "Secondary"),
        ((0, 1, VERIFIED),),
        sources={0: CircuitSourceRelationship.INTERNALLY_GENERATED},
    )
    project = project.model_copy(
        update={
            "defaults": ProjectDefaults(
                frequency_hz=Decimal(50),
                impulse_v=Decimal(600),
                insulation_type=InsulationType.BASIC,
                field_condition=FieldCondition.INHOMOGENEOUS,
                altitude_m=Decimal(0),
                pollution_degree=2,
                construction_type=ConstructionType.PRINTED_WIRING,
                cti_or_material_group="I",
            ),
            "supply_configurations": (_configuration(),),
            "pairs": tuple(_dimensionable(item) for item in project.pairs),
        }
    )
    pair = pair_between(project, circuit_id(0), COVER)
    supply = derive_project_supply(project, supply_and_clearance_rules)

    effective, resolution = resolve_supply_effective_case(project, pair, supply)

    assert resolution is not None
    assert resolution.verified_effective_impulse_v is None
    assert effective.impulse_v.value == Decimal(600)
    assert effective.impulse_v.provenance is Provenance.PROJECT_DEFAULT


def test_the_supply_rules_are_read_once_for_the_whole_project(
    supply_and_clearance_rules: RulePackage,
) -> None:
    """Every pair reads one derivation, so a project cannot disagree with itself about it."""
    project = _project(_configuration())
    supply = derive_project_supply(project, supply_and_clearance_rules)
    assert supply is not None

    resolutions = [
        resolve_supply_effective_case(project, pair, supply)[1] for pair in project.pairs
    ]

    impulses = {
        resolution.source_scenario_impulse_v
        for resolution in resolutions
        if resolution is not None and resolution.source_scenario_impulse_v is not None
    }
    assert impulses == {supply.governing.impulse_v}


def test_the_same_project_derives_the_same_result_twice(
    supply_and_clearance_rules: RulePackage,
) -> None:
    """The report rebuilds every result and refuses one that differs from what it was given.

    A derivation that varied between two runs of the same project - on iteration order, on a
    generated identifier, on anything - would block every report of a project using this
    feature, so the property is asserted rather than assumed.
    """
    project = _project(_configuration())
    pair = _circuit_to_surroundings(project)

    first = calculate_project_pair(
        project,
        pair,
        supply_and_clearance_rules,
        supply=derive_project_supply(project, supply_and_clearance_rules),
    )
    second = calculate_project_pair(
        project,
        pair,
        supply_and_clearance_rules,
        supply=derive_project_supply(project, supply_and_clearance_rules),
    )

    assert first == second
