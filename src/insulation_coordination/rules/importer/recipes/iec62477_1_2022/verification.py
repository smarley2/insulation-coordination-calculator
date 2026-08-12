"""IEC 62477-1:2022 verification table recipes. Layout facts only.

Bounding boxes, row and column counts, header/data/note row indexes, and footnote marker
characters are measured from the maintained printing. Field names and variant names are
neutral descriptions written here; no source subject, condition, or note text is copied.
"""

from __future__ import annotations

from typing import Literal

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
    ProcedureRule,
    ProcedureStep,
    SourceReference,
)
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    SemanticProposal,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import (
    StandardIdentity,
    TableAuditSpec,
    TableColumnSpec,
    TableSegmentSpec,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

_TABLE_26_PAGE = 124
_TABLE_26_CLAUSE = "5.2.3.2"
_TABLE_26_RAW_ROWS = 20
_TABLE_26_RAW_COLUMNS = 4
_TABLE_26_BBOX = (71.04, 106.8, 531.72, 769.56)
_TABLE_26_HEADER_ROWS = (0,)
_TABLE_26_DATA_ROWS = tuple(range(1, _TABLE_26_RAW_ROWS))
#: Declared apart from ``_TABLE_26_DATA_ROWS`` so the extraction-time count check is not a
#: tautology against its own input.
_TABLE_26_EXPECTED_DATA_ROWS = 19

#: Rows whose subject cell is empty: their condition continues the subject above them. They
#: are declared rather than inferred from an empty cell, so a printing that leaves a subject
#: blank for a different reason cannot be read as a continuation.
CONTINUATION_ROWS = (5, 14, 15, 19)


class ProcedureStructureError(ValueError):
    """A reviewed verification grid falls outside its declared row contract."""


def _fail(message: str) -> None:
    raise ProcedureStructureError(f"AMBIGUOUS_PROCEDURE_STRUCTURE: {message}")


#: The three variants the condition columns carry. The source pairs insulation classes in
#: its first two condition columns and gives the transient-overvoltage-reduction case in the
#: third; these identifiers name what a column selects on without reproducing its wording.
VARIANT_COLUMNS: tuple[tuple[str, int], ...] = (
    ("insulation_basic", 1),
    ("insulation_reinforced", 2),
    ("transient_reduction", 3),
)

#: Which row feeds which typed field of ``ProcedureRule``. Positional first: the row index is
#: the structural fact, and the name is this author's neutral description of what the row is
#: for. A row absent from this map has no home in the typed rule, so extraction blocks rather
#: than dropping it.
FIELD_ROWS: tuple[tuple[int, str], ...] = (
    (1, "test_reference"),
    (2, "requirement_reference"),
    (3, "subject_under_test"),
    (4, "preconditioning"),
    (6, "connection_topology"),
    (7, "initial_measurement"),
    (8, "test_equipment"),
    (9, "alternative_test_equipment"),
    (10, "alternative_test_reference"),
    (11, "power_condition"),
    (12, "insulation_class_selector"),
    (13, "measurement_and_verification"),
    (16, "repetitions"),
    (17, "test_voltage_reference"),
    (18, "altitude_correction"),
)
#: Fields that carry the procedure's own execution steps, in source order. The remaining
#: fields describe references, equipment, and preconditions instead.
_STEP_FIELDS = (
    "connection_topology",
    "initial_measurement",
    "measurement_and_verification",
    "repetitions",
    "test_voltage_reference",
    "altitude_correction",
)
_PREPARATION_FIELDS = ("preconditioning", "power_condition")


def _columns() -> tuple[TableColumnSpec, ...]:
    """The subject column, then one condition column per variant.

    Nothing in this table is a quantity: every cell is a reference, a condition, or a step.
    The subject column is context, and each variant's condition column is data so the grid
    keeps logical coordinates, while ``text_field_table`` records that those data cells are
    reviewed text rather than numbers.
    """
    subject = TableColumnSpec(
        semantic_id="procedure_subject",
        heading="subject of this row",
        source_column=0,
        role="context",
        unit="1",
    )
    conditions = tuple(
        TableColumnSpec(
            semantic_id=f"condition_{variant}",
            heading=f"test condition for {variant.replace('_', ' ')}",
            source_column=source_column,
            role="data",
            unit="1",
        )
        for variant, source_column in VARIANT_COLUMNS
    )
    return (subject, *conditions)


TABLE_26 = TableAuditSpec(
    semantic_id=ids.TEST_IMPULSE_PROCEDURE,
    source_table="26",
    title_anchor="Table 26",
    page_number=_TABLE_26_PAGE,
    clause=_TABLE_26_CLAUSE,
    target_unit="1",
    page_search_radius=2,
    expected_raw_rows=_TABLE_26_RAW_ROWS,
    expected_raw_columns=_TABLE_26_RAW_COLUMNS,
    expected_bbox=_TABLE_26_BBOX,
    data_strategy="rectangle",
    data_row_start=1,
    data_column_start=0,
    expected_data_rows=_TABLE_26_EXPECTED_DATA_ROWS,
    expected_data_columns=len(VARIANT_COLUMNS),
    text_field_table=True,
    row_axis_id="procedure_field",
    row_axis_unit="1",
    column_axis_id="procedure_variant",
    column_axis_unit="1",
    assertions=("raw_value_correspondence",),
    segments=(
        TableSegmentSpec(
            id="table-26",
            page_number=_TABLE_26_PAGE,
            title_anchor="Table 26",
            expected_raw_rows=_TABLE_26_RAW_ROWS,
            expected_raw_columns=_TABLE_26_RAW_COLUMNS,
            expected_bbox=_TABLE_26_BBOX,
            source_columns=tuple(range(_TABLE_26_RAW_COLUMNS)),
            header_rows=_TABLE_26_HEADER_ROWS,
            data_rows=_TABLE_26_DATA_ROWS,
            page_search_radius=2,
        ),
    ),
    columns=_columns(),
    decision_route_ids=tuple(
        f"{ids.TEST_IMPULSE_PROCEDURE}.{variant}" for variant, _column in VARIANT_COLUMNS
    ),
)


def _cell_text(grid: RawGrid, row: int, column: int) -> str:
    cell = next(
        (item for item in grid.cells if (item.row, item.column) == (row, column)),
        None,
    )
    if cell is None:
        _fail(f"row {row} column {column} is absent from the grid")
        raise AssertionError  # pragma: no cover - _fail always raises
    return cell.raw_text.strip()


def _condition(grid: RawGrid, row: int, column: int) -> str:
    """One variant's condition for one row, falling back to a condition spanning the row.

    A row that states one condition for every variant fills only its first condition cell,
    so a variant with an empty cell inherits that spanning value. A row that states nothing
    at all for a variant yields the empty string, and the caller decides whether that is
    allowed for the field.
    """
    own = _cell_text(grid, row, column)
    if own:
        return own
    return _cell_text(grid, row, VARIANT_COLUMNS[0][1])


def project_impulse_procedure(
    grid: RawGrid,
    identity: StandardIdentity,
) -> tuple[tuple[ProcedureRule, ...], tuple[SemanticProposal, ...]]:
    """Project Table 26 into one reviewed procedure per variant."""

    if grid.id != f"raw-{ids.TEST_IMPULSE_PROCEDURE}":
        raise ValueError("impulse procedure projection requires its own grid")
    if grid.source.standard != identity.standard or grid.source.edition != identity.edition:
        raise ValueError("impulse procedure grid does not match its identified source")
    if (grid.rows, grid.columns) != (_TABLE_26_RAW_ROWS, _TABLE_26_RAW_COLUMNS):
        _fail("expected the declared grid shape")

    declared = {row for row, _field in FIELD_ROWS} | set(CONTINUATION_ROWS)
    missing = set(_TABLE_26_DATA_ROWS) - declared
    if missing:
        _fail(f"rows {sorted(missing)} are neither a declared field nor a continuation")

    source = SourceReference(
        document_id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        page=_TABLE_26_PAGE,
        clause=_TABLE_26_CLAUSE,
        table="26",
    )
    rules: list[ProcedureRule] = []
    proposals: list[SemanticProposal] = []
    for variant, column in VARIANT_COLUMNS:
        fields = {field: _condition(grid, row, column) for row, field in FIELD_ROWS}
        continuations = tuple(
            text for row in CONTINUATION_ROWS if (text := _condition(grid, row, column))
        )
        steps = tuple(
            ProcedureStep(
                order=order,
                text=text,
                source=source.model_copy(update={"row": f"grid row {row + 1}"}),
            )
            for order, (row, text) in enumerate(
                (
                    (row, fields[field])
                    for row, field in FIELD_ROWS
                    if field in _STEP_FIELDS and fields[field]
                ),
                start=1,
            )
        )
        if not steps:
            _fail(f"variant {variant} has no reviewed procedure step")
        preparation = tuple(
            ProcedureStep(
                order=order,
                text=text,
                source=source,
            )
            for order, text in enumerate(
                (fields[field] for field in _PREPARATION_FIELDS if fields[field]),
                start=1,
            )
        )
        rule = ProcedureRule(
            id=f"{ids.TEST_IMPULSE_PROCEDURE}.{variant}",
            test_kind="impulse_withstand_voltage",
            classifications=("type_test", "sample_test"),
            repetitions=fields["repetitions"] or None,
            preparation_steps=preparation,
            procedure_steps=steps,
            applicability=" ".join(continuations)[:2_000] or "",
            source=source,
        )
        rules.append(rule)
        proposals.append(
            SemanticProposal(
                semantic_id=rule.id,
                rule_kind="procedure",
                state="proposed",
                rule_sha256=canonical_model_sha256(rule),
                source_artifact_sha256=canonical_model_sha256(grid),
            )
        )
    return tuple(rules), tuple(proposals)


# Table 27's raw grid, shared by every selection route it carries. Column 0 is the AC
# system-voltage axis and column 1 the DC system-voltage axis: two parallel row axes over the
# same physical rows, selected by supply kind, exactly as Table 7 carries them. The last data
# row (physical index 9) is DC-only -- its column 0 cell holds a not-applicable marker rather
# than a number -- so the AC route excludes it from its data rows instead of resolving a value
# that does not apply to an AC supply. Rows 10 and 11 restate interpolation and carry a source
# note; neither is a data row.
_TABLE_27_PAGE = 125
_TABLE_27_CLAUSE = "5.2.3.2"
_TABLE_27_RAW_ROWS = 12
_TABLE_27_RAW_COLUMNS = 6
_TABLE_27_BBOX = (68.52, 167.88, 527.04, 456.36)
_TABLE_27_HEADER_ROWS = (0, 1, 2)
_TABLE_27_DATA_ROWS_DC = tuple(range(3, 10))
_TABLE_27_DATA_ROWS_AC = _TABLE_27_DATA_ROWS_DC[:-1]
_TABLE_27_NOTE_ROWS = (10, 11)
#: Declared independently of the ``data_rows`` tuples above so the extraction-time row count
#: check is not a tautology against its own input.
_TABLE_27_EXPECTED_DATA_ROWS_AC = 6
_TABLE_27_EXPECTED_DATA_ROWS_DC = 7
#: The physical columns carrying the selected test voltages, grouped as the source groups them:
#: two pairs of two, each pair headed by the circuits and overvoltage category it selects for.
#: The source states an interpolation rule per pair, in the row below the data rows (physical
#: row 10, whose cells span each pair): it is permitted for the first pair and refused for the
#: second. One flag per spec cannot say both, so each pair is its own spec. Pair names are this
#: author's neutral description of what a pair selects on; the source column numbers are the
#: structural fact.
_TABLE_27_COLUMN_PAIRS: tuple[tuple[str, tuple[int, int], Literal["none", "linear"]], ...] = (
    ("non_mains_circuits", (2, 3), "linear"),
    ("mains_circuits", (4, 5), "none"),
)


def _table_27_specs() -> tuple[TableAuditSpec, ...]:
    """One spec per column pair per supply kind, over Table 27's two parallel row axes."""

    specs: list[TableAuditSpec] = []
    for pair, pair_columns, interpolation in _TABLE_27_COLUMN_PAIRS:
        for supply, axis_source_column, data_rows, expected_data_rows in (
            ("ac", 0, _TABLE_27_DATA_ROWS_AC, _TABLE_27_EXPECTED_DATA_ROWS_AC),
            ("dc", 1, _TABLE_27_DATA_ROWS_DC, _TABLE_27_EXPECTED_DATA_ROWS_DC),
        ):
            axis_semantic_id = f"system_voltage_{supply}_v"
            source_columns = (axis_source_column, *pair_columns)
            columns = (
                TableColumnSpec(
                    semantic_id=axis_semantic_id,
                    heading=f"{supply} system voltage band upper bound",
                    source_column=axis_source_column,
                    role="axis",
                    unit="V",
                ),
                *(
                    TableColumnSpec(
                        semantic_id=f"selected_test_voltage_col{source_column}_v",
                        heading=f"selected test voltage, source column {source_column}",
                        source_column=source_column,
                        role="data",
                        unit="V",
                    )
                    for source_column in pair_columns
                ),
            )
            specs.append(
                TableAuditSpec(
                    semantic_id=f"{ids.TEST_IMPULSE_SELECTION}.{pair}.{supply}",
                    source_table="27",
                    title_anchor="Table 27",
                    page_number=_TABLE_27_PAGE,
                    clause=_TABLE_27_CLAUSE,
                    target_unit="V",
                    interpolation=interpolation,
                    page_search_radius=2,
                    expected_raw_rows=_TABLE_27_RAW_ROWS,
                    expected_raw_columns=len(source_columns),
                    expected_bbox=_TABLE_27_BBOX,
                    data_strategy="rectangle",
                    data_row_start=_TABLE_27_DATA_ROWS_DC[0],
                    data_column_start=0,
                    expected_data_rows=expected_data_rows,
                    #: The axis column counts here too: extraction gives every non-context
                    #: column a logical coordinate.
                    expected_data_columns=len(source_columns),
                    row_axis_id=axis_semantic_id,
                    row_axis_unit="V",
                    column_axis_id="impulse_selection_column",
                    column_axis_unit="1",
                    assertions=("strictly_increasing_axes", "raw_value_correspondence"),
                    segments=(
                        TableSegmentSpec(
                            id=f"table-27-{pair}-{supply}",
                            page_number=_TABLE_27_PAGE,
                            title_anchor="Table 27",
                            expected_raw_rows=_TABLE_27_RAW_ROWS,
                            expected_raw_columns=_TABLE_27_RAW_COLUMNS,
                            expected_bbox=_TABLE_27_BBOX,
                            source_columns=source_columns,
                            header_rows=_TABLE_27_HEADER_ROWS,
                            data_rows=data_rows,
                            note_rows=_TABLE_27_NOTE_ROWS,
                            page_search_radius=2,
                        ),
                    ),
                    columns=columns,
                )
            )
    return tuple(specs)


TABLE_27_SPECS: tuple[TableAuditSpec, ...] = _table_27_specs()


# Tables 28 and 29 share one column layout: a row axis in column 0, then two test purposes
# side by side, each stating an AC RMS value and a DC value. A purpose is what its source
# column group selects on; these identifiers name that selection without reproducing the
# group's wording. Splitting by purpose and by supply kind keeps four quantities in four
# rules instead of one grid that mixes them.
_DIELECTRIC_CLAUSE = "5.2.3.4.2"
_DIELECTRIC_PURPOSES: tuple[tuple[str, int, int], ...] = (
    ("routine_and_basic_type", 1, 2),
    ("enhanced_type", 3, 4),
)
_DIELECTRIC_RAW_COLUMNS = 5
_DIELECTRIC_HEADER_ROWS = (0, 1, 2)
#: The source states that interpolation is permitted for both tables, so a value between two
#: tabulated rows is resolved rather than refused.
_DIELECTRIC_INTERPOLATION: Literal["none", "linear"] = "linear"

_TABLE_28_PAGE = 127
_TABLE_28_BBOX = (71.04, 118.32, 524.28, 388.32)
_TABLE_28_RAW_ROWS = 10
_TABLE_28_DATA_ROWS = tuple(range(3, 9))
_TABLE_28_NOTE_ROWS = (9,)
#: Declared independently of ``_TABLE_28_DATA_ROWS`` so the extraction-time row count check
#: is not a tautology against its own input.
_TABLE_28_EXPECTED_DATA_ROWS = 6

# Table 29 runs over a page break. Both segments carry the same three header rows and the
# same five columns; the second segment continues the first segment's row axis, so its
# logical rows are offset by the first segment's data row count.
#: The continuation prints no caption of its own -- measured from the document, the only text
#: above the second segment's grid is the page's running header -- so that header's copyright
#: identity is the anchor that binds it. Shape and bounding box still have to match exactly,
#: and a second page in the search window matching both refuses the extraction, so a generic
#: anchor does not weaken the locator.
_TABLE_29_CONTINUATION_ANCHOR = "IEC 2022"
_TABLE_29_FIRST_PAGE = 127
_TABLE_29_FIRST_BBOX = (71.04, 484.08, 524.28, 797.52)
_TABLE_29_FIRST_RAW_ROWS = 16
_TABLE_29_FIRST_DATA_ROWS = tuple(range(3, 16))
_TABLE_29_SECOND_PAGE = 128
_TABLE_29_SECOND_BBOX = (71.04, 85.32, 524.28, 346.8)
_TABLE_29_SECOND_RAW_ROWS = 9
_TABLE_29_SECOND_DATA_ROWS = tuple(range(3, 8))
_TABLE_29_SECOND_NOTE_ROWS = (8,)
_TABLE_29_EXPECTED_DATA_ROWS = 18


def _dielectric_specs(
    *,
    semantic_id: str,
    source_table: str,
    axis_semantic_id: str,
    axis_heading: str,
    raw_rows: int,
    expected_data_rows: int,
    segments: tuple[TableSegmentSpec, ...],
) -> tuple[TableAuditSpec, ...]:
    """One spec per test purpose per supply kind, all reading the same row axis."""

    specs: list[TableAuditSpec] = []
    for purpose, ac_column, dc_column in _DIELECTRIC_PURPOSES:
        for supply, source_column in (("ac", ac_column), ("dc", dc_column)):
            source_columns = (0, source_column)
            specs.append(
                TableAuditSpec(
                    semantic_id=f"{semantic_id}.{purpose}.{supply}",
                    source_table=source_table,
                    title_anchor=f"Table {source_table}",
                    page_number=segments[0].page_number,
                    clause=_DIELECTRIC_CLAUSE,
                    target_unit="V",
                    interpolation=_DIELECTRIC_INTERPOLATION,
                    page_search_radius=2,
                    expected_raw_rows=raw_rows,
                    expected_raw_columns=len(source_columns),
                    expected_bbox=segments[0].expected_bbox,
                    data_strategy="rectangle",
                    data_row_start=segments[0].data_rows[0],
                    data_column_start=0,
                    expected_data_rows=expected_data_rows,
                    #: The axis column counts here too: extraction gives every non-context
                    #: column a logical coordinate.
                    expected_data_columns=len(source_columns),
                    row_axis_id=axis_semantic_id,
                    row_axis_unit="V",
                    column_axis_id="dielectric_test_column",
                    column_axis_unit="1",
                    assertions=("strictly_increasing_axes", "raw_value_correspondence"),
                    segments=tuple(
                        segment.model_copy(
                            update={
                                "id": f"{segment.id}-{purpose}-{supply}",
                                "source_columns": source_columns,
                            }
                        )
                        for segment in segments
                    ),
                    columns=(
                        TableColumnSpec(
                            semantic_id=axis_semantic_id,
                            heading=axis_heading,
                            source_column=0,
                            role="axis",
                            unit="V",
                        ),
                        TableColumnSpec(
                            semantic_id=f"test_voltage_{purpose}_{supply}_v",
                            heading=(
                                f"{supply} test voltage for the {purpose.replace('_', ' ')} case"
                            ),
                            source_column=source_column,
                            role="data",
                            unit="V",
                        ),
                    ),
                )
            )
    return tuple(specs)


TABLE_28_SPECS = _dielectric_specs(
    semantic_id=ids.TEST_MAINS_DIELECTRIC_VALUES,
    source_table="28",
    axis_semantic_id="system_voltage_v",
    axis_heading="system voltage band upper bound",
    raw_rows=_TABLE_28_RAW_ROWS,
    expected_data_rows=_TABLE_28_EXPECTED_DATA_ROWS,
    segments=(
        TableSegmentSpec(
            id="table-28",
            page_number=_TABLE_28_PAGE,
            title_anchor="Table 28",
            expected_raw_rows=_TABLE_28_RAW_ROWS,
            expected_raw_columns=_DIELECTRIC_RAW_COLUMNS,
            expected_bbox=_TABLE_28_BBOX,
            header_rows=_DIELECTRIC_HEADER_ROWS,
            data_rows=_TABLE_28_DATA_ROWS,
            note_rows=_TABLE_28_NOTE_ROWS,
            page_search_radius=2,
        ),
    ),
)
TABLE_29_SPECS = _dielectric_specs(
    semantic_id=ids.TEST_NON_MAINS_DIELECTRIC_VALUES,
    source_table="29",
    axis_semantic_id="working_voltage_recurring_peak_v",
    axis_heading="working voltage band upper bound, recurring peak",
    raw_rows=_TABLE_29_FIRST_RAW_ROWS + _TABLE_29_SECOND_RAW_ROWS,
    expected_data_rows=_TABLE_29_EXPECTED_DATA_ROWS,
    segments=(
        TableSegmentSpec(
            id="table-29-page-1",
            page_number=_TABLE_29_FIRST_PAGE,
            title_anchor="Table 29",
            expected_raw_rows=_TABLE_29_FIRST_RAW_ROWS,
            expected_raw_columns=_DIELECTRIC_RAW_COLUMNS,
            expected_bbox=_TABLE_29_FIRST_BBOX,
            header_rows=_DIELECTRIC_HEADER_ROWS,
            data_rows=_TABLE_29_FIRST_DATA_ROWS,
            page_search_radius=2,
        ),
        TableSegmentSpec(
            id="table-29-page-2",
            page_number=_TABLE_29_SECOND_PAGE,
            title_anchor=_TABLE_29_CONTINUATION_ANCHOR,
            expected_raw_rows=_TABLE_29_SECOND_RAW_ROWS,
            expected_raw_columns=_DIELECTRIC_RAW_COLUMNS,
            expected_bbox=_TABLE_29_SECOND_BBOX,
            logical_row_offset=len(_TABLE_29_FIRST_DATA_ROWS),
            header_rows=_DIELECTRIC_HEADER_ROWS,
            data_rows=_TABLE_29_SECOND_DATA_ROWS,
            note_rows=_TABLE_29_SECOND_NOTE_ROWS,
            page_search_radius=2,
        ),
    ),
)
DIELECTRIC_SPECS: tuple[TableAuditSpec, ...] = (*TABLE_28_SPECS, *TABLE_29_SPECS)


# Table 30 is a field table like Table 26, but a flat one: every row states one subject in
# column 0 and its condition in column 1, and no row continues the row above it. Row 12 is a
# source note, not a subject.
_TABLE_30_PAGE = 131
_TABLE_30_CLAUSE = "5.2.3.5"
_TABLE_30_RAW_ROWS = 13
_TABLE_30_RAW_COLUMNS = 2
_TABLE_30_BBOX = (70.92, 106.8, 524.43, 507.48)
_TABLE_30_HEADER_ROWS = (0,)
_TABLE_30_NOTE_ROWS = (12,)
_TABLE_30_DATA_ROWS = tuple(range(1, _TABLE_30_NOTE_ROWS[0]))
#: Declared apart from ``_TABLE_30_DATA_ROWS`` so the extraction-time count check is not a
#: tautology against its own input.
_TABLE_30_EXPECTED_DATA_ROWS = 11
_PARTIAL_DISCHARGE_APPLICABILITY_ID = f"{ids.TEST_PARTIAL_DISCHARGE}.applicability"

#: Which row feeds which typed field, positional first: the row index is the structural fact
#: and the name is this author's neutral description of what the row is for. A data row absent
#: from this map has no home in the typed rule, so projection blocks rather than dropping it.
PARTIAL_DISCHARGE_FIELD_ROWS: tuple[tuple[int, str], ...] = (
    (1, "test_reference"),
    (2, "requirement_reference"),
    (3, "preconditioning"),
    (4, "initial_measurement"),
    (5, "test_equipment"),
    (6, "test_circuit"),
    (7, "test_voltage"),
    (8, "test_method"),
    (9, "equipment_calibration"),
    (10, "measurement"),
    (11, "verification"),
)
#: The rows that state what is done to the sample, in source order.
_PARTIAL_DISCHARGE_STEP_FIELDS = (
    "test_circuit",
    "test_voltage",
    "test_method",
    "measurement",
    "verification",
)
#: The rows that state what must hold before the test runs, in source order.
_PARTIAL_DISCHARGE_PREPARATION_FIELDS = (
    "preconditioning",
    "initial_measurement",
    "test_equipment",
    "equipment_calibration",
)
#: The row whose condition depends on a quantity nobody can read off the page: it is measured
#: on the equipment under test. That is what makes the applicability a decision rather than a
#: constant, and its row is the provenance for both decision rows.
_PARTIAL_DISCHARGE_GATE_FIELD = "test_voltage"

TABLE_30 = TableAuditSpec(
    semantic_id=ids.TEST_PARTIAL_DISCHARGE,
    source_table="30",
    title_anchor="Table 30",
    page_number=_TABLE_30_PAGE,
    clause=_TABLE_30_CLAUSE,
    target_unit="1",
    page_search_radius=2,
    expected_raw_rows=_TABLE_30_RAW_ROWS,
    expected_raw_columns=_TABLE_30_RAW_COLUMNS,
    expected_bbox=_TABLE_30_BBOX,
    data_strategy="rectangle",
    data_row_start=_TABLE_30_DATA_ROWS[0],
    data_column_start=0,
    expected_data_rows=_TABLE_30_EXPECTED_DATA_ROWS,
    expected_data_columns=1,
    text_field_table=True,
    row_axis_id="procedure_field",
    row_axis_unit="1",
    column_axis_id="procedure_condition",
    column_axis_unit="1",
    assertions=("raw_value_correspondence",),
    segments=(
        TableSegmentSpec(
            id="table-30",
            page_number=_TABLE_30_PAGE,
            title_anchor="Table 30",
            expected_raw_rows=_TABLE_30_RAW_ROWS,
            expected_raw_columns=_TABLE_30_RAW_COLUMNS,
            expected_bbox=_TABLE_30_BBOX,
            source_columns=tuple(range(_TABLE_30_RAW_COLUMNS)),
            header_rows=_TABLE_30_HEADER_ROWS,
            data_rows=_TABLE_30_DATA_ROWS,
            note_rows=_TABLE_30_NOTE_ROWS,
            page_search_radius=2,
        ),
    ),
    columns=(
        TableColumnSpec(
            semantic_id="procedure_subject",
            heading="subject of this row",
            source_column=0,
            role="context",
            unit="1",
        ),
        TableColumnSpec(
            semantic_id="procedure_condition",
            heading="test condition for this row",
            source_column=1,
            role="data",
            unit="1",
        ),
    ),
    decision_route_ids=(_PARTIAL_DISCHARGE_APPLICABILITY_ID,),
)


def _partial_discharge_applicability(
    grid: RawGrid,
    source: SourceReference,
    gate_row: int,
) -> DecisionRule:
    """Whether the partial-discharge test applies, given the engineering input it needs.

    The test voltage is a quantity measured on the equipment under test, so until it is
    declared the answer is neither yes nor no: it is that an engineering input is missing.
    Reporting that as "not required" would silently drop a required test. The rule is not
    exhaustive on purpose -- the source states its exemptions in prose this table does not
    tabulate, so a "not required" outcome is not derivable from this grid.
    """

    row_source = source.model_copy(update={"row": f"grid row {gate_row + 1}"})
    note = _cell_text(grid, _TABLE_30_NOTE_ROWS[0], 0)
    return DecisionRule(
        id=_PARTIAL_DISCHARGE_APPLICABILITY_ID,
        inputs=(DecisionInput(name="partial_discharge_test_voltage_declared", kind="boolean"),),
        outputs=(
            DecisionOutput(
                name="partial_discharge_test",
                kind="categorical",
                allowed_values=("required", "engineering_input_required"),
            ),
        ),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(
                        input="partial_discharge_test_voltage_declared",
                        op="equals",
                        boolean=False,
                    ),
                ),
                values=(
                    DecisionValue(
                        name="partial_discharge_test",
                        categorical="engineering_input_required",
                    ),
                ),
                source=row_source,
            ),
            DecisionRow(
                matchers=(
                    Matcher(
                        input="partial_discharge_test_voltage_declared",
                        op="equals",
                        boolean=True,
                    ),
                ),
                values=(DecisionValue(name="partial_discharge_test", categorical="required"),),
                source=row_source,
            ),
        ),
        exhaustive=False,
        applicability=note[:2_000],
        source=source,
    )


def project_partial_discharge(
    grid: RawGrid,
    identity: StandardIdentity,
) -> tuple[tuple[ProcedureRule | DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project Table 30 into one reviewed procedure and its applicability decision."""

    if grid.id != f"raw-{ids.TEST_PARTIAL_DISCHARGE}":
        raise ValueError("partial discharge projection requires its own grid")
    if grid.source.standard != identity.standard or grid.source.edition != identity.edition:
        raise ValueError("partial discharge grid does not match its identified source")
    if (grid.rows, grid.columns) != (_TABLE_30_RAW_ROWS, _TABLE_30_RAW_COLUMNS):
        _fail("expected the declared grid shape")

    declared = {row for row, _field in PARTIAL_DISCHARGE_FIELD_ROWS}
    missing = set(_TABLE_30_DATA_ROWS) - declared
    if missing:
        _fail(f"rows {sorted(missing)} are not declared fields")

    source = SourceReference(
        document_id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        page=_TABLE_30_PAGE,
        clause=_TABLE_30_CLAUSE,
        table="30",
    )
    rows_by_field = {field: row for row, field in PARTIAL_DISCHARGE_FIELD_ROWS}
    conditions = {field: _cell_text(grid, row, 1) for row, field in PARTIAL_DISCHARGE_FIELD_ROWS}
    empty = sorted(field for field, text in conditions.items() if not text)
    if empty:
        _fail(f"declared fields {empty} state no condition")

    def _steps(fields: tuple[str, ...]) -> tuple[ProcedureStep, ...]:
        """Exactly one step per declared field: one source condition is one action.

        The longest condition here runs past ``MAX_REFERENCE_TEXT_LENGTH``, which is why
        ``ProcedureStep.text`` carries its own larger cap. Splitting a condition across steps
        would invite a consumer to read one action as several.
        """
        return tuple(
            ProcedureStep(
                order=order,
                text=conditions[field],
                source=source.model_copy(update={"row": f"grid row {rows_by_field[field] + 1}"}),
            )
            for order, field in enumerate(fields, start=1)
        )

    procedure = ProcedureRule(
        id=ids.TEST_PARTIAL_DISCHARGE,
        test_kind="partial_discharge",
        # Which test classifications this carries is stated in the test matrix on the
        # clause-5.2.2 pages, not in this table, so it is not asserted here.
        preparation_steps=_steps(_PARTIAL_DISCHARGE_PREPARATION_FIELDS),
        procedure_steps=_steps(_PARTIAL_DISCHARGE_STEP_FIELDS),
        applicability_rule_id=_PARTIAL_DISCHARGE_APPLICABILITY_ID,
        source=source,
    )
    decision = _partial_discharge_applicability(
        grid,
        source,
        rows_by_field[_PARTIAL_DISCHARGE_GATE_FIELD],
    )
    rules: tuple[ProcedureRule | DecisionRule, ...] = (procedure, decision)
    artifact_sha256 = canonical_model_sha256(grid)
    kinds: tuple[tuple[ProcedureRule | DecisionRule, Literal["procedure", "decision"]], ...] = (
        (procedure, "procedure"),
        (decision, "decision"),
    )
    proposals = tuple(
        SemanticProposal(
            semantic_id=rule.id,
            rule_kind=kind,
            state="proposed",
            rule_sha256=canonical_model_sha256(rule),
            source_artifact_sha256=artifact_sha256,
        )
        for rule, kind in kinds
    )
    return rules, proposals


VERIFICATION_TABLES: tuple[TableAuditSpec, ...] = (
    TABLE_26,
    *TABLE_27_SPECS,
    *DIELECTRIC_SPECS,
    TABLE_30,
)
GRID_PROJECTORS = {
    ids.TEST_IMPULSE_PROCEDURE: project_impulse_procedure,
    ids.TEST_PARTIAL_DISCHARGE: project_partial_discharge,
}

__all__ = [
    "CONTINUATION_ROWS",
    "DIELECTRIC_SPECS",
    "FIELD_ROWS",
    "GRID_PROJECTORS",
    "PARTIAL_DISCHARGE_FIELD_ROWS",
    "TABLE_26",
    "TABLE_27_SPECS",
    "TABLE_28_SPECS",
    "TABLE_29_SPECS",
    "TABLE_30",
    "VARIANT_COLUMNS",
    "VERIFICATION_TABLES",
    "ProcedureStructureError",
    "project_impulse_procedure",
    "project_partial_discharge",
]
