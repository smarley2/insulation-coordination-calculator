from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.clearance import (
    CalculationRangeError,
    calculate_clearance_candidates,
)
from insulation_coordination.calculation.engine import (
    HIGH_FREQUENCY_REVIEW_WARNING,
    RequiredStressError,
    calculate_pair,
)
from insulation_coordination.calculation.high_frequency import (
    A2_ALTITUDE_ROUTE,
    PART4_FREQUENCY_THRESHOLD_HZ,
    HighFrequencyCalculationError,
    calculate_critical_frequency,
    calculate_high_frequency_candidates,
    select_frequency_factor,
    select_part4_table2_creepage,
)
from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
    InsulationType,
    Provenance,
)
from insulation_coordination.domain.project import (
    EffectiveCase,
    EffectiveValue,
    PairVoltage,
    PairVoltages,
)
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from tests.fixtures.synthetic_rules import claimed_standards


@pytest.fixture
def case_factory():
    def make(
        *,
        kind: InsulationType = InsulationType.BASIC,
        frequency_hz: str = "30000",
        field_condition: FieldCondition = FieldCondition.INHOMOGENEOUS,
        electrode_radius_mm: str | None = None,
        altitude_m: str = "0",
        construction_type: ConstructionType = ConstructionType.PRINTED_WIRING,
        pollution_degree: int = 2,
        long_term_rms_v: PairVoltage | None = None,
        steady_state_peak_v: PairVoltage | None = None,
        temporary_overvoltage_peak_v: PairVoltage | None = None,
        recurring_peak_v: PairVoltage | None = None,
    ) -> EffectiveCase:
        return EffectiveCase(
            id=UUID(int=7),
            key="a::b",
            net_a=UUID(int=1),
            net_b=UUID(int=2),
            voltages=PairVoltages(
                long_term_rms_v=long_term_rms_v or PairVoltage.applicable(Decimal(500)),
                steady_state_peak_v=steady_state_peak_v or PairVoltage.applicable(Decimal(300)),
                recurring_peak_v=recurring_peak_v or PairVoltage.applicable(Decimal(400)),
                temporary_overvoltage_peak_v=temporary_overvoltage_peak_v
                or PairVoltage.applicable(Decimal(600)),
            ),
            frequency_hz=EffectiveValue(
                value=Decimal(frequency_hz),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            impulse_v=EffectiveValue(
                value=Decimal(1000),
                provenance=Provenance.PAIR_OVERRIDE,
            ),
            insulation_type=EffectiveValue(value=kind, provenance=Provenance.PAIR_OVERRIDE),
            field_condition=EffectiveValue(
                value=field_condition,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            electrode_radius_mm=EffectiveValue(
                value=None if electrode_radius_mm is None else Decimal(electrode_radius_mm),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            altitude_m=EffectiveValue(
                value=Decimal(altitude_m),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            pollution_degree=EffectiveValue(
                value=pollution_degree,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            construction_type=EffectiveValue(
                value=construction_type,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            cti_or_material_group=EffectiveValue(
                value="I",
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            conventional_construction_assumptions=EffectiveValue(
                value=(),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
        )

    return make


def test_semantic_fixture_packages_do_not_claim_iec_identity(
    semantic_part4_rules: RulePackage,
) -> None:
    # semantic_part4_rules carries the annex G and part 1 content too, so one
    # assertion covers every package this suite calculates against.
    standards = claimed_standards(semantic_part4_rules)

    assert standards
    assert not any(standard.upper().startswith("IEC") for standard in standards)


def _periodic_base(case: EffectiveCase, rules: RulePackage):
    return max(
        (
            candidate
            for candidate in calculate_clearance_candidates(case, rules)
            if candidate.candidate_id != "impulse"
        ),
        key=lambda candidate: candidate.distance_mm,
    )


def test_part4_starts_only_above_30_khz(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    at_boundary = calculate_pair(case_factory(frequency_hz="30000"), semantic_part4_rules)
    above = calculate_pair(case_factory(frequency_hz="30000.1"), semantic_part4_rules)

    assert at_boundary.trace.used_part4 is False
    assert above.trace.used_part4 is True


def test_a_pair_above_the_boundary_owes_the_annex_review_where_it_is_dimensioned(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    """The obligation belongs to the insulation design, and it never states the boundary.

    The annex that owns the boundary is normative and covers clearance, creepage distance and
    solid insulation together, so the review is raised against the pair's result rather than
    against one test. What the warning states is the rule that decided it; the frequency the
    rule states is the rule's, and never appears in the sentence.
    """
    boundary = PART4_FREQUENCY_THRESHOLD_HZ
    at_boundary = calculate_pair(case_factory(frequency_hz=str(boundary)), semantic_part4_rules)
    above = calculate_pair(
        case_factory(frequency_hz=str(boundary + Decimal(1))), semantic_part4_rules
    )

    assert all(item.code != HIGH_FREQUENCY_REVIEW_WARNING for item in at_boundary.warnings)
    warning = next(item for item in above.warnings if item.code == HIGH_FREQUENCY_REVIEW_WARNING)
    assert warning.semantic_rule_id == ids.HIGH_FREQUENCY_APPLICABILITY
    assert "clearance, creepage distance and solid insulation" in warning.message
    assert "greater of the two" in warning.message
    assert "IEC 60664-4" in warning.message
    # The two standard identities are the only numerals the sentence is allowed; the boundary
    # they decided is named by the rule that states it and never written out.
    named = warning.message.replace("62477-1", "").replace("60664-4", "")
    assert not any(character.isdigit() for character in named)
    assert "kHz" not in warning.message
    assert above.trace.warnings == above.warnings


def test_critical_frequency_uses_each_pairs_clearance(
    semantic_part4_rules: RulePackage,
) -> None:
    one_mm = calculate_critical_frequency(Decimal(1), semantic_part4_rules)
    two_mm = calculate_critical_frequency(Decimal(2), semantic_part4_rules)

    assert (one_mm.value, one_mm.unit) == (Decimal(1100000), "Hz")
    assert (two_mm.value, two_mm.unit) == (Decimal(550000), "Hz")
    assert one_mm.steps[-1].semantic_rule_id == "iec60664-4-equation-1-critical-frequency"


@pytest.mark.parametrize(
    ("frequency_hz", "expected_percent", "expected_branch"),
    (
        ("1099999", "100", "below_critical"),
        ("1100000", "100", "critical_to_minimum"),
        ("5500000", "149.5", "critical_to_minimum"),
        ("9900000", "125", "at_or_above_minimum"),
    ),
)
def test_frequency_factor_follows_iec_boundaries(
    frequency_hz: str,
    expected_percent: str,
    expected_branch: str,
    semantic_part4_rules: RulePackage,
) -> None:
    selected = select_frequency_factor(
        Decimal(frequency_hz), Decimal(1100000), semantic_part4_rules
    )

    assert selected.percent == Decimal(expected_percent)
    assert selected.branch == expected_branch


@pytest.mark.parametrize(
    ("selected_field", "steady", "temporary", "recurring"),
    (
        ("steady_state_peak_v", "600", "500", "400"),
        ("temporary_overvoltage_peak_v", "300", "600", "400"),
        ("recurring_peak_v", "300", "500", "600"),
    ),
)
def test_periodic_peak_selects_and_traces_each_governing_source(
    selected_field: str,
    steady: str,
    temporary: str,
    recurring: str,
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(
        frequency_hz="60000",
        steady_state_peak_v=PairVoltage.applicable(Decimal(steady)),
        temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(temporary)),
        recurring_peak_v=PairVoltage.applicable(Decimal(recurring)),
    )
    result = calculate_high_frequency_candidates(
        case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
    )
    step = next(
        item
        for item in result.clearance_candidates[0].steps
        if item.semantic_rule_id == "iec60664-4:periodic_peak.maximum"
    )

    assert selected_field in step.reason
    assert step.output.value == Decimal(600)


def test_periodic_peak_retains_omission_and_blank_blocks(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    omitted = case_factory(
        frequency_hz="60000",
        steady_state_peak_v=PairVoltage.not_applicable("No steady-state stress."),
    )
    result = calculate_high_frequency_candidates(
        omitted, _periodic_base(omitted, semantic_part4_rules), semantic_part4_rules
    )
    assert result.periodic_peak_omissions[0].justification == "No steady-state stress."

    blank = case_factory(frequency_hz="60000", steady_state_peak_v=PairVoltage.blank())
    with pytest.raises(RequiredStressError, match="steady_state_peak_v"):
        calculate_high_frequency_candidates(
            blank, _periodic_base(blank, semantic_part4_rules), semantic_part4_rules
        )


def test_inhomogeneous_table_1_activates_only_at_pair_critical_frequency(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    below = case_factory(frequency_hz="220000")
    above = case_factory(frequency_hz="660000")
    base = _periodic_base(below, semantic_part4_rules)

    below_result = calculate_high_frequency_candidates(below, base, semantic_part4_rules)
    above_result = calculate_high_frequency_candidates(above, base, semantic_part4_rules)

    assert below_result.clearance_candidates[0].distance_mm == base.distance_mm
    assert below_result.iterations[0].selected_route == "below_critical"
    assert above_result.clearance_candidates[0].formula_id == "iec60664-4:hf-clearance-table"
    assert above_result.iterations[-1].selected_route == "inhomogeneous_table_1"


def test_functional_insulation_uses_same_reviewed_part4_decision_without_fake_mapping(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(kind=InsulationType.FUNCTIONAL, frequency_hz="60000")
    result = calculate_high_frequency_candidates(
        case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
    )

    assert result.iterations[0].selected_route == "below_critical"
    assert all(
        "functional_applicability" not in step.semantic_rule_id
        for step in result.clearance_candidates[0].steps
    )


def test_homogeneous_field_requires_geometry(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(frequency_hz="100000", field_condition=FieldCondition.HOMOGENEOUS)

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_high_frequency_candidates(
            case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
        )

    assert caught.value.code == "HF_GEOMETRY_REQUIRED"


def test_radius_failure_routes_to_inhomogeneous_table_1(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(
        frequency_hz="660000",
        field_condition=FieldCondition.APPROXIMATELY_HOMOGENEOUS,
        electrode_radius_mm="0.1",
    )
    result = calculate_high_frequency_candidates(
        case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
    )

    assert result.iterations[-1].selected_route == "inhomogeneous_table_1"
    assert result.iterations[-1].radius_ratio < Decimal("0.55")


def test_homogeneous_clearance_stabilizes_on_source_rounded_second_pass(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(
        frequency_hz="2200000",
        field_condition=FieldCondition.HOMOGENEOUS,
        electrode_radius_mm="10",
        temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(800)),
    )
    result = calculate_high_frequency_candidates(
        case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
    )

    assert len(result.iterations) == 2
    assert result.iterations[-1].stable is True
    assert result.clearance_candidates[0].distance_mm == Decimal("4.2")


def test_second_pass_instability_blocks_engineering_guess(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(frequency_hz="440000")

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_high_frequency_candidates(
            case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
        )

    assert caught.value.code == "HF_SECOND_PASS_UNSTABLE"
    assert len(caught.value.iterations) == 2


def test_engine_trace_has_pair_decisions_and_no_fabricated_iteration_settings(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    result = calculate_pair(case_factory(frequency_hz="60000"), semantic_part4_rules)
    iteration = result.trace.hf_iterations[0]

    assert iteration.critical_frequency_hz == Decimal(1100000) / Decimal("3.1")
    assert iteration.actual_frequency_hz == Decimal(60000)
    assert iteration.factor_percent == Decimal(100)
    assert not hasattr(result.trace, "hf_iteration_tolerance_mm")
    assert not hasattr(result.trace, "hf_iteration_max_iterations")


@pytest.mark.parametrize(
    ("altitude_m", "factor", "applied"),
    (
        ("0", "1", False),
        ("2000", "1", False),
        ("3800", "1.8", True),
        ("6600", "4", True),
        ("9900", "8", True),
    ),
)
def test_a2_altitude_applies_after_clearance_maximum(
    altitude_m: str,
    factor: str,
    applied: bool,
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(frequency_hz="30000", altitude_m=altitude_m),
        semantic_part4_rules,
    )

    assert result.clearance_mm == result.trace.pre_altitude_clearance_mm * Decimal(factor)
    assert result.trace.altitude_correction_applied is applied
    if applied:
        step = next(
            item
            for item in result.trace.steps
            if item.semantic_rule_id == "iec60664-1:altitude_correction:base=2000m"
        )
        assert step.source_cells == (
            "2200/clearance_factor",
            "4200/clearance_factor",
        ) or altitude_m in {"6600", "9900"}
    else:
        step = next(
            item
            for item in result.trace.steps
            if item.semantic_rule_id == "iec60664-1:a2-altitude-not-applied"
        )
        assert "does not exceed the base altitude the approved A.2 rule states" in step.reason
        assert step.source_reference is not None


@pytest.mark.parametrize("altitude_m", ("0", "2000", "3800"))
def test_a2_altitude_without_an_approved_rule_blocks_instead_of_skipping(
    altitude_m: str,
    case_factory,
    tmp_path: Path,
    semantic_part4_rules: RulePackage,
) -> None:
    """No A.2 route, no boundary: the calculation refuses rather than passing the clearance.

    The altitude a clearance is corrected above used to be a literal in this module, so a
    package that stated nothing about altitude still produced an uncorrected answer that
    looked like a corrected one. Below the boundary is the case that used to fall through
    silently, which is why it is parametrized alongside the two that always blocked.
    """

    stripped = _resealed(
        semantic_part4_rules,
        tmp_path,
        mappings=tuple(
            mapping
            for mapping in semantic_part4_rules.mappings
            if mapping.source_rule_id != A2_ALTITUDE_ROUTE
        ),
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(case_factory(frequency_hz="30000", altitude_m=altitude_m), stripped)

    assert caught.value.code == "ALTITUDE_RULE_UNAVAILABLE"
    assert "states no approved A.2 altitude correction" in str(caught.value)


def test_a2_altitude_boundary_is_read_from_the_package_row_axis(
    case_factory,
    tmp_path: Path,
    semantic_part4_rules: RulePackage,
) -> None:
    """Move the table's lowest row and the boundary moves with it; nothing here fixes it."""

    a2 = next(table for table in semantic_part4_rules.tables if table.id == "iec60664-1-a2")
    base = a2.row_axis.values[0]
    lifted = _with_lifted_a2_base(semantic_part4_rules, tmp_path, base + Decimal(1000))

    result = calculate_pair(case_factory(frequency_hz="30000", altitude_m=str(base)), lifted)

    assert result.trace.altitude_correction_applied is False
    assert result.clearance_mm == result.trace.pre_altitude_clearance_mm


def _with_lifted_a2_base(rules: RulePackage, tmp_path: Path, base: Decimal) -> RulePackage:
    """The same package with the A.2 row axis and its declared range shifted up by one row."""

    a2 = next(table for table in rules.tables if table.id == "iec60664-1-a2")
    values = (base, *a2.row_axis.values[1:])
    moved = a2.model_copy(
        update={
            "row_axis": a2.row_axis.model_copy(
                update={"values": values, "labels": tuple(str(value) for value in values)}
            ),
            "supported_ranges": tuple(
                item.model_copy(update={"minimum": base}) if item.variable == "altitude_m" else item
                for item in a2.supported_ranges
            ),
        }
    )
    return _resealed(
        rules,
        tmp_path,
        tables=tuple(moved if table.id == a2.id else table for table in rules.tables),
    )


def _resealed(rules: RulePackage, tmp_path: Path, **changes: object) -> RulePackage:
    """``rules`` with ``changes`` applied and its checksums recomputed by the archive."""

    candidate = rules.model_copy(update={**changes, "checksums": {}, "package_sha256": None})
    path = tmp_path / "resealed.icrules"
    write_rule_package(path, candidate)
    return load_rule_package(path)


def test_a2_altitude_outside_reviewed_range_blocks(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(frequency_hz="30000", altitude_m="9900.1"),
            semantic_part4_rules,
        )

    assert caught.value.code == "ALTITUDE_OUT_OF_RANGE"


def test_f9_partial_discharge_is_source_backed_advice_not_clearance_candidate(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(
            frequency_hz="30000",
            steady_state_peak_v=PairVoltage.applicable(Decimal(3000)),
            temporary_overvoltage_peak_v=PairVoltage.not_applicable("No TOV."),
            recurring_peak_v=PairVoltage.not_applicable("No recurring peak."),
        ),
        semantic_part4_rules,
    )
    warning = next(item for item in result.warnings if item.code == "PARTIAL_DISCHARGE_REVIEW")

    assert result.clearance_mm == result.trace.pre_altitude_clearance_mm
    assert all(
        candidate.formula_id != "iec60664-1-f9" for candidate in result.trace.clearance_candidates
    )
    assert warning.semantic_rule_id == "iec60664-1:f9-partial-discharge-advice"
    assert warning.source_reference is not None
    assert warning.source_reference.table == "F.9"


def test_homogeneous_case_b_requires_source_backed_withstand_test(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(
            frequency_hz="30000",
            field_condition=FieldCondition.HOMOGENEOUS,
        ),
        semantic_part4_rules,
    )
    requirement = next(
        item for item in result.verification_requirements if item.code == "WITHSTAND_TEST_REQUIRED"
    )

    assert requirement.source_reference is not None
    assert requirement.source_reference.table == "F.8"


def test_table2_is_inactive_at_30_khz_and_clamps_first_frequency_band(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    boundary = case_factory(
        frequency_hz="30000",
        construction_type=ConstructionType.PRINTED_WIRING,
    )
    active = case_factory(
        frequency_hz="60000",
        construction_type=ConstructionType.PRINTED_WIRING,
    )

    assert select_part4_table2_creepage(boundary, semantic_part4_rules) is None
    candidate = select_part4_table2_creepage(active, semantic_part4_rules)
    assert candidate is not None
    assert candidate.steps[-2].source_cells == ("0.88/band-1",)


@pytest.mark.parametrize(
    ("frequency_hz", "pollution", "expected"),
    (("220000", 1, "6"), ("220000", 2, "7.2"), ("330000", 2, "9.0")),
)
def test_table2_frequency_policy_and_pollution_multiplier(
    frequency_hz: str,
    pollution: int,
    expected: str,
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    candidate = select_part4_table2_creepage(
        case_factory(
            frequency_hz=frequency_hz,
            construction_type=ConstructionType.PRINTED_WIRING,
            pollution_degree=pollution,
            temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(500)),
            recurring_peak_v=PairVoltage.not_applicable("No recurring peak."),
        ),
        semantic_part4_rules,
    )

    assert candidate is not None
    assert candidate.distance_mm == Decimal(expected)
    assert candidate.selection_mode == "ceiling/linear"


@pytest.mark.parametrize(
    ("frequency_hz", "peak_v"),
    (("3300001", "500"), ("220000", "1101")),
)
def test_table2_supported_range_blocks(
    frequency_hz: str,
    peak_v: str,
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    with pytest.raises(CalculationRangeError):
        select_part4_table2_creepage(
            case_factory(
                frequency_hz=frequency_hz,
                construction_type=ConstructionType.PRINTED_WIRING,
                temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(peak_v)),
                recurring_peak_v=PairVoltage.not_applicable("No recurring peak."),
            ),
            semantic_part4_rules,
        )


def test_table2_can_govern_over_f5_and_clearance_floor(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(
            frequency_hz="770000",
            construction_type=ConstructionType.PRINTED_WIRING,
            long_term_rms_v=PairVoltage.applicable(Decimal(100)),
            temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(800)),
            recurring_peak_v=PairVoltage.not_applicable("No recurring peak."),
        ),
        semantic_part4_rules,
    )

    assert result.trace.governing_creepage_candidate_id == "part4_frequency_creepage"
    assert result.creepage_mm == Decimal("19.2")
