"""Calculation review page: candidates, traces, warnings, groups."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.engine import PairResult


class CalculationReviewPage(QWidget):
    """Shows calculation results, candidates, traces, and group membership."""

    def __init__(self) -> None:
        super().__init__()
        self._groups: tuple[object, ...] = ()
        self._results: tuple[PairResult, ...] = ()

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Calculation Groups"))
        self._groups_list = QListWidget()
        layout.addWidget(self._groups_list)

        layout.addWidget(QLabel("Results"))
        self._results_list = QListWidget()
        layout.addWidget(self._results_list)

    @property
    def groups(self) -> tuple[object, ...]:
        return self._groups

    def load_project(self, project: object) -> None:
        self._results = ()
        self._groups = ()
        self._results_list.clear()
        self._groups_list.clear()

    def update_results(self, results: tuple[PairResult, ...], project: object) -> None:
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
            item = QListWidgetItem(self._summarise(result))
            item.setToolTip(self._detail(result))
            self._results_list.addItem(item)

        for group in self._groups:
            group_id = getattr(group, "group_id", "?")
            pair_ids = getattr(group, "pair_ids", ())
            label = f"{group_id[:16]}… ({len(pair_ids)} pair{'s' if len(pair_ids) != 1 else ''})"
            self._groups_list.addItem(QListWidgetItem(label))

    def recalculate_after_change(self, project: object) -> None:
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

    def _summarise(self, result: PairResult) -> str:
        pair_id = str(result.pair_id)
        return f"{pair_id}: clearance={result.clearance_mm} mm, creepage={result.creepage_mm} mm"

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
