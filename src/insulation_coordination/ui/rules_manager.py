"""Rules Manager: install approved packages, audit every cell/formula, review drafts."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.rules import (
    Manifest,
    RulePackage,
    RulePackageError,
    SourceReference,
)
from insulation_coordination.rules.archive import (
    load_rule_package,
    write_rule_package,
)
from insulation_coordination.rules.audit import (
    AuditInventory,
    build_audit_inventory,
    export_inventory_json,
    export_table_csv,
)
from insulation_coordination.rules.importer.approval import is_fully_resolved
from insulation_coordination.rules.importer.extract import ImportedRuleDraft

_SECTIONS = ("Manifest", "Checksums", "Tables", "Formulas", "Mappings", "Validation")


class ImportResult:
    """Outcome of installing one approved rule package."""

    def __init__(self, path: Path, package: RulePackage) -> None:
        self.path = path
        self.package = package


class RulesManagerWindow(QWidget):
    """Browse and install rule packages; review drafts and full package audits."""

    def __init__(self, rules_dir: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Rules Manager")
        self.resize(980, 640)
        self._rules_dir = rules_dir
        self._package: RulePackage | None = None
        self._inventory: AuditInventory | None = None

        layout = QVBoxLayout(self)

        identity_row = QHBoxLayout()
        identity_row.addWidget(QLabel("Active package:"))
        self._identity_label = QLabel("(none)")
        identity_row.addWidget(self._identity_label, 1)
        layout.addLayout(identity_row)

        import_row = QHBoxLayout()
        self._import_button = QPushButton("Import approved .icrules…")
        self._import_button.clicked.connect(self._on_import_clicked)
        import_row.addWidget(self._import_button)

        self._approve_button = QPushButton("Export approved package…")
        self._approve_button.setEnabled(False)
        self._approve_button.clicked.connect(self._on_export_approved_clicked)
        import_row.addWidget(self._approve_button)

        self._inventory_button = QPushButton("Export audit inventory…")
        self._inventory_button.setEnabled(False)
        self._inventory_button.clicked.connect(self._on_export_inventory_clicked)
        import_row.addWidget(self._inventory_button)
        layout.addLayout(import_row)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search semantic IDs / references:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("e.g. clearance, IEC 60664-1, table 4.2")
        self._search_edit.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_edit, 1)
        layout.addLayout(search_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(("Audit tree",))
        self._tree.setAlternatingRowColors(True)
        self._tree.itemClicked.connect(self._on_tree_item_clicked)
        splitter.addWidget(self._tree)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        splitter.addWidget(self._detail)
        layout.addWidget(splitter, 1)

        review_group = QGroupBox("Maintainer PDF extraction review")
        review_layout = QVBoxLayout(review_group)
        self._review_status = QLabel("No draft loaded. Import a draft package or set one programmatically.")
        review_layout.addWidget(self._review_status)
        self._review_list = QListWidget()
        review_layout.addWidget(self._review_list)
        self._review_notes = QLineEdit()
        self._review_notes.setPlaceholderText("Resolution / approval notes (required)")
        review_layout.addWidget(self._review_notes)
        self._review_approve_button = QPushButton("Approve reviewed draft…")
        self._review_approve_button.clicked.connect(self._on_review_approve_clicked)
        self._review_approve_button.setEnabled(False)
        review_layout.addWidget(self._review_approve_button)
        layout.addWidget(review_group)

        self._draft: ImportedRuleDraft | None = None
        self._draft_sources: tuple[object, ...] = ()

    # -- Package state -----------------------------------------------------

    @property
    def active_package(self) -> RulePackage | None:
        return self._package

    @property
    def pdf_required(self) -> bool:
        return self._draft is not None

    @property
    def identity_text(self) -> str:
        return self._identity_label.text()

    @property
    def export_approved_enabled(self) -> bool:
        return self._approve_button.isEnabled()

    @property
    def inventory(self) -> AuditInventory | None:
        return self._inventory

    @property
    def audit_cell_count(self) -> int:
        return self._inventory.table_cell_count if self._inventory is not None else 0

    @property
    def audit_formula_count(self) -> int:
        return self._inventory.formula_node_count if self._inventory is not None else 0

    @property
    def total_cell_count(self) -> int:
        return sum(len(table.cells) for table in self._package.tables) if self._package else 0

    @property
    def cell_values(self) -> tuple[Decimal, ...]:
        return (
            tuple(cell.value for table in self._package.tables for cell in table.cells)
            if self._package
            else ()
        )

    @property
    def search_matches(self) -> tuple[str, ...]:
        return tuple(self._search_matches)

    def set_package(self, package: RulePackage) -> None:
        self._package = package
        self._draft = None
        self._inventory = build_audit_inventory(package)
        self._identity_label.setText(
            f"{package.manifest.package_id} v{package.manifest.version} "
            f"({package.package_sha256 or 'no digest'})"
        )
        self._approve_button.setEnabled(package.manifest.approved and package.manifest.compatible)
        self._inventory_button.setEnabled(True)
        self._review_status.setText("No draft loaded. Import a draft package or set one programmatically.")
        self._review_list.clear()
        self._review_notes.clear()
        self._populate_tree()
        self._apply_search()

    def import_package(self, path: Path) -> ImportResult:
        package = load_rule_package(Path(path))
        destination = self._install_path(package)
        write_rule_package(destination, package)
        loaded = load_rule_package(destination)
        self.set_package(loaded)
        return ImportResult(destination, loaded)

    # -- Draft review -----------------------------------------------------

    @property
    def review_count(self) -> int:
        return len(self._draft.review_items) if self._draft is not None else 0

    @property
    def resolved_count(self) -> int:
        if self._draft is None:
            return 0
        resolved = {r.review_item_sha256 for r in self._draft.review_resolutions}
        return len(resolved & {i.sha256 for i in self._draft.review_items})

    @property
    def is_fully_resolved(self) -> bool:
        return self._draft is not None and is_fully_resolved(self._draft)

    @property
    def can_approve(self) -> bool:
        return self._draft is not None and self.is_fully_resolved

    def _refresh_review(self) -> None:
        self._review_list.clear()
        if self._draft is None:
            self._review_status.setText("No draft loaded. Import a draft package or set one programmatically.")
            self._review_approve_button.setEnabled(False)
            return
        resolved = {r.review_item_sha256 for r in self._draft.review_resolutions}
        for item in self._draft.review_items:
            mark = "[x]" if item.sha256 in resolved else "[ ]"
            self._review_list.addItem(
                f"{mark} {item.code} {item.semantic_id} — {item.expected_contract}"
            )
        self._review_status.setText(
            f"Manual review items: {self.resolved_count} of {self.review_count} resolved."
        )
        self._review_approve_button.setEnabled(self._draft is not None and self.is_fully_resolved)

    def approve_reviewed_draft(self, approver: str, notes: str) -> None:
        """Approve a fully-resolved draft and switch the manager to the approved package."""
        if self._draft is None:
            raise RuntimeError("No draft loaded")
        from insulation_coordination.rules.importer.approval import approve_draft

        package = approve_draft(self._draft, approver, notes)
        self.set_package(package)

    def set_draft(self, draft: ImportedRuleDraft, sources: Iterable[object] = ()) -> None:
        self._draft = draft
        self._draft_sources = tuple(sources)
        self._package = None
        self._inventory = None
        self._identity_label.setText(
            f"Draft {draft.manifest.package_id} (unapproved; review required)"
        )
        self._approve_button.setEnabled(False)
        self._inventory_button.setEnabled(False)
        self._refresh_review()
        self._tree.clear()
        self._apply_search()

    # -- Audit browser -----------------------------------------------------

    def search(self, text: str) -> None:
        self._search_edit.setText(text)

    def export_inventory(self, destination: Path) -> None:
        if self._package is None or self._inventory is None:
            raise RuntimeError("No active package to export")
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        export_inventory_json(self._inventory, destination / "audit-inventory.json")
        for table in self._package.tables:
            export_table_csv(self._package, table.id, destination / f"table-{table.id}.csv")

    def _install_path(self, package: RulePackage) -> Path:
        rules_dir = (
            self._rules_dir
            if self._rules_dir is not None
            else _default_rules_dir()
        )
        rules_dir.mkdir(parents=True, exist_ok=True)
        return rules_dir / f"{package.manifest.package_id}-{package.manifest.version}.icrules"

    def _on_import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Approved Rules", "", "Rules Archive (*.icrules)"
        )
        if not path:
            return
        try:
            self.import_package(Path(path))
        except RulePackageError as error:
            QMessageBox.critical(self, "Import Rules", str(error))

    def _on_export_approved_clicked(self) -> None:
        if self._package is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Approved Package", "", "Rules Archive (*.icrules)"
        )
        if not path:
            return
        try:
            write_rule_package(Path(path), self._package)
        except RulePackageError as error:
            QMessageBox.critical(self, "Export Approved Package", str(error))

    def _on_export_inventory_clicked(self) -> None:
        if self._package is None:
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Export Audit Inventory"
        )
        if not directory:
            return
        try:
            self.export_inventory(Path(directory))
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Export Audit Inventory", str(error))

    def _on_review_approve_clicked(self) -> None:
        if self._draft is None or not self.is_fully_resolved:
            return
        try:
            self.approve_reviewed_draft("maintainer", self._review_notes.text())
        except ValueError as error:
            QMessageBox.critical(self, "Approve Draft", str(error))
            return
        QMessageBox.information(
            self,
            "Draft Approved",
            "Draft approved and ready to export.",
        )

    def _populate_tree(self) -> None:
        self._tree.clear()
        if self._package is None or self._inventory is None:
            return
        for section in _SECTIONS:
            item = QTreeWidgetItem((section,))
            self._tree.addTopLevelItem(item)
        manifest = self._inventory.manifest
        self._add_manifest_items(manifest)
        self._add_checksums_items()
        self._add_tables_items()
        self._add_formulas_items()
        self._add_mappings_items()
        self._add_validation_items()
        self._tree.expandToDepth(0)

    def _add_manifest_items(self, manifest: Manifest) -> None:
        inventory = self._require_inventory()
        top = self._tree.topLevelItem(0)
        if top is None:
            return
        for label, value in (
            ("package_id", inventory.package_id),
            ("version", inventory.version),
            ("schema_version", inventory.schema_version),
            ("package_sha256", inventory.package_sha256),
            ("importer_version", manifest.importer_version),
            ("created_at", manifest.created_at.isoformat()),
            ("approved", manifest.approved),
            ("compatible", manifest.compatible),
        ):
            top.addChild(QTreeWidgetItem((f"{label}: {value}",)))
        for index, document in enumerate(manifest.source_documents):
            top.addChild(
                QTreeWidgetItem(
                    (
                        (f"source_document[{index}]: {document.standard} "
                         f"{document.edition} {document.sha256}"),
                    )
                )
            )
        for record in manifest.approval_records:
            top.addChild(
                QTreeWidgetItem(
                    (
                        (f"approval: {record.action} by {record.actor} at "
                         f"{record.recorded_at.isoformat()} — {record.notes}"),
                    )
                )
            )

    def _add_checksums_items(self) -> None:
        inventory = self._require_inventory()
        top = self._tree.topLevelItem(1)
        if top is None:
            return
        for record in inventory.checksums:
            top.addChild(QTreeWidgetItem((f"{record.member}: {record.sha256}",)))

    def _add_tables_items(self) -> None:
        inventory = self._require_inventory()
        top = self._tree.topLevelItem(2)
        if top is None:
            return
        for table in inventory.tables:
            table_item = QTreeWidgetItem(
                (f"Table {table.id} ({table.unit}, {len(table.cells)} cells)",)
            )
            table_item.setData(0, Qt.ItemDataRole.UserRole, f"table:{table.id}")
            top.addChild(table_item)
            for supported in table.supported_ranges:
                table_item.addChild(
                    QTreeWidgetItem(
                        (
                            (f"range {supported.variable} "
                             f"{supported.minimum}..{supported.maximum} {supported.unit}"),
                        )
                    )
                )
            table_item.addChild(
                QTreeWidgetItem((f"source: {_format_reference(table.source)}",))
            )
            for cell in table.cells:
                table_item.addChild(
                    QTreeWidgetItem(
                        (
                            (f"[{cell.row},{cell.column}] {cell.value} {cell.unit} "
                             f"— {_format_reference(cell.source)}"),
                        )
                    )
                )

    def _add_formulas_items(self) -> None:
        inventory = self._require_inventory()
        top = self._tree.topLevelItem(3)
        if top is None:
            return
        for formula in inventory.formulas:
            formula_item = QTreeWidgetItem(
                (f"Formula {formula.id} ({formula.unit})",)
            )
            formula_item.setData(0, Qt.ItemDataRole.UserRole, f"formula:{formula.id}")
            top.addChild(formula_item)
            for node in inventory.formula_nodes:
                if node.formula_id != formula.id:
                    continue
                formula_item.addChild(
                    QTreeWidgetItem(
                        (f"{node.path}: {_format_expression(node.node)}",)
                    )
                )
            formula_item.addChild(
                QTreeWidgetItem((f"latex: {formula.latex}",))
            )
            formula_item.addChild(
                QTreeWidgetItem((f"source: {_format_reference(formula.source)}",))
            )

    def _add_mappings_items(self) -> None:
        inventory = self._require_inventory()
        top = self._tree.topLevelItem(4)
        if top is None:
            return
        for mapping in inventory.mappings:
            top.addChild(
                QTreeWidgetItem(
                    (
                        (f"{mapping.id}: {mapping.source_rule_id} → "
                         f"{mapping.target_rule_id} (approved={mapping.approved}) "
                         f"— {_format_reference(mapping.source)}"),
                    )
                )
            )

    def _add_validation_items(self) -> None:
        inventory = self._require_inventory()
        top = self._tree.topLevelItem(5)
        if top is None:
            return
        for result in inventory.validation.results:
            status = "PASS" if result.passed else "FAIL"
            top.addChild(QTreeWidgetItem((f"[{status}] {result.code}: {result.message}",)))

    def _require_inventory(self) -> AuditInventory:
        if self._inventory is None:
            raise RuntimeError("No audit inventory loaded")
        return self._inventory

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        self._detail.setPlainText(item.text(0))

    def _on_search_changed(self, text: str) -> None:
        self._apply_search()

    def _apply_search(self) -> None:
        self._search_matches: list[str] = []
        needle = self._search_edit.text().strip().casefold()
        if not needle or self._tree is None:
            return
        haystack = self._collect_audit_lines()
        self._search_matches = [
            line for line in haystack if needle in line.casefold()
        ]

    def _collect_audit_lines(self) -> tuple[str, ...]:
        lines: list[str] = []
        stack = [self._tree.topLevelItem(index) for index in range(self._tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            lines.append(item.text(0))
            stack.extend(item.child(index) for index in range(item.childCount()))
        return tuple(lines)

    def _collect_references(self) -> Iterator[SourceReference]:
        if self._package is None:
            return
        for table in self._package.tables:
            yield table.source
            yield from (cell.source for cell in table.cells)
            yield from (item.source for item in table.supported_ranges)
        for formula in self._package.formulas:
            yield formula.source
            yield from (item.source for item in formula.parameter_sets)
            yield from (item.source for item in formula.supported_ranges)
        yield from (mapping.source for mapping in self._package.mappings)


def _default_rules_dir() -> Path:
    import platformdirs

    return platformdirs.user_data_path("icc") / "rules"


def _format_reference(reference: SourceReference) -> str:
    parts = [f"{reference.standard}:{reference.edition}"]
    if reference.clause:
        parts.append(reference.clause)
    if reference.table:
        parts.append(f"Table {reference.table}")
    if reference.figure:
        parts.append(f"Figure {reference.figure}")
    if reference.row:
        parts.append(f"row {reference.row}")
    if reference.column:
        parts.append(f"column {reference.column}")
    if reference.note:
        parts.append(f"Note {reference.note}")
    return ", ".join(parts)


def _format_expression(node: object) -> str:
    op = getattr(node, "op", "?")
    if op == "literal":
        return str(getattr(node, "value", ""))
    if op == "variable":
        return str(getattr(node, "name", ""))
    if op == "lookup":
        return f"lookup({getattr(node, 'table_id', '?')})"
    if op == "linear_interpolate":
        return f"linear_interpolate({getattr(node, 'table_id', '?')})"
    if op == "round":
        return f"round:{getattr(node, 'places', '?')}:{getattr(node, 'mode', '?')}"
    return str(op)
