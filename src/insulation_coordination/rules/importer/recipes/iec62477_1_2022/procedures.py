"""IEC 62477-1:2022 test procedure recipes. Layout facts only.

Bounding boxes, row and column counts, header and data row indexes, and column indexes are
measured from the maintained printing. Column names are neutral descriptions written here;
no source subject, condition, heading, note, or clause prose is copied.

The clause 5.2.2 cross-reference matrix lands first, as comparison evidence. It is the only
place the source states whether a requirement is verified by a type, sample or routine test,
so every procedure this module later projects has its declared classification checked against
it. The matrix duplicates what those procedures carry, so it is evidence rather than a rule
the calculator executes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn

from insulation_coordination.domain.rules import (
    ProcedureRule,
    ProcedureStep,
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    RawGrid,
    SemanticProposal,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    StandardIdentity,
    TableAuditSpec,
    TableColumnSpec,
    TableSegmentSpec,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    ProcedureStructureError,
)

#: The matrix is evidence for the procedures, not one of the twenty-five required source
#: items, so it deliberately has no entry in ``semantic_ids``: adding one would claim the
#: package owes a rule for it. Its identifier still follows the same shape, because it names
#: a raw grid a maintainer reviews.
CLASSIFICATION_MATRIX_ID = "iec62477_2022.test.classification_matrix"

_MATRIX_CLAUSE = "5.2.2"
_MATRIX_SOURCE_TABLE = "23"
#: The matrix carries its caption on the first of its three pages and repeats its header row
#: on each. The two continuation pages print no caption, so their layout anchor is the
#: running document header, which is the only text above the grid on those pages. It is
#: matched without the part number's separator: the header prints it as a non-breaking
#: hyphen, which no anchor spelled with an ordinary one ever matches.
_MATRIX_CAPTION_ANCHOR = "Table 23"
_MATRIX_RUNNING_ANCHOR = "IEC 62477"
_MATRIX_COLUMNS = 6
#: (page, raw rows, bbox, logical row offset). Measured; the plan named the second and third
#: segments only, and the first was found by matching column boundaries and the repeated
#: header row across the three pages.
_MATRIX_SEGMENTS: tuple[tuple[int, int, tuple[float, float, float, float], int], ...] = (
    (112, 9, (70.92, 639.24, 524.64, 798.84), 0),
    (113, 36, (70.92, 85.32, 524.64, 791.04), 8),
    (114, 22, (70.92, 85.32, 524.64, 458.28), 43),
)
_MATRIX_RAW_ROWS = sum(rows for _page, rows, _bbox, _offset in _MATRIX_SEGMENTS)
#: Declared apart from the segment row counts so the extraction-time count check is not a
#: tautology against its own input.
_MATRIX_EXPECTED_DATA_ROWS = 64

#: Which classification each mark column carries, in source column order. The classification
#: names are this author's; the source states them in its header row, which stays in the
#: private draft.
CLASSIFICATION_COLUMNS: tuple[tuple[str, int], ...] = (
    ("type_test", 1),
    ("routine_test", 2),
    ("sample_test", 3),
)
#: The column holding the clause reference of the requirement being verified.
REQUIREMENT_CLAUSE_COLUMN = "requirement_clause_reference"
#: The column holding the clause reference of the test that verifies it. A procedure is
#: matched to its matrix row by this column.
TEST_CLAUSE_COLUMN = "test_clause_reference"
_SUBJECT_COLUMN = 0
_REQUIREMENT_SOURCE_COLUMN = 4
_TEST_SOURCE_COLUMN = 5


def _matrix_columns() -> tuple[TableColumnSpec, ...]:
    """The subject column as context, then the three marks and the two clause references.

    Nothing in this grid is a quantity. The subject column is context, so it takes no
    logical coordinate; the remaining five are data, so every mark and every clause
    reference is addressable by row and column.
    """
    return (
        TableColumnSpec(
            semantic_id="verification_subject",
            heading="subject of this row",
            source_column=_SUBJECT_COLUMN,
            role="context",
            unit="1",
        ),
        *(
            TableColumnSpec(
                semantic_id=f"{name}_mark",
                heading=f"whether this row is marked as a {name.replace('_', ' ')}",
                source_column=source_column,
                role="data",
                unit="1",
            )
            for name, source_column in CLASSIFICATION_COLUMNS
        ),
        TableColumnSpec(
            semantic_id=REQUIREMENT_CLAUSE_COLUMN,
            heading="clause reference of the requirement on this row",
            source_column=_REQUIREMENT_SOURCE_COLUMN,
            role="data",
            unit="1",
        ),
        TableColumnSpec(
            semantic_id=TEST_CLAUSE_COLUMN,
            heading="clause reference of the test that verifies it",
            source_column=_TEST_SOURCE_COLUMN,
            role="data",
            unit="1",
        ),
    )


CLASSIFICATION_MATRIX = TableAuditSpec(
    semantic_id=CLASSIFICATION_MATRIX_ID,
    source_table=_MATRIX_SOURCE_TABLE,
    title_anchor=_MATRIX_CAPTION_ANCHOR,
    page_number=_MATRIX_SEGMENTS[0][0],
    clause=_MATRIX_CLAUSE,
    target_unit="1",
    page_search_radius=2,
    expected_raw_rows=_MATRIX_RAW_ROWS,
    expected_raw_columns=_MATRIX_COLUMNS,
    expected_bbox=_MATRIX_SEGMENTS[0][2],
    data_strategy="rectangle",
    data_row_start=1,
    data_column_start=0,
    expected_data_rows=_MATRIX_EXPECTED_DATA_ROWS,
    #: The three marks plus the two clause-reference columns. The subject column is context,
    #: so it takes no logical coordinate and is not counted here.
    expected_data_columns=2 + len(CLASSIFICATION_COLUMNS),
    row_axis_id="verification_row",
    row_axis_unit="1",
    column_axis_id="verification_field",
    column_axis_unit="1",
    assertions=("raw_value_correspondence",),
    segments=tuple(
        TableSegmentSpec(
            id=f"classification-matrix-page-{page}",
            page_number=page,
            title_anchor=(
                _MATRIX_CAPTION_ANCHOR if page == _MATRIX_SEGMENTS[0][0]
                else _MATRIX_RUNNING_ANCHOR
            ),
            expected_raw_rows=rows,
            expected_raw_columns=_MATRIX_COLUMNS,
            expected_bbox=bbox,
            source_columns=tuple(range(_MATRIX_COLUMNS)),
            header_rows=(0,),
            data_rows=tuple(range(1, rows)),
            logical_row_offset=offset,
            page_search_radius=2,
        )
        for page, rows, bbox, offset in _MATRIX_SEGMENTS
    ),
    columns=_matrix_columns(),
    comparison_only=True,
)

#: One spec, three segments. Declared as a tuple so the recipe registers it the way it
#: registers every other family of grids.
CLASSIFICATION_MATRIX_SPECS: tuple[TableAuditSpec, ...] = (CLASSIFICATION_MATRIX,)


def _fail(message: str) -> None:
    raise ProcedureStructureError(f"AMBIGUOUS_TEST_CLASSIFICATION: {message}")


def matrix_classifications(grid: RawGrid) -> Mapping[str, frozenset[str]]:
    """Per test clause reference, the classifications the matrix marks for it.

    A mark cell is read as marked when it holds anything at all. The source uses one glyph
    throughout, so no token vocabulary is declared here -- and a printing that used two
    would still be read as marked rather than guessed at.
    """
    rows: dict[int, dict[str, str]] = {}
    for cell in grid.cells:
        if cell.logical_row is None or cell.logical_column is None:
            continue
        rows.setdefault(cell.logical_row, {})[cell.logical_column] = cell.raw_text.strip()
    marked: dict[str, set[str]] = {}
    for row in rows.values():
        clause = row.get(TEST_CLAUSE_COLUMN, "")
        if not clause:
            continue
        marked.setdefault(clause, set()).update(
            name for name, _column in CLASSIFICATION_COLUMNS if row.get(f"{name}_mark")
        )
    return {clause: frozenset(names) for clause, names in marked.items()}


def validate_classifications(grid: RawGrid, procedure: ProcedureRule) -> None:
    """Refuse a procedure whose declared classification the matrix does not mark.

    The matrix is the only place the source states whether a requirement is verified by a
    type, sample or routine test, so a procedure declaring one the matrix does not carry for
    its clause is two readings of the same document disagreeing. There is no precedence rule
    to apply: it blocks, and a maintainer decides.

    A procedure declaring no classification is not checked here. The matrix cannot say what
    a procedure meant to leave unstated, and Table 30 deliberately declares none.
    """
    declared = frozenset(procedure.classifications)
    if not declared:
        return
    clause = (procedure.source.clause or "").strip()
    by_clause = matrix_classifications(grid)
    if clause not in by_clause:
        _fail(
            f"procedure {procedure.id} declares {sorted(declared)} for clause {clause}, "
            "which the matrix has no row for"
        )
        return
    absent = declared - by_clause[clause]
    if absent:
        _fail(
            f"procedure {procedure.id} declares classification {sorted(absent)} for clause "
            f"{clause}, which the matrix does not mark there"
        )


# --- the procedure clauses ----------------------------------------------------------
#
# Measured with pdfplumber against the licensed document; the x range excludes the licence
# watermark columns at either margin, the same range ``supply.py`` established. Each bbox was
# confirmed by running ``extract_clause_fragment`` against the real page and checking the node
# kind and count before it was written here.

_WORKING_VOLTAGE_CLAUSE = "5.2.3.14"
_INTERNAL_SPD_CLAUSE = "5.2.3.15"

PROCEDURE_CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=ids.TEST_WORKING_VOLTAGE_DETERMINATION,
        clause=_WORKING_VOLTAGE_CLAUSE,
        page_number=142,
        #: The bullets only. The sentence above them states the requirement that refers this
        #: test, and the line below them points at an annex for waveform guidance; neither is
        #: a measurement condition, and including either would merge into a bullet's text.
        expected_bbox=(65.0, 575.0, 535.0, 632.0),
        expected_root_kind="bullets",
        output_kind="procedure",
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_INTERNAL_SPD_MONITORING,
        clause=_INTERNAL_SPD_CLAUSE,
        page_number=142,
        expected_bbox=(65.0, 680.0, 535.0, 730.0),
        expected_root_kind="paragraph",
        output_kind="procedure",
    ),
)

#: Reviewed structural contract per projection: (node kind, node count).
_WORKING_VOLTAGE_SHAPE = ("bullet", 3)
_INTERNAL_SPD_SHAPE = ("paragraph", 1)


def _block(message: str) -> NoReturn:
    raise ProcedureStructureError(f"AMBIGUOUS_PROCEDURE_STRUCTURE: {message}")


def _require_own_fragment(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    semantic_id: str,
    label: str,
) -> None:
    if fragment.id != f"raw-{semantic_id}":
        raise ValueError(f"{label} projection requires its own fragment")
    if (
        fragment.source.standard != identity.standard
        or fragment.source.edition != identity.edition
    ):
        raise ValueError(f"{label} fragment does not match its identified source")


def _require_shape(
    fragment: RawClauseFragment,
    shape: tuple[str, int],
    label: str,
) -> None:
    kind, count = shape
    if len(fragment.nodes) != count or any(node.kind != kind for node in fragment.nodes):
        _block(f"{label} expected {count} reviewed {kind} node(s)")


def _proposal(
    rule: ProcedureRule,
    fragment: RawClauseFragment,
) -> SemanticProposal:
    return SemanticProposal(
        semantic_id=rule.id,
        rule_kind="procedure",
        state="proposed",
        rule_sha256=canonical_model_sha256(rule),
        source_artifact_sha256=canonical_model_sha256(fragment),
    )


def matrix_grid(draft: ImportedRuleDraft, label: str) -> RawGrid:
    """The reviewed classification matrix a procedure's classification is checked against.

    A projection that cannot see the matrix cannot check what it declares, so it blocks
    rather than letting an unchecked classification through.
    """
    grid = next(
        (item for item in draft.raw_grids if item.id == f"raw-{CLASSIFICATION_MATRIX_ID}"),
        None,
    )
    if grid is None:
        _fail(f"{label} cannot check its classification: the matrix grid is absent")
        raise AssertionError  # pragma: no cover - _fail always raises
    return grid


def _steps(fragment: RawClauseFragment) -> tuple[ProcedureStep, ...]:
    """One reviewed node, one step. One source condition is one action."""

    return tuple(
        ProcedureStep(order=order, text=node.raw_text, source=node.source)
        for order, node in enumerate(fragment.nodes, start=1)
    )


def project_working_voltage_determination(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    draft: ImportedRuleDraft,
) -> tuple[tuple[ProcedureRule, ...], tuple[SemanticProposal, ...]]:
    """Project the working-voltage determination clause into a reviewed procedure.

    The clause names the measurement conditions the working voltage is determined against.
    It states no arithmetic, so none is projected: each reviewed bullet becomes one step
    naming one measurement, and a consumer that needs a value performs the measurement.
    """

    label = "working voltage determination"
    _require_own_fragment(fragment, identity, ids.TEST_WORKING_VOLTAGE_DETERMINATION, label)
    _require_shape(fragment, _WORKING_VOLTAGE_SHAPE, label)

    procedure = ProcedureRule(
        id=ids.TEST_WORKING_VOLTAGE_DETERMINATION,
        test_kind="working_voltage_determination",
        classifications=("type_test",),
        procedure_steps=_steps(fragment),
        source=fragment.source,
    )
    validate_classifications(matrix_grid(draft, label), procedure)
    return (procedure,), (_proposal(procedure, fragment),)


def project_internal_spd_monitoring(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    draft: ImportedRuleDraft,
) -> tuple[tuple[ProcedureRule, ...], tuple[SemanticProposal, ...]]:
    """Project the internal transient-limiter monitoring test into a reviewed procedure.

    The source gates this test on the monitoring circuit the supply-side clause already
    describes, and Slice D extracted that clause as its own decision. This procedure
    references it by identifier instead of restating its conditions, so one source
    requirement stays one rule and the two cannot drift apart.
    """

    label = "internal SPD monitoring"
    _require_own_fragment(fragment, identity, ids.TEST_INTERNAL_SPD_MONITORING, label)
    _require_shape(fragment, _INTERNAL_SPD_SHAPE, label)

    procedure = ProcedureRule(
        id=ids.TEST_INTERNAL_SPD_MONITORING,
        test_kind="internal_spd_monitoring",
        classifications=("type_test",),
        procedure_steps=_steps(fragment),
        applicability_rule_id=ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS,
        source=fragment.source,
    )
    validate_classifications(matrix_grid(draft, label), procedure)
    return (procedure,), (_proposal(procedure, fragment),)


CLAUSE_PROJECTORS = {
    ids.TEST_WORKING_VOLTAGE_DETERMINATION: project_working_voltage_determination,
    ids.TEST_INTERNAL_SPD_MONITORING: project_internal_spd_monitoring,
}

__all__ = [
    "CLASSIFICATION_COLUMNS",
    "CLASSIFICATION_MATRIX",
    "CLASSIFICATION_MATRIX_ID",
    "CLASSIFICATION_MATRIX_SPECS",
    "CLAUSE_PROJECTORS",
    "PROCEDURE_CLAUSES",
    "REQUIREMENT_CLAUSE_COLUMN",
    "TEST_CLAUSE_COLUMN",
    "matrix_classifications",
    "matrix_grid",
    "project_internal_spd_monitoring",
    "project_working_voltage_determination",
    "validate_classifications",
]
