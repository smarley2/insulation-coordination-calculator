"""The clause 5.2.2 matrix is evidence, and it vetoes a procedure's classification.

Synthetic clause references and synthetic marks only: nothing here comes from the licensed
document. The geometry the recipe declares is proven against the document by the licensed
suite, not here.
"""

from __future__ import annotations

import pytest

from insulation_coordination.domain.rules import (
    ProcedureRule,
    ProcedureStep,
    SourceReference,
)
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridCell,
    RawGridSegment,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.procedures import (
    CLASSIFICATION_MATRIX_SPECS,
    TEST_CLAUSE_COLUMN,
    matrix_classifications,
    validate_classifications,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    ProcedureStructureError,
)

SOURCE = SourceReference(
    document_id="synthetic-matrix",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    clause="9.9.9.1",
)
#: (test clause reference, the classifications marked for it).
_ROWS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("9.9.9.1", ("type_test",)),
    ("9.9.9.2", ("routine_test", "sample_test")),
    ("9.9.9.3", ()),
)
_MARK_COLUMNS = ("type_test_mark", "routine_test_mark", "sample_test_mark")


def _synthetic_matrix_grid() -> RawGrid:
    cells: list[RawGridCell] = []
    for row_index, (clause, marked) in enumerate(_ROWS):
        for column_index, column in enumerate((*_MARK_COLUMNS, TEST_CLAUSE_COLUMN)):
            text = clause if column == TEST_CLAUSE_COLUMN else ("M" if column[:-5] in marked else "")
            cells.append(
                RawGridCell(
                    row=row_index,
                    column=column_index,
                    raw_text=text,
                    role="data" if text else "blank",
                    logical_row=row_index,
                    logical_column=column,
                    parse_status="text" if text else "blank",
                    source=SOURCE,
                )
            )
    return RawGrid(
        id="raw-synthetic-matrix",
        rows=len(_ROWS),
        columns=len(_MARK_COLUMNS) + 1,
        target_unit="1",
        segments=(
            RawGridSegment(page_number=1, row_start=0, row_count=len(_ROWS), source=SOURCE),
        ),
        cells=tuple(cells),
        source=SOURCE,
    )


def _procedure_claiming(*classifications: str, clause: str = "9.9.9.1") -> ProcedureRule:
    return ProcedureRule(
        id="synthetic.procedure",
        test_kind="synthetic",
        classifications=classifications,
        procedure_steps=(
            ProcedureStep(order=1, text="apply the declared condition", source=SOURCE),
        ),
        source=SOURCE.model_copy(update={"clause": clause}),
    )


def test_the_matrix_is_evidence_not_a_rule() -> None:
    assert CLASSIFICATION_MATRIX_SPECS
    assert all(spec.comparison_only for spec in CLASSIFICATION_MATRIX_SPECS)
    assert not any(spec.decision_route_ids for spec in CLASSIFICATION_MATRIX_SPECS)


def test_the_matrix_declares_one_grid_over_all_of_its_pages() -> None:
    """One spec, one raw grid: a procedure looks its clause up once, not per page."""
    spec = CLASSIFICATION_MATRIX_SPECS[0]

    assert len(spec.segments) == 3
    assert sum(segment.expected_raw_rows for segment in spec.segments) == spec.expected_raw_rows
    assert {segment.page_number for segment in spec.segments} == {112, 113, 114}
    # Every segment continues the logical row numbering of the one before it, so a row on the
    # third page cannot collide with a row on the first.
    offsets = [segment.logical_row_offset for segment in spec.segments]
    assert offsets == sorted(offsets)
    assert len(set(offsets)) == len(offsets)


def test_a_marked_row_reads_as_its_classifications() -> None:
    assert matrix_classifications(_synthetic_matrix_grid()) == {
        "9.9.9.1": frozenset({"type_test"}),
        "9.9.9.2": frozenset({"routine_test", "sample_test"}),
        "9.9.9.3": frozenset(),
    }


def test_a_procedure_whose_classification_contradicts_the_matrix_blocks() -> None:
    with pytest.raises(ProcedureStructureError, match="classification"):
        validate_classifications(_synthetic_matrix_grid(), _procedure_claiming("routine_test"))


def test_a_procedure_whose_clause_the_matrix_has_no_row_for_blocks() -> None:
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_TEST_CLASSIFICATION"):
        validate_classifications(
            _synthetic_matrix_grid(),
            _procedure_claiming("type_test", clause="9.9.9.4"),
        )


def test_a_row_the_matrix_leaves_unmarked_supports_no_classification() -> None:
    with pytest.raises(ProcedureStructureError, match="does not mark"):
        validate_classifications(
            _synthetic_matrix_grid(),
            _procedure_claiming("type_test", clause="9.9.9.3"),
        )


def test_an_agreeing_classification_passes() -> None:
    validate_classifications(_synthetic_matrix_grid(), _procedure_claiming("type_test"))
    validate_classifications(
        _synthetic_matrix_grid(),
        _procedure_claiming("routine_test", "sample_test", clause="9.9.9.2"),
    )


def test_a_procedure_declaring_no_classification_is_not_checked() -> None:
    """Table 30 deliberately declares none; the matrix cannot veto what was left unstated."""
    validate_classifications(_synthetic_matrix_grid(), _procedure_claiming(clause="9.9.9.4"))
