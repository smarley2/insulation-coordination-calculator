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
    """Shows calculation results, group membership, and trace details."""

    def __init__(self) -> None:
        super().__init__()
        self._groups: tuple[object, ...] = ()
        self._results: tuple[object, ...] = ()

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
            pair_id = getattr(result, "pair_id", "?")
            clearance = getattr(result, "clearance_mm", "?")
            creepage = getattr(result, "creepage_mm", "?")
            label = f"{pair_id}: clearance={clearance} mm, creepage={creepage} mm"
            self._results_list.addItem(QListWidgetItem(label))

        for group in self._groups:
            group_id = getattr(group, "group_id", "?")
            pair_ids = getattr(group, "pair_ids", ())
            label = f"{group_id[:16]}… ({len(pair_ids)} pair{'s' if len(pair_ids) != 1 else ''})"
            self._groups_list.addItem(QListWidgetItem(label))
