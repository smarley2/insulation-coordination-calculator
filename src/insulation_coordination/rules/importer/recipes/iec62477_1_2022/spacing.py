"""IEC 62477-1:2022 clearance and creepage table recipes. Layout facts only.

Bounding boxes, row and column counts, and header/data/note row indexes are measured
from the maintained printing. Column headings are neutral descriptions written here; the
pollution-degree and material-group axis values belong to the source tables and are read
from their own header rows at import time.
"""

from insulation_coordination.rules.importer.identify import (
    BlankCellSpec,
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

SPACING_TABLES: tuple[TableAuditSpec, ...] = (TABLE_8,)

__all__ = ["SPACING_TABLES", "TABLE_8"]
