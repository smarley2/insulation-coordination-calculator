"""The authoring surface: the reviewer reads nodes and writes facts. No logic in Qt."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args

import pytest
from pydantic import BaseModel
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QPushButton

from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.importer import clause_fact_proposals
from insulation_coordination.rules.importer.clause_fact_proposals import (
    ClauseFactProposal,
    fact_variants,
    pair_wire,
    scope_wire,
)
from insulation_coordination.rules.importer.clause_facts import (
    BarrierCombinedRequirementFact,
    BarrierDownstreamInheritanceFact,
    BarrierRatingResolutionFact,
    CitedNode,
    DimensionScope,
    HfAttenuationPermissionFact,
    HfAttenuationRequirementFact,
    RouteReference,
    SpdMonitoringComplianceFact,
    SpdMonitoringExemptionFact,
    SpdMonitoringRequirementFact,
    SpdReductionFloorFact,
    SpdReductionMonitoringFact,
    SpdReductionPermissionFact,
    SystemVoltageApplicabilityFact,
    SystemVoltageMeasureFact,
    pair_vocabulary,
    scope_vocabulary,
)
from insulation_coordination.rules.importer.clauses import ClauseNode, RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import ClauseSegmentSpec
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    LEGACY_BRANCH_AUTHORITY_RULE_IDS,
    SUPPLY_CLAUSES,
    SUPPLY_FACT_FAMILY_BY_ROUTE,
    SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE,
    declared_rule_references,
)
from insulation_coordination.ui import clause_fact_review
from insulation_coordination.ui.clause_fact_review import (
    _HEADINGS,
    ClauseFactReviewDialog,
    ClauseFactReviewModel,
)
from tests.conftest import _logged
from tests.fixtures.synthetic_pdf import create_clause_pdf
from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft
from tests.rules.importer.iec62477_2022.test_supply_clause_recipes import SOURCE, _fragment
from tests.rules.importer.test_clause_fact_proposals import fragment_with_sentences
from tests.rules.importer.test_clause_fact_review_api import _hf_fact

HF_ROUTE = ids.SUPPLY_HF_TRANSFORMER_ATTENUATION
MAINS_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"
SV_ROUTE = ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
_STATUS_COLUMN = 2

#: The synthetic clause fixture's own bullet region, for the source preview. Invented geometry
#: over an invented PDF; it matches the region ``tests/rules/test_clause_extraction.py`` declares.
_PREVIEW_SEGMENT = ClauseSegmentSpec(
    page_number=3,
    expected_bbox=(70.0, 300.0, 524.0, 700.0),
    expected_root_kind="bullets",
)

# Stated here independently of the UI's own mapping, so these tests prove the editor offers the
# family the route declares rather than agreeing with whatever the dialog decided. Each family
# maps to its declared statement variants: a family whose clause states two kinds of reading has
# no single model whose fields answer for all of it.
_FACT_MODELS: dict[str, tuple[type[BaseModel], ...]] = {
    "system_voltage": (SystemVoltageMeasureFact, SystemVoltageApplicabilityFact),
    "barrier_transfer": (
        BarrierRatingResolutionFact,
        BarrierCombinedRequirementFact,
        BarrierDownstreamInheritanceFact,
    ),
    "spd_reduction": (
        SpdReductionPermissionFact,
        SpdReductionFloorFact,
        SpdReductionMonitoringFact,
    ),
    "spd_monitoring": (
        SpdMonitoringRequirementFact,
        SpdMonitoringExemptionFact,
        SpdMonitoringComplianceFact,
    ),
    "hf_attenuation": (HfAttenuationPermissionFact, HfAttenuationRequirementFact),
}
_UNDIMENSIONED = ("fact_kind", "statement_kind", "statement_index", "node_references")


def _declared_variants(models: tuple[type[BaseModel], ...]) -> tuple[str | None, ...]:
    """Each statement kind a family declares, or ``(None,)`` for a family that states one kind."""

    if len(models) == 1:
        return (None,)
    return tuple(
        str(get_args(model.model_fields["statement_kind"].annotation)[0]) for model in models
    )


def _variant_model(fact_kind: str, statement_kind: str | None) -> type[BaseModel]:
    if statement_kind is None:
        (model,) = _FACT_MODELS[fact_kind]
        return model
    return next(
        model
        for model in _FACT_MODELS[fact_kind]
        if get_args(model.model_fields["statement_kind"].annotation) == (statement_kind,)
    )


def _expected_options(
    fact_kind: str, statement_kind: str | None = None
) -> dict[str, tuple[str, ...]]:
    """Every combo dimension's vocabulary: literals verbatim, booleans as the two-value choice.

    Scope dimensions are excluded and checked through ``_expected_scope_options`` instead: a scope
    is a multi-selection over its vocabulary plus an explicit unrestricted entry, not a combo, and
    conflating the two would let a scope regress into a single-value widget unnoticed. A pair
    collection is excluded for the same reason and checked through ``_expected_pair_options``: it is
    offered as repeating source-and-target rows, and a single combo could only hold one member of one
    pair.
    """

    options: dict[str, tuple[str, ...]] = {}
    for name, field in _variant_model(fact_kind, statement_kind).model_fields.items():
        if name in _UNDIMENSIONED:
            continue
        if scope_vocabulary(field.annotation) is not None:
            continue
        if pair_vocabulary(field.annotation) is not None:
            continue
        if field.annotation is bool:
            options[name] = ("true", "false")
        elif any(isinstance(item, RouteReference) for item in field.metadata):
            # A dimension deferring to another rule is a combo like any other, over the ids the
            # recipe declares rather than a vocabulary the model carries -- so the expectation comes
            # from the recipe here, exactly as the dialog builds it.
            options[name] = declared_rule_references()
        elif get_args(field.annotation):
            options[name] = get_args(field.annotation)
    return options


def _expected_scope_options(
    fact_kind: str, statement_kind: str | None = None
) -> dict[str, tuple[str, ...]]:
    """Every scope dimension's vocabulary, read from the model that declares it."""

    return {
        name: scoped
        for name, field in _variant_model(fact_kind, statement_kind).model_fields.items()
        if (scoped := scope_vocabulary(field.annotation))
    }


def _expected_pair_options(
    fact_kind: str, statement_kind: str | None = None
) -> dict[str, tuple[str, ...]]:
    """Every pair-collection dimension's vocabulary, read from the model that declares it."""

    return {
        name: paired
        for name, field in _variant_model(fact_kind, statement_kind).model_fields.items()
        if (paired := pair_vocabulary(field.annotation))
    }


def _fragment_over_segments(
    semantic_id: str, segments: tuple[ClauseSegmentSpec, ...]
) -> RawClauseFragment:
    """A synthetic fragment declaring the given page regions, for the source preview.

    Invented node text under the real fragment id, exactly as the shared fixture does. Only the
    declared segments matter here: they are what the pane crops the page to.
    """

    nodes = (
        ClauseNode(
            order=0,
            kind="paragraph",
            raw_text="synthetic neutral node for the source preview",
            source=SOURCE.model_copy(update={"row": "node 0"}),
        ),
    )
    fragment = RawClauseFragment(
        id=f"raw-{semantic_id}",
        raw_sha256="0" * 64,
        nodes=nodes,
        tokens=(),
        segments=segments,
        source=SOURCE.model_copy(update={"standard": "SYNTHETIC"}),
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def _route_position(model: ClauseFactReviewModel, rule_route: str) -> int:
    return next(
        position for position, row in enumerate(model.routes()) if row.rule_route == rule_route
    )


def _fill_hf_dimensions(dialog: ClauseFactReviewDialog) -> None:
    """Choose every dimension of the attenuation family's demonstration requirement.

    The requirement rather than the permission because it is the richer of the two -- a scope, a
    boolean and a route reference -- so it is the one the surfaces are exercised through. Choosing
    the kind first is part of filling the editor now: a variant family offers no dimension until a
    reviewer says which kind of reading this is.
    """

    dialog.choose_statement_kind("requirement")
    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.choose_scope("evidence_kind", "test")
    dialog.dimension_combo("threshold_reference").setCurrentText(
        ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC
    )
    dialog.dimension_combo("comparison_required").setCurrentText("true")


def _fill_hf_permission(dialog: ClauseFactReviewDialog) -> None:
    """Choose every dimension of the attenuation family's permission: the gate, and nothing else."""

    dialog.choose_statement_kind("permission")
    dialog.dimension_combo("obligation").setCurrentText("permission")
    dialog.choose_scope("dvc_gate", "dvc_as")


def _selected_scope(dialog: ClauseFactReviewDialog, field: str) -> list[str]:
    return [item.text() for item in dialog.dimension_scope(field).selectedItems()]


def _author_hf_through_dialog(model: ClauseFactReviewModel, dialog: ClauseFactReviewDialog) -> int:
    """Select the HF route, read its first node, fill every dimension, and author."""

    position = _route_position(model, HF_ROUTE)
    dialog.table.selectRow(position)
    dialog.nodes_list.item(0).setSelected(True)
    _fill_hf_dimensions(dialog)
    dialog.author_selected()
    return position


@pytest.fixture
def hf_fact(draft_with_supply_fragments) -> HfAttenuationRequirementFact:
    return _hf_fact(draft_with_supply_fragments, statement_index=0)


class _DriftedFact(HfAttenuationPermissionFact):
    """A fact family one of whose dimensions is no longer expressible by any editor widget."""

    dvc_gate: Literal[1, 2]  # type: ignore[assignment]


def test_a_dimension_without_a_string_vocabulary_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silent degradation here is an unauthorable route and an approval blocked with no message."""

    monkeypatch.setitem(
        clause_fact_proposals.FACT_MODELS_BY_KIND, "hf_attenuation", (_DriftedFact,)
    )

    with pytest.raises(RulePackageError, match="dvc_gate"):
        clause_fact_proposals.fact_dimensions("hf_attenuation")


def test_the_model_lists_each_route_with_its_completion_state(draft_with_supply_fragments) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)

    routes = model.routes()

    assert routes
    # Every declared route including the evidence-only one; never the legacy route, whose
    # branch authority stays in the recipe.
    assert {route.rule_route for route in routes} == (
        set(SUPPLY_FACT_FAMILY_BY_ROUTE) - LEGACY_BRANCH_AUTHORITY_RULE_IDS
    )
    assert all(route.status == "needs_facts" for route in routes)


def test_the_model_exposes_the_nodes_a_reviewer_must_read(draft_with_supply_fragments) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    route = model.routes()[0]

    nodes = model.nodes(route.fragment_id)

    assert nodes
    assert all(node.node_sha256 for node in nodes)


def test_authoring_then_completing_moves_a_route_to_complete(
    draft_with_supply_fragments, hf_fact
) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    route_id = "iec62477_2022.supply.hf_transformer_attenuation"

    model.author(route_id, hf_fact, actor="tester", notes="authored")
    model.complete(
        route_id,
        f"raw-{route_id}",
        actor="tester",
        notes="complete",
    )

    status = next(route.status for route in model.routes() if route.rule_route == route_id)
    assert status == "complete"


def test_a_later_authoring_makes_a_completed_route_stale(
    draft_with_supply_fragments, hf_fact
) -> None:
    """The completion binds the fact-set digest, so this surface must agree with the gate."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    model.author(HF_ROUTE, hf_fact, actor="tester", notes="authored")
    model.complete(HF_ROUTE, f"raw-{HF_ROUTE}", actor="tester", notes="complete")

    # Another index *and* another reading: a statement repeating a reading is refused as a
    # duplicate, so bumping the index alone would test that refusal instead of staleness.
    model.author(
        HF_ROUTE,
        _hf_fact(draft_with_supply_fragments, statement_index=1, evidence_kind="simulation"),
        actor="tester",
        notes="one more",
    )

    status = next(route.status for route in model.routes() if route.rule_route == HF_ROUTE)
    assert status == "stale"


def test_a_statement_whose_cited_evidence_moved_reads_as_stale(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Read through the importer's own live digest, so a fact row agrees with the gate."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    model.author(HF_ROUTE, hf_fact, actor="tester", notes="authored")
    draft = model.draft
    changed = draft.model_copy(
        update={
            "raw_clause_fragments": tuple(
                fragment.model_copy(
                    update={
                        "nodes": tuple(
                            node.model_copy(update={"raw_text": "synthetic corrected node text"})
                            if node.order == 0
                            else node
                            for node in fragment.nodes
                        )
                    }
                )
                if fragment.id == f"raw-{HF_ROUTE}"
                else fragment
                for fragment in draft.raw_clause_fragments
            )
        }
    )

    facts = ClauseFactReviewModel(changed).facts(HF_ROUTE)

    assert [row.evidence for row in facts] == ["stale"]


def _completed_hf_draft(draft_with_supply_fragments, hf_fact):
    """One authored statement on the HF route, completed. The starting point for every path below."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    model.author(HF_ROUTE, hf_fact, actor="tester", notes="authored")
    model.complete(HF_ROUTE, f"raw-{HF_ROUTE}", actor="tester", notes="complete")
    return model.draft


def _cited_node(draft, rule_route: str) -> CitedNode:
    """A citation of one real node of that route's own fragment."""

    fragment = next(item for item in draft.raw_clause_fragments if item.id == f"raw-{rule_route}")
    node = fragment.nodes[0]
    return CitedNode(
        fragment_id=fragment.id,
        node_order=node.order,
        node_sha256=canonical_model_sha256(node),
    )


def _blocked_routes(draft) -> set[str]:
    from insulation_coordination.rules.importer.approval import approval_blockers

    return {
        item.semantic_id
        for item in approval_blockers(draft)
        if item.code == "CLAUSE_FACT_REVIEW_REQUIRED"
    }


def _route_status(draft, rule_route: str) -> str:
    return next(
        route.status
        for route in ClauseFactReviewModel(draft).routes()
        if route.rule_route == rule_route
    )


def test_this_surface_and_the_gate_never_disagree_about_a_route(
    draft_with_supply_fragments, hf_fact
) -> None:
    """The invariant the whole predicate exists for, asserted over every route of a real draft.

    A route this table calls complete must be one the gate does not block, and the converse. The
    dialog re-deriving a subset of the gate's comparison is how the two drifted before: the table
    read green while approval refused, and the reviewer's only clue was a per-statement row that
    contradicted the route above it.
    """

    draft = _completed_hf_draft(draft_with_supply_fragments, hf_fact)
    blocked = _blocked_routes(draft)

    for route in ClauseFactReviewModel(draft).routes():
        assert (route.status == "complete") is (route.rule_route not in blocked), route.rule_route


def test_a_fact_hash_that_is_not_its_fact_reads_as_stale(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Survives a draft-package round trip, so a loaded draft can carry it."""

    draft = _completed_hf_draft(draft_with_supply_fragments, hf_fact)
    tampered = draft.model_copy(
        update={
            "clause_fact_reviews": tuple(
                item.model_copy(update={"fact_sha256": "0" * 64})
                if item.rule_route == HF_ROUTE
                else item
                for item in draft.clause_fact_reviews
            )
        }
    )

    assert _route_status(tampered, HF_ROUTE) == "stale"
    assert HF_ROUTE in _blocked_routes(tampered)


def test_two_completion_records_for_one_route_read_as_stale(
    draft_with_supply_fragments, hf_fact
) -> None:
    """``record_fact_completion`` replaces, so only a loaded or hand-built draft carries two."""

    draft = _completed_hf_draft(draft_with_supply_fragments, hf_fact)
    completion = next(item for item in draft.clause_fact_completions if item.rule_route == HF_ROUTE)
    doubled = draft.model_copy(
        update={"clause_fact_completions": (*draft.clause_fact_completions, completion)}
    )

    assert _route_status(doubled, HF_ROUTE) == "stale"
    assert HF_ROUTE in _blocked_routes(doubled)


def test_a_completion_bound_to_a_foreign_fragment_reads_as_stale(
    draft_with_supply_fragments, hf_fact
) -> None:
    """The fragment digest can match while the fragment identity does not."""

    draft = _completed_hf_draft(draft_with_supply_fragments, hf_fact)
    foreign = draft.model_copy(
        update={
            "clause_fact_completions": tuple(
                item.model_copy(
                    update={"fragment_id": f"raw-{ids.SUPPLY_VERIFIED_BARRIER_TRANSFER}"}
                )
                if item.rule_route == HF_ROUTE
                else item
                for item in draft.clause_fact_completions
            )
        }
    )

    assert _route_status(foreign, HF_ROUTE) == "stale"
    assert HF_ROUTE in _blocked_routes(foreign)


def test_a_second_clause_moving_makes_its_citer_stale_without_tampering(
    draft_with_supply_fragments, hf_fact
) -> None:
    """The path that needs no hand-edited digest at all, which is what made the old bug reachable.

    A fact may cite a node of another route's fragment as well as its own. When only that other
    clause is re-extracted, this route's own fragment digest and its fact set are both untouched,
    so every check the dialog used to make on its own passed while the gate refused.
    """

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    own = _cited_node(draft_with_supply_fragments, HF_ROUTE)
    other = _cited_node(draft_with_supply_fragments, ids.SUPPLY_VERIFIED_BARRIER_TRANSFER)
    model.author(
        HF_ROUTE,
        hf_fact.model_copy(update={"node_references": (own, other)}),
        actor="tester",
        notes="rests on two clauses",
    )
    model.complete(HF_ROUTE, f"raw-{HF_ROUTE}", actor="tester", notes="complete")
    draft = model.draft
    assert _route_status(draft, HF_ROUTE) == "complete"

    moved = draft.model_copy(
        update={
            "raw_clause_fragments": tuple(
                fragment.model_copy(
                    update={
                        "nodes": tuple(
                            node.model_copy(update={"raw_text": "synthetic other clause reflowed"})
                            if node.order == 0
                            else node
                            for node in fragment.nodes
                        )
                    }
                )
                if fragment.id == f"raw-{ids.SUPPLY_VERIFIED_BARRIER_TRANSFER}"
                else fragment
                for fragment in draft.raw_clause_fragments
            )
        }
    )

    assert _route_status(moved, HF_ROUTE) == "stale"
    assert HF_ROUTE in _blocked_routes(moved)


def test_replace_and_retract_round_trip(draft_with_supply_fragments, hf_fact) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    model.author(HF_ROUTE, hf_fact, actor="tester", notes="first")

    replaced = hf_fact.model_copy(update={"comparison_required": False})
    model.author(HF_ROUTE, replaced, actor="tester", notes="replaced")

    facts = model.facts(HF_ROUTE)
    assert len(facts) == 1
    assert facts[0].fact == replaced

    model.retract(HF_ROUTE, hf_fact.statement_index, actor="tester", notes="retracted")

    assert model.facts(HF_ROUTE) == ()
    status = next(route.status for route in model.routes() if route.rule_route == HF_ROUTE)
    assert status == "needs_facts"


def test_the_dialog_shows_one_row_per_route(qtbot, draft_with_supply_fragments) -> None:
    dialog = ClauseFactReviewDialog(ClauseFactReviewModel(draft_with_supply_fragments))
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == len(
        ClauseFactReviewModel(draft_with_supply_fragments).routes()
    )
    assert dialog.table.columnCount() == 4


def test_authoring_through_the_dialog_records_a_review(qtbot, draft_with_supply_fragments) -> None:
    """Without this the dialog is read-only and the gate can only be cleared from test code."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    position = _author_hf_through_dialog(model, dialog)

    assert dialog.table.item(position, _STATUS_COLUMN).text() == "needs_completion"
    assert len(model.draft.clause_fact_reviews) == 1
    assert model.draft.clause_fact_reviews[0].actor == "maintainer"


def test_the_node_reader_supplies_real_citations(qtbot, draft_with_supply_fragments) -> None:
    """A fact authored through the dialog cites a live node of the route's own fragment."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    _author_hf_through_dialog(model, dialog)

    fragment = next(
        item for item in model.draft.raw_clause_fragments if item.id == f"raw-{HF_ROUTE}"
    )
    (citation,) = model.draft.clause_fact_reviews[0].fact.node_references
    assert citation.fragment_id == fragment.id
    assert citation.node_order == fragment.nodes[0].order
    assert citation.node_sha256 == canonical_model_sha256(fragment.nodes[0])


def test_completing_through_the_dialog_moves_the_route_to_complete(
    qtbot, draft_with_supply_fragments
) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    position = _author_hf_through_dialog(model, dialog)

    dialog.complete_selected()

    assert dialog.table.item(position, _STATUS_COLUMN).text() == "complete"
    assert len(model.draft.clause_fact_completions) == 1
    assert model.draft.clause_fact_completions[0].actor == "maintainer"


def test_selecting_a_statement_prefills_the_editor_for_replacement(
    qtbot, draft_with_supply_fragments
) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _author_hf_through_dialog(model, dialog)

    dialog.facts_list.setCurrentRow(0)

    assert dialog.statement_index.value() == 0
    assert _selected_scope(dialog, "evidence_kind") == ["test"]
    assert dialog.dimension_combo("comparison_required").currentText() == "true"
    assert [item.text() for item in dialog.nodes_list.selectedItems()]

    dialog.dimension_combo("comparison_required").setCurrentText("false")
    dialog.author_selected()

    assert len(model.draft.clause_fact_reviews) == 1
    assert model.draft.clause_fact_reviews[0].fact.comparison_required is False


def test_retracting_the_selected_statement_through_the_dialog(
    qtbot, draft_with_supply_fragments
) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    position = _author_hf_through_dialog(model, dialog)

    dialog.facts_list.setCurrentRow(0)
    assert dialog.retract_button.isEnabled() is True
    dialog.retract_selected()

    assert not model.draft.clause_fact_reviews
    assert dialog.table.item(position, _STATUS_COLUMN).text() == "needs_facts"
    assert dialog.retract_button.isEnabled() is False


def test_authoring_stays_disabled_while_any_dimension_is_unchosen(
    qtbot, draft_with_supply_fragments
) -> None:
    """Every dimension starts unchosen: a reviewer must never record a reading they did not pick."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    assert dialog.author_button.isEnabled() is False
    dialog.nodes_list.item(0).setSelected(True)
    assert dialog.author_button.isEnabled() is False
    # The kind first: a variant family offers no dimension until the reviewer picks one.
    assert dialog.author_button.isEnabled() is False
    dialog.choose_statement_kind("requirement")
    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.choose_scope("evidence_kind", "test")
    dialog.dimension_combo("threshold_reference").setCurrentText(
        ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC
    )
    assert dialog.author_button.isEnabled() is False
    dialog.dimension_combo("comparison_required").setCurrentText("true")
    assert dialog.author_button.isEnabled() is True


def test_authoring_stays_disabled_while_no_node_is_selected(
    qtbot, draft_with_supply_fragments
) -> None:
    """A statement rests on cited nodes; without a citation the evidence digest binds nothing."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    dialog.choose_statement_kind("requirement")
    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.choose_scope("evidence_kind", "test")
    dialog.dimension_combo("threshold_reference").setCurrentText(
        ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC
    )
    dialog.dimension_combo("comparison_required").setCurrentText("true")

    assert dialog.author_button.isEnabled() is False
    dialog.nodes_list.item(0).setSelected(True)
    assert dialog.author_button.isEnabled() is True


def test_each_combo_offers_exactly_its_fields_vocabulary(
    qtbot, draft_with_supply_fragments
) -> None:
    """The editor is built from the fact models, so a wrong-family editor cannot be offered.

    Every statement kind of every family, because a variant family has no single model whose
    fields the editor could offer: switching the kind is a different form, and offering one kind's
    dimensions for the other would ask the reviewer for a reading that kind does not make.
    """

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    offered = []
    for position, row in enumerate(model.routes()):
        dialog.table.selectRow(position)
        family = SUPPLY_FACT_FAMILY_BY_ROUTE[row.rule_route]
        assert dialog.family_text == family
        variants = fact_variants(family)
        if not variants:
            offered.append(
                (family, None, dialog.dimension_options, dialog.scope_options, dialog.pair_options)
            )
            continue
        # A variant family offers no dimension at all until a kind is chosen.
        assert dialog.dimension_options == {} and dialog.scope_options == {}
        assert dialog.pair_options == {}
        for variant in variants:
            dialog.choose_statement_kind(variant)
            offered.append(
                (
                    family,
                    variant,
                    dialog.dimension_options,
                    dialog.scope_options,
                    dialog.pair_options,
                )
            )

    # Every non-legacy family is reachable with every kind of statement it declares;
    # propagation_step belongs only to the legacy route.
    assert {(family, variant) for family, variant, _options, _scopes, _pairs in offered} == {
        (family, variant)
        for family, models in _FACT_MODELS.items()
        for variant in _declared_variants(models)
    }
    assert all(
        options == _expected_options(family, variant)
        for family, variant, options, _scopes, _pairs in offered
    )
    assert all(
        scopes == _expected_scope_options(family, variant)
        for family, variant, _options, scopes, _pairs in offered
    )
    assert all(
        pairs == _expected_pair_options(family, variant)
        for family, variant, _options, _scopes, pairs in offered
    )
    # The scope and the pair widgets are reached at all, so the assertions above are not
    # vacuously true.
    assert any(scopes for _family, _variant, _options, scopes, _pairs in offered)
    assert any(pairs for _family, _variant, _options, _scopes, pairs in offered)


def test_a_variant_family_authors_the_kind_the_reviewer_chose(
    qtbot, draft_with_supply_fragments
) -> None:
    """Both kinds are authorable, and neither is offered until the reviewer picks one.

    A surface that could only author one of a family's kinds would leave the other reviewable
    nowhere -- the unauthorable route ``fact_dimensions`` refuses to create in the first place --
    and one that defaulted to a kind would record which question the statement answers on the
    reviewer's behalf.
    """

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, SV_ROUTE))
    dialog.nodes_list.item(0).setSelected(True)

    combo = dialog.statement_kind_combo
    assert combo is not None
    assert combo.currentText() == ""
    assert dialog.author_button.isEnabled() is False

    dialog.choose_statement_kind("applicability")
    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.choose_scope("input_topology", "isolated_secondary")
    dialog.choose_scope("purpose", "impulse")
    dialog.dimension_combo("counts_as_system_voltage").setCurrentText("true")
    assert dialog.author_button.isEnabled() is True
    dialog.author_selected()

    (review,) = model.draft.clause_fact_reviews
    assert review.fact.statement_kind == "applicability"
    assert review.fact.fact_kind == "system_voltage"
    # The row leads with the kind, so two kinds of one family do not read as unrelated statements.
    assert dialog.facts_list.item(0).text().startswith("statement 0 · applicability")

    # And the other kind, whose editor is a different set of dimensions.
    dialog.nodes_list.item(0).setSelected(True)
    dialog.choose_statement_kind("measure")
    assert "measure" in dialog.dimension_options
    assert "counts_as_system_voltage" not in dialog.dimension_options


def test_a_route_reference_is_offered_as_a_choice_over_the_declared_ids(
    qtbot, draft_with_supply_fragments
) -> None:
    """A blank line edit for a rule identifier is a field nobody can fill from the screen.

    The maintainer authoring the reduction clause's monitoring statement had no way to know what
    ``monitoring_reference`` wanted: the value is a route id discoverable only by reading the recipe
    source, and a grammar constant cannot reach it because the grammar proposes one statement kind
    and this dimension lives on a variant it does not propose. Offered as a choice, the reviewer picks
    rather than recalls and a typo is not expressible.

    Every declared id rather than a per-field shortlist, because narrowing means encoding which rules
    may reference which and no reviewed reading states that.
    """

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, MAINS_ROUTE))
    dialog.choose_statement_kind("monitoring")

    kinds = {
        name: kind
        for name, kind, _options in clause_fact_proposals.fact_dimensions(
            "spd_reduction", "monitoring"
        )
    }

    assert kinds["monitoring_reference"] == "route_reference"
    # A choice, not a line edit -- and over ids that actually exist.
    assert "monitoring_reference" not in dialog.pair_options
    with pytest.raises(KeyError):
        dialog.dimension_edit("monitoring_reference")
    offered = dialog.dimension_options["monitoring_reference"]
    assert offered == declared_rule_references()
    assert MAINS_ROUTE in offered
    assert f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring" in offered
    # The family id a barrier rating statement defers to is offered too: that field names a route
    # *family*, so narrowing the choice to leaf routes would put its correct value out of reach.
    assert ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS in offered


def test_a_statement_deferring_to_an_undeclared_rule_is_refused(
    qtbot, draft_with_supply_fragments
) -> None:
    """Nothing consumes these references yet, so a typo would have surfaced years later.

    Refused where the other identity defects are refused -- the wrong family, the foreign citation,
    the contradicting supply kind -- so both ``author_clause_fact`` and the approval gate reject it
    and a hand-built draft cannot slip one past either.
    """

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, MAINS_ROUTE))
    dialog.nodes_list.item(0).setSelected(True)
    dialog.choose_statement_kind("monitoring")
    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.dimension_combo("device_degradable").setCurrentText("true")
    dialog.dimension_combo("monitoring_obligation").setCurrentText("required")
    dialog.dimension_combo("status_indication").setCurrentText("required")
    # A well-formed identifier that names no declared rule: exactly what a typo produces.
    combo = dialog.dimension_combo("monitoring_reference")
    combo.setEditable(True)
    combo.setCurrentText("iec62477_2022.supply.spd_reduction_requirements.monitorng")

    dialog.author_selected()

    assert "refused" in dialog.status_text
    assert "monitorng" in dialog.status_text
    assert "names no rule this recipe declares" in dialog.status_text
    assert model.draft.clause_fact_reviews == ()

    # The declared id authors, through the same press.
    combo.setCurrentText(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring")
    dialog.author_selected()

    (review,) = model.draft.clause_fact_reviews
    assert review.fact.monitoring_reference == f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"


def test_a_scope_dimension_offers_its_values_and_an_explicit_unrestricted_entry(
    qtbot, draft_with_supply_fragments
) -> None:
    """Selecting every value must stay a different action from selecting unrestricted.

    They project differently wherever the reviewed and consumer domains coincide, so a widget that
    only offered the values would leave the unrestricted reading unauthorable, and one that treated
    "all selected" as unrestricted would record a reading the reviewer did not state.
    """

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    dialog.nodes_list.item(0).setSelected(True)
    _fill_hf_permission(dialog)

    widget = dialog.dimension_scope("dvc_gate")
    assert [widget.item(row).text() for row in range(widget.count())] == [
        "(unrestricted)",
        "dvc_as",
        "dvc_b",
    ]

    dialog.choose_scope("dvc_gate", "dvc_as", "dvc_b")
    dialog.author_selected()

    # Authoring reloads the route, which puts every dimension back to unchosen.
    dialog.nodes_list.item(0).setSelected(True)
    _fill_hf_permission(dialog)
    dialog.choose_scope("dvc_gate", unrestricted=True)
    dialog.author_selected()

    every_value, unrestricted = (item.fact.dvc_gate for item in model.draft.clause_fact_reviews)
    assert (every_value.mode, every_value.values) == ("exact_set", ("dvc_as", "dvc_b"))
    assert (unrestricted.mode, unrestricted.values) == ("unrestricted", ())


def test_one_statement_naming_both_designations_is_authored_once(
    qtbot, draft_with_supply_fragments
) -> None:
    """The reviewer's side of the duplicate-expansion fix: one reading, one Author, one statement."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    dialog.nodes_list.item(0).setSelected(True)
    _fill_hf_permission(dialog)
    dialog.choose_scope("dvc_gate", "dvc_b", "dvc_as")

    dialog.author_selected()

    (review,) = model.draft.clause_fact_reviews
    assert review.fact.dvc_gate == DimensionScope.of("dvc_as", "dvc_b")
    # The reading a reviewer reads back off the row, not a model repr.
    assert "dvc_as|dvc_b" in dialog.facts_list.item(0).text()


# --- pair-collection dimensions: one row per stated pair ------------------------------

#: Two transitions of the declared overvoltage scale, in that scale's own order. Neutral typed
#: vocabulary chosen for these tests: they say nothing about what any clause permits, only that a
#: statement naming two transitions is one statement carrying two rows.
_STATED_STEPS = (("ovc_ii", "ovc_i"), ("ovc_iii", "ovc_ii"))
_PAIR_FIELD = "permitted_steps"


def _select_reduction_route(model: ClauseFactReviewModel, dialog: ClauseFactReviewDialog) -> None:
    """Select the reduction route and cite its first node, ready for either statement kind."""

    dialog.table.selectRow(_route_position(model, MAINS_ROUTE))
    dialog.nodes_list.item(0).setSelected(True)


def _fill_permission_dimensions(dialog: ClauseFactReviewDialog, *pairs: tuple[str, str]) -> None:
    """Choose every dimension of the reduction permission variant, stating the given pairs.

    ``supply_kind`` is not chosen here: the route determines it, so the editor prefills and locks it.
    """

    dialog.choose_statement_kind("permission")
    dialog.dimension_combo("obligation").setCurrentText("permission")
    dialog.choose_scope("insulation_classes", "basic")
    dialog.choose_pairs(_PAIR_FIELD, *pairs)


def _stated_pairs(fact: SpdReductionPermissionFact) -> list[tuple[str, str]]:
    """One authored collection read back as pairs, in the order the statement carries them."""

    return [(step.source_ovc, step.target_ovc) for step in fact.permitted_steps]


def test_a_pair_dimension_offers_one_row_per_stated_pair(
    qtbot, draft_with_supply_fragments
) -> None:
    """Two stated transitions are two rows and one statement -- never four crossings of them.

    Two independent multi-selections over the same vocabulary would fabricate a cartesian product of
    the endpoints, which is the defect the pair member model exists to refuse. Each row is one stated
    pair, and the collection keeps the reviewer's order.
    """

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _select_reduction_route(model, dialog)

    _fill_permission_dimensions(dialog, *_STATED_STEPS)

    editor = dialog.dimension_pairs(_PAIR_FIELD)
    # Both members of every row draw from the one vocabulary the model declares; it is not a scope
    # and not a combo, either of which could hold only one member of one pair.
    assert dialog.pair_options == _expected_pair_options("spd_reduction", "permission")
    assert _PAIR_FIELD not in dialog.scope_options
    assert _PAIR_FIELD not in dialog.dimension_options
    assert editor.pairs() == _STATED_STEPS

    dialog.author_selected()

    (review,) = model.draft.clause_fact_reviews
    assert _stated_pairs(review.fact) == list(_STATED_STEPS)
    # One statement with two transitions, not two statements and not four fabricated ones.
    assert len(model.facts(MAINS_ROUTE)) == 1
    assert pair_wire(_STATED_STEPS) in dialog.facts_list.item(0).text()


def test_an_empty_or_half_stated_pair_collection_is_not_a_choice(
    qtbot, draft_with_supply_fragments
) -> None:
    """A dimension starts unchosen, and half a pair is no more a reading than no pair is."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _select_reduction_route(model, dialog)
    _fill_permission_dimensions(dialog)

    editor = dialog.dimension_pairs(_PAIR_FIELD)
    # No row at all: the collection is unchosen, exactly as an empty scope selection is.
    assert editor.pairs() == ()
    assert dialog.author_button.isEnabled() is False

    editor.add_pair()
    assert editor.pairs() == (("", ""),)
    assert dialog.author_button.isEnabled() is False

    dialog.choose_pairs(_PAIR_FIELD, ("ovc_iii", ""))
    assert dialog.author_button.isEnabled() is False

    dialog.choose_pairs(_PAIR_FIELD, ("ovc_iii", "ovc_ii"))
    assert dialog.author_button.isEnabled() is True

    # Removing the only row puts the dimension back to unchosen rather than leaving a stale reading.
    editor.remove_pair(0)
    assert editor.pairs() == ()
    assert dialog.author_button.isEnabled() is False


def test_a_collection_the_model_would_refuse_says_so_beside_the_rows(
    qtbot, draft_with_supply_fragments
) -> None:
    """The reviewer must not build a refused collection blind, and the rows must not be reordered.

    The model rejects an out-of-order or duplicated collection rather than sorting it, so that a
    duplicate the reviewer meant to notice stays visible. The editor therefore quotes that refusal
    where the rows are instead of quietly rearranging them -- and the refusal itself stays the
    model's, asked of the fact model rather than restated here.
    """

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _select_reduction_route(model, dialog)
    _fill_permission_dimensions(dialog, *reversed(_STATED_STEPS))
    editor = dialog.dimension_pairs(_PAIR_FIELD)

    # The rows stay in the order the reviewer arranged them; only the refusal is added.
    assert editor.pairs() == tuple(reversed(_STATED_STEPS))
    assert "declared vocabulary order" in editor.refusal_text

    dialog.author_selected()

    assert "refused" in dialog.status_text
    assert not model.draft.clause_fact_reviews

    dialog.choose_pairs(_PAIR_FIELD, _STATED_STEPS[0], _STATED_STEPS[0])
    assert "names each transition once" in editor.refusal_text

    dialog.choose_pairs(_PAIR_FIELD, ("ovc_ii", "ovc_ii"))
    assert "different category" in editor.refusal_text

    dialog.choose_pairs(_PAIR_FIELD, *_STATED_STEPS)
    assert editor.refusal_text == ""

    dialog.author_selected()

    (review,) = model.draft.clause_fact_reviews
    assert _stated_pairs(review.fact) == list(_STATED_STEPS)


def test_a_stated_collection_does_not_survive_a_switch_of_statement_kind(
    qtbot, draft_with_supply_fragments
) -> None:
    """A kind that states no such dimension must not carry the rows of the kind that does.

    Choosing a statement kind rebuilds the dimension rows, so the collection has to go with them:
    a surviving one would either be authored onto a variant that declares no such field, or reappear
    as a prefilled reading when the reviewer came back to the kind that does.
    """

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _select_reduction_route(model, dialog)
    _fill_permission_dimensions(dialog, *_STATED_STEPS)

    dialog.choose_statement_kind("floor")

    assert dialog.pair_options == {}
    with pytest.raises(KeyError):
        dialog.dimension_pairs(_PAIR_FIELD)

    # The floor variant is authorable, which a surviving collection would break: the fact models
    # forbid undeclared fields.
    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.dimension_combo("unreduced_basis").setCurrentText(
        "basic_insulation_without_the_reducing_means"
    )
    dialog.dimension_combo("relation").setCurrentText("must_not_fall_below")
    dialog.choose_scope("insulation_classes", "basic")
    dialog.author_selected()

    (review,) = model.draft.clause_fact_reviews
    assert review.fact.statement_kind == "floor"
    assert not hasattr(review.fact, _PAIR_FIELD)

    # And back to the kind that does state one: unchosen again, so Author stays disabled until the
    # reviewer states the collection afresh.
    _select_reduction_route(model, dialog)
    _fill_permission_dimensions(dialog)

    assert dialog.dimension_pairs(_PAIR_FIELD).pairs() == ()
    assert dialog.author_button.isEnabled() is False


def test_a_stated_collection_is_loaded_back_into_the_rows_for_a_sibling_statement(
    qtbot, draft_with_supply_fragments
) -> None:
    """Duplicate is the cheapest path to a sibling statement, collections included."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _select_reduction_route(model, dialog)
    _fill_permission_dimensions(dialog, *_STATED_STEPS)
    dialog.author_selected()

    dialog.facts_list.setCurrentRow(0)
    dialog.duplicate_selected()

    assert dialog.dimension_pairs(_PAIR_FIELD).pairs() == _STATED_STEPS
    assert dialog.statement_index.value() == 1

    dialog.choose_pairs(_PAIR_FIELD, _STATED_STEPS[0])
    dialog.author_selected()

    facts = model.facts(MAINS_ROUTE)
    assert [_stated_pairs(row.fact) for row in facts] == [
        list(_STATED_STEPS),
        [_STATED_STEPS[0]],
    ]


class _ModelWithOneProposal(ClauseFactReviewModel):
    """The review model with one synthetic draft for the reduction route and none elsewhere.

    A grammar mapping source phrasing to a pair collection is licensed-derived and loads only from
    beside the licensed material, so a public checkout proposes nothing for this route at all. What
    this stands in for is only the prefill: a draft whose wire value names two stated pairs.
    """

    def __init__(self, draft: ImportedRuleDraft, proposal: ClauseFactProposal) -> None:
        super().__init__(draft)
        self._proposal = proposal

    def proposals(self, rule_route: str) -> tuple[ClauseFactProposal, ...]:
        return (self._proposal,) if rule_route == self._proposal.rule_route else ()


def test_a_draft_prefills_the_rows_from_the_collection_it_proposes(
    qtbot, draft_with_supply_fragments
) -> None:
    """A suggested collection reaches the rows through the same wire form, in the proposed order."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    node = model.nodes(f"raw-{MAINS_ROUTE}")[0]
    proposal = ClauseFactProposal(
        rule_route=MAINS_ROUTE,
        fact_kind="spd_reduction",
        statement_kind="permission",
        sentence_index=0,
        sentence_text="Synthetic sentence standing in for one stating two transitions.",
        node_references=(
            CitedNode(
                fragment_id=node.fragment_id,
                node_order=node.node_order,
                node_sha256=node.node_sha256,
            ),
        ),
        chosen={_PAIR_FIELD: pair_wire(_STATED_STEPS)},
        unchosen=("obligation", "supply_kind", "insulation_classes"),
    )
    proposing = _ModelWithOneProposal(draft_with_supply_fragments, proposal)
    dialog = ClauseFactReviewDialog(proposing)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(proposing, MAINS_ROUTE))

    dialog.facts_list.setCurrentRow(0)
    dialog.use_suggested_button.click()

    assert dialog.dimension_pairs(_PAIR_FIELD).pairs() == _STATED_STEPS
    # A prefill and nothing else: the dimensions the draft did not settle stay unchosen.
    assert dialog.author_button.isEnabled() is False
    assert not proposing.draft.clause_fact_reviews


#: One invented sentence carrying every marker the synthetic reduction grammar names, with its two
#: transitions stated in the order the declared scale does *not* put them in. The markers are coined
#: in ``synthetic_private_grammars`` and mean nothing outside these tests; the real declarations live
#: beside the licensed material (amendment A1) and are spelled nowhere here.
_PROPOSED_COLLECTION_SENTENCE = (
    "Synthetic reading: synthallow synthclassone synthreduce synthovcfour to synthovcthree, "
    "then synthovcthree to synthovctwo."
)


@pytest.fixture
def draft_with_a_proposed_collection(synthetic_private_grammars: Path) -> ImportedRuleDraft:
    """Every supply fragment, with the mains reduction route's node carrying the sentence above."""

    fragments = tuple(
        fragment_with_sentences(spec.semantic_id, (_PROPOSED_COLLECTION_SENTENCE,))
        if spec.semantic_id == MAINS_ROUTE
        else _fragment(spec.semantic_id)
        for spec in SUPPLY_CLAUSES
    )
    return _logged(_draft(fragments=fragments))


def test_a_route_whose_draft_states_a_collection_still_shows_its_statements(
    qtbot, draft_with_a_proposed_collection
) -> None:
    """The defect the maintainer hit on both reduction routes, and its three visible symptoms.

    Selecting the route left the statements pane empty, the suggestion button disabled and the editor
    still describing the route selected *before* it -- because listing the drafts asks whether each is
    already authored, that asks the fact model to build the draft's own statement, and the model
    refuses a step collection that is not in its declared scale order. The refusal escaped into a Qt
    slot, which took the rest of route loading with it.

    So the assertions are the whole of what was broken: the pane lists the draft, the editor is the
    route's own family, and the draft is authorable -- a prefill the model refuses is not a prefill.
    """

    model = ClauseFactReviewModel(draft_with_a_proposed_collection)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    # Another family first, so a stale editor would be visible as staleness rather than emptiness.
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    assert dialog.family_text == "hf_attenuation"

    dialog.table.selectRow(_route_position(model, MAINS_ROUTE))

    (proposal,) = model.open_proposals(MAINS_ROUTE)
    assert proposal.fully_proposed
    assert dialog.facts_list.count() == 1
    assert dialog.family_text == "spd_reduction"
    assert dialog.use_suggested_button.isEnabled() is False

    dialog.facts_list.setCurrentRow(0)

    assert dialog.use_suggested_button.isEnabled() is True

    dialog.use_suggested_button.click()
    dialog.author_selected()

    (review,) = model.draft.clause_fact_reviews
    assert review.fact.statement_kind == "permission"
    # In the declared scale's order, which is the only order the collection can be authored in.
    assert [(step.source_ovc, step.target_ovc) for step in review.fact.permitted_steps] == [
        ("ovc_iii", "ovc_ii"),
        ("ovc_iv", "ovc_iii"),
    ]


class _ModelThatCannotLoad(ClauseFactReviewModel):
    """A review model whose draft listing refuses, standing in for any failure inside it."""

    def open_proposals(self, rule_route: str) -> tuple[ClauseFactProposal, ...]:
        raise ValueError("synthetic refusal from inside route loading")


def test_a_route_that_cannot_be_loaded_says_so_instead_of_failing_in_silence(
    qtbot, draft_with_supply_fragments
) -> None:
    """Route loading is a Qt slot, so a failure in it reached nobody the maintainer could ask.

    Qt prints such an exception to a stream a packaged application has no console for and the slot
    returns, so the only symptom was three panes disagreeing with each other. Whatever refuses in
    there next, it says so here.
    """

    model = _ModelThatCannotLoad(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    assert "could not be loaded" in dialog.status_text
    assert "synthetic refusal from inside route loading" in dialog.status_text


def test_an_importer_refusal_lands_in_the_status_line(qtbot, draft_with_supply_fragments) -> None:
    """Completing a route with no authored facts is the importer's refusal, not the dialog's."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    position = _route_position(model, HF_ROUTE)
    dialog.table.selectRow(position)

    dialog.complete_selected()

    assert "refused" in dialog.status_text
    assert not model.draft.clause_fact_completions
    assert dialog.table.item(position, _STATUS_COLUMN).text() == "needs_facts"


# --- authoring ergonomics -------------------------------------------------------------


def test_supply_kind_is_prefilled_and_locked_to_the_routes_own_reading(
    qtbot, draft_with_supply_fragments
) -> None:
    """The route determines this dimension; the editor shows it rather than asking for it."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    dialog.table.selectRow(_route_position(model, MAINS_ROUTE))
    # A variant family offers no dimension until a kind is chosen, and the route's own dimension is
    # prefilled and locked whichever kind that is: it is structural for every statement it carries.
    for variant in fact_variants(SUPPLY_FACT_FAMILY_BY_ROUTE[MAINS_ROUTE]):
        dialog.choose_statement_kind(variant)

        combo = dialog.dimension_combo("supply_kind")
        assert combo.currentText() == SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE[MAINS_ROUTE], variant
        assert combo.isEnabled() is False, variant


def test_statement_index_default_updates_when_the_route_changes(
    qtbot, draft_with_supply_fragments
) -> None:
    """Typing an index is still possible, but the offered default tracks the selected route."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _author_hf_through_dialog(model, dialog)

    assert dialog.statement_index.value() == 1

    dialog.table.selectRow(_route_position(model, MAINS_ROUTE))
    assert dialog.statement_index.value() == 0

    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    assert dialog.statement_index.value() == 1


def test_duplicate_button_enabled_only_with_a_selected_statement(
    qtbot, draft_with_supply_fragments
) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _author_hf_through_dialog(model, dialog)

    assert dialog.duplicate_button.isEnabled() is False

    dialog.facts_list.setCurrentRow(0)

    assert dialog.duplicate_button.isEnabled() is True


def test_duplicate_loads_the_selected_statement_under_the_next_free_index(
    qtbot, draft_with_supply_fragments
) -> None:
    """The single biggest saving: a sibling statement is one field change plus Author."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _author_hf_through_dialog(model, dialog)

    dialog.facts_list.setCurrentRow(0)
    dialog.duplicate_selected()

    assert dialog.statement_index.value() == 1
    assert _selected_scope(dialog, "evidence_kind") == ["test"]
    assert [item.text() for item in dialog.nodes_list.selectedItems()]

    dialog.choose_scope("evidence_kind", "simulation")
    dialog.author_selected()

    facts = model.facts(HF_ROUTE)
    assert [row.statement_index for row in facts] == [0, 1]
    assert [scope_wire(row.fact.evidence_kind) for row in facts] == ["test", "simulation"]


def test_duplicate_with_nothing_selected_reports_status_rather_than_raising(
    qtbot, draft_with_supply_fragments
) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    dialog.duplicate_selected()

    assert "Select an authored statement" in dialog.status_text


def test_the_node_reader_wraps_full_text_without_eliding(
    qtbot, draft_with_supply_fragments
) -> None:
    """A reviewer must be able to read the full node they are about to cite."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    assert dialog.nodes_list.wordWrap() is True
    assert dialog.nodes_list.textElideMode() == Qt.TextElideMode.ElideNone


# --- proposed drafts, one per clause sentence -----------------------------------------

#: Invented node count for the fragment below, and invented node text carrying no term any
#: declared grammar looks for. Both say nothing about any real clause: what these tests show is
#: that the dialog offers one draft per sentence and leaves every unsettled dimension unchosen.
_SEEDED_NODE_COUNT = 3


@pytest.fixture
def draft_with_a_multi_node_fragment(synthetic_private_grammars: Path) -> ImportedRuleDraft:
    """Every supply fragment, one of them carrying several single-sentence nodes.

    The shared fixture gives each fragment a single node, which cannot show a surface that
    offers a draft per sentence across nodes. Node text stays invented here exactly as it is
    there. Rebuilt rather than copied from that fixture, because the extraction audit record
    every correction verifies is a digest of the fragments themselves.

    A grammar is installed too: with every grammar beside the licensed material, a public checkout
    proposes nothing at all, and a surface test asserting what the drafts look like would pass
    vacuously with no drafts.
    """

    fragments = tuple(
        _fragment(
            spec.semantic_id,
            count=_SEEDED_NODE_COUNT if spec.semantic_id == HF_ROUTE else 1,
        )
        for spec in SUPPLY_CLAUSES
    )
    return _logged(_draft(fragments=fragments))


def test_a_route_offers_one_draft_per_clause_sentence(
    qtbot, draft_with_a_multi_node_fragment
) -> None:
    """The first statement of a route is the expensive one: there is nothing to duplicate from."""

    model = ClauseFactReviewModel(draft_with_a_multi_node_fragment)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    assert dialog.facts_list.count() == len(model.proposals(HF_ROUTE))
    # These nodes carry one sentence each, so a draft per sentence is a draft per node here.
    assert dialog.facts_list.count() == _SEEDED_NODE_COUNT
    # A proposed draft is not an authored statement, so there is nothing to retract or duplicate.
    assert dialog.retract_button.isEnabled() is False
    assert dialog.duplicate_button.isEnabled() is False


def test_the_proposed_drafts_are_not_offered_as_a_statement_count(
    qtbot, draft_with_a_multi_node_fragment
) -> None:
    """A sentence is not a statement, and nothing on this surface may imply that it is.

    The reviewer decides how many statements a clause makes; a wording that reads as a count
    would make this prefill look like a reading of the source, which it is not.
    """

    model = ClauseFactReviewModel(draft_with_a_multi_node_fragment)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    assert "Sentence count is not statement count" in dialog.facts_list.toolTip()
    assert all(
        "statement" not in dialog.facts_list.item(index).text()
        for index in range(dialog.facts_list.count())
    )


def test_selecting_a_draft_cites_its_own_node_and_leaves_unsettled_dimensions_unchosen(
    qtbot, draft_with_a_multi_node_fragment
) -> None:
    """The saving: the reviewer fills dimensions instead of also picking an index and a node.

    The invented node text settles no dimension, so this also pins the honest half: a dimension
    no rule reached stays blank and Author stays disabled, rather than defaulting to anything.
    """

    model = ClauseFactReviewModel(draft_with_a_multi_node_fragment)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    nodes = model.nodes(f"raw-{HF_ROUTE}")

    dialog.facts_list.setCurrentRow(1)

    # The next free index for the route, not the draft's own position: authoring the fifth draft
    # first must not claim index five.
    assert dialog.statement_index.value() == 0
    assert [item.text() for item in dialog.nodes_list.selectedItems()] == [
        dialog.nodes_list.item(1).text()
    ]
    # Every dimension the draft did not settle stays blank -- and the one this route's grammar
    # declares as a constant arrives filled, which is what a prefill is for.
    draft = model.open_proposals(HF_ROUTE)[1]
    assert draft.chosen == {"threshold_reference": ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}
    assert all(
        dialog.dimension_combo(field).currentText() == draft.chosen.get(field, "")
        for field in dialog.dimension_options
    )
    assert all(not _selected_scope(dialog, field) for field in dialog.scope_options)
    assert dialog.author_button.isEnabled() is False

    _fill_hf_dimensions(dialog)
    dialog.author_selected()

    (review,) = model.draft.clause_fact_reviews
    (citation,) = review.fact.node_references
    assert citation.node_order == nodes[1].node_order
    # Marked in the notes, so the audit distinguishes a confirmed proposal from a typed reading.
    assert "proposal" in review.notes


def test_walking_the_proposed_drafts_records_nothing(
    qtbot, draft_with_a_multi_node_fragment
) -> None:
    """A proposal is a prefill of the editor: a reviewer who authors nothing has changed nothing."""

    model = ClauseFactReviewModel(draft_with_a_multi_node_fragment)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    for index in range(dialog.facts_list.count()):
        dialog.facts_list.setCurrentRow(index)

    assert model.draft == draft_with_a_multi_node_fragment


def test_a_proposed_draft_can_be_authored_citing_more_than_its_own_node(
    qtbot, draft_with_a_multi_node_fragment
) -> None:
    """A proposal must not narrow what a statement may rest on: further nodes are added by hand."""

    model = ClauseFactReviewModel(draft_with_a_multi_node_fragment)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    dialog.facts_list.setCurrentRow(0)
    _fill_hf_dimensions(dialog)

    dialog.nodes_list.item(2).setSelected(True)
    dialog.author_selected()

    (review,) = model.draft.clause_fact_reviews
    assert {item.node_order for item in review.fact.node_references} == {0, 2}
    # The authored statement joins the list; the remaining drafts stay reachable, so the
    # statements a proposal could not settle keep their prefill.
    assert dialog.facts_list.count() == 1 + _SEEDED_NODE_COUNT


def test_an_authored_row_shows_its_reading_not_just_its_index(
    qtbot, draft_with_supply_fragments
) -> None:
    """A row naming only the index and the family is what made ten duplicates look distinct."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _author_hf_through_dialog(model, dialog)

    text = dialog.facts_list.item(0).text()

    assert "statement 0" in text
    # Every dimension of the family, derived from the model rather than a per-family format.
    for value in ("requirement", "test", ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC):
        assert value in text
    # A boolean reads as the editor's own two values, so a row and the editor agree.
    assert "true" in text


def _author_first_draft(model: ClauseFactReviewModel, dialog: ClauseFactReviewDialog) -> None:
    """Select the route's first draft and author exactly the reading it proposes."""

    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    dialog.facts_list.setCurrentRow(0)
    dialog.author_selected()


def test_an_authored_draft_leaves_the_list(qtbot, draft_with_fully_proposed_sentences) -> None:
    """A draft the reviewer has authored is done; leaving it open invites a second copy of it."""

    model = ClauseFactReviewModel(draft_with_fully_proposed_sentences)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    before = len(model.open_proposals(HF_ROUTE))

    _author_first_draft(model, dialog)

    assert len(model.open_proposals(HF_ROUTE)) == before - 1
    # One authored statement plus the drafts still open, and the authored one's sentence is not
    # offered again as a draft.
    assert dialog.facts_list.count() == 1 + before - 1
    assert model.covered_by(HF_ROUTE, model.proposals(HF_ROUTE)[0]) == 0


#: One invented sentence carrying two of the synthetic attenuation grammar's markers and neither of
#: the other two, so its draft settles some dimensions and leaves the rest to the reviewer -- which
#: is the ordinary case, and the one that used to strand a draft in the list forever.
_PARTLY_PROPOSED_SENTENCE = "Synthetic reading: synthbind synthgateone."


@pytest.fixture
def draft_with_a_partly_proposed_sentence(synthetic_private_grammars: Path) -> ImportedRuleDraft:
    """Every supply fragment, with the attenuation route's one node carrying the sentence above."""

    fragments = tuple(
        fragment_with_sentences(spec.semantic_id, (_PARTLY_PROPOSED_SENTENCE,))
        if spec.semantic_id == HF_ROUTE
        else _fragment(spec.semantic_id)
        for spec in SUPPLY_CLAUSES
    )
    return _logged(_draft(fragments=fragments))


def test_a_draft_whose_unsettled_dimensions_the_reviewer_filled_leaves_the_list(
    qtbot, draft_with_a_partly_proposed_sentence
) -> None:
    """The maintainer's case: a grammar settles what its terms reach, the reviewer reads the rest.

    Matching a draft against an authored statement's *whole* reading made that permanent. The
    authored fact is then strictly more settled than the draft, equality never holds, and the row
    stays in the list indistinguishable from unstarted work -- so the list read as a to-do that could
    never be finished. The reviewer supplying an unsettled dimension is the workflow, not a
    divergence, so those dimensions are not compared.
    """

    model = ClauseFactReviewModel(draft_with_a_partly_proposed_sentence)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    (draft,) = model.open_proposals(HF_ROUTE)

    assert draft.fully_proposed is False
    assert set(draft.unchosen) == {"comparison_required"}

    dialog.facts_list.setCurrentRow(0)
    dialog.use_suggested_button.click()
    # Exactly the one the grammar could not settle, read out of the sentence by the reviewer.
    dialog.dimension_combo("comparison_required").setCurrentText("true")
    dialog.author_selected()

    assert model.open_proposals(HF_ROUTE) == ()
    assert model.covered_by(HF_ROUTE, draft) == 0
    # One authored statement and no draft left: the list is finishable.
    assert dialog.facts_list.count() == 1
    # And the guard agrees for its own reasons, which this test does not change.
    assert model.uncovered(HF_ROUTE) == ()


def test_an_authored_statement_disagreeing_with_a_settled_dimension_covers_nothing(
    qtbot, draft_with_a_partly_proposed_sentence
) -> None:
    """Only the dimensions the draft left unchosen are exempt from the comparison.

    A dimension the grammar did settle and the reviewer then read differently is a divergence from
    the suggestion, and the row stays open to say so -- the reviewer has authored a statement, not
    taken this draft.
    """

    model = ClauseFactReviewModel(draft_with_a_partly_proposed_sentence)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    (draft,) = model.open_proposals(HF_ROUTE)

    assert draft.chosen["evidence_kind"] == "test"

    dialog.facts_list.setCurrentRow(0)
    dialog.use_suggested_button.click()
    dialog.dimension_combo("comparison_required").setCurrentText("true")
    # The one discriminating dimension the grammar settled, read differently by the reviewer.
    dialog.choose_scope("evidence_kind", "simulation")
    dialog.author_selected()

    assert len(model.facts(HF_ROUTE)) == 1
    assert model.covered_by(HF_ROUTE, draft) is None
    assert model.open_proposals(HF_ROUTE) == (draft,)
    # The guard is satisfied all the same: it asks whether a statement of this clause is unreviewed,
    # never whether a suggestion was taken.
    assert model.uncovered(HF_ROUTE) == ()


#: One node carrying three invented sentences, and a second carrying one. The three settle the two
#: dimensions both system-voltage kinds share and no two of them alike, which is the shape the real
#: fragment has; the fourth settles only the modality, which every sentence carries. The markers are
#: coined in ``synthetic_private_grammars`` and mean nothing outside these tests.
_SHARED_NODE_SENTENCES = (
    (
        "Synthetic reading: synthbind synthdirect synthimpulse. "
        "Synthetic reading: synthbind synthrectified synthimpulse. "
        "Synthetic reading: synthbind synthdirect synthtov."
    ),
    "Synthetic reading: synthbind.",
)


@pytest.fixture
def draft_with_sibling_sentences_on_one_node(
    synthetic_private_grammars: Path,
) -> ImportedRuleDraft:
    """Every supply fragment, with the system voltage route's nodes carrying the sentences above."""

    fragments = tuple(
        fragment_with_sentences(spec.semantic_id, _SHARED_NODE_SENTENCES)
        if spec.semantic_id == SV_ROUTE
        else _fragment(spec.semantic_id)
        for spec in SUPPLY_CLAUSES
    )
    return _logged(_draft(fragments=fragments))


def _author_applicability(
    dialog: ClauseFactReviewDialog, *, input_topology: str, purpose: str
) -> None:
    """Switch the loaded draft to the applicability kind, fill that kind, and author.

    The maintainer's own sequence: Fill takes the draft's citation and its measure reading, the kind
    combo is then moved because the sentence states no measure at all, and switching it rebuilds the
    dimension rows unchosen while leaving the cited node selected.
    """

    dialog.choose_statement_kind("applicability")
    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.choose_scope("input_topology", input_topology)
    dialog.choose_scope("purpose", purpose)
    dialog.dimension_combo("counts_as_system_voltage").setCurrentText("true")
    dialog.author_selected()


def test_a_draft_is_closed_by_a_statement_of_the_kind_its_sentence_really_states(
    qtbot, draft_with_sibling_sentences_on_one_node
) -> None:
    """The maintainer's case: the reviewer overrode a mis-proposed kind and the draft stayed.

    A grammar declares exactly one statement kind and no declared term distinguishes the family's
    others, so a sentence stating a different kind of reading gets a wrong-kind draft and the
    reviewer switching the combo is the documented residual of gap 3a. Requiring the authored kind to
    equal the draft's therefore made a draft unclosable on every route where that judgement is
    needed.

    The three drafts share one node, so this also pins the selectivity that makes cross-kind closing
    safe: they settle the two shared dimensions differently, and only the one authored from closes.
    """

    model = ClauseFactReviewModel(draft_with_sibling_sentences_on_one_node)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, SV_ROUTE))
    drafts = model.open_proposals(SV_ROUTE)

    assert len(drafts) == 4
    assert all(item.statement_kind == "measure" for item in drafts)
    # Two anchors for the guard, because it counts cited nodes; four rows for the list, because it
    # counts sentences. The two notions are different here before anything is authored.
    assert len(model.uncovered(SV_ROUTE)) == 2

    dialog.facts_list.setCurrentRow(0)
    dialog.use_suggested_button.click()
    _author_applicability(dialog, input_topology="direct", purpose="impulse")

    (review,) = model.draft.clause_fact_reviews
    assert review.fact.statement_kind == "applicability"
    assert model.covered_by(SV_ROUTE, drafts[0]) == 0
    # Its two siblings on the same node stay open: authoring one statement must not clear the
    # sentences nobody has read yet.
    assert model.open_proposals(SV_ROUTE) == drafts[1:]
    # The guard is untouched by any of it: node-granular, so one statement clears one of its two.
    assert len(model.uncovered(SV_ROUTE)) == 1


def test_a_different_kind_disagreeing_on_a_shared_dimension_closes_nothing(
    qtbot, draft_with_sibling_sentences_on_one_node
) -> None:
    """Cross-kind closing compares the shared dimensions; it does not skip them."""

    model = ClauseFactReviewModel(draft_with_sibling_sentences_on_one_node)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, SV_ROUTE))
    drafts = model.open_proposals(SV_ROUTE)

    dialog.facts_list.setCurrentRow(0)
    dialog.use_suggested_button.click()
    # A topology none of the three sentences names, so every shared comparison disagrees.
    _author_applicability(dialog, input_topology="isolated_secondary", purpose="impulse")

    assert len(model.facts(SV_ROUTE)) == 1
    assert model.open_proposals(SV_ROUTE) == drafts
    assert all(model.covered_by(SV_ROUTE, item) is None for item in drafts)


def test_a_draft_settling_only_family_wide_dimensions_is_never_closed_across_kinds(
    qtbot, draft_with_sibling_sentences_on_one_node
) -> None:
    """ "Agreeing on the empty set is not agreement", one level up.

    The fourth sentence settles only the modality, and its route settles the supply kind for every
    statement it carries -- so agreeing on both identifies no sentence at all. A statement of another
    kind citing that node would otherwise clear a row nobody has read, which is exactly what the
    same rule refuses for a draft that settled nothing.
    """

    model = ClauseFactReviewModel(draft_with_sibling_sentences_on_one_node)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, SV_ROUTE))
    alone = model.open_proposals(SV_ROUTE)[3]

    assert set(alone.chosen) == {"obligation", "supply_kind"}
    assert set(alone.chosen) <= clause_fact_review._UNDISCRIMINATING_DIMENSIONS

    dialog.facts_list.setCurrentRow(3)
    dialog.use_suggested_button.click()
    _author_applicability(dialog, input_topology="direct", purpose="impulse")

    (review,) = model.draft.clause_fact_reviews
    assert {item.node_order for item in review.fact.node_references} == {1}
    assert model.covered_by(SV_ROUTE, alone) is None
    assert alone in model.open_proposals(SV_ROUTE)
    # And matching the kind is no substitute for a discriminating dimension: the same draft, of the
    # kind that was authored, is still not closed.
    same_kind = alone.model_copy(update={"statement_kind": "applicability"})
    assert model.covered_by(SV_ROUTE, same_kind) is None


#: One node carrying three invented sentences of the barrier family, whose variants share nothing
#: but the obligation. Two settle the proposed variant's own scope, differently; the third settles
#: only the modality, which is the shape that used to be closed by a sibling's statement.
_BARRIER_SIBLING_SENTENCES = (
    (
        "Synthetic reading: synthbind synthmainsside. "
        "Synthetic reading: synthbind synthothersid. "
        "Synthetic reading: synthbind and nothing further."
    ),
)


@pytest.fixture
def draft_with_barrier_siblings_on_one_node(
    synthetic_private_grammars: Path,
) -> ImportedRuleDraft:
    """Every supply fragment, with the barrier route's one node carrying the sentences above."""

    barrier_route = ids.SUPPLY_VERIFIED_BARRIER_TRANSFER
    fragments = tuple(
        fragment_with_sentences(spec.semantic_id, _BARRIER_SIBLING_SENTENCES)
        if spec.semantic_id == barrier_route
        else _fragment(spec.semantic_id)
        for spec in SUPPLY_CLAUSES
    )
    return _logged(_draft(fragments=fragments))


def test_agreement_on_the_obligation_alone_closes_no_sibling_draft(
    qtbot, draft_with_barrier_siblings_on_one_node
) -> None:
    """The over-closing the maintainer hit, and the reason it is worse than a cosmetic slip.

    This clause's three sentences rest on one node and this family's variants share nothing but the
    obligation, so a draft whose grammar reached nothing else has an overlap of exactly that one
    dimension -- which every sibling sentence agrees on too. Authoring one statement therefore closed
    a draft whose own reading nobody had written.

    Both safety nets were blind at once. The guard's anchor is node-granular, so the single statement
    below already satisfies it for all three sentences -- asserted here, because that is the hole this
    test documents rather than fixes. With the list dropping the row as well, completion was reachable
    with two of three statements missing and nothing objected.

    So the third draft stays visible and, unless a declaration reaches a discriminating dimension for
    it, unclosable. That is the accepted cost: visible and unclosable is safe.
    """

    barrier_route = ids.SUPPLY_VERIFIED_BARRIER_TRANSFER
    model = ClauseFactReviewModel(draft_with_barrier_siblings_on_one_node)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, barrier_route))
    first, sibling, obligation_only = model.open_proposals(barrier_route)

    assert set(obligation_only.chosen) == {"obligation"}
    assert {item.node_references[0].node_order for item in (first, sibling, obligation_only)} == {0}

    dialog.facts_list.setCurrentRow(0)
    dialog.use_suggested_button.click()
    dialog.dimension_combo("rating_reference").setCurrentText(
        ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC
    )
    dialog.author_selected()

    assert len(model.facts(barrier_route)) == 1
    # Only the draft whose discriminating dimension the statement matches.
    assert model.covered_by(barrier_route, first) == 0
    assert model.covered_by(barrier_route, sibling) is None
    assert model.covered_by(barrier_route, obligation_only) is None
    assert model.open_proposals(barrier_route) == (sibling, obligation_only)
    # The guard, untouched and already satisfied: one node, one anchor, one statement. Two of this
    # clause's three statements are unauthored and it reports nothing -- a maintainer decision under
    # A5/A5-C, quantified in the report rather than changed here.
    assert model.uncovered(barrier_route) == ()


def test_a_draft_that_settles_no_dimension_is_never_covered(
    qtbot, draft_with_supply_fragments, synthetic_private_grammars: Path
) -> None:
    """Agreeing on the empty set is not agreement.

    This replaces the equality rule's own guarantee, which was that a draft settling less than an
    authored statement is never called done. That rule is gone -- a draft the grammar could not fully
    settle has to be closable -- and the risk it guarded against survives at the bottom end: a draft
    that settled *nothing* would be covered by whatever statement happened to cite its node, and a
    row nobody has read would leave the list looking done.

    The barrier route's synthetic grammar declares no rule and no constant, so its draft settles
    nothing at all. The statement authored below cites that draft's own node and still does not cover
    it. The completion guard, meanwhile, *is* satisfied -- which is the two notions being different
    on purpose, asserted in the one place they disagree.
    """

    barrier_route = ids.SUPPLY_VERIFIED_BARRIER_TRANSFER
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, barrier_route))
    (draft,) = model.open_proposals(barrier_route)

    assert draft.chosen == {}

    dialog.facts_list.setCurrentRow(0)
    dialog.nodes_list.item(draft.node_references[0].node_order).setSelected(True)
    dialog.choose_statement_kind("rating_resolution")
    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.choose_scope("rated_side", "mains")
    dialog.dimension_combo("rating_reference").setCurrentText(
        ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC
    )
    dialog.author_selected()

    assert len(model.facts(barrier_route)) == 1
    assert model.covered_by(barrier_route, draft) is None
    assert model.open_proposals(barrier_route) == (draft,)
    assert model.uncovered(barrier_route) == ()


def test_no_action_authors_more_than_one_statement(
    qtbot, draft_with_fully_proposed_sentences
) -> None:
    """Amendment A1: the route-level "author every fully proposed draft" action is gone.

    Not disabled and not hidden -- removed, on both the dialog and the model. A proposal is
    assistance and the maintainer is the authority, so one press certifying several
    machine-derived normative facts is not review, and leaving the affordance reachable from
    either layer would leave that press available.
    """

    model = ClauseFactReviewModel(draft_with_fully_proposed_sentences)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    assert not hasattr(model, "author_proposed")
    assert not hasattr(dialog, "author_proposed_button")
    assert not hasattr(dialog, "author_proposed_selected")
    # No surviving control offers to author more than the one statement in the editor.
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    labels = [button.text() for button in dialog.findChildren(QPushButton)]
    assert labels
    assert not any("all" in label.lower() for label in labels)


def test_one_authoring_action_records_exactly_one_statement(
    qtbot, draft_with_fully_proposed_sentences
) -> None:
    """Every fully proposed draft is still reachable -- one suggestion, one Author, one fact."""

    model = ClauseFactReviewModel(draft_with_fully_proposed_sentences)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    fully_proposed = sum(1 for item in model.open_proposals(HF_ROUTE) if item.fully_proposed)
    assert fully_proposed > 1

    recorded = []
    for _press in range(fully_proposed):
        position = next(
            index
            for index, item in enumerate(model.open_proposals(HF_ROUTE))
            if item.fully_proposed
        )
        dialog.facts_list.setCurrentRow(len(model.facts(HF_ROUTE)) + position)
        dialog.use_suggested_button.click()
        dialog.author_selected()
        recorded.append(len(model.facts(HF_ROUTE)))

    # One statement per authoring action, never two, and never none.
    assert recorded == list(range(1, fully_proposed + 1))
    reviews = [item for item in model.draft.clause_fact_reviews if item.rule_route == HF_ROUTE]
    assert len({item.fact_sha256 for item in reviews}) == len(reviews)
    assert all("proposal" in item.notes for item in reviews)


def test_the_dialog_reports_the_duplicate_refusal_rather_than_raising(
    qtbot, draft_with_fully_proposed_sentences
) -> None:
    """The path still reachable once a covered draft leaves the list: a hand-typed index.

    Selecting the authored statement loads it for replacement at its own index, which is the
    sanctioned path. Typing a free index instead asks for a second copy of it, and that is the
    importer's refusal, surfaced where the reviewer pressed the button with nothing recorded.
    """

    model = ClauseFactReviewModel(draft_with_fully_proposed_sentences)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _author_first_draft(model, dialog)

    dialog.facts_list.setCurrentRow(0)
    assert dialog.statement_index.value() == 0
    dialog.statement_index.setValue(1)
    dialog.author_selected()

    assert "already authored as statement 0" in dialog.status_text
    assert len(model.draft.clause_fact_reviews) == 1


def test_the_suggestion_action_needs_a_selected_draft_and_records_nothing(
    qtbot, draft_with_a_multi_node_fragment
) -> None:
    """The gate the prefill must not dissolve: it fills the editor and records no statement."""

    model = ClauseFactReviewModel(draft_with_a_multi_node_fragment)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    assert dialog.use_suggested_button.isEnabled() is False
    dialog.use_suggested_selected()
    assert "Select a proposed draft" in dialog.status_text

    # These nodes settle no dimension, so the suggestion leaves the reading unauthorable.
    dialog.facts_list.setCurrentRow(0)
    assert dialog.use_suggested_button.isEnabled() is True
    dialog.use_suggested_button.click()

    assert not model.draft.clause_fact_reviews
    assert dialog.author_button.isEnabled() is False
    assert "unchosen dimension(s)" in dialog.status_text


# --- the clause as printed, and telling the reviewer what to do -----------------------


def test_the_source_pane_renders_the_routes_own_declared_regions(qtbot, tmp_path) -> None:
    """A reviewer interprets a statement against the page it is printed on.

    Exactly the reviewed segments, cropped: rendering the whole page would put unreviewed text
    beside the statement as if it were part of the evidence.
    """

    path = tmp_path / "clause.pdf"
    create_clause_pdf(path)
    fragment = _fragment_over_segments(HF_ROUTE, (_PREVIEW_SEGMENT,))
    fragments = tuple(
        fragment if spec.semantic_id == HF_ROUTE else _fragment(spec.semantic_id)
        for spec in SUPPLY_CLAUSES
    )
    model = ClauseFactReviewModel(_logged(_draft(fragments=fragments)))
    dialog = ClauseFactReviewDialog(model, pdf_paths={"SYNTHETIC": path})
    qtbot.addWidget(dialog)

    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    assert len(dialog.source_preview.pixmaps) == 1
    assert dialog.source_preview.messages == ()
    # Cropped to the declared region, so it is far shorter than the whole page.
    assert dialog.source_preview.pixmaps[0].height() < dialog.source_preview.pixmaps[0].width() * 3


def test_a_route_with_no_declared_region_says_so_instead_of_showing_a_page(
    qtbot, draft_with_supply_fragments
) -> None:
    """The shared fixture's fragments carry no segment inventory; none may be invented for them."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    assert dialog.source_preview.pixmaps == ()
    assert dialog.source_preview.messages == (clause_fact_review._NO_SOURCE_REGION,)


def test_every_disabled_action_states_why_it_is_disabled(
    qtbot, draft_with_supply_fragments
) -> None:
    """The maintainer sat in front of grey buttons with no path forward; that must be impossible."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    for button in (
        dialog.author_button,
        dialog.use_suggested_button,
        dialog.retract_button,
        dialog.duplicate_button,
    ):
        assert button.isEnabled() is False
        assert button.toolTip()

    dialog.nodes_list.item(0).setSelected(True)
    _fill_hf_dimensions(dialog)

    assert dialog.author_button.isEnabled() is True
    # Cleared once the action works, so a tooltip never states a reason that is no longer true.
    assert dialog.author_button.toolTip() == ""


def test_a_blocked_completion_names_the_uncovered_statements_and_the_way_out(
    qtbot, draft_with_a_multi_node_fragment
) -> None:
    """The completion guard on this surface: which statements are missing, and what clears it.

    A disabled control with no path forward is the specific complaint an earlier iteration earned,
    so the route row states the reason and the button itself carries the remedy. Once every known
    statement is authored, completion becomes available -- and it still has to be pressed, because
    consuming the drafts is a lower bound on review and never the assertion itself.

    The remedy must not tell the reviewer to author whichever draft is offered. A grammar proposes
    one statement kind, coverage is variant-agnostic on purpose, and following that instruction on a
    node stating a different kind records a wrong-kind reading *and* clears the block with it. So
    the text is asserted to send the reviewer to the node and its kind, and never to the draft
    alone.
    """

    model = ClauseFactReviewModel(draft_with_a_multi_node_fragment)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    position = _route_position(model, HF_ROUTE)
    dialog.table.selectRow(position)

    assert dialog.complete_button.isEnabled() is False
    tooltip = dialog.complete_button.toolTip()
    for node_order in range(_SEEDED_NODE_COUNT):
        assert f"node(s) {node_order}" in tooltip
    assert "Record completion becomes available" in tooltip
    # The honest remedy: the node and the kind of reading it states, never "author the draft".
    assert "choose the kind of reading the node states" in tooltip
    assert "where a node states a different kind" in tooltip
    assert "author a statement for it" not in tooltip

    # One statement per node, each from that node's own draft: the authored ones come first in the
    # list, and these drafts settle no dimension so none of them ever leaves it.
    for index in range(_SEEDED_NODE_COUNT):
        dialog.facts_list.setCurrentRow(len(model.facts(HF_ROUTE)) + index)
        _fill_hf_dimensions(dialog)
        dialog.author_selected()
        if index == 0:
            # Part-way through: the row itself names what is still missing, so a reviewer scanning
            # the table sees the blocked completion without having to hover the button.
            row_text = dialog.table.item(position, _STATUS_COLUMN).text()
            assert row_text.startswith("needs_completion")
            assert "node(s) 1" in row_text

    dialog.table.selectRow(position)
    assert model.uncovered(HF_ROUTE) == ()
    assert dialog.complete_button.isEnabled() is True
    assert dialog.complete_button.toolTip() == ""
    # Available, not done: the maintainer's own assertion is still the thing that completes it.
    assert dialog.table.item(position, _STATUS_COLUMN).text() == "needs_completion"

    dialog.complete_selected()

    assert dialog.table.item(position, _STATUS_COLUMN).text() == "complete"


def test_selecting_a_partly_proposed_draft_names_the_dimensions_still_needed(
    qtbot, draft_with_supply_fragments, synthetic_private_grammars: Path
) -> None:
    """Naming them is the difference between a disabled button and a next step."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    dialog.facts_list.setCurrentRow(0)

    assert "unchosen dimension(s)" in dialog.status_text
    assert "evidence_kind" in dialog.status_text
    assert "Author fact" in dialog.status_text

    _fill_hf_dimensions(dialog)

    assert "ready" in dialog.status_text


def test_the_dimension_hint_does_not_survive_a_change_of_route(
    qtbot, draft_with_supply_fragments, synthetic_private_grammars: Path
) -> None:
    """A hint naming a family's dimensions under a route that declares none of them is a dead end.

    The maintainer selected the monitoring and attenuation routes and the status line still asked
    for the reduction family's own dimensions, which those routes' editors do not offer at all --
    so the one line telling them what to do next named fields that were not on the screen.
    """

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, MAINS_ROUTE))
    dialog.facts_list.setCurrentRow(0)
    reduction_only = {"insulation_classes", "permitted_steps"}

    assert "unchosen dimension(s)" in dialog.status_text
    assert reduction_only <= {field for field in reduction_only if field in dialog.status_text}

    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    # Nothing carried over: the route being left is what wrote that line.
    assert not any(field in dialog.status_text for field in reduction_only)

    dialog.facts_list.setCurrentRow(0)
    offered = {*dialog.dimension_options, *dialog.scope_options, *dialog.pair_options}
    hint = dialog.status_text

    assert "unchosen dimension(s)" in hint
    assert not any(field in hint for field in reduction_only)
    # And it names this route's own dimensions, so clearing it did not silence the hint instead.
    assert any(field in hint for field in offered)


def test_the_routes_table_stretches_the_columns_a_reviewer_picks_a_row_by(
    qtbot, draft_with_supply_fragments
) -> None:
    """Both id columns truncated to a few characters, which made the table unreadable."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    header = dialog.table.horizontalHeader()

    modes = {heading: header.sectionResizeMode(column) for column, heading in enumerate(_HEADINGS)}

    assert modes["route"] == QHeaderView.ResizeMode.Stretch
    assert modes["fragment"] == QHeaderView.ResizeMode.Stretch
    assert modes["authored"] == QHeaderView.ResizeMode.ResizeToContents
    # Tall enough for every route at once rather than opening as a two-row slit.
    assert dialog.table.maximumHeight() >= sum(
        dialog.table.rowHeight(row) for row in range(dialog.table.rowCount())
    )


# --- one suggestion at a time ---------------------------------------------------------

#: Invented sentences carrying, between them, every marker the synthetic attenuation grammar names
#: -- two that settle every dimension and one that settles none. The markers are coined in
#: ``synthetic_private_grammars`` and mean nothing outside these tests; the real grammar's own terms
#: live beside the licensed material (amendment A1) and are not spelled anywhere here.
_FULLY_PROPOSED_SENTENCES = (
    "Synthetic reading: synthbind synthgateone synthcompare.",
    "Synthetic reading: synthbind synthgatetwo synthevidence synthcompare.",
    "Synthetic reading naming nothing the grammar looks for.",
)


@pytest.fixture
def draft_with_fully_proposed_sentences(synthetic_private_grammars: Path) -> ImportedRuleDraft:
    """Every supply fragment, with the attenuation route's nodes carrying the sentences above."""

    fragments = tuple(
        fragment_with_sentences(spec.semantic_id, _FULLY_PROPOSED_SENTENCES)
        if spec.semantic_id == HF_ROUTE
        else _fragment(spec.semantic_id)
        for spec in SUPPLY_CLAUSES
    )
    return _logged(_draft(fragments=fragments))


def test_the_suggestion_loads_one_drafts_values_and_its_citation(
    qtbot, draft_with_fully_proposed_sentences
) -> None:
    """The permitted half of amendment A1: one draft's suggested dimensions, then Author.

    The prefill carries the draft's own citation and its settled dimensions and nothing else, and
    the statement is recorded by the ordinary per-statement Author -- so the reviewer sees the
    reading and the evidence before anything is written.
    """

    model = ClauseFactReviewModel(draft_with_fully_proposed_sentences)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    position = _route_position(model, HF_ROUTE)
    dialog.table.selectRow(position)
    proposal = model.open_proposals(HF_ROUTE)[0]

    dialog.facts_list.setCurrentRow(0)
    # The label says what the press does. "Use suggested values" read as accepting them, and a
    # button that fills the editor and records nothing must not be worded like one that certifies.
    assert dialog.use_suggested_button.text() == "Fill with the suggested values"
    dialog.use_suggested_button.click()

    assert _selected_scope(dialog, "evidence_kind") == list(
        proposal.chosen["evidence_kind"].split("|")
    )
    assert [item.text() for item in dialog.nodes_list.selectedItems()] == [
        dialog.nodes_list.item(proposal.node_references[0].node_order).text()
    ]
    # Loading a suggestion records nothing at all.
    assert model.draft == draft_with_fully_proposed_sentences

    dialog.author_selected()

    reviews = [item for item in model.draft.clause_fact_reviews if item.rule_route == HF_ROUTE]
    assert [item.statement_index for item in reviews] == [0]
    assert scope_wire(reviews[0].fact.evidence_kind) == proposal.chosen["evidence_kind"]
    assert reviews[0].actor == "maintainer"
    assert "proposal" in reviews[0].notes
    # The route's other drafts are still unauthored, which the completion guard names in the row.
    assert dialog.table.item(position, _STATUS_COLUMN).text().startswith("needs_completion")


def test_the_statement_the_grammar_could_not_settle_is_left_for_the_reviewer(
    qtbot, draft_with_fully_proposed_sentences
) -> None:
    """A partly proposed draft keeps its prefill and its blank fields, however many are authored."""

    model = ClauseFactReviewModel(draft_with_fully_proposed_sentences)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    # One suggestion, one Author, twice over: the two fully proposed drafts, one at a time.
    for _press in range(2):
        position = next(
            index
            for index, item in enumerate(model.open_proposals(HF_ROUTE))
            if item.fully_proposed
        )
        dialog.facts_list.setCurrentRow(len(model.facts(HF_ROUTE)) + position)
        dialog.use_suggested_button.click()
        dialog.author_selected()

    remaining = [item for item in model.proposals(HF_ROUTE) if not item.fully_proposed]
    assert len(remaining) == 1
    # The two authored drafts have left the list; the one the grammar could not settle stays,
    # keeping its prefill and its blank fields.
    assert dialog.facts_list.count() == 2 + len(remaining)
    dialog.facts_list.setCurrentRow(2)
    assert _selected_scope(dialog, "evidence_kind") == []
    assert dialog.author_button.isEnabled() is False


def test_the_button_is_enabled_by_clause_fragments(qtbot, draft_with_supply_fragments) -> None:
    """Clause fact review is its own approval gate, reachable whenever fragments exist."""

    from insulation_coordination.ui.rules_manager import RulesManagerWindow

    window = RulesManagerWindow()
    qtbot.addWidget(window)

    window.set_draft(draft_with_supply_fragments)
    assert window.clause_fact_review_enabled is True

    window.set_draft(draft_with_supply_fragments.model_copy(update={"raw_clause_fragments": ()}))
    assert window.clause_fact_review_enabled is False
