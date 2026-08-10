"""IEC 62477-1:2022 clearance and creepage table recipes. Layout facts only.

Bounding boxes, row and column counts, and header/data/note row indexes are measured
from the maintained printing. Column headings are neutral descriptions written here; the
pollution-degree and material-group axis values belong to the source tables and are read
from their own header rows at import time.
"""

from decimal import Decimal
from typing import Literal

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.importer.identify import (
    BlankCellSpec,
    CrossStandardAxisMatchSpec,
    CrossStandardCheckSpec,
    MergedCellSpec,
    TableAuditSpec,
    TableColumnSpec,
    TableSegmentSpec,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

_TABLE_8_PAGE = 68
_TABLE_8_CLAUSE = "4.4.7.4"
_TABLE_8_RAW_ROWS = 15
_TABLE_8_RAW_COLUMNS = 7
_TABLE_8_BBOX = (70.9, 144.8, 524.6, 618.4)
#: Grid row 0 numbers the columns, row 1 carries the merged titles, row 2 spans the
#: pollution-degree group, and row 3 holds the pollution-degree values themselves.
_TABLE_8_HEADER_ROWS = (0, 1, 2, 3)
_TABLE_8_DATA_ROWS = tuple(range(4, 14))
_TABLE_8_NOTE_ROWS = (14,)
#: Declared independently of ``_TABLE_8_DATA_ROWS`` so the extraction-time row count check
#: is not a tautology against its own input.
_TABLE_8_EXPECTED_DATA_ROWS = 10
#: Physical row whose cells carry the pollution-degree values. Structural, not a value.
_TABLE_8_POLLUTION_DEGREE_HEADER_ROW = 3
#: Footnote marker characters the data and correspondence cells carry.
_TABLE_8_SUFFIXES = ("b", "c", "e")

#: The three correspondence titles span the header rows downward; the clearance title and
#: the pollution-degree group span their row to the right.
_TABLE_8_MERGED_CELLS = (
    MergedCellSpec(row=1, column=0, row_span=3, inherit="down"),
    MergedCellSpec(row=1, column=1, row_span=3, inherit="down"),
    MergedCellSpec(row=1, column=2, row_span=3, inherit="down"),
    MergedCellSpec(row=1, column=3, column_span=4, inherit="right"),
    MergedCellSpec(row=2, column=3, column_span=4, inherit="right"),
)

#: The clearance columns print a requirement only where it changes: a cell left blank
#: repeats the last printed value in its own column, which is why every clearance column
#: sets ``fill_down``. These coordinates are recorded as ``inherit`` rather than left
#: unclassified because the reading is checked, not assumed: after filling down, no row
#: decreases across the pollution degrees, which both the public and the private tests
#: assert. A blank at any other coordinate stays unclassified, so extraction blocks and
#: the maintainer decides in the Rule Manager.
_TABLE_8_BLANK_CELLS = (
    #: Header cells covered by the merges above.
    *(BlankCellSpec(row=1, column=column, semantics="inherit") for column in range(4, 7)),
    *(BlankCellSpec(row=2, column=column, semantics="inherit") for column in range(3)),
    *(BlankCellSpec(row=2, column=column, semantics="inherit") for column in range(4, 7)),
    *(BlankCellSpec(row=3, column=column, semantics="inherit") for column in range(3)),
    #: The note row carries its text in the first column only.
    *(BlankCellSpec(row=14, column=column, semantics="structural") for column in range(1, 7)),
    BlankCellSpec(row=5, column=4, semantics="inherit"),
    BlankCellSpec(row=5, column=5, semantics="inherit"),
    BlankCellSpec(row=5, column=6, semantics="inherit"),
    BlankCellSpec(row=6, column=4, semantics="inherit"),
    BlankCellSpec(row=6, column=5, semantics="inherit"),
    BlankCellSpec(row=6, column=6, semantics="inherit"),
    BlankCellSpec(row=7, column=5, semantics="inherit"),
    BlankCellSpec(row=7, column=6, semantics="inherit"),
    BlankCellSpec(row=8, column=6, semantics="inherit"),
)


def _table_8_columns() -> tuple[TableColumnSpec, ...]:
    """The impulse row axis, two voltage correspondence columns, and four clearances.

    The two voltage columns are context: they belong to the same physical rows but carry
    volts, not the millimetres this table projects.
    """
    axis = TableColumnSpec(
        semantic_id="impulse_withstand_voltage_v",
        heading="impulse withstand voltage entering this table",
        source_column=0,
        role="axis",
        unit="V",
    )
    correspondence = tuple(
        TableColumnSpec(
            semantic_id=semantic_id,
            heading=heading,
            source_column=source_column,
            role="context",
            unit="V",
        )
        for semantic_id, heading, source_column in (
            ("temporary_overvoltage_v", "temporary overvoltage on the same row", 1),
            ("working_voltage_v", "working voltage on the same row", 2),
        )
    )
    clearances = tuple(
        TableColumnSpec(
            semantic_id=f"clearance_pollution_degree_{ordinal}_mm",
            heading=f"clearance for pollution degree column {ordinal}",
            source_column=source_column,
            role="data",
            unit="mm",
            axis_value_source_row=_TABLE_8_POLLUTION_DEGREE_HEADER_ROW,
            fill_down=True,
        )
        for ordinal, source_column in enumerate(range(3, 7), start=1)
    )
    return (axis, *correspondence, *clearances)


TABLE_8 = TableAuditSpec(
    semantic_id=ids.CLEARANCE_REQUIREMENTS,
    source_table="8",
    title_anchor="Table 8",
    page_number=_TABLE_8_PAGE,
    clause=_TABLE_8_CLAUSE,
    target_unit="mm",
    interpolation="none",
    page_search_radius=2,
    expected_raw_rows=_TABLE_8_RAW_ROWS,
    expected_raw_columns=_TABLE_8_RAW_COLUMNS,
    expected_bbox=_TABLE_8_BBOX,
    data_strategy="rectangle",
    data_row_start=4,
    data_column_start=0,
    expected_data_rows=_TABLE_8_EXPECTED_DATA_ROWS,
    expected_data_columns=5,
    row_axis_id="impulse_withstand_voltage_v",
    row_axis_unit="V",
    column_axis_id="pollution_degree",
    column_axis_unit="1",
    allowed_suffixes=_TABLE_8_SUFFIXES,
    assertions=("strictly_increasing_axes", "raw_value_correspondence"),
    segments=(
        TableSegmentSpec(
            id="table-8",
            page_number=_TABLE_8_PAGE,
            title_anchor="Table 8",
            expected_raw_rows=_TABLE_8_RAW_ROWS,
            expected_raw_columns=_TABLE_8_RAW_COLUMNS,
            expected_bbox=_TABLE_8_BBOX,
            source_columns=tuple(range(_TABLE_8_RAW_COLUMNS)),
            header_rows=_TABLE_8_HEADER_ROWS,
            data_rows=_TABLE_8_DATA_ROWS,
            note_rows=_TABLE_8_NOTE_ROWS,
            page_search_radius=2,
        ),
    ),
    columns=_table_8_columns(),
    merged_cells=_TABLE_8_MERGED_CELLS,
    blank_cells=_TABLE_8_BLANK_CELLS,
)

_TABLE_9_PAGE = 71
_TABLE_9_CLAUSE = "4.4.7.5"
#: Table 9 rules one box around several working-voltage lines, so the ruling lines cannot
#: separate its logical rows: with the default strategy every cell arrives holding three or
#: six stacked values. Read with one row per text line instead, which gives one grid row per
#: working voltage at the cost of a taller grid whose blank spacer lines carry nothing.
_TABLE_9_ROW_STRATEGY: Literal["lines", "text"] = "text"
_TABLE_9_RAW_ROWS = 96
_TABLE_9_RAW_COLUMNS = 12
_TABLE_9_BBOX = (71.3, 112.6, 524.3, 775.9)
_TABLE_9_HEADER_ROWS = (0, 2, 3, 4, 5, 6, 7, 8, 9, 11)
#: One grid row per printed working voltage.
_TABLE_9_DATA_ROWS = (
    13, 15, 17, 19, 21, 23, 25, 27, 29, 32, 34, 38, 40, 42, 43, 45, 49, 51, 54, 57, 59,
    61, 63, 65, 67, 69, 71, 73, 75, 77,
)
#: The printed-wiring columns carry values only over the lower part of the axis. Above
#: that, one row holds a footnote marker in place of a value and the remaining rows are
#: empty, so the printed-wiring spec stops where its data stops rather than classifying
#: nine rows of absent values. The footnote that states the limit stays in the raw grid.
_TABLE_9_PRINTED_WIRING_DATA_ROWS = _TABLE_9_DATA_ROWS[:21]
_TABLE_9_EXPECTED_DATA_ROWS = 30
_TABLE_9_EXPECTED_PRINTED_WIRING_DATA_ROWS = 21
#: Columns 7 and 11 hold no data on any row: they are artifacts of the merged header spans,
#: so no spec reads them.
_TABLE_9_PRINTED_WIRING_COLUMNS = (0, 1, 2)
_TABLE_9_OTHER_COLUMNS = (0, 3, 4, 5, 6, 8, 9, 10)
_TABLE_9_FOOTNOTE_ROWS = tuple(
    row
    for row in range(_TABLE_9_RAW_ROWS)
    if row not in (*_TABLE_9_HEADER_ROWS, *_TABLE_9_DATA_ROWS)
)
_TABLE_9_SUFFIXES = ("b", "c", "d", "e")
_WORKING_VOLTAGE_AXIS = "working_voltage_v"


def _table_9_spec(
    *,
    semantic_id: str,
    segment_id: str,
    source_columns: tuple[int, ...],
    data_rows: tuple[int, ...],
    expected_data_rows: int,
    data_items: tuple[tuple[str, str, int], ...],
    column_axis_id: str,
) -> TableAuditSpec:
    """One creepage lookup over Table 9's shared grid.

    Table 9 answers a four-way question -- insulator construction, pollution degree,
    insulating material group, and working voltage -- which does not fit one table's two
    axes. Each spec therefore fixes the construction and reads the material groups of one
    pollution degree as its column axis, the same way the Table 7 pair fixes AC or DC.
    """
    columns = (
        TableColumnSpec(
            semantic_id=_WORKING_VOLTAGE_AXIS,
            heading="working voltage entering this table",
            source_column=0,
            role="axis",
            unit="V",
        ),
        *(
            TableColumnSpec(
                semantic_id=column_semantic_id,
                heading=heading,
                source_column=source_column,
                role="data",
                unit="mm",
            )
            for column_semantic_id, heading, source_column in data_items
        ),
    )
    return TableAuditSpec(
        semantic_id=semantic_id,
        source_table="9",
        title_anchor="Table 9",
        page_number=_TABLE_9_PAGE,
        clause=_TABLE_9_CLAUSE,
        target_unit="mm",
        #: Table 9 permits interpolation, unlike Tables 7 and 8.
        interpolation="linear",
        page_search_radius=2,
        expected_raw_rows=_TABLE_9_RAW_ROWS,
        expected_raw_columns=len(source_columns),
        expected_bbox=_TABLE_9_BBOX,
        data_strategy="rectangle",
        data_row_start=_TABLE_9_DATA_ROWS[0],
        data_column_start=0,
        expected_data_rows=expected_data_rows,
        expected_data_columns=len(data_items) + 1,
        row_axis_id=_WORKING_VOLTAGE_AXIS,
        row_axis_unit="V",
        column_axis_id=column_axis_id,
        column_axis_unit="1",
        allowed_suffixes=_TABLE_9_SUFFIXES,
        allowed_qualifiers=("up_to",),
        assertions=("strictly_increasing_axes", "raw_value_correspondence"),
        segments=(
            TableSegmentSpec(
                id=segment_id,
                page_number=_TABLE_9_PAGE,
                title_anchor="Table 9",
                expected_raw_rows=_TABLE_9_RAW_ROWS,
                expected_raw_columns=_TABLE_9_RAW_COLUMNS,
                expected_bbox=_TABLE_9_BBOX,
                source_columns=source_columns,
                header_rows=_TABLE_9_HEADER_ROWS,
                data_rows=data_rows,
                footnote_rows=_TABLE_9_FOOTNOTE_ROWS,
                page_search_radius=2,
                row_strategy=_TABLE_9_ROW_STRATEGY,
            ),
        ),
        columns=columns,
    )


TABLE_9_PRINTED_WIRING = _table_9_spec(
    semantic_id=f"{ids.CREEPAGE_REQUIREMENTS}.printed_wiring",
    segment_id="table-9-printed-wiring",
    source_columns=_TABLE_9_PRINTED_WIRING_COLUMNS,
    data_rows=_TABLE_9_PRINTED_WIRING_DATA_ROWS,
    expected_data_rows=_TABLE_9_EXPECTED_PRINTED_WIRING_DATA_ROWS,
    data_items=(
        ("printed_wiring_pollution_1_mm", "printed wiring pollution degree 1", 1),
        ("printed_wiring_pollution_2_mm", "printed wiring pollution degree 2", 2),
    ),
    column_axis_id="printed_wiring_pollution_branch",
)

TABLE_9_OTHER_INSULATORS = _table_9_spec(
    semantic_id=f"{ids.CREEPAGE_REQUIREMENTS}.other_insulators",
    segment_id="table-9-other-insulators",
    source_columns=_TABLE_9_OTHER_COLUMNS,
    data_rows=_TABLE_9_DATA_ROWS,
    expected_data_rows=_TABLE_9_EXPECTED_DATA_ROWS,
    data_items=(
        ("other_pollution_1_all_groups_mm", "other insulators pollution degree 1", 3),
        ("other_pollution_2_group_1_mm", "other insulators pollution degree 2 group 1", 4),
        ("other_pollution_2_group_2_mm", "other insulators pollution degree 2 group 2", 5),
        ("other_pollution_2_group_3_mm", "other insulators pollution degree 2 group 3", 6),
        ("other_pollution_3_group_1_mm", "other insulators pollution degree 3 group 1", 8),
        ("other_pollution_3_group_2_mm", "other insulators pollution degree 3 group 2", 9),
        ("other_pollution_3_group_3_mm", "other insulators pollution degree 3 group 3", 10),
    ),
    column_axis_id="other_insulator_pollution_material_branch",
)

SPACING_TABLES: tuple[TableAuditSpec, ...] = (
    TABLE_8,
    TABLE_9_PRINTED_WIRING,
    TABLE_9_OTHER_INSULATORS,
)


def _aligned_cell_map(
    *,
    rows: int,
    column_pairs: tuple[tuple[str, str], ...],
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Pair two grids of the same shape cell by cell, row order against row order.

    Both Annex F grids and their IEC 60664-4 counterparts declare the same number of data
    rows over the same quantity, so position is the correspondence. If a printing ever
    ordered them differently the comparison reports divergences rather than a mapping,
    which is the outcome a maintainer needs to see.
    """
    cell_map = tuple(
        (f"{row}/{source_column}", f"{row}/{target_column}")
        for row in range(rows)
        for source_column, target_column in column_pairs
    )
    return cell_map, tuple(source_id for source_id, _target_id in cell_map)


_ANNEX_F1_CELL_MAP, _ANNEX_F1_SOURCE_CELLS = _aligned_cell_map(
    rows=8,
    column_pairs=(("clearance_mm", "clearance_mm"),),
)
_ANNEX_F3_CELL_MAP, _ANNEX_F3_SOURCE_CELLS = _aligned_cell_map(
    rows=18,
    column_pairs=tuple(
        (
            f"creepage_frequency_band_{ordinal}_mm",
            target,
        )
        for ordinal, target in enumerate(
            (
                "frequency_30_100_khz_mm",
                "frequency_200_khz_mm",
                "frequency_400_khz_mm",
                "frequency_700_khz_mm",
                "frequency_1_mhz_mm",
                "frequency_2_mhz_mm",
                "frequency_3_mhz_mm",
            ),
            start=1,
        )
    ),
)

#: IEC 62477-1 Table 8 lists ten impulse levels in volts where the IEC 60664-1 clearance
#: table lists twenty-six in kilovolts, so its rows pair by the impulse level they state,
#: scaled into the target's unit, never by position. Every source row does find a target
#: row; pollution degrees 1 to 3 agree cell for cell against the target's first three
#: clearance columns. Pollution degree 4 has no counterpart in IEC 60664-1 at all, so it is
#: declared out of the claim rather than paired with an approximation.
_TABLE_8_AXIS_MATCH = CrossStandardAxisMatchSpec(
    source_axis_column="impulse_withstand_voltage_v",
    target_axis_column="impulse_withstand_kv",
    axis_value_scale=Decimal("0.001"),
    column_pairs=tuple(
        (f"clearance_pollution_degree_{ordinal}_mm", target)
        for ordinal, target in enumerate(("case_a_pd1_mm", "case_a_pd2_mm", "case_a_pd3_mm"), 1)
    ),
    uncompared_source_columns=(
        (
            "clearance_pollution_degree_4_mm",
            (
                "IEC 60664-1 carries no column for this pollution degree, so this column "
                "is the IEC 62477-1 rule's own requirement and no equivalence is claimed "
                "for it"
            ),
        ),
    ),
)

#: The printed-wiring creepage columns pair against the IEC 60664-1 printed-wiring columns
#: over the working voltages both documents state. IEC 62477-1 starts its axis below the
#: lowest voltage that table reaches and carries one row above where its printed-wiring
#: columns stop, so those three rows are declared out of the claim; every remaining row
#: agrees. The other-insulator half of Table 9 is not checked at all: the IEC 60664-1
#: recipe reads those columns as context, so their cells hold no logical coordinates to
#: compare against, and pairing them would need that reviewed table's own shape to change.
_TABLE_9_PRINTED_WIRING_AXIS_MATCH = CrossStandardAxisMatchSpec(
    source_axis_column=_WORKING_VOLTAGE_AXIS,
    target_axis_column="rms_voltage_v",
    column_pairs=(
        ("printed_wiring_pollution_1_mm", "pcb_pollution_1"),
        ("printed_wiring_pollution_2_mm", "pcb_pollution_2"),
    ),
    uncompared_source_rows=(
        *(
            (
                row,
                (
                    "the IEC 60664-1 printed-wiring table's axis does not reach this "
                    "working voltage, so the requirement on this row is the IEC 62477-1 "
                    "rule's own"
                ),
            )
            for row in (0, 1)
        ),
        (
            20,
            (
                "the IEC 60664-1 printed-wiring columns carry no requirement on the row "
                "of this working voltage, so nothing there can prove or refute "
                "equivalence"
            ),
        ),
    ),
)

#: Annex F states that the design above its frequency threshold follows IEC 60664-4:2005,
#: and the package already carries that standard's reviewed clearance and creepage rules.
#: These checks prove the reproduction agrees cell for cell before a mapping is recorded;
#: any divergence blocks approval and leaves both rules standing for a maintainer to judge.
#: Table F.2 has no counterpart among the approved IEC 60664-4 rules, so it is declared no
#: check at all rather than being paired with an approximate target.
CROSS_STANDARD_CHECKS: tuple[CrossStandardCheckSpec, ...] = (
    CrossStandardCheckSpec(
        id=f"{ids.CLEARANCE_REQUIREMENTS}.matches_part1_clearance",
        source_rule_id=f"raw-{ids.CLEARANCE_REQUIREMENTS}",
        target_rule_id="raw-iec60664-1-f2",
        family="clearance",
        axis_match=_TABLE_8_AXIS_MATCH,
        source=SourceReference(
            document_id="iec62477-1-2022",
            standard="IEC 62477-1",
            edition="2022",
            page=_TABLE_8_PAGE,
            clause=_TABLE_8_CLAUSE,
            table="8",
        ),
    ),
    CrossStandardCheckSpec(
        id=f"{ids.CREEPAGE_REQUIREMENTS}.printed_wiring_matches_part1_creepage",
        source_rule_id=f"raw-{ids.CREEPAGE_REQUIREMENTS}.printed_wiring",
        target_rule_id="raw-iec60664-1-f5",
        family="creepage",
        axis_match=_TABLE_9_PRINTED_WIRING_AXIS_MATCH,
        source=SourceReference(
            document_id="iec62477-1-2022",
            standard="IEC 62477-1",
            edition="2022",
            page=_TABLE_9_PAGE,
            clause=_TABLE_9_CLAUSE,
            table="9",
        ),
    ),
    CrossStandardCheckSpec(
        id=f"{ids.HIGH_FREQUENCY_APPLICABILITY}.annex_f1_matches_part4_clearance",
        source_rule_id=f"raw-{ids.HIGH_FREQUENCY_APPLICABILITY}.annex_f1",
        target_rule_id="raw-iec60664-4-table-1",
        family="high-frequency-clearance",
        cell_map=_ANNEX_F1_CELL_MAP,
        source_data_cell_ids=_ANNEX_F1_SOURCE_CELLS,
        source=SourceReference(
            document_id="iec62477-1-2022",
            standard="IEC 62477-1",
            edition="2022",
            page=197,
            clause="F.2.2",
            table="F.1",
        ),
    ),
    CrossStandardCheckSpec(
        id=f"{ids.HIGH_FREQUENCY_APPLICABILITY}.annex_f3_matches_part4_creepage",
        source_rule_id=f"raw-{ids.HIGH_FREQUENCY_APPLICABILITY}.annex_f3",
        target_rule_id="raw-iec60664-4-table-2",
        family="high-frequency-creepage",
        cell_map=_ANNEX_F3_CELL_MAP,
        source_data_cell_ids=_ANNEX_F3_SOURCE_CELLS,
        #: Both tables step their requirements and leave the inapplicable cells without a
        #: number. The IEC 62477-1 printing marks those cells with a dash where the
        #: IEC 60664-4 printing leaves them empty, which is notation, not requirement.
        no_requirement_tokens=("--", "-", "–", "—"),
        source=SourceReference(
            document_id="iec62477-1-2022",
            standard="IEC 62477-1",
            edition="2022",
            page=199,
            clause="F.3",
            table="F.3",
        ),
    ),
)

__all__ = [
    "CROSS_STANDARD_CHECKS",
    "SPACING_TABLES",
    "TABLE_8",
    "TABLE_9_OTHER_INSULATORS",
    "TABLE_9_PRINTED_WIRING",
]
