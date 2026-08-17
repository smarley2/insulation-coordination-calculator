"""IEC 62477-1:2022 Annex F table recipes, and the band grid's own projection.

Tables F.1 and F.3 restate the approved IEC 60664-4 high-frequency clearance and creepage
grids, so they are extracted for comparison rather than as a second copy of numbers the
package already carries: a comparison either proves the two agree or blocks. Table F.2 has
no counterpart among those rules and states a requirement of its own, so it is projected
into a decision that answers which factor a fundamental frequency falls under (#72). That
adds no cross-standard claim: the table becomes resolvable in its own right, not equivalent
to another standard's.

Bounding boxes, row and column counts, and header/data/note row indexes are measured from
the maintained printing. Column headings are neutral descriptions written here. Every axis
value belongs to the source: the peak-voltage axis is read from its own column, the
frequency band values of Table F.3 come from the table's own header row through
``axis_value_source_row``, and Table F.2's band bounds are parsed out of its own axis cells
and confirmed by a reviewer -- never from a literal in this file.
"""

from itertools import pairwise
from typing import cast

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
    RulePackageError,
)
from insulation_coordination.rules.importer.axis_selectors import (
    ConfirmedAxes,
    FrequencyBandSelector,
)
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    SemanticProposal,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import (
    AxisSelectorSpec,
    BlankCellSpec,
    GridProjector,
    MergedCellSpec,
    StandardIdentity,
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
#: The two logical columns of the band grid, and the base unit its bands are converted to.
#: The source states its own SI prefix in the axis column's header, and extraction reads the
#: scale from there rather than from anything declared in this file.
_TABLE_F2_BAND_FIELD = "frequency_band"
_TABLE_F2_FACTOR_FIELD = "band_factor"
_TABLE_F2_AXIS_UNIT = "Hz"

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
    MergedCellSpec(row=0, column=1, column_span=len(_TABLE_F3_DATA_COLUMNS), inherit="right"),
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

    The band is prose with two bounds rather than one number, so the generic numeric parser
    still cannot type it and the axis declares no numeric value here. What types it is the
    band axis selector below: extraction parses the two bounds and the closed end out of this
    column's own cells, and a reviewer confirms that reading before anything resolves from it.
    """
    return (
        TableColumnSpec(
            semantic_id=_TABLE_F2_BAND_FIELD,
            heading="frequency band entering this table",
            source_column=0,
            role="axis",
            unit=_TABLE_F2_AXIS_UNIT,
        ),
        TableColumnSpec(
            semantic_id=_TABLE_F2_FACTOR_FIELD,
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
    semantic_id=ids.HIGH_FREQUENCY_BAND_FACTOR,
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
    row_axis_id=_TABLE_F2_BAND_FIELD,
    row_axis_unit=_TABLE_F2_AXIS_UNIT,
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
    decision_route_ids=(ids.HIGH_FREQUENCY_BAND_FACTOR,),
    axis_selectors=(
        AxisSelectorSpec(
            axis="row",
            expected_positions=_TABLE_F2_EXPECTED_DATA_ROWS,
            selector_kind="frequency_band",
        ),
    ),
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

#: Tables F.1 and F.3 reproduce IEC 60664-4:2005 requirements the package already approves,
#: so they are extracted as evidence for the cross-standard comparison rather than as rules
#: of their own and no package carries two copies of one requirement. Table F.2 is not among
#: them: no approved rule states what it states, so it stays a rule of its own.
ANNEX_F_TABLES: tuple[TableAuditSpec, ...] = (
    TABLE_F1.model_copy(update={"comparison_only": True}),
    TABLE_F2,
    TABLE_F3.model_copy(update={"comparison_only": True}),
)

#: The same input name the annex's applicability decision answers, so a consumer asks both
#: rules the one question it already has an answer for.
_FREQUENCY_INPUT = "working_voltage_frequency_hz"


def _band_rows(grid: RawGrid, axes: ConfirmedAxes) -> tuple[DecisionRow, ...]:
    """One row per reviewed band: the band's own interval, and the factor beside it.

    The interval comes from the confirmed selector and the factor from the extracted cell on
    the same physical row, so neither is stated here. Bands are refused where two overlap:
    ``evaluate_decision`` serves the first row that fits, so an overlap would silently pick a
    factor by row order rather than by what the source says.
    """

    factors = {
        cell.row: cell
        for cell in grid.cells
        if cell.role == "data" and cell.logical_column == _TABLE_F2_FACTOR_FIELD
    }
    bands = sorted(
        ((index, cast(FrequencyBandSelector, axes.row(index))) for index in axes.rows),
        key=lambda item: item[1].lower_hz,
    )
    for (_earlier_index, earlier), (_later_index, later) in pairwise(bands):
        if later.lower_hz < earlier.upper_hz or (
            later.lower_hz == earlier.upper_hz
            and earlier.inclusive_bound in {"upper", "both"}
            and later.inclusive_bound in {"lower", "both"}
        ):
            raise RulePackageError("Table F.2 has two overlapping reviewed frequency bands")
    rows: list[DecisionRow] = []
    for index, band in bands:
        cell = factors.get(index)
        if cell is None or cell.value is None or cell.parse_status != "numeric":
            raise RulePackageError(f"Table F.2 row {index} has no numeric factor beside its band")
        rows.append(
            DecisionRow(
                matchers=(
                    Matcher(
                        input=_FREQUENCY_INPUT,
                        op="range",
                        minimum=band.lower_hz,
                        maximum=band.upper_hz,
                        minimum_inclusive=band.inclusive_bound in {"lower", "both"},
                        maximum_inclusive=band.inclusive_bound in {"upper", "both"},
                    ),
                ),
                values=(
                    DecisionValue(
                        name=_TABLE_F2_FACTOR_FIELD, numeric=cell.value, unit=grid.target_unit
                    ),
                ),
                source=cell.source,
            )
        )
    return tuple(rows)


def project_high_frequency_band_factor(
    grid: RawGrid,
    identity: StandardIdentity,
    confirmed_axes: ConfirmedAxes,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the reviewed band grid into the decision that answers one frequency.

    Not exhaustive on purpose: the source declares bands over part of the frequency range and
    says nothing about the rest, so a frequency outside every declared band resolves to
    ``no_match`` and the consumer is told the table settles nothing there, rather than being
    handed the nearest band's factor.
    """

    if grid.id != f"raw-{ids.HIGH_FREQUENCY_BAND_FACTOR}":
        raise ValueError("the band factor projection requires the Annex F band grid")
    if grid.source.standard != identity.standard or grid.source.edition != identity.edition:
        raise ValueError("the band grid does not match its identified source")
    if len(confirmed_axes.rows) != TABLE_F2.expected_data_rows:
        raise ValueError("the band factor projection needs every reviewed band")
    rule = DecisionRule(
        id=ids.HIGH_FREQUENCY_BAND_FACTOR,
        inputs=(DecisionInput(name=_FREQUENCY_INPUT, kind="numeric", unit=_TABLE_F2_AXIS_UNIT),),
        outputs=(
            DecisionOutput(name=_TABLE_F2_FACTOR_FIELD, kind="numeric", unit=TABLE_F2.target_unit),
        ),
        rows=_band_rows(grid, confirmed_axes),
        exhaustive=False,
        source=grid.source,
    )
    proposal = SemanticProposal(
        semantic_id=rule.id,
        rule_kind="decision",
        state="proposed",
        rule_sha256=canonical_model_sha256(rule),
        source_artifact_sha256=canonical_model_sha256(grid),
    )
    return (rule,), (proposal,)


GRID_PROJECTORS: dict[str, GridProjector] = {
    ids.HIGH_FREQUENCY_BAND_FACTOR: project_high_frequency_band_factor,
}

__all__ = [
    "ANNEX_F_TABLES",
    "GRID_PROJECTORS",
    "TABLE_F1",
    "TABLE_F2",
    "TABLE_F3",
    "project_high_frequency_band_factor",
]
