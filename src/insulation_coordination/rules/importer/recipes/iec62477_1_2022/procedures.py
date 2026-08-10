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

import re
from collections.abc import Mapping
from typing import NoReturn

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
    ProcedureRule,
    ProcedureStep,
    RuleKind,
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
    ClauseProjector,
    StandardIdentity,
    TableAuditSpec,
    TableColumnSpec,
    TableSegmentSpec,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    FIELD_ROWS,
    VARIANT_COLUMNS,
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
#: The general clause Table 26's preconditioning row defers to, and the identifier of the gate
#: it becomes. Declared here because the spec tuple below names both.
_PRECONDITIONING_GENERAL_CLAUSE = "5.2.3.1"
PRECONDITIONING_APPLICABILITY_ID = f"{ids.TEST_PRECONDITIONING}.applicability"
#: The clause that states the foil geometry, and the clause that states when an accessible
#: surface calls for it. The matrix carries a classification for the first; the second is a
#: sub-clause the matrix does not list separately, and it states a gate rather than a test.
_FOIL_GEOMETRY_CLAUSE = "5.2.3.13.3"
_VOLTAGE_TEST_PERFORMANCE_CLAUSE = "5.2.3.4.4"
FOIL_APPLICABILITY_ID = f"{ids.TEST_ACCESSIBLE_SURFACE_FOIL}.applicability"

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
    ClauseAuditSpec(
        semantic_id=ids.TEST_PRECONDITIONING,
        clause="5.2.3.16",
        page_number=143,
        #: The numbered steps only. The sentence above them states which requirements call for
        #: the test, which is the applicability the general clause below settles.
        expected_bbox=(65.0, 158.0, 535.0, 218.0),
        expected_root_kind="bullets",
        output_kind="procedure",
    ),
    ClauseAuditSpec(
        semantic_id=PRECONDITIONING_APPLICABILITY_ID,
        clause=_PRECONDITIONING_GENERAL_CLAUSE,
        page_number=123,
        #: The general clause's preconditioning paragraph alone. The paragraphs on either side
        #: state the scope of the electrical tests and what may be tested in place of the
        #: complete equipment, neither of which is a preconditioning gate.
        expected_bbox=(65.0, 274.0, 535.0, 310.0),
        expected_root_kind="paragraph",
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_ACCESSIBLE_SURFACE_FOIL,
        clause=_FOIL_GEOMETRY_CLAUSE,
        page_number=142,
        #: The paragraph that states the foil's dimensions, placement and edge distance, and
        #: cites the two figures that illustrate them. The bulleted test voltages further down
        #: the page belong to the surrounding test, not to placing the foil.
        expected_bbox=(65.0, 119.0, 535.0, 190.0),
        expected_root_kind="paragraph",
        output_kind="procedure",
    ),
    ClauseAuditSpec(
        semantic_id=FOIL_APPLICABILITY_ID,
        clause=_VOLTAGE_TEST_PERFORMANCE_CLAUSE,
        page_number=130,
        expected_bbox=(65.0, 142.0, 535.0, 190.0),
        expected_root_kind="paragraph",
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION,
        clause=_VOLTAGE_TEST_PERFORMANCE_CLAUSE,
        page_number=130,
        #: The three conditions only. The sentence introducing them is above the first bullet,
        #: where the extractor drops it rather than merging it into a condition.
        expected_bbox=(65.0, 326.0, 535.0, 378.0),
        expected_root_kind="bullets",
        output_kind="decision",
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
    rule: ProcedureRule | DecisionRule,
    rule_kind: RuleKind,
    fragment: RawClauseFragment,
) -> SemanticProposal:
    return SemanticProposal(
        semantic_id=rule.id,
        rule_kind=rule_kind,
        state="proposed",
        rule_sha256=canonical_model_sha256(rule),
        source_artifact_sha256=canonical_model_sha256(fragment),
    )


def _sibling_grid(draft: ImportedRuleDraft, semantic_id: str, label: str) -> RawGrid:
    """A reviewed grid this projection has to read besides its own fragment.

    A projection that cannot see a source it is required to agree with cannot check the
    agreement, so it blocks rather than proceeding on the one source it can see.
    """
    grid = next((item for item in draft.raw_grids if item.id == f"raw-{semantic_id}"), None)
    if grid is None:
        _block(f"{label} cannot be projected: grid {semantic_id} is absent from the draft")
    return grid


def _sibling_fragment(
    draft: ImportedRuleDraft,
    semantic_id: str,
    label: str,
) -> RawClauseFragment:
    """A reviewed clause fragment this projection has to read besides its own."""

    fragment = next(
        (item for item in draft.raw_clause_fragments if item.id == f"raw-{semantic_id}"),
        None,
    )
    if fragment is None:
        _block(f"{label} cannot be projected: fragment {semantic_id} is absent from the draft")
    return fragment


def matrix_grid(draft: ImportedRuleDraft, label: str) -> RawGrid:
    """The reviewed classification matrix a procedure's classification is checked against."""

    return _sibling_grid(draft, CLASSIFICATION_MATRIX_ID, label)


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
    return (procedure,), (_proposal(procedure, "procedure", fragment),)


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
    return (procedure,), (_proposal(procedure, "procedure", fragment),)


# --- preconditioning ----------------------------------------------------------------

#: The source states preconditioning in three places: a general clause that gates it on what
#: the test is for, a material clause that enumerates the steps, and Table 26's own
#: preconditioning row. The procedure is projected from the material clause, whose row the
#: classification matrix carries; the general clause becomes the applicability decision.
_PRECONDITIONING_SHAPE = ("bullet", 3)
_PRECONDITIONING_GENERAL_SHAPE = ("paragraph", 1)
#: The clause-reference shape of one of this standard's own preconditioning steps. Structural:
#: it matches a clause number and never a step's wording.
_PRECONDITIONING_STEP_REFERENCE = re.compile(r"\b5\.2\.6\.3\.\d+\b")
#: The trailing boundary matters: without it this would also match the material clause's own
#: number, which starts with the general clause's.
_PRECONDITIONING_DEFERRAL = re.compile(r"\b5\.2\.3\.1\b")
#: Which Table 26 row and condition column carry the preconditioning statement. Read from the
#: maintained Table 26 recipe rather than restated, so the two cannot drift apart.
_TABLE_26_PRECONDITIONING_ROW = next(
    row for row, field in FIELD_ROWS if field == "preconditioning"
)
_TABLE_26_FIRST_CONDITION_COLUMN = VARIANT_COLUMNS[0][1]
#: What the general clause's gate discriminates on. The source settles the type test, the
#: sample test, and the acceptance-criteria case; it settles no other, so the decision is not
#: exhaustive.
_PRECONDITIONING_TEST_PURPOSES = ("type_test", "sample_test", "acceptance_criteria")


def _cell_text(grid: RawGrid, row: int, column: int, label: str) -> str:
    cell = next(
        (item for item in grid.cells if (item.row, item.column) == (row, column)),
        None,
    )
    if cell is None:
        _block(f"{label}: grid row {row} column {column} is absent")
    return cell.raw_text.strip()


def _agreed_preconditioning_steps(
    fragment: RawClauseFragment,
    draft: ImportedRuleDraft,
    label: str,
) -> int:
    """How many preconditioning steps all three sources require, or block if they differ.

    The material clause enumerates its steps as reviewed nodes. The general clause names the
    clauses it requires instead of enumerating them. Table 26's preconditioning row states no
    inventory of its own: it defers to the general clause, and this confirms that deferral
    rather than assuming it, because a printing that spelled its own inventory there would be
    a fourth statement of the same requirement.

    There is deliberately no precedence rule. Where the three disagree the projection blocks
    and a maintainer decides which reading the package carries.
    """
    material_steps = len(fragment.nodes)
    general = _sibling_fragment(draft, PRECONDITIONING_APPLICABILITY_ID, label)
    _require_shape(general, _PRECONDITIONING_GENERAL_SHAPE, f"{label} general clause")
    general_steps = len(
        set(_PRECONDITIONING_STEP_REFERENCE.findall(general.nodes[0].raw_text))
    )
    if not general_steps:
        _block(f"{label}: clause {_PRECONDITIONING_GENERAL_CLAUSE} names no preconditioning step")
    row_text = _cell_text(
        _sibling_grid(draft, ids.TEST_IMPULSE_PROCEDURE, label),
        _TABLE_26_PRECONDITIONING_ROW,
        _TABLE_26_FIRST_CONDITION_COLUMN,
        label,
    )
    if not _PRECONDITIONING_DEFERRAL.search(row_text):
        raise ProcedureStructureError(
            f"AMBIGUOUS_PRECONDITIONING_SOURCES: {label}: Table 26 row "
            f"{_TABLE_26_PRECONDITIONING_ROW + 1} does not defer to clause "
            f"{_PRECONDITIONING_GENERAL_CLAUSE}, so its own inventory is a third statement "
            "of the same requirement"
        )
    if material_steps != general_steps:
        raise ProcedureStructureError(
            "AMBIGUOUS_PRECONDITIONING_SOURCES: "
            f"{label}: the material clause enumerates {material_steps} step(s) while clause "
            f"{_PRECONDITIONING_GENERAL_CLAUSE}, which Table 26 row "
            f"{_TABLE_26_PRECONDITIONING_ROW + 1} defers to, names {general_steps}; the three "
            "sources do not agree and no precedence rule is applied"
        )
    return material_steps


def project_preconditioning(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    draft: ImportedRuleDraft,
) -> tuple[tuple[ProcedureRule, ...], tuple[SemanticProposal, ...]]:
    """Project the material preconditioning clause into one reviewed procedure.

    One procedure only, and only when the general clause and Table 26's preconditioning row
    require the same steps it enumerates.
    """

    label = "preconditioning"
    _require_own_fragment(fragment, identity, ids.TEST_PRECONDITIONING, label)
    _require_shape(fragment, _PRECONDITIONING_SHAPE, label)
    _agreed_preconditioning_steps(fragment, draft, label)

    procedure = ProcedureRule(
        id=ids.TEST_PRECONDITIONING,
        test_kind="material_preconditioning",
        classifications=("type_test",),
        procedure_steps=_steps(fragment),
        applicability_rule_id=PRECONDITIONING_APPLICABILITY_ID,
        source=fragment.source,
    )
    validate_classifications(matrix_grid(draft, label), procedure)
    return (procedure,), (_proposal(procedure, "procedure", fragment),)


def project_preconditioning_applicability(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the general clause's preconditioning gate into a decision.

    The general clause settles whether preconditioning is required from what the test is
    for, and nothing else. A purpose it does not settle is left uncovered so a consumer
    blocks rather than inheriting a guessed answer.
    """

    label = "preconditioning applicability"
    _require_own_fragment(fragment, identity, PRECONDITIONING_APPLICABILITY_ID, label)
    _require_shape(fragment, _PRECONDITIONING_GENERAL_SHAPE, label)

    rule = DecisionRule(
        id=PRECONDITIONING_APPLICABILITY_ID,
        inputs=(
            DecisionInput(
                name="test_purpose",
                kind="categorical",
                allowed_values=_PRECONDITIONING_TEST_PURPOSES,
            ),
        ),
        outputs=(DecisionOutput(name="preconditioning_required", kind="boolean"),),
        rows=tuple(
            DecisionRow(
                matchers=(Matcher(input="test_purpose", op="equals", values=(purpose,)),),
                values=(
                    DecisionValue(
                        name="preconditioning_required",
                        boolean=purpose != "acceptance_criteria",
                    ),
                ),
                source=fragment.nodes[0].source,
            )
            for purpose in _PRECONDITIONING_TEST_PURPOSES
        ),
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


# --- accessible insulating surface, foil ---------------------------------------------

_FOIL_SHAPE = ("paragraph", 1)
_FOIL_APPLICABILITY_SHAPE = ("paragraph", 1)
_FIGURE_REFERENCE_PREFIX = "figure-"
#: What the accessible-surface clause permits in place of the classification the matrix marks
#: for the surrounding test. Named as a substitution rather than as a classification of its
#: own: the matrix marks that test as a type and a routine test and does not mark a sample
#: test there, so a procedure declaring one would contradict it. This decision records what
#: the clause permits without making that claim.
_FOIL_SUBSTITUTIONS = ("sample_test_instead_of_routine_test",)


def _figure_references(fragment: RawClauseFragment, label: str) -> str:
    """The figure numbers the reviewed clause cites, in the order it cites them.

    The figures illustrate a geometry the clause also states in prose, so neither is
    digitized. They are kept as a source reference on the step they belong to, which is what
    a maintainer follows to check the placement against the drawing.
    """
    numbers = tuple(
        dict.fromkeys(
            str(token.normalized).removeprefix(_FIGURE_REFERENCE_PREFIX)
            for token in fragment.tokens
            if token.kind == "reference"
            and str(token.normalized).startswith(_FIGURE_REFERENCE_PREFIX)
        )
    )
    if not numbers:
        _block(f"{label} expected the reviewed figure references the clause cites")
    return ", ".join(numbers)


def project_accessible_surface_foil(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    draft: ImportedRuleDraft,
) -> tuple[tuple[ProcedureRule, ...], tuple[SemanticProposal, ...]]:
    """Project the foil placement clause into a reviewed procedure."""

    label = "accessible surface foil"
    _require_own_fragment(fragment, identity, ids.TEST_ACCESSIBLE_SURFACE_FOIL, label)
    _require_shape(fragment, _FOIL_SHAPE, label)
    figures = _figure_references(fragment, label)

    procedure = ProcedureRule(
        id=ids.TEST_ACCESSIBLE_SURFACE_FOIL,
        test_kind="accessible_surface_foil_placement",
        classifications=("type_test",),
        procedure_steps=(
            ProcedureStep(
                order=1,
                text=fragment.nodes[0].raw_text,
                source=fragment.nodes[0].source.model_copy(update={"figure": figures}),
            ),
        ),
        applicability_rule_id=FOIL_APPLICABILITY_ID,
        # The rule itself is a clause, not a figure: only the step that places the foil cites
        # the drawings, so only that step carries them.
        source=fragment.source,
    )
    validate_classifications(matrix_grid(draft, label), procedure)
    return (procedure,), (_proposal(procedure, "procedure", fragment),)


def project_accessible_surface_foil_applicability(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the accessible-surface gate for the foil into a decision.

    The clause states what to do where a non-conductive accessible surface covers the
    equipment. It states nothing about equipment without one, so that case is left uncovered
    rather than read as a permission to skip the test.
    """

    label = "accessible surface foil applicability"
    _require_own_fragment(fragment, identity, FOIL_APPLICABILITY_ID, label)
    _require_shape(fragment, _FOIL_APPLICABILITY_SHAPE, label)

    rule = DecisionRule(
        id=FOIL_APPLICABILITY_ID,
        inputs=(DecisionInput(name="non_conductive_accessible_surface_present", kind="boolean"),),
        outputs=(
            DecisionOutput(name="foil_wrap_required", kind="boolean"),
            DecisionOutput(
                name="permitted_classification_substitution",
                kind="categorical",
                allowed_values=_FOIL_SUBSTITUTIONS,
            ),
        ),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(
                        input="non_conductive_accessible_surface_present",
                        op="equals",
                        boolean=True,
                    ),
                ),
                values=(
                    DecisionValue(name="foil_wrap_required", boolean=True),
                    DecisionValue(
                        name="permitted_classification_substitution",
                        categorical=_FOIL_SUBSTITUTIONS[0],
                    ),
                ),
                source=fragment.nodes[0].source,
            ),
        ),
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


# --- assembled-equipment routine test exemption ---------------------------------------

_EXEMPTION_SHAPE = ("bullet", 3)
#: One input per reviewed condition, in source order. Neutral descriptions of what each
#: condition asks about; the source states them as prose this file does not copy.
_EXEMPTION_CONDITIONS = (
    "sub_assembly_routine_test_performed",
    "assembly_shown_not_to_compromise_insulation",
    "assembled_type_test_passed",
)


def project_assembled_routine_exemption(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the routine-test exemption for assembled equipment into a decision.

    The source grants the exemption only where every one of its conditions holds. The rule
    therefore carries exactly one row, the one the source states, and is not exhaustive: a
    combination the source does not settle -- including one where a condition is simply not
    known -- resolves to nothing, so a consumer blocks instead of reading silence as exempt.
    """

    label = "assembled routine exemption"
    _require_own_fragment(fragment, identity, ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION, label)
    _require_shape(fragment, _EXEMPTION_SHAPE, label)
    if len(_EXEMPTION_CONDITIONS) != _EXEMPTION_SHAPE[1]:  # pragma: no cover - guards the pair
        _block(f"{label} declares a different number of inputs than reviewed conditions")

    rule = DecisionRule(
        id=ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION,
        inputs=tuple(
            DecisionInput(name=condition, kind="boolean") for condition in _EXEMPTION_CONDITIONS
        ),
        outputs=(DecisionOutput(name="assembled_routine_test_exempt", kind="boolean"),),
        rows=(
            DecisionRow(
                matchers=tuple(
                    Matcher(input=condition, op="equals", boolean=True)
                    for condition in _EXEMPTION_CONDITIONS
                ),
                values=(DecisionValue(name="assembled_routine_test_exempt", boolean=True),),
                source=fragment.source,
            ),
        ),
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


CLAUSE_PROJECTORS: Mapping[str, ClauseProjector] = {
    ids.TEST_WORKING_VOLTAGE_DETERMINATION: project_working_voltage_determination,
    ids.TEST_INTERNAL_SPD_MONITORING: project_internal_spd_monitoring,
    ids.TEST_PRECONDITIONING: project_preconditioning,
    PRECONDITIONING_APPLICABILITY_ID: project_preconditioning_applicability,
    ids.TEST_ACCESSIBLE_SURFACE_FOIL: project_accessible_surface_foil,
    FOIL_APPLICABILITY_ID: project_accessible_surface_foil_applicability,
    ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION: project_assembled_routine_exemption,
}

__all__ = [
    "CLASSIFICATION_COLUMNS",
    "CLASSIFICATION_MATRIX",
    "CLASSIFICATION_MATRIX_ID",
    "CLASSIFICATION_MATRIX_SPECS",
    "CLAUSE_PROJECTORS",
    "FOIL_APPLICABILITY_ID",
    "PRECONDITIONING_APPLICABILITY_ID",
    "PROCEDURE_CLAUSES",
    "REQUIREMENT_CLAUSE_COLUMN",
    "TEST_CLAUSE_COLUMN",
    "matrix_classifications",
    "matrix_grid",
    "project_accessible_surface_foil",
    "project_accessible_surface_foil_applicability",
    "project_assembled_routine_exemption",
    "project_internal_spd_monitoring",
    "project_preconditioning",
    "project_preconditioning_applicability",
    "project_working_voltage_determination",
    "validate_classifications",
]
