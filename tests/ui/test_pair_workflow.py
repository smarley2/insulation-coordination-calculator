from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.domain.enums import (
    Applicability,
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
    NetClass,
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.project.pairs import reconcile_pairs
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from tests.fixtures.synthetic_rules import synthetic_part1_rule_package as synthetic_rule_package


def _uuid(seed: int) -> UUID:
    return UUID(int=seed)


def _make_project(net_names: tuple[str, ...]) -> Project:
    net_classes = tuple(NetClass(id=_uuid(i + 1), name=name) for i, name in enumerate(net_names))
    pairs = reconcile_pairs(net_classes, ())
    return Project(
        id=_uuid(100),
        metadata=ProjectMetadata(title="Test Drive"),
        application_version="0.1.0",
        required_rules=RulePackageReference(
            package_id="iec-60664",
            version="2020.1",
            sha256="a" * 64,
        ),
        defaults=ProjectDefaults(
            frequency_hz=Decimal(50),
            insulation_type=InsulationType.BASIC,
            field_condition=FieldCondition.INHOMOGENEOUS,
            altitude_m=Decimal(0),
            pollution_degree=2,
            construction_type=ConstructionType.OTHER,
            cti_or_material_group="I",
        ),
        net_classes=net_classes,
        pairs=pairs,
    )


@pytest.fixture
def synthetic_rules(tmp_path: Path) -> RulePackage:
    path = tmp_path / "synthetic.icrules"
    write_rule_package(path, synthetic_rule_package())
    return load_rule_package(path)


@pytest.fixture
def pair_page(qtbot, synthetic_rules):
    from insulation_coordination.ui.pair_editor import PairPage

    project = _make_project(("HV+", "HV-", "PE"))
    page = PairPage()
    page.load_project(project)
    page.load_rules(synthetic_rules)
    qtbot.addWidget(page)
    return page


def test_matrix_lower_half_references_same_pair(qtbot, pair_page):
    upper = pair_page.matrix_model.pair_at(0, 1)
    lower = pair_page.matrix_model.pair_at(1, 0)
    assert upper is lower


def test_matrix_diagonal_is_none(qtbot, pair_page):
    assert pair_page.matrix_model.pair_at(0, 0) is None


def test_select_pair_fills_editor(qtbot, pair_page):
    pair = pair_page.project.pairs[0]
    pair_page.select_pair_by_id(str(pair.id))
    assert pair_page.editor.pair is not None
    assert pair_page.editor.pair.id == pair.id


def test_frequency_override_is_visible(qtbot, pair_page):
    pair = pair_page.project.pairs[0]
    pair_page.select_pair_by_id(str(pair.id))
    assert pair_page.editor.frequency_source_text == "Default"
    pair_page.editor.set_frequency_override("100 kHz")
    assert pair_page.editor.frequency_source_text == "Override"


def test_set_long_term_rms_updates_project(qtbot, pair_page):
    pair = pair_page.project.pairs[0]
    pair_page.select_pair_by_id(str(pair.id))
    pair_page.editor.set_long_term_rms("500 V")
    updated = pair_page.project.pair_by_id(pair.id)
    assert updated.voltages.long_term_rms_v.applicability is Applicability.APPLICABLE
    assert updated.voltages.long_term_rms_v.value == Decimal(500)


def test_recalculate_after_voltage_change(qtbot, pair_page):
    pair = pair_page.project.pairs[0]
    pair_page.select_pair_by_id(str(pair.id))
    pair_page.editor.set_long_term_rms("500 V")
    pair_page.editor.set_steady_state_peak("300 V")
    pair_page.editor.set_recurring_peak("400 V")
    pair_page.editor.set_temporary_overvoltage_not_applicable()
    pair_page.editor.set_impulse_override("800 V")
    pair_page.recalculate()
    result = pair_page.result_by_id(pair.id)
    assert result is not None
    assert result.clearance_mm > Decimal(0)
    assert result.creepage_mm > Decimal(0)
    assert result.clearance_mm <= result.creepage_mm


def test_invalid_input_clears_results(qtbot, pair_page):
    pair = pair_page.project.pairs[0]
    pair_page.select_pair_by_id(str(pair.id))
    pair_page.editor.set_long_term_rms("500 V")
    pair_page.editor.set_steady_state_peak("300 V")
    pair_page.editor.set_recurring_peak("400 V")
    pair_page.editor.set_temporary_overvoltage_not_applicable()
    pair_page.editor.set_impulse_override("800 V")
    pair_page.recalculate()
    assert pair_page.result_by_id(pair.id) is not None
    # Clear impulse — calculation should fail without it
    pair_page.editor.clear_impulse_override()
    pair_page.recalculate()
    assert pair_page.result_by_id(pair.id) is None


def test_pair_list_shows_net_names(qtbot, pair_page):
    model = pair_page.pair_list_model
    assert model.rowCount() == 3
    for row in range(model.rowCount()):
        label = model.data(model.index(row, 0))
        assert "HV" in label or "PE" in label


def test_grouping_shows_signatures(qtbot, pair_page):
    # Set up all pairs with valid voltages
    for pair in pair_page.project.pairs:
        pair_page.select_pair_by_id(str(pair.id))
        pair_page.editor.set_long_term_rms("500 V")
        pair_page.editor.set_steady_state_peak("300 V")
        pair_page.editor.set_recurring_peak("400 V")
        pair_page.editor.set_temporary_overvoltage_not_applicable()
        pair_page.editor.set_impulse_override("800 V")
    pair_page.recalculate()
    groups = pair_page.calculation_review.groups
    assert len(groups) >= 1
