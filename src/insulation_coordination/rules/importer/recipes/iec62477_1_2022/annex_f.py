"""IEC 62477-1:2022 Annex F table recipes. Layout facts only.

The three annex grids are extracted for comparison, not to add a second copy of numbers
the approved IEC 60664-4 rules already carry: Tables F.1 and F.3 restate that standard's
high-frequency clearance and creepage grids, and a comparison either proves the two agree
or blocks. Table F.2 has no counterpart among the approved IEC 60664-4 rules, so it is
recorded here with no cross-standard claim rather than being quietly matched to a grid it
does not correspond to.

Bounding boxes, row and column counts, and header/data/note row indexes are measured from
the maintained printing. Column headings are neutral descriptions written here. Every axis
value belongs to the source: the peak-voltage axis is read from its own column, and the
frequency band values of Table F.3 come from the table's own header row through
``axis_value_source_row``, never from a literal in this file.
"""

from insulation_coordination.rules.importer.identify import (
    BlankCellSpec,
    MergedCellSpec,
    TableAuditSpec,
    TableColumnSpec,
    TableSegmentSpec,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

#: Both annex clearance/creepage grids share the peak-voltage row axis of their
#: IEC 60664-4 counterparts.
_PEAK_VOLTAGE_AXIS = "peak_voltage_kv"
#: Footnote marker character measured on Table F.1's axis cells. Tables F.2 and F.3 carry
#: none on a data cell, so neither declares an allowed suffix.
_TABLE_F1_SUFFIXES = ("b",)

_TABLE_F1_PAGE = 197
_TABLE_F1_RAW_ROWS = 10
_TABLE_F1_RAW_COLUMNS = 2
_TABLE_F1_BBOX = (169.7, 118.3, 425.9, 338.6)
_TABLE_F1_HEADER_ROWS = (0,)
_TABLE_F1_DATA_ROWS = tuple(range(1, 9))
_TABLE_F1_NOTE_ROWS = (9,)
#: Declared apart from ``_TABLE_F1_DATA_ROWS`` so the extraction-time count check is not a
#: tautology against its own input.
_TABLE_F1_EXPECTED_DATA_ROWS = 8

_TABLE_F2_PAGE = 197
_TABLE_F2_RAW_ROWS = 5
_TABLE_F2_RAW_COLUMNS = 2
_TABLE_F2_BBOX = (184.3, 528.2, 411.1, 632.3)
_TABLE_F2_HEADER_ROWS = (0,)
_TABLE_F2_DATA_ROWS = tuple(range(1, 5))
_TABLE_F2_EXPECTED_DATA_ROWS = 4

_TABLE_F3_PAGE = 199
_TABLE_F3_RAW_ROWS = 21
_TABLE_F3_RAW_COLUMNS = 8
_TABLE_F3_BBOX = (70.9, 106.8, 524.5, 516.0)
#: Grid row 0 carries the two merged titles and row 1 the per-column frequency bands.
_TABLE_F3_HEADER_ROWS = (0, 1)
_TABLE_F3_DATA_ROWS = tuple(range(2, 20))
_TABLE_F3_NOTE_ROWS = (20,)
_TABLE_F3_EXPECTED_DATA_ROWS = 18
#: Physical row whose cells state each data column's frequency band. Structural, not a
#: value: the band itself is read from the document at import time.
_TABLE_F3_BAND_HEADER_ROW = 1
_TABLE_F3_DATA_COLUMNS = tuple(range(1, _TABLE_F3_RAW_COLUMNS))

#: The axis title spans both header rows downward; the frequency banner spans its row to
#: the right across every data column.
_TABLE_F3_MERGED_CELLS = (
    MergedCellSpec(row=0, column=0, row_span=2, inherit="down"),
    MergedCellSpec(
        row=0, column=1, column_span=len(_TABLE_F3_DATA_COLUMNS), inherit="right"
    ),
)
_TABLE_F3_BLANK_CELLS = (
    *(
        BlankCellSpec(row=0, column=column, semantics="inherit")
        for column in _TABLE_F3_DATA_COLUMNS[1:]
    ),
    BlankCellSpec(row=1, column=0, semantics="inherit"),
    #: The note row carries its text in the first column only.
    *(
        BlankCellSpec(row=20, column=column, semantics="structural")
        for column in _TABLE_F3_DATA_COLUMNS
    ),
)


def _f1_columns() -> tuple[TableColumnSpec, ...]:
    return (
        TableColumnSpec(
            semantic_id=_PEAK_VOLTAGE_AXIS,
            heading="peak voltage entering this table",
            source_column=0,
            role="axis",
            unit="kV",
        ),
        TableColumnSpec(
            semantic_id="clearance_mm",
            heading="clearance on the same row",
            source_column=1,
            role="data",
            unit="mm",
        ),
    )


def _f2_columns() -> tuple[TableColumnSpec, ...]:
    """A frequency band stated as a range, and the factor that band carries.

    The band is prose with two bounds rather than one number, so the generic numeric
    parser cannot type it; those cells arrive as text and raise a raw-cell review item
    instead of being guessed into a numeric axis.
    """
    return (
        TableColumnSpec(
            semantic_id="frequency_band",
            heading="frequency band entering this table",
            source_column=0,
            role="axis",
            unit="Hz",
        ),
        TableColumnSpec(
            semantic_id="band_factor",
            heading="dimensionless factor for the band on the same row",
            source_column=1,
            role="data",
            unit="1",
        ),
    )


def _f3_columns() -> tuple[TableColumnSpec, ...]:
    return (
        TableColumnSpec(
            semantic_id=_PEAK_VOLTAGE_AXIS,
            heading="peak voltage entering this table",
            source_column=0,
            role="axis",
            unit="kV",
        ),
        *(
            TableColumnSpec(
                semantic_id=f"creepage_frequency_band_{ordinal}_mm",
                heading=f"creepage for frequency band column {ordinal}",
                source_column=source_column,
                role="data",
                unit="mm",
                axis_value_source_row=_TABLE_F3_BAND_HEADER_ROW,
            )
            for ordinal, source_column in enumerate(_TABLE_F3_DATA_COLUMNS, start=1)
        ),
    )


TABLE_F1 = TableAuditSpec(
    semantic_id=f"{ids.HIGH_FREQUENCY_APPLICABILITY}.annex_f1",
    source_table="F.1",
    title_anchor="Table F.1",
    page_number=_TABLE_F1_PAGE,
    clause="F.2.2",
    target_unit="mm",
    # Comparison-only: whether this grid may be interpolated is settled by the
    # IEC 60664-4 rule it is compared against, not asserted here.
    interpolation="none",
    page_search_radius=2,
    expected_raw_rows=_TABLE_F1_RAW_ROWS,
    expected_raw_columns=_TABLE_F1_RAW_COLUMNS,
    expected_bbox=_TABLE_F1_BBOX,
    data_strategy="rectangle",
    data_row_start=_TABLE_F1_DATA_ROWS[0],
    data_column_start=0,
    expected_data_rows=_TABLE_F1_EXPECTED_DATA_ROWS,
    expected_data_columns=2,
    row_axis_id=_PEAK_VOLTAGE_AXIS,
    row_axis_unit="kV",
    column_axis_id="clearance_branch",
    column_axis_unit="1",
    allowed_suffixes=_TABLE_F1_SUFFIXES,
    allowed_qualifiers=("up_to",),
    assertions=("strictly_increasing_axes", "raw_value_correspondence"),
    segments=(
        TableSegmentSpec(
            id="table-f1",
            page_number=_TABLE_F1_PAGE,
            title_anchor="Table F.1",
            expected_raw_rows=_TABLE_F1_RAW_ROWS,
            expected_raw_columns=_TABLE_F1_RAW_COLUMNS,
            expected_bbox=_TABLE_F1_BBOX,
            source_columns=tuple(range(_TABLE_F1_RAW_COLUMNS)),
            header_rows=_TABLE_F1_HEADER_ROWS,
            data_rows=_TABLE_F1_DATA_ROWS,
            note_rows=_TABLE_F1_NOTE_ROWS,
            page_search_radius=2,
        ),
    ),
    columns=_f1_columns(),
    #: The note row carries its text in the first column only.
    blank_cells=(BlankCellSpec(row=9, column=1, semantics="structural"),),
)

TABLE_F2 = TableAuditSpec(
    semantic_id=f"{ids.HIGH_FREQUENCY_APPLICABILITY}.annex_f2",
    source_table="F.2",
    title_anchor="Table F.2",
    page_number=_TABLE_F2_PAGE,
    clause="F.2.3",
    target_unit="1",
    interpolation="none",
    page_search_radius=2,
    expected_raw_rows=_TABLE_F2_RAW_ROWS,
    expected_raw_columns=_TABLE_F2_RAW_COLUMNS,
    expected_bbox=_TABLE_F2_BBOX,
    data_strategy="rectangle",
    data_row_start=_TABLE_F2_DATA_ROWS[0],
    data_column_start=0,
    expected_data_rows=_TABLE_F2_EXPECTED_DATA_ROWS,
    expected_data_columns=2,
    row_axis_id="frequency_band",
    row_axis_unit="Hz",
    column_axis_id="band_factor_branch",
    column_axis_unit="1",
    # The band column states ranges, so no monotonic axis is claimed for this grid.
    assertions=("raw_value_correspondence",),
    segments=(
        TableSegmentSpec(
            id="table-f2",
            page_number=_TABLE_F2_PAGE,
            title_anchor="Table F.2",
            expected_raw_rows=_TABLE_F2_RAW_ROWS,
            expected_raw_columns=_TABLE_F2_RAW_COLUMNS,
            expected_bbox=_TABLE_F2_BBOX,
            source_columns=tuple(range(_TABLE_F2_RAW_COLUMNS)),
            header_rows=_TABLE_F2_HEADER_ROWS,
            data_rows=_TABLE_F2_DATA_ROWS,
            page_search_radius=2,
        ),
    ),
    columns=_f2_columns(),
)

TABLE_F3 = TableAuditSpec(
    semantic_id=f"{ids.HIGH_FREQUENCY_APPLICABILITY}.annex_f3",
    source_table="F.3",
    title_anchor="Table F.3",
    page_number=_TABLE_F3_PAGE,
    clause="F.3",
    target_unit="mm",
    interpolation="none",
    page_search_radius=2,
    expected_raw_rows=_TABLE_F3_RAW_ROWS,
    expected_raw_columns=_TABLE_F3_RAW_COLUMNS,
    expected_bbox=_TABLE_F3_BBOX,
    data_strategy="rectangle",
    data_row_start=_TABLE_F3_DATA_ROWS[0],
    data_column_start=0,
    expected_data_rows=_TABLE_F3_EXPECTED_DATA_ROWS,
    expected_data_columns=_TABLE_F3_RAW_COLUMNS,
    row_axis_id=_PEAK_VOLTAGE_AXIS,
    row_axis_unit="kV",
    column_axis_id="frequency_hz",
    column_axis_unit="Hz",
    assertions=("strictly_increasing_axes", "raw_value_correspondence"),
    segments=(
        TableSegmentSpec(
            id="table-f3",
            page_number=_TABLE_F3_PAGE,
            title_anchor="Table F.3",
            expected_raw_rows=_TABLE_F3_RAW_ROWS,
            expected_raw_columns=_TABLE_F3_RAW_COLUMNS,
            expected_bbox=_TABLE_F3_BBOX,
            source_columns=tuple(range(_TABLE_F3_RAW_COLUMNS)),
            header_rows=_TABLE_F3_HEADER_ROWS,
            data_rows=_TABLE_F3_DATA_ROWS,
            note_rows=_TABLE_F3_NOTE_ROWS,
            page_search_radius=2,
        ),
    ),
    columns=_f3_columns(),
    merged_cells=_TABLE_F3_MERGED_CELLS,
    blank_cells=_TABLE_F3_BLANK_CELLS,
)

#: Annex F reproduces IEC 60664-4:2005 requirements for the calculator's frequency range,
#: and those rules are already approved in the package. These grids are therefore extracted
#: as evidence for the cross-standard comparison rather than as rules of their own, so no
#: package carries two copies of the same requirement.
ANNEX_F_TABLES: tuple[TableAuditSpec, ...] = tuple(
    spec.model_copy(update={"comparison_only": True})
    for spec in (TABLE_F1, TABLE_F2, TABLE_F3)
)

__all__ = [
    "ANNEX_F_TABLES",
    "TABLE_F1",
    "TABLE_F2",
    "TABLE_F3",
]
