"""Synthetic IEC 62477-1 test-procedure clause projections. No IEC content.

Every fragment here is written by hand: neutral placeholder step text and the clause
references the recipe declares. The bounding boxes and node shapes the recipe carries are
proven against the licensed document by the licensed suite, not here.
"""

from __future__ import annotations

import pytest

from insulation_coordination.domain.rules import ProcedureRule, SourceReference
from insulation_coordination.rules.importer.clauses import ClauseNode, RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    RawGrid,
    RawGridCell,
    RawGridSegment,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import RECIPE as IEC_RECIPE
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.procedures import (
    CLASSIFICATION_COLUMNS,
    CLASSIFICATION_MATRIX_ID,
    PROCEDURE_CLAUSES,
    TEST_CLAUSE_COLUMN,
    project_internal_spd_monitoring,
    project_working_voltage_determination,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    ProcedureStructureError,
)
from tests.fixtures.synthetic_rules import synthetic_rule_package

IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="7" * 64,
    page_count=200,
    recipe_id="synthetic-procedures",
)
SOURCE = SourceReference(
    document_id="synthetic-procedures",
    standard="SYNTHETIC",
    edition="1",
    page=142,
)
#: The clause reference each projection's fragment carries, and the classification the
#: matrix marks for it. Clause references are structural identifiers, not source content.
CLAUSE_OF = {
    ids.TEST_WORKING_VOLTAGE_DETERMINATION: "5.2.3.14",
    ids.TEST_INTERNAL_SPD_MONITORING: "5.2.3.15",
}


def _fragment(semantic_id: str, node_count: int, kind: str = "bullet") -> RawClauseFragment:
    source = SOURCE.model_copy(update={"clause": CLAUSE_OF[semantic_id]})
    nodes = tuple(
        ClauseNode(
            order=order,
            kind=kind,  # type: ignore[arg-type]
            raw_text=f"perform the declared condition {order + 1}",
            source=source,
        )
        for order in range(node_count)
    )
    fragment = RawClauseFragment(
        id=f"raw-{semantic_id}",
        raw_sha256="0" * 64,
        nodes=nodes,
        tokens=(),
        source=source,
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def _matrix_grid(marks: dict[str, tuple[str, ...]]) -> RawGrid:
    """A matrix grid marking the given classifications for the given test clauses."""

    columns = (*(f"{name}_mark" for name, _column in CLASSIFICATION_COLUMNS), TEST_CLAUSE_COLUMN)
    cells: list[RawGridCell] = []
    for row, (clause, marked) in enumerate(marks.items()):
        for index, column in enumerate(columns):
            text = clause if column == TEST_CLAUSE_COLUMN else ("M" if column[:-5] in marked else "")
            cells.append(
                RawGridCell(
                    row=row,
                    column=index,
                    raw_text=text,
                    role="data" if text else "blank",
                    logical_row=row,
                    logical_column=column,
                    parse_status="text" if text else "blank",
                    source=SOURCE,
                )
            )
    return RawGrid(
        id=f"raw-{CLASSIFICATION_MATRIX_ID}",
        rows=len(marks),
        columns=len(columns),
        target_unit="1",
        segments=(
            RawGridSegment(page_number=113, row_start=0, row_count=len(marks), source=SOURCE),
        ),
        cells=tuple(cells),
        source=SOURCE,
    )


def _draft(*grids: RawGrid, fragments: tuple[RawClauseFragment, ...] = ()) -> ImportedRuleDraft:
    package = synthetic_rule_package()
    return ImportedRuleDraft(
        manifest=package.manifest.model_copy(
            update={
                "approved": False,
                "compatible": False,
                "source_documents": (),
                "approval_records": (),
            }
        ),
        tables=(),
        formulas=(),
        mappings=(),
        raw_grids=grids,
        raw_clause_fragments=fragments,
        source_identities=(IDENTITY,),
    )


def _agreeing_matrix() -> RawGrid:
    return _matrix_grid({clause: ("type_test",) for clause in CLAUSE_OF.values()})


def test_the_recipe_registers_a_projector_for_every_procedure_clause() -> None:
    declared = {spec.semantic_id for spec in PROCEDURE_CLAUSES}

    assert declared <= set(IEC_RECIPE.clause_projectors)
    assert declared <= {spec.semantic_id for spec in IEC_RECIPE.clauses}


def test_working_voltage_outputs_name_a_measurement_not_a_formula() -> None:
    """The clause names measurement conditions and states no arithmetic, so none is built."""
    rules, _proposals = project_working_voltage_determination(
        _fragment(ids.TEST_WORKING_VOLTAGE_DETERMINATION, 3),
        IDENTITY,
        _draft(_agreeing_matrix()),
    )

    assert not any(getattr(rule, "expression", None) for rule in rules)
    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))
    assert len(procedure.procedure_steps) == 3
    assert procedure.classifications == ("type_test",)


def test_working_voltage_blocks_on_a_node_count_the_recipe_does_not_declare() -> None:
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_working_voltage_determination(
            _fragment(ids.TEST_WORKING_VOLTAGE_DETERMINATION, 2),
            IDENTITY,
            _draft(_agreeing_matrix()),
        )


def test_internal_spd_monitoring_references_the_supply_decision_rather_than_restating_it() -> None:
    rules, _proposals = project_internal_spd_monitoring(
        _fragment(ids.TEST_INTERNAL_SPD_MONITORING, 1, kind="paragraph"),
        IDENTITY,
        _draft(_agreeing_matrix()),
    )

    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))
    assert procedure.applicability_rule_id == ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS
    assert procedure.applicability == ""


def test_each_procedure_classification_matches_the_matrix() -> None:
    """Every projection checks what it declares against the matrix, and blocks on a clash."""
    contradicting = _matrix_grid({clause: ("routine_test",) for clause in CLAUSE_OF.values()})

    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_TEST_CLASSIFICATION"):
        project_working_voltage_determination(
            _fragment(ids.TEST_WORKING_VOLTAGE_DETERMINATION, 3), IDENTITY, _draft(contradicting)
        )
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_TEST_CLASSIFICATION"):
        project_internal_spd_monitoring(
            _fragment(ids.TEST_INTERNAL_SPD_MONITORING, 1, kind="paragraph"),
            IDENTITY,
            _draft(contradicting),
        )


def test_a_procedure_cannot_be_projected_without_the_matrix_to_check_it() -> None:
    with pytest.raises(ProcedureStructureError, match="matrix grid is absent"):
        project_working_voltage_determination(
            _fragment(ids.TEST_WORKING_VOLTAGE_DETERMINATION, 3), IDENTITY, _draft()
        )


def test_a_projection_refuses_a_fragment_that_is_not_its_own() -> None:
    with pytest.raises(ValueError, match="requires its own fragment"):
        project_internal_spd_monitoring(
            _fragment(ids.TEST_WORKING_VOLTAGE_DETERMINATION, 3),
            IDENTITY,
            _draft(_agreeing_matrix()),
        )
