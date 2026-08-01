"""Report page: group controls, validation summary, and offline .tex/PDF export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
)
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.report.compiler import CompilerCommand, compile_pdf
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import ReportBuildError, build_report_model


@dataclass(frozen=True)
class ReportOutput:
    """Generated artifacts for one report export."""

    tex_path: Path
    pdf_path: Path | None
    log_path: Path | None


class ReportPage(QWidget):
    """Shows automatic groups, document metadata, and blocked/final report state."""

    def __init__(self, tectonic: CompilerCommand | None = None) -> None:
        super().__init__()
        self._project: Project | None = None
        self._rules: RulePackage | None = None
        self._results: tuple[PairResult, ...] = ()
        self._groups: tuple[CalculationGroup, ...] = ()
        self._blocking: tuple[str, ...] = ()
        self._tectonic = tectonic

        layout = QVBoxLayout(self)

        self._title_label = QLabel("Report")
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14pt;")
        layout.addWidget(self._title_label)

        metadata_group = QGroupBox("Document metadata")
        metadata_layout = QFormLayout(metadata_group)
        self._document_number_edit = QLineEdit()
        metadata_layout.addRow("Document number:", self._document_number_edit)
        self._revision_edit = QLineEdit()
        metadata_layout.addRow("Revision:", self._revision_edit)
        layout.addWidget(metadata_group)

        self._summary_label = QLabel("No project loaded")
        layout.addWidget(self._summary_label)

        groups_group = QGroupBox("Automatic groups")
        groups_layout = QVBoxLayout(groups_group)
        self._groups_list = QListWidget()
        groups_layout.addWidget(self._groups_list)
        layout.addWidget(groups_group)

        export_row = QHBoxLayout()
        self._generate_button = QPushButton("Generate .tex and PDF…")
        self._generate_button.setEnabled(False)
        self._generate_button.clicked.connect(self._on_generate_clicked)
        export_row.addWidget(self._generate_button)
        self._artifacts_label = QLabel("")
        export_row.addWidget(self._artifacts_label, 1)
        layout.addLayout(export_row)

    @property
    def generate_enabled(self) -> bool:
        return self._generate_button.isEnabled()

    @property
    def blocking_summary(self) -> str:
        return "; ".join(self._blocking) if self._blocking else ""

    @property
    def validation_summary(self) -> str:
        if self._project is None:
            return "No project loaded"
        if self._blocking:
            return self.blocking_summary
        return "All pairs calculated"

    @property
    def group_count(self) -> int:
        return len(self._groups)

    def load_project(self, project: Project) -> None:
        self._project = project
        self._document_number_edit.setText(project.metadata.document_number)
        self._revision_edit.setText(project.metadata.revision)
        self._refresh()

    def load_rules(self, rules: RulePackage) -> None:
        self._rules = rules
        self._refresh()

    def generate(self, destination: Path) -> ReportOutput:
        """Recalculate every pair against the installed rules and render + compile."""
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        if self._project is None or self._rules is None:
            raise RuntimeError("Report generation requires a project and rules")
        if self._blocking:
            raise RuntimeError(self.blocking_summary)
        tectonic = self._tectonic or find_tectonic()
        if tectonic is None:
            raise RuntimeError(
                "No Tectonic executable found: pass a path or install Tectonic on PATH"
            )
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
        tex.write_text(render_latex(model), encoding="utf-8")
        result = compile_pdf(tex, destination / f"{self._basename()}.pdf", tectonic)
        return ReportOutput(
            tex_path=tex,
            pdf_path=result.pdf_path,
            log_path=result.log_path if result.pdf_path is not None else None,
        )

    def export(self, destination: Path) -> ReportOutput:
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        return self.generate(destination)

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
            return
        results: list[PairResult] = []
        blocking: list[str] = []
        for pair in self._project.pairs:
            try:
                effective = resolve_effective_case(self._project.defaults, pair)
                results.append(calculate_pair(effective, self._rules))
            except CalculationError as error:
                blocking.append(f"{pair.id}: {error}")
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
        self._summary_label.setText(self.validation_summary)
        self._groups_list.clear()
        for group in self._groups:
            label = (
                f"{group.group_id[:16]}… ({len(group.pair_ids)} pair"
                f"{'s' if len(group.pair_ids) != 1 else ''})"
            )
            self._groups_list.addItem(label)

    def _on_generate_clicked(self) -> None:
        if self._project is None:
            return
        directory = QFileDialog.getExistingDirectory(self, "Export Report")
        if not directory:
            return
        try:
            output = self.export(Path(directory))
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Generate Report", str(error))
            return
        self._artifacts_label.setText(
            f"{output.tex_path.name} → {output.pdf_path.name if output.pdf_path else '(no PDF)'}"
        )


def find_tectonic() -> Path | None:
    """Locate a bundled Tectonic first, then a system installation on PATH."""
    import shutil

    bundled = _bundled_tectonic()
    if bundled is not None:
        return bundled
    found = shutil.which("tectonic")
    return Path(found) if found else None


def _bundled_tectonic() -> Path | None:
    import sys
    from pathlib import Path as _Path

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        base = _Path(getattr(sys, "_MEIPASS", _Path(sys.executable).parent))
        candidates.extend(
            (
                base / "tectonic",
                base / "tectonic.exe",
                base / "tectonic" / "tectonic",
            )
        )
    return next((candidate for candidate in candidates if candidate.is_file()), None)
