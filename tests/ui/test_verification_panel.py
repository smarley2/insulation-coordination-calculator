"""The pair page's dielectric verification panel.

Every figure, name and reference here comes from the synthetic verification fixture, whose
bands and cell values are invented for this repository. Nothing reproduces a value, a heading
or any wording from any standard: what is under test is that the panel shows what the plan
decided, that it says so when the plan could not decide, and that nothing it does moves a
calculated result.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pytestqt.qtbot import QtBot

from insulation_coordination.calculation.engine import derive_project_supply
from insulation_coordination.calculation.impulse_override import SpdMonitoringDependency
from insulation_coordination.calculation.routine_exemption import (
    ExemptionCondition,
    ExemptionConditionState,
    RoutineExemptionAssessment,
)
from insulation_coordination.calculation.verification_plan import (
    PairVerificationAssessment,
    VerificationPlan,
    VerificationPlanService,
)
from insulation_coordination.domain.enums import DecisiveVoltageClass, ReviewState
from insulation_coordination.domain.project import PairCase, Project
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.supply import SpdDevicePlacement
from insulation_coordination.domain.verification import (
    ProtectionImplementation,
    SolidInsulationTestData,
    TestApplicability,
    TestReferenceKind,
)
from insulation_coordination.ui.pair_editor import PairEditor, PairPage
from insulation_coordination.ui.verification_panel import (
    EMPTY_VALUE,
    NO_PLAN_TEXT,
    NOT_PLANNED_TEXT,
    ROW_LABELS,
    VerificationPanel,
    exemption_text,
    plan_rows,
    protection_badge_state,
    review_text,
    spd_monitoring_text,
)
from tests.fixtures.verification_topologies import (
    ENCLOSURE,
    LIVE_A,
    declared_solid_insulation,
    mains_configuration,
    pair_between,
    verification_and_supply_package,
    verification_topology,
    with_pair_fields,
)

BASIC = ProtectionImplementation.BASIC_INSULATION
REINFORCED = ProtectionImplementation.REINFORCED_INSULATION


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


def _build(project: Project, package: RulePackage) -> VerificationPlan:
    return VerificationPlanService().build(
        project, package, derive_project_supply(project, package)
    )


@pytest.fixture
def plan(project: Project, package: RulePackage) -> VerificationPlan:
    return _build(project, package)


@pytest.fixture
def panel(qtbot: QtBot) -> VerificationPanel:
    widget = VerificationPanel()
    qtbot.addWidget(widget)
    return widget


def _planned_pair(project: Project) -> PairCase:
    return pair_between(project, LIVE_A, ENCLOSURE)


def _reclassified(
    project: Project, dvc: DecisiveVoltageClass = DecisiveVoltageClass.DVC_C
) -> Project:
    """The same project with ``LIVE_A`` in another class, which moves its Table 3 row."""

    return project.model_copy(
        update={
            "net_classes": tuple(
                net.model_copy(update={"decisive_voltage_class": dvc}) if net.id == LIVE_A else net
                for net in project.net_classes
            )
        }
    )


def test_the_panel_shows_the_status_the_plan_decided(
    panel: VerificationPanel, project: Project, plan: VerificationPlan
) -> None:
    pair = _planned_pair(project)
    assessment = next(item for item in plan.pair_assessments if item.pair_id == pair.id)

    panel.set_pair(pair, plan)

    assert panel.value_text("Status") == assessment.status.value.replace("_", " ")
    assert panel.notice_text == ""


def test_every_unresolved_input_is_named_where_the_plan_could_not_settle(
    panel: VerificationPanel, package: RulePackage
) -> None:
    """A pair with no protection implementation cannot say what its tests verify, and the
    panel repeats every reason rather than reporting one status and stopping."""

    project = verification_topology(supply_configurations=(mains_configuration(),))
    plan = _build(project, package)
    pair = _planned_pair(project)
    assessment = next(item for item in plan.pair_assessments if item.pair_id == pair.id)

    panel.set_pair(pair, plan)

    shown = panel.value_text("Unresolved inputs")
    assert assessment.unresolved_inputs
    for message in assessment.unresolved_inputs:
        assert message in shown
    assert "no protection implementation selected" in shown
    assert panel.value_text("Status") == "engineering review required"


def test_a_test_the_plan_could_not_settle_says_so_on_its_own_row(
    panel: VerificationPanel, project: Project, plan: VerificationPlan
) -> None:
    pair = _planned_pair(project)
    assessment = next(item for item in plan.pair_assessments if item.pair_id == pair.id)
    unsettled = tuple(
        item
        for item in plan.test_applications
        if item.test_id in assessment.test_ids
        and item.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    )

    panel.set_pair(pair, plan)

    assert unsettled, "the synthetic package leaves at least one row unsettled"
    rows = "\n".join(panel.value_text(label) for label in ("Impulse", "AC/DC type tests"))
    assert "engineering input required" in rows


def test_a_pair_outside_the_plan_says_so_rather_than_showing_an_empty_form(
    panel: VerificationPanel, project: Project, plan: VerificationPlan
) -> None:
    outside = next(
        pair
        for pair in project.pairs
        if all(item.pair_id != pair.id for item in plan.pair_assessments)
    )

    panel.set_pair(outside, plan)

    assert panel.notice_text == NOT_PLANNED_TEXT
    assert panel.value_text("Status") == EMPTY_VALUE


def test_without_a_plan_the_panel_says_the_results_above_are_unaffected(
    panel: VerificationPanel, project: Project
) -> None:
    panel.set_pair(_planned_pair(project), None)

    assert panel.notice_text == NO_PLAN_TEXT


def test_a_caller_notice_replaces_the_absent_plan_message(
    panel: VerificationPanel, project: Project
) -> None:
    panel.set_pair(_planned_pair(project), None, "Dielectric verification — package refused.")

    assert panel.notice_text == "Dielectric verification — package refused."


def test_the_trace_opens_on_demand_and_closes_again(
    panel: VerificationPanel, project: Project, plan: VerificationPlan
) -> None:
    panel.set_pair(_planned_pair(project), plan)

    assert not panel.trace_visible
    panel.toggle_trace()
    assert panel.trace_visible
    assert panel.trace_body != EMPTY_VALUE
    panel.toggle_trace()
    assert not panel.trace_visible


def test_showing_a_pair_leaves_the_plan_exactly_as_it_was(
    panel: VerificationPanel, project: Project, plan: VerificationPlan
) -> None:
    """The panel renders and decides nothing. Anything it recomputed could disagree with
    the schedule it is meant to be showing."""

    before = plan.model_copy(deep=True)
    pair = _planned_pair(project)

    panel.set_pair(pair, plan)
    panel.toggle_trace()
    panel.set_pair(pair, plan)

    assert plan == before


def test_an_unconfirmed_selection_carries_no_manual_badge(project: Project) -> None:
    pair = _planned_pair(project)
    unconfirmed = pair.model_copy(update={"protection_review_state": ReviewState.NEEDS_REVIEW})

    assert protection_badge_state(pair) is not None
    assert protection_badge_state(unconfirmed) is None
    assert "awaiting confirmation" in review_text(unconfirmed)
    assert review_text(pair).endswith("confirmed.")


def test_selecting_a_protection_implementation_produces_one_replacement_pair(
    qtbot: QtBot, project: Project
) -> None:
    editor = PairEditor()
    qtbot.addWidget(editor)
    pair = _planned_pair(project)
    editor.load_pair(pair, project.defaults)
    seen: list[PairCase] = []
    editor.pair_changed.connect(seen.append)

    combo = editor.verification_panel._protection_combo
    combo.setCurrentIndex(combo.findData(REINFORCED.value))

    assert len(seen) == 1
    updated = seen[0]
    assert updated.protection_implementation is REINFORCED
    # Nothing else moved: the pair the clearance engine reads is byte-for-byte the one it read
    # before, apart from the one field the user changed.
    assert updated.model_copy(update={"protection_implementation": BASIC}) == pair


def test_the_solid_insulation_declaration_is_written_back_whole(
    qtbot: QtBot, project: Project
) -> None:
    editor = PairEditor()
    qtbot.addWidget(editor)
    editor.load_pair(_planned_pair(project), project.defaults)
    seen: list[PairCase] = []
    editor.pair_changed.connect(seen.append)
    panel = editor.verification_panel

    panel._present_combo.setCurrentIndex(panel._present_combo.findData(True))

    assert len(seen) == 1
    declared = seen[0].solid_insulation
    assert declared == SolidInsulationTestData(present=True)


def test_an_unanswered_declaration_is_not_a_negative_answer(qtbot: QtBot, project: Project) -> None:
    """``present`` unanswered and ``present`` false are different states, and the panel keeps
    them apart because the partial-discharge assessment reads them differently."""

    editor = PairEditor()
    qtbot.addWidget(editor)
    pair = _planned_pair(project).model_copy(
        update={"solid_insulation": declared_solid_insulation()}
    )
    editor.load_pair(pair, project.defaults)
    panel = editor.verification_panel

    assert panel._present_combo.currentData() is True
    assert panel._layers_edit.text() == "1"

    editor.load_pair(_planned_pair(project), project.defaults)
    assert panel._present_combo.currentData() is None


def test_a_claimed_material_exemption_with_no_reference_is_refused(
    qtbot: QtBot, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "insulation_coordination.ui.verification_panel.QMessageBox.warning",
        lambda *args: warnings.append(str(args[2])),
    )
    editor = PairEditor()
    qtbot.addWidget(editor)
    editor.load_pair(_planned_pair(project), project.defaults)
    seen: list[PairCase] = []
    editor.pair_changed.connect(seen.append)
    panel = editor.verification_panel

    panel._exempt_combo.setCurrentIndex(panel._exempt_combo.findData(True))

    assert seen == []
    assert warnings and "material reference" in warnings[0]


def test_editing_a_verification_choice_never_runs_the_calculation_engine(
    qtbot: QtBot, project: Project, package: RulePackage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recalculation stays on the button that owns it. A choice made here changes what the
    schedule verifies and no clearance or creepage figure at all."""

    calls: list[UUID] = []
    monkeypatch.setattr(
        "insulation_coordination.calculation.engine.calculate_project_pair",
        lambda project, pair, rules, supply=None: calls.append(pair.id),
    )
    page = PairPage()
    qtbot.addWidget(page)
    page.load_project(project)
    page.load_rules(package)
    pair = _planned_pair(project)
    page.select_pair_by_id(str(pair.id))
    panel = page.editor.verification_panel

    combo = panel._protection_combo
    combo.setCurrentIndex(combo.findData(REINFORCED.value))

    assert calls == []
    assert page.verification_plan is not None
    assert page.editor.pair is not None
    assert page.editor.pair.protection_implementation is REINFORCED


def test_the_page_reports_why_no_plan_could_be_built(qtbot: QtBot, project: Project) -> None:
    """A package that cannot answer the verification questions leaves the pairs editable and
    says so where the plan would be."""

    from tests.fixtures.synthetic_rules import synthetic_supply_rule_package

    page = PairPage()
    qtbot.addWidget(page)
    page.load_project(project)
    page.load_rules(synthetic_supply_rule_package())
    page.select_pair_by_id(str(_planned_pair(project).id))

    assert page.verification_plan is None
    assert page.editor.verification_panel.notice_text.startswith("Dielectric verification")


def test_the_exemption_lists_every_condition_in_source_order() -> None:
    assessment = RoutineExemptionAssessment(
        pair_key="synthetic",
        conditions=(
            ExemptionCondition(
                field_name="first",
                state=ExemptionConditionState.SATISFIED,
                detail="the first condition holds",
            ),
            ExemptionCondition(
                field_name="second",
                state=ExemptionConditionState.NOT_DECLARED,
                detail="the second condition was never answered",
            ),
        ),
    )

    shown = exemption_text(assessment)

    assert "Not granted" in shown
    assert shown.index("the first condition holds") < shown.index(
        "the second condition was never answered"
    )
    assert "not declared" in shown


def test_the_monitoring_row_repeats_the_dependency_issue_36_recorded() -> None:
    dependency = SpdMonitoringDependency(
        pair_id=UUID(int=7),
        affected_location="the input filter",
        device_placement=SpdDevicePlacement.INTERNAL_TO_EQUIPMENT,
        device_degradable=True,
        monitoring_required=True,
        status_indication_required=True,
        required_type_test_semantic_id="synthetic.monitoring",
    )
    assessment = PairVerificationAssessment(
        pair_id=UUID(int=7),
        pair_key="synthetic",
        reference_kind=TestReferenceKind.WITHIN_CIRCUIT,
        spd_monitoring_dependency=dependency,
    )

    shown = spd_monitoring_text(assessment)

    assert "the input filter" in shown
    assert "synthetic.monitoring" in shown
    assert spd_monitoring_text(None) == EMPTY_VALUE


def test_the_requirement_row_states_what_the_package_requires_and_whether_it_is_met(
    panel: VerificationPanel, project: Project, plan: VerificationPlan
) -> None:
    panel.set_pair(_planned_pair(project), plan)
    shown = panel.value_text("Protection requirement")

    assert "basic protection" in shown
    assert "met by the selected implementation" in shown
    assert "NOT met" not in shown


def test_the_requirement_row_says_so_when_the_implementation_does_not_meet_it(
    panel: VerificationPanel, package: RulePackage
) -> None:
    """The row a reader signs off has to be able to say no, which is why it is read at all."""
    project = with_pair_fields(
        _reclassified(verification_topology(supply_configurations=(mains_configuration(),))),
        protection_implementation=BASIC,
        protection_review_state=ReviewState.USER_CONFIRMED,
    )
    plan = _build(project, package)
    panel.set_pair(_planned_pair(project), plan)

    assert "NOT met by the selected implementation" in panel.value_text("Protection requirement")


def test_the_requirement_row_never_reports_the_implementation_back_as_the_requirement(
    panel: VerificationPanel, package: RulePackage
) -> None:
    """A pair whose class nobody assigned has no requirement, whatever was selected for it."""
    project = with_pair_fields(
        _reclassified(
            verification_topology(supply_configurations=(mains_configuration(),)),
            dvc=DecisiveVoltageClass.NOT_EVALUATED,
        ),
        protection_implementation=REINFORCED,
        protection_review_state=ReviewState.USER_CONFIRMED,
    )
    plan = _build(project, package)
    panel.set_pair(_planned_pair(project), plan)
    shown = panel.value_text("Protection requirement")

    assert "not established from the active package" in shown
    assert "enhanced" not in shown


def test_plan_rows_answer_every_label_even_with_nothing_planned() -> None:
    """No row goes quiet. A label with nothing behind it says so rather than disappearing."""

    rows = plan_rows(None, (), None)

    assert tuple(rows) == ROW_LABELS
    assert all(value for value in rows.values())
    assert rows["Status"] == EMPTY_VALUE


def test_the_partial_discharge_row_shows_a_declared_pair_differently(
    panel: VerificationPanel, package: RulePackage
) -> None:
    undeclared = verification_topology(supply_configurations=(mains_configuration(),))
    declared = with_pair_fields(
        undeclared,
        protection_implementation=BASIC,
        protection_review_state=ReviewState.USER_CONFIRMED,
        solid_insulation=declared_solid_insulation(minimum_thickness_mm=Decimal("0.5")),
    )
    plan = _build(declared, package)
    panel.set_pair(_planned_pair(declared), plan)
    with_declaration = panel.value_text("Partial discharge")

    panel.set_pair(_planned_pair(undeclared), _build(undeclared, package))

    assert with_declaration != EMPTY_VALUE
    assert panel.value_text("Partial discharge") == "engineering input required"
