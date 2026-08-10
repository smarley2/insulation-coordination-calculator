"""What an approved package must contain, derived once from the recipe registry.

Five gates decide whether a package is complete: the inventory report, the two approval
gates over mappings and recipe semantics, and the ``pcb_source_inventory`` validation
check. Each used to re-derive "which spec yields which rule" from its own reading of the
spec kinds, so a new kind -- a comparison-only grid, a text-field table, any
projector-backed spec -- had to be taught to all of them separately, and each omission
surfaced only once a licensed run reached approval.

They now all read one derivation. ``package_expectations`` takes the registry as an
argument rather than importing it, so a test can inject a recipe tuple, and it raises on a
spec whose kind it cannot classify rather than silently expecting the wrong rule.
"""

from __future__ import annotations

from collections.abc import Mapping

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.rules.importer.identify import StandardRecipe


class UnknownSpecKindError(ValueError):
    """A declared spec whose kind this derivation does not classify.

    Raised rather than guessed: a spec silently assigned the wrong expectation makes a
    package fail approval on the documents, minutes into a licensed run, with no hint
    about which spec caused it.
    """


class PackageExpectations(FrozenModel):
    """Every identifier family an approved package is expected to carry."""

    #: ``raw-<semantic id>`` for every table spec, comparison-only ones included: the raw
    #: grid is what review reads and what a cross-standard check compares.
    raw_grid_ids: frozenset[str]
    #: Specs that must have a raw artifact of some kind -- grid, clause fragment or traced
    #: figure -- named by bare semantic id. Formulas are projected and have none.
    raw_artifact_ids: frozenset[str]
    #: Table specs that project a ``Table``: no registered projector, not comparison-only.
    table_rule_ids: frozenset[str]
    #: The rules a registered grid projector yields, from the routes its spec declares.
    projected_rule_ids: frozenset[str]
    #: Comparison-only specs. Evidence for a cross-standard check; they yield no rule.
    evidence_grid_ids: frozenset[str]
    formula_ids: frozenset[str]
    clause_rule_ids: frozenset[str]
    curve_rule_ids: frozenset[str]
    declared_mapping_ids: frozenset[str]
    declared_mapping_routes: frozenset[str]
    #: Mappings a cross-standard comparison proves. Permitted beside the declared family
    #: rather than required: the comparison itself refuses a divergence during review.
    proven_mapping_ids: frozenset[str]
    proven_mapping_routes: frozenset[str]
    #: Per declared spec, the typed rule ids it must contribute -- empty for a spec that
    #: contributes evidence only. Its keys are every spec the registry declares, which is
    #: what completeness reporting matches required inventory items against.
    typed_results: Mapping[str, frozenset[str]]


def package_expectations(recipes: tuple[StandardRecipe, ...]) -> PackageExpectations:
    """Derive the package expectations of a recipe registry."""
    raw_grid_ids: set[str] = set()
    raw_artifact_ids: set[str] = set()
    table_rule_ids: set[str] = set()
    projected_rule_ids: set[str] = set()
    evidence_grid_ids: set[str] = set()
    formula_ids: set[str] = set()
    clause_rule_ids: set[str] = set()
    curve_rule_ids: set[str] = set()
    typed_results: dict[str, frozenset[str]] = {}
    for recipe in recipes:
        for table_spec in recipe.tables:
            semantic_id = table_spec.semantic_id
            raw_grid_ids.add(f"raw-{semantic_id}")
            raw_artifact_ids.add(semantic_id)
            projector = recipe.grid_projectors.get(semantic_id)
            if table_spec.comparison_only:
                if projector is not None:
                    raise UnknownSpecKindError(
                        f"{semantic_id!r} is comparison evidence and cannot be projected"
                    )
                evidence_grid_ids.add(semantic_id)
                typed_results[semantic_id] = frozenset()
            elif projector is not None:
                if not table_spec.decision_route_ids:
                    raise UnknownSpecKindError(
                        f"{semantic_id!r} has a grid projector but declares no route, so "
                        "there is no way to know which rules it must yield"
                    )
                routes = frozenset(table_spec.decision_route_ids)
                projected_rule_ids |= routes
                typed_results[semantic_id] = routes
            elif table_spec.text_field_table:
                raise UnknownSpecKindError(
                    f"{semantic_id!r} is a text field table, whose reviewed text cells only "
                    "a projection understands, so it must register a grid projector"
                )
            else:
                table_rule_ids.add(semantic_id)
                typed_results[semantic_id] = frozenset({semantic_id})
        for clause_spec in recipe.clauses:
            clause_rule_ids.add(clause_spec.semantic_id)
            raw_artifact_ids.add(clause_spec.semantic_id)
            typed_results[clause_spec.semantic_id] = frozenset({clause_spec.semantic_id})
        for curve_spec in recipe.curves:
            curve_rule_ids.add(curve_spec.semantic_id)
            raw_artifact_ids.add(curve_spec.semantic_id)
            typed_results[curve_spec.semantic_id] = frozenset({curve_spec.semantic_id})
        for formula_spec in recipe.formulas:
            # Projected from its recipe and the reviewed grids, with no raw artifact of its
            # own, so it is only ever a typed expectation.
            formula_ids.add(formula_spec.semantic_id)
            typed_results[formula_spec.semantic_id] = frozenset({formula_spec.semantic_id})
    return PackageExpectations(
        raw_grid_ids=frozenset(raw_grid_ids),
        raw_artifact_ids=frozenset(raw_artifact_ids),
        table_rule_ids=frozenset(table_rule_ids),
        projected_rule_ids=frozenset(projected_rule_ids),
        evidence_grid_ids=frozenset(evidence_grid_ids),
        formula_ids=frozenset(formula_ids),
        clause_rule_ids=frozenset(clause_rule_ids),
        curve_rule_ids=frozenset(curve_rule_ids),
        declared_mapping_ids=frozenset(
            spec.id for recipe in recipes for spec in recipe.mappings
        ),
        declared_mapping_routes=frozenset(
            spec.semantic_route for recipe in recipes for spec in recipe.mappings
        ),
        proven_mapping_ids=frozenset(
            check.id for recipe in recipes for check in recipe.cross_standard_checks
        ),
        proven_mapping_routes=frozenset(
            check.source_rule_id for recipe in recipes for check in recipe.cross_standard_checks
        ),
        typed_results=typed_results,
    )


__all__ = ["PackageExpectations", "UnknownSpecKindError", "package_expectations"]
