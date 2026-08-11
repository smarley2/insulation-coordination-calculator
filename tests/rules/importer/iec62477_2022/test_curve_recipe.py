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


#: The reviewed slot inventory, stated independently of the recipe so the two can
#: disagree: (subject, voltage_basis, dvc_context, environment_context) per figure.
_EXPECTED_SLOTS: dict[str, tuple[tuple[str, str, str | None, str | None], ...]] = {
    "5": (
        ("accessible_circuit", "dc", "b", "dry"),
        ("accessible_circuit", "dc", "as", "dry"),
        ("accessible_circuit", "dc", "as", "wet_and_saltwater_wet"),
    ),
    "6": (
        ("accessible_circuit", "ac_peak", "b", "dry"),
        ("accessible_circuit", "ac_peak", "as", "dry"),
        ("accessible_circuit", "ac_peak", "as", "wet_and_saltwater_wet"),
    ),
    # Figure 7 identifies the variant as AC without specifying RMS or peak. Therefore the
    # semantic contract uses ac_unspecified and consumers must not infer a more specific
    # basis.
    "7": (
        ("conductive_accessible_part", "dc", None, None),
        ("conductive_accessible_part", "ac_unspecified", None, None),
    ),
}


def test_each_figure_declares_its_exact_slot_inventory() -> None:
    declared = {
        spec.figure: tuple(
            (
                selector.subject,
                selector.voltage_basis,
                selector.dvc_context,
                selector.environment_context,
            )
            for selector in spec.variant_slots
        )
        for spec in CURVES
    }
    assert declared == _EXPECTED_SLOTS


def test_recipe_exposes_curves_tuple() -> None:
    assert isinstance(RECIPE.curves, tuple)
    assert len(RECIPE.curves) == 3
