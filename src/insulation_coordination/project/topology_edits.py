"""Galvanic-domain and barrier edits: another kind of project mutation, like ``pairs``.

Every function here takes a :class:`~insulation_coordination.domain.project.Project` and
returns a replacement one - never a widget, never Qt. They started out inside
``insulation_coordination.ui.galvanic_domains`` and ``insulation_coordination.ui.galvanic_barriers``
because the issue that introduced them named those file paths, but they hold no Qt of
their own, and non-UI code already needed them directly:
``tests/test_end_to_end.py`` calls :func:`rename_domain` to script a project edit outside
any panel. :mod:`insulation_coordination.project.pairs` is the precedent for what this
package is - the module that owns one kind of project mutation, reusable by whichever
panel, test, or future feature (a domain and barrier editor for a second topology view,
say) needs to make that edit without dragging in a widget tree.

The two panels this module used to live inside stay exactly as thin as before: each
imports the functions it needs from here, translates a dialog's answer into a call, and
emits the resulting project.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from insulation_coordination.domain.enums import BarrierVerificationStatus, VerificationMethod
from insulation_coordination.domain.project import NetClass, Project
from insulation_coordination.domain.topology import (
    GalvanicBarrier,
    GalvanicDomain,
    barrier_between,
    domain_by_id,
)

# --- galvanic domain edits -------------------------------------------------------------


def _normalised(name: str) -> str:
    return name.strip().casefold()


def _requires_unique_name(project: Project, name: str, *, except_id: UUID | None = None) -> None:
    normalised = _normalised(name)
    for domain in project.galvanic_domains:
        if domain.id == except_id:
            continue
        if _normalised(domain.name) == normalised:
            raise ValueError(f"A galvanic domain named '{name.strip()}' already exists")


def add_domain(project: Project, name: str, description: str = "") -> Project:
    """Append a new domain, becoming the direct source domain if it is the first one.

    A project with any domains must have exactly one direct source domain, so the very
    first domain added has nothing to inherit that flag from and must carry it itself.
    """
    name = name.strip()
    if not name:
        raise ValueError("Domain name must not be empty")
    _requires_unique_name(project, name)
    domain = GalvanicDomain(
        id=uuid4(),
        name=name,
        description=description.strip(),
        is_direct_source_domain=not project.galvanic_domains,
    )
    return project.model_copy(update={"galvanic_domains": (*project.galvanic_domains, domain)})


def rename_domain(project: Project, domain_id: UUID, new_name: str) -> Project:
    """Rename a domain, keeping its id - renaming is never a delete-and-recreate."""
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Domain name must not be empty")
    domain_by_id(project, domain_id)
    _requires_unique_name(project, new_name, except_id=domain_id)
    domains = tuple(
        domain.model_copy(update={"name": new_name}) if domain.id == domain_id else domain
        for domain in project.galvanic_domains
    )
    return project.model_copy(update={"galvanic_domains": domains})


def set_domain_description(project: Project, domain_id: UUID, description: str) -> Project:
    domain_by_id(project, domain_id)
    domains = tuple(
        domain.model_copy(update={"description": description.strip()})
        if domain.id == domain_id
        else domain
        for domain in project.galvanic_domains
    )
    return project.model_copy(update={"galvanic_domains": domains})


def set_direct_domain(project: Project, domain_id: UUID) -> Project:
    """Make ``domain_id`` the direct source domain, clearing whichever one held it before.

    Both edits land in the one ``model_copy`` call, so the project is never left - even
    transiently - holding two direct source domains or none.
    """
    domain_by_id(project, domain_id)
    domains = tuple(
        domain.model_copy(update={"is_direct_source_domain": domain.id == domain_id})
        for domain in project.galvanic_domains
    )
    return project.model_copy(update={"galvanic_domains": domains})


def referencing_nets(project: Project, domain_id: UUID) -> tuple[NetClass, ...]:
    """Every net currently assigned to ``domain_id``, in project order."""
    return tuple(net for net in project.net_classes if net.galvanic_domain_id == domain_id)


def referencing_barriers(project: Project, domain_id: UUID) -> tuple[GalvanicBarrier, ...]:
    """Every barrier that names ``domain_id`` on either side, in project order."""
    return tuple(
        barrier
        for barrier in project.galvanic_barriers
        if domain_id in (barrier.domain_a_id, barrier.domain_b_id)
    )


@dataclass(frozen=True)
class DomainDeletionPreview:
    """Everything a remap-and-delete would touch, computed before it is applied.

    ``dropped_barriers`` are referencing barriers that a remap would turn into either a
    self-loop (the other side was the replacement itself) or a duplicate of a barrier the
    replacement already has recorded against that same domain; neither can survive the
    project validator, so they are dropped rather than merged or reported as an error.
    """

    domain: GalvanicDomain
    replacement: GalvanicDomain | None
    nets: tuple[NetClass, ...]
    remapped_barriers: tuple[GalvanicBarrier, ...]
    dropped_barriers: tuple[GalvanicBarrier, ...]


def _resolve_replacement(
    project: Project, domain_id: UUID, replacement_id: UUID | None
) -> GalvanicDomain | None:
    if replacement_id is None:
        if len(project.galvanic_domains) > 1:
            raise ValueError("A replacement domain is required while other domains remain")
        return None
    if replacement_id == domain_id:
        raise ValueError("Replacement domain must differ from the domain being deleted")
    return domain_by_id(project, replacement_id)


def preview_domain_deletion(
    project: Project, domain_id: UUID, replacement_id: UUID | None
) -> DomainDeletionPreview:
    domain = domain_by_id(project, domain_id)
    replacement = _resolve_replacement(project, domain_id, replacement_id)
    barriers = referencing_barriers(project, domain_id)

    remapped: list[GalvanicBarrier] = []
    dropped: list[GalvanicBarrier] = []
    for barrier in barriers:
        other_id = barrier.domain_b_id if barrier.domain_a_id == domain_id else barrier.domain_a_id
        if replacement is None or other_id == replacement.id:
            # No replacement to move to, or the barrier is against the replacement itself -
            # remapping either side onto the other would self-loop, which is not a barrier.
            dropped.append(barrier)
            continue
        collides = any(
            b.id != barrier.id and {b.domain_a_id, b.domain_b_id} == {replacement.id, other_id}
            for b in project.galvanic_barriers
        )
        if collides:
            # The replacement already has a barrier recorded against this same domain.
            dropped.append(barrier)
        else:
            remapped.append(barrier)

    return DomainDeletionPreview(
        domain=domain,
        replacement=replacement,
        nets=referencing_nets(project, domain_id),
        remapped_barriers=tuple(remapped),
        dropped_barriers=tuple(dropped),
    )


def remap_and_delete_domain(
    project: Project, domain_id: UUID, replacement_id: UUID | None
) -> Project:
    """Delete ``domain_id``, moving every net and non-colliding barrier to the replacement.

    Applies as a single ``model_copy`` so the project only ever holds the fully-remapped
    state; pairs are untouched because a domain edit never changes which net classes exist.
    """
    preview = preview_domain_deletion(project, domain_id, replacement_id)
    replacement = preview.replacement
    replacement_domain_id = None if replacement is None else replacement.id

    net_classes = tuple(
        net.model_copy(update={"galvanic_domain_id": replacement_domain_id})
        if net.galvanic_domain_id == domain_id
        else net
        for net in project.net_classes
    )

    dropped_ids = {barrier.id for barrier in preview.dropped_barriers}
    remapped_ids = {barrier.id for barrier in preview.remapped_barriers}
    barriers = tuple(
        _remap_barrier(barrier, domain_id, replacement_domain_id)
        if barrier.id in remapped_ids
        else barrier
        for barrier in project.galvanic_barriers
        if barrier.id not in dropped_ids
    )

    domains: list[GalvanicDomain] = []
    for existing in project.galvanic_domains:
        if existing.id == domain_id:
            continue
        if (
            replacement is not None
            and existing.id == replacement.id
            and preview.domain.is_direct_source_domain
            and not existing.is_direct_source_domain
        ):
            existing = existing.model_copy(update={"is_direct_source_domain": True})
        domains.append(existing)

    return project.model_copy(
        update={
            "net_classes": net_classes,
            "galvanic_barriers": barriers,
            "galvanic_domains": tuple(domains),
        }
    )


def _remap_barrier(
    barrier: GalvanicBarrier, old_id: UUID, new_id: UUID | None
) -> GalvanicBarrier:
    if new_id is None:
        raise AssertionError("a remapped barrier always has a replacement domain")
    if barrier.domain_a_id == old_id:
        return barrier.model_copy(update={"domain_a_id": new_id})
    return barrier.model_copy(update={"domain_b_id": new_id})


# --- galvanic barrier edits --------------------------------------------------------------


def _barrier_by_id(project: Project, barrier_id: UUID) -> GalvanicBarrier:
    barrier = next((b for b in project.galvanic_barriers if b.id == barrier_id), None)
    if barrier is None:
        raise ValueError("Unknown galvanic barrier")
    return barrier


def _replace_barrier(project: Project, barrier_id: UUID, **updates: object) -> Project:
    """Rebuild one barrier through its constructor, so its own validator actually runs.

    ``model_copy`` would apply ``updates`` without checking the result, letting a
    verified status through with no evidence or a non-verified one with a stray method -
    both are exactly the states ``GalvanicBarrier`` exists to refuse.
    """
    barrier = _barrier_by_id(project, barrier_id)
    data = barrier.model_dump()
    data.update(updates)
    replacement = GalvanicBarrier(**data)
    barriers = tuple(
        replacement if existing.id == barrier_id else existing
        for existing in project.galvanic_barriers
    )
    return project.model_copy(update={"galvanic_barriers": barriers})


def add_barrier(
    project: Project, domain_a_id: UUID, domain_b_id: UUID, description: str = ""
) -> Project:
    """Record a new, not-yet-evaluated barrier between two domains.

    A-B and B-A are the same barrier: adding a second one for a pair that already has
    one recorded is refused rather than silently replacing or duplicating it.
    """
    domain_by_id(project, domain_a_id)
    domain_by_id(project, domain_b_id)
    if barrier_between(project, domain_a_id, domain_b_id) is not None:
        raise ValueError("A barrier already exists between these two domains")
    barrier = GalvanicBarrier(
        id=uuid4(),
        domain_a_id=domain_a_id,
        domain_b_id=domain_b_id,
        status=BarrierVerificationStatus.NOT_EVALUATED,
        description=description.strip(),
    )
    return project.model_copy(update={"galvanic_barriers": (*project.galvanic_barriers, barrier)})


def set_barrier_description(project: Project, barrier_id: UUID, description: str) -> Project:
    return _replace_barrier(project, barrier_id, description=description.strip())


def mark_verified(
    project: Project,
    barrier_id: UUID,
    verification_method: VerificationMethod | None,
    evidence_reference: str,
) -> Project:
    """Select verified galvanic isolation for a barrier, keeping its id.

    A missing method or a blank evidence reference is refused by
    ``GalvanicBarrier._requires_consistent_verification`` itself, with its own message -
    this function does not duplicate that check.
    """
    stripped = evidence_reference.strip()
    return _replace_barrier(
        project,
        barrier_id,
        status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
        verification_method=verification_method,
        evidence_reference=stripped or None,
    )


def unmark_verified(
    project: Project, barrier_id: UUID, new_status: BarrierVerificationStatus
) -> Project:
    """Move a barrier off verified isolation, clearing the fields only that status may carry.

    Restricted to the two non-verified statuses - the caller (the panel's uncheck dialog)
    always resolves to one of them, and this refuses anything else rather than silently
    accepting a wrong one.
    """
    if new_status is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION:
        raise ValueError("Use mark_verified to select verified isolation")
    return _replace_barrier(
        project,
        barrier_id,
        status=new_status,
        verification_method=None,
        evidence_reference=None,
    )


def delete_barrier(project: Project, barrier_id: UUID) -> Project:
    """Remove one barrier record, leaving every domain, net, and pair untouched.

    Deleting is not a remap: unlike a domain delete, a barrier has nothing on either
    side to reassign the record to. This exists for the barrier recorded against the
    wrong pair - the fix there is to remove it and add the correct one, not to have no
    way back short of deleting an entire domain.
    """
    _barrier_by_id(project, barrier_id)
    barriers = tuple(b for b in project.galvanic_barriers if b.id != barrier_id)
    return project.model_copy(update={"galvanic_barriers": barriers})


__all__ = [
    "DomainDeletionPreview",
    "add_barrier",
    "add_domain",
    "delete_barrier",
    "mark_verified",
    "preview_domain_deletion",
    "referencing_barriers",
    "referencing_nets",
    "remap_and_delete_domain",
    "rename_domain",
    "set_barrier_description",
    "set_direct_domain",
    "set_domain_description",
    "unmark_verified",
]
