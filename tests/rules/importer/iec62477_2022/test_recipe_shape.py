from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes import RECIPES

RECIPE = next(recipe for recipe in RECIPES if recipe.id == "iec62477-1-2022")


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


def test_no_62477_table_permits_interpolation() -> None:
    assert all(spec.interpolation == "none" for spec in RECIPE.tables)


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
