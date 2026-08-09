"""IEC 62477-1:2022 curve recipe structure: locators only, no licensed content."""

from __future__ import annotations

from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import RECIPE
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.curves import CURVES


def test_recipe_declares_curve_specs() -> None:
    assert RECIPE.curves == CURVES


def test_curve_specs_cover_figures_five_to_seven_on_pages_54_to_56() -> None:
    figures = tuple(spec.figure for spec in CURVES)
    assert figures == ("5", "6", "7")
    pages = tuple(spec.page_number for spec in CURVES)
    assert pages == (54, 55, 56)


def test_curve_specs_share_one_semantic_id_and_log_axes() -> None:
    assert {spec.semantic_id for spec in CURVES} == {"iec62477_2022.dvc.fault_time_voltage"}
    for spec in CURVES:
        assert spec.x_scale == "log10"
        assert spec.y_scale == "log10"
        assert spec.variant_slots
        assert spec.permitted_segment_types
        assert spec.permitted_interpolations


def test_curve_specs_declare_one_exact_semantic_role_per_figure() -> None:
    selectors = tuple(spec.variant_slots for spec in CURVES)
    assert all(len(slots) == 1 for slots in selectors)
    figure5, figure6, figure7 = (slots[0] for slots in selectors)
    assert (figure5.subject, figure5.voltage_basis) == ("accessible_circuit", "ac_rms")
    assert (figure6.subject, figure6.voltage_basis) == ("accessible_circuit", "dc")
    assert figure5.dvc_context is not None and figure5.environment_context is not None
    assert figure6.dvc_context is not None and figure6.environment_context is not None
    assert (figure7.subject, figure7.voltage_basis) == (
        "conductive_accessible_part",
        "ac_peak",
    )
    assert figure7.dvc_context is None and figure7.environment_context is None


def test_recipe_exposes_curves_tuple() -> None:
    assert isinstance(RECIPE.curves, tuple)
    assert len(RECIPE.curves) == 3
