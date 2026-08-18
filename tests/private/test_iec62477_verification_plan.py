"""Issue #37's verification plan and its report, run against the approved licensed package.

The public suite proves the plan on synthetic content. What only this module can prove is that
the *licensed* archive answers the same adapter: that every semantic ID the plan reads survives
extraction, review, approval and a round trip, and that what the package then says about five
different equipment topologies reaches a schedule rather than being dropped on the way.

**Nothing here asserts a value.** Which test voltage the package resolves for a row is licensed
content, and a test that pinned one would write it into a public file. What is asserted instead
is the shape a schedule has to have whatever the numbers are: every row keeps its place, every
column is answered or is reported unanswered, and every refusal names the rule that refused.

No value, heading, label or wording from any licensed table or clause is named here, and **no
document is written to the tree**: the report is built and rendered in memory, and the rendered
string is only ever searched for this application's own section headings.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from insulation_coordination.calculation.engine import (
    calculate_project_pair,
    derive_project_supply,
)
from insulation_coordination.calculation.grouping import group_results
from insulation_coordination.calculation.verification_plan import (
    VerificationPlan,
    VerificationPlanService,
)
from insulation_coordination.calculation.verification_rules import (
    READ_SEMANTIC_IDS,
    read_verification_rules,
    verification_rule_blocks,
)
from insulation_coordination.domain.enums import ConstructionType
from insulation_coordination.domain.project import (
    PairVoltage,
    PairVoltages,
    Project,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.verification import TestApplicability
from insulation_coordination.report.human_view import build_human_report_view
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import build_report_model
from tests.fixtures.verification_projects import (
    accessible_surfaces,
    multi_supply,
    surge_protected_input,
    variable_speed_drive,
    wireless_charger,
)

pytestmark = pytest.mark.private_standard

#: The pair entries and the default impulse this module dimensions from. Plain round numbers
#: chosen here so the clearance engine has something inside the ranges the package supports;
#: none of them is read from any licensed axis.
DEFAULT_IMPULSE_V = Decimal(2500)
PAIR_VOLTAGES = PairVoltages(
    long_term_rms_v=PairVoltage.applicable(Decimal(300)),
    steady_state_peak_v=PairVoltage.applicable(Decimal(400)),
    recurring_peak_v=PairVoltage.applicable(Decimal(500)),
    temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(600)),
)

TOPOLOGIES: tuple[tuple[str, Callable[[], Project]], ...] = (
    ("wireless charger", wireless_charger),
    ("variable speed drive", variable_speed_drive),
    ("multi-supply input", multi_supply),
    ("surge-protected input", surge_protected_input),
    ("accessible surfaces", accessible_surfaces),
)


def _pinned(project: Project, rules: RulePackage) -> Project:
    """The fixture project, pinned to the licensed package and dimensionable against it."""

    assert rules.package_sha256 is not None
    return project.model_copy(
        update={
            "metadata": ProjectMetadata(
                title=f"Licensed package {project.metadata.title}",
                document_number="PRIV-037",
                revision="A",
            ),
            "application_version": "0.1.0",
            "required_rules": RulePackageReference(
                package_id=str(rules.manifest.package_id),
                version=rules.manifest.version,
                sha256=rules.package_sha256,
            ),
            # The construction moves to printed wiring because that is the one the licensed
            # package's creepage route supports; nothing in the verification plan reads it.
            "defaults": project.defaults.model_copy(
                update={
                    "impulse_v": DEFAULT_IMPULSE_V,
                    "construction_type": ConstructionType.PRINTED_WIRING,
                }
            ),
            "pairs": tuple(
                pair.model_copy(update={"voltages": PAIR_VOLTAGES}) for pair in project.pairs
            ),
        }
    )


def _plan(project: Project, rules: RulePackage) -> VerificationPlan:
    return VerificationPlanService().build(project, rules, derive_project_supply(project, rules))


def test_the_approved_licensed_package_answers_the_verification_adapter(
    licensed_package: RulePackage,
) -> None:
    """Every semantic ID the plan reads survives approval and a round trip, with no blocks.

    Slice 1 proved this with a throwaway test and deleted it. It belongs here: the adapter's
    refusals are exhaustive by design, so one run of it against the real archive is the whole
    statement that the archive is readable.
    """

    package = licensed_package

    assert verification_rule_blocks(package) == ()
    rules = read_verification_rules(package)

    assert READ_SEMANTIC_IDS
    available = {
        rule.id
        for rule in (
            *package.tables,
            *package.formulas,
            *package.decisions,
            *package.curves,
            *package.procedures,
            *package.guidance,
        )
    }
    for semantic_id in READ_SEMANTIC_IDS:
        assert any(
            candidate == semantic_id or candidate.startswith(f"{semantic_id}.")
            for candidate in available
        ), semantic_id
    assert rules.working_voltage_determination.id.startswith("iec62477_2022.")
    assert rules.assembled_routine_exemption.rows


@pytest.mark.parametrize(("name", "build"), TOPOLOGIES, ids=[name for name, _ in TOPOLOGIES])
def test_every_topology_produces_a_schedule_nothing_falls_out_of(
    name: str, build: Callable[[], Project], licensed_package: RulePackage
) -> None:
    """Five arrangements, one property: a row is always answered or always says it is not."""

    project = _pinned(build(), licensed_package)

    plan = _plan(project, licensed_package)

    assert plan.test_applications, name
    assert plan.rule_package.sha256 == licensed_package.package_sha256
    for application in plan.test_applications:
        assert application.test_id
        assert application.high_side_net_ids
        if application.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED:
            assert application.unresolved_inputs, application.test_id
        # Either the row names what it read, or it says why it read nothing. A partial-
        # discharge row for a pair whose solid insulation nobody declared is the second
        # case against the real package: its gate was never asked, so it cites no rule.
        assert application.source_rule_ids or application.unresolved_inputs
    covered = {
        pair_id
        for application in plan.test_applications
        for pair_id in application.covered_pair_ids
    }
    planned = {assessment.pair_id for assessment in plan.pair_assessments}
    assert planned <= covered, name


def test_a_plan_is_the_same_plan_when_the_licensed_package_is_read_twice(
    licensed_package: RulePackage,
) -> None:
    """A generated identity is derived from the package, so two runs are one schedule."""

    project = _pinned(accessible_surfaces(), licensed_package)

    first = _plan(project, licensed_package)
    second = _plan(project, licensed_package)

    assert first == second


def test_the_report_carries_the_verification_sections_against_the_licensed_package(
    licensed_package: RulePackage,
) -> None:
    """Built and rendered in memory. Nothing is written, and no resolved value is asserted."""

    rules = licensed_package
    project = _pinned(accessible_surfaces(), rules)
    supply = derive_project_supply(project, rules)
    results = tuple(
        calculate_project_pair(project, pair, rules, supply=supply) for pair in project.pairs
    )

    model = build_report_model(project, results, group_results(results, ()), rules)
    view = build_human_report_view(model)
    rendered = render_latex(model)

    assert model.verification.plan is not None
    assert model.verification.unavailable_reason == ""
    assert view.verification.available
    assert view.verification.schedule
    assert "Dielectric Verification" in rendered
    assert rendered.index("\\section{Grouped Calculations}") < rendered.index(
        "\\section{Dielectric Verification}"
    )
    assert model.verification.plan.rule_package.sha256 in rendered
    for row in view.verification.schedule:
        assert row.voltage and row.classification and row.duration and row.applicability
