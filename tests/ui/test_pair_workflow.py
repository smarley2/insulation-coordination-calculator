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
    PairVoltage,
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
    assert pair_page.editor.frequency_source_text == "Project default"
    pair_page.editor.set_frequency_override("100 kHz")
    assert pair_page.editor.frequency_source_text == "Manual"


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


def test_recalculate_reports_missing_rules(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from insulation_coordination.ui.pair_editor import PairPage

    page = PairPage()
    qtbot.addWidget(page)
    page.load_project(_make_project(("HV+", "HV-", "PE")))
    captured: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _parent, _title, message: captured.append(message)),
    )

    page.recalculate()

    assert "Load an approved rules package" in captured[0]
    assert page.result_by_id(page.project.pairs[0].id) is None


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


def test_pairs_column_stays_as_narrow_as_its_pair_names(qtbot, pair_page):
    pair_page.resize(1600, 900)
    pair_page.show()
    qtbot.waitExposed(pair_page)
    pair_page._set_initial_splitter_sizes()

    pairs_width, review_width = pair_page._lower_splitter.sizes()
    names_width = pair_page._pair_list_view.sizeHintForColumn(0)

    assert names_width <= pairs_width <= names_width + 80
    assert pairs_width < 1600 // 3
    assert review_width > 2 * pairs_width
    groups_width, results_width = pair_page.calculation_review._review_splitter.sizes()
    assert abs(groups_width - results_width) <= 1


def test_matrix_parameter_displays_inner_layer_distances(qtbot, pair_page):
    pair_page._matrix_parameter_combo.setCurrentText("Inner-layer clearance")
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == "—"

    _set_valid_inputs(pair_page)
    pair_page.recalculate()
    result = pair_page.result_by_id(pair_page.project.pairs[0].id)

    assert result is not None
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == (
        f"{result.inner_clearance_mm} mm"
    )

    pair_page._matrix_parameter_combo.setCurrentText("Inner-layer creepage")
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == (
        f"{format(result.inner_creepage_mm, 'f').rstrip('0').rstrip('.')} mm"
    )


def test_clicking_matrix_cell_loads_pair_editor(qtbot, pair_page):
    pair_page._on_matrix_clicked(pair_page.matrix_model.index(1, 0))
    assert pair_page.editor.pair is pair_page.project.pairs[0]


def test_pair_editor_shows_inherited_default_values(qtbot, pair_page):
    pair_page.select_pair_by_id(str(pair_page.project.pairs[0].id))
    assert pair_page.editor._freq_edit.text() == "50"
    assert pair_page.editor._freq_source_label.text() == "Project default"
    assert pair_page.editor._impulse_combo.currentText() == "1.2 kV"
    assert pair_page.editor._impulse_source_label.text() == "Project default"


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

    assert isinstance(pair_page._lower_splitter, QSplitter)
    assert pair_page._lower_splitter.sizes()[0] >= 80
    assert pair_page._lower_splitter.sizes()[1] >= 160
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


def test_pair_inputs_stay_narrow_and_hug_the_right_edge(qtbot, pair_page):
    from PySide6.QtWidgets import QApplication, QWidget

    # Wide enough that the editor gets the width it asks for. A row now carries a
    # help control, the input, a state badge and a button, so below roughly 1700
    # the splitter's half caps the editor and every row is squeezed flush.
    pair_page.resize(1900, 900)
    pair_page.show()
    pair_page.select_pair_by_id(str(pair_page.project.pairs[0].id))
    QApplication.processEvents()

    editor = pair_page.editor
    for field in (editor._rms_edit, editor._freq_edit, editor._insulation_combo):
        assert field.width() <= 220
        row = field.parentWidget()
        assert field.x() > 0, "a leading stretch should push the input to the right"
        rightmost = max(child.geometry().right() for child in row.findChildren(QWidget))
        assert row.width() - rightmost <= 4, "the row must not leave slack on the right"


def test_lower_area_shows_pairs_groups_and_results_side_by_side(qtbot, pair_page):
    from PySide6.QtWidgets import QApplication

    pair_page.resize(1600, 900)
    pair_page.show()
    QApplication.processEvents()

    review = pair_page.calculation_review
    assert pair_page._lower_splitter.orientation().name == "Horizontal"
    assert review._review_splitter.orientation().name == "Horizontal"
    assert pair_page._lower_splitter.widget(0).isAncestorOf(pair_page._pair_list_view)
    assert pair_page._lower_splitter.widget(1) is review
    assert review._review_splitter.widget(0).isAncestorOf(review._groups_list)
    assert review._review_splitter.widget(1).isAncestorOf(review._results_list)

    columns = [
        pair_page._pair_list_view,
        review._groups_list,
        review._results_list,
    ]
    corners = [column.mapTo(pair_page, column.rect().topLeft()) for column in columns]
    lefts = [corner.x() for corner in corners]
    assert lefts == sorted(lefts), "pairs, groups, results must read left to right"
    assert len(set(lefts)) == 3, "the three columns must not overlap"
    assert len({corner.y() for corner in corners}) == 1, "the three columns must share a top edge"
    # Recalculate spans the three columns rather than sitting inside one.
    assert pair_page.recalc_button.width() > review._groups_list.width()


def test_matrix_parameter_combo_is_only_as_wide_as_its_entries(qtbot, pair_page):
    from PySide6.QtWidgets import QApplication

    pair_page.resize(1600, 900)
    pair_page.show()
    QApplication.processEvents()

    combo = pair_page._matrix_parameter_combo
    assert combo.width() <= combo.sizeHint().width() + 4
    assert combo.width() < pair_page._matrix_view.width()


def test_editor_opens_no_wider_than_its_inputs_need(qtbot, pair_page):
    from PySide6.QtWidgets import QApplication

    pair_page.resize(1900, 1000)
    pair_page.show()
    QApplication.processEvents()

    matrix_width, editor_width = pair_page._top_splitter.sizes()
    assert editor_width <= pair_page.editor.sizeHint().width() + 40
    assert editor_width < matrix_width, "the matrix should keep the wider half"


def _select_matrix_columns(page, columns: tuple[int, ...]) -> None:
    from PySide6.QtCore import QItemSelection, QItemSelectionModel

    model = page.matrix_model
    selection_model = page._matrix_view.selectionModel()
    selection_model.clearSelection()
    last_row = model.rowCount() - 1
    for column in columns:
        selection = QItemSelection(model.index(0, column), model.index(last_row, column))
        selection_model.select(selection, QItemSelectionModel.SelectionFlag.Select)


def test_hiding_selected_matrix_columns_leaves_the_rest_visible(qtbot, pair_page):
    page = pair_page
    _select_matrix_columns(page, (0, 2))

    page.hide_selected_columns()

    assert page.hidden_column_names == ("HV+", "PE")
    assert page._matrix_view.isColumnHidden(0)
    assert not page._matrix_view.isColumnHidden(1)
    assert page._matrix_view.isColumnHidden(2)


def test_hidden_columns_survive_a_matrix_refresh(qtbot, pair_page):
    page = pair_page
    _select_matrix_columns(page, (1,))
    page.hide_selected_columns()

    page.load_project(page.project)

    assert page.hidden_column_names == ("HV-",)
    assert page._matrix_view.isColumnHidden(1)


def test_showing_all_columns_clears_every_hidden_column(qtbot, pair_page):
    page = pair_page
    _select_matrix_columns(page, (0, 1))
    page.hide_selected_columns()

    page.show_all_columns()

    assert page.hidden_column_names == ()
    assert not any(page._matrix_view.isColumnHidden(i) for i in range(3))


def test_hiding_without_a_selection_changes_nothing(qtbot, pair_page):
    page = pair_page
    page._matrix_view.selectionModel().clearSelection()

    page.hide_selected_columns()

    assert page.hidden_column_names == ()


def test_matrix_columns_are_resizable_by_dragging(qtbot, pair_page):
    from PySide6.QtWidgets import QHeaderView

    page = pair_page
    header = page._matrix_view.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
    assert page._matrix_view.verticalHeader().sectionResizeMode(0) == (
        QHeaderView.ResizeMode.Interactive
    )


def test_copy_paste_moves_configuration_to_another_pair(qtbot, pair_page):
    page = pair_page
    source, target = page.project.pairs[0], page.project.pairs[1]
    page.select_pair_by_id(str(source.id))
    page.editor.set_long_term_rms("700 V")
    page.editor.set_recurring_peak_not_applicable("Source justification")
    page.editor.set_frequency_override("100 kHz")
    page.editor.set_construction_override(ConstructionType.PRINTED_WIRING)
    page.editor.set_notes("Belongs to the source pair only")
    page.copy_selected_pair()

    page.select_pair_by_id(str(target.id))
    page.paste_into_selection()

    pasted = page.project.pair_by_id(target.id)
    assert pasted.voltages.long_term_rms_v.value == Decimal(700)
    assert pasted.voltages.recurring_peak_v.applicability is Applicability.NOT_APPLICABLE
    assert pasted.frequency_hz.value == Decimal(100_000)
    assert pasted.construction_type.value is ConstructionType.PRINTED_WIRING
    assert pasted.notes == "Belongs to the source pair only"
    assert (pasted.id, pasted.net_a, pasted.net_b) == (target.id, target.net_a, target.net_b)
    assert page.editor.pair.id == target.id
    assert page.editor.frequency_source_text == "Manual"


def test_copy_paste_leaves_the_source_pair_untouched(qtbot, pair_page):
    page = pair_page
    source, target = page.project.pairs[0], page.project.pairs[1]
    page.select_pair_by_id(str(source.id))
    page.editor.set_long_term_rms("700 V")
    page.copy_selected_pair()

    page.select_pair_by_id(str(target.id))
    page.editor.set_long_term_rms("120 V")
    page.paste_into_selection()

    assert page.project.pair_by_id(source.id).voltages.long_term_rms_v.value == Decimal(700)


def test_paste_without_a_copy_changes_nothing(qtbot, pair_page):
    page = pair_page
    target = page.project.pairs[0]
    page.select_pair_by_id(str(target.id))

    page.paste_into_selection()

    assert page.project.pair_by_id(target.id) == target


def test_copy_without_a_selected_pair_leaves_paste_inert(qtbot, pair_page):
    page = pair_page
    before = page.project

    page.copy_selected_pair()
    page.paste_into_selection()

    assert page.project is before


def test_matrix_ctrl_c_ctrl_v_copies_configuration(qtbot, pair_page):
    from PySide6.QtCore import Qt

    page = pair_page
    source, target = page.project.pairs[0], page.project.pairs[1]
    page.select_pair_by_id(str(source.id))
    page.editor.set_long_term_rms("700 V")

    view = page._matrix_view
    qtbot.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    page.select_pair_by_id(str(target.id))
    qtbot.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)

    assert page.project.pair_by_id(target.id).voltages.long_term_rms_v.value == Decimal(700)


def _select_matrix_cells(page, cells: tuple[tuple[int, int], ...]) -> None:
    from PySide6.QtCore import QItemSelectionModel

    selection_model = page._matrix_view.selectionModel()
    selection_model.clearSelection()
    for row, column in cells:
        selection_model.select(
            page.matrix_model.index(row, column), QItemSelectionModel.SelectionFlag.Select
        )


def test_paste_fills_every_selected_matrix_cell(qtbot, pair_page):
    page = pair_page
    source = page.matrix_model.pair_at(0, 1)
    page.select_pair_by_id(str(source.id))
    page.editor.set_long_term_rms("700 V")
    page.copy_selected_pair()

    # The diagonal carries no pair, and (2, 0) mirrors (0, 2) — both must be tolerated.
    _select_matrix_cells(page, ((0, 0), (0, 2), (2, 0), (1, 2)))
    page.paste_into_selection()

    for row, column in ((0, 2), (1, 2)):
        pasted = page.project.pair_by_id(page.matrix_model.pair_at(row, column).id)
        assert pasted.voltages.long_term_rms_v.value == Decimal(700)


def test_paste_without_a_selection_falls_back_to_the_clicked_pair(qtbot, pair_page):
    page = pair_page
    source, target = page.project.pairs[0], page.project.pairs[1]
    page.select_pair_by_id(str(source.id))
    page.editor.set_long_term_rms("700 V")
    page.copy_selected_pair()

    page.select_pair_by_id(str(target.id))
    page._matrix_view.selectionModel().clearSelection()
    page.paste_into_selection()

    assert page.project.pair_by_id(target.id).voltages.long_term_rms_v.value == Decimal(700)


def test_not_applicable_voltage_shows_na_instead_of_an_empty_box(qtbot, pair_page):
    page = pair_page
    pair = page.project.pairs[0]
    page.select_pair_by_id(str(pair.id))

    page.editor._on_rms_na()

    assert page.editor._rms_edit.text() == "N/A"
    # And it survives a reload from the project, not just the button click.
    page.select_pair_by_id(str(pair.id))
    assert page.editor._rms_edit.text() == "N/A"
    assert page.editor._rms_edit.toolTip() == "Not applicable per design review"
    assert page.editor._steady_peak_edit.text() == ""


def _exclude_pair(page, pair) -> None:
    page.select_pair_by_id(str(pair.id))
    page.editor.set_long_term_rms_not_applicable("Nets cannot come near each other.")
    page.editor.set_steady_state_peak_not_applicable("Nets cannot come near each other.")
    page.editor.set_recurring_peak_not_applicable("Nets cannot come near each other.")
    page.editor.set_temporary_overvoltage_not_applicable()


def test_recalculate_skips_pairs_whose_every_stress_is_na(qtbot, pair_page, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    page = pair_page
    _set_valid_inputs(page)
    excluded, calculated = page.project.pairs[0], page.project.pairs[1]
    _exclude_pair(page, excluded)
    captured: list[object] = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args: captured.append(args)))

    page.recalculate()

    assert captured == []
    assert page.result_by_id(excluded.id) is None
    assert page.result_by_id(calculated.id) is not None


def test_coverage_matrix_marks_excluded_pairs(qtbot, pair_page):
    page = pair_page
    excluded = page.matrix_model.pair_at(0, 1)
    _exclude_pair(page, excluded)

    page.matrix_model.set_parameter("coverage")

    assert page.matrix_model.data(page.matrix_model.index(0, 1)) == "N/A"
    assert page.matrix_model.data(page.matrix_model.index(0, 2)) == "✓"


def test_pair_editor_offers_the_same_dropdowns_as_the_project_defaults(qtbot, pair_page):
    from insulation_coordination.ui.value_options import (
        IMPULSE_OPTIONS,
        MATERIAL_OPTIONS,
        POLLUTION_OPTIONS,
    )

    page = pair_page
    page.select_pair_by_id(str(page.project.pairs[0].id))

    for combo, options in (
        (page.editor._impulse_combo, IMPULSE_OPTIONS),
        (page.editor._pollution_combo, POLLUTION_OPTIONS),
        (page.editor._cti_combo, MATERIAL_OPTIONS),
    ):
        texts = [combo.itemText(index) for index in range(combo.count())]
        # No blank entry: "use the project default" is the Default button, not a value.
        assert texts == [text for text, _value in options]


def test_choosing_a_dropdown_value_overrides_the_project_default(qtbot, pair_page):
    page = pair_page
    pair = page.project.pairs[0]
    page.select_pair_by_id(str(pair.id))
    assert page.editor._impulse_source_label.text() == "Project default"

    page.editor._impulse_combo.setCurrentText("2.5 kV")
    page.editor._pollution_combo.setCurrentText("1")
    page.editor._cti_combo.setCurrentText("IIIa")

    updated = page.project.pair_by_id(pair.id)
    assert updated.impulse_v.value == Decimal(2500)
    assert updated.pollution_degree.value == 1
    assert updated.cti_or_material_group.value == "IIIa"
    assert page.editor._impulse_source_label.text() == "Manual"


def test_an_off_list_override_is_offered_back_as_legacy(qtbot, pair_page):
    page = pair_page
    pair = page.project.pairs[0]
    page.select_pair_by_id(str(pair.id))

    page.editor.set_pollution_override("3")
    page.select_pair_by_id(str(pair.id))

    assert page.editor._pollution_combo.currentText() == "3 (legacy)"
    assert page.project.pair_by_id(pair.id).pollution_degree.value == 3


def test_pair_dropdown_is_empty_when_no_value_resolves(qtbot, pair_page, monkeypatch):
    """A missing project default must stay visibly missing, not fall back silently."""
    from PySide6.QtWidgets import QMessageBox

    page = pair_page
    _set_valid_inputs(page)
    project = page.project
    page.load_project(
        project.model_copy(
            update={
                "defaults": project.defaults.model_copy(update={"insulation_type": None}),
                "pairs": tuple(
                    pair.model_copy(update={"insulation_type": pair.insulation_type.inherit()})
                    for pair in project.pairs
                ),
            }
        )
    )
    pair = page.project.pairs[0]
    page.select_pair_by_id(str(pair.id))

    assert page.editor._insulation_combo.currentIndex() == -1
    assert page.editor._insulation_combo.currentText() == ""

    captured: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _parent, _title, message: captured.append(message)),
    )
    page.recalculate()

    assert "Insulation type is required" in captured[0]
    assert page.result_by_id(pair.id) is None


def test_default_button_restores_inheritance_and_shows_the_inherited_value(qtbot, pair_page):
    page = pair_page
    pair = page.project.pairs[0]
    page.select_pair_by_id(str(pair.id))
    page.editor._impulse_combo.setCurrentText("2.5 kV")
    assert page.project.pair_by_id(pair.id).impulse_v.is_override

    page.editor.clear_impulse_override()

    assert not page.project.pair_by_id(pair.id).impulse_v.is_override
    assert page.editor._impulse_combo.currentText() == "1.2 kV"
    assert page.editor._impulse_source_label.text() == "Project default"


_OVERRIDE_CASES = (
    ("frequency_hz", "set_frequency_override", "100 kHz", Decimal(100_000)),
    ("impulse_v", "set_impulse_override", "2500 V", Decimal(2500)),
    ("electrode_radius_mm", "set_radius_override", "2.5", Decimal("2.5")),
    ("altitude_m", "set_altitude_override", "2000", Decimal(2000)),
    ("pollution_degree", "set_pollution_override", "1", 1),
    ("cti_or_material_group", "set_cti_override", "IIIa", "IIIa"),
    ("insulation_type", "set_insulation_override", InsulationType.REINFORCED, None),
    ("field_condition", "set_field_override", FieldCondition.HOMOGENEOUS, None),
    ("construction_type", "set_construction_override", ConstructionType.PRINTED_WIRING, None),
)


@pytest.mark.parametrize(("field", "setter", "argument", "expected"), _OVERRIDE_CASES)
def test_every_pair_override_reaches_the_effective_case(
    qtbot, pair_page, field, setter, argument, expected
) -> None:
    """Each per-pair parameter the editor can set must win over the project default."""
    from insulation_coordination.domain.enums import Provenance
    from insulation_coordination.project.resolver import resolve_effective_case

    page = pair_page
    edited, untouched = page.project.pairs[0], page.project.pairs[1]
    page.select_pair_by_id(str(edited.id))

    getattr(page.editor, setter)(argument)

    wanted = expected if expected is not None else argument
    stored = getattr(page.project.pair_by_id(edited.id), field)
    assert stored.is_override
    assert stored.value == wanted

    effective = resolve_effective_case(page.project.defaults, page.project.pair_by_id(edited.id))
    resolved = getattr(effective, field)
    assert resolved.value == wanted
    assert resolved.provenance is Provenance.PAIR_OVERRIDE

    neighbour = resolve_effective_case(page.project.defaults, page.project.pair_by_id(untouched.id))
    assert getattr(neighbour, field).provenance is Provenance.PROJECT_DEFAULT


def test_a_pair_override_is_what_the_calculation_consumes(qtbot, pair_page):
    """The engine must see each pair's own value, not the project default.

    Asserted on the effective inputs the result records rather than on the
    distances: the synthetic rule package carries one value per parameter, so most
    overrides cannot move a number here. Numeric sensitivity needs the licensed IEC
    tables, which only the private_standard tests have.
    """
    page = pair_page
    _set_valid_inputs(page)
    edited, untouched = page.project.pairs[0], page.project.pairs[1]
    page.select_pair_by_id(str(edited.id))
    page.editor.set_pollution_override("1")

    page.recalculate()

    assert page.result_by_id(edited.id).effective_inputs.pollution_degree.value == 1
    assert page.result_by_id(untouched.id).effective_inputs.pollution_degree.value == 2
