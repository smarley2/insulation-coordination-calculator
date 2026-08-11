from typing import Literal

from insulation_coordination.rules.importer.identify import (
    BlankCellSpec,
    CompoundQuantitySpec,
    FormulaAuditSpec,
    MergedCellSpec,
    ReferenceSlotSpec,
    TableAuditSpec,
    TableColumnSpec,
    TableSegmentSpec,
    TokenGrammarSpec,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.annex_f import (
    ANNEX_F_TABLES,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.spacing import (
    SPACING_TABLES,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    VERIFICATION_TABLES,
)

ColumnRole = Literal["axis", "data", "context"]

TABLE_2 = TableAuditSpec(
    semantic_id=ids.DVC_VOLTAGE_LIMITS,
    source_table="2",
    title_anchor="Table 2",
    page_number=44,
    clause="4.4.2",
    target_unit="V",
    expected_raw_rows=8,
    expected_raw_columns=6,
    expected_bbox=(70.9, 314.5, 524.4, 663.2),
    data_strategy="rectangle",
    data_row_start=3,
    data_column_start=1,
    expected_data_rows=4,
    expected_data_columns=5,
    row_axis_id="dvc_row",
    row_axis_unit="1",
    column_axis_id="voltage_quantity",
    column_axis_unit="1",
    assertions=("raw_value_correspondence",),
    page_search_radius=2,
    merged_cells=(
        MergedCellSpec(row=0, column=0, row_span=3, inherit="down"),
        MergedCellSpec(row=0, column=1, column_span=5, inherit="right"),
        MergedCellSpec(row=1, column=1, column_span=4, inherit="right"),
        MergedCellSpec(row=3, column=4, row_span=2, inherit="down"),
        MergedCellSpec(row=3, column=5, row_span=3, inherit="down"),
        MergedCellSpec(row=5, column=4, row_span=2, inherit="down"),
    ),
    blank_cells=(
        BlankCellSpec(row=1, column=0, semantics="inherit"),
        BlankCellSpec(row=2, column=0, semantics="inherit"),
        *(BlankCellSpec(row=0, column=column, semantics="inherit") for column in range(2, 6)),
        *(BlankCellSpec(row=1, column=column, semantics="inherit") for column in range(2, 5)),
        BlankCellSpec(row=4, column=4, semantics="inherit"),
        BlankCellSpec(row=4, column=5, semantics="inherit"),
        BlankCellSpec(row=5, column=5, semantics="inherit"),
        BlankCellSpec(row=6, column=4, semantics="inherit"),
        BlankCellSpec(row=6, column=5, semantics="not_applicable"),
        *(BlankCellSpec(row=7, column=column, semantics="structural") for column in range(1, 6)),
    ),
    reference_slots=(
        ReferenceSlotSpec(
            row=3,
            column=5,
            target_rule_id=ids.DVC_FAULT_TIME_VOLTAGE,
            target_kind="curve",
        ),
        ReferenceSlotSpec(
            row=5,
            column=4,
            target_rule_id=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
            target_kind="table",
        ),
    ),
    decision_route_ids=(
        ids.DVC_VOLTAGE_LIMITS,
        f"{ids.DVC_VOLTAGE_LIMITS}.fault_time_reference",
        f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference",
        f"{ids.DVC_VOLTAGE_LIMITS}.not_applicable",
    ),
)

# Table 7's raw grid, shared by the four AC/DC impulse and TOV specs below. Column 0 is
# the AC system voltage axis, column 1 is the DC system voltage axis: two parallel row
# axes for the same physical rows, selected by supply type. The last data row (grid row
# 12, physical index 11) is DC-only -- its column 0 cell holds a not-applicable marker,
# not a number -- so the AC specs exclude it from their data rows entirely rather than
# resolve a value that does not apply to an AC supply.
_TABLE_7_PAGE = 63
_TABLE_7_CLAUSE = "4.4.7.1.7"
_TABLE_7_RAW_ROWS = 13
_TABLE_7_RAW_COLUMNS = 7
_TABLE_7_BBOX = (70.8, 326.2, 524.5, 629.5)
_TABLE_7_HEADER_ROWS = (0, 1, 2, 3, 4)
_TABLE_7_DATA_ROWS_DC = tuple(range(5, 12))
_TABLE_7_DATA_ROWS_AC = _TABLE_7_DATA_ROWS_DC[:-1]
_TABLE_7_FOOTNOTE_ROWS = (12,)
#: Declared independently of the ``data_rows`` tuples above so the extraction-time row
#: count check (``expected_data_rows``) is not a tautology against its own input.
_TABLE_7_EXPECTED_DATA_ROWS_AC = 6
_TABLE_7_EXPECTED_DATA_ROWS_DC = 7
#: The DC row axis cell carries a footnote marker on the DC-only row; the AC axis and
#: the shared data columns carry none of the rows either spec actually reads.
_TABLE_7_AC_SUFFIXES: tuple[str, ...] = ()
_TABLE_7_DC_SUFFIXES: tuple[str, ...] = ("c",)

_IMPULSE_DATA_COLUMNS: tuple[tuple[str, str, int, ColumnRole, str], ...] = (
    ("impulse_ovc_1_v", "overvoltage category 1", 2, "data", "V"),
    ("impulse_ovc_2_v", "overvoltage category 2", 3, "data", "V"),
    ("impulse_ovc_3_v", "overvoltage category 3", 4, "data", "V"),
    ("impulse_ovc_4_v", "overvoltage category 4", 5, "data", "V"),
)
_TOV_DATA_COLUMNS: tuple[tuple[str, str, int, ColumnRole, str], ...] = (
    ("temporary_overvoltage_v", "temporary overvoltage requirement", 6, "data", "V"),
)


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


def _table_7_ac_dc_pair(
    *,
    impulse_or_tov_id: str,
    axis_column_axis_id: str,
    axis_column_axis_unit: str,
    data_items: tuple[tuple[str, str, int, ColumnRole, str], ...],
    expected_data_columns: int,
    interpolation: Literal["none", "linear"],
    compound_component_ids: tuple[str, ...] = (),
) -> tuple[TableAuditSpec, TableAuditSpec]:
    """One AC spec and one DC spec reading Table 7's two parallel row axes.

    Both read the same data columns; only the row-axis source column and the set of
    data rows differ, per the AC/DC split. System voltage interpolation is not
    permitted for the impulse lookup but is permitted for the TOV lookup (4.4.7.1.7);
    the matching ``FormulaAuditSpec`` row mode is declared by the caller.
    """
    specs = []
    for supply, axis_source_column, data_rows, allowed_suffixes, expected_data_rows in (
        ("ac", 0, _TABLE_7_DATA_ROWS_AC, _TABLE_7_AC_SUFFIXES, _TABLE_7_EXPECTED_DATA_ROWS_AC),
        ("dc", 1, _TABLE_7_DATA_ROWS_DC, _TABLE_7_DC_SUFFIXES, _TABLE_7_EXPECTED_DATA_ROWS_DC),
    ):
        axis_semantic_id = f"system_voltage_{supply}_v"
        source_columns = (axis_source_column, *(item[2] for item in data_items))
        columns = _columns(
            (
                axis_semantic_id,
                f"{supply} system voltage band upper bound",
                axis_source_column,
                "axis",
                "V",
            ),
            *data_items,
        )
        if compound_component_ids:
            compound = CompoundQuantitySpec(
                component_ids=compound_component_ids,
                formula_candidates=tuple(
                    (
                        component_id,
                        f"{impulse_or_tov_id}.{component_id}.lookup",
                    )
                    for component_id in compound_component_ids
                ),
            )
            columns = tuple(
                column.model_copy(
                    update={
                        "compound_quantity": compound,
                        "projected_component_id": supply,
                    }
                )
                if column.role == "data"
                else column
                for column in columns
            )
        specs.append(
            TableAuditSpec(
                semantic_id=f"{impulse_or_tov_id}.{supply}",
                source_table="7",
                title_anchor="Table 7",
                page_number=_TABLE_7_PAGE,
                clause=_TABLE_7_CLAUSE,
                target_unit="V",
                interpolation=interpolation,
                page_search_radius=2,
                expected_raw_rows=_TABLE_7_RAW_ROWS,
                expected_raw_columns=len(source_columns),
                expected_bbox=_TABLE_7_BBOX,
                data_strategy="rectangle",
                data_row_start=5,
                data_column_start=0,
                expected_data_rows=expected_data_rows,
                expected_data_columns=expected_data_columns,
                row_axis_id=axis_semantic_id,
                row_axis_unit="V",
                column_axis_id=axis_column_axis_id,
                column_axis_unit=axis_column_axis_unit,
                allowed_suffixes=allowed_suffixes,
                assertions=("strictly_increasing_axes", "raw_value_correspondence"),
                segments=(
                    TableSegmentSpec(
                        id=f"table-7-{impulse_or_tov_id.rsplit('.', 1)[-1]}-{supply}",
                        page_number=_TABLE_7_PAGE,
                        title_anchor="Table 7",
                        expected_raw_rows=_TABLE_7_RAW_ROWS,
                        expected_raw_columns=_TABLE_7_RAW_COLUMNS,
                        expected_bbox=_TABLE_7_BBOX,
                        source_columns=source_columns,
                        header_rows=_TABLE_7_HEADER_ROWS,
                        data_rows=data_rows,
                        footnote_rows=_TABLE_7_FOOTNOTE_ROWS,
                        page_search_radius=2,
                    ),
                ),
                columns=columns,
            )
        )
    return specs[0], specs[1]


_IMPULSE_AC, _IMPULSE_DC = _table_7_ac_dc_pair(
    impulse_or_tov_id=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
    axis_column_axis_id="overvoltage_category",
    axis_column_axis_unit="1",
    data_items=_IMPULSE_DATA_COLUMNS,
    expected_data_columns=5,
    interpolation="none",
)
_TOV_AC, _TOV_DC = _table_7_ac_dc_pair(
    impulse_or_tov_id=ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE,
    axis_column_axis_id="tov_branch",
    axis_column_axis_unit="1",
    data_items=_TOV_DATA_COLUMNS,
    expected_data_columns=2,
    interpolation="linear",
    compound_component_ids=("ac", "dc"),
)

#: Table E.2's four altitude-band data columns are physically ordered descending by
#: altitude, with the reference axis column last; the column axis must be strictly
#: increasing, so the logical column order (and matching ``source_columns`` on the
#: segment below) runs ascending instead.
_ALTITUDE_BAND_SOURCE_COLUMNS = (3, 2, 1, 0, 4)
#: Physical row (within the E.2 segment) whose cells carry the four altitude bands'
#: numeric header values; structural, not a licensed value.
_ALTITUDE_BAND_HEADER_ROW = 2


def _altitude_band_columns() -> tuple[TableColumnSpec, ...]:
    """The four corrected-voltage columns of Table E.2, plus the reference altitude axis.

    The altitude band values are licensed table content, so they are read from the
    document's own header row via ``axis_value_source_row`` instead of being declared
    here.
    """
    columns = _columns(
        ("corrected_impulse_band1_kv", "corrected impulse withstand at band 1", 3, "data", "kV"),
        ("corrected_impulse_band2_kv", "corrected impulse withstand at band 2", 2, "data", "kV"),
        ("corrected_impulse_band3_kv", "corrected impulse withstand at band 3", 1, "data", "kV"),
        ("corrected_impulse_band4_kv", "corrected impulse withstand at band 4", 0, "data", "kV"),
        (
            "reference_impulse_withstand_kv",
            "reference impulse withstand at sea level",
            4,
            "axis",
            "kV",
        ),
    )
    return tuple(
        column
        if column.role == "axis"
        else column.model_copy(update={"axis_value_source_row": _ALTITUDE_BAND_HEADER_ROW})
        for column in columns
    )


#: Table 3 has three semantic DVC rows and six protection-context columns inside
#: a physical 9x7 grid. Physical rows 5 and 7 retain wrapped source continuations;
#: row 8 retains source notes. Public identifiers are positional and neutral.
TABLE_3 = TableAuditSpec(
    semantic_id=ids.DVC_PROTECTION_MATRIX,
    source_table="3",
    title_anchor="Table 3",
    page_number=45,
    clause="4.4.3",
    target_unit="1",
    expected_raw_rows=9,
    expected_raw_columns=7,
    expected_bbox=(71.0, 265.3, 524.3, 744.2),
    data_strategy="rectangle",
    data_row_start=None,
    data_column_start=None,
    expected_data_rows=3,
    expected_data_columns=6,
    row_axis_id="dvc",
    row_axis_unit="1",
    column_axis_id="protection_context",
    column_axis_unit="1",
    assertions=("complete_grid", "raw_value_correspondence"),
    page_search_radius=2,
    segments=(
        TableSegmentSpec(
            id="table-3",
            page_number=45,
            title_anchor="Table 3",
            expected_raw_rows=9,
            expected_raw_columns=7,
            expected_bbox=(71.0, 265.3, 524.3, 744.2),
            source_columns=tuple(range(7)),
            header_rows=(0, 1, 2),
            data_rows=(3, 4, 6),
            note_rows=(5, 7),
            footnote_rows=(8,),
            page_search_radius=2,
        ),
    ),
    columns=(
        TableColumnSpec(
            semantic_id="dvc_source",
            heading="dvc source row",
            source_column=0,
            role="context",
            unit="1",
        ),
        *(
            TableColumnSpec(
                semantic_id=f"protection-context-{column}",
                heading=f"protection context {column}",
                source_column=column,
                role="data",
                unit="1",
            )
            for column in range(1, 7)
        ),
    ),
    token_grammar=TokenGrammarSpec(
        target="categorical",
        tokens=(
            ("none", "none"),
            ("basic", "basic_protection"),
            ("enhanced", "enhanced_protection"),
        ),
        match="prefix",
    ),
    decision_route_ids=(ids.DVC_PROTECTION_MATRIX,),
)

TABLES: tuple[TableAuditSpec, ...] = (
    TABLE_2,
    TABLE_3,
    _IMPULSE_AC,
    _IMPULSE_DC,
    _TOV_AC,
    _TOV_DC,
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
            ("pressure_kpa", "air pressure at this altitude", 1, "context", "kPa"),
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
    *SPACING_TABLES,
    *ANNEX_F_TABLES,
    *VERIFICATION_TABLES,
)

FORMULAS: tuple[FormulaAuditSpec, ...] = (
    FormulaAuditSpec(
        semantic_id=f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac.lookup",
        unit="V",
        variables=("system_voltage_ac_v", "overvoltage_category"),
        expression_shape=(
            f"table_select:{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac(ceiling,exact)"
        ),
        page_number=_TABLE_7_PAGE,
        clause=_TABLE_7_CLAUSE,
        table="Table 7",
    ),
    FormulaAuditSpec(
        semantic_id=f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc.lookup",
        unit="V",
        variables=("system_voltage_dc_v", "overvoltage_category"),
        expression_shape=(
            f"table_select:{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc(ceiling,exact)"
        ),
        page_number=_TABLE_7_PAGE,
        clause=_TABLE_7_CLAUSE,
        table="Table 7",
    ),
    FormulaAuditSpec(
        semantic_id=f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac.lookup",
        unit="V",
        variables=("system_voltage_ac_v", "tov_branch"),
        expression_shape=f"table_select:{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac(linear,exact)",
        page_number=_TABLE_7_PAGE,
        clause=_TABLE_7_CLAUSE,
        table="Table 7",
    ),
    FormulaAuditSpec(
        semantic_id=f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.dc.lookup",
        unit="V",
        variables=("system_voltage_dc_v", "tov_branch"),
        expression_shape=f"table_select:{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.dc(linear,exact)",
        page_number=_TABLE_7_PAGE,
        clause=_TABLE_7_CLAUSE,
        table="Table 7",
    ),
)
