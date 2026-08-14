"""The authoring surface: the reviewer reads nodes and writes facts. No logic in Qt."""

from __future__ import annotations

from typing import Literal, get_args

import pytest
from PySide6.QtCore import Qt

from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.importer import clause_fact_proposals
from insulation_coordination.rules.importer.clause_facts import (
    BarrierTransferFact,
    CitedNode,
    HfAttenuationFact,
    SpdMonitoringFact,
    SpdReductionFact,
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
    SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE,
)
from insulation_coordination.ui.clause_fact_review import (
    ClauseFactReviewDialog,
    ClauseFactReviewModel,
)
from tests.conftest import _logged
from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft
from tests.rules.importer.iec62477_2022.test_supply_clause_recipes import _fragment
from tests.rules.importer.test_clause_fact_proposals import fragment_with_sentences
from tests.rules.importer.test_clause_fact_review_api import _hf_fact

HF_ROUTE = ids.SUPPLY_HF_TRANSFORMER_ATTENUATION
MAINS_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"
_STATUS_COLUMN = 2

# Stated here independently of the UI's own mapping, so these tests prove the editor offers the
# family the route declares rather than agreeing with whatever the dialog decided.
_FACT_MODELS = {
    "system_voltage": SystemVoltageFact,
    "barrier_transfer": BarrierTransferFact,
    "spd_reduction": SpdReductionFact,
    "spd_monitoring": SpdMonitoringFact,
    "hf_attenuation": HfAttenuationFact,
}


def _expected_options(fact_kind: str) -> dict[str, tuple[str, ...]]:
    """Every combo dimension's vocabulary: literals verbatim, booleans as the two-value choice."""

    options: dict[str, tuple[str, ...]] = {}
    for name, field in _FACT_MODELS[fact_kind].model_fields.items():
        if name in ("fact_kind", "statement_index", "node_references"):
            continue
        if field.annotation is bool:
            options[name] = ("true", "false")
        elif get_args(field.annotation):
            options[name] = get_args(field.annotation)
    return options


def _route_position(model: ClauseFactReviewModel, rule_route: str) -> int:
    return next(
        position for position, row in enumerate(model.routes()) if row.rule_route == rule_route
    )


def _fill_hf_dimensions(dialog: ClauseFactReviewDialog) -> None:
    """Choose every dimension of the HF family, leaving only the index and the citation."""

    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.dimension_combo("dvc_gate").setCurrentText("dvc_as")
    dialog.dimension_combo("evidence_kind").setCurrentText("test")
    dialog.dimension_edit("threshold_reference").setText(ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC)
    dialog.dimension_combo("comparison_required").setCurrentText("true")


def _author_hf_through_dialog(model: ClauseFactReviewModel, dialog: ClauseFactReviewDialog) -> int:
    """Select the HF route, read its first node, fill every dimension, and author."""

    position = _route_position(model, HF_ROUTE)
    dialog.table.selectRow(position)
    dialog.nodes_list.item(0).setSelected(True)
    _fill_hf_dimensions(dialog)
    dialog.author_selected()
    return position


@pytest.fixture
def hf_fact(draft_with_supply_fragments) -> HfAttenuationFact:
    return _hf_fact(draft_with_supply_fragments, statement_index=0)


class _DriftedFact(HfAttenuationFact):
    """A fact family one of whose dimensions is no longer expressible by any editor widget."""

    dvc_gate: Literal[1, 2]  # type: ignore[assignment]


def test_a_dimension_without_a_string_vocabulary_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silent degradation here is an unauthorable route and an approval blocked with no message."""

    monkeypatch.setitem(clause_fact_proposals.FACT_MODEL_BY_KIND, "hf_attenuation", _DriftedFact)

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

    model.author(
        HF_ROUTE,
        _hf_fact(draft_with_supply_fragments, statement_index=1),
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
    assert dialog.dimension_combo("dvc_gate").currentText() == "dvc_as"
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
    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.dimension_combo("dvc_gate").setCurrentText("dvc_as")
    dialog.dimension_combo("evidence_kind").setCurrentText("test")
    dialog.dimension_edit("threshold_reference").setText(ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC)
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

    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.dimension_combo("dvc_gate").setCurrentText("dvc_as")
    dialog.dimension_combo("evidence_kind").setCurrentText("test")
    dialog.dimension_edit("threshold_reference").setText(ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC)
    dialog.dimension_combo("comparison_required").setCurrentText("true")

    assert dialog.author_button.isEnabled() is False
    dialog.nodes_list.item(0).setSelected(True)
    assert dialog.author_button.isEnabled() is True


def test_each_combo_offers_exactly_its_fields_vocabulary(
    qtbot, draft_with_supply_fragments
) -> None:
    """The editor is built from the fact models, so a wrong-family editor cannot be offered."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    offered = []
    for position, row in enumerate(model.routes()):
        dialog.table.selectRow(position)
        family = SUPPLY_FACT_FAMILY_BY_ROUTE[row.rule_route]
        assert dialog.family_text == family
        offered.append((family, dialog.dimension_options))

    # Every non-legacy family is reachable; propagation_step belongs only to the legacy route.
    assert {family for family, _options in offered} == set(_FACT_MODELS)
    assert all(options == _expected_options(family) for family, options in offered)


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

    combo = dialog.dimension_combo("supply_kind")
    assert combo.currentText() == SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE[MAINS_ROUTE]
    assert combo.isEnabled() is False


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
    assert dialog.dimension_combo("dvc_gate").currentText() == "dvc_as"
    assert [item.text() for item in dialog.nodes_list.selectedItems()]

    dialog.dimension_combo("dvc_gate").setCurrentText("dvc_b")
    dialog.author_selected()

    facts = model.facts(HF_ROUTE)
    assert [row.statement_index for row in facts] == [0, 1]
    assert facts[0].fact.dvc_gate == "dvc_as"
    assert facts[1].fact.dvc_gate == "dvc_b"


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
def draft_with_a_multi_node_fragment() -> ImportedRuleDraft:
    """Every supply fragment, one of them carrying several single-sentence nodes.

    The shared fixture gives each fragment a single node, which cannot show a surface that
    offers a draft per sentence across nodes. Node text stays invented here exactly as it is
    there. Rebuilt rather than copied from that fixture, because the extraction audit record
    every correction verifies is a digest of the fragments themselves.
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

    assert "Sentence count is not statement count" in dialog.seed_hint.text()
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
    assert all(
        dialog.dimension_combo(field).currentText() == "" for field in dialog.dimension_options
    )
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
    assert dialog.seed_hint.text() != ""


def test_the_batch_action_stays_disabled_while_no_draft_is_fully_proposed(
    qtbot, draft_with_a_multi_node_fragment
) -> None:
    """The gate the batch action must not dissolve: it can only confirm complete readings."""

    model = ClauseFactReviewModel(draft_with_a_multi_node_fragment)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    assert dialog.author_proposed_button.isEnabled() is False

    dialog.author_proposed_selected()

    assert not model.draft.clause_fact_reviews
    assert "No draft" in dialog.status_text


# --- authoring every fully proposed statement of a route ------------------------------

#: Invented sentences carrying, between them, every term the attenuation route's declared rules
#: name -- two that settle every dimension and one that settles none. They are written for this
#: file out of the public keyword list and state nothing any clause states.
_FULLY_PROPOSED_SENTENCES = (
    "Synthetic DVC As gate shall be shown by test, simulation or calculation.",
    "Synthetic DVC B gate shall be shown by test, simulation or calculation.",
    "Synthetic reading naming nothing the grammar looks for.",
)


@pytest.fixture
def draft_with_fully_proposed_sentences() -> ImportedRuleDraft:
    """Every supply fragment, with the attenuation route's nodes carrying the sentences above."""

    fragments = tuple(
        fragment_with_sentences(spec.semantic_id, _FULLY_PROPOSED_SENTENCES)
        if spec.semantic_id == HF_ROUTE
        else _fragment(spec.semantic_id)
        for spec in SUPPLY_CLAUSES
    )
    return _logged(_draft(fragments=fragments))


def test_authoring_every_fully_proposed_statement_records_each_one_individually(
    qtbot, draft_with_fully_proposed_sentences
) -> None:
    """Speed without dissolving the gate: one ``author_clause_fact`` per statement, marked.

    The action is a shortcut through the clicking, never through the recording: each statement
    keeps its own actor, notes and audited correction, and the partly proposed draft is left for
    the reviewer rather than completed with a guess.
    """

    model = ClauseFactReviewModel(draft_with_fully_proposed_sentences)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    position = _route_position(model, HF_ROUTE)
    dialog.table.selectRow(position)
    assert dialog.author_proposed_button.isEnabled() is True

    dialog.author_proposed_selected()

    reviews = [item for item in model.draft.clause_fact_reviews if item.rule_route == HF_ROUTE]
    assert [item.statement_index for item in reviews] == [0, 1]
    assert {item.fact.dvc_gate for item in reviews} == {"dvc_as", "dvc_b"}
    assert all(item.actor == "maintainer" for item in reviews)
    assert all("grammar-proposed" in item.notes for item in reviews)
    assert dialog.table.item(position, _STATUS_COLUMN).text() == "needs_completion"
    assert "Recorded 2" in dialog.status_text


def test_the_statement_the_grammar_could_not_settle_is_left_for_the_reviewer(
    qtbot, draft_with_fully_proposed_sentences
) -> None:
    """A partly proposed draft survives the batch and keeps its prefill and its blank fields."""

    model = ClauseFactReviewModel(draft_with_fully_proposed_sentences)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    dialog.author_proposed_selected()

    remaining = [item for item in model.proposals(HF_ROUTE) if not item.fully_proposed]
    assert len(remaining) == 1
    # Two authored statements and every draft still listed: the unsettled one stays reachable.
    assert dialog.facts_list.count() == 2 + len(_FULLY_PROPOSED_SENTENCES)
    dialog.facts_list.setCurrentRow(2 + 2)
    assert dialog.dimension_combo("dvc_gate").currentText() == ""
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
