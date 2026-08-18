"""The project page's voltage-evidence library.

Every figure here is this module's own invention. Nothing reproduces a value, a heading or any
wording from any standard: what is under test is which entry the panel says governs, how it
says an unapproved one does not, and that one action produces exactly one project.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from insulation_coordination.domain.project import Project
from insulation_coordination.domain.verification import (
    EvidenceApprovalState,
    EvidenceTarget,
    VoltageEvidence,
    VoltageEvidenceMethod,
    VoltageQuantityKind,
)
from insulation_coordination.ui.voltage_evidence import (
    ABOVE_GOVERNING_TEXT,
    COLUMN_LABELS,
    EDIT_APPROVED_REFUSAL,
    GOVERNING_PREFIX,
    NOTHING_GOVERNS_TEXT,
    VoltageEvidencePanel,
    target_label,
)
from tests.fixtures.verification_topologies import LIVE_A, LIVE_B, verification_topology

RECORDED_AT = datetime(2026, 4, 5, 6, 7, 8, tzinfo=UTC)

APPROVAL = COLUMN_LABELS.index("Approval")
COMPARISON = COLUMN_LABELS.index("Comparison")
VALUE = COLUMN_LABELS.index("Value")
MEASUREMENT = COLUMN_LABELS.index("Measurement")
METHOD = COLUMN_LABELS.index("Method")

#: Two invented figures, the higher of the two left unapproved on purpose.
APPROVED_V = Decimal(77)
DRAFT_V = Decimal(91)


def _entry(
    value_v: Decimal,
    *,
    state: EvidenceApprovalState = EvidenceApprovalState.DRAFT,
    method: VoltageEvidenceMethod = VoltageEvidenceMethod.CALCULATION,
    quantity: VoltageQuantityKind = VoltageQuantityKind.AC_RMS,
    net_id: UUID | None = LIVE_A,
    source: str = "SYN-EV-1",
    **overrides: object,
) -> VoltageEvidence:
    fields: dict[str, object] = {
        "id": uuid4(),
        "net_id": net_id,
        "quantity_kind": quantity,
        "value_v": value_v,
        "method": method,
        "operating_condition": "steady running",
        "source_reference": source,
        "recorded_at": RECORDED_AT,
        "approval_state": state,
    }
    fields.update(overrides)
    return VoltageEvidence(**fields)


@pytest.fixture
def project() -> Project:
    return verification_topology()


@pytest.fixture
def panel(qtbot: QtBot, project: Project) -> VoltageEvidencePanel:
    widget = VoltageEvidencePanel()
    qtbot.addWidget(widget)
    widget.set_project(project)
    return widget


def _emitted(qtbot: QtBot, panel: VoltageEvidencePanel) -> list[Project]:
    """Collect every project the panel emits, so a test can count them as well as read them."""

    seen: list[Project] = []
    panel.project_changed.connect(seen.append)
    return seen


def test_adding_an_entry_emits_one_complete_project(
    qtbot: QtBot, panel: VoltageEvidencePanel
) -> None:
    seen = _emitted(qtbot, panel)
    entry = _entry(APPROVED_V)

    panel.add_evidence(entry)

    assert len(seen) == 1
    assert seen[0].voltage_evidence == (entry,)
    assert panel.row_count == 1


def test_a_draft_above_the_governing_figure_never_reads_as_approved(
    panel: VoltageEvidencePanel,
) -> None:
    """The one case the whole approval gate exists for, in the column and in the summary."""

    approved = _entry(APPROVED_V, state=EvidenceApprovalState.APPROVED_FOR_DESIGN)
    draft = _entry(DRAFT_V)
    panel.add_evidence(approved)
    panel.add_evidence(draft)

    row = panel.row_of(draft.id)
    assert panel.row_text(row, APPROVAL) == "draft"
    assert ABOVE_GOVERNING_TEXT in panel.row_text(row, COMPARISON)
    assert "does not govern" in panel.row_text(row, COMPARISON)
    assert panel.row_text(panel.row_of(approved.id), COMPARISON) == "governs"
    assert f"{APPROVED_V} V" in panel.summary_text
    assert f"the highest at {DRAFT_V} V" in panel.summary_text
    assert "none of them governs" in panel.summary_text


def test_nothing_governs_while_every_entry_is_a_draft(panel: VoltageEvidencePanel) -> None:
    panel.add_evidence(_entry(DRAFT_V))

    assert GOVERNING_PREFIX in panel.summary_text
    assert NOTHING_GOVERNS_TEXT in panel.summary_text


def test_approving_moves_the_state_and_nothing_else(
    qtbot: QtBot, panel: VoltageEvidencePanel
) -> None:
    entry = _entry(APPROVED_V)
    panel.add_evidence(entry)
    seen = _emitted(qtbot, panel)

    panel.set_approval(entry.id, EvidenceApprovalState.APPROVED_FOR_DESIGN)

    assert len(seen) == 1
    (stored,) = seen[0].voltage_evidence
    assert stored.approval_state is EvidenceApprovalState.APPROVED_FOR_DESIGN
    assert stored.id == entry.id
    assert stored.value_v == entry.value_v
    assert panel.row_text(panel.row_of(entry.id), COMPARISON) == "governs"


def test_superseding_without_a_justification_is_refused_by_the_model(
    qtbot: QtBot, panel: VoltageEvidencePanel
) -> None:
    entry = _entry(APPROVED_V, state=EvidenceApprovalState.APPROVED_FOR_DESIGN)
    panel.add_evidence(entry)
    seen = _emitted(qtbot, panel)

    with pytest.raises(ValueError):
        panel.set_approval(entry.id, EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION)

    assert seen == []


def test_a_revision_keeps_the_original_and_adds_the_new_figure_in_one_update(
    qtbot: QtBot, panel: VoltageEvidencePanel
) -> None:
    """Both halves land together. A revision that superseded and failed to replace would
    leave the target with nothing governing it."""

    original = _entry(APPROVED_V, state=EvidenceApprovalState.APPROVED_FOR_DESIGN)
    panel.add_evidence(original)
    seen = _emitted(qtbot, panel)
    replacement = _entry(DRAFT_V, source="SYN-EV-2")

    panel.revise_evidence(original.id, replacement, "the model was re-run")

    assert len(seen) == 1
    stored, added = seen[0].voltage_evidence
    assert stored.id == original.id
    assert stored.approval_state is EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION
    assert stored.approval_justification == "the model was re-run"
    assert stored.value_v == APPROVED_V
    assert added.id == replacement.id


def test_an_approved_entry_cannot_be_edited_in_place(
    qtbot: QtBot, panel: VoltageEvidencePanel
) -> None:
    entry = _entry(APPROVED_V, state=EvidenceApprovalState.APPROVED_FOR_DESIGN)
    panel.add_evidence(entry)
    seen = _emitted(qtbot, panel)

    with pytest.raises(ValueError, match="cannot be edited in place"):
        panel.update_draft(entry.id, value_v=DRAFT_V)

    assert seen == []
    assert EDIT_APPROVED_REFUSAL.startswith("This entry is not a draft")


def test_a_draft_is_corrected_in_place_without_gaining_a_row(
    qtbot: QtBot, panel: VoltageEvidencePanel
) -> None:
    entry = _entry(APPROVED_V)
    panel.add_evidence(entry)
    seen = _emitted(qtbot, panel)

    panel.update_draft(entry.id, value_v=DRAFT_V)

    assert len(seen) == 1
    (stored,) = seen[0].voltage_evidence
    assert stored.id == entry.id
    assert stored.value_v == DRAFT_V


def test_a_measurement_shows_where_and_to_what_uncertainty(panel: VoltageEvidencePanel) -> None:
    entry = _entry(
        APPROVED_V,
        method=VoltageEvidenceMethod.MEASUREMENT,
        measurement_points="across the barrier",
        tolerance_or_uncertainty="±2 %",
    )
    panel.add_evidence(entry)

    assert panel.row_text(panel.row_of(entry.id), MEASUREMENT) == "across the barrier / ±2 %"


def test_a_filter_hides_rows_and_changes_nothing_about_what_governs(
    panel: VoltageEvidencePanel,
) -> None:
    approved = _entry(APPROVED_V, state=EvidenceApprovalState.APPROVED_FOR_DESIGN)
    measured = _entry(
        DRAFT_V,
        method=VoltageEvidenceMethod.MEASUREMENT,
        measurement_points="at the terminals",
        tolerance_or_uncertainty="±1 %",
    )
    panel.add_evidence(approved)
    panel.add_evidence(measured)
    summary_before = panel.summary_text

    panel._filter_method.setCurrentIndex(
        panel._filter_method.findData(VoltageEvidenceMethod.CALCULATION.value)
    )

    assert panel.row_count == 1
    assert panel.row_text(0, METHOD) == "calculation"
    assert panel.summary_text == summary_before


def test_the_unresolved_filter_keeps_only_targets_with_a_decision_outstanding(
    panel: VoltageEvidencePanel,
) -> None:
    settled = _entry(APPROVED_V, state=EvidenceApprovalState.APPROVED_FOR_DESIGN, net_id=LIVE_A)
    outstanding = _entry(DRAFT_V, net_id=LIVE_B)
    panel.add_evidence(settled)
    panel.add_evidence(outstanding)

    panel._filter_unresolved.setChecked(True)

    assert panel.row_count == 1
    assert panel.row_text(0, VALUE) == f"{DRAFT_V} V"


def test_deleting_removes_the_entry_in_one_update(
    qtbot: QtBot, panel: VoltageEvidencePanel
) -> None:
    entry = _entry(APPROVED_V)
    panel.add_evidence(entry)
    seen = _emitted(qtbot, panel)

    panel.remove_evidence(entry.id)

    assert len(seen) == 1
    assert seen[0].voltage_evidence == ()


def test_a_target_is_named_by_its_net_or_by_both_of_its_pair_names(project: Project) -> None:
    assert target_label(project, EvidenceTarget(net_id=LIVE_A)) == "net Live A"
    pair = project.pairs[0]
    assert target_label(project, EvidenceTarget(pair_id=pair.id)).startswith("pair ")


def test_the_form_builds_the_entry_the_fields_describe(
    qtbot: QtBot, panel: VoltageEvidencePanel, project: Project
) -> None:
    """The one path from widgets to a model, checked once so the buttons above it can be
    trusted to use it."""

    target = EvidenceTarget(net_id=LIVE_A)
    combo = panel._target_combo
    combo.setCurrentIndex(combo.findData(target.model_dump_json()))
    panel._value_edit.setText(str(APPROVED_V))
    panel._condition_edit.setText("full load")
    panel._source_edit.setText("SYN-EV-9")

    entry = panel.build_entry()

    assert entry.target == target
    assert entry.value_v == APPROVED_V
    assert entry.approval_state is EvidenceApprovalState.DRAFT
    assert entry.source_reference == "SYN-EV-9"


def _fill(panel: VoltageEvidencePanel, value_v: Decimal, source: str = "SYN-EV-9") -> None:
    """Describe an entry in the form, the way a user does before pressing a button."""

    combo = panel._target_combo
    combo.setCurrentIndex(combo.findData(EvidenceTarget(net_id=LIVE_A).model_dump_json()))
    panel._value_edit.setText(str(value_v))
    panel._condition_edit.setText("full load")
    panel._source_edit.setText(source)


def test_the_add_button_records_what_the_form_describes(
    qtbot: QtBot, panel: VoltageEvidencePanel
) -> None:
    seen = _emitted(qtbot, panel)
    _fill(panel, APPROVED_V)

    panel._add_button.click()

    assert len(seen) == 1
    (stored,) = seen[0].voltage_evidence
    assert stored.value_v == APPROVED_V
    assert stored.approval_state is EvidenceApprovalState.DRAFT


def test_a_form_the_model_refuses_warns_and_records_nothing(
    qtbot: QtBot, panel: VoltageEvidencePanel, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "insulation_coordination.ui.voltage_evidence.QMessageBox.warning",
        lambda *args: warnings.append(str(args[2])),
    )
    seen = _emitted(qtbot, panel)
    _fill(panel, APPROVED_V)
    panel._source_edit.setText("")

    panel._add_button.click()

    assert seen == []
    assert warnings


def test_the_update_button_corrects_the_selected_draft(
    qtbot: QtBot, panel: VoltageEvidencePanel
) -> None:
    entry = _entry(APPROVED_V)
    panel.add_evidence(entry)
    panel.select_entry(entry.id)
    seen = _emitted(qtbot, panel)
    panel._value_edit.setText(str(DRAFT_V))

    panel._edit_button.click()

    assert len(seen) == 1
    (stored,) = seen[0].voltage_evidence
    assert stored.id == entry.id
    assert stored.value_v == DRAFT_V


def test_the_update_button_is_unavailable_once_an_entry_is_approved(
    panel: VoltageEvidencePanel,
) -> None:
    entry = _entry(APPROVED_V, state=EvidenceApprovalState.APPROVED_FOR_DESIGN)
    panel.add_evidence(entry)
    panel.select_entry(entry.id)

    assert not panel._edit_button.isEnabled()
    assert panel._revise_button.isEnabled()


def test_the_revision_button_asks_for_a_justification_and_keeps_the_original(
    qtbot: QtBot, panel: VoltageEvidencePanel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "insulation_coordination.ui.voltage_evidence.QInputDialog.getText",
        lambda *args, **kwargs: ("the model was re-run", True),
    )
    original = _entry(APPROVED_V, state=EvidenceApprovalState.APPROVED_FOR_DESIGN)
    panel.add_evidence(original)
    panel.select_entry(original.id)
    seen = _emitted(qtbot, panel)
    _fill(panel, DRAFT_V, source="SYN-EV-10")

    panel._revise_button.click()

    assert len(seen) == 1
    stored, added = seen[0].voltage_evidence
    assert stored.id == original.id
    assert stored.approval_justification == "the model was re-run"
    assert added.value_v == DRAFT_V


def test_the_delete_button_asks_before_anything_leaves(
    qtbot: QtBot, panel: VoltageEvidencePanel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answering no keeps the entry. Deletion is the only way anything leaves the library,
    so it is the one action that asks first."""

    asked: list[str] = []

    def _question(*args: object, **kwargs: object) -> QMessageBox.StandardButton:
        asked.append(str(args[2]))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(
        "insulation_coordination.ui.voltage_evidence.QMessageBox.question", _question
    )
    entry = _entry(APPROVED_V)
    panel.add_evidence(entry)
    panel.select_entry(entry.id)
    seen = _emitted(qtbot, panel)

    panel._delete_button.click()

    assert asked and "Superseding it instead" in asked[0]
    assert seen == []
    assert panel.row_count == 1
