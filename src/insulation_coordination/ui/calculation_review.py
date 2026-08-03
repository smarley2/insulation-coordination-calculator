"""Calculation review page: candidates, traces, warnings, groups."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.engine import PairResult
from insulation_coordination.domain.display import group_label, pair_label
from insulation_coordination.domain.project import Project


def titled_panel(title: str, body: QWidget) -> QWidget:
    """One labelled column of the lower Pairs-page row.

    Margins are zero so every column's heading and list line up across the
    splitter, whichever module builds the column.
    """
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel(title))
    layout.addWidget(body)
    return panel


class CalculationReviewPage(QWidget):
    """Shows calculation results, candidates, traces, and group membership."""

    def __init__(self) -> None:
        super().__init__()
        self._groups: tuple[object, ...] = ()
        self._results: tuple[PairResult, ...] = ()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._groups_list = QListWidget()
        self._results_list = QListWidget()
        self._review_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._review_splitter.setChildrenCollapsible(False)
        self._review_splitter.addWidget(titled_panel("Calculation Groups", self._groups_list))
        self._review_splitter.addWidget(titled_panel("Results", self._results_list))
        layout.addWidget(self._review_splitter)

    def balance_columns(self, total_width: int | None = None) -> None:
        """Give the group and result columns equal width.

        ``total_width`` is the width the page is about to receive; pass it when
        the enclosing splitter has just been resized and has not laid out yet.
        """
        half = max((total_width if total_width is not None else self.width()) // 2, 1)
        self._review_splitter.setSizes([half, half])

    @property
    def groups(self) -> tuple[object, ...]:
        return self._groups

    def load_project(self, project: Project) -> None:
        self._results = ()
        self._groups = ()
        self._results_list.clear()
        self._groups_list.clear()

    def update_results(self, results: tuple[PairResult, ...], project: Project) -> None:
        from insulation_coordination.calculation.grouping import group_results

        self._results = results
        try:
            splits = getattr(project, "group_splits", ())
            self._groups = group_results(results, splits)
        except (ValueError, RuntimeError, KeyError):
            self._groups = ()

        self._results_list.clear()
        self._groups_list.clear()

        nets_by_id = {}
        net_classes = getattr(project, "net_classes", ())
        for nc in net_classes:
            nets_by_id[nc.id] = nc.name

        for result in results:
            pair = next(
                (candidate for candidate in project.pairs if candidate.id == result.pair_id), None
            )
            label = pair_label(project, pair) if pair is not None else "? ↔ ?"
            item = QListWidgetItem(self._summarise(result, label))
            item.setToolTip(self._detail(result))
            self._results_list.addItem(item)

        for group_index, group in enumerate(self._groups, start=1):
            pair_ids = getattr(group, "pair_ids", ())
            item = QListWidgetItem(group_label(project, pair_ids, group_index))
            item.setToolTip(f"Internal group: {getattr(group, 'group_id', '?')}")
            self._groups_list.addItem(item)

    def recalculate_after_change(self, project: Project) -> None:
        """Recalculate from project + stored rules if available; else clear."""
        rules = getattr(project, "_rules", None)
        if rules is None:
            self.update_results((), project)
            return
        from insulation_coordination.calculation.engine import calculate_pair
        from insulation_coordination.project.resolver import resolve_effective_case

        pairs = getattr(project, "pairs", ())
        from insulation_coordination.domain.project import ProjectDefaults

        defaults = getattr(project, "defaults", None)
        if not isinstance(defaults, ProjectDefaults):
            self.update_results((), project)
            return
        valid: list[PairResult] = []
        for pair in pairs:
            try:
                valid.append(calculate_pair(resolve_effective_case(defaults, pair), rules))
            except (ValueError, RuntimeError, TypeError, KeyError):
                continue
        self.update_results(tuple(valid), project)

    def _summarise(self, result: PairResult, label: str) -> str:
        return f"{label}: clearance={result.clearance_mm} mm, creepage={result.creepage_mm} mm"

    def _detail(self, result: PairResult) -> str:
        lines: list[str] = []
        lines.append(f"Pair {result.pair_id}  [{result.pair_key}]")
        lines.append(f"Final clearance: {result.clearance_mm} mm")
        lines.append(f"Final creepage: {result.creepage_mm} mm")

        lines.append("")
        lines.append("Clearance candidates:")
        for c in result.trace.clearance_candidates:
            lines.append(
                f"  {c.candidate_id}: distance={c.distance_mm} mm, "
                f"stress={getattr(c.stress, 'value', '?')} {getattr(c.stress, 'unit', '?')}, "
                f"rule={c.semantic_rule_id}"
            )
            if getattr(c, "reason", None):
                lines.append(f"    reason: {c.reason}")
        lines.append(
            f"Governing clearance: {result.trace.governing_clearance_candidate_id} "
            f"({result.trace.governing_clearance_reason})"
        )
        if result.trace.altitude_correction_applied:
            lines.append(
                f"Altitude correction applied (pre-altitude {result.trace.pre_altitude_clearance_mm} mm)"
            )

        lines.append("")
        lines.append("Creepage candidates:")
        for c in result.trace.creepage_candidates:
            lines.append(
                f"  {c.candidate_id}: distance={c.distance_mm} mm, "
                f"stress={getattr(c.stress, 'value', '?')} {getattr(c.stress, 'unit', '?')}, "
                f"rule={c.semantic_rule_id}"
            )
            if getattr(c, "reason", None):
                lines.append(f"    reason: {c.reason}")
        lines.append(
            f"Governing creepage: {result.trace.governing_creepage_candidate_id} "
            f"({result.trace.governing_creepage_reason})"
        )

        lines.append("")
        lines.append("Trace steps:")
        for step in result.trace.steps:
            lines.append(f"  {step.semantic_rule_id} [{step.operation}]")
            if step.symbolic:
                lines.append(f"    symbolic: {step.symbolic}")
            if step.substituted:
                lines.append(f"    substituted: {step.substituted}")
            if step.reason:
                lines.append(f"    reason: {step.reason}")
            if step.source_reference:
                lines.append(f"    source: {_ref(step.source_reference)}")

        if result.warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in result.warnings:
                lines.append(f"  {w.code}: {w.message}")
        if result.verification_requirements:
            lines.append("")
            lines.append("Verification requirements:")
            for v in result.verification_requirements:
                lines.append(f"  {v.code}: {v.message}")
        return "\n".join(lines)


def _ref(source: object) -> str:
    parts = []
    for attr in ("standard", "edition", "clause", "table", "row", "column"):
        value = getattr(source, attr, None)
        if value:
            parts.append(f"{attr}={value}")
    return ", ".join(parts)
