from decimal import Decimal
from typing import Literal

from insulation_coordination.rules.importer.identify import (
    FormulaAuditSpec,
    TableAuditSpec,
    TableColumnSpec,
    TableSegmentSpec,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

ColumnRole = Literal["axis", "data", "context"]

# Table 7's raw grid, shared by the impulse and TOV specs below.
_TABLE_7_PAGE = 63
_TABLE_7_CLAUSE = "4.4.7.1.7"
_TABLE_7_RAW_ROWS = 13
_TABLE_7_RAW_COLUMNS = 7
_TABLE_7_BBOX = (70.8, 326.2, 524.5, 629.5)
_TABLE_7_HEADER_ROWS = (0, 1, 2, 3, 4)
_TABLE_7_DATA_ROWS = tuple(range(5, 12))
_TABLE_7_FOOTNOTE_ROWS = (12,)


def _columns(
    *items: tuple[str, str, int, ColumnRole, str],
) -> tuple[TableColumnSpec, ...]:
    return tuple(
        TableColumnSpec(
            semantic_id=semantic_id,
            heading=heading,
            source_column=source_column,
            role=role,
            unit=unit,
        )
        for semantic_id, heading, source_column, role, unit in items
    )


#: Table E.2's data columns, physically ordered 2000/1000/500/200 m then the 0 m axis
#: column; the column axis must be strictly increasing, so the logical column order
#: (and matching ``source_columns`` on the segment below) runs ascending by altitude.
_ALTITUDE_BAND_SOURCE_COLUMNS = (3, 2, 1, 0, 4)


def _altitude_band_columns() -> tuple[TableColumnSpec, ...]:
    """The four corrected-voltage columns of Table E.2, plus the reference (0 m) axis."""
    columns = _columns(
        ("corrected_impulse_200m_kv", "corrected impulse withstand at 200 m", 3, "data", "kV"),
        ("corrected_impulse_500m_kv", "corrected impulse withstand at 500 m", 2, "data", "kV"),
        ("corrected_impulse_1000m_kv", "corrected impulse withstand at 1000 m", 1, "data", "kV"),
        ("corrected_impulse_2000m_kv", "corrected impulse withstand at 2000 m", 0, "data", "kV"),
        (
            "reference_impulse_withstand_kv",
            "reference impulse withstand at sea level",
            4,
            "axis",
            "kV",
        ),
    )
    altitudes: tuple[Decimal | None, ...] = (
        Decimal(200),
        Decimal(500),
        Decimal(1000),
        Decimal(2000),
        None,
    )
    return tuple(
        column.model_copy(update={"axis_value": altitude})
        for column, altitude in zip(columns, altitudes, strict=True)
    )


TABLES: tuple[TableAuditSpec, ...] = (
    TableAuditSpec(
        semantic_id=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
        source_table="7",
        title_anchor="Table 7",
        page_number=_TABLE_7_PAGE,
        clause=_TABLE_7_CLAUSE,
        target_unit="V",
        interpolation="none",
        page_search_radius=2,
        expected_raw_rows=_TABLE_7_RAW_ROWS,
        expected_raw_columns=5,
        expected_bbox=_TABLE_7_BBOX,
        data_strategy="rectangle",
        data_row_start=5,
        data_column_start=0,
        expected_data_rows=7,
        expected_data_columns=5,
        row_axis_id="system_voltage_v",
        row_axis_unit="V",
        column_axis_id="overvoltage_category",
        column_axis_unit="1",
        allowed_suffixes=("c",),
        assertions=("strictly_increasing_axes", "raw_value_correspondence"),
        segments=(
            TableSegmentSpec(
                id="table-7-impulse",
                page_number=_TABLE_7_PAGE,
                title_anchor="Table 7",
                expected_raw_rows=_TABLE_7_RAW_ROWS,
                expected_raw_columns=_TABLE_7_RAW_COLUMNS,
                expected_bbox=_TABLE_7_BBOX,
                source_columns=(1, 2, 3, 4, 5),
                header_rows=_TABLE_7_HEADER_ROWS,
                data_rows=_TABLE_7_DATA_ROWS,
                footnote_rows=_TABLE_7_FOOTNOTE_ROWS,
                page_search_radius=2,
            ),
        ),
        columns=_columns(
            ("system_voltage_v", "system voltage band upper bound", 1, "axis", "V"),
            ("impulse_ovc_1_v", "overvoltage category 1", 2, "data", "V"),
            ("impulse_ovc_2_v", "overvoltage category 2", 3, "data", "V"),
            ("impulse_ovc_3_v", "overvoltage category 3", 4, "data", "V"),
            ("impulse_ovc_4_v", "overvoltage category 4", 5, "data", "V"),
        ),
    ),
    TableAuditSpec(
        semantic_id=ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE,
        source_table="7",
        title_anchor="Table 7",
        page_number=_TABLE_7_PAGE,
        clause=_TABLE_7_CLAUSE,
        target_unit="V",
        interpolation="none",
        page_search_radius=2,
        expected_raw_rows=_TABLE_7_RAW_ROWS,
        expected_raw_columns=2,
        expected_bbox=_TABLE_7_BBOX,
        data_strategy="rectangle",
        data_row_start=5,
        data_column_start=0,
        expected_data_rows=7,
        expected_data_columns=2,
        row_axis_id="system_voltage_v",
        row_axis_unit="V",
        column_axis_id="tov_branch",
        column_axis_unit="1",
        allowed_suffixes=("c",),
        assertions=("strictly_increasing_axes", "raw_value_correspondence"),
        segments=(
            TableSegmentSpec(
                id="table-7-tov",
                page_number=_TABLE_7_PAGE,
                title_anchor="Table 7",
                expected_raw_rows=_TABLE_7_RAW_ROWS,
                expected_raw_columns=_TABLE_7_RAW_COLUMNS,
                expected_bbox=_TABLE_7_BBOX,
                source_columns=(1, 6),
                header_rows=_TABLE_7_HEADER_ROWS,
                data_rows=_TABLE_7_DATA_ROWS,
                footnote_rows=_TABLE_7_FOOTNOTE_ROWS,
                page_search_radius=2,
            ),
        ),
        columns=_columns(
            ("system_voltage_v", "system voltage band upper bound", 1, "axis", "V"),
            ("temporary_overvoltage_v", "temporary overvoltage requirement", 6, "data", "V"),
        ),
    ),
    TableAuditSpec(
        semantic_id=f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e1",
        source_table="E.1",
        title_anchor="Table E.1",
        page_number=193,
        clause="Annex E",
        target_unit="1",
        interpolation="none",
        page_search_radius=2,
        expected_raw_rows=13,
        expected_raw_columns=3,
        expected_bbox=(127.6, 248.4, 467.8, 500.2),
        data_strategy="rectangle",
        data_row_start=1,
        data_column_start=0,
        expected_data_rows=11,
        expected_data_columns=2,
        row_axis_id="altitude_m",
        row_axis_unit="m",
        column_axis_id="clearance_correction_branch",
        column_axis_unit="1",
        assertions=("strictly_increasing_axes", "raw_value_correspondence"),
        segments=(
            TableSegmentSpec(
                id="table-e1",
                page_number=193,
                title_anchor="Table E.1",
                expected_raw_rows=13,
                expected_raw_columns=3,
                expected_bbox=(127.6, 248.4, 467.8, 500.2),
                header_rows=(0,),
                data_rows=tuple(range(1, 12)),
                footnote_rows=(12,),
                page_search_radius=2,
            ),
        ),
        columns=_columns(
            ("altitude_m", "altitude above sea level", 0, "axis", "m"),
            ("pressure_kpa", "reference barometric pressure", 1, "context", "kPa"),
            ("clearance_factor", "clearance multiplication factor", 2, "data", "1"),
        ),
    ),
    TableAuditSpec(
        semantic_id=f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e2",
        source_table="E.2",
        title_anchor="Table E.2",
        page_number=194,
        clause="Annex E",
        target_unit="kV",
        interpolation="none",
        page_search_radius=2,
        expected_raw_rows=22,
        expected_raw_columns=5,
        expected_bbox=(70.9, 106.8, 524.5, 558.8),
        data_strategy="rectangle",
        data_row_start=3,
        data_column_start=0,
        expected_data_rows=18,
        expected_data_columns=5,
        row_axis_id="reference_impulse_withstand_kv",
        row_axis_unit="kV",
        column_axis_id="altitude_band_m",
        column_axis_unit="m",
        assertions=("strictly_increasing_axes", "raw_value_correspondence"),
        segments=(
            TableSegmentSpec(
                id="table-e2",
                page_number=194,
                title_anchor="Table E.2",
                expected_raw_rows=22,
                expected_raw_columns=5,
                expected_bbox=(70.9, 106.8, 524.5, 558.8),
                source_columns=_ALTITUDE_BAND_SOURCE_COLUMNS,
                header_rows=(0, 1, 2),
                data_rows=tuple(range(3, 21)),
                footnote_rows=(21,),
                page_search_radius=2,
            ),
        ),
        columns=_altitude_band_columns(),
    ),
)

FORMULAS: tuple[FormulaAuditSpec, ...] = (
    FormulaAuditSpec(
        semantic_id=f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.lookup",
        unit="V",
        variables=("system_voltage_v", "overvoltage_category"),
        expression_shape=f"table_select:{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}(ceiling,exact)",
        page_number=_TABLE_7_PAGE,
        clause=_TABLE_7_CLAUSE,
        table="Table 7",
    ),
    FormulaAuditSpec(
        semantic_id=f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.lookup",
        unit="V",
        variables=("system_voltage_v", "tov_branch"),
        expression_shape=f"table_select:{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}(ceiling,exact)",
        page_number=_TABLE_7_PAGE,
        clause=_TABLE_7_CLAUSE,
        table="Table 7",
    ),
)
