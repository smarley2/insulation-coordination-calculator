"""The galvanic domain editor: pure project transformations plus a thin Qt panel.

Rule-level tests below construct and inspect ``Project`` values directly and need no Qt
event loop. Only the widget-structure and signal-wiring tests at the bottom use ``qtbot``.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from insulation_coordination.domain.enums import BarrierVerificationStatus
from insulation_coordination.domain.project import (
    NetClass,
    Project,
    ProjectDefaults,
    ProjectMetadata,
)
from insulation_coordination.domain.topology import GalvanicBarrier, GalvanicDomain
from insulation_coordination.ui.galvanic_domains import (
    DomainDeletionPreview,
    GalvanicDomainsPanel,
    add_domain,
    preview_domain_deletion,
    referencing_barriers,
    referencing_nets,
    remap_and_delete_domain,
    rename_domain,
    set_direct_domain,
    set_domain_description,
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


# --- add_domain ---------------------------------------------------------------------


def test_add_domain_to_an_empty_project_becomes_the_direct_source_domain() -> None:
    project = _project()
    updated = add_domain(project, "Primary side")
    (domain,) = updated.galvanic_domains
    assert domain.name == "Primary side"
    assert domain.is_direct_source_domain is True


def test_add_domain_after_the_first_is_not_direct_by_default() -> None:
    project = _project(galvanic_domains=(_domain(is_direct_source_domain=True),))
    updated = add_domain(project, "Secondary side")
    assert updated.galvanic_domains[1].is_direct_source_domain is False
    assert sum(d.is_direct_source_domain for d in updated.galvanic_domains) == 1


def test_add_domain_rejects_a_blank_name() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        add_domain(_project(), "   ")


def test_add_domain_rejects_a_duplicate_name_after_whitespace_and_case_normalisation() -> None:
    project = _project(galvanic_domains=(_domain(name="Primary side", is_direct_source_domain=True),))
    with pytest.raises(ValueError, match="already exists"):
        add_domain(project, "  PRIMARY SIDE  ")


def test_add_domain_result_passes_full_project_validation() -> None:
    project = _project()
    updated = add_domain(project, "Primary side", "The mains-connected side")
    revalidated = Project.model_validate(updated.model_dump(mode="python"))
    assert revalidated.galvanic_domains[0].description == "The mains-connected side"


# --- rename_domain -------------------------------------------------------------------


def test_rename_domain_preserves_the_uuid() -> None:
    domain = _domain(is_direct_source_domain=True)
    project = _project(galvanic_domains=(domain,))
    updated = rename_domain(project, domain.id, "New name")
    assert updated.galvanic_domains[0].id == domain.id
    assert updated.galvanic_domains[0].name == "New name"


def test_rename_domain_rejects_a_duplicate_name() -> None:
    domains = (
        _domain(id=UUID(int=1), name="A", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="B"),
    )
    project = _project(galvanic_domains=domains)
    with pytest.raises(ValueError, match="already exists"):
        rename_domain(project, domains[1].id, " a ")


def test_rename_domain_permits_keeping_its_own_name() -> None:
    domain = _domain(name="A", is_direct_source_domain=True)
    project = _project(galvanic_domains=(domain,))
    updated = rename_domain(project, domain.id, "A")
    assert updated.galvanic_domains[0].name == "A"


def test_rename_domain_rejects_a_blank_name() -> None:
    domain = _domain(is_direct_source_domain=True)
    project = _project(galvanic_domains=(domain,))
    with pytest.raises(ValueError, match="must not be empty"):
        rename_domain(project, domain.id, "  ")


def test_rename_domain_rejects_an_unknown_id() -> None:
    project = _project()
    with pytest.raises(ValueError, match="Unknown"):
        rename_domain(project, uuid4(), "Anything")


# --- set_domain_description -----------------------------------------------------------


def test_set_domain_description_updates_only_that_field() -> None:
    domain = _domain(is_direct_source_domain=True)
    project = _project(galvanic_domains=(domain,))
    updated = set_domain_description(project, domain.id, "New description")
    assert updated.galvanic_domains[0].description == "New description"
    assert updated.galvanic_domains[0].name == domain.name
    assert updated.galvanic_domains[0].id == domain.id


# --- set_direct_domain -----------------------------------------------------------------


def test_set_direct_domain_clears_the_previous_one_in_the_same_update() -> None:
    domains = (
        _domain(id=UUID(int=1), name="A", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="B"),
    )
    project = _project(galvanic_domains=domains)
    updated = set_direct_domain(project, domains[1].id)
    assert updated.galvanic_domains[0].is_direct_source_domain is False
    assert updated.galvanic_domains[1].is_direct_source_domain is True
    # Never transiently two directs: a full revalidation of the result confirms it.
    Project.model_validate(updated.model_dump(mode="python"))


def test_set_direct_domain_rejects_an_unknown_id() -> None:
    project = _project(galvanic_domains=(_domain(is_direct_source_domain=True),))
    with pytest.raises(ValueError, match="Unknown"):
        set_direct_domain(project, uuid4())


# --- referencing_nets / referencing_barriers --------------------------------------------


def test_referencing_nets_returns_only_nets_pointing_at_the_domain() -> None:
    domain = _domain(is_direct_source_domain=True)
    other = _domain(id=uuid4(), name="Other")
    net_in = _net(galvanic_domain_id=domain.id)
    net_out = _net(galvanic_domain_id=other.id)
    net_unset = _net(galvanic_domain_id=None)
    project = _project(
        net_classes=(net_in, net_out, net_unset), galvanic_domains=(domain, other)
    )
    assert referencing_nets(project, domain.id) == (net_in,)


def test_referencing_barriers_matches_either_side() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    barrier_ab = _barrier(domain_a_id=a, domain_b_id=b)
    barrier_cb = _barrier(domain_a_id=c, domain_b_id=b)
    domains = (
        _domain(id=a, name="A", is_direct_source_domain=True),
        _domain(id=b, name="B"),
        _domain(id=c, name="C"),
    )
    project = _project(galvanic_domains=domains, galvanic_barriers=(barrier_ab, barrier_cb))
    assert referencing_barriers(project, b) == (barrier_ab, barrier_cb)


# --- preview_domain_deletion -------------------------------------------------------------


def test_preview_lists_referencing_nets_and_the_chosen_replacement() -> None:
    domain = _domain(is_direct_source_domain=True)
    replacement = _domain(id=uuid4(), name="Secondary")
    net = _net(galvanic_domain_id=domain.id)
    project = _project(net_classes=(net,), galvanic_domains=(domain, replacement))

    preview = preview_domain_deletion(project, domain.id, replacement.id)

    assert isinstance(preview, DomainDeletionPreview)
    assert preview.domain == domain
    assert preview.replacement == replacement
    assert preview.nets == (net,)
    assert preview.remapped_barriers == ()
    assert preview.dropped_barriers == ()


def test_preview_requires_a_replacement_while_other_domains_remain() -> None:
    domains = (
        _domain(id=UUID(int=1), name="A", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="B"),
    )
    project = _project(galvanic_domains=domains)
    with pytest.raises(ValueError, match="replacement domain is required"):
        preview_domain_deletion(project, domains[0].id, None)


def test_preview_rejects_a_replacement_equal_to_the_deleted_domain() -> None:
    domain = _domain(is_direct_source_domain=True)
    project = _project(galvanic_domains=(domain,))
    with pytest.raises(ValueError, match="must differ"):
        preview_domain_deletion(project, domain.id, domain.id)


def test_preview_permits_no_replacement_when_it_is_the_only_domain() -> None:
    domain = _domain(is_direct_source_domain=True)
    project = _project(galvanic_domains=(domain,))
    preview = preview_domain_deletion(project, domain.id, None)
    assert preview.replacement is None


def test_preview_drops_a_barrier_that_would_become_a_self_loop() -> None:
    domain = _domain(id=UUID(int=1), name="A", is_direct_source_domain=True)
    replacement = _domain(id=UUID(int=2), name="B")
    barrier = _barrier(domain_a_id=domain.id, domain_b_id=replacement.id)
    project = _project(galvanic_domains=(domain, replacement), galvanic_barriers=(barrier,))

    preview = preview_domain_deletion(project, domain.id, replacement.id)

    assert preview.dropped_barriers == (barrier,)
    assert preview.remapped_barriers == ()


def test_preview_drops_a_barrier_that_would_duplicate_an_existing_pair() -> None:
    domain = _domain(id=UUID(int=1), name="A", is_direct_source_domain=True)
    replacement = _domain(id=UUID(int=2), name="B")
    third = _domain(id=UUID(int=3), name="C")
    stale = _barrier(id=UUID(int=100), domain_a_id=domain.id, domain_b_id=third.id)
    kept = _barrier(id=UUID(int=101), domain_a_id=replacement.id, domain_b_id=third.id)
    project = _project(
        galvanic_domains=(domain, replacement, third), galvanic_barriers=(stale, kept)
    )

    preview = preview_domain_deletion(project, domain.id, replacement.id)

    assert preview.dropped_barriers == (stale,)
    assert preview.remapped_barriers == ()


def test_preview_remaps_a_barrier_that_does_not_collide() -> None:
    domain = _domain(id=UUID(int=1), name="A", is_direct_source_domain=True)
    replacement = _domain(id=UUID(int=2), name="B")
    third = _domain(id=UUID(int=3), name="C")
    barrier = _barrier(domain_a_id=domain.id, domain_b_id=third.id)
    project = _project(
        galvanic_domains=(domain, replacement, third), galvanic_barriers=(barrier,)
    )

    preview = preview_domain_deletion(project, domain.id, replacement.id)

    assert preview.remapped_barriers == (barrier,)
    assert preview.dropped_barriers == ()


# --- remap_and_delete_domain -------------------------------------------------------------


def test_remap_and_delete_moves_referencing_nets_to_the_replacement() -> None:
    domain = _domain(is_direct_source_domain=True)
    replacement = _domain(id=uuid4(), name="Secondary")
    net = _net(galvanic_domain_id=domain.id)
    project = _project(net_classes=(net,), galvanic_domains=(domain, replacement))

    updated = remap_and_delete_domain(project, domain.id, replacement.id)

    assert updated.net_classes[0].galvanic_domain_id == replacement.id
    assert len(updated.galvanic_domains) == 1
    assert updated.galvanic_domains[0].id == replacement.id


def test_remap_and_delete_transfers_the_direct_flag_to_the_replacement() -> None:
    domain = _domain(is_direct_source_domain=True)
    replacement = _domain(id=uuid4(), name="Secondary")
    project = _project(galvanic_domains=(domain, replacement))

    updated = remap_and_delete_domain(project, domain.id, replacement.id)

    assert updated.galvanic_domains[0].is_direct_source_domain is True
    Project.model_validate(updated.model_dump(mode="python"))


def test_remap_and_delete_leaves_pairs_untouched() -> None:
    net_a, net_b = _net(name="A"), _net(name="B")
    from insulation_coordination.project.pairs import reconcile_pairs

    pairs = reconcile_pairs((net_a, net_b), ())
    domain = _domain(is_direct_source_domain=True)
    replacement = _domain(id=uuid4(), name="Secondary")
    project = _project(
        net_classes=(net_a, net_b), pairs=pairs, galvanic_domains=(domain, replacement)
    )

    updated = remap_and_delete_domain(project, domain.id, replacement.id)

    assert updated.pairs == pairs


def test_remap_and_delete_drops_a_colliding_barrier_and_keeps_the_kept_one() -> None:
    domain = _domain(id=UUID(int=1), name="A", is_direct_source_domain=True)
    replacement = _domain(id=UUID(int=2), name="B")
    third = _domain(id=UUID(int=3), name="C")
    stale = _barrier(id=UUID(int=100), domain_a_id=domain.id, domain_b_id=third.id)
    kept = _barrier(id=UUID(int=101), domain_a_id=replacement.id, domain_b_id=third.id)
    project = _project(
        galvanic_domains=(domain, replacement, third), galvanic_barriers=(stale, kept)
    )

    updated = remap_and_delete_domain(project, domain.id, replacement.id)

    assert updated.galvanic_barriers == (kept,)
    Project.model_validate(updated.model_dump(mode="python"))


def test_remap_and_delete_moves_a_non_colliding_barrier_to_the_replacement() -> None:
    domain = _domain(id=UUID(int=1), name="A", is_direct_source_domain=True)
    replacement = _domain(id=UUID(int=2), name="B")
    third = _domain(id=UUID(int=3), name="C")
    barrier = _barrier(domain_a_id=domain.id, domain_b_id=third.id)
    project = _project(
        galvanic_domains=(domain, replacement, third), galvanic_barriers=(barrier,)
    )

    updated = remap_and_delete_domain(project, domain.id, replacement.id)

    (moved,) = updated.galvanic_barriers
    assert {moved.domain_a_id, moved.domain_b_id} == {replacement.id, third.id}
    assert moved.id == barrier.id
    Project.model_validate(updated.model_dump(mode="python"))


def test_remap_and_delete_can_remove_the_only_domain_without_a_replacement() -> None:
    domain = _domain(is_direct_source_domain=True)
    net = _net(galvanic_domain_id=domain.id)
    project = _project(net_classes=(net,), galvanic_domains=(domain,))

    updated = remap_and_delete_domain(project, domain.id, None)

    assert updated.galvanic_domains == ()
    assert updated.net_classes[0].galvanic_domain_id is None
    Project.model_validate(updated.model_dump(mode="python"))


def test_remap_and_delete_on_nets_with_no_domain_reference_is_unaffected() -> None:
    domain = _domain(is_direct_source_domain=True)
    replacement = _domain(id=uuid4(), name="Secondary")
    unrelated = _net(galvanic_domain_id=None)
    project = _project(net_classes=(unrelated,), galvanic_domains=(domain, replacement))

    updated = remap_and_delete_domain(project, domain.id, replacement.id)

    assert updated.net_classes[0].galvanic_domain_id is None


# ==== Widget: GalvanicDomainsPanel (needs a Qt event loop) ====================================


@pytest.fixture
def panel(qtbot) -> GalvanicDomainsPanel:
    widget = GalvanicDomainsPanel()
    qtbot.addWidget(widget)
    return widget


def test_panel_lists_existing_domains_marking_the_direct_one(panel: GalvanicDomainsPanel) -> None:
    domains = (
        _domain(id=UUID(int=1), name="Primary side", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="Secondary side"),
    )
    panel.set_project(_project(galvanic_domains=domains))
    assert panel._list.count() == 2
    assert panel._list.item(0).text() == "Primary side (direct)"
    assert panel._list.item(1).text() == "Secondary side"


def test_panel_add_domain_emits_project_changed(panel: GalvanicDomainsPanel, qtbot) -> None:
    panel.set_project(_project())
    with qtbot.waitSignal(panel.project_changed, timeout=1000) as blocker:
        panel.add_domain("Primary side")
    (updated,) = blocker.args
    assert updated.galvanic_domains[0].name == "Primary side"
    assert panel._list.count() == 1


def test_panel_rename_domain_emits_project_changed(panel: GalvanicDomainsPanel, qtbot) -> None:
    domain = _domain(is_direct_source_domain=True)
    panel.set_project(_project(galvanic_domains=(domain,)))
    with qtbot.waitSignal(panel.project_changed, timeout=1000) as blocker:
        panel.rename_domain(domain.id, "New name")
    (updated,) = blocker.args
    assert updated.galvanic_domains[0].name == "New name"


def test_panel_selecting_a_domain_shows_its_description(panel: GalvanicDomainsPanel) -> None:
    domain = _domain(is_direct_source_domain=True, description="The mains side")
    panel.set_project(_project(galvanic_domains=(domain,)))
    panel._list.setCurrentRow(0)
    assert panel._description_edit.text() == "The mains side"


def test_panel_set_direct_domain_moves_the_marker(panel: GalvanicDomainsPanel, qtbot) -> None:
    domains = (
        _domain(id=UUID(int=1), name="A", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="B"),
    )
    panel.set_project(_project(galvanic_domains=domains))
    with qtbot.waitSignal(panel.project_changed, timeout=1000):
        panel.set_direct_domain(domains[1].id)
    assert panel._list.item(0).text() == "A"
    assert panel._list.item(1).text() == "B (direct)"


def test_panel_remap_and_delete_on_a_64_net_project_emits_exactly_one_update(
    panel: GalvanicDomainsPanel, qtbot
) -> None:
    domain = _domain(is_direct_source_domain=True)
    replacement = _domain(id=uuid4(), name="Secondary")
    nets = tuple(_net(name=f"N{i}", galvanic_domain_id=domain.id) for i in range(64))
    panel.set_project(_project(net_classes=nets, galvanic_domains=(domain, replacement)))

    received: list[object] = []
    panel.project_changed.connect(received.append)
    panel.remap_and_delete_domain(domain.id, replacement.id)

    assert len(received) == 1
    (updated,) = received
    assert all(net.galvanic_domain_id == replacement.id for net in updated.net_classes)
    assert len(updated.galvanic_domains) == 1
