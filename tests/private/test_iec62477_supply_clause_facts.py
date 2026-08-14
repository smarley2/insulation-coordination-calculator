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
    BarrierTransferFact,
    CitedNode,
    DimensionScope,
    HfAttenuationFact,
    SpdMonitoringFact,
    SpdReductionFact,
    SupplyFact,
    SystemVoltageFact,
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


def _first_cited_node(draft: ImportedRuleDraft, route: str) -> tuple[CitedNode, ...]:
    """A citation of one real node of the route's own fragment, by identity and content.

    The nodes are the licensed ones -- a fact must cite its own clause -- but only their
    order and digest are read, never their text.
    """

    fragment = next(item for item in draft.raw_clause_fragments if item.id == f"raw-{route}")
    node = fragment.nodes[0]
    return (
        CitedNode(
            fragment_id=fragment.id,
            node_order=node.order,
            node_sha256=canonical_model_sha256(node),
        ),
    )


def _placeholder_facts(draft: ImportedRuleDraft) -> dict[str, SupplyFact]:
    """One local placeholder statement per non-legacy route: valid tokens, invented readings.

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
    """

    return {
        SV_ROUTE: SystemVoltageFact(
            statement_index=0,
            node_references=_first_cited_node(draft, SV_ROUTE),
            obligation="requirement",
            supply_kind="mains",
            phase_system="three_phase_delta",
            earthing="tn",
            input_topology="direct",
            purpose="impulse",
            measure="phase_to_earth_rms",
        ),
        SUPPLY_SYSTEM_VOLTAGE_NON_MAINS: SystemVoltageFact(
            statement_index=0,
            node_references=_first_cited_node(draft, SUPPLY_SYSTEM_VOLTAGE_NON_MAINS),
            obligation="requirement",
            supply_kind="non_mains",
            phase_system="single_phase_it",
            earthing="it",
            input_topology="isolated_secondary",
            purpose="temporary_overvoltage",
            measure="between_supply_conductors_rms",
        ),
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER: BarrierTransferFact(
            statement_index=0,
            node_references=_first_cited_node(draft, ids.SUPPLY_VERIFIED_BARRIER_TRANSFER),
            obligation="requirement",
            isolation_present=True,
            downstream_connection_kind="verified_galvanic_isolation",
            combined_circuit_rule="side_specific_from_transfer",
        ),
        SPD_MAINS_ROUTE: SpdReductionFact(
            statement_index=0,
            node_references=_first_cited_node(draft, SPD_MAINS_ROUTE),
            obligation="permission",
            supply_kind="mains",
            source_ovc="ovc_i",
            target_ovc="ovc_iv",
            insulation_class="basic",
            degradable=True,
            monitoring_obligation="required",
            monitoring_reference=SPD_MONITORING_ROUTE,
        ),
        SPD_NON_MAINS_ROUTE: SpdReductionFact(
            statement_index=0,
            node_references=_first_cited_node(draft, SPD_NON_MAINS_ROUTE),
            obligation="permission",
            supply_kind="non_mains",
            source_ovc="ovc_ii",
            target_ovc="ovc_i",
            insulation_class="double",
            degradable=False,
            monitoring_obligation="not_required",
            monitoring_reference=SPD_MONITORING_ROUTE,
        ),
        SPD_MONITORING_ROUTE: SpdMonitoringFact(
            statement_index=0,
            node_references=_first_cited_node(draft, SPD_MONITORING_ROUTE),
            obligation="requirement",
            device_placement="internal_to_pecs",
            participates_in_reduction=True,
            monitoring_required=True,
            compliance_evidence="monitoring_test",
        ),
        ids.SUPPLY_HF_TRANSFORMER_ATTENUATION: HfAttenuationFact(
            statement_index=0,
            node_references=_first_cited_node(draft, ids.SUPPLY_HF_TRANSFORMER_ATTENUATION),
            obligation="permission",
            dvc_gate=DimensionScope.of("dvc_b"),
            evidence_kind="simulation",
            threshold_reference=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
            comparison_required=True,
        ),
    }


def author_placeholder_supply_clause_facts(draft: ImportedRuleDraft) -> ImportedRuleDraft:
    """Author and complete one placeholder statement for every non-legacy supply route.

    Called from the shared private review pass, so every private test that builds or
    approves a licensed draft goes through the same authoring the maintainer's own session
    would. The statements are local placeholders -- see ``_placeholder_facts`` -- and prove
    only that the workflow reaches a projection, never what the clauses state.
    """

    facts = _placeholder_facts(draft)
    if set(facts) != set(AUTHORED_ROUTES):
        raise AssertionError(
            "every non-legacy supply route needs a placeholder statement; missing "
            f"{sorted(set(AUTHORED_ROUTES) - set(facts))}, unexpected "
            f"{sorted(set(facts) - set(AUTHORED_ROUTES))}"
        )
    for route, fact in facts.items():
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
