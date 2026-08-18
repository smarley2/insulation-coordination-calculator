"""Synthetic reinforced-treatment projections. Coined factors and quantities; no IEC content.

Every factor below is an obviously invented one -- a whole number nothing in any document
states -- and every branch is a token of the fact model's own declared vocabulary. What the
licensed clauses actually state is nowhere in this file, and the private suite is what checks
the recipe against them.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.clause_facts import (
    CitedNode,
    ConfirmedFacts,
    DimensionScope,
    ReinforcedFactorFact,
    ReinforcedLevelStepFact,
)
from insulation_coordination.rules.importer.extract import canonical_model_sha256
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.clauses import (
    ClauseStructureError,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.reinforced import (
    REINFORCED_CLAUSES,
    REINFORCED_FACT_FAMILY_BY_ROUTE,
    project_reinforced_treatment,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    SUPPLY_CLAUSES,
    SUPPLY_FACT_FAMILY_BY_ROUTE,
)
from tests.rules.importer.iec62477_2022.test_supply_clause_recipes import (
    IDENTITY,
    _mixed_fragment,
)

CLEARANCE = ids.CLEARANCE_REINFORCED_TREATMENT
CREEPAGE = ids.CREEPAGE_REINFORCED_TREATMENT

#: The rule each treatment is stated against, as its reviewed statements name it.
_REQUIREMENT = {
    CLEARANCE: ids.CLEARANCE_REQUIREMENTS,
    CREEPAGE: ids.CREEPAGE_REQUIREMENTS,
}

#: The node shapes the recipe declares for each route, so a fragment built here is one the
#: projector accepts for the route it is built for.
_SHAPES = {
    CLEARANCE: ("paragraph", "bullet", "bullet", "bullet", "paragraph"),
    CREEPAGE: ("paragraph", "paragraph"),
}


def _citation(route: str, node_order: int = 0) -> tuple[CitedNode, ...]:
    fragment = _mixed_fragment(route, _SHAPES[route])
    node = fragment.nodes[node_order]
    return (
        CitedNode(
            fragment_id=fragment.id,
            node_order=node.order,
            node_sha256=canonical_model_sha256(node),
        ),
    )


def _factor_fact(
    route: str,
    *,
    statement_index: int = 0,
    quantity: str = "working_voltage_peak",
    factor: str = "7",
    node_order: int = 0,
) -> ReinforcedFactorFact:
    return ReinforcedFactorFact(
        statement_index=statement_index,
        node_references=_citation(route, node_order),
        obligation="requirement",
        insulation_classes=DimensionScope[str].of("reinforced"),
        treated_quantity=DimensionScope[str].of(quantity),
        requirement_reference=_REQUIREMENT[route],
        factor=factor,
    )


def _step_fact(
    route: str,
    *,
    statement_index: int = 1,
    quantity: str = "impulse_withstand_voltage",
    node_order: int = 1,
) -> ReinforcedLevelStepFact:
    return ReinforcedLevelStepFact(
        statement_index=statement_index,
        node_references=_citation(route, node_order),
        obligation="requirement",
        insulation_classes=DimensionScope[str].of("reinforced"),
        treated_quantity=DimensionScope[str].of(quantity),
        requirement_reference=_REQUIREMENT[route],
    )


def _project(route: str, *facts: object) -> tuple:
    return project_reinforced_treatment(
        _mixed_fragment(route, _SHAPES[route]),
        IDENTITY,
        None,
        ConfirmedFacts(by_route={route: tuple(facts)}),  # type: ignore[arg-type]
    )


def test_both_treatment_routes_are_declared_specs_projectors_and_fact_routes() -> None:
    """A route the recipe forgets anywhere is unauthorable, unapprovable or unprojected."""

    declared = {spec.semantic_id: spec for spec in REINFORCED_CLAUSES}
    assert set(declared) == {CLEARANCE, CREEPAGE}
    assert set(declared) <= {spec.semantic_id for spec in SUPPLY_CLAUSES}
    assert set(declared) <= set(SUPPLY_FACT_FAMILY_BY_ROUTE)
    assert set(REINFORCED_FACT_FAMILY_BY_ROUTE.values()) == {"reinforced_treatment"}
    assert set(declared) <= set(IEC_RECIPE.clause_projectors)
    assert {spec.clause for spec in REINFORCED_CLAUSES} == {"4.4.7.4.2", "4.4.7.5.2"}


def test_a_spec_declares_locators_and_never_an_expected_value() -> None:
    """Page, bbox and root shape only: a recipe says where to look, never what will be found."""

    for spec in REINFORCED_CLAUSES:
        assert spec.output_kind == "decision"
        for segment in spec.segments:
            assert segment.page_number >= 1
            assert segment.expected_root_kind in ("paragraph", "bullets")
            left, top, right, bottom = segment.expected_bbox
            assert left < right and top < bottom


def test_a_factor_statement_projects_its_own_factor_and_the_multiply_mode() -> None:
    (rule,), (proposal,) = _project(CLEARANCE, _factor_fact(CLEARANCE))

    assert rule.id == CLEARANCE
    assert proposal.semantic_id == CLEARANCE
    assert tuple(item.name for item in rule.outputs) == (
        "treatment_mode",
        "treatment_multiplier",
        "preferred_level_axis",
    )
    result = evaluate_decision(
        rule, {"insulation_class": "reinforced", "treated_quantity": "working_voltage_peak"}
    )
    assert result.status == "matched"
    values = {item.name: item for item in result.values}
    assert values["treatment_mode"].categorical == "multiply"
    assert values["treatment_multiplier"].numeric == Decimal(7)
    assert values["preferred_level_axis"].reference == ids.CLEARANCE_REQUIREMENTS


def test_a_step_statement_states_the_axis_it_steps_along_and_scales_nothing() -> None:
    (rule,), _proposals = _project(CLEARANCE, _step_fact(CLEARANCE, statement_index=0))

    result = evaluate_decision(
        rule, {"insulation_class": "reinforced", "treated_quantity": "impulse_withstand_voltage"}
    )
    values = {item.name: item for item in result.values}
    assert values["treatment_mode"].categorical == "next_level_in_requirement_axis"
    assert values["treatment_multiplier"].numeric == Decimal(1)
    assert values["preferred_level_axis"].reference == ids.CLEARANCE_REQUIREMENTS


def test_one_clause_states_both_shapes_and_the_treated_quantity_separates_them() -> None:
    """The clearance clause steps one quantity and scales another, in one rule."""

    (rule,), _proposals = _project(CLEARANCE, _factor_fact(CLEARANCE), _step_fact(CLEARANCE))

    modes = {
        quantity: {
            item.name: item
            for item in evaluate_decision(
                rule, {"insulation_class": "reinforced", "treated_quantity": quantity}
            ).values
        }["treatment_mode"].categorical
        for quantity in ("working_voltage_peak", "impulse_withstand_voltage")
    }
    assert modes == {
        "working_voltage_peak": "multiply",
        "impulse_withstand_voltage": "next_level_in_requirement_axis",
    }


def test_the_creepage_rule_states_no_axis_because_its_requirement_is_two_rules() -> None:
    """A ``reference`` must resolve to exactly one package rule, and Table 9's is two routes.

    So the deferral stays a reviewed dimension of the statement and the rule does not carry it.
    Asserted rather than left implicit: an output that appeared here would be an unresolvable
    reference in the approved package, which is a validation failure a long way from its cause.
    """

    (rule,), _proposals = _project(CREEPAGE, _factor_fact(CREEPAGE))

    assert tuple(item.name for item in rule.outputs) == (
        "treatment_mode",
        "treatment_multiplier",
    )
    assert all(value.reference is None for row in rule.rows for value in row.values)


def test_a_class_no_reviewed_statement_covers_reaches_no_row() -> None:
    (rule,), _proposals = _project(CREEPAGE, _factor_fact(CREEPAGE))

    result = evaluate_decision(
        rule, {"insulation_class": "basic", "treated_quantity": "working_voltage_peak"}
    )
    assert result.status == "no_match"


def test_a_route_with_no_reviewed_fact_refuses_rather_than_projecting() -> None:
    with pytest.raises(ClauseStructureError, match="needs reviewed clause facts"):
        _project(CLEARANCE)


def test_two_statements_on_the_same_branch_are_refused() -> None:
    with pytest.raises(ClauseStructureError, match="not disjoint"):
        _project(
            CLEARANCE,
            _factor_fact(CLEARANCE),
            _factor_fact(CLEARANCE, statement_index=1, factor="9", node_order=1),
        )


def test_a_fragment_of_neither_route_is_refused() -> None:
    fragment = _mixed_fragment(ids.SUPPLY_HF_TRANSFORMER_ATTENUATION, ("paragraph",))
    with pytest.raises(ValueError, match="one of its own fragments"):
        project_reinforced_treatment(fragment, IDENTITY, None, ConfirmedFacts())


def test_a_reflowed_clause_blocks_instead_of_projecting_a_shape_nobody_reviewed() -> None:
    fragment = _mixed_fragment(CREEPAGE, ("paragraph",))
    with pytest.raises(ClauseStructureError, match="reviewed node"):
        project_reinforced_treatment(
            fragment,
            IDENTITY,
            None,
            ConfirmedFacts(by_route={CREEPAGE: (_factor_fact(CREEPAGE),)}),
        )


#: A comma decimal is in the list because a reviewer reading a document that writes decimals
#: that way will type one; the value itself is a coined one, as every literal in this file is.
@pytest.mark.parametrize("factor", ["0", "0.0", "-2", "two", "9,9", ""])
def test_a_factor_that_is_not_a_positive_number_cannot_be_authored(factor: str) -> None:
    """The one free-text dimension a reviewer types, so it validates where it is recorded."""

    with pytest.raises(ValueError):
        _factor_fact(CLEARANCE, factor=factor)
