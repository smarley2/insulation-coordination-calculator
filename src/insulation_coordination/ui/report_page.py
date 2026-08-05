"""Report page: group controls, validation summary, and offline .tex/PDF export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.engine import (
    CalculationError,
    PairResult,
    calculate_pair,
)
from insulation_coordination.calculation.grouping import (
    CalculationGroup,
    GroupingError,
    group_results,
    split_group,
)
from insulation_coordination.domain.display import group_label, pair_label
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.report.compiler import CompilerCommand, compile_pdf
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import ReportBuildError, build_report_model
from insulation_coordination.report.revision_diff import (
    render_revision_diff,
    revision_of,
    revision_slug,
)
from insulation_coordination.report.tectonic import (
    TectonicIntegrityError,
    TectonicRuntime,
    resolve_tectonic_runtime,
)


@dataclass(frozen=True)
class ReportOutput:
    """Generated artifacts for one report export."""

    tex_path: Path
    pdf_path: Path | None
    log_path: Path | None
    diff_pdf_path: Path | None = None


class ReportPage(QWidget):
    """Shows automatic groups, document metadata, and blocked/final report state."""

    project_changed = Signal(object)

    def __init__(self, tectonic: CompilerCommand | None = None) -> None:
        super().__init__()
        self._project: Project | None = None
        self._rules: RulePackage | None = None
        self._results: tuple[PairResult, ...] = ()
        self._groups: tuple[CalculationGroup, ...] = ()
        self._blocking: tuple[str, ...] = ()
        self._stale: bool = False
        self._tectonic = tectonic

        layout = QVBoxLayout(self)

        self._title_label = QLabel("Report")
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14pt;")
        layout.addWidget(self._title_label)

        metadata_group = QGroupBox("Document metadata")
        metadata_layout = QFormLayout(metadata_group)
        self._document_number_edit = QLineEdit()
        self._document_number_edit.textChanged.connect(self._on_document_number_changed)
        metadata_layout.addRow("Document number:", self._document_number_edit)
        self._revision_edit = QLineEdit()
        self._revision_edit.textChanged.connect(self._on_revision_changed)
        metadata_layout.addRow("Revision:", self._revision_edit)
        layout.addWidget(metadata_group)

        export_row = QHBoxLayout()
        self._generate_button = QPushButton("Generate .tex and PDF…")
        self._generate_button.setEnabled(False)
        self._generate_button.clicked.connect(self._on_generate_clicked)
        export_row.addWidget(self._generate_button)
        self._artifacts_label = QLabel("")
        export_row.addWidget(self._artifacts_label, 1)
        layout.addLayout(export_row)

        self._summary_label = QLabel("No project loaded")
        layout.addWidget(self._summary_label)

        groups_group = QGroupBox("Automatic groups")
        groups_layout = QVBoxLayout(groups_group)
        self._groups_list = QListWidget()
        groups_layout.addWidget(self._groups_list)
        self._split_button = QPushButton("Split selected group")
        self._split_button.setEnabled(False)
        self._split_button.clicked.connect(self._on_split_clicked)
        groups_layout.addWidget(self._split_button)
        layout.addWidget(groups_group)
        layout.addStretch(1)

    @property
    def generate_enabled(self) -> bool:
        self._ensure_fresh()
        return self._generate_button.isEnabled()

    @property
    def blocking_summary(self) -> str:
        self._ensure_fresh()
        return "; ".join(self._blocking) if self._blocking else ""

    @property
    def validation_summary(self) -> str:
        self._ensure_fresh()
        if self._project is None:
            return "No project loaded"
        if self._blocking:
            return self.blocking_summary
        return "All pairs calculated"

    @property
    def group_count(self) -> int:
        self._ensure_fresh()
        return len(self._groups)

    def load_project(self, project: Project) -> None:
        self._project = project
        for edit in (self._document_number_edit, self._revision_edit):
            edit.blockSignals(True)
        self._document_number_edit.setText(project.metadata.document_number)
        self._revision_edit.setText(project.metadata.revision)
        for edit in (self._document_number_edit, self._revision_edit):
            edit.blockSignals(False)
        self._mark_stale()

    def _mark_stale(self) -> None:
        self._stale = True
        if self.isVisible():
            self._ensure_fresh()

    def _ensure_fresh(self) -> None:
        if self._stale:
            self._stale = False
            self._refresh()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._ensure_fresh()

    def _on_document_number_changed(self, text: str) -> None:
        self._update_metadata(document_number=text)

    def _on_revision_changed(self, text: str) -> None:
        self._update_metadata(revision=text)

    def _update_metadata(self, **updates: str) -> None:
        """Publish a metadata edit so the Project page and the saved file follow."""
        if self._project is None:
            return
        metadata = self._project.metadata.model_copy(update=updates)
        if metadata == self._project.metadata:
            return
        # Metadata does not affect the calculation, so no refresh is needed here.
        self._project = self._project.model_copy(update={"metadata": metadata})
        self.project_changed.emit(self._project)

    def load_rules(self, rules: RulePackage) -> None:
        self._rules = rules
        self._mark_stale()

    def generate(self, destination: Path, baseline_tex: Path | None = None) -> ReportOutput:
        """Recalculate every pair against the installed rules and render + compile.

        ``baseline_tex`` is an earlier revision's ``.tex`` chosen by the user. When
        given, a second PDF holding only the differences is produced as well.
        """
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        if self._project is None or self._rules is None:
            raise RuntimeError("Report generation requires a project and rules")
        self._ensure_fresh()
        if self._blocking:
            raise RuntimeError(self.blocking_summary)
        try:
            runtime = resolve_tectonic_runtime(self._tectonic)
        except TectonicIntegrityError as error:
            raise RuntimeError(str(error)) from error
        try:
            model = build_report_model(
                self._project,
                self._results,
                self._groups,
                self._rules,
            )
        except ReportBuildError as error:
            raise RuntimeError(str(error)) from error
        tex = destination / f"{self._basename()}.tex"
        # Read the chosen baseline first: it may be the file about to be overwritten.
        previous_tex = self._read_baseline(baseline_tex)
        current_tex = render_latex(model)
        tex.write_text(current_tex, encoding="utf-8")
        result = compile_pdf(
            tex,
            destination / f"{self._basename()}.pdf",
            runtime.command,
            offline_flag=runtime.offline_flag,
            cache_dir=runtime.cache_dir,
        )
        return ReportOutput(
            tex_path=tex,
            pdf_path=result.pdf_path,
            log_path=result.log_path if result.pdf_path is not None else None,
            diff_pdf_path=self._compile_revision_diff(
                destination, previous_tex, current_tex, runtime
            ),
        )

    @staticmethod
    def _read_baseline(baseline_tex: Path | None) -> str | None:
        if baseline_tex is None:
            return None
        try:
            return Path(baseline_tex).read_text(encoding="utf-8")
        except OSError as error:
            raise RuntimeError(f"Could not read the selected earlier revision: {error}") from error

    def _compile_revision_diff(
        self,
        destination: Path,
        previous_tex: str | None,
        current_tex: str,
        runtime: TectonicRuntime,
    ) -> Path | None:
        """Render the user-selected earlier revision against this one."""
        if previous_tex is None:
            return None
        previous_revision = revision_of(previous_tex) or "unknown"
        current_revision = revision_of(current_tex) or "unknown"
        stem = (
            f"{self._basename()}-diff-rev{revision_slug(previous_revision)}"
            f"-rev{revision_slug(current_revision)}"
        )
        diff_tex = destination / f"{stem}.tex"
        diff_tex.write_text(
            render_revision_diff(
                previous_tex,
                current_tex,
                previous_revision=previous_revision,
                current_revision=current_revision,
            ),
            encoding="utf-8",
        )
        diff_result = compile_pdf(
            diff_tex,
            destination / f"{stem}.pdf",
            runtime.command,
            offline_flag=runtime.offline_flag,
            cache_dir=runtime.cache_dir,
        )
        return diff_result.pdf_path

    def export(self, destination: Path, baseline_tex: Path | None = None) -> ReportOutput:
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        return self.generate(destination, baseline_tex)

    def _basename(self) -> str:
        if self._project is None:
            return "insulation-coordination-report"
        number = self._project.metadata.document_number or "report"
        return f"icc-report-{number}".replace(" ", "_")

    def _refresh(self) -> None:
        if self._project is None or self._rules is None:
            self._results = ()
            self._groups = ()
            self._blocking = ()
            self._generate_button.setEnabled(False)
            self._summary_label.setText("Load a project and an approved rules package")
            self._groups_list.clear()
            self._fit_groups_list()
            return
        results: list[PairResult] = []
        blocking: list[str] = []
        for pair in self._project.pairs:
            if pair.is_excluded:
                continue
            try:
                effective = resolve_effective_case(self._project.defaults, pair)
                results.append(calculate_pair(effective, self._rules))
            except CalculationError as error:
                blocking.append(f"{pair_label(self._project, pair)}: {error}")
        self._results = tuple(results)
        if blocking:
            self._groups = ()
            self._blocking = tuple(blocking)
        else:
            try:
                self._groups = group_results(self._results, self._project.group_splits)
            except GroupingError as error:
                self._groups = ()
                self._blocking = (str(error),)
            else:
                self._blocking = ()
        self._generate_button.setEnabled(self._project is not None and not self._blocking)
        self._split_button.setEnabled(
            self._project is not None and any(len(group.pair_ids) > 1 for group in self._groups)
        )
        self._summary_label.setText(self.validation_summary)
        self._groups_list.clear()
        for index, group in enumerate(self._groups, start=1):
            self._groups_list.addItem(group_label(self._project, group.pair_ids, index))
        self._fit_groups_list()

    def _fit_groups_list(self) -> None:
        """Keep the group list tall enough for its rows and no taller."""
        rows = self._groups_list.count()
        row_height = self._groups_list.sizeHintForRow(0) if rows else 0
        if row_height <= 0:
            row_height = self._groups_list.fontMetrics().height() + 8
        frame = 2 * self._groups_list.frameWidth() + 4
        self._groups_list.setMinimumHeight(min(rows, 3) * row_height + frame)
        self._groups_list.setMaximumHeight(max(rows, 1) * row_height + frame)

    def split_selected_group(self) -> None:
        """Split the first multi-pair group by moving its last pair out."""
        if self._project is None or self._groups is None:
            return
        self._ensure_fresh()
        target = next((g for g in self._groups if len(g.pair_ids) > 1), None)
        if target is None:
            raise GroupingError("no group with more than one pair to split")
        selected = target.pair_ids[-1:]
        split_group(self._groups, target.group_id, selected)  # validate split applies
        # persist a GroupSplit
        from insulation_coordination.domain.project import GroupSplit

        existing = list(self._project.group_splits)
        existing.append(GroupSplit(signature=target.signature, pair_ids=selected))
        project = self._project.model_copy(update={"group_splits": tuple(existing)})
        self._project = project
        self._refresh()
        self.project_changed.emit(project)

    def _on_split_clicked(self) -> None:
        try:
            self.split_selected_group()
        except GroupingError as error:
            QMessageBox.warning(self, "Split Group", str(error))

    def _on_generate_clicked(self) -> None:
        if self._project is None:
            return
        directory = QFileDialog.getExistingDirectory(self, "Export Report")
        if not directory:
            return
        baseline, _ = QFileDialog.getOpenFileName(
            self,
            "Compare against an earlier revision (Cancel to skip)",
            directory,
            "Report Source (*.tex)",
        )
        try:
            output = self.export(Path(directory), Path(baseline) if baseline else None)
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Generate Report", str(error))
            return
        artifacts = f"{output.tex_path.name} → {output.pdf_path.name if output.pdf_path else '(no PDF)'}"
        if output.diff_pdf_path is not None:
            artifacts += f" + {output.diff_pdf_path.name}"
        self._artifacts_label.setText(artifacts)
        for pdf in (output.pdf_path, output.diff_pdf_path):
            if pdf is not None:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf)))
