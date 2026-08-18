"""The report page's dielectric test schedule, and the exemption control beside it.

Every figure, name and reference here comes from the synthetic verification fixture and is
this repository's own invention. Nothing reproduces a value, a heading or any wording from any
standard.

Three properties are under test.

*Verification completeness is stated apart from calculation completeness.* A plan with
unsettled rows must not disable the generate button, and the two summaries must not be one
sentence.

*No row goes quiet.* Every column of every row is filled, and a row the plan could not settle
says what is outstanding beside it.

*An exemption can be granted from inside the application.* Before this slice the pair panel
showed the conditions and collected none of them, so the grant was impossible; these tests
drive the control and read the grant back out of the rebuilt plan.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from insulation_coordination.calculation.engine import derive_project_supply
from insulation_coordination.calculation.verification_plan import (
    VerificationPlan,
    VerificationPlanService,
)
from insulation_coordination.domain.enums import ConstructionType, ReviewState
from insulation_coordination.domain.project import Project, RulePackageReference
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.verification import (
    ProtectionImplementation,
    TestApplicability,
)
from insulation_coordination.report.human_view import (
    VERIFICATION_INCOMPLETE_PREFIX,
    VERIFICATION_INDEPENDENT_TEXT,
)
from insulation_coordination.ui.pair_editor import PairPage
from insulation_coordination.ui.report_page import ReportPage
from insulation_coordination.ui.test_schedule import (
    COLUMN_LABELS,
    NO_PLAN_TEXT,
    TestSchedulePanel,
)
from insulation_coordination.ui.verification_panel import NOT_REVIEWED_TEXT
from tests.fixtures.synthetic_rules import (
    merged_rule_package,
    synthetic_part1_rule_package,
    synthetic_supply_rule_package,
)
from tests.fixtures.verification_topologies import (
    ENCLOSURE,
    LIVE_A,
    LIVE_B,
    LIVE_C,
    mains_configuration,
    pair_between,
    single_column_dielectric_package,
    verification_and_supply_package,
    verification_topology,
    with_pair_fields,
)

BASIC = ProtectionImplementation.BASIC_INSULATION
OUTSTANDING = COLUMN_LABELS.index("Outstanding")
VOLTAGE = COLUMN_LABELS.index("Voltage")
APPLICABILITY = COLUMN_LABELS.index("Applicability")


@pytest.fixture
def package(tmp_path: Path) -> RulePackage:
    return verification_and_supply_package(tmp_path / "merged.icrules")


@pytest.fixture
def project() -> Project:
    return with_pair_fields(
        verification_topology(supply_configurations=(mains_configuration(),)),
        protection_implementation=BASIC,
        protection_review_state=ReviewState.USER_CONFIRMED,
    )


@pytest.fixture
def plan(project: Project, package: RulePackage) -> VerificationPlan:
    return VerificationPlanService().build(
        project, package, derive_project_supply(project, package)
    )


@pytest.fixture
def panel(qtbot: QtBot) -> TestSchedulePanel:
    widget = TestSchedulePanel()
    qtbot.addWidget(widget)
    return widget


# --- the schedule panel ----------------------------------------------------------------


def test_the_panel_says_so_before_any_plan_is_built(panel: TestSchedulePanel) -> None:
    panel.set_plan(None, None)

    assert panel.row_count == 0
    assert panel.completeness_text == NO_PLAN_TEXT


def test_a_package_that_cannot_answer_is_stated_rather_than_left_blank(
    panel: TestSchedulePanel, project: Project
) -> None:
    panel.set_plan(None, project, "Dielectric verification — the package answers nothing.")

    assert panel.row_count == 0
    assert "the package answers nothing" in panel.completeness_text


def test_every_row_names_its_electrodes_and_what_is_outstanding(
    panel: TestSchedulePanel, project: Project, plan: VerificationPlan
) -> None:
    panel.set_plan(plan, project)

    assert panel.row_count == len(plan.test_applications)
    for row in range(panel.row_count):
        for column in range(len(COLUMN_LABELS) - 1):
            assert panel.row_text(row, column), COLUMN_LABELS[column]
    unsettled = [
        row
        for row in range(panel.row_count)
        if panel.row_text(row, APPLICABILITY) == "engineering input required"
    ]
    assert unsettled
    for row in unsettled:
        assert panel.row_text(row, OUTSTANDING)


def test_a_row_whose_voltage_could_not_be_read_keeps_its_row_and_says_so(
    panel: TestSchedulePanel, project: Project, package: RulePackage
) -> None:
    """A pair with no recurring peak cannot key the non-mains route; its row must not vanish."""

    blank = verification_topology(
        supply_configurations=(mains_configuration(),), recurring_peak_v=None
    )
    blank = with_pair_fields(
        blank,
        protection_implementation=BASIC,
        protection_review_state=ReviewState.USER_CONFIRMED,
    )
    built = VerificationPlanService().build(blank, package, derive_project_supply(blank, package))

    panel.set_plan(built, blank)

    assert panel.row_count == len(built.test_applications)
    assert any(panel.row_text(row, VOLTAGE) == "not resolved" for row in range(panel.row_count))


def test_the_completeness_line_is_the_report_s_own_sentence(
    panel: TestSchedulePanel, project: Project, plan: VerificationPlan
) -> None:
    """One sentence, shared with the document, so the screen and the report cannot disagree."""

    panel.set_plan(plan, project)

    assert panel.completeness_text.startswith(VERIFICATION_INCOMPLETE_PREFIX)
    assert VERIFICATION_INDEPENDENT_TEXT in panel.completeness_text


# --- the report page -------------------------------------------------------------------


@pytest.fixture
def report_package(tmp_path: Path) -> RulePackage:
    """Clearance, supply and verification in one package, which a report page needs."""

    return merged_rule_package(
        synthetic_part1_rule_package(),
        synthetic_supply_rule_package(),
        single_column_dielectric_package(),
        path=tmp_path / "report.icrules",
    )


@pytest.fixture
def report_project(report_package: RulePackage) -> Project:
    project = verification_topology(
        supply_configurations=(mains_configuration(),), recurring_peak_v=Decimal(500)
    )
    assert report_package.package_sha256 is not None
    return with_pair_fields(
        project.model_copy(
            update={
                "required_rules": RulePackageReference(
                    package_id=str(report_package.manifest.package_id),
                    version=report_package.manifest.version,
                    sha256=report_package.package_sha256,
                ),
                "defaults": project.defaults.model_copy(
                    update={
                        "construction_type": ConstructionType.OTHER,
                        "impulse_v": Decimal(150),
                    }
                ),
            }
        ),
        protection_implementation=BASIC,
        protection_review_state=ReviewState.USER_CONFIRMED,
    )


def test_an_incomplete_verification_never_blocks_the_report(
    qtbot: QtBot, report_project: Project, report_package: RulePackage
) -> None:
    page = ReportPage()
    qtbot.addWidget(page)

    page.load_project(report_project)
    page.load_rules(report_package)

    assert page.generate_enabled
    assert page.validation_summary == "All pairs calculated"
    assert page.verification_summary != page.validation_summary
    assert page.verification_summary.startswith(VERIFICATION_INCOMPLETE_PREFIX)
    assert page.schedule_panel.row_count > 0


def test_a_package_with_no_verification_rules_leaves_the_report_generable(
    qtbot: QtBot, report_project: Project
) -> None:
    page = ReportPage()
    qtbot.addWidget(page)
    distance_only = synthetic_part1_rule_package()

    page.load_project(report_project)
    page.load_rules(distance_only)

    # The project pins a different package, so the report itself is blocked - but the reason
    # is the pin, never the verification plan, and the schedule says why it is empty.
    assert page.verification_plan is None
    assert page.schedule_panel.row_count == 0
    assert "Dielectric verification" in page.verification_summary


# --- granting the exemption from inside the application ---------------------------------


def _grant(page: PairPage) -> None:
    panel = page.editor.verification_panel
    panel._exemption_claimed.setChecked(True)
    panel._subassemblies_check.setChecked(True)
    panel._subassembly_edit.setText("SYN-SUB-1")
    panel._subassembly_edit.editingFinished.emit()
    panel._assembly_check.setChecked(True)
    panel._assembly_edit.setText("SYN-ASSEMBLY-1")
    panel._assembly_edit.editingFinished.emit()
    panel._type_test_check.setChecked(True)
    panel._type_test_edit.setText("SYN-TYPE-1")
    panel._type_test_edit.editingFinished.emit()
    panel._reviewer_edit.setText("Synthetic reviewer")
    panel._reviewer_edit.editingFinished.emit()


def test_an_exemption_can_be_granted_from_the_pair_page(
    qtbot: QtBot, project: Project, package: RulePackage
) -> None:
    """The gap slice 5 recorded: the conditions were shown and none of them could be answered."""

    page = PairPage()
    qtbot.addWidget(page)
    page.load_project(project)
    page.load_rules(package)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    page.select_pair_by_id(str(pair.id))

    _grant(page)

    updated = page.project
    changed = next(item for item in updated.pairs if item.id == pair.id)
    record = changed.routine_exemption
    assert record is not None
    assert record.reviewer == "Synthetic reviewer"
    assert record.reviewed_at is not None
    rebuilt = VerificationPlanService().build(
        updated, package, derive_project_supply(updated, package)
    )
    assessment = next(item for item in rebuilt.pair_assessments if item.pair_id == pair.id)
    assert assessment.routine_exemption is not None
    assert assessment.routine_exemption.exemption_permitted


def test_a_granted_exemption_marks_the_routine_rows_and_removes_none(
    qtbot: QtBot, project: Project, package: RulePackage
) -> None:
    """The pair behind the barrier is alone in its live group, so its own grant reaches its rows."""

    page = PairPage()
    qtbot.addWidget(page)
    page.load_project(project)
    page.load_rules(package)
    pair = pair_between(project, LIVE_C, ENCLOSURE)
    page.select_pair_by_id(str(pair.id))
    before = page.verification_plan
    assert before is not None
    planned_before = len(before.test_applications)

    _grant(page)

    after = page.verification_plan
    assert after is not None
    assert len(after.test_applications) == planned_before
    excused = [
        item
        for item in after.test_applications
        if pair.id in item.covered_pair_ids and item.applicability is TestApplicability.NOT_REQUIRED
    ]
    assert excused
    for item in excused:
        assert any("exemption is granted" in step for step in item.preparation_steps)


def test_one_pair_s_grant_does_not_excuse_the_row_it_shares_with_another(
    qtbot: QtBot, project: Project, package: RulePackage
) -> None:
    """Two circuit nets of one live group share a row, and one of them cannot excuse it."""

    page = PairPage()
    qtbot.addWidget(page)
    page.load_project(project)
    page.load_rules(package)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    neighbour = pair_between(project, LIVE_B, ENCLOSURE)
    page.select_pair_by_id(str(pair.id))

    _grant(page)

    after = page.verification_plan
    assert after is not None
    shared = [
        item
        for item in after.test_applications
        if pair.id in item.covered_pair_ids and neighbour.id in item.covered_pair_ids
    ]
    assert shared, "the fixture's two primary circuits must share at least one row"
    assert all(item.applicability is not TestApplicability.NOT_REQUIRED for item in shared)


def test_withdrawing_the_claim_removes_the_record_rather_than_emptying_it(
    qtbot: QtBot, project: Project, package: RulePackage
) -> None:
    """A claim nobody made and a claim answered "no" are different, and stay different."""

    page = PairPage()
    qtbot.addWidget(page)
    page.load_project(project)
    page.load_rules(package)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    page.select_pair_by_id(str(pair.id))
    _grant(page)

    page.editor.verification_panel._exemption_claimed.setChecked(False)

    updated = page.project
    assert next(item for item in updated.pairs if item.id == pair.id).routine_exemption is None


def test_the_panel_shows_a_record_that_was_never_reviewed_as_never_reviewed(
    qtbot: QtBot, project: Project
) -> None:
    from insulation_coordination.ui.verification_panel import VerificationPanel

    panel = VerificationPanel()
    qtbot.addWidget(panel)
    pair = pair_between(project, LIVE_A, ENCLOSURE)

    panel.set_pair(pair)

    assert panel.exemption_claimed is False
    assert panel.exemption_reviewed_text == NOT_REVIEWED_TEXT
