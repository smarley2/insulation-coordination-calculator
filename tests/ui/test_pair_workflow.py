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
    PairVoltage,
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
            impulse_v=Decimal(1200),
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


def _set_valid_inputs(page) -> None:
    for pair in page.project.pairs:
        page.select_pair_by_id(str(pair.id))
        page.editor.set_long_term_rms("500 V")
        page.editor.set_steady_state_peak("300 V")
        page.editor.set_recurring_peak("400 V")
        page.editor.set_temporary_overvoltage_not_applicable()
        page.editor.set_impulse_override("800 V")


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
    _set_valid_inputs(pair_page)
    pair_page.recalculate()
    result = pair_page.result_by_id(pair.id)
    assert result is not None
    assert result.clearance_mm > Decimal(0)
    assert result.creepage_mm > Decimal(0)
    assert result.clearance_mm <= result.creepage_mm


def test_invalid_input_clears_results(qtbot, pair_page, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    pair = pair_page.project.pairs[0]
    _set_valid_inputs(pair_page)
    pair_page.recalculate()
    assert pair_page.result_by_id(pair.id) is not None
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *_args: None))
    # Clear impulse — calculation should fail without it
    for current_pair in pair_page.project.pairs:
        pair_page.select_pair_by_id(str(current_pair.id))
        pair_page.editor.clear_impulse_override()
    pair_page.recalculate()
    assert pair_page.result_by_id(pair.id) is None


def test_recalculate_reports_missing_frequency_with_pair_label(qtbot, pair_page, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    project = pair_page.project.model_copy(
        update={
            "defaults": pair_page.project.defaults.model_copy(update={"frequency_hz": None}),
            "pairs": tuple(
                pair.model_copy(
                    update={
                        "voltages": pair.voltages.model_copy(
                            update={
                                "long_term_rms_v": PairVoltage.applicable(Decimal(500)),
                                "steady_state_peak_v": PairVoltage.applicable(Decimal(300)),
                                "recurring_peak_v": PairVoltage.applicable(Decimal(400)),
                                "temporary_overvoltage_peak_v": PairVoltage.not_applicable(
                                    "No temporary overvoltage."
                                ),
                            }
                        ),
                        "impulse_v": pair.impulse_v.override(Decimal(800)),
                    }
                )
                for pair in pair_page.project.pairs
            ),
        }
    )
    pair_page.load_project(project)
    captured: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _parent, _title, message: captured.append(message)),
    )

    pair_page.recalculate()

    assert pair_page.calculation_review._results_list.count() == 0
    assert "HV+ ↔ HV-" in captured[0]
    assert "HV+ ↔ PE" in captured[0]
    assert "HV- ↔ PE" in captured[0]
    assert "Frequency is required" in captured[0]


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


def test_matrix_parameter_displays_pair_voltage(qtbot, pair_page):
    pair = pair_page.project.pairs[0]
    pair_page.select_pair_by_id(str(pair.id))
    pair_page.editor.set_long_term_rms("500 V")
    pair_page._matrix_parameter_combo.setCurrentText("Long-term RMS voltage")

    index = pair_page.matrix_model.index(0, 1)
    assert pair_page.matrix_model.data(index) == "500 V"
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(1, 0)) == "500 V"


def test_matrix_parameter_displays_default_and_pair_override(qtbot, pair_page):
    pair = pair_page.project.pairs[0]
    pair_page._matrix_parameter_combo.setCurrentText("Frequency")
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == "50 Hz (D)"

    pair_page.select_pair_by_id(str(pair.id))
    pair_page.editor.set_frequency_override("100 kHz")
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == "100000 Hz (O)"

    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 2)) == "50 Hz (D)"


def test_matrix_parameter_displays_calculated_distances(qtbot, pair_page):
    pair_page._matrix_parameter_combo.setCurrentText("Required clearance")
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == "—"

    _set_valid_inputs(pair_page)
    pair_page.recalculate()
    result = pair_page.result_by_id(pair_page.project.pairs[0].id)

    assert result is not None
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == (
        f"{result.clearance_mm} mm"
    )
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(1, 0)) == (
        f"{result.clearance_mm} mm"
    )

    pair_page._matrix_parameter_combo.setCurrentText("Required creepage")
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == (
        f"{format(result.creepage_mm, 'f').rstrip('0').rstrip('.')} mm"
    )


def test_clicking_matrix_cell_loads_pair_editor(qtbot, pair_page):
    pair_page._on_matrix_clicked(pair_page.matrix_model.index(1, 0))
    assert pair_page.editor.pair is pair_page.project.pairs[0]


def test_pair_editor_shows_inherited_default_values(qtbot, pair_page):
    pair_page.select_pair_by_id(str(pair_page.project.pairs[0].id))
    assert pair_page.editor._freq_edit.text() == "50"
    assert pair_page.editor._freq_source_label.text() == "Default"
    assert pair_page.editor._impulse_edit.text() == "1200"
    assert pair_page.editor._impulse_source_label.text() == "Default"


def test_pairs_page_uses_splitters_and_expanding_matrix(qtbot, pair_page):
    from PySide6.QtWidgets import QSplitter

    assert isinstance(pair_page._main_splitter, QSplitter)
    assert isinstance(pair_page._top_splitter, QSplitter)
    assert pair_page._matrix_view.minimumHeight() >= 160
    assert pair_page._matrix_view.sizePolicy().verticalPolicy().name == "Expanding"


def test_pair_edit_refreshes_selected_matrix_parameter(qtbot, pair_page):
    pair_page._matrix_parameter_combo.setCurrentText("Long-term RMS voltage")
    pair = pair_page.project.pairs[0]
    pair_page.select_pair_by_id(str(pair.id))
    pair_page.editor.set_long_term_rms("750 V")
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == "750 V"


def test_pairs_page_separates_matrix_pairs_and_editor_scroll(qtbot, pair_page):
    from PySide6.QtWidgets import QApplication, QSplitter

    pair_page.resize(1200, 800)
    pair_page.show()
    QApplication.processEvents()

    assert isinstance(pair_page._left_splitter, QSplitter)
    assert pair_page._left_splitter.sizes()[0] >= 160
    assert pair_page._left_splitter.sizes()[1] >= 80
    assert pair_page._editor_scroll.verticalScrollBar().maximum() > 0
    matrix_rect = pair_page._matrix_view.rect()
    matrix_rect.moveTopLeft(pair_page._matrix_view.mapTo(pair_page, matrix_rect.topLeft()))
    pairs_rect = pair_page._pair_list_view.rect()
    pairs_rect.moveTopLeft(pair_page._pair_list_view.mapTo(pair_page, pairs_rect.topLeft()))
    assert not matrix_rect.intersects(pairs_rect)
    assert pair_page.editor._rms_na_button.parentWidget() is not None
    assert pair_page.editor._steady_na_button.parentWidget() is not None


def test_pair_editor_does_not_force_horizontal_page_growth(qtbot, pair_page):
    assert pair_page.editor.minimumWidth() == 0
    assert pair_page._editor_scroll.minimumWidth() == 0
    assert pair_page.editor.sizePolicy().horizontalPolicy().name == "Expanding"
