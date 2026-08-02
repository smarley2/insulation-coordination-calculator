"""Human-readable labels shared by UI and report presentation code."""

from __future__ import annotations

from insulation_coordination.domain.project import PairCase, Project


def pair_label(project: Project, pair: PairCase) -> str:
    """Return the stable human label for a pair's two net classes."""
    names_by_id = {net_class.id: net_class.name for net_class in project.net_classes}
    return f"{names_by_id.get(pair.net_a, '?')} ↔ {names_by_id.get(pair.net_b, '?')}"
