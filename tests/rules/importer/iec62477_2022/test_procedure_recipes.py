"""Synthetic IEC 62477-1 test-procedure clause projections. No IEC content.

Every fragment here is written by hand: neutral placeholder step text and the clause
references the recipe declares. The bounding boxes and node shapes the recipe carries are
proven against the licensed document by the licensed suite, not here.
"""

from __future__ import annotations

import pytest

from insulation_coordination.domain.rules import ProcedureRule, SourceReference
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.clauses import (
    ClauseNode,
    ClauseToken,
    RawClauseFragment,
)
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
    FOIL_APPLICABILITY_ID,
    PRECONDITIONING_APPLICABILITY_ID,
    PROCEDURE_CLAUSES,
    TEST_CLAUSE_COLUMN,
    project_accessible_surface_foil,
    project_accessible_surface_foil_applicability,
    project_assembled_routine_exemption,
    project_internal_spd_monitoring,
    project_preconditioning,
    project_preconditioning_applicability,
    project_working_voltage_determination,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    FIELD_ROWS,
    VARIANT_COLUMNS,
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
    ids.TEST_PRECONDITIONING: "5.2.3.16",
    PRECONDITIONING_APPLICABILITY_ID: "5.2.3.1",
    ids.TEST_ACCESSIBLE_SURFACE_FOIL: "5.2.3.13.3",
    FOIL_APPLICABILITY_ID: "5.2.3.4.4",
    ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION: "5.2.3.4.4",
}


def _fragment(
    semantic_id: str,
    node_count: int,
    kind: str = "bullet",
    texts: tuple[str, ...] = (),
) -> RawClauseFragment:
    source = SOURCE.model_copy(update={"clause": CLAUSE_OF[semantic_id]})
    nodes = tuple(
        ClauseNode(
            order=order,
            kind=kind,  # type: ignore[arg-type]
            raw_text=(
                texts[order] if order < len(texts) else f"perform the declared condition {order + 1}"
            ),
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
    with pytest.raises(ProcedureStructureError, match="classification_matrix is absent"):
        project_working_voltage_determination(
            _fragment(ids.TEST_WORKING_VOLTAGE_DETERMINATION, 3), IDENTITY, _draft()
        )


#: The Table 26 row and column that carry the preconditioning statement, read from the
#: maintained recipe so the fixture cannot drift away from what the projection reads.
_PRECONDITIONING_ROW = next(row for row, field in FIELD_ROWS if field == "preconditioning")
_PRECONDITIONING_COLUMN = VARIANT_COLUMNS[0][1]


def _general_fragment(step_clauses: tuple[str, ...]) -> RawClauseFragment:
    """The general clause's paragraph, naming the preconditioning clauses it requires."""

    named = " and ".join(step_clauses)
    return _fragment(
        PRECONDITIONING_APPLICABILITY_ID,
        1,
        kind="paragraph",
        texts=(f"preconditioning according to {named} is required before the test",),
    )


def _table_26_grid(*, defers: bool = True) -> RawGrid:
    text = (
        "preconditioned once according to 5.2.3.1"
        if defers
        else "preconditioned once according to 5.2.6.3.1"
    )
    cell = RawGridCell(
        row=_PRECONDITIONING_ROW,
        column=_PRECONDITIONING_COLUMN,
        raw_text=text,
        role="data",
        logical_row=_PRECONDITIONING_ROW,
        logical_column="condition_insulation_basic",
        parse_status="text",
        source=SOURCE,
    )
    return RawGrid(
        id=f"raw-{ids.TEST_IMPULSE_PROCEDURE}",
        rows=_PRECONDITIONING_ROW + 1,
        columns=_PRECONDITIONING_COLUMN + 1,
        target_unit="1",
        segments=(
            RawGridSegment(
                page_number=124,
                row_start=0,
                row_count=_PRECONDITIONING_ROW + 1,
                source=SOURCE,
            ),
        ),
        cells=(cell,),
        source=SOURCE,
    )


def _preconditioning_draft(
    *,
    general_steps: tuple[str, ...] = ("5.2.6.3.1", "5.2.6.3.2", "5.2.6.3.3"),
    defers: bool = True,
) -> ImportedRuleDraft:
    return _draft(
        _agreeing_matrix(),
        _table_26_grid(defers=defers),
        fragments=(_general_fragment(general_steps),),
    )


def test_three_agreeing_sources_yield_one_procedure() -> None:
    """The material clause enumerates three steps, and the other two sources require three."""
    rules, proposals = project_preconditioning(
        _fragment(ids.TEST_PRECONDITIONING, 3), IDENTITY, _preconditioning_draft()
    )

    assert len(rules) == 1
    assert rules[0].id == ids.TEST_PRECONDITIONING
    assert rules[0].applicability_rule_id == PRECONDITIONING_APPLICABILITY_ID
    assert rules[0].classifications == ("type_test",)
    assert [proposal.semantic_id for proposal in proposals] == [ids.TEST_PRECONDITIONING]


def test_a_disagreement_between_the_three_sources_blocks() -> None:
    """No precedence rule: a general clause naming fewer steps refuses the projection."""
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PRECONDITIONING_SOURCES"):
        project_preconditioning(
            _fragment(ids.TEST_PRECONDITIONING, 3),
            IDENTITY,
            _preconditioning_draft(general_steps=("5.2.6.3.1", "5.2.6.3.2")),
        )


def test_a_table_row_that_states_its_own_inventory_blocks() -> None:
    """Table 26's row is a deferral. A printing that spelled its own steps is a fourth source."""
    with pytest.raises(ProcedureStructureError, match="does not defer to clause"):
        project_preconditioning(
            _fragment(ids.TEST_PRECONDITIONING, 3),
            IDENTITY,
            _preconditioning_draft(defers=False),
        )


def test_preconditioning_blocks_when_a_source_it_must_agree_with_is_absent() -> None:
    with pytest.raises(ProcedureStructureError, match="is absent from the draft"):
        project_preconditioning(
            _fragment(ids.TEST_PRECONDITIONING, 3), IDENTITY, _draft(_agreeing_matrix())
        )


def test_the_preconditioning_gate_never_settles_a_purpose_the_source_leaves_open() -> None:
    rules, _proposals = project_preconditioning_applicability(
        _general_fragment(("5.2.6.3.1", "5.2.6.3.2")), IDENTITY
    )
    rule = rules[0]

    assert rule.id == PRECONDITIONING_APPLICABILITY_ID
    assert rule.exhaustive is False
    assert {
        row.matchers[0].values[0]: row.values[0].boolean for row in rule.rows
    } == {"type_test": True, "sample_test": True, "acceptance_criteria": False}


def _foil_fragment(*, figures: tuple[str, ...] = ("23", "24")) -> RawClauseFragment:
    source = SOURCE.model_copy(update={"clause": CLAUSE_OF[ids.TEST_ACCESSIBLE_SURFACE_FOIL]})
    node = ClauseNode(
        order=0,
        kind="paragraph",
        raw_text="place the foil as the cited drawings show",
        source=source,
    )
    fragment = RawClauseFragment(
        id=f"raw-{ids.TEST_ACCESSIBLE_SURFACE_FOIL}",
        raw_sha256="0" * 64,
        nodes=(node,),
        tokens=tuple(
            ClauseToken(
                kind="reference",
                raw_text=f"Figure {number}",
                normalized=f"figure-{number}",
                source=source,
            )
            for number in figures
        ),
        source=source,
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def test_the_foil_procedure_keeps_its_figures_as_references_not_geometry() -> None:
    rules, _proposals = project_accessible_surface_foil(
        _foil_fragment(), IDENTITY, _draft(_agreeing_matrix())
    )
    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))

    assert procedure.source.figure is None
    assert all(step.source.figure for step in procedure.procedure_steps)
    assert any("23" in (step.source.figure or "") for step in procedure.procedure_steps)
    assert any("24" in (step.source.figure or "") for step in procedure.procedure_steps)
    assert procedure.applicability_rule_id == FOIL_APPLICABILITY_ID


def test_the_foil_procedure_blocks_when_the_clause_cites_no_figure() -> None:
    with pytest.raises(ProcedureStructureError, match="figure references"):
        project_accessible_surface_foil(
            _foil_fragment(figures=()), IDENTITY, _draft(_agreeing_matrix())
        )


def test_the_foil_gate_records_a_substitution_rather_than_a_classification() -> None:
    """The matrix marks no sample test for the surrounding test, so no rule claims one."""
    rules, _proposals = project_accessible_surface_foil_applicability(
        _fragment(FOIL_APPLICABILITY_ID, 1, kind="paragraph"), IDENTITY
    )
    rule = rules[0]

    assert rule.id == FOIL_APPLICABILITY_ID
    assert rule.exhaustive is False
    assert len(rule.rows) == 1
    unsupported = evaluate_decision(rule, {"non_conductive_accessible_surface_present": False})
    assert unsupported.status == "no_match"
    assert unsupported.values == ()


def test_the_exemption_never_defaults_to_exempt() -> None:
    rules, _proposals = project_assembled_routine_exemption(
        _fragment(ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION, 3), IDENTITY
    )
    rule = rules[0]

    assert rule.exhaustive is False
    granted: dict[str, object] = {item.name: True for item in rule.inputs}
    exempt = evaluate_decision(rule, granted)
    assert exempt.status == "matched"
    assert [(value.name, value.boolean) for value in exempt.values] == [
        ("assembled_routine_test_exempt", True)
    ]
    for condition in granted:
        withheld = {**granted, condition: False}
        assert evaluate_decision(rule, withheld).status == "no_match"


def test_a_projection_refuses_a_fragment_that_is_not_its_own() -> None:
    with pytest.raises(ValueError, match="requires its own fragment"):
        project_internal_spd_monitoring(
            _fragment(ids.TEST_WORKING_VOLTAGE_DETERMINATION, 3),
            IDENTITY,
            _draft(_agreeing_matrix()),
        )
