"""IEC 62477-1:2022 verification table recipes. Layout facts only.

Bounding boxes, row and column counts, header/data/note row indexes, and footnote marker
characters are measured from the maintained printing. Field names and variant names are
neutral descriptions written here; no source subject, condition, or note text is copied.
"""

from __future__ import annotations

from insulation_coordination.domain.rules import (
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
            text
            for row in CONTINUATION_ROWS
            if (text := _condition(grid, row, column))
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
                (
                    fields[field]
                    for field in _PREPARATION_FIELDS
                    if fields[field]
                ),
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


# Table 27's raw grid, shared by the AC and DC selection routes. Column 0 is the AC
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
#: The physical columns carrying the selected test voltages. Their source column numbers are
#: the structural fact; what each selects is stated in wording this file does not copy, so the
#: column axis stays positional.
_TABLE_27_DATA_COLUMNS = (2, 3, 4, 5)


def _table_27_pair() -> tuple[TableAuditSpec, TableAuditSpec]:
    """One AC spec and one DC spec reading Table 27's two parallel row axes."""

    specs: list[TableAuditSpec] = []
    for supply, axis_source_column, data_rows, expected_data_rows in (
        ("ac", 0, _TABLE_27_DATA_ROWS_AC, _TABLE_27_EXPECTED_DATA_ROWS_AC),
        ("dc", 1, _TABLE_27_DATA_ROWS_DC, _TABLE_27_EXPECTED_DATA_ROWS_DC),
    ):
        axis_semantic_id = f"system_voltage_{supply}_v"
        source_columns = (axis_source_column, *_TABLE_27_DATA_COLUMNS)
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
                for source_column in _TABLE_27_DATA_COLUMNS
            ),
        )
        specs.append(
            TableAuditSpec(
                semantic_id=f"{ids.TEST_IMPULSE_SELECTION}.{supply}",
                source_table="27",
                title_anchor="Table 27",
                page_number=_TABLE_27_PAGE,
                clause=_TABLE_27_CLAUSE,
                target_unit="V",
                interpolation="none",
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
                        id=f"table-27-{supply}",
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
    return specs[0], specs[1]


TABLE_27_AC, TABLE_27_DC = _table_27_pair()


VERIFICATION_TABLES: tuple[TableAuditSpec, ...] = (TABLE_26, TABLE_27_AC, TABLE_27_DC)
GRID_PROJECTORS = {ids.TEST_IMPULSE_PROCEDURE: project_impulse_procedure}

__all__ = [
    "CONTINUATION_ROWS",
    "FIELD_ROWS",
    "GRID_PROJECTORS",
    "TABLE_26",
    "TABLE_27_AC",
    "TABLE_27_DC",
    "VARIANT_COLUMNS",
    "VERIFICATION_TABLES",
    "ProcedureStructureError",
    "project_impulse_procedure",
]
