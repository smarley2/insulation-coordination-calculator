from __future__ import annotations

from typing import cast
from uuid import UUID

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from insulation_coordination.domain.project import PairCase, Project


class CoverageMatrixModel(QAbstractTableModel):
    """Square net-class × net-class matrix; lower half mirrors upper half."""

    def __init__(self) -> None:
        super().__init__()
        self._project: Project | None = None
        self._pairs_by_net: dict[tuple[UUID, UUID], PairCase] = {}

    def load_project(self, project: Project) -> None:
        self.beginResetModel()
        self._project = project
        self._pairs_by_net = {}
        for pair in project.pairs:
            key = cast(tuple[UUID, UUID], tuple(sorted((pair.net_a, pair.net_b))))
            self._pairs_by_net[key] = pair
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        if self._project is None or (parent is not None and parent.isValid()):
            return 0
        return len(self._project.net_classes)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        if self._project is None or (parent is not None and parent.isValid()):
            return 0
        return len(self._project.net_classes)

    def pair_at(self, row: int, col: int) -> PairCase | None:
        if self._project is None:
            return None
        nets = self._project.net_classes
        if row == col or row < 0 or col < 0 or row >= len(nets) or col >= len(nets):
            return None
        key = cast(tuple[UUID, UUID], tuple(sorted((nets[row].id, nets[col].id))))
        return self._pairs_by_net.get(key)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> str | None:  # type: ignore[override]
        if not index.isValid() or self._project is None:
            return None
        row, col = index.row(), index.column()
        nets = self._project.net_classes
        if role == Qt.ItemDataRole.DisplayRole:
            if row == col:
                return nets[row].name
            pair = self.pair_at(row, col)
            if pair is not None:
                return "✓"
            return ""
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        if self._project is None or role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and section < len(self._project.net_classes):
            return self._project.net_classes[section].name
        if orientation == Qt.Orientation.Vertical and section < len(self._project.net_classes):
            return self._project.net_classes[section].name
        return None


class PairListModel(QAbstractTableModel):
    """Flat pair list showing net names and calculation status."""

    _columns = ("Pair", "Status")

    def __init__(self) -> None:
        super().__init__()
        self._project: Project | None = None
        self._pair_labels: list[str] = []
        self._statuses: list[str] = []

    def load_project(self, project: Project, statuses: dict[str, str] | None = None) -> None:
        self.beginResetModel()
        self._project = project
        self._pair_labels = []
        self._statuses = []
        nets_by_id = {nc.id: nc.name for nc in project.net_classes}
        for pair in project.pairs:
            name_a = nets_by_id.get(pair.net_a, "?")
            name_b = nets_by_id.get(pair.net_b, "?")
            self._pair_labels.append(f"{name_a} ↔ {name_b}")
            self._statuses.append((statuses or {}).get(str(pair.id), "—"))
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        if self._project is None or (parent is not None and parent.isValid()):
            return 0
        return len(self._project.pairs)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> str | None:  # type: ignore[override]
        if not index.isValid() or self._project is None:
            return None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        row, col = index.row(), index.column()
        if col == 0:
            return self._pair_labels[row]
        if col == 1:
            return self._statuses[row]
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and section < len(self._columns):
            return self._columns[section]
        return None
