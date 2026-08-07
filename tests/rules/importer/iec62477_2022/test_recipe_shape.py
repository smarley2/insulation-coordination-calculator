import re

from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes import RECIPES

RECIPE = next(recipe for recipe in RECIPES if recipe.id == "iec62477-1-2022")

_TABLE_SELECT = re.compile(
    r"^table_select:(?P<table_id>.+)\((?P<row_mode>[a-z]+),(?P<column_mode>[a-z]+)\)$"
)


def _row_mode(base_id: str, suffix: str) -> str:
    formula = next(
        formula
        for formula in RECIPE.formulas
        if formula.expression_shape.startswith(f"table_select:{base_id}.{suffix}(")
    )
    match = _TABLE_SELECT.match(formula.expression_shape)
    assert match is not None
    return match["row_mode"]


def test_recipe_targets_the_supported_edition_only() -> None:
    assert RECIPE.standard == "IEC 62477-1"
    assert RECIPE.edition == "2022"
    assert RECIPE.expected_page_count == 522


def test_table_seven_is_split_into_four_ac_dc_specs() -> None:
    table_ids = {spec.semantic_id for spec in RECIPE.tables}
    assert table_ids >= {
        f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac",
        f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc",
        f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac",
        f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.dc",
    }


def _table_seven_spec(suffix: str, base_id: str):
    return next(
        spec for spec in RECIPE.tables if spec.semantic_id == f"{base_id}.{suffix}"
    )


def test_the_ac_and_dc_specs_of_one_quantity_read_different_row_axis_columns() -> None:
    for base_id in (ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC, ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE):
        ac_spec = _table_seven_spec("ac", base_id)
        dc_spec = _table_seven_spec("dc", base_id)
        ac_axis = next(column for column in ac_spec.columns if column.role == "axis")
        dc_axis = next(column for column in dc_spec.columns if column.role == "axis")
        assert ac_axis.source_column != dc_axis.source_column


def test_impulse_and_tov_specs_read_disjoint_data_columns() -> None:
    impulse_data = {
        column.source_column
        for suffix in ("ac", "dc")
        for column in _table_seven_spec(suffix, ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC).columns
        if column.role == "data"
    }
    tov_data = {
        column.source_column
        for suffix in ("ac", "dc")
        for column in _table_seven_spec(suffix, ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE).columns
        if column.role == "data"
    }
    assert impulse_data and tov_data
    assert impulse_data.isdisjoint(tov_data)


def test_ac_specs_declare_fewer_data_rows_than_dc_specs() -> None:
    for base_id in (ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC, ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE):
        ac_spec = _table_seven_spec("ac", base_id)
        dc_spec = _table_seven_spec("dc", base_id)
        assert ac_spec.expected_data_rows < dc_spec.expected_data_rows


def test_impulse_specs_forbid_interpolation_and_tov_specs_permit_it() -> None:
    for suffix in ("ac", "dc"):
        impulse = _table_seven_spec(suffix, ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC)
        tov = _table_seven_spec(suffix, ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE)
        assert impulse.interpolation == "none"
        assert tov.interpolation == "linear"


def test_impulse_formulas_use_ceiling_row_mode_and_tov_formulas_use_linear() -> None:
    for suffix in ("ac", "dc"):
        assert _row_mode(ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC, suffix) == "ceiling"
        assert _row_mode(ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE, suffix) == "linear"


def test_every_62477_table_searches_a_page_window() -> None:
    assert all(spec.page_search_radius == 2 for spec in RECIPE.tables)
    assert all(
        segment.page_search_radius == 2 for spec in RECIPE.tables for segment in spec.segments
    )


def test_altitude_tables_share_one_semantic_family() -> None:
    altitude = [
        spec
        for spec in RECIPE.tables
        if spec.semantic_id.startswith(ids.ALTITUDE_TEST_VOLTAGE_CORRECTION)
    ]
    assert len(altitude) == 2


def test_column_headings_are_neutral_internal_descriptions() -> None:
    for spec in RECIPE.tables:
        for column in spec.columns:
            assert column.heading == column.heading.strip()
            assert column.heading == column.heading.lower()
            assert 0 < len(column.heading) <= 60


def test_no_column_hardcodes_a_licensed_axis_value() -> None:
    """Licensed table values (e.g. Table E.2's altitude bands) must never live in this

    public recipe as a declared ``axis_value``; they must be read from the document's
    own header row instead.
    """
    for spec in RECIPE.tables:
        for column in spec.columns:
            assert column.axis_value is None

    altitude_e2 = next(
        spec
        for spec in RECIPE.tables
        if spec.semantic_id == f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e2"
    )
    altitude_data_columns = [
        column for column in altitude_e2.columns if column.role == "data"
    ]
    assert altitude_data_columns
    assert all(
        column.axis_value_source_row is not None for column in altitude_data_columns
    )
