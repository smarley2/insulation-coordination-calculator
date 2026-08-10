"""The shared derivation of what an approved package must contain.

These assertions exist to move one class of failure from a licensed run to a public one.
Every gate that decides package completeness -- the inventory report, the two approval
gates over compatibility mappings and recipe semantics, and the ``pcb_source_inventory``
validation check -- used to re-derive "which spec kind yields which rule" for itself. A new
spec kind (a comparison-only grid, a text-field table, any projector-backed spec) therefore
had to be taught to each gate separately, and every omission was discovered the same
expensive way: a full import of the licensed PDFs, fifteen minutes in, failing at approval.

The gates now read ``package_expectations``, and this module checks that derivation against
the real registry in under a second: every declared spec is classified by exactly one
expectation set, the sets do not contradict each other, and a spec whose kind the
derivation cannot classify raises instead of being silently assigned the wrong rule.
"""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.expectations import (
    UnknownSpecKindError,
    package_expectations,
)
from insulation_coordination.rules.importer.identify import StandardRecipe, TableAuditSpec
from insulation_coordination.rules.importer.recipes import RECIPES

EXPECTATIONS = package_expectations(RECIPES)
TABLE_SPECS = tuple((recipe, spec) for recipe in RECIPES for spec in recipe.tables)


def _recipe_with_a_projector() -> StandardRecipe:
    return next(recipe for recipe in RECIPES if recipe.grid_projectors)


def _recipe_with_comparison_evidence() -> StandardRecipe:
    return next(
        recipe for recipe in RECIPES if any(spec.comparison_only for spec in recipe.tables)
    )


def test_every_table_spec_is_classified_by_exactly_one_expectation_set() -> None:
    for recipe, spec in TABLE_SPECS:
        classifications = [
            spec.semantic_id in EXPECTATIONS.table_rule_ids,
            spec.semantic_id in EXPECTATIONS.evidence_grid_ids,
            bool(recipe.grid_projectors.get(spec.semantic_id))
            and bool(EXPECTATIONS.typed_results[spec.semantic_id])
            and EXPECTATIONS.typed_results[spec.semantic_id]
            <= EXPECTATIONS.projected_rule_ids,
        ]
        assert sum(classifications) == 1, spec.semantic_id


def test_every_declared_spec_has_a_typed_expectation_entry() -> None:
    declared = (
        {spec.semantic_id for _recipe, spec in TABLE_SPECS}
        | EXPECTATIONS.clause_rule_ids
        | EXPECTATIONS.curve_rule_ids
        | EXPECTATIONS.formula_ids
    )

    assert set(EXPECTATIONS.typed_results) == declared


def test_expectation_sets_do_not_contradict_each_other() -> None:
    # A comparison-only grid is evidence for a cross-standard check, so it can be neither a
    # table nor a projected rule; a projected rule can never also be a table.
    assert not EXPECTATIONS.evidence_grid_ids & EXPECTATIONS.table_rule_ids
    assert not EXPECTATIONS.evidence_grid_ids & EXPECTATIONS.projected_rule_ids
    assert not EXPECTATIONS.table_rule_ids & EXPECTATIONS.projected_rule_ids
    assert all(
        EXPECTATIONS.typed_results[semantic_id] == frozenset()
        for semantic_id in EXPECTATIONS.evidence_grid_ids
    )
    # Every table spec has a raw grid, evidence included, and only a rule with a source
    # artifact of its own is expected to have one: a formula is projected from the recipe.
    assert EXPECTATIONS.raw_grid_ids == {
        f"raw-{spec.semantic_id}" for _recipe, spec in TABLE_SPECS
    }
    assert EXPECTATIONS.raw_artifact_ids == (
        {spec.semantic_id for _recipe, spec in TABLE_SPECS}
        | EXPECTATIONS.clause_rule_ids
        | EXPECTATIONS.curve_rule_ids
    )
    assert not EXPECTATIONS.raw_artifact_ids & EXPECTATIONS.formula_ids


def test_every_projector_backed_spec_declares_the_rules_it_yields() -> None:
    for recipe, spec in TABLE_SPECS:
        if spec.semantic_id not in recipe.grid_projectors:
            continue
        routes = frozenset(spec.decision_route_ids)
        assert routes
        assert routes <= EXPECTATIONS.projected_rule_ids


def test_the_registry_declares_comparison_evidence_that_yields_no_rule() -> None:
    """Guards the premise the approval and validation gates now share.

    Slice D added grids extracted only to prove a cross-standard equivalence. A gate that
    still assumed every grid becomes a ``Table`` failed on the documents; this fails here.
    """
    assert EXPECTATIONS.evidence_grid_ids
    for semantic_id in EXPECTATIONS.evidence_grid_ids:
        assert f"raw-{semantic_id}" in EXPECTATIONS.raw_grid_ids
        assert not EXPECTATIONS.typed_results[semantic_id]


def test_proven_mappings_are_a_separate_family_from_the_declared_one() -> None:
    """A proven cross-standard mapping is permitted beside the declared family.

    The declared family must be exactly complete, so the two families must not overlap:
    otherwise a proven mapping would be subtracted from the family it belongs to and the
    gate would report the declared family incomplete.
    """
    assert EXPECTATIONS.proven_mapping_ids
    assert not EXPECTATIONS.proven_mapping_ids & EXPECTATIONS.declared_mapping_ids
    assert not EXPECTATIONS.proven_mapping_routes & EXPECTATIONS.declared_mapping_routes


def test_every_mapping_resolves_to_a_formula_the_package_carries() -> None:
    """Both mapping families target a formula, which is what ``mapping_links`` requires.

    A cross-standard check that named the compared grid instead of the rule produced a
    mapping validation rejected, and only a licensed run reached that rejection.
    """
    targets = {
        spec.target_rule_id for recipe in RECIPES for spec in recipe.mappings
    } | {check.target_rule_id for recipe in RECIPES for check in recipe.cross_standard_checks}

    assert targets <= EXPECTATIONS.formula_ids


def test_a_text_field_table_without_a_projector_is_refused() -> None:
    recipe = _recipe_with_a_projector()
    assert any(spec.text_field_table for spec in recipe.tables)

    with pytest.raises(UnknownSpecKindError, match="text field table"):
        package_expectations((recipe.model_copy(update={"grid_projectors": {}}),))


def test_a_projector_backed_spec_without_routes_is_refused() -> None:
    recipe = _recipe_with_a_projector()
    tables = tuple(
        spec.model_copy(update={"decision_route_ids": ()})
        if spec.semantic_id in recipe.grid_projectors
        else spec
        for spec in recipe.tables
    )

    with pytest.raises(UnknownSpecKindError, match="declares no route"):
        package_expectations((recipe.model_copy(update={"tables": tables}),))


def test_comparison_evidence_with_a_projector_is_refused() -> None:
    recipe = _recipe_with_comparison_evidence()
    projector = next(iter(_recipe_with_a_projector().grid_projectors.values()))
    evidence = next(spec for spec in recipe.tables if spec.comparison_only)

    with pytest.raises(UnknownSpecKindError, match="comparison evidence"):
        package_expectations(
            (recipe.model_copy(update={"grid_projectors": {evidence.semantic_id: projector}}),)
        )


def test_a_new_spec_kind_flag_must_be_taught_to_the_derivation() -> None:
    """A kind-selecting flag the derivation does not read fails here, loudly.

    ``package_expectations`` classifies a table spec from ``comparison_only``,
    ``text_field_table`` and whether a grid projector is registered. A further boolean flag
    on the spec would be a further kind, and every gate reading this derivation would
    silently expect the wrong rule for it.
    """
    boolean_flags = {
        name
        for name, field in TableAuditSpec.model_fields.items()
        if field.annotation is bool
    }

    assert boolean_flags == {"comparison_only", "text_field_table"}
