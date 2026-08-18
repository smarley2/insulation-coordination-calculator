"""What a report discloses about the supply stresses a project was dimensioned from.

The question every assertion here asks is whether a reviewer holding only the document can
reconstruct the number: which arrangement governed, which system voltage it resolved and how,
which route the stress travelled and across which barriers, whether an override applied and on
what evidence, whether the reinforced treatment applied, and that altitude touched none of it.

Every value is synthetic. The supply fixture's bands run 11 V to 33 V and the Part 1 fixture's
distances are invented for this suite; the two only have to overlap for one package to answer
both questions. No document is compiled and none is written to the tree - the assertions read
the report model and the rendered LaTeX source.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import (
    ENTRY_EXCEEDS_DERIVED_WARNING,
    SUPERSEDED_ENTRY_WARNING,
    calculate_project_pair,
    derive_project_supply,
)
from insulation_coordination.calculation.grouping import group_results
from insulation_coordination.calculation.impulse_override import SPD_REDUCTION_WARNING
from insulation_coordination.calculation.stress_propagation import (
    UNRESOLVED_TOPOLOGY_WARNING,
    DomainStressState,
)
from insulation_coordination.calculation.supply_stress import OVERVOLTAGE_CATEGORY_I_WARNING
from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
    PairCase,
    PairVoltage,
    PairVoltages,
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
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
    SpdDevicePlacement,
    SupplyConfiguration,
    SupplyKind,
    VerifiedImpulseOverride,
)
from insulation_coordination.report.human_view import (
    ALTITUDE_STATEMENT,
    HumanReportView,
    build_human_report_view,
)
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import ReportModel, build_report_model
from tests.fixtures.supply_topologies import (
    COVER,
    ENCLOSURE,
    NO_ISOLATION,
    UNEVALUATED,
    VERIFIED,
    circuit_id,
    pair_between,
    supply_topology,
)
from tests.fixtures.synthetic_rules import (
    merged_rule_package,
    synthetic_part1_rule_package,
    synthetic_supply_rule_package,
)

#: The top band of the supply fixture's synthetic system-voltage axis.
IN_BAND = Decimal(33)

#: A middle band, so a second arrangement derives a lower stress than the first.
LOWER_BAND = Decimal(22)

#: Past the top of every band, so an arrangement declaring it is enabled and underivable.
OUT_OF_BAND = Decimal(999)

#: The project default impulse. Below what the fixture derives, so a derived stress governs
#: wherever one reaches, and the pairs no stress reaches are still dimensionable.
DEFAULT_IMPULSE_V = Decimal(150)


@pytest.fixture
def supply_rules(tmp_path: Path) -> RulePackage:
    return merged_rule_package(
        synthetic_part1_rule_package(),
        synthetic_supply_rule_package(),
        path=tmp_path / "merged.icrules",
    )


def _configuration(**overrides: object) -> SupplyConfiguration:
    band = overrides.pop("band", IN_BAND)
    fields: dict[str, object] = {
        "id": UUID(int=1),
        "enabled": True,
        "name": "Primary mains",
        "supply_kind": SupplyKind.AC_MAINS,
        "nominal_voltage_v": band,
        "phase_system": PhaseSystem.THREE_PHASE,
        "earthing_arrangement": EarthingArrangement.TN_STAR_POINT_EARTHED,
        "overvoltage_category": OvervoltageCategory.IV,
        "input_topology": InputTopology.DIRECT_INPUT,
        "declared_system_voltages": (
            DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=band),
        ),
    }
    fields.update(overrides)
    return SupplyConfiguration(**fields)


def _project(
    rules: RulePackage,
    *configurations: SupplyConfiguration,
    barrier_status: object = VERIFIED,
    insulation: InsulationType = InsulationType.BASIC,
) -> Project:
    """Two domains across one barrier, every pair dimensionable, one arrangement or several."""
    project = supply_topology(("Primary", "Secondary"), ((0, 1, barrier_status),))
    assert rules.package_sha256 is not None
    return project.model_copy(
        update={
            "metadata": ProjectMetadata(
                title="Synthetic supply report",
                customer="Synthetic customer",
                document_number="SYN-036",
                revision="A",
                author="Author",
                checker="Checker",
                approver="Approver",
            ),
            "application_version": "0.1.0",
            "required_rules": RulePackageReference(
                package_id=str(rules.manifest.package_id),
                version=rules.manifest.version,
                sha256=rules.package_sha256,
            ),
            "defaults": ProjectDefaults(
                frequency_hz=Decimal(50),
                impulse_v=DEFAULT_IMPULSE_V,
                insulation_type=insulation,
                field_condition=FieldCondition.INHOMOGENEOUS,
                altitude_m=Decimal(0),
                pollution_degree=2,
                construction_type=ConstructionType.OTHER,
                cti_or_material_group="I",
            ),
            "supply_configurations": configurations,
            "pairs": tuple(_dimensionable(pair) for pair in project.pairs),
        }
    )


def _dimensionable(pair: PairCase) -> PairCase:
    """Give every stress a value, so no pair is excluded from the analysis."""
    return pair.model_copy(
        update={
            "voltages": PairVoltages(
                long_term_rms_v=PairVoltage.applicable(Decimal(150)),
                steady_state_peak_v=PairVoltage.applicable(Decimal(150)),
                recurring_peak_v=PairVoltage.applicable(Decimal(150)),
                temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(200)),
            )
        }
    )


def _with_pair(project: Project, pair_id: UUID, **updates: object) -> Project:
    return project.model_copy(
        update={
            "pairs": tuple(
                pair.model_copy(update=updates) if pair.id == pair_id else pair
                for pair in project.pairs
            )
        }
    )


def _report(project: Project, rules: RulePackage) -> ReportModel:
    supply = derive_project_supply(project, rules)
    results = tuple(
        calculate_project_pair(project, pair, rules, supply=supply) for pair in project.pairs
    )
    return build_report_model(project, results, group_results(results, ()), rules)


def _human(project: Project, rules: RulePackage) -> HumanReportView:
    return build_human_report_view(_report(project, rules))


def _stage(view: HumanReportView, pair_label: str, stage: str) -> str:
    """One stage of one pair's derivation, found by the label the report prints."""
    return next(
        item.value
        for group in view.groups
        for block in group.supply
        if pair_label in block.pair_labels
        for item in block.stages
        if item.name == stage
    )


def _evidence(view: HumanReportView, pair_label: str) -> dict[str, str]:
    return {
        item.name: item.value
        for group in view.groups
        for block in group.supply
        if pair_label in block.pair_labels
        for item in block.evidence
    }


_TO_ENCLOSURE = "Circuit Primary ↔ Enclosure"
_ACROSS_THE_BARRIER = "Circuit Primary ↔ Circuit Secondary"


def test_every_declared_arrangement_is_reported_whether_or_not_it_was_evaluated(
    supply_rules: RulePackage,
) -> None:
    """A disabled arrangement is a recorded decision, so it is disclosed as one."""
    project = _project(
        supply_rules,
        _configuration(),
        _configuration(id=UUID(int=2), name="Spare mains", enabled=False, band=LOWER_BAND),
    )

    view = _human(project, supply_rules)

    assert view.supply is not None
    assert [
        (configuration.name, configuration.status) for configuration in view.supply.configurations
    ] == [("Primary mains", "enabled"), ("Spare mains", "not enabled")]
    assert [scenario.name for scenario in view.supply.scenarios] == ["Primary mains"]
    assert "Spare mains" in render_latex(_report(project, supply_rules))


def test_each_scenario_reports_the_system_voltages_it_resolved_and_the_stresses_they_gave(
    supply_rules: RulePackage,
) -> None:
    """The two system voltages are resolved independently, so both are reported."""
    project = _project(supply_rules, _configuration())
    model = _report(project, supply_rules)

    scenario = model.supply.governing.scenarios[0] if model.supply else None
    view = build_human_report_view(model)

    assert scenario is not None
    assert scenario.system_voltage_for_impulse_v == IN_BAND
    assert scenario.system_voltage_for_tov_v == IN_BAND
    reported = view.supply.scenarios[0] if view.supply else None
    assert reported is not None
    assert reported.system_voltage_impulse == f"{IN_BAND} V"
    assert reported.system_voltage_tov == f"{IN_BAND} V"
    assert reported.rated_impulse == f"{scenario.rated_impulse_v} V"
    assert reported.temporary_overvoltage_rms == f"{scenario.temporary_overvoltage_rms_v} V"
    assert reported.temporary_overvoltage_peak == f"{scenario.temporary_overvoltage_peak_v} V"
    assert view.supply is not None
    assert view.supply.scenario_rules[0].value.startswith("iec62477_2022.supply.")


def test_the_governing_stresses_are_each_reported_with_the_arrangement_behind_it(
    supply_rules: RulePackage,
) -> None:
    """Three selections, made independently, so each names its own owner."""
    project = _project(
        supply_rules,
        _configuration(),
        _configuration(id=UUID(int=2), name="Auxiliary mains", band=LOWER_BAND),
    )
    model = _report(project, supply_rules)
    view = build_human_report_view(model)

    assert model.supply is not None
    assert view.supply is not None
    assert [item.name for item in view.supply.governing] == [
        "Governing impulse withstand voltage",
        "Governing temporary overvoltage (peak)",
        "Governing temporary overvoltage (RMS)",
    ]
    assert all("Primary mains" in item.value for item in view.supply.governing)
    # The arrangement that did not govern is still reported, or a reader cannot see what the
    # governing value was worse than.
    assert [scenario.name for scenario in view.supply.scenarios] == [
        "Primary mains",
        "Auxiliary mains",
    ]
    assert view.supply.scenarios[1].governs == "—"


def test_the_domain_graph_reports_each_domains_stress_and_the_route_a_transfer_took(
    supply_rules: RulePackage,
) -> None:
    project = _project(supply_rules, _configuration())

    view = _human(project, supply_rules)

    assert view.supply is not None
    primary, secondary = view.supply.domains
    assert primary.name == "Primary"
    assert primary.state == "supplied"
    assert primary.route == "no barrier crossed"
    assert secondary.state == "transferred"
    assert "Primary to Secondary across Primary ↔ Secondary" in secondary.route
    assert "overvoltage category" in secondary.route
    assert secondary.transferred_impulse == secondary.governing_impulse


def test_domains_no_barrier_isolates_share_one_electrical_set_in_the_report(
    supply_rules: RulePackage,
) -> None:
    project = _project(supply_rules, _configuration(), barrier_status=NO_ISOLATION)

    view = _human(project, supply_rules)

    assert view.supply is not None
    assert [domain.electrical_set for domain in view.supply.domains] == [
        "Primary, Secondary",
        "Primary, Secondary",
    ]


def test_the_report_states_that_altitude_left_the_source_voltages_alone(
    supply_rules: RulePackage,
) -> None:
    """Verified against the derivation's own trace, not asserted by the template."""
    project = _project(supply_rules, _configuration())
    model = _report(project, supply_rules)

    assert model.supply is not None
    assert model.supply.altitude_altered_source_voltages is False
    view = build_human_report_view(model)
    assert view.supply is not None
    assert view.supply.altitude_statement == ALTITUDE_STATEMENT
    assert "Altitude did not alter any source voltage" in render_latex(model)


def test_a_pair_reports_every_stage_between_the_supply_and_its_clearance_input(
    supply_rules: RulePackage,
) -> None:
    """The whole trace a reviewer reconstructs the number from, for one pair."""
    project = _project(supply_rules, _configuration(), insulation=InsulationType.REINFORCED)
    model = _report(project, supply_rules)
    view = build_human_report_view(model)
    assert model.supply is not None
    derived = model.supply.governing.impulse_v
    assert derived is not None

    assert _stage(view, _TO_ENCLOSURE, "Pair relationship") == "circuit to surroundings"
    assert _stage(view, _TO_ENCLOSURE, "Topology state") == "supplied"
    assert _stage(view, _TO_ENCLOSURE, "Source scenarios") == f"Primary mains: {derived} V"
    assert _stage(view, _TO_ENCLOSURE, "Propagation path") == "Primary: no barrier crossed"
    assert _stage(view, _TO_ENCLOSURE, "Source scenario impulse") == f"{derived} V"
    assert _stage(view, _TO_ENCLOSURE, "Local domain impulse") == f"{derived} V"
    assert _stage(view, _TO_ENCLOSURE, "Governing before override") == f"{derived} V"
    assert _stage(view, _TO_ENCLOSURE, "Verified effective impulse") == f"{derived} V"
    # The reinforced treatment is the engine's, applied once to the untreated value above.
    # It is reported beside it rather than fed back, so the two differ and both are visible.
    treated = _stage(view, _TO_ENCLOSURE, "Insulation-treated impulse")
    assert treated not in {"—", f"{derived} V"}
    assert "from the derived mains supply" in _stage(view, _TO_ENCLOSURE, "Temporary overvoltage")
    assert "iec62477_2022.supply." in _stage(view, _TO_ENCLOSURE, "Rules read")


def test_a_stress_arriving_across_a_barrier_names_the_route_in_the_pairs_own_trace(
    supply_rules: RulePackage,
) -> None:
    project = _project(supply_rules, _configuration())

    view = _human(project, supply_rules)

    route = _stage(view, _ACROSS_THE_BARRIER, "Propagation path")
    assert "Primary: no barrier crossed" in route
    assert "Primary to Secondary across Primary ↔ Secondary" in route
    assert _stage(view, _ACROSS_THE_BARRIER, "Transferred impulse") != "—"


def test_a_circuit_to_circuit_pair_keeps_its_own_temporary_overvoltage_in_the_report(
    supply_rules: RulePackage,
) -> None:
    """No mains temporary overvoltage is copied here, and the report says whose value it is."""
    project = _project(supply_rules, _configuration())

    view = _human(project, supply_rules)

    assert "this pair's own entry" in _stage(view, _ACROSS_THE_BARRIER, "Temporary overvoltage")


def test_a_pair_with_no_circuit_on_either_side_reports_why_nothing_applies(
    supply_rules: RulePackage,
) -> None:
    """No supply reaches it and no mains temporary overvoltage is copied to it."""
    project = _project(supply_rules, _configuration())
    pair = pair_between(project, ENCLOSURE, COVER)
    project = _with_pair(
        project,
        pair.id,
        voltages=pair.voltages.model_copy(
            update={
                "temporary_overvoltage_peak_v": PairVoltage.not_applicable(
                    "Neither side is a circuit."
                )
            }
        ),
    )

    view = _human(project, supply_rules)

    stage = _stage(view, "Enclosure ↔ Cover", "Temporary overvoltage")
    assert stage.startswith("not applicable — ")
    assert _stage(view, "Enclosure ↔ Cover", "Pair relationship") == "non circuit reference"
    assert _stage(view, "Enclosure ↔ Cover", "Governing before override") == "—"


def test_a_verified_override_is_reported_with_its_evidence_and_what_became_of_it(
    supply_rules: RulePackage,
) -> None:
    project = _project(supply_rules, _configuration())
    pair = pair_between(project, circuit_id(0), ENCLOSURE)
    project = _with_pair(
        project,
        pair.id,
        impulse_override=VerifiedImpulseOverride(
            value_v=Decimal(321),
            basis=ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER,
            verification_method=ReductionVerificationMethod.TEST,
            justification="Synthetic limiter at the input terminals",
            evidence_reference="SYN-SPD-1",
            affected_location="Primary circuit to enclosure",
            spd_device_placement=SpdDevicePlacement.INTERNAL_TO_EQUIPMENT,
            spd_device_degradable=False,
        ),
    )
    model = _report(project, supply_rules)
    view = build_human_report_view(model)

    evidence = _evidence(view, _TO_ENCLOSURE)
    assert evidence["Recorded value"] == "321 V"
    assert evidence["Basis"] == "spd or transient limiter"
    assert evidence["Verification method"] == "test"
    assert evidence["Evidence reference"] == "SYN-SPD-1"
    assert evidence["Affected location"] == "Primary circuit to enclosure"
    assert evidence["Device placement"] == "internal to equipment"
    assert evidence["Outcome"].startswith("applied; effective impulse 321 V")
    assert _stage(view, _TO_ENCLOSURE, "Verified effective impulse") == "321 V"
    # The obligations the reduction carries stay visible while it is active.
    assert SPD_REDUCTION_WARNING in {advisory.code for advisory in view.advisories}
    assert "SYN-SPD-1" in render_latex(model)


def test_a_refused_override_is_reported_with_the_reason_and_the_derived_value_stands(
    supply_rules: RulePackage,
) -> None:
    project = _project(supply_rules, _configuration())
    pair = pair_between(project, circuit_id(0), ENCLOSURE)
    project = _with_pair(
        project,
        pair.id,
        impulse_override=VerifiedImpulseOverride(
            value_v=Decimal(11),
            basis=ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER,
            verification_method=ReductionVerificationMethod.TEST,
            justification="Synthetic attenuation claimed where nothing isolates the two sides",
            evidence_reference="SYN-HF-2",
            affected_location="Primary circuit to enclosure",
            transformer_frequency_hz=Decimal(5000),
        ),
    )
    model = _report(project, supply_rules)
    view = build_human_report_view(model)
    assert model.supply is not None

    evidence = _evidence(view, _TO_ENCLOSURE)
    assert evidence["Outcome"].startswith("not applied — ")
    assert _stage(view, _TO_ENCLOSURE, "Verified effective impulse") == (
        f"{model.supply.governing.impulse_v} V"
    )


def test_an_arrangement_that_could_not_be_derived_is_reported_with_every_reason(
    supply_rules: RulePackage,
) -> None:
    project = _project(
        supply_rules,
        _configuration(),
        _configuration(id=UUID(int=3), name="Unsupported mains", band=OUT_OF_BAND),
    )
    model = _report(project, supply_rules)
    view = build_human_report_view(model)

    assert view.supply is not None
    assert [blocked.name for blocked in view.supply.blocked] == ["Unsupported mains"]
    assert view.supply.blocked[0].reasons
    assert all(":" in reason for reason in view.supply.blocked[0].reasons)
    assert "Unsupported mains" in render_latex(model)


def test_a_pair_whose_topology_is_unresolved_says_so_rather_than_reporting_a_stress(
    supply_rules: RulePackage,
) -> None:
    project = _project(supply_rules, _configuration(), barrier_status=UNEVALUATED)
    model = _report(project, supply_rules)
    view = build_human_report_view(model)

    assert _stage(view, _TO_ENCLOSURE, "Topology state") == "not evaluated"
    assert _stage(view, _TO_ENCLOSURE, "Governing before override") == "—"
    assert UNRESOLVED_TOPOLOGY_WARNING in {advisory.code for advisory in view.advisories}
    assert any(
        calculation.supply is not None
        and calculation.supply.state is DomainStressState.NOT_EVALUATED
        for group in model.groups
        for calculation in group.calculations
    )


def test_both_figures_are_reported_when_a_derivation_supersedes_an_entry(
    supply_rules: RulePackage,
) -> None:
    """The report never shows only the winner: an entry that was overruled is named."""
    project = _project(supply_rules, _configuration())
    model = _report(project, supply_rules)
    assert model.supply is not None
    derived = model.supply.governing.impulse_v
    assert derived is not None and derived > DEFAULT_IMPULSE_V

    superseded = next(
        warning for warning in model.warnings if warning.code == SUPERSEDED_ENTRY_WARNING
    )
    assert f"{DEFAULT_IMPULSE_V}" in superseded.message
    assert f"{derived}" in superseded.message
    # The renderer escapes the underscores in a warning code, so the message is what is looked
    # for here; the code itself is asserted on the model above.
    assert "is superseded by" in render_latex(model)


def test_both_figures_are_reported_when_an_entry_is_the_more_severe_of_the_two(
    supply_rules: RulePackage,
) -> None:
    project = _project(supply_rules, _configuration())
    entered = Decimal(600)
    project = project.model_copy(
        update={"defaults": project.defaults.model_copy(update={"impulse_v": entered})}
    )
    model = _report(project, supply_rules)
    assert model.supply is not None
    derived = model.supply.governing.impulse_v
    assert derived is not None and derived < entered

    exceeds = next(
        warning for warning in model.warnings if warning.code == ENTRY_EXCEEDS_DERIVED_WARNING
    )
    assert f"{entered}" in exceeds.message
    assert f"{derived}" in exceeds.message
    # The pair is dimensioned from the entry, and the derivation it beat is still reported.
    assert (
        _stage(build_human_report_view(model), _TO_ENCLOSURE, "Verified effective impulse")
        == f"{derived} V"
    )
    row = next(row for row in model.matrix_rows if row.net_a == "Circuit Primary")
    assert row.impulse.value == entered


def test_a_project_declaring_no_arrangement_reports_no_supply_section(report_inputs) -> None:
    """The state every project that predates the feature is in, and the one a user returns to."""
    project, results, groups, rules = report_inputs
    model = build_report_model(project, results, groups, rules)

    assert model.supply is None
    assert model.supply_configurations == ()
    assert build_human_report_view(model).supply is None
    assert "Supply Arrangements" not in render_latex(model)


def test_pairs_sharing_a_group_but_not_a_derivation_are_reported_separately(
    supply_rules: RulePackage,
) -> None:
    """One block per distinct derivation, so no pair's route stands in for another's."""
    project = _project(supply_rules, _configuration())
    view = _human(project, supply_rules)

    described: list[str] = []
    for group in view.groups:
        for block in group.supply:
            described.extend(block.pair_labels)
    assert sorted(described) == sorted(
        label for group in view.groups for label in group.pair_labels
    )
    assert len(set(described)) == len(described)


def test_the_lowest_overvoltage_category_keeps_its_standing_warning_in_the_report(
    supply_rules: RulePackage,
) -> None:
    """A warning about the source, disclosed once for the arrangement that carries it."""
    project = _project(supply_rules, _configuration(overvoltage_category=OvervoltageCategory.I))
    model = _report(project, supply_rules)

    warning = next(item for item in model.warnings if item.code == OVERVOLTAGE_CATEGORY_I_WARNING)
    assert "Primary mains" in warning.message
    assert OVERVOLTAGE_CATEGORY_I_WARNING in {
        advisory.code for advisory in build_human_report_view(model).advisories
    }


def test_a_project_whose_arrangements_are_all_disabled_still_lists_them(
    supply_rules: RulePackage,
) -> None:
    """Switching every row off derives nothing, and does not erase what was declared."""
    project = _project(supply_rules, _configuration(enabled=False))
    model = _report(project, supply_rules)
    view = build_human_report_view(model)

    assert model.supply is None
    assert view.supply is not None
    assert [item.status for item in view.supply.configurations] == ["not enabled"]
    assert view.supply.scenarios == ()
    rendered = render_latex(model)
    assert "Primary mains" in rendered
    assert "No supply arrangement is enabled" in rendered
