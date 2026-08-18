"""The project's dielectric test schedule, on the page that generates the report.

One row is one deduplicated
:class:`~insulation_coordination.domain.verification.TestApplication`, projected by the same
:func:`~insulation_coordination.report.human_view.human_test_row` the document uses. That is
the point of importing it rather than writing a second projection: what an engineer signs off
on screen and what the report prints are the same rows, in the same words, or they are a bug.

Three properties are deliberate.

*Verification completeness is stated separately from calculation completeness.* The report page
above this panel already says whether every pair calculated; this panel says whether every test
is planned, and says in the same breath that an unfinished plan does not stop the report. The
generate button never reads this panel.

*No row goes quiet.* A test whose voltage, classification or duration the package could not
resolve keeps its row and says so in the cell, and the last column names what is outstanding.
A row a granted exemption excused stays too, marked not required.

*The panel renders and never plans.* It takes a plan and shows it. Building one is the page's
job, exactly as building a supply derivation is.
"""

from __future__ import annotations

from typing import Final

from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.verification_plan import VerificationPlan
from insulation_coordination.domain.display import pair_label
from insulation_coordination.domain.project import Project
from insulation_coordination.report.human_view import (
    VERIFICATION_UNAVAILABLE_PREFIX,
    HumanTestRow,
    human_test_row,
    verification_statement,
)
from insulation_coordination.ui.help_indicator import wrapping_label

COLUMN_LABELS: Final = (
    "Test",
    "High side",
    "Low side",
    "Voltage",
    "Classification",
    "Applicability",
    "Pairs covered",
    "Outstanding",
)

#: Shown while no plan exists at all, which is the state of a page with no project or no
#: approved package loaded. Not an error: the caller's notice says which.
NO_PLAN_TEXT: Final = (
    "No dielectric verification plan has been built for this project. The clearance and "
    "creepage report is unaffected."
)


class TestSchedulePanel(QWidget):
    """Every planned dielectric test, and how far the verification as a whole has got."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[HumanTestRow, ...] = ()

        group = QGroupBox("Dielectric test schedule")
        layout = QVBoxLayout(group)

        self._summary = wrapping_label(NO_PLAN_TEXT)
        self._summary.setObjectName("_verification_completeness")
        layout.addWidget(self._summary)

        self._table = QTableWidget(0, len(COLUMN_LABELS))
        self._table.setHorizontalHeaderLabels(COLUMN_LABELS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)

    # -- what a test and the page read back ---------------------------------------------

    @property
    def completeness_text(self) -> str:
        """How far the verification has got, in words, never as a colour or a count alone."""

        return self._summary.text()

    @property
    def row_count(self) -> int:
        return self._table.rowCount()

    def row_text(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return "" if item is None else item.text()

    def row_of(self, test_id: str) -> int:
        return next(
            (index for index, entry in enumerate(self._rows) if entry.test_id == test_id),
            -1,
        )

    # -- inputs -------------------------------------------------------------------------

    def set_plan(
        self,
        plan: VerificationPlan | None,
        project: Project | None,
        notice: str = "",
    ) -> None:
        """Show ``plan``'s schedule, or say why there is none.

        ``notice`` is whatever only the caller knows about an absent plan - the rule package's
        own refusal, most usefully. It is stated rather than swallowed: a table that was empty
        because nothing could be read looks identical to one that was empty because nothing is
        required.
        """

        self._rows = _rows(plan, project)
        self._table.setRowCount(len(self._rows))
        for index, entry in enumerate(self._rows):
            for column, text in enumerate(_cells(entry)):
                self._table.setItem(index, column, QTableWidgetItem(text))
        self._table.resizeColumnsToContents()
        if plan is None:
            self._summary.setText(
                f"{VERIFICATION_UNAVAILABLE_PREFIX}{notice}" if notice else NO_PLAN_TEXT
            )
            return
        self._summary.setText(verification_statement(plan))


def _rows(plan: VerificationPlan | None, project: Project | None) -> tuple[HumanTestRow, ...]:
    if plan is None or project is None:
        return ()
    net_names = {net.id: net.name for net in project.net_classes}
    pair_labels = {str(pair.id): pair_label(project, pair) for pair in project.pairs}
    return tuple(
        human_test_row(application, net_names, pair_labels)
        for application in plan.test_applications
    )


def _cells(entry: HumanTestRow) -> tuple[str, ...]:
    return (
        entry.test,
        entry.high_side,
        entry.low_side,
        entry.voltage,
        entry.classification,
        entry.applicability,
        entry.covered_pairs,
        "; ".join(entry.unresolved),
    )


__all__ = ["COLUMN_LABELS", "NO_PLAN_TEXT", "TestSchedulePanel"]
