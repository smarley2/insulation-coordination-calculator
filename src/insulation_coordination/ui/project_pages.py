"""Project setup page: metadata, defaults, and net-class editing."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
    NetClass,
    Project,
    ProjectDefaults,
)
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.project.pairs import reconcile_pairs
from insulation_coordination.project.persistence import (
    ProjectLoadError,
    load_project,
    save_project_atomic,
)

_IMPULSE_OPTIONS = (
    ("0.33 kV", Decimal(330)),
    ("0.40 kV", Decimal(400)),
    ("0.50 kV", Decimal(500)),
    ("0.60 kV", Decimal(600)),
    ("0.80 kV", Decimal(800)),
    ("1.0 kV", Decimal(1000)),
    ("1.2 kV", Decimal(1200)),
    ("1.5 kV", Decimal(1500)),
    ("2.0 kV", Decimal(2000)),
    ("2.5 kV", Decimal(2500)),
    ("3.0 kV", Decimal(3000)),
    ("4.0 kV", Decimal(4000)),
    ("5.0 kV", Decimal(5000)),
    ("6.0 kV", Decimal(6000)),
    ("8.0 kV", Decimal(8000)),
    ("10 kV", Decimal(10000)),
    ("12 kV", Decimal(12000)),
    ("15 kV", Decimal(15000)),
    ("20 kV", Decimal(20000)),
    ("25 kV", Decimal(25000)),
    ("30 kV", Decimal(30000)),
    ("40 kV", Decimal(40000)),
    ("50 kV", Decimal(50000)),
    ("60 kV", Decimal(60000)),
    ("80 kV", Decimal(80000)),
    ("100 kV", Decimal(100000)),
)
_POLLUTION_OPTIONS = (("1", 1), ("2", 2))
_MATERIAL_OPTIONS = (("I", "I"), ("II", "II"), ("IIIa", "IIIa"), ("IIIb", "IIIb"))


class ProjectPage(QWidget):
    """Project metadata, defaults, and net-class editing page."""

    project_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._project: Project | None = None
        self._dirty = False

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)

        title_label = QLabel("Project")
        title_label.setStyleSheet("font-weight: bold; font-size: 14pt;")
        layout.addWidget(title_label)

        meta_group = QGroupBox("Project metadata")
        meta_layout = QFormLayout(meta_group)
        self._title_edit = QLineEdit()
        self._title_edit.textChanged.connect(self._on_title_changed)
        meta_layout.addRow("Title:", self._title_edit)
        self._customer_edit = QLineEdit()
        self._customer_edit.textChanged.connect(self._on_customer_changed)
        meta_layout.addRow("Customer:", self._customer_edit)
        self._doc_edit = QLineEdit()
        self._doc_edit.textChanged.connect(self._on_doc_changed)
        meta_layout.addRow("Document number:", self._doc_edit)
        self._revision_edit = QLineEdit()
        self._revision_edit.textChanged.connect(self._on_revision_changed)
        meta_layout.addRow("Revision:", self._revision_edit)
        defaults_group = QGroupBox("Project defaults")
        defaults_layout = QFormLayout(defaults_group)
        self._freq_edit = QLineEdit()
        self._freq_edit.editingFinished.connect(self._on_freq_changed)
        defaults_layout.addRow("Frequency (Hz):", self._freq_edit)
        self._impulse_combo = QComboBox()
        self._populate_combo(self._impulse_combo, _IMPULSE_OPTIONS)
        self._impulse_combo.currentIndexChanged.connect(
            lambda index: self._update_combo_default("impulse_v", self._impulse_combo, index)
        )
        defaults_layout.addRow("Impulse:", self._impulse_combo)
        self._insulation_combo = QComboBox()
        self._insulation_combo.addItem("")
        for insulation in InsulationType:
            self._insulation_combo.addItem(insulation.value)
        self._insulation_combo.currentTextChanged.connect(self._on_insulation_changed)
        defaults_layout.addRow("Insulation type:", self._insulation_combo)
        self._field_combo = QComboBox()
        self._field_combo.addItem("")
        for field in FieldCondition:
            self._field_combo.addItem(field.value)
        self._field_combo.currentTextChanged.connect(self._on_field_changed)
        defaults_layout.addRow("Field condition:", self._field_combo)
        self._altitude_edit = QLineEdit()
        self._altitude_edit.editingFinished.connect(self._on_altitude_changed)
        defaults_layout.addRow("Altitude (m):", self._altitude_edit)
        self._pollution_combo = QComboBox()
        self._populate_combo(self._pollution_combo, _POLLUTION_OPTIONS)
        self._pollution_combo.currentIndexChanged.connect(
            lambda index: self._update_combo_default("pollution_degree", self._pollution_combo, index)
        )
        defaults_layout.addRow("Pollution degree:", self._pollution_combo)
        self._construction_combo = QComboBox()
        self._construction_combo.addItem("")
        for construction in ConstructionType:
            self._construction_combo.addItem(construction.value)
        self._construction_combo.currentTextChanged.connect(self._on_construction_changed)
        defaults_layout.addRow("Construction:", self._construction_combo)
        self._cti_combo = QComboBox()
        self._populate_combo(self._cti_combo, _MATERIAL_OPTIONS)
        self._cti_combo.currentIndexChanged.connect(
            lambda index: self._update_combo_default(
                "cti_or_material_group", self._cti_combo, index
            )
        )
        defaults_layout.addRow("CTI / material group:", self._cti_combo)
        project_columns = QHBoxLayout()
        project_columns.addWidget(meta_group, 1)
        project_columns.addWidget(defaults_group, 1)
        layout.addLayout(project_columns)

        rules_layout = QHBoxLayout()
        rules_layout.addWidget(QLabel("Rules package:"))
        self._rules_label = QLabel("(none)")
        rules_layout.addWidget(self._rules_label, 1)
        layout.addLayout(rules_layout)

        net_group = QGroupBox("Net classes")
        net_layout = QHBoxLayout(net_group)
        self._net_list = QListWidget()
        net_layout.addWidget(self._net_list, 1)

        net_controls = QVBoxLayout()
        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText("Selected net description")
        self._description_edit.editingFinished.connect(self._on_description_changed)
        net_controls.addWidget(self._description_edit)

        self._add_button = QPushButton("Add")
        self._add_button.clicked.connect(self._on_add_clicked)
        net_controls.addWidget(self._add_button)
        self._rename_button = QPushButton("Rename")
        self._rename_button.clicked.connect(self._on_rename_clicked)
        net_controls.addWidget(self._rename_button)
        self._delete_button = QPushButton("Delete")
        self._delete_button.clicked.connect(self._on_delete_clicked)
        net_controls.addWidget(self._delete_button)
        net_controls.addStretch(1)
        net_layout.addLayout(net_controls)
        layout.addWidget(net_group)

        self._net_list.currentRowChanged.connect(self._on_net_selection_changed)

    @property
    def project(self) -> Project:
        if self._project is None:
            raise RuntimeError("No project loaded")
        return self._project

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_saved(self) -> None:
        self._dirty = False

    def set_rules_package(self, package: RulePackage) -> None:
        self._rules_label.setText(
            f"{package.manifest.package_id} v{package.manifest.version} "
            f"({package.package_sha256 or 'no digest'})"
        )

    def load_project(self, project: Project) -> None:
        self._project = project
        self._dirty = False
        for widget in (
            self._title_edit,
            self._customer_edit,
            self._doc_edit,
            self._revision_edit,
            self._freq_edit,
            self._altitude_edit,
        ):
            widget.blockSignals(True)
        for combo in (self._impulse_combo, self._pollution_combo, self._cti_combo):
            combo.blockSignals(True)
        self._title_edit.setText(project.metadata.title)
        self._customer_edit.setText(project.metadata.customer)
        self._doc_edit.setText(project.metadata.document_number)
        self._revision_edit.setText(project.metadata.revision)
        defaults = project.defaults
        self._freq_edit.setText("" if defaults.frequency_hz is None else str(defaults.frequency_hz))
        self._altitude_edit.setText("" if defaults.altitude_m is None else str(defaults.altitude_m))
        self._restore_combo_value(
            self._impulse_combo,
            _IMPULSE_OPTIONS,
            defaults.impulse_v,
            None
            if defaults.impulse_v is None
            else f"{defaults.impulse_v / Decimal(1000):g} kV",
        )
        self._restore_combo_value(
            self._pollution_combo,
            _POLLUTION_OPTIONS,
            defaults.pollution_degree,
            None if defaults.pollution_degree is None else str(defaults.pollution_degree),
        )
        self._restore_combo_value(
            self._cti_combo,
            _MATERIAL_OPTIONS,
            defaults.cti_or_material_group,
            defaults.cti_or_material_group,
        )
        self._insulation_combo.blockSignals(True)
        self._field_combo.blockSignals(True)
        self._construction_combo.blockSignals(True)
        self._insulation_combo.setCurrentText(
            defaults.insulation_type.value if defaults.insulation_type else ""
        )
        self._field_combo.setCurrentText(
            defaults.field_condition.value if defaults.field_condition else ""
        )
        self._construction_combo.setCurrentText(
            defaults.construction_type.value if defaults.construction_type else ""
        )
        self._insulation_combo.blockSignals(False)
        self._field_combo.blockSignals(False)
        self._construction_combo.blockSignals(False)
        for widget in (
            self._title_edit,
            self._customer_edit,
            self._doc_edit,
            self._revision_edit,
            self._freq_edit,
            self._altitude_edit,
        ):
            widget.blockSignals(False)
        for combo in (self._impulse_combo, self._pollution_combo, self._cti_combo):
            combo.blockSignals(False)
        rules = project.required_rules
        if rules is None:
            self._rules_label.setText("(none)")
        else:
            self._rules_label.setText(f"{rules.package_id} v{rules.version} ({rules.sha256[:12]}…)")
        self._refresh_net_list()

    def open_project(self, path: Path) -> None:
        try:
            project = load_project(Path(path))
        except ProjectLoadError as error:
            QMessageBox.critical(self, "Open Project", str(error))
            return
        self.load_project(project)

    def save_project(self, path: Path) -> None:
        if self._project is None:
            raise RuntimeError("No project loaded")
        save_project_atomic(Path(path), self._project)
        self._dirty = False

    def add_net_class(self, name: str, description: str = "") -> None:
        if self._project is None:
            raise RuntimeError("No project loaded")
        name = name.strip()
        if not name:
            raise ValueError("Net-class name must not be empty")
        existing_names = self._project.net_class_names
        if name in existing_names:
            raise ValueError(f"Net-class name '{name}' already exists")
        net_class = NetClass(id=uuid4(), name=name, description=description or None)
        net_classes = (*self._project.net_classes, net_class)
        pairs = reconcile_pairs(net_classes, self._project.pairs)
        self._update_project(net_classes=net_classes, pairs=pairs)

    def rename_net_class(self, index: int, new_name: str) -> None:
        if self._project is None:
            raise RuntimeError("No project loaded")
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Net-class name must not be empty")
        net_classes = list(self._project.net_classes)
        if index < 0 or index >= len(net_classes):
            raise IndexError("Net-class index out of range")
        other_names = [nc.name for i, nc in enumerate(net_classes) if i != index]
        if new_name in other_names:
            raise ValueError(f"Net-class name '{new_name}' already exists")
        old = net_classes[index]
        net_classes[index] = old.model_copy(update={"name": new_name})
        self._update_project(net_classes=tuple(net_classes))

    def delete_net_class(self, index: int) -> None:
        if self._project is None:
            raise RuntimeError("No project loaded")
        net_classes = list(self._project.net_classes)
        if index < 0 or index >= len(net_classes):
            raise IndexError("Net-class index out of range")
        del net_classes[index]
        pairs = reconcile_pairs(tuple(net_classes), self._project.pairs)
        self._update_project(net_classes=tuple(net_classes), pairs=pairs)

    def _update_project(self, **updates: object) -> None:
        self._project = self._project.model_copy(update=updates)  # type: ignore[union-attr]
        self._dirty = True
        self._refresh_net_list()
        self.project_changed.emit(self._project)

    def _refresh_net_list(self) -> None:
        self._net_list.clear()
        if self._project is None:
            return
        for net_class in self._project.net_classes:
            item = QListWidgetItem(net_class.name)
            item.setData(0x0100, str(net_class.id))
            self._net_list.addItem(item)
        self._on_net_selection_changed(self._net_list.currentRow())

    def _on_net_selection_changed(self, row: int) -> None:
        if self._project is None or row < 0 or row >= len(self._project.net_classes):
            self._description_edit.blockSignals(True)
            self._description_edit.clear()
            self._description_edit.blockSignals(False)
            return
        net = self._project.net_classes[row]
        self._description_edit.blockSignals(True)
        self._description_edit.setText(net.description or "")
        self._description_edit.blockSignals(False)

    def _on_description_changed(self) -> None:
        if self._project is None:
            return
        row = self._net_list.currentRow()
        if row < 0 or row >= len(self._project.net_classes):
            return
        net_classes = list(self._project.net_classes)
        net_classes[row] = net_classes[row].model_copy(
            update={"description": self._description_edit.text().strip() or None}
        )
        self._update_project(net_classes=tuple(net_classes))

    def _on_title_changed(self, text: str) -> None:
        if self._project is None:
            return
        metadata = self._project.metadata.model_copy(update={"title": text})
        self._update_project(metadata=metadata)

    def _on_customer_changed(self, text: str) -> None:
        if self._project is None:
            return
        metadata = self._project.metadata.model_copy(update={"customer": text})
        self._update_project(metadata=metadata)

    def _on_doc_changed(self, text: str) -> None:
        if self._project is None:
            return
        metadata = self._project.metadata.model_copy(update={"document_number": text})
        self._update_project(metadata=metadata)

    def _on_revision_changed(self, text: str) -> None:
        if self._project is None:
            return
        metadata = self._project.metadata.model_copy(update={"revision": text})
        self._update_project(metadata=metadata)

    def _on_freq_changed(self) -> None:
        self._update_default("frequency_hz", self._freq_edit.text())

    def _on_altitude_changed(self) -> None:
        self._update_default("altitude_m", self._altitude_edit.text())

    def _update_default(self, field: str, text: str) -> None:
        if self._project is None:
            return
        from decimal import Decimal, InvalidOperation

        defaults = dict(self._project.defaults.model_dump(mode="python"))
        text = text.strip()
        try:
            if not text:
                defaults[field] = None
            else:
                defaults[field] = Decimal(text)
        except (InvalidOperation, ValueError):
            return
        self._update_project(defaults=ProjectDefaults.model_validate(defaults))

    def _on_insulation_changed(self, text: str) -> None:
        self._update_enum_default("insulation_type", InsulationType, text)

    def _on_field_changed(self, text: str) -> None:
        self._update_enum_default("field_condition", FieldCondition, text)

    def _on_construction_changed(self, text: str) -> None:
        self._update_enum_default("construction_type", ConstructionType, text)

    def _update_enum_default(self, field: str, enum: type[Any], text: str) -> None:
        if self._project is None:
            return
        defaults = dict(self._project.defaults.model_dump(mode="python"))
        defaults[field] = enum(text).value if text else None
        self._update_project(defaults=ProjectDefaults.model_validate(defaults))

    @staticmethod
    def _populate_combo(
        combo: QComboBox,
        options: tuple[tuple[str, Any], ...],
    ) -> None:
        combo.addItem("", None)
        for text, value in options:
            combo.addItem(text, value)

    def _restore_combo_value(
        self,
        combo: QComboBox,
        options: tuple[tuple[str, Any], ...],
        value: Any,
        legacy_display: str | None,
    ) -> None:
        combo.clear()
        self._populate_combo(combo, options)
        if value is None:
            combo.setCurrentIndex(0)
            return
        index = combo.findData(value)
        if index < 0:
            if legacy_display is None:
                raise ValueError("Legacy combo value requires a display label")
            combo.addItem(f"{legacy_display} (legacy)", value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def _update_combo_default(self, field: str, combo: QComboBox, index: int) -> None:
        if self._project is None:
            return
        defaults = dict(self._project.defaults.model_dump(mode="python"))
        defaults[field] = combo.itemData(index)
        self._update_project(defaults=ProjectDefaults.model_validate(defaults))

    def _on_add_clicked(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Add Net Class", "Name:")
        if ok and name.strip():
            try:
                self.add_net_class(name.strip())
            except ValueError as error:
                QMessageBox.warning(self, "Add Net Class", str(error))

    def _on_rename_clicked(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        row = self._net_list.currentRow()
        if row < 0:
            return
        current_name = self._net_list.item(row).text()
        name, ok = QInputDialog.getText(self, "Rename Net Class", "Name:", text=current_name)
        if ok and name.strip():
            try:
                self.rename_net_class(row, name.strip())
            except (ValueError, IndexError) as error:
                QMessageBox.warning(self, "Rename Net Class", str(error))

    def _on_delete_clicked(self) -> None:
        row = self._net_list.currentRow()
        if row < 0:
            return
        name = self._net_list.item(row).text()
        reply = QMessageBox.question(
            self,
            "Delete Net Class",
            f"Delete '{name}'? This removes all pairs involving it.",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_net_class(row)
