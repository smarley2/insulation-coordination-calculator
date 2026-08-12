"""Rules Manager: install approved packages, audit every cell/formula, review drafts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
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

from insulation_coordination.domain.display import render_expression
from insulation_coordination.domain.rules import (
    Manifest,
    RulePackage,
    RulePackageError,
    SourceReference,
)
from insulation_coordination.rules.archive import write_rule_package
from insulation_coordination.rules.audit import (
    AuditInventory,
    build_audit_inventory,
    export_inventory_json,
    export_table_csv,
)
from insulation_coordination.rules.importer.approval import is_fully_resolved
from insulation_coordination.rules.importer.extract import _REQUIRED_RECIPES, ImportedRuleDraft
from insulation_coordination.rules.installation import install_rule_package
from insulation_coordination.ui.axis_review import AxisReviewDialog, AxisReviewModel
from insulation_coordination.ui.curve_review import CurveReviewDialog
from insulation_coordination.ui.equation_review import EquationReviewDialog
from insulation_coordination.ui.raw_grid_review import RawGridReviewDialog, source_pdf_paths

_SECTIONS = (
    "Manifest",
    "Checksums",
    "Tables",
    "Formulas",
    "Mappings",
    "Validation",
    "Decisions",
    "Procedures",
    "Guidance",
    "Curves",
)


class ImportResult:
    """Outcome of installing one approved rule package."""

    def __init__(self, path: Path, package: RulePackage) -> None:
        self.path = path
        self.package = package


class RulesManagerWindow(QWidget):
    """Browse and install rule packages; review drafts and full package audits."""

    package_activated = Signal(object)

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

        self._extract_draft_button = QPushButton("Extract draft from IEC PDFs…")
        self._extract_draft_button.clicked.connect(self._on_extract_draft_clicked)
        import_row.addWidget(self._extract_draft_button)
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
        self._review_status = QLabel(
            "No draft loaded. Import a draft package or set one programmatically."
        )
        review_layout.addWidget(self._review_status)
        review_layout.addWidget(QLabel("Needs your review:"))
        self._review_list = QListWidget()
        review_layout.addWidget(self._review_list)
        self._recipe_status = QLabel("")
        self._recipe_status.setWordWrap(True)
        review_layout.addWidget(self._recipe_status)
        self._review_notes = QLineEdit()
        self._review_notes.setPlaceholderText("Resolution / approval notes (required)")
        review_layout.addWidget(self._review_notes)

        review_actions = QHBoxLayout()
        self._review_tables_button = QPushButton("Review extracted tables…")
        self._review_tables_button.setEnabled(False)
        self._review_tables_button.clicked.connect(self._on_review_tables_clicked)
        review_actions.addWidget(self._review_tables_button)
        self._review_equations_button = QPushButton("Review equations and mappings…")
        self._review_equations_button.setEnabled(False)
        self._review_equations_button.clicked.connect(self._on_review_equations_clicked)
        review_actions.addWidget(self._review_equations_button)
        self._review_curves_button = QPushButton("Review manual curves…")
        self._review_curves_button.setEnabled(False)
        self._review_curves_button.clicked.connect(self._on_review_curves_clicked)
        review_actions.addWidget(self._review_curves_button)
        self._review_axis_selectors_button = QPushButton("Review axis selectors…")
        self._review_axis_selectors_button.setEnabled(False)
        self._review_axis_selectors_button.clicked.connect(self._on_review_axis_selectors_clicked)
        review_actions.addWidget(self._review_axis_selectors_button)
        review_layout.addLayout(review_actions)

        self._review_approve_button = QPushButton("Approve draft and build package…")
        self._review_approve_button.clicked.connect(self._on_review_approve_clicked)
        self._review_approve_button.setEnabled(False)
        review_layout.addWidget(self._review_approve_button)
        layout.addWidget(review_group)

        export_row = QHBoxLayout()
        self._approve_button = QPushButton("Export approved package…")
        self._approve_button.setEnabled(False)
        self._approve_button.clicked.connect(self._on_export_approved_clicked)
        export_row.addWidget(self._approve_button)

        self._inventory_button = QPushButton("Export audit inventory…")
        self._inventory_button.setEnabled(False)
        self._inventory_button.clicked.connect(self._on_export_inventory_clicked)
        export_row.addWidget(self._inventory_button)
        layout.addLayout(export_row)

        self._draft: ImportedRuleDraft | None = None
        self._draft_pdfs: dict[str, Path] = {}
        self._draft_passwords: dict[Path, str] = {}

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
    def audit_curve_count(self) -> int:
        return self._inventory.curve_count if self._inventory is not None else 0

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
        self._refresh_review()
        self._review_notes.clear()
        self._populate_tree()
        self._apply_search()
        self.package_activated.emit(package)

    def import_package(self, path: Path) -> ImportResult:
        installed = install_rule_package(Path(path), self._rules_dir)
        self.set_package(installed.package)
        return ImportResult(installed.path, installed.package)

    # -- Draft review -----------------------------------------------------

    @property
    def review_count(self) -> int:
        return len(self._draft.review_items) if self._draft is not None else 0

    @property
    def review_tables_enabled(self) -> bool:
        return self._review_tables_button.isEnabled()

    @property
    def build_review_enabled(self) -> bool:
        """True when approving would still have to project typed rule content."""
        if self._draft is None:
            return False
        from insulation_coordination.rules.importer.review import missing_required_content

        return self.is_fully_resolved and bool(missing_required_content(self._draft))

    @property
    def formula_review_enabled(self) -> bool:
        return self._review_equations_button.isEnabled()

    @property
    def curve_review_enabled(self) -> bool:
        return self._review_curves_button.isEnabled()

    @property
    def axis_review_enabled(self) -> bool:
        return self._review_axis_selectors_button.isEnabled()

    @property
    def review_approve_enabled(self) -> bool:
        return self._review_approve_button.isEnabled()

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
    def draft(self) -> ImportedRuleDraft | None:
        """The currently selected draft, for review surfaces backed by this window."""
        return self._draft

    @property
    def can_approve(self) -> bool:
        return self._draft is not None and self.is_fully_resolved

    def _refresh_review(self) -> None:
        self._review_list.clear()
        if self._draft is None:
            self._review_status.setText(
                "No draft loaded. Import a draft package or set one programmatically."
            )
            self._recipe_status.setText("")
            self._review_approve_button.setEnabled(False)
            self._review_tables_button.setEnabled(False)
            self._review_equations_button.setEnabled(False)
            self._review_curves_button.setEnabled(False)
            self._review_axis_selectors_button.setEnabled(False)
            return
        from insulation_coordination.rules.importer.review import (
            recipe_derived_items,
            unresolved_equation_items,
            unresolved_mapping_items,
            unresolved_raw_review_items,
            unresolved_table_items,
        )

        raw_pending = unresolved_raw_review_items(self._draft)
        table_pending = unresolved_table_items(self._draft)
        equation_pending = unresolved_equation_items(self._draft)
        mapping_pending = unresolved_mapping_items(self._draft)
        tables_done = not table_pending and not raw_pending
        self._review_tables_button.setEnabled(not tables_done)
        self._review_equations_button.setEnabled(
            tables_done and bool(equation_pending or mapping_pending)
        )
        self._review_curves_button.setEnabled(bool(self._draft.raw_figures))
        self._review_axis_selectors_button.setEnabled(bool(self._draft.axis_selector_proposals))
        for item in table_pending:
            flagged = sum(
                candidate.semantic_id.startswith(f"raw-{item.semantic_id}:")
                for candidate in raw_pending
            )
            self._review_list.addItem(
                f"Table {item.source.table or item.semantic_id} — "
                f"{item.source.standard} {item.source.clause}, {item.source.note}"
                f" — {flagged} cell(s) unclear"
            )
        for item in (*equation_pending, *mapping_pending):
            self._review_list.addItem(
                f"{item.kind.capitalize()} {item.semantic_id} — "
                f"{item.source.standard} {item.source.clause}, {item.source.note}"
            )
        if not self._review_list.count():
            self._review_list.addItem(
                "Nothing left to review. Add approval notes, then approve the draft."
            )
        self._review_status.setText(
            f"① Tables {len(self._draft.raw_grids) - len(table_pending)}"
            f" of {len(self._draft.raw_grids)} accepted"
            f"  ·  ② Equations and mappings {len(equation_pending) + len(mapping_pending)} pending"
            f"  ·  ③ Approve{' — ready' if self.can_approve else ''}"
        )
        derived = recipe_derived_items(self._draft)
        formulas = sum(item.kind == "formula" for item in derived)
        mappings = sum(item.kind == "mapping" for item in derived)
        self._recipe_status.setText(
            f"Taken from this app's recipe, no PDF content: {formulas} formula(s), "
            f"{mappings} mapping(s) — resolved by the importer, see the audit tree."
        )
        self._review_approve_button.setEnabled(self.can_approve)

    def _on_review_tables_clicked(self) -> None:
        if self._draft is None:
            return
        dialog = RawGridReviewDialog(
            self._draft,
            actor="maintainer",
            pdf_paths=self._draft_pdfs,
            pdf_passwords=self._draft_passwords,
        )
        dialog.draft_changed.connect(self.set_draft)
        dialog.exec()

    def _on_review_equations_clicked(self) -> None:
        if self._draft is None:
            return
        dialog = EquationReviewDialog(self._draft, actor="maintainer")
        dialog.draft_changed.connect(self.set_draft)
        dialog.exec()

    def _on_review_curves_clicked(self) -> None:
        if self._draft is None:
            return
        dialog = CurveReviewDialog(
            self._draft,
            actor="maintainer",
            pdf_paths=self._draft_pdfs,
            pdf_passwords=self._draft_passwords,
        )
        dialog.draft_changed.connect(self.set_draft)
        dialog.exec()

    def _on_review_axis_selectors_clicked(self) -> None:
        if self._draft is None:
            return
        model = AxisReviewModel(self._draft)
        dialog = AxisReviewDialog(model)
        dialog.exec()
        self.set_draft(model.draft)

    def approve_reviewed_draft(self, approver: str, notes: str) -> None:
        """Project reviewed content, approve, and switch to the approved package.

        Projection is a deterministic function of the accepted source artifacts,
        so it is part of approving rather than a separate button the maintainer
        has to know to press first.
        """
        if self._draft is None:
            raise RuntimeError("No draft loaded")
        from insulation_coordination.rules.importer.approval import approve_draft
        from insulation_coordination.rules.importer.review import (
            build_reviewed_draft,
            missing_required_content,
        )

        draft = self._draft
        if missing_required_content(draft):
            draft = build_reviewed_draft(draft, actor=approver, notes=notes)
            self.set_draft(draft)
        package = approve_draft(draft, approver, notes)
        self.set_package(package)

    def set_draft(self, draft: ImportedRuleDraft) -> None:
        self._draft = draft
        self._package = None
        self._inventory = None
        identities = {identity.recipe_id: identity for identity in draft.source_identities}
        lines = [
            f"{identity.standard} {identity.edition} ({identity.sha256[:12]})"
            for recipe_id in sorted(_REQUIRED_RECIPES)
            if (identity := identities.get(recipe_id)) is not None
        ]
        # The standards lines are extra detail, not a replacement for the unapproved
        # warning -- a maintainer must never lose the one statement that this draft
        # still requires review.
        self._identity_label.setText(
            "\n".join((f"Draft {draft.manifest.package_id} (unapproved; review required)", *lines))
        )
        self._approve_button.setEnabled(False)
        self._inventory_button.setEnabled(False)
        self._refresh_review()
        self._populate_draft_tree()
        self._apply_search()

    # -- Audit browser -----------------------------------------------------

    def _populate_draft_tree(self) -> None:
        """Show draft provenance and review state before an approved package exists."""
        from insulation_coordination.rules.importer.review import (
            inventory_report,
            missing_required_content,
            required_content_report,
            unresolved_equation_items,
            unresolved_mapping_items,
            unresolved_raw_review_items,
            unresolved_table_items,
        )

        draft = self._draft
        self._tree.clear()
        if draft is None:
            return
        resolved = {resolution.review_item_sha256 for resolution in draft.review_resolutions}
        review = QTreeWidgetItem(("Draft review",))
        self._tree.addTopLevelItem(review)
        report = required_content_report(draft)
        review.addChild(QTreeWidgetItem((f"package_id: {draft.manifest.package_id}",)))
        review.addChild(QTreeWidgetItem((f"sources: {len(draft.manifest.source_documents)}",)))
        review.addChild(
            QTreeWidgetItem(
                (f"review items: {len(resolved)} of {len(draft.review_items)} resolved",)
            )
        )
        review.addChild(
            QTreeWidgetItem(
                (
                    (
                        f"required content: {len(report) - len(missing_required_content(draft))} "
                        f"of {len(report)} present"
                    ),
                )
            )
        )
        inventory = inventory_report(draft)
        approved_items = tuple(status for status in inventory if status.approved)
        deferred_items = tuple(status for status in inventory if status.deferred)
        review.addChild(
            QTreeWidgetItem(
                (
                    (
                        f"required source items: {len(approved_items)} of {len(inventory)} "
                        f"approved, {len(deferred_items)} deferred"
                    ),
                )
            )
        )
        for issue in sorted({issue for status in inventory for issue in status.consumer_issue_ids}):
            consumed = tuple(status for status in inventory if issue in status.consumer_issue_ids)
            ready = tuple(status for status in consumed if status.approved)
            review.addChild(
                QTreeWidgetItem((f"  issue #{issue}: {len(ready)} of {len(consumed)} approved",))
            )

        sources = QTreeWidgetItem(("Source documents",))
        self._tree.addTopLevelItem(sources)
        for source in draft.manifest.source_documents:
            sources.addChild(QTreeWidgetItem((f"{source.standard} {source.edition}",)))

        tables = QTreeWidgetItem(("Extracted tables",))
        self._tree.addTopLevelItem(tables)
        pending_tables = {item.semantic_id for item in unresolved_table_items(draft)}
        pending_raw = {item.semantic_id for item in unresolved_raw_review_items(draft)}
        for grid in draft.raw_grids:
            pending = sum(item.startswith(f"{grid.id}:") for item in pending_raw)
            state = "pending" if grid.id.removeprefix("raw-") in pending_tables else "accepted"
            tables.addChild(QTreeWidgetItem((f"{grid.id}: {state}, {pending} raw cells pending",)))

        equations = QTreeWidgetItem(("Extracted equations",))
        self._tree.addTopLevelItem(equations)
        pending_equations = {item.semantic_id for item in unresolved_equation_items(draft)}
        for equation in draft.extracted_equations:
            state = "pending" if equation.id in pending_equations else "accepted"
            equations.addChild(
                QTreeWidgetItem((f"{equation.id}: {state} ({equation.parse_status})",))
            )

        mappings = QTreeWidgetItem(("Semantic mappings",))
        self._tree.addTopLevelItem(mappings)
        pending_mappings = {item.semantic_id for item in unresolved_mapping_items(draft)}
        from insulation_coordination.rules.importer.recipes import RECIPES

        for spec in (spec for recipe in RECIPES for spec in recipe.mappings):
            state = (
                "pending"
                if spec.id in pending_mappings
                else "accepted (recipe-defined, resolved by importer)"
            )
            mappings.addChild(QTreeWidgetItem((f"{spec.id}: {state} — {spec.semantic_route}",)))
        self._tree.expandToDepth(0)

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

    def _on_extract_draft_clicked(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select IEC 60664-1 and 60664-4 PDFs",
            "",
            "PDF files (*.pdf)",
        )
        if not paths:
            return
        from insulation_coordination.rules.importer.extract import ExtractionError, extract_draft
        from insulation_coordination.rules.importer.identify import (
            PasswordRequiredError,
            StandardIdentificationError,
        )

        selected_paths = tuple(Path(path) for path in paths)
        passwords: dict[Path, str] = {}
        while True:
            try:
                draft = extract_draft(selected_paths, passwords=passwords)
                break
            except PasswordRequiredError as error:
                password, accepted = QInputDialog.getText(
                    self,
                    "Unlock standard PDF",
                    f"{error}\nEnter the PDF password for {error.path.name}:",
                    QLineEdit.EchoMode.Password,
                )
                if not accepted:
                    QMessageBox.critical(self, "Extract Draft", str(error))
                    return
                passwords[error.path] = password
            except (ExtractionError, StandardIdentificationError) as error:
                QMessageBox.critical(self, "Extract Draft", str(error))
                return
        self.set_draft(draft)
        # Keep the sources reachable so table review can show each grid's PDF page.
        self._draft_pdfs = source_pdf_paths(draft, selected_paths)
        self._draft_passwords = dict(passwords)

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
        directory = QFileDialog.getExistingDirectory(self, "Export Audit Inventory")
        if not directory:
            return
        try:
            self.export_inventory(Path(directory))
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Export Audit Inventory", str(error))

    def _on_review_approve_clicked(self) -> None:
        if self._draft is None or not self.is_fully_resolved:
            return
        notes = self._review_notes.text().strip()
        if not notes:
            QMessageBox.warning(self, "Approve Draft", "Approval notes are required.")
            return
        try:
            self.approve_reviewed_draft("maintainer", notes)
        except (ValueError, KeyError) as error:
            QMessageBox.critical(self, "Approve Draft", str(error))
            return
        QMessageBox.information(
            self,
            "Draft Approved",
            "Draft approved, rule content built, and ready to export.",
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
        self._add_decisions_items()
        self._add_procedures_items()
        self._add_guidance_items()
        self._add_curves_items()
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
                        (
                            f"source_document[{index}]: {document.standard} "
                            f"{document.edition} {document.sha256}"
                        ),
                    )
                )
            )
        for record in manifest.approval_records:
            top.addChild(
                QTreeWidgetItem(
                    (
                        (
                            f"approval: {record.action} by {record.actor} at "
                            f"{record.recorded_at.isoformat()} — {record.notes}"
                        ),
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
                            (
                                f"range {supported.variable} "
                                f"{supported.minimum}..{supported.maximum} {supported.unit}"
                            ),
                        )
                    )
                )
            table_item.addChild(QTreeWidgetItem((f"source: {_format_reference(table.source)}",)))
            for cell in table.cells:
                table_item.addChild(
                    QTreeWidgetItem(
                        (
                            (
                                f"[{cell.row},{cell.column}] {cell.value} {cell.unit} "
                                f"— {_format_reference(cell.source)}"
                            ),
                        )
                    )
                )

    def _add_formulas_items(self) -> None:
        inventory = self._require_inventory()
        top = self._tree.topLevelItem(3)
        if top is None:
            return
        for formula in inventory.formulas:
            formula_item = QTreeWidgetItem((f"Formula {formula.id} ({formula.unit})",))
            formula_item.setData(0, Qt.ItemDataRole.UserRole, f"formula:{formula.id}")
            top.addChild(formula_item)
            formula_item.addChild(
                QTreeWidgetItem((f"calculation: {render_expression(formula.expression)}",))
            )
            for node in inventory.formula_nodes:
                if node.formula_id != formula.id:
                    continue
                formula_item.addChild(
                    QTreeWidgetItem((f"{node.path}: {render_expression(node.node)}",))
                )
            formula_item.addChild(QTreeWidgetItem((f"latex: {formula.latex}",)))
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
                        (
                            f"{mapping.id}: {mapping.source_rule_id} → "
                            f"{mapping.target_rule_id} (approved={mapping.approved}) "
                            f"— {_format_reference(mapping.source)}"
                        ),
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

    def _add_decisions_items(self) -> None:
        top = self._tree.topLevelItem(6)
        if top is None or self._package is None:
            return
        for decision in self._package.decisions:
            top.addChild(
                QTreeWidgetItem((f"{decision.id} — {_format_reference(decision.source)}",))
            )

    def _add_procedures_items(self) -> None:
        top = self._tree.topLevelItem(7)
        if top is None or self._package is None:
            return
        for procedure in self._package.procedures:
            top.addChild(
                QTreeWidgetItem((f"{procedure.id} — {_format_reference(procedure.source)}",))
            )

    def _add_guidance_items(self) -> None:
        top = self._tree.topLevelItem(8)
        if top is None or self._package is None:
            return
        for guidance in self._package.guidance:
            top.addChild(
                QTreeWidgetItem((f"{guidance.id} — {_format_reference(guidance.source)}",))
            )

    def _add_curves_items(self) -> None:
        top = self._tree.topLevelItem(9)
        if top is None or self._inventory is None:
            return
        for curve in self._inventory.curves:
            top.addChild(QTreeWidgetItem((f"{curve.id} — {_format_reference(curve.source)}",)))

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
        self._search_matches = [line for line in haystack if needle in line.casefold()]

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
