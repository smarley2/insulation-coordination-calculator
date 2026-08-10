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
        assert spec.x_source_unit == "ms"
        assert spec.y_scale == "log10"
        assert spec.variant_slots
        assert spec.permitted_segment_types
        assert spec.permitted_interpolations


def test_curve_specs_declare_the_exact_eight_semantic_roles() -> None:
    selectors = tuple(spec.variant_slots for spec in CURVES)
    assert tuple(map(len, selectors)) == (3, 3, 2)
    assert all(
        selector.subject == "accessible_circuit"
        and selector.voltage_basis == basis
        and selector.dvc_context is not None
        and selector.environment_context is not None
        for slots, basis in zip(selectors[:2], ("dc", "ac_peak"), strict=True)
        for selector in slots
    )
    assert tuple(selector.voltage_basis for selector in selectors[2]) == (
        "dc",
        "ac_peak",
    )
    assert all(
        selector.subject == "conductive_accessible_part"
        and selector.dvc_context is None
        and selector.environment_context is None
        for selector in selectors[2]
    )


def test_recipe_exposes_curves_tuple() -> None:
    assert isinstance(RECIPE.curves, tuple)
    assert len(RECIPE.curves) == 3
