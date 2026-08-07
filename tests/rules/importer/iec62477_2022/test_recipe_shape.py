from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes import RECIPES

RECIPE = next(recipe for recipe in RECIPES if recipe.id == "iec62477-1-2022")


def test_recipe_targets_the_supported_edition_only() -> None:
    assert RECIPE.standard == "IEC 62477-1"
    assert RECIPE.edition == "2022"
    assert RECIPE.expected_page_count == 522


def test_table_seven_is_split_into_impulse_and_tov() -> None:
    table_ids = {spec.semantic_id for spec in RECIPE.tables}
    assert ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC in table_ids
    assert ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE in table_ids


def test_the_two_table_seven_specs_read_disjoint_source_columns() -> None:
    impulse, tov = (
        next(spec for spec in RECIPE.tables if spec.semantic_id == semantic_id)
        for semantic_id in (
            ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
            ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE,
        )
    )
    impulse_data = {
        column.source_column for column in impulse.columns if column.role == "data"
    }
    tov_data = {column.source_column for column in tov.columns if column.role == "data"}
    assert impulse_data and tov_data
    assert impulse_data.isdisjoint(tov_data)


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
