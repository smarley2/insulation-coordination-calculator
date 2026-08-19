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
from typing import Literal, NoReturn

from insulation_coordination.domain.rules import (
    MAX_APPLICABILITY_LENGTH,
    MAX_REFERENCE_TEXT_LENGTH,
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    EquivalenceMeasure,
    Matcher,
    PermittedAlternative,
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
    ClauseSegmentSpec,
    StandardIdentity,
    TableAuditSpec,
    TableColumnSpec,
    TableSegmentSpec,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    DIELECTRIC_PURPOSES,
    FIELD_ROWS,
    VARIANT_COLUMNS,
    ProcedureStructureError,
)

#: The matrix is evidence for the procedures, not one of the required source
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
                _MATRIX_CAPTION_ANCHOR if page == _MATRIX_SEGMENTS[0][0] else _MATRIX_RUNNING_ANCHOR
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
#: The material clause. Named here because the gate reads the matrix row for it.
_PRECONDITIONING_MATERIAL_CLAUSE = "5.2.3.16"
PRECONDITIONING_APPLICABILITY_ID = f"{ids.TEST_PRECONDITIONING}.applicability"
#: Preconditioning has two routes under one required inventory item, because its two source
#: clauses carry two different gates: the general clause governs the electrical tests, the
#: material clause the solid-insulation and material requirements. They legitimately state
#: different step inventories, and one identifier cannot carry both readings. That the two
#: gates are distinct is the maintainer's decision, recorded here rather than inferred.
PRECONDITIONING_ELECTRICAL_ID = f"{ids.TEST_PRECONDITIONING}.electrical_tests"
PRECONDITIONING_MATERIAL_ID = f"{ids.TEST_PRECONDITIONING}.material"
#: The clause that performs the AC or DC voltage test. One paragraph of it states both when a
#: non-conductive accessible surface calls for the foil and what the test does once it is
#: wrapped, so the gate and the procedure are two readings of one paragraph and share one
#: fragment. The mandrel test's own foil, which is placed on a thin-sheet specimen after the
#: rotation, is a different requirement that happens to involve foil: it belongs to the
#: thin-sheet procedure, which is not one of the required items and is not extracted here.
_VOLTAGE_TEST_PERFORMANCE_CLAUSE = "5.2.3.4.4"
FOIL_APPLICABILITY_ID = f"{ids.TEST_ACCESSIBLE_SURFACE_FOIL}.applicability"
#: The clause permitting a voltage test in place of the impulse withstand test.
_IMPULSE_ALTERNATIVE_CLAUSE = "5.2.3.3"
#: One route per permitted alternative, because the engineer chooses between them and a choice
#: needs something to name. The suffixes are the tokens the project's own stored selection uses,
#: so a consumer joins a saved choice to its rule without a translation table in between.
IMPULSE_ALTERNATIVE_AC_ID = f"{ids.TEST_IMPULSE_ALTERNATIVE}.ac_voltage_test"
IMPULSE_ALTERNATIVE_DC_ID = f"{ids.TEST_IMPULSE_ALTERNATIVE}.dc_voltage_test"
#: The remaining subclauses of the AC or DC voltage test. The performance subclause is the one
#: ``_VOLTAGE_TEST_PERFORMANCE_CLAUSE`` above already names; the other three are its siblings.
_DIELECTRIC_DISCONNECTION_CLAUSE = "5.2.3.4.3"
_DIELECTRIC_DURATION_CLAUSE = "5.2.3.4.5"
_DIELECTRIC_ACCEPTANCE_CLAUSE = "5.2.3.4.6"

PROCEDURE_CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=ids.TEST_WORKING_VOLTAGE_DETERMINATION,
        clause=_WORKING_VOLTAGE_CLAUSE,
        #: The bullets only. The sentence above them states the requirement that refers this
        #: test, and the line below them points at an annex for waveform guidance; neither is
        #: a measurement condition, and including either would merge into a bullet's text.
        segments=(
            ClauseSegmentSpec(
                page_number=142,
                expected_bbox=(65.0, 575.0, 535.0, 632.0),
                expected_root_kind="bullets",
            ),
        ),
        output_kind="procedure",
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_INTERNAL_SPD_MONITORING,
        clause=_INTERNAL_SPD_CLAUSE,
        segments=(
            ClauseSegmentSpec(
                page_number=142,
                expected_bbox=(65.0, 680.0, 535.0, 730.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="procedure",
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_PRECONDITIONING,
        clause=_PRECONDITIONING_MATERIAL_CLAUSE,
        #: The numbered steps only. The sentence above them states which requirements call for
        #: the test, which is the applicability the general clause below settles.
        segments=(
            ClauseSegmentSpec(
                page_number=143,
                expected_bbox=(65.0, 158.0, 535.0, 218.0),
                expected_root_kind="bullets",
            ),
        ),
        output_kind="procedure",
        projected_rule_ids=(PRECONDITIONING_MATERIAL_ID,),
    ),
    ClauseAuditSpec(
        semantic_id=PRECONDITIONING_APPLICABILITY_ID,
        clause=_PRECONDITIONING_GENERAL_CLAUSE,
        #: The general clause's preconditioning paragraph alone. The paragraphs on either side
        #: state the scope of the electrical tests and what may be tested in place of the
        #: complete equipment, neither of which is a preconditioning gate.
        segments=(
            ClauseSegmentSpec(
                page_number=123,
                expected_bbox=(65.0, 274.0, 535.0, 310.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        #: This clause states both the gate and the electrical tests' own step inventory, so
        #: it projects the gate under its own identifier and that route beside it.
        projected_rule_ids=(PRECONDITIONING_ELECTRICAL_ID,),
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_ACCESSIBLE_SURFACE_FOIL,
        clause=_VOLTAGE_TEST_PERFORMANCE_CLAUSE,
        #: The accessible-surface paragraph alone. The paragraph above it states what may be
        #: bridged or disconnected before testing and the one below what an opening permits,
        #: neither of which concerns an accessible surface.
        segments=(
            ClauseSegmentSpec(
                page_number=130,
                expected_bbox=(65.0, 142.0, 535.0, 190.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="procedure",
        #: The same paragraph states the gate, so this spec projects it beside the procedure
        #: rather than extracting the paragraph twice.
        projected_rule_ids=(FOIL_APPLICABILITY_ID,),
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION,
        clause=_VOLTAGE_TEST_PERFORMANCE_CLAUSE,
        #: The three conditions only. The sentence introducing them is above the first bullet,
        #: where the extractor drops it rather than merging it into a condition.
        segments=(
            ClauseSegmentSpec(
                page_number=130,
                expected_bbox=(65.0, 326.0, 535.0, 378.0),
                expected_root_kind="bullets",
            ),
        ),
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_IMPULSE_ALTERNATIVE,
        clause=_IMPULSE_ALTERNATIVE_CLAUSE,
        #: Four regions of running prose, one per paragraph, because a paragraph region is one
        #: node: the permission, the first alternative's modification, the second's, and the
        #: ramp allowance. Declared apart rather than as one region so each reading stays its
        #: own node -- merged, the two alternatives would share one text and neither could be
        #: attributed to the choice it belongs to.
        #:
        #: The subclause's closing line is deliberately outside every region. It points at
        #: another standard for further information and states no modification, so extracting
        #: it would add a fifth node this recipe would then have to drop.
        segments=tuple(
            ClauseSegmentSpec(
                page_number=125,
                expected_bbox=bbox,
                expected_root_kind="paragraph",
            )
            for bbox in (
                (65.0, 500.0, 535.0, 543.0),
                (65.0, 548.0, 535.0, 581.0),
                (65.0, 586.0, 535.0, 619.0),
                (65.0, 624.0, 535.0, 646.0),
            )
        ),
        output_kind="procedure",
        projected_rule_ids=(IMPULSE_ALTERNATIVE_AC_ID, IMPULSE_ALTERNATIVE_DC_ID),
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_DIELECTRIC_DISCONNECTION,
        clause=_DIELECTRIC_DISCONNECTION_CLAUSE,
        #: Four regions of running prose, one per paragraph, for the reason the permitted
        #: alternative's four are declared apart: a paragraph region extracts as one node, and
        #: merged the four obligations would share one text no step could be attributed to.
        #: The subclause's heading is above the first region and is not extracted.
        segments=tuple(
            ClauseSegmentSpec(
                page_number=128,
                expected_bbox=bbox,
                expected_root_kind="paragraph",
            )
            for bbox in (
                (65.0, 390.0, 535.0, 443.0),
                (65.0, 451.0, 535.0, 493.0),
                (65.0, 501.0, 535.0, 554.0),
                (65.0, 562.0, 535.0, 604.0),
            )
        ),
        output_kind="procedure",
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION,
        clause=_VOLTAGE_TEST_PERFORMANCE_CLAUSE,
        #: Three regions. The first is the lead-in sentence and the first two items of the
        #: subclause's list; the second is the third item, which begins the next page and runs
        #: on into the prose qualifying it; the third is the sentence, below the figure, that
        #: states when the test is not made at all. What lies between the second and third --
        #: the figure itself and the enclosure condition -- states no electrode pair and no
        #: column, so neither is inside a region.
        segments=(
            ClauseSegmentSpec(
                page_number=128,
                expected_bbox=(65.0, 632.0, 535.0, 787.0),
                expected_root_kind="bullets",
            ),
            ClauseSegmentSpec(
                page_number=129,
                expected_bbox=(65.0, 84.0, 535.0, 245.0),
                expected_root_kind="bullets",
            ),
            ClauseSegmentSpec(
                page_number=129,
                expected_bbox=(65.0, 730.0, 535.0, 761.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_DIELECTRIC_APPLICATION_DURATION,
        clause=_DIELECTRIC_DURATION_CLAUSE,
        segments=(
            ClauseSegmentSpec(
                page_number=130,
                expected_bbox=(65.0, 405.0, 535.0, 437.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="procedure",
    ),
    ClauseAuditSpec(
        semantic_id=ids.TEST_DIELECTRIC_ACCEPTANCE,
        clause=_DIELECTRIC_ACCEPTANCE_CLAUSE,
        segments=(
            ClauseSegmentSpec(
                page_number=130,
                expected_bbox=(65.0, 465.0, 535.0, 486.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
)

#: Reviewed structural contract per projection: the node kind expected at each position, in
#: order -- the same contract ``supply.py``'s ``_require_shape`` uses, so a clause spec fed a
#: second physical segment gets a shape refusal from either module instead of a
#: ``(kind, count)`` pair's ``ValueError: too many values to unpack``.
_WORKING_VOLTAGE_SHAPE = ("bullet",) * 3
_INTERNAL_SPD_SHAPE = ("paragraph",) * 1


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
    if fragment.source.standard != identity.standard or fragment.source.edition != identity.edition:
        raise ValueError(f"{label} fragment does not match its identified source")


def _require_shape(
    fragment: RawClauseFragment,
    shape: tuple[str, ...],
    label: str,
) -> None:
    if tuple(node.kind for node in fragment.nodes) != shape:
        _block(f"{label} expected {len(shape)} reviewed node(s) of kinds {shape}")


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
    _confirmed_facts: object = None,
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
    _confirmed_facts: object = None,
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
        # The monitoring route specifically: the bare identifier stopped being projected when
        # the reduction rule split into a route per supply kind, and monitoring is the
        # obligation this test is gated on.
        applicability_rule_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",
        source=fragment.source,
    )
    validate_classifications(matrix_grid(draft, label), procedure)
    return (procedure,), (_proposal(procedure, "procedure", fragment),)


# --- preconditioning ----------------------------------------------------------------

#: The source states preconditioning in three places: a general clause that gates it on what
#: the test is for and names the steps the electrical tests take, a material clause that
#: enumerates the steps the solid-insulation and material requirements take, and Table 26's
#: preconditioning row, which defers to the general clause.
#:
#: The two clauses carry two gates, so they legitimately name different inventories, and the
#: package carries one route per clause under the single required inventory item. There is
#: still no precedence rule: what blocks is a clause whose own inventory does not have the
#: shape this recipe declares for it, and Table 26 stating an inventory of its own instead of
#: deferring.
_PRECONDITIONING_SHAPE = ("bullet",) * 3
_PRECONDITIONING_GENERAL_SHAPE = ("paragraph",) * 1
#: How many preconditioning clauses the general clause names. Reviewed against the document.
_PRECONDITIONING_ELECTRICAL_STEPS = 2
#: The clause-reference shape of one of this standard's own preconditioning steps. Structural:
#: it matches a clause number and never a step's wording.
_PRECONDITIONING_STEP_REFERENCE = re.compile(r"\b5\.2\.6\.3\.\d+\b")
#: The trailing boundary matters: without it this would also match the material clause's own
#: number, which starts with the general clause's.
_PRECONDITIONING_DEFERRAL = re.compile(r"\b5\.2\.3\.1\b")
#: Which Table 26 row and condition column carry the preconditioning statement. Read from the
#: maintained Table 26 recipe rather than restated, so the two cannot drift apart.
_TABLE_26_PRECONDITIONING_ROW = next(row for row, field in FIELD_ROWS if field == "preconditioning")
_TABLE_26_FIRST_CONDITION_COLUMN = VARIANT_COLUMNS[0][1]
#: What the general clause's gate discriminates on. The source settles the type test, the
#: sample test, and the acceptance-criteria case; it settles no other, so the decision is not
#: exhaustive.
_PRECONDITIONING_TEST_PURPOSES = ("type_test", "sample_test", "acceptance_criteria")
#: Which of the two clauses' gates a request falls under. Neutral names for what each clause
#: governs; the gate selects the route from this, so a consumer never has to know that the
#: source states preconditioning twice.
_PRECONDITIONING_ELECTRICAL_CONTEXT = "electrical_test"
#: The requirements the material clause states it is invoked by. It applies when one of them
#: requires it and nowhere else, so the gate discriminates on which one is being met rather
#: than on a label for material work in general, which would make the clause universal. The
#: cross-reference matrix lists the same three against this clause, and the gate refuses to be
#: projected if a printing stops doing so.
MATERIAL_PRECONDITIONING_INVOCATIONS = ("4.4.7.8.4.2", "4.4.7.8.4.3", "4.4.7.9")
#: One context per invoking requirement. A consumer names the requirement it is meeting; a
#: request that names none of them matches no row, so nothing is preconditioned by default.
PRECONDITIONING_MATERIAL_CONTEXTS = tuple(
    f"solid_insulation_requirement_{clause}" for clause in MATERIAL_PRECONDITIONING_INVOCATIONS
)
_PRECONDITIONING_TEST_CONTEXTS = (
    _PRECONDITIONING_ELECTRICAL_CONTEXT,
    *PRECONDITIONING_MATERIAL_CONTEXTS,
)
_PRECONDITIONING_ROUTES = (PRECONDITIONING_ELECTRICAL_ID, PRECONDITIONING_MATERIAL_ID)
#: A clause reference as the matrix prints one in its requirement column. Structural: it
#: matches a clause number and never a requirement's wording.
_REQUIREMENT_REFERENCE = re.compile(r"\b\d+(?:\.\d+)+\b")


def _cell_text(grid: RawGrid, row: int, column: int, label: str) -> str:
    cell = next(
        (item for item in grid.cells if (item.row, item.column) == (row, column)),
        None,
    )
    if cell is None:
        _block(f"{label}: grid row {row} column {column} is absent")
    return cell.raw_text.strip()


def _require_table_26_defers(draft: ImportedRuleDraft, label: str) -> None:
    """Confirm Table 26's preconditioning row defers rather than stating its own inventory.

    Table 26's tests are electrical tests, so its row points at the general clause instead of
    enumerating steps. A printing that spelled an inventory there would be a third statement
    of the same requirement, which no route could carry, so it blocks.
    """
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


def _require_matrix_names_the_invocations(draft: ImportedRuleDraft, label: str) -> None:
    """Confirm the matrix lists the requirements this recipe reviewed as invoking the clause.

    The material clause applies when one of a few named requirements calls for it, and the gate
    keys its rows on exactly those. The matrix states the same relation in its requirement
    column, so a printing that names a different set means the gate would silently answer for
    the wrong requirements, and it blocks instead.
    """
    grid = matrix_grid(draft, label)
    rows: dict[int, dict[str, str]] = {}
    for cell in grid.cells:
        if cell.logical_row is None or cell.logical_column is None:
            continue
        rows.setdefault(cell.logical_row, {})[cell.logical_column] = cell.raw_text.strip()
    listed = frozenset(
        reference
        for row in rows.values()
        if row.get(TEST_CLAUSE_COLUMN) == _PRECONDITIONING_MATERIAL_CLAUSE
        for reference in _REQUIREMENT_REFERENCE.findall(row.get(REQUIREMENT_CLAUSE_COLUMN, ""))
    )
    if listed != frozenset(MATERIAL_PRECONDITIONING_INVOCATIONS):
        raise ProcedureStructureError(
            f"AMBIGUOUS_PRECONDITIONING_SOURCES: {label}: the matrix lists "
            f"{len(listed)} requirement(s) invoking clause {_PRECONDITIONING_MATERIAL_CLAUSE} "
            f"where this recipe reviewed {sorted(MATERIAL_PRECONDITIONING_INVOCATIONS)}"
        )


def _electrical_preconditioning_steps(
    fragment: RawClauseFragment,
    label: str,
) -> tuple[ProcedureStep, ...]:
    """One step per preconditioning clause the general clause names.

    The general clause states its inventory by reference rather than by enumeration, so each
    named clause becomes one step. The step text is written here and names only the clause
    number; the reviewed paragraph it came from stays the step's source.
    """
    node = fragment.nodes[0]
    named = tuple(dict.fromkeys(_PRECONDITIONING_STEP_REFERENCE.findall(node.raw_text)))
    if len(named) != _PRECONDITIONING_ELECTRICAL_STEPS:
        raise ProcedureStructureError(
            f"AMBIGUOUS_PRECONDITIONING_SOURCES: {label}: clause "
            f"{_PRECONDITIONING_GENERAL_CLAUSE} names {len(named)} preconditioning clause(s) "
            f"where this recipe reviewed {_PRECONDITIONING_ELECTRICAL_STEPS}"
        )
    return tuple(
        ProcedureStep(
            order=order,
            text=f"perform the preconditioning of clause {clause}",
            source=node.source,
        )
        for order, clause in enumerate(named, start=1)
    )


def project_preconditioning(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    draft: ImportedRuleDraft,
    _confirmed_facts: object = None,
) -> tuple[tuple[ProcedureRule, ...], tuple[SemanticProposal, ...]]:
    """Project the material clause into the material preconditioning route.

    This route carries the steps the material clause enumerates, which are the ones the
    solid-insulation and material requirements take. The electrical tests take the general
    clause's route instead, and the applicability gate says which of the two applies.
    """

    label = "preconditioning"
    _require_own_fragment(fragment, identity, ids.TEST_PRECONDITIONING, label)
    _require_shape(fragment, _PRECONDITIONING_SHAPE, label)
    _require_table_26_defers(draft, label)

    procedure = ProcedureRule(
        id=PRECONDITIONING_MATERIAL_ID,
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
    draft: ImportedRuleDraft,
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule | ProcedureRule, ...], tuple[SemanticProposal, ...]]:
    """Project the general clause into the gate and the electrical-tests route.

    The general clause settles two things: whether preconditioning is required, from what the
    test is for, and which steps the electrical tests take. The gate carries the first and
    names the route that carries the second, so a consumer asks one rule and is told which
    procedure to follow. A test purpose the source does not settle is left uncovered, so a
    consumer blocks rather than inheriting a guessed answer.

    The material route is gated the way its own clause states it: it applies when one of the
    requirements that clause names calls for it, so the gate carries one row per named
    requirement. Material work that none of those requirements calls for is left uncovered
    too: the material clause is invoked, not universal.

    The electrical route declares no classification: the cross-reference matrix has no row
    for this clause, and a classification it does not carry would be this recipe's invention.
    """

    label = "preconditioning applicability"
    _require_own_fragment(fragment, identity, PRECONDITIONING_APPLICABILITY_ID, label)
    _require_shape(fragment, _PRECONDITIONING_GENERAL_SHAPE, label)
    _require_table_26_defers(draft, label)
    _require_matrix_names_the_invocations(draft, label)

    rule = DecisionRule(
        id=PRECONDITIONING_APPLICABILITY_ID,
        inputs=(
            DecisionInput(
                name="test_context",
                kind="categorical",
                allowed_values=_PRECONDITIONING_TEST_CONTEXTS,
            ),
            DecisionInput(
                name="test_purpose",
                kind="categorical",
                allowed_values=_PRECONDITIONING_TEST_PURPOSES,
            ),
        ),
        outputs=(
            DecisionOutput(name="preconditioning_required", kind="boolean"),
            DecisionOutput(
                name="preconditioning_procedure_rule_id",
                kind="categorical",
                allowed_values=_PRECONDITIONING_ROUTES,
            ),
        ),
        rows=(
            *(
                DecisionRow(
                    matchers=(
                        Matcher(
                            input="test_context",
                            op="equals",
                            values=(_PRECONDITIONING_ELECTRICAL_CONTEXT,),
                        ),
                        Matcher(input="test_purpose", op="equals", values=(purpose,)),
                    ),
                    values=(
                        DecisionValue(
                            name="preconditioning_required",
                            boolean=purpose != "acceptance_criteria",
                        ),
                        DecisionValue(
                            name="preconditioning_procedure_rule_id",
                            categorical=PRECONDITIONING_ELECTRICAL_ID,
                        ),
                    ),
                    source=fragment.nodes[0].source,
                )
                for purpose in _PRECONDITIONING_TEST_PURPOSES
            ),
            # One row per requirement the material clause states it is invoked by. The clause
            # states its steps for those requirements without qualifying them by what the test
            # is for, so each row matches on the context alone rather than reading the general
            # clause's exemption across the gate.
            *(
                DecisionRow(
                    matchers=(Matcher(input="test_context", op="equals", values=(context,)),),
                    values=(
                        DecisionValue(name="preconditioning_required", boolean=True),
                        DecisionValue(
                            name="preconditioning_procedure_rule_id",
                            categorical=PRECONDITIONING_MATERIAL_ID,
                        ),
                    ),
                    source=fragment.nodes[0].source,
                )
                for context in PRECONDITIONING_MATERIAL_CONTEXTS
            ),
        ),
        exhaustive=False,
        source=fragment.source,
    )
    procedure = ProcedureRule(
        id=PRECONDITIONING_ELECTRICAL_ID,
        test_kind="electrical_test_preconditioning",
        procedure_steps=_electrical_preconditioning_steps(fragment, label),
        applicability_rule_id=PRECONDITIONING_APPLICABILITY_ID,
        source=fragment.source,
    )
    validate_classifications(matrix_grid(draft, label), procedure)
    return (rule, procedure), (
        _proposal(rule, "decision", fragment),
        _proposal(procedure, "procedure", fragment),
    )


# --- accessible insulating surface, foil ---------------------------------------------

_FOIL_SHAPE = ("paragraph",) * 1
#: What the accessible-surface clause permits in place of the classification the matrix marks
#: for the surrounding test. Named as a substitution rather than as a classification of its
#: own: the matrix marks that test as a type and a routine test and does not mark a sample
#: test there, so a procedure declaring one would contradict it. This decision records what
#: the clause permits without making that claim.
_FOIL_SUBSTITUTIONS = ("sample_test_instead_of_routine_test",)


def project_accessible_surface_foil(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[ProcedureRule | DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the accessible-surface paragraph into the foil procedure and its gate.

    The paragraph states one requirement: where a non-conductive accessible surface covers the
    equipment, conductive foil is wrapped around that surface and the voltage test is performed
    against it, and the test between a circuit and the surface may then be a sample test in
    place of a routine test. The gate carries the condition and what it permits, the procedure
    the action. Equipment without such a surface is left uncovered rather than read as a
    permission to skip the test.

    The procedure declares no classification. The cross-reference matrix has no row for this
    sub-clause, so any classification here would be this recipe's invention -- which is also
    why the permitted sample test is modelled as a substitution the gate records.
    """

    label = "accessible surface foil"
    _require_own_fragment(fragment, identity, ids.TEST_ACCESSIBLE_SURFACE_FOIL, label)
    _require_shape(fragment, _FOIL_SHAPE, label)

    procedure = ProcedureRule(
        id=ids.TEST_ACCESSIBLE_SURFACE_FOIL,
        test_kind="accessible_surface_foil_placement",
        procedure_steps=_steps(fragment),
        applicability_rule_id=FOIL_APPLICABILITY_ID,
        source=fragment.source,
    )
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
    return (procedure, rule), (
        _proposal(procedure, "procedure", fragment),
        _proposal(rule, "decision", fragment),
    )


# --- assembled-equipment routine test exemption ---------------------------------------

_EXEMPTION_SHAPE = ("bullet",) * 3
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
    _confirmed_facts: object = None,
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
    if len(_EXEMPTION_CONDITIONS) != len(_EXEMPTION_SHAPE):  # pragma: no cover - guards the count
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


# --- the permitted alternative to the impulse withstand test --------------------------

_IMPULSE_ALTERNATIVE_SHAPE = ("paragraph",) * 4
#: Which node states the permission -- what the alternative may be used for, and which test it
#: may be used instead of. Shared by both routes, because the source states it once for both.
_IMPULSE_ALTERNATIVE_PERMISSION_NODE = 0
#: Which node states the ramp allowance. Shared for the same reason.
_IMPULSE_ALTERNATIVE_RAMP_NODE = 3
#: One entry per permitted alternative, in source order: the node stating its modification, the
#: route it is projected under, what kind of test it is, and which measure of its own voltage
#: carries the equivalence the source states. Positional first -- the node index is the
#: structural fact -- and the remaining three are neutral identifiers for what that node is
#: about, never its wording. The measure is the one thing here that is not a layout fact, and
#: it is the same class of reading as Table 26's condition columns: which of two named measures
#: a paragraph is about, recorded as a token rather than copied as text.
IMPULSE_ALTERNATIVE_VARIANTS: tuple[tuple[int, str, str, EquivalenceMeasure], ...] = (
    (1, IMPULSE_ALTERNATIVE_AC_ID, "ac_voltage_test", "peak"),
    (2, IMPULSE_ALTERNATIVE_DC_ID, "dc_voltage_test", "average"),
)


def project_impulse_alternative(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[ProcedureRule, ...], tuple[SemanticProposal, ...]]:
    """Project the alternative to the impulse withstand test into one procedure per method.

    The subclause permits a voltage test in place of the impulse withstand test, states one
    modification per method, and states one ramp allowance covering both. So it projects two
    procedures rather than one: the engineer selects a method, and a single rule carrying both
    modifications would leave that selection nothing to name.

    Each route declares what makes it usable as a substitute -- the test it replaces, and the
    measure of its own voltage that the replaced test's voltage must equal. Neither is derived:
    which test is replaced is stated by the permission node the recipe declares, and the measure
    is the variant. **No voltage is read here at all**; the equivalence names the rule that
    resolves one.

    The application pattern -- how many times, for how long, in which polarity -- stays in the
    reviewed step. The source states it as one sentence per method, and splitting that sentence
    into ``repetitions``, ``duration`` and ``polarity`` would mean parsing licensed prose in
    public code; those fields stay open for a source that states them separately.

    Neither route declares a classification, for the reason the accessible-surface procedure
    declares none: the cross-reference matrix has no row for this subclause, so a classification
    here would be this recipe's invention. A consumer needing one reads it from the test named
    in ``instead_of_rule_id``, which is the test this one is performed in place of.
    """

    label = "impulse alternative"
    _require_own_fragment(fragment, identity, ids.TEST_IMPULSE_ALTERNATIVE, label)
    _require_shape(fragment, _IMPULSE_ALTERNATIVE_SHAPE, label)

    permission = fragment.nodes[_IMPULSE_ALTERNATIVE_PERMISSION_NODE].raw_text
    ramp = fragment.nodes[_IMPULSE_ALTERNATIVE_RAMP_NODE].raw_text.strip()
    rules: list[ProcedureRule] = []
    proposals: list[SemanticProposal] = []
    for node_index, rule_id, test_kind, measure in IMPULSE_ALTERNATIVE_VARIANTS:
        node = fragment.nodes[node_index]
        rule = ProcedureRule(
            id=rule_id,
            test_kind=test_kind,
            procedure_steps=(ProcedureStep(order=1, text=node.raw_text, source=node.source),),
            # What the substitution may be used to verify, which is the same question every
            # other procedure answers here. Truncated the way Table 26's continuations are:
            # a reflowed printing must not turn a reading into a validation error.
            applicability=permission[:MAX_APPLICABILITY_LENGTH],
            permitted_alternative=PermittedAlternative(
                # The whole test rather than one of its variants: the permission is stated
                # over the impulse withstand test, not over the insulation it is performed for.
                instead_of_rule_id=ids.TEST_IMPULSE_PROCEDURE,
                equivalent_measure=measure,
                equivalent_to_rule_id=ids.TEST_IMPULSE_SELECTION,
                ramp=ramp[:MAX_REFERENCE_TEXT_LENGTH] or None,
            ),
            source=fragment.source,
        )
        rules.append(rule)
        proposals.append(_proposal(rule, "procedure", fragment))
    return tuple(rules), tuple(proposals)


# --- the body of the AC or DC voltage test ---------------------------------------------
#
# Tables 28 and 29 carry the test's values and nothing else. These four projections carry what
# the subclause states around them, and none of the four declares a classification: the
# cross-reference matrix has a row for the test's parent subclause, not for its parts, so a
# classification here would be this recipe's invention. Which of the two column groups an
# application reads *is* stated per classification, and that is the selection rule below --
# a different question from what the matrix answers.

_DIELECTRIC_DISCONNECTION_SHAPE = ("paragraph",) * 4
_DIELECTRIC_DURATION_SHAPE = ("paragraph",) * 1
_DIELECTRIC_ACCEPTANCE_SHAPE = ("paragraph",) * 1
#: The lead-in sentence, the first two list items, the third item, and the closing sentence.
_DIELECTRIC_TOPOLOGY_SHAPE = ("paragraph", "bullet", "bullet", "bullet", "paragraph")


def project_dielectric_disconnection(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[ProcedureRule, ...], tuple[SemanticProposal, ...]]:
    """Project what is disconnected, opened and restored before the voltage is applied.

    Four reviewed paragraphs, four steps, in source order: what shall be disconnected, what
    should not be, which connection shall be opened and afterwards restored, and how a
    protective impedance is handled. Kept as steps rather than as a decision because the
    source states obligations on the test setup, not a choice keyed on an input -- and the two
    it states as recommendations sit beside the two it states as requirements, which only the
    reviewed wording distinguishes.
    """

    label = "dielectric test disconnection"
    _require_own_fragment(fragment, identity, ids.TEST_DIELECTRIC_DISCONNECTION, label)
    _require_shape(fragment, _DIELECTRIC_DISCONNECTION_SHAPE, label)

    procedure = ProcedureRule(
        id=ids.TEST_DIELECTRIC_DISCONNECTION,
        test_kind="dielectric_test_disconnection",
        procedure_steps=_steps(fragment),
        source=fragment.source,
    )
    return (procedure,), (_proposal(procedure, "procedure", fragment),)


def project_dielectric_application_duration(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[ProcedureRule, ...], tuple[SemanticProposal, ...]]:
    """Project how long the voltage is held, and the ramp the source permits around it.

    One reviewed paragraph states both, separately for the type and the routine test, so it
    becomes one step and is also carried on ``duration``: a consumer asking a procedure how
    long to apply the voltage reads that field, and until this rule existed nothing in the
    package answered it. Text rather than a number for the reason the permitted alternative's
    ramp is text -- a limit is licensed source content and belongs in the reviewed statement,
    not beside the recipe -- and one field rather than two because the source states the two
    durations in one sentence, which splitting would mean parsing in public code.
    """

    label = "dielectric test application duration"
    _require_own_fragment(fragment, identity, ids.TEST_DIELECTRIC_APPLICATION_DURATION, label)
    _require_shape(fragment, _DIELECTRIC_DURATION_SHAPE, label)

    procedure = ProcedureRule(
        id=ids.TEST_DIELECTRIC_APPLICATION_DURATION,
        test_kind="dielectric_voltage_application",
        duration=fragment.nodes[0].raw_text.strip()[:MAX_REFERENCE_TEXT_LENGTH] or None,
        procedure_steps=_steps(fragment),
        source=fragment.source,
    )
    return (procedure,), (_proposal(procedure, "procedure", fragment),)


#: What is observed, and what the observation settles. One boolean each: the source states the
#: criterion as a single condition on the whole application.
_ACCEPTANCE_INPUT = "electric_breakdown_observed"
_ACCEPTANCE_OUTPUT = "voltage_test_passed"


def project_dielectric_acceptance(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the acceptance criterion of the AC or DC voltage test.

    Exhaustive over its one input, unlike the permissions elsewhere in this module. Those are
    conditional grants, where a combination the source does not settle has to resolve to
    nothing; this is an acceptance criterion over a single observation, and the source states
    both of its outcomes -- the observation absent is a pass, and an acceptance criterion that
    left its own failing case unresolved would report a breakdown as an unknown result.
    """

    label = "dielectric test acceptance"
    _require_own_fragment(fragment, identity, ids.TEST_DIELECTRIC_ACCEPTANCE, label)
    _require_shape(fragment, _DIELECTRIC_ACCEPTANCE_SHAPE, label)

    rule = DecisionRule(
        id=ids.TEST_DIELECTRIC_ACCEPTANCE,
        inputs=(DecisionInput(name=_ACCEPTANCE_INPUT, kind="boolean"),),
        outputs=(DecisionOutput(name=_ACCEPTANCE_OUTPUT, kind="boolean"),),
        rows=tuple(
            DecisionRow(
                matchers=(Matcher(input=_ACCEPTANCE_INPUT, op="equals", boolean=observed),),
                values=(DecisionValue(name=_ACCEPTANCE_OUTPUT, boolean=not observed),),
                source=fragment.nodes[0].source,
            )
            for observed in (False, True)
        ),
        exhaustive=True,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


#: The reference an application is made against -- the low side of the pair. Neutral names for
#: the three the subclause's list enumerates, plus the adjacency case it states separately
#: because that one reads its row from the other side of the pair.
DIELECTRIC_REFERENCE_KINDS = (
    "earthed_conductive_accessible_part",
    "unearthed_or_non_conductive_accessible_surface",
    "adjacent_circuit",
    "dvc_as_adjacent_circuit",
)
DIELECTRIC_TEST_CLASSIFICATIONS = ("type_test", "routine_test")
#: What an application is *not*. A sentinel member of both output vocabularies rather than a
#: third boolean output, because the subclause states its exclusions as cases of the same list
#: the columns come from, and a row that had to name a column it does not read would be a lie.
DIELECTRIC_NOT_APPLICABLE = "not_applicable"
#: The two column groups Tables 28 and 29 are extracted as, named by the route ids those specs
#: carry. Read from the shared declaration so this rule cannot name a column no route projects.
DIELECTRIC_COLUMNS = (*(purpose for purpose, _ac, _dc in DIELECTRIC_PURPOSES),)
#: Which side of the pair the row is read from. The subclause states the circuit under test for
#: every application except the adjacency one, which it states as the higher-voltage circuit.
DIELECTRIC_ROW_AXIS_CIRCUITS = ("circuit_under_test", "higher_voltage_circuit")
_TOPOLOGY_INPUTS: tuple[tuple[str, Literal["categorical", "boolean"]], ...] = (
    ("reference_kind", "categorical"),
    ("test_classification", "categorical"),
    ("circuit_under_test_is_dvc_as", "boolean"),
    ("circuit_connected_to_conductive_accessible_parts", "boolean"),
    ("enhanced_protection", "boolean"),
)
_TOPOLOGY_COLUMN_OUTPUT = "dielectric_column"
_TOPOLOGY_ROW_OUTPUT = "row_axis_circuit"
#: One entry per row the subclause states, in first-match order: the reviewed node the row
#: rests on, its conditions in ``_TOPOLOGY_INPUTS`` order, the column it reads and the side of
#: the pair its row is keyed on. ``None`` leaves a dimension unmatched, which is how a row the
#: source states without qualifying it stays one row instead of a product of the dimensions it
#: says nothing about. The node index makes a row cite the part of the subclause it came from
#: rather than the fragment as a whole.
_NA = DIELECTRIC_NOT_APPLICABLE
_BASIC_COLUMN, _ENHANCED_COLUMN = DIELECTRIC_COLUMNS
_OWN_ROW, _HIGHER_ROW = DIELECTRIC_ROW_AXIS_CIRCUITS
_TOPOLOGY_ROWS: tuple[tuple[int, tuple[str | bool | None, ...], str, str], ...] = (
    # The closing sentence: a circuit electrically connected to the conductive accessible parts
    # is not tested at all. First, because it holds whatever the electrodes would have been.
    (4, (None, None, None, True, None), _NA, _NA),
    # Both applications of the first item except DVC As circuits, which the third item handles.
    (1, ("earthed_conductive_accessible_part", None, True, None, None), _NA, _NA),
    (1, ("unearthed_or_non_conductive_accessible_surface", None, True, None, None), _NA, _NA),
    # The third item: the column follows the classification, and the row is keyed on the
    # higher-voltage circuit of the two rather than on the circuit under test.
    (3, ("dvc_as_adjacent_circuit", "type_test", None, None, None), _ENHANCED_COLUMN, _HIGHER_ROW),
    (3, ("dvc_as_adjacent_circuit", "routine_test", None, None, None), _BASIC_COLUMN, _HIGHER_ROW),
    # The first item's second application: the classification alone decides the column here.
    # The protection level of the circuit under test does not enter, which is the whole point
    # of stating this case apart from the enhanced-protection one below.
    (
        1,
        ("unearthed_or_non_conductive_accessible_surface", "type_test", None, None, None),
        _ENHANCED_COLUMN,
        _OWN_ROW,
    ),
    (
        1,
        ("unearthed_or_non_conductive_accessible_surface", "routine_test", None, None, None),
        _BASIC_COLUMN,
        _OWN_ROW,
    ),
    # The first item's first application and the second item. Both name the basic column, and
    # the third item's closing prose states that the type test of insulation used for enhanced
    # protection is otherwise read from the other one, so enhanced protection is a row of its
    # own ahead of each. A routine test never reaches those: the source states the stronger
    # column for the type test only.
    (
        3,
        ("earthed_conductive_accessible_part", "type_test", None, None, True),
        _ENHANCED_COLUMN,
        _OWN_ROW,
    ),
    (1, ("earthed_conductive_accessible_part", None, None, None, None), _BASIC_COLUMN, _OWN_ROW),
    (3, ("adjacent_circuit", "type_test", None, None, True), _ENHANCED_COLUMN, _OWN_ROW),
    (2, ("adjacent_circuit", None, None, None, None), _BASIC_COLUMN, _OWN_ROW),
)


def _topology_matcher(name: str, value: str | bool | None) -> tuple[Matcher, ...]:
    """One matcher, or none where the source states the row without qualifying this dimension."""

    if value is None:
        return ()
    if isinstance(value, bool):
        return (Matcher(input=name, op="equals", boolean=value),)
    return (Matcher(input=name, op="equals", values=(value,)),)


def project_dielectric_topology_selection(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project which electrodes an application uses and which column it reads.

    The subclause states the electrode pairs as a list and, for each, which column of the value
    tables the application reads and whose voltage keys the row. It states three exclusions --
    the DVC As circuits its first item excepts, the circuit electrically connected to the
    conductive accessible parts, and, inside the third item, the enhanced-protection type test
    that reads the lower column where the higher one cannot be applied. All of that is one
    selection, so it is one decision: a consumer that had to join a topology rule to a column
    rule would be inventing the join.

    Not exhaustive. A combination the subclause does not settle resolves to nothing and the
    consumer blocks, which is the only safe answer for a rule whose output is a test voltage.

    Two things the subclause states here are deliberately not part of this rule. The enclosure
    condition and the foil requirement are test-setup obligations rather than electrode or
    column selections, and the foil already has its own required item. And the permission to
    fall back to the lower column where the higher one cannot be applied is carried as the
    enhanced-protection row's reviewed statement rather than as an input: the source qualifies
    it with what is *typically* impossible, which is an engineering judgement about a
    particular assembly and not something a package can resolve.
    """

    label = "dielectric topology selection"
    _require_own_fragment(fragment, identity, ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION, label)
    _require_shape(fragment, _DIELECTRIC_TOPOLOGY_SHAPE, label)

    allowed: Mapping[str, tuple[str, ...]] = {
        "reference_kind": DIELECTRIC_REFERENCE_KINDS,
        "test_classification": DIELECTRIC_TEST_CLASSIFICATIONS,
    }
    rule = DecisionRule(
        id=ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION,
        inputs=tuple(
            DecisionInput(name=name, kind=kind, allowed_values=allowed.get(name, ()))
            if kind == "categorical"
            else DecisionInput(name=name, kind=kind)
            for name, kind in _TOPOLOGY_INPUTS
        ),
        outputs=(
            DecisionOutput(
                name=_TOPOLOGY_COLUMN_OUTPUT,
                kind="categorical",
                allowed_values=(*DIELECTRIC_COLUMNS, DIELECTRIC_NOT_APPLICABLE),
            ),
            DecisionOutput(
                name=_TOPOLOGY_ROW_OUTPUT,
                kind="categorical",
                allowed_values=(*DIELECTRIC_ROW_AXIS_CIRCUITS, DIELECTRIC_NOT_APPLICABLE),
            ),
        ),
        rows=tuple(
            DecisionRow(
                matchers=tuple(
                    matcher
                    for (name, _kind), value in zip(_TOPOLOGY_INPUTS, conditions, strict=True)
                    for matcher in _topology_matcher(name, value)
                ),
                values=(
                    DecisionValue(name=_TOPOLOGY_COLUMN_OUTPUT, categorical=column),
                    DecisionValue(name=_TOPOLOGY_ROW_OUTPUT, categorical=row_side),
                ),
                source=fragment.nodes[node].source,
            )
            for node, conditions, column, row_side in _TOPOLOGY_ROWS
        ),
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


CLAUSE_PROJECTORS: Mapping[str, ClauseProjector] = {
    ids.TEST_IMPULSE_ALTERNATIVE: project_impulse_alternative,
    ids.TEST_DIELECTRIC_DISCONNECTION: project_dielectric_disconnection,
    ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION: project_dielectric_topology_selection,
    ids.TEST_DIELECTRIC_APPLICATION_DURATION: project_dielectric_application_duration,
    ids.TEST_DIELECTRIC_ACCEPTANCE: project_dielectric_acceptance,
    ids.TEST_WORKING_VOLTAGE_DETERMINATION: project_working_voltage_determination,
    ids.TEST_INTERNAL_SPD_MONITORING: project_internal_spd_monitoring,
    ids.TEST_PRECONDITIONING: project_preconditioning,
    PRECONDITIONING_APPLICABILITY_ID: project_preconditioning_applicability,
    ids.TEST_ACCESSIBLE_SURFACE_FOIL: project_accessible_surface_foil,
    ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION: project_assembled_routine_exemption,
}

__all__ = [
    "CLASSIFICATION_COLUMNS",
    "CLASSIFICATION_MATRIX",
    "CLASSIFICATION_MATRIX_ID",
    "CLASSIFICATION_MATRIX_SPECS",
    "CLAUSE_PROJECTORS",
    "DIELECTRIC_COLUMNS",
    "DIELECTRIC_NOT_APPLICABLE",
    "DIELECTRIC_REFERENCE_KINDS",
    "DIELECTRIC_ROW_AXIS_CIRCUITS",
    "DIELECTRIC_TEST_CLASSIFICATIONS",
    "FOIL_APPLICABILITY_ID",
    "IMPULSE_ALTERNATIVE_AC_ID",
    "IMPULSE_ALTERNATIVE_DC_ID",
    "IMPULSE_ALTERNATIVE_VARIANTS",
    "MATERIAL_PRECONDITIONING_INVOCATIONS",
    "PRECONDITIONING_APPLICABILITY_ID",
    "PRECONDITIONING_ELECTRICAL_ID",
    "PRECONDITIONING_MATERIAL_CONTEXTS",
    "PRECONDITIONING_MATERIAL_ID",
    "PROCEDURE_CLAUSES",
    "REQUIREMENT_CLAUSE_COLUMN",
    "TEST_CLAUSE_COLUMN",
    "matrix_classifications",
    "matrix_grid",
    "project_accessible_surface_foil",
    "project_assembled_routine_exemption",
    "project_dielectric_acceptance",
    "project_dielectric_application_duration",
    "project_dielectric_disconnection",
    "project_dielectric_topology_selection",
    "project_impulse_alternative",
    "project_internal_spd_monitoring",
    "project_preconditioning",
    "project_preconditioning_applicability",
    "project_working_voltage_determination",
    "validate_classifications",
]
