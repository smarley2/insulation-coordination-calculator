"""Issue #36's derivation and its report, run against the approved licensed package.

The public suite proves the derivation and the report on synthetic content. What only this
module can prove is that the *licensed* archive answers the same adapter: that every semantic
ID the derivation reads survives extraction, review, approval and a round trip, and that
whatever the package then says about one declared arrangement - a derived scenario or a typed
refusal - reaches the report rather than being dropped on the way.

**Why no derived scenario is asserted here.** Branch authority for the supply routes comes
from reviewed clause facts, and the fact set this repository can hold is the placeholder set
``tests/private/test_iec62477_supply_clause_facts.py`` authors: local tokens chosen for
structural distinctness, not readings of the licensed clauses. A real reading is the
maintainer's authoring session and has no anchor here, so no arrangement resolves a system
voltage against the placeholders. Asserting a derived figure would mean writing that reading
into this file, which is the one thing the private suite exists to avoid. What is asserted
instead is that the refusal is typed, names the rule that refused, and is disclosed - which is
the behaviour a package that cannot answer must have.

No value, heading, label or wording from any licensed table or clause is named here, and no
document is written to the tree.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import (
    calculate_project_pair,
    derive_project_supply,
)
from insulation_coordination.calculation.grouping import group_results
from insulation_coordination.calculation.supply_rules import READ_SEMANTIC_IDS, read_supply_rules
from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
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
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    SupplyConfiguration,
    SupplyKind,
)
from insulation_coordination.report.human_view import (
    ALTITUDE_STATEMENT,
    build_human_report_view,
)
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import ReportModel, build_report_model
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from tests.fixtures.supply_topologies import VERIFIED, supply_topology
from tests.private.test_iec62477_slice_c_roundtrip import _approved_slice_c

pytestmark = pytest.mark.private_standard

#: The one arrangement this project declares. Its voltage is a plain round number chosen here,
#: not read from any licensed axis, so nothing about the source's own bands is recorded.
DECLARED_VOLTAGE_V = Decimal(400)


def _licensed_package(reviewed_draft, tmp_path: Path) -> RulePackage:
    """The approved licensed package, written and reloaded through the archive."""

    archive = tmp_path / "iec62477-supply-report.icrules"
    write_rule_package(archive, _approved_slice_c(reviewed_draft))
    return load_rule_package(archive)


def _project(rules: RulePackage) -> Project:
    """Two domains across a verified barrier, one enabled arrangement, every pair dimensionable.

    The pair entries are what dimension this project: nothing here depends on the licensed
    package answering the derivation, so the report builds whether it does or not.
    """

    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))
    assert rules.package_sha256 is not None
    configuration = SupplyConfiguration(
        id=UUID(int=1),
        enabled=True,
        name="Declared mains input",
        supply_kind=SupplyKind.AC_MAINS,
        nominal_voltage_v=DECLARED_VOLTAGE_V,
        phase_system=PhaseSystem.THREE_PHASE,
        earthing_arrangement=EarthingArrangement.TN_STAR_POINT_EARTHED,
        overvoltage_category=OvervoltageCategory.III,
        input_topology=InputTopology.DIRECT_INPUT,
        declared_system_voltages=(
            DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=DECLARED_VOLTAGE_V),
        ),
    )
    return project.model_copy(
        update={
            "metadata": ProjectMetadata(
                title="Licensed package supply report",
                document_number="PRIV-036",
                revision="A",
            ),
            "application_version": "0.1.0",
            "required_rules": RulePackageReference(
                package_id=str(rules.manifest.package_id),
                version=rules.manifest.version,
                sha256=rules.package_sha256,
            ),
            "defaults": ProjectDefaults(
                frequency_hz=Decimal(50),
                impulse_v=Decimal(2500),
                insulation_type=InsulationType.BASIC,
                field_condition=FieldCondition.INHOMOGENEOUS,
                altitude_m=Decimal(0),
                pollution_degree=2,
                construction_type=ConstructionType.PRINTED_WIRING,
                cti_or_material_group="I",
            ),
            "supply_configurations": (configuration,),
            "pairs": tuple(
                pair.model_copy(
                    update={
                        "voltages": PairVoltages(
                            long_term_rms_v=PairVoltage.applicable(Decimal(300)),
                            steady_state_peak_v=PairVoltage.applicable(Decimal(400)),
                            recurring_peak_v=PairVoltage.applicable(Decimal(500)),
                            temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(600)),
                        )
                    }
                )
                for pair in project.pairs
            ),
        }
    )


def _report(project: Project, rules: RulePackage) -> ReportModel:
    supply = derive_project_supply(project, rules)
    results = tuple(
        calculate_project_pair(project, pair, rules, supply=supply) for pair in project.pairs
    )
    return build_report_model(project, results, group_results(results, ()), rules)


def test_the_approved_licensed_package_answers_the_supply_adapter(
    reviewed_draft,
    tmp_path: Path,
) -> None:
    """Every semantic ID the derivation reads survives approval and a round trip."""

    package = _licensed_package(reviewed_draft, tmp_path)

    rules = read_supply_rules(package)

    assert READ_SEMANTIC_IDS
    available = {
        rule.id
        for rule in (*package.tables, *package.formulas, *package.decisions, *package.guidance)
    }
    for semantic_id in READ_SEMANTIC_IDS:
        assert any(
            candidate == semantic_id or candidate.startswith(f"{semantic_id}.")
            for candidate in available
        ), semantic_id
    assert rules.system_voltage_resolution.id.startswith("iec62477_2022.supply.")
    assert rules.impulse.ac.table.cells and rules.impulse.dc.table.cells
    assert rules.temporary_overvoltage.ac.table.cells


def test_every_declared_arrangement_reaches_the_report_derived_or_refused(
    reviewed_draft,
    tmp_path: Path,
) -> None:
    """A package that cannot answer must say so in the document, not fall silent.

    The approved licensed package answers the clearance questions too, so this is one package
    throughout - the same one an installation receives.
    """

    rules = _licensed_package(reviewed_draft, tmp_path)
    project = _project(rules)

    model = _report(project, rules)
    view = build_human_report_view(model)

    assert model.supply is not None
    assert view.supply is not None
    declared = {configuration.name for configuration in project.supply_configurations}
    accounted = {scenario.configuration_name for scenario in model.supply.governing.scenarios} | {
        blocked.configuration_name for blocked in model.supply.governing.unresolved
    }
    assert accounted == declared
    for blocked in model.supply.governing.unresolved:
        assert blocked.blocks
        # A refusal names what refused, so a reader can look the rule up rather than guess.
        assert all(item.semantic_rule_id for item in blocked.blocks)
    rendered = render_latex(model)
    assert "Supply Arrangements" in rendered
    for name in declared:
        assert name in rendered


def test_the_report_states_that_altitude_left_the_licensed_source_voltages_alone(
    reviewed_draft,
    tmp_path: Path,
) -> None:
    """Read off the derivation's own trace, against the real package's rule identifiers."""

    rules = _licensed_package(reviewed_draft, tmp_path)

    model = _report(_project(rules), rules)
    view = build_human_report_view(model)

    assert model.supply is not None
    assert model.supply.altitude_altered_source_voltages is False
    assert view.supply is not None
    assert view.supply.altitude_statement == ALTITUDE_STATEMENT
