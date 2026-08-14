"""Private clause-fact workflow: every non-legacy supply route authors, completes and projects.

The licensed clauses are read at runtime; nothing here records what they state. The facts
this module authors are **local placeholders**, exactly as
``_complete_manual_curve_review`` uses placeholder calibration and points: arbitrary but
valid vocabulary tokens chosen only to be structurally distinct. ``tests/private/`` is
committed to the public repository and only its *execution* needs the PDFs, so a real fact
set written here would publish each clause's normative branches as tokens -- which is
precisely what this slice removed from public code. The real statement inventory has no
anchor in this repository, the same way the reviewed curve digest has none, and the real
authoring session is the maintainer's, through the Rules Manager's fact editor.

Every assertion below is about workflow and structure -- which route authors which fact
family, that both system-voltage evidence scopes are required, that the declared rule ids
are projected, that an approved archive round-trips -- never about the inventory, its size
or its distribution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.importer.approval import approval_blockers
from insulation_coordination.rules.importer.clause_facts import (
    BarrierCombinedRequirementFact,
    CitedNode,
    DimensionScope,
    HfAttenuationFact,
    OvercategoryStep,
    SpdMonitoringRequirementFact,
    SpdReductionMonitoringFact,
    SpdReductionPermissionFact,
    SupplyFact,
    SystemVoltageApplicabilityFact,
    SystemVoltageMeasureFact,
)
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    LEGACY_BRANCH_AUTHORITY_RULE_IDS,
    SUPPLY_CLAUSES,
    SUPPLY_FACT_FAMILY_BY_ROUTE,
    SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,
)
from insulation_coordination.rules.importer.review import (
    ClauseFactResolutionError,
    author_clause_fact,
    record_fact_completion,
    resolve_confirmed_clause_facts,
    retract_clause_fact,
)
from tests.private.test_iec62477_slice_c_roundtrip import _approved_slice_c

pytestmark = pytest.mark.private_standard

SV_ROUTE = ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
SPD_MAINS_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"
SPD_NON_MAINS_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains"
SPD_MONITORING_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"

#: Every supply route whose branch authority is a reviewed fact, so every route this
#: module has to author. Derived from the recipe's own declaration rather than listed, so a
#: route added later is authored here or fails loudly instead of silently skipping the gate.
AUTHORED_ROUTES: tuple[str, ...] = tuple(
    route for route in SUPPLY_FACT_FAMILY_BY_ROUTE if route not in LEGACY_BRANCH_AUTHORITY_RULE_IDS
)


def _cited_node(draft: ImportedRuleDraft, route: str, node_order: int) -> tuple[CitedNode, ...]:
    """A citation of one real node of the route's own fragment, by identity and content.

    The nodes are the licensed ones -- a fact must cite its own clause -- but only their
    order and digest are read, never their text.
    """

    fragment = next(item for item in draft.raw_clause_fragments if item.id == f"raw-{route}")
    node = next(item for item in fragment.nodes if item.order == node_order)
    return (
        CitedNode(
            fragment_id=fragment.id,
            node_order=node.order,
            node_sha256=canonical_model_sha256(node),
        ),
    )


def _first_cited_node(draft: ImportedRuleDraft, route: str) -> tuple[CitedNode, ...]:
    """A citation of the route's own first node."""

    fragment = next(item for item in draft.raw_clause_fragments if item.id == f"raw-{route}")
    return _cited_node(draft, route, fragment.nodes[0].order)


#: Structurally distinct tokens for the placeholder applicability statements below, cycled by node
#: so no two of them read alike beyond the node each rests on. Vocabulary tokens only; they state
#: nothing about the clause.
_PLACEHOLDER_TOPOLOGIES = (
    "direct",
    "rectified_dc",
    "series_rectifier_bridges",
    "isolated_secondary",
    "any_input_topology",
)


def _system_voltage_placeholders(
    draft: ImportedRuleDraft, route: str, supply_kind: str
) -> tuple[SupplyFact, ...]:
    """One placeholder statement per node of a system voltage subclause's fragment.

    The completion guard refuses a route that leaves a known statement of its clause unauthored,
    and this subclause is the one whose licensed fragment carries a bullet list, so a single
    statement cannot complete it. Only the measure statement is projected; every other node gets
    the **carried** applicability variant, which contributes no row and so cannot invent a branch
    the source does not state while still recording that the node was read.

    Driven off the fragment's own node count rather than a number written here, so the licensed
    document's structure decides how many statements the workflow authors -- and so re-extracting
    a widened clause region changes this fixture's behaviour rather than breaking it. Still
    placeholders: each field is a token of its own declared vocabulary, cycled for structural
    distinctness only.
    """

    fragment = next(item for item in draft.raw_clause_fragments if item.id == f"raw-{route}")
    measure = SystemVoltageMeasureFact(
        statement_index=0,
        node_references=_cited_node(draft, route, fragment.nodes[0].order),
        obligation="requirement",
        supply_kind=supply_kind,  # type: ignore[arg-type]
        phase_system="three_phase_delta" if supply_kind == "mains" else "single_phase_it",
        earthing="tn" if supply_kind == "mains" else "it",
        input_topology="direct" if supply_kind == "mains" else "isolated_secondary",
        purpose="impulse" if supply_kind == "mains" else "temporary_overvoltage",
        measure="phase_to_earth_rms" if supply_kind == "mains" else "between_supply_conductors_rms",
    )
    carried = tuple(
        SystemVoltageApplicabilityFact(
            statement_index=index,
            node_references=_cited_node(draft, route, node.order),
            obligation="requirement",
            supply_kind=supply_kind,  # type: ignore[arg-type]
            input_topology=_PLACEHOLDER_TOPOLOGIES[index % len(_PLACEHOLDER_TOPOLOGIES)],  # type: ignore[arg-type]
            purpose="impulse" if index % 2 else "temporary_overvoltage",
            counts_as_system_voltage=bool(index % 2),
        )
        for index, node in enumerate(fragment.nodes[1:], start=1)
    )
    return (measure, *carried)


def _placeholder_facts(draft: ImportedRuleDraft) -> dict[str, tuple[SupplyFact, ...]]:
    """Local placeholder statements per non-legacy route: valid tokens, invented readings.

    Not the source's readings, and not to be read as them. Each field is filled with a token of
    its own declared vocabulary picked for structural distinctness only, and deliberately
    combined so no set here reads as a plausible reviewed reading -- a category step is authored
    inverted, and a phase system is paired with a measure that does not belong to it. What this
    module proves is that the workflow runs against the real documents, never what the documents
    say.

    The two system-voltage scopes project into one rule's rows, so their dimensions are authored
    explicitly and differ: ``_require_distinct_branches`` refuses a set whose distinguishing
    dimension nobody authored, and an unrestricted ``any_*`` beside a specific value is exactly
    the overlap it exists to catch.

    A tuple per route rather than one statement, for two independent reasons that both have to
    hold. The completion guard refuses a route that leaves a known statement of its clause
    unauthored -- see ``_system_voltage_placeholders`` for the subclause whose licensed fragment
    carries a list, which one statement therefore cannot complete. And a route whose clause
    projects more than one rule needs a statement of each kind those rules are built from: a
    reduction clause projects a permission rule and its reducing device's monitoring rule, and the
    second exists only if a monitoring statement was reviewed for it. Where neither reason applies
    the tuple holds one statement.
    """

    return {
        SV_ROUTE: _system_voltage_placeholders(draft, SV_ROUTE, "mains"),
        SUPPLY_SYSTEM_VOLTAGE_NON_MAINS: _system_voltage_placeholders(
            draft, SUPPLY_SYSTEM_VOLTAGE_NON_MAINS, "non_mains"
        ),
        # The isolation this clause is scoped by is route-declared now, so this placeholder can no
        # longer state the positive-isolation reading it used to: that combination contradicted the
        # fragment it cited, and nothing refused it.
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER: (
            BarrierCombinedRequirementFact(
                statement_index=0,
                node_references=_first_cited_node(draft, ids.SUPPLY_VERIFIED_BARRIER_TRANSFER),
                obligation="requirement",
                combined_circuit_rule="side_specific_from_transfer",
            ),
        ),
        # Two statements per reduction route, because the clause projects two rules and the second
        # exists only if a statement was reviewed for it. A transition authored the wrong way up
        # the scale, so no placeholder here reads as a plausible reviewed permission.
        SPD_MAINS_ROUTE: (
            SpdReductionPermissionFact(
                statement_index=0,
                node_references=_first_cited_node(draft, SPD_MAINS_ROUTE),
                obligation="permission",
                supply_kind="mains",
                permitted_steps=(OvercategoryStep(source_ovc="ovc_i", target_ovc="ovc_iv"),),
                insulation_classes=DimensionScope.of("basic"),
            ),
            SpdReductionMonitoringFact(
                statement_index=1,
                node_references=_first_cited_node(draft, SPD_MAINS_ROUTE),
                obligation="requirement",
                supply_kind="mains",
                device_degradable=True,
                monitoring_obligation="required",
                status_indication="required",
                monitoring_reference=SPD_MONITORING_ROUTE,
            ),
        ),
        SPD_NON_MAINS_ROUTE: (
            SpdReductionPermissionFact(
                statement_index=0,
                node_references=_first_cited_node(draft, SPD_NON_MAINS_ROUTE),
                obligation="permission",
                supply_kind="non_mains",
                permitted_steps=(OvercategoryStep(source_ovc="ovc_ii", target_ovc="ovc_i"),),
                insulation_classes=DimensionScope.of("double"),
            ),
            SpdReductionMonitoringFact(
                statement_index=1,
                node_references=_first_cited_node(draft, SPD_NON_MAINS_ROUTE),
                obligation="requirement",
                supply_kind="non_mains",
                device_degradable=False,
                monitoring_obligation="not_required",
                status_indication="not_required",
                monitoring_reference=SPD_MONITORING_ROUTE,
            ),
        ),
        SPD_MONITORING_ROUTE: (
            SpdMonitoringRequirementFact(
                statement_index=0,
                node_references=_first_cited_node(draft, SPD_MONITORING_ROUTE),
                obligation="requirement",
                device_placement=DimensionScope.of("internal_to_pecs"),
                participates_in_reduction=True,
            ),
        ),
        ids.SUPPLY_HF_TRANSFORMER_ATTENUATION: (
            HfAttenuationFact(
                statement_index=0,
                node_references=_first_cited_node(draft, ids.SUPPLY_HF_TRANSFORMER_ATTENUATION),
                obligation="permission",
                dvc_gate=DimensionScope.of("dvc_b"),
                evidence_kind="simulation",
                threshold_reference=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
                comparison_required=True,
            ),
        ),
    }


def author_placeholder_supply_clause_facts(draft: ImportedRuleDraft) -> ImportedRuleDraft:
    """Author and complete placeholder statements for every non-legacy supply route.

    Called from the shared private review pass, so every private test that builds or
    approves a licensed draft goes through the same authoring the maintainer's own session
    would -- the completion guard included, which is what forces a subclause carrying several
    statements to be authored several times over rather than certified once. The statements are
    local placeholders -- see ``_placeholder_facts`` -- and prove only that the workflow reaches a
    projection, never what the clauses state.

    Completion is recorded once per route after all of its statements, because the record binds the
    route's whole fact-set digest: recording it between two statements would bind a set the second
    one then changes -- and because the guard is evaluated against the statements authored so far,
    so a route is certified only once every one of them is in.
    """

    facts = _placeholder_facts(draft)
    if set(facts) != set(AUTHORED_ROUTES):
        raise AssertionError(
            "every non-legacy supply route needs a placeholder statement; missing "
            f"{sorted(set(AUTHORED_ROUTES) - set(facts))}, unexpected "
            f"{sorted(set(facts) - set(AUTHORED_ROUTES))}"
        )
    for route, statements in facts.items():
        for fact in statements:
            draft = author_clause_fact(
                draft,
                rule_route=route,
                fact=fact,
                actor="Private fixture reviewer",
                notes="Authored local placeholder statement.",
            )
        draft = record_fact_completion(
            draft,
            rule_route=route,
            fragment_id=f"raw-{route}",
            actor="Private fixture reviewer",
            notes="Asserted the placeholder fact set complete.",
        )
    return draft


def test_every_non_legacy_route_authors_its_declared_family_and_resolves(
    reviewed_draft,
) -> None:
    """The workflow, per route: the declared family, its own completion, and resolution."""

    reviews = {item.rule_route: item.fact for item in reviewed_draft.clause_fact_reviews}
    completions = {item.rule_route: item for item in reviewed_draft.clause_fact_completions}

    assert set(reviews) == set(AUTHORED_ROUTES)
    for route in AUTHORED_ROUTES:
        assert reviews[route].fact_kind == SUPPLY_FACT_FAMILY_BY_ROUTE[route], route
        assert completions[route].fragment_id == f"raw-{route}", route

    for spec in SUPPLY_CLAUSES:
        confirmed = resolve_confirmed_clause_facts(spec, reviewed_draft)
        for route in confirmed.by_route:
            assert confirmed.for_route(route), route
            assert all(
                fact.fact_kind == SUPPLY_FACT_FAMILY_BY_ROUTE[route]
                for fact in confirmed.for_route(route)
            ), route


def test_the_legacy_route_projects_from_its_recipe_with_no_authored_facts(
    reviewed_draft,
) -> None:
    """The single declared exception: its rule is projected, and nobody authored it."""

    projected = {rule.id for rule in reviewed_draft.decisions}

    for route in LEGACY_BRANCH_AUTHORITY_RULE_IDS:
        assert route in projected, route
        assert not any(item.rule_route == route for item in reviewed_draft.clause_fact_reviews), (
            route
        )


def test_the_reviewed_draft_projects_every_declared_supply_rule(reviewed_draft) -> None:
    """Fact-driven projection yields the rule ids the recipe declares, and blocks nothing."""

    projected = {rule.id for rule in reviewed_draft.decisions} | {
        rule.id for rule in reviewed_draft.guidance
    }
    declared = {
        route
        for spec in SUPPLY_CLAUSES
        if spec.projection_role != "evidence"
        for route in (spec.projected_rule_ids or (spec.semantic_id,))
    }

    assert declared <= projected
    assert "CLAUSE_FACT_REVIEW_REQUIRED" not in {
        item.code for item in approval_blockers(reviewed_draft)
    }


def test_both_system_voltage_evidence_scopes_are_required(reviewed_draft) -> None:
    """One rule, two subclauses: dropping either scope's statement refuses the whole rule."""

    spec = next(item for item in SUPPLY_CLAUSES if item.semantic_id == SV_ROUTE)

    for route in (SV_ROUTE, SUPPLY_SYSTEM_VOLTAGE_NON_MAINS):
        without = retract_clause_fact(
            reviewed_draft,
            rule_route=route,
            statement_index=0,
            actor="Private fixture reviewer",
            notes="Retracted the placeholder statement.",
        )
        with pytest.raises(ClauseFactResolutionError, match=route):
            resolve_confirmed_clause_facts(spec, without)


def test_the_approved_archive_does_not_carry_the_clause_fact_collections(
    reviewed_draft,
    tmp_path: Path,
) -> None:
    """Reviewed facts are draft-only by design: the package carries the projected rules.

    An approved package is what a consumer receives, and it answers questions rather than
    recording who reviewed which statement. The declared supply rules must survive the
    archive; the review records must not appear in it at all.
    """

    package = _approved_slice_c(reviewed_draft)
    archive = tmp_path / "supply-clause-facts.icrules"
    write_rule_package(archive, package)
    reloaded = load_rule_package(archive)

    assert {SV_ROUTE, ids.SUPPLY_HF_TRANSFORMER_ATTENUATION} <= {
        rule.id for rule in reloaded.decisions
    }
    assert not {"clause_fact_reviews", "clause_fact_completions"} & set(reloaded.model_dump())
