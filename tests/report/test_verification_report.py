"""What the report says about the dielectric verification plan, and what it refuses to hide.

Every figure, name and reference reached here comes from ``tests.fixtures.verification_topologies``
and is this repository's own invention. Nothing reproduces a value, a heading, a note or any
wording from any standard, and no rendered document is written anywhere but a temporary
directory.

Four properties are what these tests exist for.

*A schedule a test house can act on.* Every row names what is tested, between which electrodes,
at what voltage and of what classification, and every one of those columns is filled - a column
the plan could not resolve says so rather than going blank.

*No test is ever silently removed.* A granted exemption marks its routine rows and writes the
grounds beside them; the rows stay in the schedule and in the document.

*Verification incompleteness does not block the report.* A package that answers no verification
question at all still produces the whole clearance and creepage report, with the verification
sections present and stating why they are empty.

*The circuit diagram from #33 keeps its section and its position*, with the new sections placed
after Grouped Calculations rather than anywhere near it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import (
    calculate_project_pair,
    derive_project_supply,
)
from insulation_coordination.calculation.grouping import group_results
from insulation_coordination.domain.enums import ConstructionType, ReviewState
from insulation_coordination.domain.project import Project, RulePackageReference
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.verification import (
    EvidenceApprovalState,
    ProtectionImplementation,
    RoutineTestExemptionEvidence,
    TestApplicability,
    VoltageEvidence,
    VoltageEvidenceMethod,
    VoltageQuantityKind,
)
from insulation_coordination.report.human_view import (
    NOT_RESOLVED_TEXT,
    VERIFICATION_COMPLETE_TEXT,
    VERIFICATION_INCOMPLETE_PREFIX,
    VERIFICATION_INDEPENDENT_TEXT,
    VERIFICATION_UNAVAILABLE_PREFIX,
    build_human_report_view,
)
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import ReportVerification, build_report_model
from tests.fixtures.images import attachment_from, png_bytes
from tests.fixtures.synthetic_rules import (
    merged_rule_package,
    synthetic_part1_rule_package,
    synthetic_supply_rule_package,
)
from tests.fixtures.verification_topologies import (
    LIVE_A,
    mains_configuration,
    single_column_dielectric_package,
    verification_topology,
)

RECORDED_AT = datetime(2026, 5, 6, 7, 8, 9, tzinfo=UTC)

#: Everything a granted exemption needs. Each reference is this module's own token.
FULLY_EVIDENCED_EXEMPTION = RoutineTestExemptionEvidence(
    subassemblies_routine_tested=True,
    subassembly_evidence_reference="SYN-SUB-1",
    assembly_cannot_compromise_insulation=True,
    assembly_justification="SYN-ASSEMBLY-1",
    assembled_type_test_passed=True,
    assembled_type_test_reference="SYN-TYPE-1",
    reviewer="Synthetic reviewer",
    reviewed_at=RECORDED_AT,
)


def _topology() -> Project:
    """The verification fixture's project, dimensionable by the clearance fixture as well.

    The recurring peak is raised into the clearance fixture's supported range. It then sits
    above the non-mains dielectric row axis, so the mains pairs resolve a test voltage and the
    non-mains ones report that the table could not be read for them - which is the pair of
    outcomes a schedule has to show side by side. The construction is moved to the one the
    clearance fixture states a creepage route for; nothing in the verification plan reads it.
    """

    project = verification_topology(
        supply_configurations=(mains_configuration(),), recurring_peak_v=Decimal(500)
    )
    return project.model_copy(
        update={
            "defaults": project.defaults.model_copy(
                update={
                    "construction_type": ConstructionType.OTHER,
                    # A pair behind the verified barrier inherits no derived impulse, and a
                    # clearance cannot be dimensioned without one. This module's own figure.
                    "impulse_v": Decimal(150),
                }
            )
        }
    )


def _pinned(project: Project, package: RulePackage) -> Project:
    assert package.package_sha256 is not None
    return project.model_copy(
        update={
            "required_rules": RulePackageReference(
                package_id=str(package.manifest.package_id),
                version=package.manifest.version,
                sha256=package.package_sha256,
            ),
            "pairs": tuple(
                pair.model_copy(
                    update={
                        "protection_implementation": ProtectionImplementation.BASIC_INSULATION,
                        "protection_review_state": ReviewState.USER_CONFIRMED,
                    }
                )
                for pair in project.pairs
            ),
        }
    )


def _inputs(project: Project, package: RulePackage):
    supply = derive_project_supply(project, package)
    results = tuple(
        calculate_project_pair(project, pair, package, supply=supply)
        for pair in project.pairs
        if not pair.is_excluded
    )
    return project, results, group_results(results, ()), package


@pytest.fixture
def package(tmp_path: Path) -> RulePackage:
    """One package answering the clearance, supply and verification questions together.

    A report needs all three: the clearance engine dimensions every pair before the plan is
    built, so the two-package merge the plan tests use is not enough here. The clearance
    fixture goes first, so where it and the verification fixture both declare a rule the
    dimensioning content is the one that survives the merge.
    """

    return merged_rule_package(
        synthetic_part1_rule_package(),
        synthetic_supply_rule_package(),
        single_column_dielectric_package(),
        path=tmp_path / "merged.icrules",
    )


@pytest.fixture
def verification_inputs(package: RulePackage):
    project = _pinned(_topology(), package)
    return _inputs(project, package)


# --- the plan reaches the report -------------------------------------------------------


def test_the_report_carries_the_plan_the_project_and_the_package_produce(
    verification_inputs,
) -> None:
    model = build_report_model(*verification_inputs)

    plan = model.verification.plan
    assert plan is not None
    assert model.verification.unavailable_reason == ""
    assert plan.rule_package.sha256 == verification_inputs[3].package_sha256
    assert plan.test_applications


def test_two_builds_of_one_project_produce_the_same_verification_section(
    verification_inputs,
) -> None:
    """A plan is recomputed, never persisted, so a report has to be diffable against the last."""

    first = build_report_model(*verification_inputs)
    second = build_report_model(*verification_inputs)

    assert first.verification == second.verification
    assert render_latex(first) == render_latex(second)


# --- the schedule a test house reads ---------------------------------------------------


def test_every_schedule_row_names_its_electrodes_voltage_and_classification(
    verification_inputs,
) -> None:
    """No column is ever blank. An unresolved answer says so; it does not go quiet."""

    view = build_human_report_view(build_report_model(*verification_inputs))

    assert view.verification.schedule
    for row in view.verification.schedule:
        assert row.test
        assert row.high_side and row.high_side != "—"
        assert row.low_side
        assert row.voltage
        assert row.classification
        assert row.duration
        assert row.applicability
        assert row.covered_pairs


def test_a_row_the_plan_could_not_resolve_stays_and_says_what_is_missing(
    verification_inputs,
) -> None:
    model = build_report_model(*verification_inputs)
    view = build_human_report_view(model)

    unsettled = [
        row
        for row in view.verification.schedule
        if row.applicability == TestApplicability.ENGINEERING_INPUT_REQUIRED.value.replace("_", " ")
    ]
    assert unsettled, "the synthetic package cannot settle every row, so some must say so"
    for row in unsettled:
        assert row.unresolved
    rendered = render_latex(model)
    for row in unsettled:
        # The digest half of the identifier: the readable half carries an underscore, which
        # the LaTeX escape turns into something a plain substring search would miss.
        assert row.test_id.rsplit("-", 1)[1] in rendered


def test_an_incomplete_plan_states_how_much_is_outstanding_and_that_the_report_stands(
    verification_inputs,
) -> None:
    model = build_report_model(*verification_inputs)

    statement = build_human_report_view(model).verification.statement

    assert statement.startswith(VERIFICATION_INCOMPLETE_PREFIX)
    assert VERIFICATION_INDEPENDENT_TEXT in statement
    plan = model.verification.plan
    assert plan is not None
    assert f"{len(plan.unresolved_inputs)} inputs are unresolved" in statement


def test_a_plan_with_nothing_outstanding_says_so(verification_inputs) -> None:
    """The other half of the statement, from a plan whose rows all settled.

    The synthetic package cannot settle every row - no resolved rule states an AC/DC duration -
    so the settled plan is made here by resolving the rows of the real one. What is under test
    is the projection, which must not describe a complete plan as incomplete.
    """

    model = build_report_model(*verification_inputs)
    plan = model.verification.plan
    assert plan is not None
    settled = plan.model_copy(
        update={
            "unresolved_inputs": (),
            "test_applications": tuple(
                application.model_copy(
                    update={
                        "applicability": TestApplicability.REQUIRED,
                        "unresolved_inputs": (),
                    }
                )
                for application in plan.test_applications
            ),
        }
    )
    complete = model.model_copy(
        update={"verification": ReportVerification(plan=settled, evidence=())}
    )

    assert build_human_report_view(complete).verification.statement == VERIFICATION_COMPLETE_TEXT


# --- nothing is silently removed -------------------------------------------------------


def test_a_granted_exemption_keeps_its_routine_rows_and_prints_the_grounds(
    package: RulePackage,
) -> None:
    project = _pinned(_topology(), package)
    exempt = project.model_copy(
        update={
            "pairs": tuple(
                pair.model_copy(update={"routine_exemption": FULLY_EVIDENCED_EXEMPTION})
                for pair in project.pairs
            )
        }
    )

    model = build_report_model(*_inputs(exempt, package))
    view = build_human_report_view(model)
    rendered = render_latex(model)

    plan = model.verification.plan
    assert plan is not None
    excused = [
        application
        for application in plan.test_applications
        if application.applicability is TestApplicability.NOT_REQUIRED
    ]
    assert excused, "a fully evidenced exemption must mark rows rather than remove them"
    for application in excused:
        row = next(
            item for item in view.verification.schedule if item.test_id == application.test_id
        )
        assert row.test_id.rsplit("-", 1)[1] in rendered
        assert any("exemption is granted" in step for step in row.preparation)
    assert all(row.exemption.startswith("granted") for row in view.verification.pairs)
    assert "SYN-TYPE-1" in rendered


def test_an_exemption_nobody_claimed_names_every_condition_that_stopped_it(
    verification_inputs,
) -> None:
    """The checklist is reported unprompted, so a reader is never told only that it was not granted."""

    model = build_report_model(*verification_inputs)
    view = build_human_report_view(model)
    rendered = render_latex(model)

    assert view.verification.pairs
    for row in view.verification.pairs:
        assert row.exemption.startswith("not granted - ")
        for subject in ("routine tested", "compromise the insulation", "type test", "reviewer"):
            assert subject in row.exemption
    assert "not granted" in rendered


# --- evidence, governing value and rule identity ---------------------------------------


def test_a_superseded_entry_stays_in_the_inventory_and_says_it_does_not_govern(
    package: RulePackage,
) -> None:
    project = _pinned(_topology(), package)
    with_evidence = project.model_copy(
        update={
            "voltage_evidence": (
                VoltageEvidence(
                    id=UUID(int=901),
                    net_id=LIVE_A,
                    quantity_kind=VoltageQuantityKind.AC_RMS,
                    value_v=Decimal(120),
                    method=VoltageEvidenceMethod.CALCULATION,
                    operating_condition="normal operation",
                    source_reference="SYN-CALC-1",
                    recorded_at=RECORDED_AT,
                    approval_state=EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION,
                    approval_justification="Superseded by a later measurement.",
                ),
                VoltageEvidence(
                    id=UUID(int=902),
                    net_id=LIVE_A,
                    quantity_kind=VoltageQuantityKind.AC_RMS,
                    value_v=Decimal(90),
                    method=VoltageEvidenceMethod.MEASUREMENT,
                    operating_condition="normal operation",
                    source_reference="SYN-MEAS-1",
                    measurement_points="between the two terminals",
                    tolerance_or_uncertainty="plus or minus one percent",
                    recorded_at=RECORDED_AT,
                    approval_state=EvidenceApprovalState.APPROVED_FOR_DESIGN,
                ),
            )
        }
    )

    model = build_report_model(*_inputs(with_evidence, package))
    view = build_human_report_view(model)
    rendered = render_latex(model)

    values = {row.value: row for row in view.verification.evidence}
    assert set(values) == {"120 V", "90 V"}
    assert "does not govern" in values["120 V"].comparison
    assert values["90 V"].comparison == "governs"
    assert values["90 V"].measurement
    assert "SYN-CALC-1" in rendered
    assert view.verification.governing


def test_the_report_names_the_package_identity_and_every_rule_it_read(
    verification_inputs,
) -> None:
    model = build_report_model(*verification_inputs)
    view = build_human_report_view(model)
    rendered = render_latex(model)

    plan = model.verification.plan
    assert plan is not None
    assert plan.rule_package.sha256 in rendered
    named = {item.name: item.value for item in view.verification.rules}
    assert named["Package SHA-256"] == plan.rule_package.sha256
    for rule_id in plan.source_rule_ids:
        assert rule_id in named["Rule identifiers read"]


# --- placement, and what the older report still does -----------------------------------


def test_the_verification_sections_come_after_grouped_calculations(
    verification_inputs,
) -> None:
    rendered = render_latex(build_report_model(*verification_inputs))

    assert rendered.index("\\section{Grouped Calculations}") < rendered.index(
        "\\section{Dielectric Verification}"
    )
    assert rendered.index("\\section{Dielectric Verification}") < rendered.index(
        "\\section{Rules Package Provenance}"
    )
    for heading in (
        "Protection Implementation",
        "Voltage Evidence Inventory",
        "Governing Value Trace",
        "Working Voltage Determination",
        "Pair Verification Matrix",
        "Test Schedule",
        "Connection and Preparation Instructions",
        "Unresolved Verification Inputs and Warnings",
        "Verification Rules Identity",
    ):
        assert f"\\subsection{{{heading}}}" in rendered


def test_a_package_that_answers_no_verification_question_still_renders_the_report(
    report_inputs,
) -> None:
    """The distance-only report from before this issue, unchanged and unblocked."""

    model = build_report_model(*report_inputs)
    view = build_human_report_view(model)
    rendered = render_latex(model)

    assert model.verification.plan is None
    assert model.verification.unavailable_reason
    assert view.verification.available is False
    assert view.verification.statement.startswith(VERIFICATION_UNAVAILABLE_PREFIX)
    assert VERIFICATION_INDEPENDENT_TEXT in view.verification.statement
    assert "Grouped Calculations" in rendered
    assert "Pair Comparison Matrices" in rendered
    assert "No dielectric verification plan could be built" in rendered
    assert "No dielectric test is planned for this project." in rendered
    assert NOT_RESOLVED_TEXT not in rendered


def test_a_diagram_still_stages_and_keeps_its_position_beside_the_new_sections(
    package: RulePackage, tmp_path: Path
) -> None:
    project = _pinned(_topology(), package)
    attachment = attachment_from(png_bytes(), caption="Topology", source_note="EDA export")
    with_diagram = project.model_copy(update={"circuit_diagram": attachment})
    build_directory = tmp_path / "build"

    model = build_report_model(*_inputs(with_diagram, package), image_directory=build_directory)
    rendered = render_latex(model)

    assert model.circuit_diagram is not None
    staged = build_directory / model.circuit_diagram.staged_filename
    assert staged.read_bytes() == attachment.decoded_bytes()
    assert (
        rendered.index("\\section{Net Classes}")
        < rendered.index("\\section{Circuit Diagram}")
        < rendered.index("\\section{Project Topology}")
        < rendered.index("\\section{Dielectric Verification}")
    )
