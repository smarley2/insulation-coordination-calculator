"""The authoring surface: the reviewer reads nodes and writes facts. No logic in Qt."""

from __future__ import annotations

from typing import Literal, get_args

import pytest

from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.importer.clause_facts import (
    BarrierTransferFact,
    HfAttenuationFact,
    SpdMonitoringFact,
    SpdReductionFact,
    SystemVoltageFact,
)
from insulation_coordination.rules.importer.extract import canonical_model_sha256
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    LEGACY_BRANCH_AUTHORITY_RULE_IDS,
    SUPPLY_FACT_FAMILY_BY_ROUTE,
)
from insulation_coordination.ui import clause_fact_review
from insulation_coordination.ui.clause_fact_review import (
    ClauseFactReviewDialog,
    ClauseFactReviewModel,
)
from tests.rules.importer.test_clause_fact_review_api import _hf_fact

HF_ROUTE = ids.SUPPLY_HF_TRANSFORMER_ATTENUATION
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


def _author_hf_through_dialog(model: ClauseFactReviewModel, dialog: ClauseFactReviewDialog) -> int:
    """Select the HF route, read its first node, fill every dimension, and author."""

    position = _route_position(model, HF_ROUTE)
    dialog.table.selectRow(position)
    dialog.nodes_list.item(0).setSelected(True)
    dialog.dimension_combo("obligation").setCurrentText("requirement")
    dialog.dimension_combo("dvc_gate").setCurrentText("dvc_as")
    dialog.dimension_combo("evidence_kind").setCurrentText("test")
    dialog.dimension_edit("threshold_reference").setText(ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC)
    dialog.dimension_combo("comparison_required").setCurrentText("true")
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

    monkeypatch.setitem(clause_fact_review._FACT_MODELS, "hf_attenuation", _DriftedFact)

    with pytest.raises(RulePackageError, match="dvc_gate"):
        clause_fact_review._dimensions("hf_attenuation")


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


def test_the_button_is_enabled_by_clause_fragments(qtbot, draft_with_supply_fragments) -> None:
    """Clause fact review is its own approval gate, reachable whenever fragments exist."""

    from insulation_coordination.ui.rules_manager import RulesManagerWindow

    window = RulesManagerWindow()
    qtbot.addWidget(window)

    window.set_draft(draft_with_supply_fragments)
    assert window.clause_fact_review_enabled is True

    window.set_draft(draft_with_supply_fragments.model_copy(update={"raw_clause_fragments": ()}))
    assert window.clause_fact_review_enabled is False
