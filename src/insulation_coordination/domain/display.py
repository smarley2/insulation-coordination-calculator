"""Human-readable labels shared by UI and report presentation code."""

from __future__ import annotations

from collections.abc import Sequence

from insulation_coordination.domain.project import PairCase, Project


def pair_label(project: Project, pair: PairCase) -> str:
    """Return the stable human label for a pair's two net classes."""
    names_by_id = {net_class.id: net_class.name for net_class in project.net_classes}
    return f"{names_by_id.get(pair.net_a, '?')} ↔ {names_by_id.get(pair.net_b, '?')}"


def group_label(project: Project, pair_ids: Sequence[object], index: int) -> str:
    """Return the human label for one calculation group, without internal identifiers."""
    pairs_by_id = {str(pair.id): pair for pair in project.pairs}
    members = ", ".join(
        pair_label(project, pairs_by_id[str(pair_id)])
        for pair_id in pair_ids
        if str(pair_id) in pairs_by_id
    )
    count = len(pair_ids)
    label = f"Group {index} — {count} pair{'s' if count != 1 else ''}"
    return f"{label}: {members}" if members else label
