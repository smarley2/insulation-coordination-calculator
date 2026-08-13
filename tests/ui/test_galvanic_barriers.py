"""The verified-barrier editor: pure project transformations plus a thin Qt panel.

Rule-level tests below construct and inspect ``Project`` values directly and need no Qt
event loop. Only the widget-structure and signal-wiring tests at the bottom use ``qtbot``.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from insulation_coordination.domain.enums import BarrierVerificationStatus, VerificationMethod
from insulation_coordination.domain.project import (
    NetClass,
    PairVoltage,
    Project,
    ProjectDefaults,
    ProjectMetadata,
)
from insulation_coordination.domain.topology import GalvanicBarrier, GalvanicDomain
from insulation_coordination.project.topology_edits import (
    add_barrier,
    delete_barrier,
    mark_verified,
    set_barrier_description,
    unmark_verified,
)
from insulation_coordination.ui.galvanic_barriers import (
    GalvanicBarriersPanel,
    _describe_barrier_deletion,
)


def _project(**overrides: object) -> Project:
    from insulation_coordination.project.pairs import reconcile_pairs

    fields: dict[str, object] = {
        "id": UUID(int=1000),
        "metadata": ProjectMetadata(title="Synthetic"),
        "application_version": "test",
        "defaults": ProjectDefaults(),
        "net_classes": (),
        "pairs": (),
    }
    fields.update(overrides)
    if "net_classes" in overrides and "pairs" not in overrides:
        net_classes = fields["net_classes"]
        assert isinstance(net_classes, tuple)
        fields["pairs"] = reconcile_pairs(net_classes, ())
    return Project(**fields)


def _domain(**overrides: object) -> GalvanicDomain:
    fields: dict[str, object] = {"id": uuid4(), "name": "Domain A"}
    fields.update(overrides)
    return GalvanicDomain(**fields)


def _barrier(**overrides: object) -> GalvanicBarrier:
    fields: dict[str, object] = {
        "id": uuid4(),
        "domain_a_id": uuid4(),
        "domain_b_id": uuid4(),
        "status": BarrierVerificationStatus.NOT_EVALUATED,
        "description": "Synthetic barrier",
    }
    fields.update(overrides)
    return GalvanicBarrier(**fields)


def _net(**overrides: object) -> NetClass:
    fields: dict[str, object] = {"id": uuid4(), "name": f"Net-{uuid4()}"}
    fields.update(overrides)
    return NetClass(**fields)


# --- add_barrier ----------------------------------------------------------------------


def test_add_barrier_defaults_to_not_evaluated_with_no_evidence() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    project = _project(galvanic_domains=(a, b))
    updated = add_barrier(project, a.id, b.id, "The isolation transformer")
    (barrier,) = updated.galvanic_barriers
    assert barrier.status is BarrierVerificationStatus.NOT_EVALUATED
    assert barrier.verification_method is None
    assert barrier.evidence_reference is None
    assert barrier.description == "The isolation transformer"


def test_add_barrier_rejects_a_second_barrier_for_the_same_unordered_pair() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    existing = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = _project(galvanic_domains=(a, b), galvanic_barriers=(existing,))
    with pytest.raises(ValueError, match="already exists"):
        add_barrier(project, b.id, a.id)


def test_add_barrier_rejects_the_same_domain_on_both_sides() -> None:
    a = _domain(is_direct_source_domain=True)
    project = _project(galvanic_domains=(a,))
    with pytest.raises(ValueError, match="different domains"):
        add_barrier(project, a.id, a.id)


def test_add_barrier_rejects_an_unknown_domain() -> None:
    a = _domain(is_direct_source_domain=True)
    project = _project(galvanic_domains=(a,))
    with pytest.raises(ValueError, match="Unknown"):
        add_barrier(project, a.id, uuid4())


def test_add_barrier_result_passes_full_project_validation() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    project = _project(galvanic_domains=(a, b))
    updated = add_barrier(project, a.id, b.id)
    Project.model_validate(updated.model_dump(mode="python"))


# --- set_barrier_description ------------------------------------------------------------


def test_set_barrier_description_updates_only_that_field() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = _project(galvanic_domains=(a, b), galvanic_barriers=(barrier,))
    updated = set_barrier_description(project, barrier.id, "New description")
    (result,) = updated.galvanic_barriers
    assert result.description == "New description"
    assert result.id == barrier.id
    assert result.status == barrier.status


def test_set_barrier_description_rejects_an_unknown_id() -> None:
    project = _project()
    with pytest.raises(ValueError, match="Unknown"):
        set_barrier_description(project, uuid4(), "x")


# --- mark_verified ----------------------------------------------------------------------


def test_mark_verified_requires_a_non_blank_evidence_reference() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = _project(galvanic_domains=(a, b), galvanic_barriers=(barrier,))
    with pytest.raises(ValueError, match="requires a verification method and an evidence"):
        mark_verified(project, barrier.id, VerificationMethod.TEST, "   ")


def test_mark_verified_requires_a_verification_method() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = _project(galvanic_domains=(a, b), galvanic_barriers=(barrier,))
    with pytest.raises(ValueError, match="requires a verification method and an evidence"):
        mark_verified(project, barrier.id, None, "Test report TR-001")


def test_mark_verified_sets_status_method_and_evidence_and_keeps_the_id() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = _project(galvanic_domains=(a, b), galvanic_barriers=(barrier,))
    updated = mark_verified(project, barrier.id, VerificationMethod.TEST, "  TR-001  ")
    (result,) = updated.galvanic_barriers
    assert result.id == barrier.id
    assert result.status is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION
    assert result.verification_method is VerificationMethod.TEST
    assert result.evidence_reference == "TR-001"
    Project.model_validate(updated.model_dump(mode="python"))


def test_mark_verified_leaves_every_pair_voltage_and_insulation_selection_unchanged() -> None:
    net_a, net_b = _net(name="A"), _net(name="B")
    from insulation_coordination.project.pairs import reconcile_pairs

    pairs = reconcile_pairs((net_a, net_b), ())
    pairs = (
        pairs[0].model_copy(
            update={
                "voltages": pairs[0].voltages.model_copy(
                    update={"long_term_rms_v": PairVoltage.applicable(Decimal(12))}
                )
            }
        ),
    )
    domain = _domain(is_direct_source_domain=True)
    barrier = _barrier(domain_a_id=domain.id, domain_b_id=uuid4())
    other = _domain(id=barrier.domain_b_id, name="B")
    project = _project(
        net_classes=(net_a, net_b),
        pairs=pairs,
        galvanic_domains=(domain, other),
        galvanic_barriers=(barrier,),
    )

    updated = mark_verified(project, barrier.id, VerificationMethod.TEST, "TR-001")

    assert updated.pairs == pairs
    assert updated.net_classes == (net_a, net_b)


def test_mark_verified_rejects_an_unknown_barrier_id() -> None:
    project = _project()
    with pytest.raises(ValueError, match="Unknown"):
        mark_verified(project, uuid4(), VerificationMethod.TEST, "TR-001")


# --- unmark_verified --------------------------------------------------------------------


def test_unmark_verified_to_not_evaluated_clears_method_and_evidence() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    barrier = _barrier(
        domain_a_id=a.id,
        domain_b_id=b.id,
        status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
        verification_method=VerificationMethod.TEST,
        evidence_reference="TR-001",
    )
    project = _project(galvanic_domains=(a, b), galvanic_barriers=(barrier,))
    updated = unmark_verified(project, barrier.id, BarrierVerificationStatus.NOT_EVALUATED)
    (result,) = updated.galvanic_barriers
    assert result.id == barrier.id
    assert result.status is BarrierVerificationStatus.NOT_EVALUATED
    assert result.verification_method is None
    assert result.evidence_reference is None


def test_unmark_verified_to_no_isolation_clears_method_and_evidence() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    barrier = _barrier(
        domain_a_id=a.id,
        domain_b_id=b.id,
        status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
        verification_method=VerificationMethod.TEST,
        evidence_reference="TR-001",
    )
    project = _project(galvanic_domains=(a, b), galvanic_barriers=(barrier,))
    updated = unmark_verified(project, barrier.id, BarrierVerificationStatus.NO_GALVANIC_ISOLATION)
    (result,) = updated.galvanic_barriers
    assert result.status is BarrierVerificationStatus.NO_GALVANIC_ISOLATION
    assert result.verification_method is None
    assert result.evidence_reference is None


def test_unmark_verified_refuses_verified_as_the_target_status() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = _project(galvanic_domains=(a, b), galvanic_barriers=(barrier,))
    with pytest.raises(ValueError, match="mark_verified"):
        unmark_verified(project, barrier.id, BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION)


# --- delete_barrier --------------------------------------------------------------------


def test_delete_barrier_removes_only_the_named_barrier() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    c = _domain(id=UUID(int=3), name="C")
    kept = _barrier(domain_a_id=a.id, domain_b_id=c.id)
    target = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = _project(galvanic_domains=(a, b, c), galvanic_barriers=(kept, target))

    updated = delete_barrier(project, target.id)

    assert updated.galvanic_barriers == (kept,)


def test_delete_barrier_leaves_pairs_and_nets_untouched() -> None:
    net_a, net_b = _net(name="A"), _net(name="B")
    from insulation_coordination.project.pairs import reconcile_pairs

    pairs = reconcile_pairs((net_a, net_b), ())
    domain = _domain(is_direct_source_domain=True)
    barrier = _barrier(domain_a_id=domain.id, domain_b_id=uuid4())
    other = _domain(id=barrier.domain_b_id, name="B")
    project = _project(
        net_classes=(net_a, net_b),
        pairs=pairs,
        galvanic_domains=(domain, other),
        galvanic_barriers=(barrier,),
    )

    updated = delete_barrier(project, barrier.id)

    assert updated.pairs == pairs
    assert updated.net_classes == (net_a, net_b)
    assert updated.galvanic_domains == (domain, other)


def test_delete_barrier_rejects_an_unknown_id() -> None:
    project = _project()
    with pytest.raises(ValueError, match="Unknown"):
        delete_barrier(project, uuid4())


# --- _describe_barrier_deletion ----------------------------------------------------------


def test_describe_barrier_deletion_names_both_domains() -> None:
    a = _domain(id=UUID(int=1), name="Primary", is_direct_source_domain=True)
    b = _domain(id=UUID(int=2), name="Secondary")
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = _project(galvanic_domains=(a, b), galvanic_barriers=(barrier,))

    description = _describe_barrier_deletion(barrier, project)

    assert "Primary" in description
    assert "Secondary" in description
    assert "verified" not in description.lower()


def test_describe_barrier_deletion_flags_a_verified_isolation_record() -> None:
    a = _domain(id=UUID(int=1), name="Primary", is_direct_source_domain=True)
    b = _domain(id=UUID(int=2), name="Secondary")
    barrier = _barrier(
        domain_a_id=a.id,
        domain_b_id=b.id,
        status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
        verification_method=VerificationMethod.TEST,
        evidence_reference="TR-001",
    )
    project = _project(galvanic_domains=(a, b), galvanic_barriers=(barrier,))

    description = _describe_barrier_deletion(barrier, project)

    assert "verified galvanic isolation" in description.lower()


# --- stable ids across every edit --------------------------------------------------------


def test_barrier_id_is_stable_across_add_mark_and_unmark() -> None:
    a, b = _domain(id=UUID(int=1), is_direct_source_domain=True), _domain(id=UUID(int=2), name="B")
    project = _project(galvanic_domains=(a, b))

    project = add_barrier(project, a.id, b.id)
    (barrier,) = project.galvanic_barriers
    barrier_id = barrier.id

    project = mark_verified(project, barrier_id, VerificationMethod.TEST, "TR-001")
    assert project.galvanic_barriers[0].id == barrier_id

    project = unmark_verified(project, barrier_id, BarrierVerificationStatus.NOT_EVALUATED)
    assert project.galvanic_barriers[0].id == barrier_id

    project = set_barrier_description(project, barrier_id, "Updated")
    assert project.galvanic_barriers[0].id == barrier_id


# ==== Widget: GalvanicBarriersPanel (needs a Qt event loop) ===============================


@pytest.fixture
def panel(qtbot) -> GalvanicBarriersPanel:
    widget = GalvanicBarriersPanel()
    qtbot.addWidget(widget)
    return widget


def _two_domain_project(**overrides: object) -> tuple[Project, GalvanicDomain, GalvanicDomain]:
    a = _domain(id=UUID(int=1), name="Primary", is_direct_source_domain=True)
    b = _domain(id=UUID(int=2), name="Secondary")
    project = _project(galvanic_domains=(a, b), **overrides)
    return project, a, b


def test_panel_lists_existing_barriers_by_domain_name(panel: GalvanicBarriersPanel) -> None:
    project, a, b = _two_domain_project()
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id, description="Main transformer")
    project = project.model_copy(update={"galvanic_barriers": (barrier,)})
    panel.set_project(project)
    assert panel._table.rowCount() == 1
    assert panel._table.item(0, 0).text() == "Primary"
    assert panel._table.item(0, 1).text() == "Secondary"
    assert panel._table.item(0, 5).text() == "Main transformer"


def test_panel_add_barrier_emits_project_changed(panel: GalvanicBarriersPanel, qtbot) -> None:
    project, a, b = _two_domain_project()
    panel.set_project(project)
    with qtbot.waitSignal(panel.project_changed, timeout=1000) as blocker:
        panel.add_barrier(a.id, b.id)
    (updated,) = blocker.args
    assert len(updated.galvanic_barriers) == 1
    assert panel._table.rowCount() == 1


def test_panel_add_barrier_for_an_existing_pair_raises(panel: GalvanicBarriersPanel) -> None:
    project, a, b = _two_domain_project()
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = project.model_copy(update={"galvanic_barriers": (barrier,)})
    panel.set_project(project)
    with pytest.raises(ValueError, match="already exists"):
        panel.add_barrier(b.id, a.id)


def test_panel_mark_verified_emits_project_changed(panel: GalvanicBarriersPanel, qtbot) -> None:
    project, a, b = _two_domain_project()
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = project.model_copy(update={"galvanic_barriers": (barrier,)})
    panel.set_project(project)
    with qtbot.waitSignal(panel.project_changed, timeout=1000) as blocker:
        panel.mark_verified(barrier.id, VerificationMethod.TEST, "TR-001")
    (updated,) = blocker.args
    assert (
        updated.galvanic_barriers[0].status is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION
    )


def test_panel_selecting_a_row_shows_its_fields(panel: GalvanicBarriersPanel) -> None:
    project, a, b = _two_domain_project()
    barrier = _barrier(
        domain_a_id=a.id,
        domain_b_id=b.id,
        status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
        verification_method=VerificationMethod.TEST,
        evidence_reference="TR-001",
        description="Main transformer",
    )
    project = project.model_copy(update={"galvanic_barriers": (barrier,)})
    panel.set_project(project)
    panel._table.setCurrentCell(0, 0)
    assert panel._description_edit.text() == "Main transformer"
    assert panel._verified_checkbox.isChecked() is True
    assert panel._evidence_edit.text() == "TR-001"


def test_checking_verified_without_evidence_is_refused_and_reverts(
    panel: GalvanicBarriersPanel, qtbot, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    project, a, b = _two_domain_project()
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = project.model_copy(update={"galvanic_barriers": (barrier,)})
    panel.set_project(project)
    panel._table.setCurrentCell(0, 0)

    panel._verified_checkbox.setChecked(True)

    assert panel._verified_checkbox.isChecked() is False
    assert panel.project.galvanic_barriers[0].status is BarrierVerificationStatus.NOT_EVALUATED


def test_unchecking_verified_applies_the_chosen_state(
    panel: GalvanicBarriersPanel, qtbot, monkeypatch
) -> None:
    project, a, b = _two_domain_project()
    barrier = _barrier(
        domain_a_id=a.id,
        domain_b_id=b.id,
        status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
        verification_method=VerificationMethod.TEST,
        evidence_reference="TR-001",
    )
    project = project.model_copy(update={"galvanic_barriers": (barrier,)})
    panel.set_project(project)
    panel._table.setCurrentCell(0, 0)
    monkeypatch.setattr(
        panel,
        "_ask_unverified_state",
        lambda barrier: BarrierVerificationStatus.NO_GALVANIC_ISOLATION,
    )

    panel._verified_checkbox.setChecked(False)

    assert (
        panel.project.galvanic_barriers[0].status is BarrierVerificationStatus.NO_GALVANIC_ISOLATION
    )
    assert panel.project.galvanic_barriers[0].evidence_reference is None


def test_panel_delete_confirmed_removes_the_barrier(
    panel: GalvanicBarriersPanel, qtbot, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    project, a, b = _two_domain_project()
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = project.model_copy(update={"galvanic_barriers": (barrier,)})
    panel.set_project(project)
    panel._table.setCurrentCell(0, 0)

    with qtbot.waitSignal(panel.project_changed, timeout=1000) as blocker:
        panel._on_delete_clicked()
    (updated,) = blocker.args
    assert updated.galvanic_barriers == ()
    assert panel._table.rowCount() == 0


def test_panel_delete_cancelled_leaves_the_project_untouched(
    panel: GalvanicBarriersPanel, qtbot, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    project, a, b = _two_domain_project()
    barrier = _barrier(domain_a_id=a.id, domain_b_id=b.id)
    project = project.model_copy(update={"galvanic_barriers": (barrier,)})
    panel.set_project(project)
    panel._table.setCurrentCell(0, 0)

    received: list[object] = []
    panel.project_changed.connect(received.append)
    panel._on_delete_clicked()

    assert received == []
    assert panel.project.galvanic_barriers == (barrier,)
    assert panel._table.rowCount() == 1


def test_unchecking_verified_cancel_leaves_the_project_untouched(
    panel: GalvanicBarriersPanel, qtbot, monkeypatch
) -> None:
    project, a, b = _two_domain_project()
    barrier = _barrier(
        domain_a_id=a.id,
        domain_b_id=b.id,
        status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
        verification_method=VerificationMethod.TEST,
        evidence_reference="TR-001",
    )
    project = project.model_copy(update={"galvanic_barriers": (barrier,)})
    panel.set_project(project)
    panel._table.setCurrentCell(0, 0)
    monkeypatch.setattr(panel, "_ask_unverified_state", lambda barrier: None)

    received: list[object] = []
    panel.project_changed.connect(received.append)
    panel._verified_checkbox.setChecked(False)

    assert received == []
    assert (
        panel.project.galvanic_barriers[0].status
        is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION
    )
    assert panel._verified_checkbox.isChecked() is True
