"""One pair's dielectric verification: the two choices it collects, and the plan it produces.

The top half of this panel collects the engineering answers only a person can give - which
construction implements the pair's protection, whether that selection has been confirmed, and
what has been declared about its solid insulation. Every one of them is written back as one
complete replacement pair, exactly as the impulse-override editor beside it writes its own.

The bottom half is a rendering of
:class:`~insulation_coordination.calculation.verification_plan.VerificationPlan` and nothing
else. It resolves no rule, re-derives no applicability, recomputes no governing value and
touches no calculated result: a status, a test voltage or an exemption shown here was decided
by the plan, and the panel's only job is to make that decision legible. Recalculation stays on
the button that already owns it, so changing a protection implementation never silently moves
a clearance or a creepage figure.

Three properties are why it is shaped this way.

*Nothing settled looks settled unless it is.* A test the plan could not resolve says
``engineering input required`` in its own row and lists what is missing underneath, and an
exemption that was not granted names the condition that stopped it. There is no row that goes
quiet when its answer is unknown. The requirement row is the sharpest case: it states what the
package requires and whether the selected construction provides it, and where the package could
not be asked it says so rather than restating the construction as though it were the demand.

*Every unresolved input is on screen.* The pair's own, its applications' and its exemption's
are gathered into one list rather than left one click away, because a reader deciding whether
the verification is complete is asking exactly that question.

*The trace is available and out of the way.* It is the whole basis for a planned voltage and
far too long to sit in a form, so it opens on demand and closes again.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.routine_exemption import RoutineExemptionAssessment
from insulation_coordination.calculation.verification_plan import (
    PairVerificationAssessment,
    VerificationPlan,
)
from insulation_coordination.domain.enums import ReviewState
from insulation_coordination.domain.project import PairCase
from insulation_coordination.domain.trace import TraceStep
from insulation_coordination.domain.verification import (
    EvidenceTarget,
    ProtectionImplementation,
    RoutineTestExemptionEvidence,
    SolidInsulationTestData,
    TestApplication,
    TestClassification,
    TestKind,
    WorkingVoltageDetermination,
)
from insulation_coordination.ui.help_indicator import FieldStateBadge, wrapping_label
from insulation_coordination.ui.value_options import populate_combo
from insulation_coordination.ui.voltage_guidance import VoltageGuidanceId

#: Shown for a row the plan has nothing to say about, so a row never disappears and reads as
#: "not part of this verification" when it means "nothing was planned".
EMPTY_VALUE: Final = "—"

#: Shown while no plan could be built at all. Not an error on its own: a project with no
#: approved package loaded is in this state, and so is one whose package cannot answer the
#: verification questions - the caller's notice says which.
NO_PLAN_TEXT: Final = (
    "No dielectric verification plan has been built for this project. The clearance and "
    "creepage results above are unaffected."
)

#: Shown for a pair the plan does not cover, which is every pair that was excluded and every
#: pair with no circuit net in it.
NOT_PLANNED_TEXT: Final = (
    "This pair is not part of the dielectric verification plan: it is either excluded or has "
    "no circuit net in it."
)

#: The value a tri-state declaration takes while nobody has answered it. A blank answer is not
#: a no, and the partial-discharge assessment reads the two differently.
NOT_DECLARED_OPTION: Final = "not declared"

#: Shown where an exemption record states no review date. A record nobody dated is not one
#: anybody granted, and the assessment beside this panel says so in the same words.
NOT_REVIEWED_TEXT: Final = "not reviewed"

#: The label on the control that brings an exemption record into existence. Unticking it
#: removes the record entirely, which is a different state from a record whose conditions are
#: all false: the assessment reports the first as "nothing records that" and the second as "it
#: is not recorded that", and a reviewer chasing them does different things.
CLAIM_EXEMPTION_TEXT: Final = "Claimed for this pair"

#: The stage labels, in the order the issue's pair page lists them.
ROW_LABELS: Final = (
    "Status",
    "Protection requirement",
    "Enhanced protection",
    "Working voltage",
    "Impulse",
    "AC/DC type tests",
    "AC/DC routine tests",
    "Sample tests",
    "Partial discharge",
    "SPD monitoring",
    "Preparation and topology",
    "Routine exemption",
    "Unresolved inputs",
)

#: The two dielectric kinds, which are planned together and read as one row per classification.
_DIELECTRIC_KINDS: Final = (TestKind.AC_DIELECTRIC, TestKind.DC_DIELECTRIC)

_TRACE_BUTTON_TEXT: Final = "Trace"


def _words(value: str) -> str:
    return value.replace("_", " ")


def _options(enum: type[StrEnum]) -> tuple[tuple[str, str], ...]:
    return tuple((_words(member.value), member.value) for member in enum)


def _bullets(lines: Iterable[str]) -> str:
    listed = tuple(lines)
    return "\n".join(f"• {line}" for line in listed) if listed else EMPTY_VALUE


def protection_badge_state(pair: PairCase | None) -> VoltageGuidanceId | None:
    """Whether the protection implementation on show is a selection somebody made.

    ``MANUAL_VALUE`` only once an engineer has confirmed it. A value this application mapped
    during a migration is not a decision anyone took, so it gets no badge at all and the words
    beside it say review is outstanding - a badge reading "Manual" over a mapped guess would
    be the one place in this panel where an unconfirmed answer looked confirmed.
    """

    if pair is None or pair.protection_implementation is None:
        return None
    if pair.protection_review_state is not ReviewState.USER_CONFIRMED:
        return None
    return VoltageGuidanceId.MANUAL_VALUE


def review_text(pair: PairCase | None) -> str:
    """The protection selection in words, including whether anybody has confirmed it."""

    if pair is None or pair.protection_implementation is None:
        return "No protection implementation is selected, so no test can say what it verifies."
    selected = _words(pair.protection_implementation.value)
    if pair.protection_review_state is ReviewState.USER_CONFIRMED:
        return f"{selected}, confirmed."
    return f"{selected}, awaiting confirmation by an engineer."


def application_line(application: TestApplication) -> str:
    """One schedule row as one line: what it is, whether it applies, and at what."""

    parts = [f"{application.test_id}: {_words(application.applicability.value)}"]
    if application.classifications:
        parts.append("/".join(_words(item.value) for item in application.classifications))
    if application.voltage is not None:
        parts.append(f"{application.voltage.value} {application.voltage.unit}")
    for optional in (application.waveform, application.polarity, application.duration):
        if optional:
            parts.append(optional)
    return " — ".join(parts)


def applications_text(applications: Sequence[TestApplication]) -> str:
    return _bullets(application_line(item) for item in applications)


def working_voltage_text(determination: WorkingVoltageDetermination | None) -> str:
    """How far this pair's working-voltage determination has got, and what it still needs."""

    if determination is None:
        return EMPTY_VALUE
    line = _words(determination.status.value)
    quantities = ", ".join(_words(item.value) for item in determination.required_quantities)
    return f"{line} — establishing {quantities}" if quantities else line


def partial_discharge_text(assessment: PairVerificationAssessment | None) -> str:
    if assessment is None or assessment.partial_discharge is None:
        return EMPTY_VALUE
    return _words(assessment.partial_discharge.value)


def spd_monitoring_text(assessment: PairVerificationAssessment | None) -> str:
    """The monitoring one recorded impulse reduction depends on, as issue #36 recorded it.

    Read back rather than re-asked: whether a device inside the equipment owes monitoring was
    settled where the override was resolved, and a second answer here could disagree with it.
    """

    if assessment is None:
        return EMPTY_VALUE
    dependency = assessment.spd_monitoring_dependency
    if dependency is None:
        return "No recorded impulse reduction depends on internal SPD monitoring."
    return (
        f"The reduction recorded at {dependency.affected_location!r} depends on the type test "
        f"{dependency.required_type_test_semantic_id}."
    )


def preparation_text(applications: Sequence[TestApplication]) -> str:
    """Every preparation step the pair's applications ask for, each stated once."""

    steps = dict.fromkeys(step for item in applications for step in item.preparation_steps)
    return _bullets(steps)


def exemption_text(exemption: RoutineExemptionAssessment | None) -> str:
    """Whether the assembled-equipment routine exemption holds, condition by condition.

    Every condition is listed in the order the source states them, satisfied ones included: a
    reader deciding whether to chase an exemption needs to see how far it got, and a list of
    only the failures cannot distinguish "one condition left" from "nothing declared".
    """

    if exemption is None:
        return EMPTY_VALUE
    headline = (
        "Granted; the routine tests below are marked not required and keep their grounds."
        if exemption.exemption_permitted
        else "Not granted; the routine test stays in the schedule."
    )
    conditions = tuple(
        f"{_words(condition.state.value)}: {condition.detail}" for condition in exemption.conditions
    )
    return "\n".join((headline, *(f"• {line}" for line in conditions)))


def requirement_text(assessment: PairVerificationAssessment | None) -> str:
    """What the package requires here, and whether the selected construction provides it.

    The requirement and the verdict are two sentences rather than one word, because this row
    is the one place a reader learns that the two are separate things. A requirement nobody
    could read says so and points at the unresolved inputs; it never borrows the
    implementation's own level and presents it back as the requirement, which is what this row
    did before anything was behind it.
    """

    if assessment is None:
        return EMPTY_VALUE
    if assessment.required_protection is None:
        return (
            "not established from the active package — see the unresolved inputs below; "
            "the selected implementation is not evidence of what is required"
        )
    stated = f"{_words(assessment.required_protection)}, from {assessment.requirement_columns}"
    if assessment.protection_satisfied is None:
        return f"{stated}; whether the selected implementation provides it is outstanding"
    if assessment.protection_satisfied:
        return f"{stated}; met by the selected implementation"
    return f"{stated}; NOT met by the selected implementation"


def unresolved_text(
    assessment: PairVerificationAssessment | None,
    applications: Sequence[TestApplication],
    determination: WorkingVoltageDetermination | None,
) -> str:
    """Everything outstanding for this pair, gathered from every part of its plan.

    One list rather than three, because "is this pair's verification complete" is one question
    and an answer split across three places is one a reader has to assemble.
    """

    lines = dict.fromkeys(
        (
            *(() if assessment is None else assessment.unresolved_inputs),
            *(() if determination is None else determination.unresolved_inputs),
            *(item for application in applications for item in application.unresolved_inputs),
        )
    )
    return _bullets(lines)


def trace_text(applications: Sequence[TestApplication]) -> str:
    """Every trace step behind the pair's applications, under the test that produced it."""

    blocks: list[str] = []
    for application in applications:
        if not application.trace_steps:
            continue
        blocks.append(application.test_id)
        blocks.extend(f"  {_step_line(step)}" for step in application.trace_steps)
    return "\n".join(blocks) if blocks else EMPTY_VALUE


def _step_line(step: TraceStep) -> str:
    return f"{step.semantic_rule_id}: {step.substituted} → {step.output.value} {step.output.unit}"


def _classified(
    applications: Sequence[TestApplication],
    kinds: Sequence[TestKind],
    classification: TestClassification,
) -> tuple[TestApplication, ...]:
    return tuple(
        item
        for item in applications
        if item.test_kind in kinds and classification in item.classifications
    )


def plan_rows(
    assessment: PairVerificationAssessment | None,
    applications: Sequence[TestApplication],
    determination: WorkingVoltageDetermination | None,
) -> dict[str, str]:
    """Every read-only row of the panel, keyed by its label. Pure, so a test reads it directly."""

    sample = tuple(
        item for item in applications if TestClassification.SAMPLE in item.classifications
    )
    return {
        "Status": EMPTY_VALUE if assessment is None else _words(assessment.status.value),
        "Protection requirement": requirement_text(assessment),
        "Enhanced protection": (
            EMPTY_VALUE
            if assessment is None
            else (
                "yes — verified as one combined requirement; the constituent protective means "
                "of a double-insulation construction are not covered separately"
                if assessment.enhanced_protection
                else "no"
            )
        ),
        "Working voltage": working_voltage_text(determination),
        "Impulse": applications_text(
            tuple(item for item in applications if item.test_kind is TestKind.IMPULSE_WITHSTAND)
        ),
        "AC/DC type tests": applications_text(
            _classified(applications, _DIELECTRIC_KINDS, TestClassification.TYPE)
        ),
        "AC/DC routine tests": applications_text(
            _classified(applications, _DIELECTRIC_KINDS, TestClassification.ROUTINE)
        ),
        "Sample tests": applications_text(sample),
        "Partial discharge": partial_discharge_text(assessment),
        "SPD monitoring": spd_monitoring_text(assessment),
        "Preparation and topology": preparation_text(applications),
        "Routine exemption": exemption_text(
            None if assessment is None else assessment.routine_exemption
        ),
        "Unresolved inputs": unresolved_text(assessment, applications, determination),
    }


class VerificationPanel(QWidget):
    """One pair's verification: the choices it collects and the plan those choices produce.

    The three signals carry a replacement field value, never a mutated pair. The pair editor
    that owns them turns each into one complete replacement pair, so a partly applied change
    cannot exist and this panel never holds a copy of the project.
    """

    protection_changed = Signal(object)
    review_state_changed = Signal(object)
    solid_insulation_changed = Signal(object)
    routine_exemption_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._pair: PairCase | None = None

        group = QGroupBox("Dielectric verification")
        outer = QVBoxLayout(group)

        self._notice = wrapping_label(NO_PLAN_TEXT)
        outer.addWidget(self._notice)

        choices = QFormLayout()
        self._protection_combo = QComboBox()
        populate_combo(self._protection_combo, _options(ProtectionImplementation))
        self._protection_combo.currentIndexChanged.connect(self._on_protection_selected)
        self._protection_badge = FieldStateBadge(states=(VoltageGuidanceId.MANUAL_VALUE,))
        protection_row = QHBoxLayout()
        protection_row.setContentsMargins(0, 0, 0, 0)
        protection_row.addWidget(self._protection_combo, 1)
        protection_row.addWidget(self._protection_badge)
        protection_container = QWidget()
        protection_container.setLayout(protection_row)
        choices.addRow("Protection implementation:", protection_container)
        self._review_combo = QComboBox()
        populate_combo(self._review_combo, _options(ReviewState), blank=False)
        self._review_combo.currentIndexChanged.connect(self._on_review_selected)
        choices.addRow("Selection review:", self._review_combo)
        self._review_label = wrapping_label("")
        self._review_label.setObjectName("_protection_review")
        choices.addRow("", self._review_label)

        self._present_combo = self._tristate()
        choices.addRow("Solid insulation present:", self._present_combo)
        self._thickness_edit = QLineEdit()
        self._thickness_edit.editingFinished.connect(self._on_solid_insulation_changed)
        choices.addRow("Minimum thickness (mm):", self._thickness_edit)
        self._layers_edit = QLineEdit()
        self._layers_edit.editingFinished.connect(self._on_solid_insulation_changed)
        choices.addRow("Layer count:", self._layers_edit)
        self._exempt_combo = self._tristate()
        choices.addRow("Material exempt from PD:", self._exempt_combo)
        self._material_edit = QLineEdit()
        self._material_edit.setPlaceholderText("The material record behind a claimed exemption")
        self._material_edit.editingFinished.connect(self._on_solid_insulation_changed)
        choices.addRow("Material reference:", self._material_edit)
        outer.addLayout(choices)

        outer.addWidget(self._exemption_group())

        form = QFormLayout()
        self._values = {label: wrapping_label(EMPTY_VALUE) for label in ROW_LABELS}
        for label, widget in self._values.items():
            form.addRow(f"{label}:", widget)
        outer.addLayout(form)

        self._trace_button = QToolButton()
        self._trace_button.setText(_TRACE_BUTTON_TEXT)
        self._trace_button.setCheckable(True)
        self._trace_button.setAutoRaise(True)
        self._trace_button.toggled.connect(self._on_trace_toggled)
        outer.addWidget(self._trace_button)
        self._trace = wrapping_label(EMPTY_VALUE)
        self._trace.setObjectName("_verification_trace")
        self._trace.setVisible(False)
        outer.addWidget(self._trace)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(group)

    # -- what a test and the page read back --------------------------------------------

    def value_text(self, label: str) -> str:
        return self._values[label].text()

    @property
    def notice_text(self) -> str:
        return "" if self._notice.isHidden() else self._notice.text()

    @property
    def review_summary(self) -> str:
        return self._review_label.text()

    @property
    def protection_badge(self) -> str:
        return self._protection_badge.text()

    @property
    def trace_visible(self) -> bool:
        # ``isHidden`` rather than ``isVisible``: a child of a window nobody has shown is not
        # visible, which would make every headless test of this control read as closed.
        return not self._trace.isHidden()

    @property
    def trace_body(self) -> str:
        return self._trace.text()

    def toggle_trace(self) -> None:
        self._trace_button.setChecked(not self._trace_button.isChecked())

    # -- inputs ------------------------------------------------------------------------

    def set_pair(
        self,
        pair: PairCase | None,
        plan: VerificationPlan | None = None,
        notice: str = "",
    ) -> None:
        """Show ``pair``'s choices, and whatever ``plan`` decided about it.

        ``plan`` is read and never rebuilt here: the caller owns when a plan is computed, so
        opening this panel cannot change a schedule and editing a choice cannot change a
        calculated result. ``notice`` carries whatever only the caller knows about an absent
        plan - the rule package's refusal, most usefully.
        """

        self._pair = pair
        assessment = _assessment_for(plan, pair)
        applications = _applications_for(plan, assessment)
        determination = _determination_for(plan, pair)
        self._notice.setText(
            notice
            or (NOT_PLANNED_TEXT if plan is not None and assessment is None else NO_PLAN_TEXT)
        )
        self._notice.setVisible(bool(notice) or assessment is None)
        rows = plan_rows(assessment, applications, determination)
        for label, widget in self._values.items():
            widget.setText(rows[label])
        self._trace.setText(trace_text(applications))
        self._show_choices(pair)

    # -- internals ---------------------------------------------------------------------

    def _exemption_group(self) -> QGroupBox:
        """The controls that let an exemption actually be granted from inside the application.

        Until this existed the panel could show the conditions and collect none of them, so an
        exemption could not be claimed at all. Every field here is one the assessment beside it
        already reads; nothing new is invented, and no control decides anything - a ticked
        condition with an empty reference is still reported as evidence missing.

        The review timestamp is stamped by the application when the record is written, the way
        an evidence entry's is. The record's date is therefore "when this claim was last
        edited", which is the only date this application can honestly know.
        """

        group = QGroupBox("Assembled-equipment routine test exemption")
        form = QFormLayout(group)
        self._exemption_claimed = QCheckBox(CLAIM_EXEMPTION_TEXT)
        form.addRow("", self._exemption_claimed)
        self._subassemblies_check = QCheckBox("recorded")
        form.addRow("Subassemblies routine tested:", self._subassemblies_check)
        self._subassembly_edit = QLineEdit()
        self._subassembly_edit.setPlaceholderText("The evidence behind it")
        form.addRow("Subassembly evidence:", self._subassembly_edit)
        self._assembly_check = QCheckBox("recorded")
        form.addRow("Assembly cannot compromise it:", self._assembly_check)
        self._assembly_edit = QLineEdit()
        self._assembly_edit.setPlaceholderText("The justification behind it")
        form.addRow("Assembly justification:", self._assembly_edit)
        self._type_test_check = QCheckBox("recorded")
        form.addRow("Assembled type test passed:", self._type_test_check)
        self._type_test_edit = QLineEdit()
        self._type_test_edit.setPlaceholderText("The report reference")
        form.addRow("Type test evidence:", self._type_test_edit)
        self._reviewer_edit = QLineEdit()
        self._reviewer_edit.setPlaceholderText("Who granted it")
        form.addRow("Reviewer:", self._reviewer_edit)
        self._reviewed_label = wrapping_label(NOT_REVIEWED_TEXT)
        self._reviewed_label.setObjectName("_exemption_reviewed_at")
        form.addRow("Reviewed at:", self._reviewed_label)
        for widget in self._exemption_widgets():
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(lambda _checked: self._on_exemption_changed())
            elif isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self._on_exemption_changed)
        return group

    def _exemption_widgets(self) -> tuple[QWidget, ...]:
        return (
            self._exemption_claimed,
            self._subassemblies_check,
            self._subassembly_edit,
            self._assembly_check,
            self._assembly_edit,
            self._type_test_check,
            self._type_test_edit,
            self._reviewer_edit,
        )

    def _on_exemption_changed(self) -> None:
        """Hand back a whole replacement record, or ``None`` where the claim was withdrawn."""

        if not self._exemption_claimed.isChecked():
            self.routine_exemption_changed.emit(None)
            return
        self.routine_exemption_changed.emit(
            RoutineTestExemptionEvidence(
                subassemblies_routine_tested=self._subassemblies_check.isChecked(),
                subassembly_evidence_reference=self._subassembly_edit.text().strip(),
                assembly_cannot_compromise_insulation=self._assembly_check.isChecked(),
                assembly_justification=self._assembly_edit.text().strip(),
                assembled_type_test_passed=self._type_test_check.isChecked(),
                assembled_type_test_reference=self._type_test_edit.text().strip(),
                reviewer=self._reviewer_edit.text().strip(),
                reviewed_at=datetime.now(UTC),
            )
        )

    def _show_exemption(self, pair: PairCase | None) -> None:
        record = None if pair is None else pair.routine_exemption
        for widget in self._exemption_widgets():
            widget.blockSignals(True)
        self._exemption_claimed.setChecked(record is not None)
        self._subassemblies_check.setChecked(
            record is not None and record.subassemblies_routine_tested
        )
        self._subassembly_edit.setText(
            "" if record is None else record.subassembly_evidence_reference
        )
        self._assembly_check.setChecked(
            record is not None and record.assembly_cannot_compromise_insulation
        )
        self._assembly_edit.setText("" if record is None else record.assembly_justification)
        self._type_test_check.setChecked(record is not None and record.assembled_type_test_passed)
        self._type_test_edit.setText("" if record is None else record.assembled_type_test_reference)
        self._reviewer_edit.setText("" if record is None else record.reviewer)
        for widget in self._exemption_widgets():
            widget.blockSignals(False)
        self._reviewed_label.setText(
            NOT_REVIEWED_TEXT
            if record is None or record.reviewed_at is None
            else record.reviewed_at.isoformat()
        )

    @property
    def exemption_reviewed_text(self) -> str:
        return self._reviewed_label.text()

    @property
    def exemption_claimed(self) -> bool:
        return self._exemption_claimed.isChecked()

    def _tristate(self) -> QComboBox:
        """A declaration with three answers, because "not declared" is not "no"."""

        combo = QComboBox()
        combo.addItem(NOT_DECLARED_OPTION, None)
        combo.addItem("yes", True)
        combo.addItem("no", False)
        combo.currentIndexChanged.connect(lambda _index: self._on_solid_insulation_changed())
        return combo

    def _show_choices(self, pair: PairCase | None) -> None:
        widgets: tuple[QWidget, ...] = (
            self._protection_combo,
            self._review_combo,
            self._present_combo,
            self._thickness_edit,
            self._layers_edit,
            self._exempt_combo,
            self._material_edit,
        )
        for widget in widgets:
            widget.blockSignals(True)
        implementation = None if pair is None else pair.protection_implementation
        self._protection_combo.setCurrentIndex(
            _index_of(
                self._protection_combo,
                None if implementation is None else implementation.value,
            )
        )
        review = ReviewState.NEEDS_REVIEW if pair is None else pair.protection_review_state
        self._review_combo.setCurrentIndex(_index_of(self._review_combo, review.value))
        declared = None if pair is None else pair.solid_insulation
        self._present_combo.setCurrentIndex(
            _index_of(self._present_combo, None if declared is None else declared.present)
        )
        self._exempt_combo.setCurrentIndex(
            _index_of(self._exempt_combo, None if declared is None else declared.material_pd_exempt)
        )
        self._thickness_edit.setText(
            ""
            if declared is None or declared.minimum_thickness_mm is None
            else str(declared.minimum_thickness_mm)
        )
        self._layers_edit.setText(
            "" if declared is None or declared.layer_count is None else str(declared.layer_count)
        )
        self._material_edit.setText(
            ""
            if declared is None or declared.material_reference is None
            else declared.material_reference
        )
        for widget in widgets:
            widget.blockSignals(False)
        self._protection_badge.set_state(protection_badge_state(pair))
        self._review_label.setText(review_text(pair))
        self._show_exemption(pair)

    def _on_protection_selected(self, index: int) -> None:
        data = self._protection_combo.itemData(index)
        self.protection_changed.emit(None if data is None else ProtectionImplementation(str(data)))

    def _on_review_selected(self, index: int) -> None:
        self.review_state_changed.emit(ReviewState(str(self._review_combo.itemData(index))))

    def _on_solid_insulation_changed(self) -> None:
        """Rebuild the declaration through its own validation and hand it back whole.

        The model refuses a claimed material exemption with no material reference behind it,
        and that refusal is the message a user reads: the rule is written once, where the
        declaration is defined.
        """

        try:
            declared = SolidInsulationTestData(
                present=self._present_combo.currentData(),
                minimum_thickness_mm=_decimal(self._thickness_edit.text()),
                material_pd_exempt=self._exempt_combo.currentData(),
                layer_count=_integer(self._layers_edit.text()),
                material_reference=self._material_edit.text().strip() or None,
            )
        except (InvalidOperation, ValueError) as error:
            QMessageBox.warning(self, "Solid insulation", str(error))
            self._show_choices(self._pair)
            return
        self.solid_insulation_changed.emit(declared)

    def _on_trace_toggled(self, shown: bool) -> None:
        self._trace.setVisible(shown)


def _index_of(combo: QComboBox, value: object) -> int:
    """The row carrying ``value``, or the first. ``findData`` does not match ``None``."""

    return next(
        (index for index in range(combo.count()) if combo.itemData(index) == value),
        0,
    )


def _decimal(text: str) -> Decimal | None:
    stripped = text.strip()
    return Decimal(stripped) if stripped else None


def _integer(text: str) -> int | None:
    stripped = text.strip()
    return int(stripped) if stripped else None


def _assessment_for(
    plan: VerificationPlan | None, pair: PairCase | None
) -> PairVerificationAssessment | None:
    if plan is None or pair is None:
        return None
    return next((item for item in plan.pair_assessments if item.pair_id == pair.id), None)


def _applications_for(
    plan: VerificationPlan | None, assessment: PairVerificationAssessment | None
) -> tuple[TestApplication, ...]:
    if plan is None or assessment is None:
        return ()
    wanted = set(assessment.test_ids)
    return tuple(item for item in plan.test_applications if item.test_id in wanted)


def _determination_for(
    plan: VerificationPlan | None, pair: PairCase | None
) -> WorkingVoltageDetermination | None:
    if plan is None or pair is None:
        return None
    target = EvidenceTarget(pair_id=pair.id)
    return next((item for item in plan.working_voltage if item.target == target), None)


__all__ = [
    "EMPTY_VALUE",
    "NOT_DECLARED_OPTION",
    "NOT_PLANNED_TEXT",
    "NO_PLAN_TEXT",
    "ROW_LABELS",
    "VerificationPanel",
    "application_line",
    "applications_text",
    "exemption_text",
    "partial_discharge_text",
    "plan_rows",
    "preparation_text",
    "protection_badge_state",
    "requirement_text",
    "review_text",
    "spd_monitoring_text",
    "trace_text",
    "unresolved_text",
    "working_voltage_text",
]
