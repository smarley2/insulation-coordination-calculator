"""The prompt button, its preview and its clipboard: an aid that records nothing.

Every fragment these tests read is the synthetic one, so the licensed text the real feature quotes
never appears here.
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication

from insulation_coordination.rules.importer.clause_fact_ai_prompt import (
    build_clause_fact_ai_prompt,
)
from insulation_coordination.ui.clause_fact_ai_prompt import (
    LICENCE_WARNING,
    ClauseFactAiPromptDialog,
)
from insulation_coordination.ui.clause_fact_review import (
    ClauseFactReviewDialog,
    ClauseFactReviewModel,
)
from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft
from tests.ui.test_clause_fact_review import (
    HF_ROUTE,
    _author_hf_through_dialog,
    _route_position,
)


def test_the_button_is_disabled_until_a_route_is_selected(qtbot) -> None:
    """A draft with no route never selects a row, so the button must open disabled and say why."""

    dialog = ClauseFactReviewDialog(ClauseFactReviewModel(_draft()))
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 0
    assert not dialog.ai_prompt_button.isEnabled()
    assert "Select a rule route first" in dialog.ai_prompt_button.toolTip()


def test_selecting_a_route_enables_the_button(qtbot, draft_with_supply_fragments) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)

    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    assert dialog.ai_prompt_button.isEnabled()
    assert dialog.ai_prompt_button.toolTip() == ""


def test_the_preview_shows_the_prompt_for_the_selected_route(
    qtbot, draft_with_supply_fragments
) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))

    preview = dialog.ai_prompt_dialog()

    assert preview is not None
    qtbot.addWidget(preview)
    assert preview.prompt == build_clause_fact_ai_prompt(model.ai_prompt_context(HF_ROUTE))
    assert HF_ROUTE in preview.prompt
    assert model.nodes(f"raw-{HF_ROUTE}")[0].raw_text in preview.prompt


def test_the_licence_warning_is_visible_before_anything_is_copied(
    qtbot, draft_with_supply_fragments
) -> None:
    """The whole point of the preview: the reviewer decides the disclosure, so they must read it."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    QGuiApplication.clipboard().setText("untouched")

    preview = dialog.ai_prompt_dialog()

    assert preview is not None
    qtbot.addWidget(preview)
    assert preview.warning.text() == LICENCE_WARNING
    assert "licensed clause text" in LICENCE_WARNING
    # Opening the preview copies nothing: licensed text on the clipboard of anyone who merely
    # looked at it is the disclosure this dialog exists to make deliberate.
    assert QGuiApplication.clipboard().text() == "untouched"
    assert preview.status_text == ""


def test_copy_prompt_writes_exactly_the_previewed_text(qtbot) -> None:
    preview = ClauseFactAiPromptDialog("invented prompt body")
    qtbot.addWidget(preview)
    QGuiApplication.clipboard().setText("untouched")

    preview.copy_prompt()

    assert QGuiApplication.clipboard().text() == "invented prompt body"
    assert preview.status_text


def test_generating_a_prompt_records_nothing(qtbot, draft_with_supply_fragments) -> None:
    """An aid, not an authoring path: no review, no dismissal, no completion, no draft change."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    before = model.draft

    preview = dialog.ai_prompt_dialog()

    assert preview is not None
    qtbot.addWidget(preview)
    preview.copy_prompt()
    preview.reject()

    assert model.draft == before
    assert model.draft.clause_fact_reviews == ()
    assert model.draft.clause_fact_completions == ()
    assert model.draft.clause_fact_dismissals == ()


def test_a_reopened_prompt_describes_the_route_as_it_now_is(
    qtbot, draft_with_supply_fragments
) -> None:
    """Assembled per press, never cached: a stale prompt asks a model an already-answered question."""

    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_route_position(model, HF_ROUTE))
    first = dialog.ai_prompt_dialog()
    assert first is not None
    qtbot.addWidget(first)

    _author_hf_through_dialog(model, dialog)
    second = dialog.ai_prompt_dialog()

    assert second is not None
    qtbot.addWidget(second)
    assert "(none authored for this route yet)" in first.prompt
    assert "next suggested statement index: 0" in first.prompt
    assert "(none authored for this route yet)" not in second.prompt
    assert "statement 0, kind requirement" in second.prompt
    assert "next suggested statement index: 1" in second.prompt


def test_a_retraction_is_reflected_in_the_next_prompt(qtbot, draft_with_supply_fragments) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    dialog = ClauseFactReviewDialog(model)
    qtbot.addWidget(dialog)
    _author_hf_through_dialog(model, dialog)
    model.retract(HF_ROUTE, 0, actor="tester", notes="retracted")

    preview = dialog.ai_prompt_dialog()

    assert preview is not None
    qtbot.addWidget(preview)
    assert "(none authored for this route yet)" in preview.prompt
