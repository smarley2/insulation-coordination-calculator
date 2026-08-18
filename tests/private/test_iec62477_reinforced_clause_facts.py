"""The licensed document yields the two reinforced treatment rules from reviewed statements.

The clauses are read at runtime and nothing here records what they state: the statements the
shared review pass authors are local placeholders -- see ``_reinforced_placeholders`` -- and every
assertion below is about structure. That a fragment was extracted for each treatment, that its
node shape is the one the recipe declares, that the projected rule states a mode, a multiplier and
the requirement it defers to, and that the multiplier a row carries is the one its own statement
was authored with rather than anything written in this repository.

What the source's own factors are has no anchor here, the same way the reviewed curve digest has
none. The maintainer authors them in the Rules Manager's fact editor, against the clause text the
private fragment shows them.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.reinforced import (
    REINFORCED_CLAUSES,
    project_reinforced_treatment,
)
from insulation_coordination.rules.importer.review import resolve_confirmed_clause_facts
from tests.private.test_iec62477_supply_clause_facts import _PLACEHOLDER_FACTOR

pytestmark = pytest.mark.private_standard

ROUTES = (ids.CLEARANCE_REINFORCED_TREATMENT, ids.CREEPAGE_REINFORCED_TREATMENT)

#: What a treatment statement can answer, and nothing else: which operation and by how much,
#: plus -- where the requirement it defers to is a single rule of the package -- the axis a step
#: moves along. Asserted as a tuple so an output added without a reviewed statement to fill it is
#: caught here rather than surfacing as a fabricated value in a consumer.
_OUTPUTS = {
    ids.CLEARANCE_REINFORCED_TREATMENT: (
        "treatment_mode",
        "treatment_multiplier",
        "preferred_level_axis",
    ),
    ids.CREEPAGE_REINFORCED_TREATMENT: ("treatment_mode", "treatment_multiplier"),
}


def _spec(route: str):
    return next(item for item in REINFORCED_CLAUSES if item.semantic_id == route)


def _identity(draft: ImportedRuleDraft, fragment) -> StandardIdentity:
    """The identity of the document this fragment was read from, as the projector checks it."""

    return next(
        item
        for item in draft.source_identities
        if item.standard == fragment.source.standard and item.edition == fragment.source.edition
    )


@pytest.mark.parametrize("route", ROUTES)
def test_the_licensed_document_yields_each_treatment_fragment(
    extracted_draft: ImportedRuleDraft, route: str
) -> None:
    """The declared regions reach a fragment, and it reads as the shape the recipe reviewed."""

    fragment = next(
        (item for item in extracted_draft.raw_clause_fragments if item.id == f"raw-{route}"), None
    )
    assert fragment is not None, route
    assert fragment.segments == _spec(route).segments
    # Every declared region contributed at least one node, so no part of the clause the recipe
    # points at was reached by nothing.
    assert {node.segment_index for node in fragment.nodes} == set(range(len(fragment.segments)))


@pytest.mark.parametrize("route", ROUTES)
def test_the_reviewed_statements_project_the_treatment_rule(
    reviewed_draft: ImportedRuleDraft, route: str
) -> None:
    """Point 5 of #110: the reviewed fact set, on the licensed fragment, is the rule."""

    fragment = next(
        item for item in reviewed_draft.raw_clause_fragments if item.id == f"raw-{route}"
    )
    confirmed = resolve_confirmed_clause_facts(_spec(route), reviewed_draft)
    facts = confirmed.for_route(route)
    assert facts, route

    (rule,), (proposal,) = project_reinforced_treatment(
        fragment, _identity(reviewed_draft, fragment), reviewed_draft, confirmed
    )
    assert rule.id == route
    assert proposal.semantic_id == route
    assert tuple(item.name for item in rule.inputs) == ("insulation_class", "treated_quantity")
    assert tuple(item.name for item in rule.outputs) == _OUTPUTS[route]
    # One row per reviewed statement: a projection inventing a branch nobody authored, or dropping
    # one somebody did, is what this counts.
    assert len(rule.rows) == len(facts)
    assert all(
        item.reference == route.rsplit(".", 1)[0] + ".requirements"
        for row in rule.rows
        for item in row.values
        if item.name == "requirement_reference"
    )


@pytest.mark.parametrize("route", ROUTES)
def test_a_row_carries_the_mode_and_the_factor_its_own_statement_states(
    reviewed_draft: ImportedRuleDraft, route: str
) -> None:
    """The factor reaches the rule from the reviewed statement, never from this repository."""

    fragment = next(
        item for item in reviewed_draft.raw_clause_fragments if item.id == f"raw-{route}"
    )
    confirmed = resolve_confirmed_clause_facts(_spec(route), reviewed_draft)
    (rule,), _proposals = project_reinforced_treatment(
        fragment, _identity(reviewed_draft, fragment), reviewed_draft, confirmed
    )

    answers = {}
    for fact in confirmed.for_route(route):
        result = evaluate_decision(
            rule,
            {
                "insulation_class": fact.insulation_classes.values[0],
                "treated_quantity": fact.treated_quantity.values[0],
            },
        )
        assert result.status == "matched"
        values = {item.name: item for item in result.values}
        answers[values["treatment_mode"].categorical] = values["treatment_multiplier"].numeric

    # The step statement scales nothing and the factor statements carry the placeholder factor the
    # fixture authored, so the rule reports exactly what was reviewed for it.
    assert answers["multiply"] == Decimal(_PLACEHOLDER_FACTOR)
    if "next_level_in_requirement_axis" in answers:
        assert answers["next_level_in_requirement_axis"] == Decimal(1)


@pytest.mark.parametrize("route", ROUTES)
def test_the_reviewed_draft_projects_each_treatment_rule(
    reviewed_draft: ImportedRuleDraft, route: str
) -> None:
    """And the draft's own projection carries it, so the approved package will."""

    assert route in {rule.id for rule in reviewed_draft.decisions}
