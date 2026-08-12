from __future__ import annotations

import logging
import os
import re
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.clearance import calculate_clearance_candidates
from insulation_coordination.calculation.engine import calculate_pair
from insulation_coordination.calculation.high_frequency import assess_part4_clearance
from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
    PairCase,
    PairVoltage,
    PairVoltages,
    ProjectDefaults,
)
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.importer.approval import approve_draft, is_fully_resolved
from insulation_coordination.rules.importer.extract import (
    _REQUIRED_RECIPES,
    ExtractionError,
    extract_draft,
)
from insulation_coordination.rules.importer.identify import (
    StandardIdentificationError,
    identify_standard,
)
from insulation_coordination.rules.importer.review import draft_review_digest
from insulation_coordination.rules.validation import validate_rule_package
from tests.private.test_iec62477_curves import _complete_manual_curve_review
from tests.private.test_iec62477_dvc_tables import _review_all_c2_proposals

pytestmark = pytest.mark.private_standard


def _paths(supplied_standards: dict[str, Path]) -> tuple[Path, ...]:
    return tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES))


def _golden_digest_path() -> Path:
    repository = Path(__file__).parents[2]
    private_rules = Path(os.environ.get("ICC_PRIVATE_RULES_DIR", repository / "private-rules"))
    return private_rules / "supplied-standards-draft.sha256"


def _approve_supplied_package(reviewed) -> RulePackage:
    """Approve an already-reviewed draft: the review pass is shared by fixture.

    A curve variant does not exist until it is manually entered, so the calibration and
    the point entry both have to run before the variant can be reviewed.  The helper
    beside the manual-review lifecycle tests owns that sequence, and its inputs are local
    placeholders rather than values read off the licensed figure.
    """

    reviewed = _complete_manual_curve_review(reviewed)
    assert is_fully_resolved(reviewed)
    return approve_draft(
        reviewed,
        approver="Private fixture reviewer",
        notes="Approved supplied IEC PCB sources",
    )


def _effective_case(*, frequency_hz: int, peak_v: int):
    defaults = ProjectDefaults(
        frequency_hz=Decimal(frequency_hz),
        impulse_v=Decimal(1000),
        insulation_type=InsulationType.BASIC,
        field_condition=FieldCondition.INHOMOGENEOUS,
        altitude_m=Decimal(0),
        pollution_degree=2,
        construction_type=ConstructionType.PRINTED_WIRING,
        cti_or_material_group="I",
    )
    pair = PairCase(
        id=UUID(int=frequency_hz + peak_v),
        key="private-a::private-b",
        net_a=UUID(int=1),
        net_b=UUID(int=2),
        voltages=PairVoltages(
            long_term_rms_v=PairVoltage.applicable(Decimal(peak_v)),
            steady_state_peak_v=PairVoltage.applicable(Decimal(peak_v)),
            recurring_peak_v=PairVoltage.not_applicable("No recurring peak."),
            temporary_overvoltage_peak_v=PairVoltage.not_applicable("No temporary overvoltage."),
        ),
    )
    return resolve_effective_case(defaults, pair)


def test_supplied_standards_match_human_reviewed_draft(
    caplog: pytest.LogCaptureFixture,
    supplied_standards: dict[str, Path],
) -> None:
    paths = _paths(supplied_standards)
    golden_path = _golden_digest_path()

    try:
        with caplog.at_level(logging.ERROR, logger="pypdf._page"):
            identities = tuple(identify_standard(path) for path in paths)
            draft = extract_draft(paths)
    except (ExtractionError, StandardIdentificationError):
        pytest.fail(
            "private standard identification or structural extraction failed", pytrace=False
        )
    assert {
        ("IEC 60664-1", "2020"),
        ("IEC 60664-4", "2005"),
    } <= {(item.standard, item.edition) for item in identities}
    grid_ids = {grid.id for grid in draft.raw_grids}
    assert {
        "raw-iec60664-1-f2",
        "raw-iec60664-1-f5",
        "raw-iec60664-1-f8",
        "raw-iec60664-1-f9",
        "raw-iec60664-1-a2",
        "raw-iec60664-4-table-1",
        "raw-iec60664-4-table-2",
    } <= grid_ids
    grid_shapes = {grid.id: (grid.rows, grid.columns) for grid in draft.raw_grids}
    assert {
        "raw-iec60664-1-f2": (30, 7),
        "raw-iec60664-1-f5": (49, 10),
        "raw-iec60664-1-f8": (35, 3),
        "raw-iec60664-1-f9": (35, 2),
        "raw-iec60664-1-a2": (12, 3),
        "raw-iec60664-4-table-1": (10, 2),
        "raw-iec60664-4-table-2": (20, 8),
    }.items() <= grid_shapes.items()
    assert draft.review_items
    assert {item.code for item in draft.review_items} <= {
        "AMBIGUOUS_COMPONENT_FORMULA",
        "AMBIGUOUS_COMPOUND_CELL",
        # A proven cross-standard equivalence still needs a maintainer's sign-off before it
        # becomes an approved mapping.
        "CROSS_STANDARD_EQUIVALENCE_REVIEW_REQUIRED",
        "CURVE_VARIANT_REVIEW_REQUIRED",
        "MANUAL_CLAUSE_DEFINITION_REQUIRED",
        "MANUAL_TABLE_DEFINITION_REQUIRED",
        "MANUAL_RULE_DEFINITION_REQUIRED",
        "MANUAL_MAPPING_REQUIRED",
        "MANUAL_RAW_CELL_REVIEW_REQUIRED",
    }
    assert all(
        cell.source.row is not None and cell.source.column is not None
        for grid in draft.raw_grids
        for cell in grid.cells
    )
    assert any(
        cell.qualifier is not None or cell.suffix is not None
        for grid in draft.raw_grids
        for cell in grid.cells
    )
    f5 = next(grid for grid in draft.raw_grids if grid.id == "raw-iec60664-1-f5")
    assert tuple(segment.page_number for segment in f5.segments) == (74, 75)
    assert tuple(segment.row_start for segment in f5.segments) == (0, 30)
    assert all(cell.role in {"header", "data", "blank", "note", "footnote"} for cell in f5.cells)
    assert max(cell.logical_row for cell in f5.cells if cell.logical_row is not None) == 38
    assert any(
        " " in cell.raw_text.strip() and cell.value is not None
        for cell in f5.cells
        if cell.logical_column == "rms_voltage_v"
    )
    assert any(cell.footnotes for grid in draft.raw_grids for cell in grid.cells)
    assert {equation.id for equation in draft.extracted_equations} == {
        "iec60664-4-equation-1-critical-frequency",
        "iec60664-4-equation-2-frequency-factor",
        "iec60664-4-minimum-frequency",
        "iec60664-4-radius-criterion",
    }
    assert all(equation.parse_status == "parsed" for equation in draft.extracted_equations)
    assert all(equation.raw_text and equation.rendered for equation in draft.extracted_equations)
    assert all(equation.source.clause for equation in draft.extracted_equations)
    built = _review_all_c2_proposals(draft)
    assert {
        "iec60664-1-f2",
        "iec60664-1-f5",
        "iec60664-1-f8",
        "iec60664-1-f9",
        "iec60664-1-a2",
        "iec60664-4-table-1",
        "iec60664-4-table-2",
    } <= {table.id for table in built.tables}
    f5_table = next(table for table in built.tables if table.id == "iec60664-1-f5")
    f2_table = next(table for table in built.tables if table.id == "iec60664-1-f2")
    assert len(f2_table.cells) == 26 * 6
    assert len(f5_table.row_axis.values) == 39
    assert f5_table.row_axis.values[-1] > f5_table.row_axis.values[-2]
    assert all(
        earlier < later
        for earlier, later in zip(f5_table.row_axis.values, f5_table.row_axis.values[1:])
    )
    assert all(table.row_axis.labels and table.column_axis.labels for table in built.tables)
    assert all("raw_sequence" not in str(formula.expression) for formula in built.formulas)
    expected_draft_failures = {
        "approval",
        "approval_record",
        "compatibility",
        "checksums",
        "package_digest",
    }
    package_view = RulePackage(
        manifest=draft.manifest,
        tables=draft.tables,
        formulas=draft.formulas,
        mappings=draft.mappings,
    )
    assert {
        result.code for result in validate_rule_package(package_view).results if not result.passed
    } <= expected_draft_failures
    if not golden_path.is_file():
        pytest.skip("separately human-reviewed private draft digest is unavailable")
    golden = golden_path.read_text(encoding="ascii").strip()
    assert re.fullmatch(r"[0-9a-f]{64}", golden), "private golden digest is malformed"

    assert draft.raw_grids
    assert len({grid.id for grid in draft.raw_grids}) == len(draft.raw_grids)
    assert draft_review_digest(draft) == golden, "private extraction differs from reviewed digest"


@pytest.mark.timeout(300)
def test_supplied_standards_approve_and_calculate_pcb_annex_gh(
    tmp_path: Path,
    reviewed_draft,
) -> None:
    approved = _approve_supplied_package(reviewed_draft)
    archive = tmp_path / "reviewed.icrules"
    write_rule_package(archive, approved)
    rules = load_rule_package(archive)

    assert validate_rule_package(rules).is_valid
    part1 = calculate_pair(_effective_case(frequency_hz=50, peak_v=300), rules)
    low_peak_hf = calculate_pair(_effective_case(frequency_hz=100_000, peak_v=300), rules)
    high_peak_hf = calculate_pair(_effective_case(frequency_hz=100_000, peak_v=600), rules)

    assert part1.trace.used_part4 is False
    assert {candidate.formula_id for candidate in part1.trace.clearance_candidates} >= {
        "iec60664-1:f2-clearance",
        "iec60664-1:f8-clearance",
    }
    assert {candidate.formula_id for candidate in part1.trace.creepage_candidates} >= {
        "iec60664-1:f5-pcb-creepage"
    }
    assert low_peak_hf.trace.hf_iterations[0].critical_frequency_hz != (
        high_peak_hf.trace.hf_iterations[0].critical_frequency_hz
    )
    assert all(
        result.trace.hf_iterations[0].actual_frequency_hz == 100_000
        for result in (low_peak_hf, high_peak_hf)
    )
    assert any(
        candidate.formula_id == "iec60664-4:hf-creepage-table"
        for candidate in high_peak_hf.trace.creepage_candidates
    )

    table1_case = _effective_case(frequency_hz=4_000_000, peak_v=600)
    base = max(
        (
            candidate
            for candidate in calculate_clearance_candidates(table1_case, rules)
            if candidate.candidate_id != "impulse"
        ),
        key=lambda candidate: candidate.distance_mm,
    )
    table1 = assess_part4_clearance(table1_case, base, rules)
    assert table1.iterations[-1].selected_route == "inhomogeneous_table_1"
    source_tables = {
        reference.table
        for result in (part1, high_peak_hf)
        for step in result.trace.steps
        for reference in (step.source_reference, step.formula_source_reference)
        if reference is not None
    }
    assert {"F.2", "F.5", "F.8", "2"} <= source_tables
    assert any(
        step.formula_source_reference is not None
        and step.formula_source_reference.standard == "IEC 60664-4"
        for step in table1.iterations[-1].steps
    )
