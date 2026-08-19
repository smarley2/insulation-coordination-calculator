"""Synthetic IEC 62477-1 test-procedure clause projections. No IEC content.

Every fragment here is written by hand: neutral placeholder step text and the clause
references the recipe declares. The bounding boxes and node shapes the recipe carries are
proven against the licensed document by the licensed suite, not here.
"""

from __future__ import annotations

import pytest

from insulation_coordination.domain.rules import DecisionRule, ProcedureRule, SourceReference
from insulation_coordination.rules.evaluator import DecisionResult, evaluate_decision
from insulation_coordination.rules.importer.clauses import (
    ClauseNode,
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
    DIELECTRIC_COLUMNS,
    DIELECTRIC_NOT_APPLICABLE,
    DIELECTRIC_REFERENCE_KINDS,
    DIELECTRIC_ROW_AXIS_CIRCUITS,
    DIELECTRIC_TEST_CLASSIFICATIONS,
    FOIL_APPLICABILITY_ID,
    IMPULSE_ALTERNATIVE_VARIANTS,
    MATERIAL_PRECONDITIONING_INVOCATIONS,
    PRECONDITIONING_APPLICABILITY_ID,
    PRECONDITIONING_ELECTRICAL_ID,
    PRECONDITIONING_MATERIAL_CONTEXTS,
    PRECONDITIONING_MATERIAL_ID,
    PROCEDURE_CLAUSES,
    REQUIREMENT_CLAUSE_COLUMN,
    TEST_CLAUSE_COLUMN,
    project_accessible_surface_foil,
    project_assembled_routine_exemption,
    project_dielectric_acceptance,
    project_dielectric_application_duration,
    project_dielectric_disconnection,
    project_dielectric_topology_selection,
    project_impulse_alternative,
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
    ids.TEST_ACCESSIBLE_SURFACE_FOIL: "5.2.3.4.4",
    ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION: "5.2.3.4.4",
    ids.TEST_IMPULSE_ALTERNATIVE: "5.2.3.3",
    ids.TEST_DIELECTRIC_DISCONNECTION: "5.2.3.4.3",
    ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION: "5.2.3.4.4",
    ids.TEST_DIELECTRIC_APPLICATION_DURATION: "5.2.3.4.5",
    ids.TEST_DIELECTRIC_ACCEPTANCE: "5.2.3.4.6",
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
                texts[order]
                if order < len(texts)
                else f"perform the declared condition {order + 1}"
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


def _matrix_grid(
    marks: dict[str, tuple[str, ...]],
    invocations: tuple[str, ...] = MATERIAL_PRECONDITIONING_INVOCATIONS,
) -> RawGrid:
    """A matrix grid marking the given classifications for the given test clauses.

    Its requirement column carries the requirements that invoke the material preconditioning
    clause, because the gate reads them from here.
    """

    columns = (
        *(f"{name}_mark" for name, _column in CLASSIFICATION_COLUMNS),
        TEST_CLAUSE_COLUMN,
        REQUIREMENT_CLAUSE_COLUMN,
    )
    material_clause = CLAUSE_OF[ids.TEST_PRECONDITIONING]
    cells: list[RawGridCell] = []
    for row, (clause, marked) in enumerate(marks.items()):
        for index, column in enumerate(columns):
            if column == TEST_CLAUSE_COLUMN:
                text = clause
            elif column == REQUIREMENT_CLAUSE_COLUMN:
                text = ", ".join(invocations) if clause == material_clause else ""
            else:
                text = "M" if column[:-5] in marked else ""
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


def _agreeing_matrix(
    invocations: tuple[str, ...] = MATERIAL_PRECONDITIONING_INVOCATIONS,
) -> RawGrid:
    return _matrix_grid({clause: ("type_test",) for clause in CLAUSE_OF.values()}, invocations)


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
    # A route the recipe actually projects. The bare identifier stopped being projected when the
    # reduction rule split per supply kind, so referencing it would name no rule at all.
    assert procedure.applicability_rule_id == f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"
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
    invocations: tuple[str, ...] = MATERIAL_PRECONDITIONING_INVOCATIONS,
) -> ImportedRuleDraft:
    return _draft(
        _agreeing_matrix(invocations),
        _table_26_grid(defers=defers),
        fragments=(_general_fragment(general_steps),),
    )


def test_the_material_clause_yields_the_material_route() -> None:
    """The material clause's own three steps, under the route the maintainer decided on."""
    rules, proposals = project_preconditioning(
        _fragment(ids.TEST_PRECONDITIONING, 3), IDENTITY, _preconditioning_draft()
    )

    assert len(rules) == 1
    assert rules[0].id == PRECONDITIONING_MATERIAL_ID
    assert len(rules[0].procedure_steps) == 3
    assert rules[0].applicability_rule_id == PRECONDITIONING_APPLICABILITY_ID
    assert rules[0].classifications == ("type_test",)
    assert [proposal.semantic_id for proposal in proposals] == [PRECONDITIONING_MATERIAL_ID]


def test_the_general_clause_yields_the_gate_and_the_electrical_route() -> None:
    """Two gates, two routes: the electrical route carries what the general clause names."""
    rules, proposals = project_preconditioning_applicability(
        _general_fragment(("5.2.6.3.1", "5.2.6.3.2")), IDENTITY, _preconditioning_draft()
    )
    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))

    assert procedure.id == PRECONDITIONING_ELECTRICAL_ID
    assert len(procedure.procedure_steps) == 2
    assert procedure.applicability_rule_id == PRECONDITIONING_APPLICABILITY_ID
    # The matrix has no row for the general clause, so the route claims no classification.
    assert procedure.classifications == ()
    assert {proposal.semantic_id for proposal in proposals} == {
        PRECONDITIONING_APPLICABILITY_ID,
        PRECONDITIONING_ELECTRICAL_ID,
    }


def test_a_clause_inventory_that_is_not_the_reviewed_shape_still_blocks() -> None:
    """The block was never "the two clauses differ" -- it is "no precedence rule is invented"."""
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PRECONDITIONING_SOURCES"):
        project_preconditioning_applicability(
            _general_fragment(("5.2.6.3.1",)), IDENTITY, _preconditioning_draft()
        )
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_preconditioning(
            _fragment(ids.TEST_PRECONDITIONING, 2), IDENTITY, _preconditioning_draft()
        )


def test_a_table_row_that_states_its_own_inventory_blocks() -> None:
    """Table 26's row is a deferral. A printing that spelled its own steps is a third source."""
    with pytest.raises(ProcedureStructureError, match="does not defer to clause"):
        project_preconditioning(
            _fragment(ids.TEST_PRECONDITIONING, 3),
            IDENTITY,
            _preconditioning_draft(defers=False),
        )


def test_preconditioning_blocks_when_a_source_it_must_read_is_absent() -> None:
    with pytest.raises(ProcedureStructureError, match="is absent from the draft"):
        project_preconditioning(
            _fragment(ids.TEST_PRECONDITIONING, 3), IDENTITY, _draft(_agreeing_matrix())
        )


def test_the_preconditioning_gate_selects_the_route_for_the_test_context() -> None:
    rules, _proposals = project_preconditioning_applicability(
        _general_fragment(("5.2.6.3.1", "5.2.6.3.2")), IDENTITY, _preconditioning_draft()
    )
    rule = next(item for item in rules if isinstance(item, DecisionRule))

    assert rule.id == PRECONDITIONING_APPLICABILITY_ID
    assert rule.exhaustive is False
    electrical = evaluate_decision(
        rule, {"test_context": "electrical_test", "test_purpose": "type_test"}
    )
    material = evaluate_decision(
        rule,
        {"test_context": PRECONDITIONING_MATERIAL_CONTEXTS[0], "test_purpose": "type_test"},
    )
    exempt = evaluate_decision(
        rule, {"test_context": "electrical_test", "test_purpose": "acceptance_criteria"}
    )

    assert _values(electrical) == {
        "preconditioning_required": True,
        "preconditioning_procedure_rule_id": PRECONDITIONING_ELECTRICAL_ID,
    }
    assert _values(material) == {
        "preconditioning_required": True,
        "preconditioning_procedure_rule_id": PRECONDITIONING_MATERIAL_ID,
    }
    assert _values(exempt)["preconditioning_required"] is False


def test_the_material_route_is_gated_on_the_requirements_that_invoke_it() -> None:
    """The material clause applies when a named requirement calls for it, not to material work."""
    rules, _proposals = project_preconditioning_applicability(
        _general_fragment(("5.2.6.3.1", "5.2.6.3.2")), IDENTITY, _preconditioning_draft()
    )
    rule = next(item for item in rules if isinstance(item, DecisionRule))
    contexts = next(item for item in rule.inputs if item.name == "test_context").allowed_values

    assert set(contexts) == {"electrical_test", *PRECONDITIONING_MATERIAL_CONTEXTS}
    assert len(PRECONDITIONING_MATERIAL_CONTEXTS) == len(MATERIAL_PRECONDITIONING_INVOCATIONS)
    for context in PRECONDITIONING_MATERIAL_CONTEXTS:
        selected = evaluate_decision(rule, {"test_context": context, "test_purpose": "type_test"})
        assert _values(selected) == {
            "preconditioning_required": True,
            "preconditioning_procedure_rule_id": PRECONDITIONING_MATERIAL_ID,
        }


def test_the_gate_blocks_when_the_matrix_invokes_the_material_clause_differently() -> None:
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PRECONDITIONING_SOURCES"):
        project_preconditioning_applicability(
            _general_fragment(("5.2.6.3.1", "5.2.6.3.2")),
            IDENTITY,
            _preconditioning_draft(invocations=MATERIAL_PRECONDITIONING_INVOCATIONS[:1]),
        )


def _values(result: DecisionResult) -> dict[str, object]:
    return {
        value.name: value.boolean if value.boolean is not None else value.categorical
        for value in result.values
    }


def _foil_fragment() -> RawClauseFragment:
    return _fragment(ids.TEST_ACCESSIBLE_SURFACE_FOIL, 1, kind="paragraph")


def test_the_foil_family_is_grounded_in_the_voltage_test_clause_alone() -> None:
    """One paragraph of the voltage test states the gate and the action, and nothing else."""
    rules, proposals = project_accessible_surface_foil(_foil_fragment(), IDENTITY)
    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))

    assert procedure.source.clause == "5.2.3.4.4"
    assert procedure.applicability_rule_id == FOIL_APPLICABILITY_ID
    assert len(procedure.procedure_steps) == 1
    # The mandrel test's figures belong to the thin-sheet procedure, not to this family.
    assert procedure.source.figure is None
    assert all(step.source.figure is None for step in procedure.procedure_steps)
    # The matrix has no row for this sub-clause, so the procedure claims no classification.
    assert procedure.classifications == ()
    assert {proposal.semantic_id for proposal in proposals} == {
        ids.TEST_ACCESSIBLE_SURFACE_FOIL,
        FOIL_APPLICABILITY_ID,
    }


def test_the_foil_gate_records_a_substitution_rather_than_a_classification() -> None:
    """The matrix marks no sample test for the surrounding test, so no rule claims one."""
    rules, _proposals = project_accessible_surface_foil(_foil_fragment(), IDENTITY)
    rule = next(item for item in rules if isinstance(item, DecisionRule))

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


def _alternative_fragment(node_count: int = 4) -> RawClauseFragment:
    """The subclause's paragraphs: the permission, one per method, and the ramp allowance."""

    return _fragment(
        ids.TEST_IMPULSE_ALTERNATIVE,
        node_count,
        kind="paragraph",
        texts=(
            "the substitute test may be used for the stated verifications only",
            "the first method's declared modification",
            "the second method's declared modification",
            "the declared ramp allowance",
        )[:node_count],
    )


def test_the_alternative_projects_one_procedure_per_permitted_method() -> None:
    """The engineer chooses between the methods, so each is a rule the choice can name."""
    rules, proposals = project_impulse_alternative(_alternative_fragment(), IDENTITY)

    assert [rule.id for rule in rules] == [
        rule_id for _node, rule_id, _kind, _measure in IMPULSE_ALTERNATIVE_VARIANTS
    ]
    assert len({rule.test_kind for rule in rules}) == len(rules)
    assert [proposal.semantic_id for proposal in proposals] == [rule.id for rule in rules]
    # Both routes hang off the required inventory item, so completeness finds them by it.
    assert all(rule.id.startswith(f"{ids.TEST_IMPULSE_ALTERNATIVE}.") for rule in rules)


def test_each_alternative_states_the_test_it_replaces_and_the_voltage_it_matches() -> None:
    """Without both, a plan has a substitute test it can neither justify nor dimension."""
    rules, _proposals = project_impulse_alternative(_alternative_fragment(), IDENTITY)

    for rule, variant in zip(rules, IMPULSE_ALTERNATIVE_VARIANTS, strict=True):
        alternative = rule.permitted_alternative
        assert alternative is not None
        assert alternative.instead_of_rule_id == ids.TEST_IMPULSE_PROCEDURE
        assert alternative.equivalent_to_rule_id == ids.TEST_IMPULSE_SELECTION
        assert alternative.equivalent_measure == variant[3]
    # The two methods differ by their measure, which is what stops one standing for both.
    measures = {rule.permitted_alternative.equivalent_measure for rule in rules}  # type: ignore[union-attr]
    assert len(measures) == len(rules)


def test_the_shared_permission_and_ramp_reach_every_method_but_the_modification_does_not() -> None:
    """One statement covering both methods is carried by both; a per-method one is not."""
    fragment = _alternative_fragment()
    rules, _proposals = project_impulse_alternative(fragment, IDENTITY)
    permission = fragment.nodes[0].raw_text
    ramp = fragment.nodes[3].raw_text

    assert {rule.applicability for rule in rules} == {permission}
    assert {rule.permitted_alternative.ramp for rule in rules} == {ramp}  # type: ignore[union-attr]
    steps = [step.text for rule in rules for step in rule.procedure_steps]
    assert steps == [fragment.nodes[node].raw_text for node, *_rest in IMPULSE_ALTERNATIVE_VARIANTS]
    assert permission not in steps
    assert ramp not in steps


def test_the_alternative_leaves_the_application_pattern_in_its_reviewed_step() -> None:
    """The source states it as one sentence; splitting it would mean parsing that sentence."""
    rules, _proposals = project_impulse_alternative(_alternative_fragment(), IDENTITY)

    for rule in rules:
        assert (rule.repetitions, rule.duration, rule.polarity, rule.waveform) == (
            None,
            None,
            None,
            None,
        )
        # The matrix has no row for this subclause, so no route claims a classification.
        assert rule.classifications == ()


def test_the_alternative_blocks_on_a_node_count_the_recipe_does_not_declare() -> None:
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_impulse_alternative(_alternative_fragment(3), IDENTITY)


# --- the body of the AC or DC voltage test ---------------------------------------------

#: The four subclauses of the AC or DC voltage test the value tables do not state, and the
#: number of reviewed regions the recipe declares for each.
DIELECTRIC_BODY_SEGMENTS = {
    ids.TEST_DIELECTRIC_DISCONNECTION: 4,
    ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION: 3,
    ids.TEST_DIELECTRIC_APPLICATION_DURATION: 1,
    ids.TEST_DIELECTRIC_ACCEPTANCE: 1,
}


def _topology_fragment(
    kinds: tuple[str, ...] = ("paragraph", "bullet", "bullet", "bullet", "paragraph"),
) -> RawClauseFragment:
    """The selection clause's mixed node shape: a lead-in, three items and a closing sentence."""

    source = SOURCE.model_copy(update={"clause": CLAUSE_OF[ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION]})
    nodes = tuple(
        ClauseNode(
            order=order,
            kind=kind,  # type: ignore[arg-type]
            raw_text=f"synthetic selection statement {order + 1}",
            source=source,
        )
        for order, kind in enumerate(kinds)
    )
    fragment = RawClauseFragment(
        id=f"raw-{ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION}",
        raw_sha256="0" * 64,
        nodes=nodes,
        tokens=(),
        source=source,
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def _selection(**inputs: str | bool) -> DecisionResult:
    rules, _proposals = project_dielectric_topology_selection(_topology_fragment(), IDENTITY)
    return evaluate_decision(rules[0], inputs)


def _application(
    reference_kind: str,
    classification: str,
    *,
    dvc_as: bool = False,
    connected: bool = False,
    enhanced: bool = False,
) -> dict[str, str | None]:
    result = _selection(
        reference_kind=reference_kind,
        test_classification=classification,
        circuit_under_test_is_dvc_as=dvc_as,
        circuit_connected_to_conductive_accessible_parts=connected,
        enhanced_protection=enhanced,
    )
    return {value.name: value.categorical for value in result.values}


def test_the_voltage_test_body_is_declared_under_its_own_subclause_locators() -> None:
    """Four required items, four subclauses. The value tables state none of this.

    A conformance review (issue #37, 2026-08-18, finding B3) found the whole body of the test
    unrepresented: the package carried Tables 28 and 29 and nothing that said how long to hold
    the voltage, between which electrodes, what to disconnect first, or what counts as a pass.
    """
    declared = {spec.semantic_id: spec for spec in PROCEDURE_CLAUSES}

    for semantic_id, segments in DIELECTRIC_BODY_SEGMENTS.items():
        spec = declared[semantic_id]
        assert spec.clause == CLAUSE_OF[semantic_id]
        assert len(spec.segments) == segments
        assert semantic_id in IEC_RECIPE.clause_projectors


def test_the_duration_rule_answers_the_question_nothing_in_the_package_answered() -> None:
    """The reviewed sentence reaches ``duration``, which is where a consumer asks.

    Slice 3 recorded every planned dielectric application as carrying an unresolved input
    because no resolved rule stated a duration. This is the rule that states it.
    """
    rules, proposals = project_dielectric_application_duration(
        _fragment(ids.TEST_DIELECTRIC_APPLICATION_DURATION, 1, kind="paragraph"),
        IDENTITY,
    )

    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))
    assert procedure.duration == procedure.procedure_steps[0].text
    assert procedure.duration
    # The matrix has a row for the parent subclause, not for this one, so nothing is claimed.
    assert procedure.classifications == ()
    assert [proposal.rule_kind for proposal in proposals] == ["procedure"]


def test_the_disconnection_rule_carries_one_step_per_reviewed_obligation() -> None:
    rules, _proposals = project_dielectric_disconnection(
        _fragment(ids.TEST_DIELECTRIC_DISCONNECTION, 4, kind="paragraph"),
        IDENTITY,
    )

    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))
    assert len(procedure.procedure_steps) == 4
    assert [step.order for step in procedure.procedure_steps] == [1, 2, 3, 4]
    assert procedure.classifications == ()


def test_the_acceptance_criterion_settles_both_of_its_outcomes() -> None:
    """Unlike the permissions in this module, an acceptance criterion has no unknown case.

    A breakdown is a failure, and a criterion that reported it as unresolved would leave a
    consumer unable to say the test failed.
    """
    rules, _proposals = project_dielectric_acceptance(
        _fragment(ids.TEST_DIELECTRIC_ACCEPTANCE, 1, kind="paragraph"),
        IDENTITY,
    )

    rule = next(item for item in rules if isinstance(item, DecisionRule))
    assert rule.exhaustive
    outcomes = {
        observed: evaluate_decision(rule, {"electric_breakdown_observed": observed})
        for observed in (False, True)
    }
    assert [value.boolean for value in outcomes[False].values] == [True]
    assert [value.boolean for value in outcomes[True].values] == [False]


def test_the_column_an_application_reads_follows_the_classification_and_the_reference() -> None:
    """Finding A4: the column is a property of the topology and the test, not of the pair.

    A basic-protection circuit tested against an accessible surface that is non-conductive or
    not bonded to earth reads the stronger column for its type test. Selecting from the pair's
    protection implementation alone planned that application at the weaker one.
    """
    basic, enhanced = DIELECTRIC_COLUMNS
    own_side, _higher = DIELECTRIC_ROW_AXIS_CIRCUITS
    surface = "unearthed_or_non_conductive_accessible_surface"

    assert _application(surface, "type_test") == {
        "dielectric_column": enhanced,
        "row_axis_circuit": own_side,
    }
    assert _application(surface, "routine_test")["dielectric_column"] == basic
    # And the routine test always reads the weaker column, however the circuit is protected.
    assert _application("adjacent_circuit", "routine_test", enhanced=True)["dielectric_column"] == (
        basic
    )
    assert _application("adjacent_circuit", "type_test", enhanced=True)["dielectric_column"] == (
        enhanced
    )
    assert _application("adjacent_circuit", "type_test")["dielectric_column"] == basic


def test_the_dvc_as_adjacency_reads_its_row_from_the_higher_voltage_circuit() -> None:
    """Finding A5: this one application is keyed on the other side of the pair."""
    basic, enhanced = DIELECTRIC_COLUMNS
    _own_side, higher = DIELECTRIC_ROW_AXIS_CIRCUITS

    assert _application("dvc_as_adjacent_circuit", "type_test") == {
        "dielectric_column": enhanced,
        "row_axis_circuit": higher,
    }
    assert _application("dvc_as_adjacent_circuit", "routine_test") == {
        "dielectric_column": basic,
        "row_axis_circuit": higher,
    }


def test_the_applications_the_source_states_are_not_made_resolve_to_no_column() -> None:
    """The two exclusions the subclause states, which the plan asserted its way past."""
    for reference_kind in (
        "earthed_conductive_accessible_part",
        "unearthed_or_non_conductive_accessible_surface",
    ):
        assert _application(reference_kind, "type_test", dvc_as=True) == {
            "dielectric_column": DIELECTRIC_NOT_APPLICABLE,
            "row_axis_circuit": DIELECTRIC_NOT_APPLICABLE,
        }
    assert (
        _application("adjacent_circuit", "routine_test", connected=True)["dielectric_column"]
        == DIELECTRIC_NOT_APPLICABLE
    )


def test_the_selection_names_only_columns_the_value_tables_project() -> None:
    """A column this rule named that no route projects would resolve to nothing."""
    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
        DIELECTRIC_SPECS,
    )

    routes = {spec.semantic_id.rsplit(".", 2)[1] for spec in DIELECTRIC_SPECS}

    assert set(DIELECTRIC_COLUMNS) <= routes
    rules, _proposals = project_dielectric_topology_selection(_topology_fragment(), IDENTITY)
    outputs = {output.name: output.allowed_values for output in rules[0].outputs}
    assert set(outputs["dielectric_column"]) == {*DIELECTRIC_COLUMNS, DIELECTRIC_NOT_APPLICABLE}
    inputs = {item.name: item.allowed_values for item in rules[0].inputs}
    assert inputs["reference_kind"] == DIELECTRIC_REFERENCE_KINDS
    assert inputs["test_classification"] == DIELECTRIC_TEST_CLASSIFICATIONS
    # A combination the subclause does not settle resolves to nothing rather than to a column.
    assert not rules[0].exhaustive


def test_each_voltage_test_body_projection_blocks_on_an_undeclared_node_shape() -> None:
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_dielectric_disconnection(
            _fragment(ids.TEST_DIELECTRIC_DISCONNECTION, 3, kind="paragraph"), IDENTITY
        )
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_dielectric_application_duration(
            _fragment(ids.TEST_DIELECTRIC_APPLICATION_DURATION, 2, kind="paragraph"), IDENTITY
        )
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_dielectric_acceptance(
            _fragment(ids.TEST_DIELECTRIC_ACCEPTANCE, 2, kind="paragraph"), IDENTITY
        )
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_dielectric_topology_selection(
            _topology_fragment(("paragraph", "bullet", "bullet")), IDENTITY
        )
