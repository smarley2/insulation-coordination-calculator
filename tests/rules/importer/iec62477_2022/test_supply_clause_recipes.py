"""Synthetic supply-clause projections. Invented values only; no IEC content."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import (
    DecisionRule,
    GuidanceRule,
    SourceReference,
)
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.clauses import (
    ClauseNode,
    ClauseToken,
    RawClauseFragment,
)
from insulation_coordination.rules.importer.extract import canonical_model_sha256
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.clauses import (
    ClauseStructureError,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    SUPPLY_CLAUSES,
    project_hf_transformer_attenuation,
    project_multiple_source_propagation,
    project_spd_reduction_requirements,
    project_system_voltage_resolution,
    project_verified_barrier_transfer,
)

SOURCE = SourceReference(
    document_id="synthetic-supply",
    standard="SYNTHETIC",
    edition="1",
    page=9,
    clause="9.9.9",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="6" * 64,
    page_count=44,
    recipe_id="synthetic-supply",
)


def _fragment(
    semantic_id: str,
    *,
    kind: str = "bullet",
    count: int = 1,
    tokens: tuple[ClauseToken, ...] = (),
) -> RawClauseFragment:
    nodes = tuple(
        ClauseNode(
            order=order,
            kind=kind,
            raw_text=f"synthetic neutral {kind} node {order}",
            source=SOURCE.model_copy(update={"row": f"node {order}"}),
        )
        for order in range(count)
    )
    fragment = RawClauseFragment(
        id=f"raw-{semantic_id}",
        raw_sha256="0" * 64,
        nodes=nodes,
        tokens=tokens,
        source=SOURCE,
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def _bullet_fragment(*, count: int = 3) -> RawClauseFragment:
    return _fragment(ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, kind="bullet", count=count)


def _lettered_fragment(*, count: int = 4) -> RawClauseFragment:
    return _fragment(ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION, kind="bullet", count=count)


def _paragraph_fragment(
    semantic_id: str,
    *,
    count: int = 1,
    tokens: tuple[ClauseToken, ...] = (),
) -> RawClauseFragment:
    return _fragment(semantic_id, kind="paragraph", count=count, tokens=tokens)


def _decision(rules: tuple[object, ...], semantic_id: str) -> DecisionRule:
    return next(rule for rule in rules if isinstance(rule, DecisionRule) and rule.id == semantic_id)


def _project_system_voltage(fragment: RawClauseFragment) -> DecisionRule:
    rules, _proposals = project_system_voltage_resolution(fragment, IDENTITY)
    return _decision(rules, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)


def _project_propagation(fragment: RawClauseFragment) -> DecisionRule:
    rules, _proposals = project_multiple_source_propagation(fragment, IDENTITY)
    return _decision(rules, ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION)


def _project_barrier(fragment: RawClauseFragment) -> DecisionRule:
    rules, _proposals = project_verified_barrier_transfer(fragment, IDENTITY)
    return _decision(rules, ids.SUPPLY_VERIFIED_BARRIER_TRANSFER)


def _lookup(rule: DecisionRule, **inputs: Decimal | str | bool) -> object | None:
    result = evaluate_decision(rule, inputs)
    return result if result.status == "matched" else None


def _value(result: object, name: str) -> object:
    value = next(item for item in result.values if item.name == name)  # type: ignore[attr-defined]
    for field in (value.categorical, value.numeric, value.boolean, value.reference):
        if field is not None:
            return field
    raise AssertionError(f"decision value {name} carries nothing")


def _system_voltage_inputs(**overrides: str) -> dict[str, str]:
    inputs = {
        "supply_kind": "mains",
        "phase_system": "three_phase_star",
        "earthing_arrangement": "tn",
        "input_topology": "direct",
        "calculation_purpose": "impulse",
    }
    inputs.update(overrides)
    return inputs


# --- Task 6: system voltage, propagation, barrier transfer -------------------------


def test_every_declared_branch_is_reachable_and_unsupported_combinations_are_not() -> None:
    rule = _project_system_voltage(_bullet_fragment())
    assert len(rule.rows) == 9
    assert rule.exhaustive is False
    matched = {
        evaluate_decision(rule, _system_voltage_inputs(**overrides)).matched_row
        for overrides in (
            {},
            {"phase_system": "three_phase_delta"},
            {"phase_system": "three_phase_it", "earthing_arrangement": "it"},
            {
                "phase_system": "three_phase_it",
                "earthing_arrangement": "it",
                "calculation_purpose": "temporary_overvoltage",
            },
            {"phase_system": "single_phase_it", "earthing_arrangement": "it"},
            {"input_topology": "rectified_dc"},
            {"input_topology": "series_rectifier_bridges"},
            {"input_topology": "isolated_secondary"},
            {
                "supply_kind": "non_mains",
                "phase_system": "single_phase",
                "earthing_arrangement": "unspecified",
            },
        )
    }
    assert matched == set(range(9))
    assert _lookup(rule, **_system_voltage_inputs(phase_system="unspecified")) is None


def test_impulse_and_temporary_overvoltage_branches_stay_separate() -> None:
    rule = _project_system_voltage(_bullet_fragment())
    impulse = _lookup(
        rule,
        **_system_voltage_inputs(
            phase_system="three_phase_it",
            earthing_arrangement="it",
            calculation_purpose="impulse",
        ),
    )
    tov = _lookup(
        rule,
        **_system_voltage_inputs(
            phase_system="three_phase_it",
            earthing_arrangement="it",
            calculation_purpose="temporary_overvoltage",
        ),
    )
    assert impulse is not None and tov is not None
    assert _value(impulse, "system_voltage_measure") != _value(tov, "system_voltage_measure")


def test_the_note_becomes_guidance_and_never_a_formula() -> None:
    rules, proposals = project_system_voltage_resolution(_bullet_fragment(), IDENTITY)
    assert any(isinstance(rule, GuidanceRule) for rule in rules)
    assert not any(getattr(rule, "expression", None) for rule in rules)
    assert not any(getattr(rule, "expression_shape", None) for rule in rules)
    assert {proposal.rule_kind for proposal in proposals} == {"decision", "guidance"}


def test_a_fragment_whose_bullet_count_differs_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_system_voltage_resolution(_bullet_fragment(count=7), IDENTITY)


def test_a_foreign_fragment_cannot_be_projected() -> None:
    foreign = _bullet_fragment().model_copy(update={"id": "raw-other-clause"})
    with pytest.raises(ValueError, match="system voltage"):
        project_system_voltage_resolution(foreign, IDENTITY)


def test_a_fragment_from_another_standard_cannot_be_projected() -> None:
    other = _bullet_fragment()
    other = other.model_copy(update={"source": other.source.model_copy(update={"edition": "2"})})
    with pytest.raises(ValueError, match="identified source"):
        project_system_voltage_resolution(other, IDENTITY)


def test_propagation_is_evaluated_in_both_directions() -> None:
    rule = _project_propagation(_lettered_fragment())
    common = {
        "mains_overvoltage_category": "ovc_ii",
        "non_mains_overvoltage_category": "ovc_iv",
        "galvanic_isolation_present": True,
    }
    mains_side = _lookup(rule, evaluated_side="mains", **common)
    non_mains_side = _lookup(rule, evaluated_side="non_mains", **common)
    assert mains_side is not None and non_mains_side is not None
    assert _value(mains_side, "transferred_requirement") != _value(mains_side, "source_requirement")
    assert _value(mains_side, "source_requirement") == "ovc_ii"
    assert _value(non_mains_side, "source_requirement") == "ovc_iv"
    assert _value(mains_side, "governing_requirement") == "ovc_iii"
    assert _value(non_mains_side, "governing_requirement") == "ovc_iv"


def test_propagation_without_verified_isolation_is_not_covered_here() -> None:
    rule = _project_propagation(_lettered_fragment())
    assert (
        _lookup(
            rule,
            evaluated_side="mains",
            mains_overvoltage_category="ovc_ii",
            non_mains_overvoltage_category="ovc_iv",
            galvanic_isolation_present=False,
        )
        is None
    )


def test_a_propagation_fragment_with_the_wrong_alternative_count_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_multiple_source_propagation(_lettered_fragment(count=3), IDENTITY)


def test_without_verified_isolation_the_combined_requirement_propagates() -> None:
    rule = _project_barrier(_paragraph_fragment(ids.SUPPLY_VERIFIED_BARRIER_TRANSFER))
    row = _lookup(
        rule,
        galvanic_isolation_verified=False,
        isolation_evidence_kind="none",
        downstream_connection_kind="no_isolation",
    )
    assert row is not None
    assert _value(row, "propagates_to_connected_circuits") is True
    assert _value(row, "transfer_permitted") is False
    assert _value(row, "combined_circuit_requirement") == "more_severe_of_both_sides"


def test_verified_isolation_keeps_the_transfer_side_specific() -> None:
    rule = _project_barrier(_paragraph_fragment(ids.SUPPLY_VERIFIED_BARRIER_TRANSFER))
    row = _lookup(
        rule,
        galvanic_isolation_verified=True,
        isolation_evidence_kind="test",
        downstream_connection_kind="verified_galvanic_isolation",
    )
    assert row is not None
    assert _value(row, "transfer_permitted") is True
    assert _value(row, "propagates_to_connected_circuits") is False


def test_a_barrier_fragment_with_extra_nodes_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_verified_barrier_transfer(
            _paragraph_fragment(ids.SUPPLY_VERIFIED_BARRIER_TRANSFER, count=2),
            IDENTITY,
        )


# --- Task 7: transient limiter and high-frequency transformer ----------------------


def _spd_inputs(**overrides: str | bool) -> dict[str, str | bool]:
    inputs: dict[str, str | bool] = {
        "device_placement": "internal_to_pecs",
        "insulation_class": "basic",
        "device_degradable": False,
        "part_of_category_reduction": True,
    }
    inputs.update(overrides)
    return inputs


_SPD_MAINS_ID = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"
_SPD_NON_MAINS_ID = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains"
_SPD_MONITORING_ID = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"


def _project_spd(fragment: RawClauseFragment) -> DecisionRule:
    rules, _proposals = project_spd_reduction_requirements(fragment, IDENTITY)
    # The produced rule's id is whichever route the fragment names -- there is no
    # longer one bare id to look up.
    return _decision(rules, fragment.id.removeprefix("raw-"))


def _frequency_tokens(
    *pairs: tuple[str, str],
) -> tuple[ClauseToken, ...]:
    """Invented quantity/unit token pairs; the real threshold is never in this repo."""

    tokens: list[ClauseToken] = []
    for quantity, unit in pairs:
        tokens.append(
            ClauseToken(
                kind="quantity",
                raw_text=quantity,
                normalized=Decimal(quantity),
                source=SOURCE,
            )
        )
        tokens.append(ClauseToken(kind="unit", raw_text=unit, normalized=unit, source=SOURCE))
    return tuple(tokens)


def _hf_fragment(*pairs: tuple[str, str]) -> RawClauseFragment:
    return _paragraph_fragment(
        ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        tokens=_frequency_tokens(*pairs) if pairs else (),
    )


def _project_hf_transformer(fragment: RawClauseFragment) -> DecisionRule:
    rules, _proposals = project_hf_transformer_attenuation(fragment, IDENTITY)
    return _decision(rules, ids.SUPPLY_HF_TRANSFORMER_ATTENUATION)


def _hf_inputs(**overrides: Decimal | str | bool) -> dict[str, Decimal | str | bool]:
    inputs: dict[str, Decimal | str | bool] = {
        "circuit_dvc": "dvc_b",
        "transformer_frequency_hz": Decimal(500000),
        "isolation_provided": True,
        "attenuation_evidence_kind": "test",
    }
    inputs.update(overrides)
    return inputs


def test_double_and_reinforced_insulation_keep_the_unreduced_floor() -> None:
    rule = _project_spd(_paragraph_fragment(_SPD_MAINS_ID))
    row = _lookup(rule, **_spd_inputs(insulation_class="reinforced"))
    assert row is not None
    assert _value(row, "reinforced_floor_applies") is True
    assert _value(row, "reduction_permitted") is False
    assert _value(row, "reduced_category") == "not_reduced"


def test_a_degradable_device_requires_monitoring_and_indication() -> None:
    rule = _project_spd(_paragraph_fragment(_SPD_MAINS_ID))
    row = _lookup(rule, **_spd_inputs(device_degradable=True))
    assert row is not None
    assert _value(row, "monitoring_required") is True
    assert _value(row, "status_indication_required") is True
    assert _value(row, "reduction_permitted") is True


def test_a_device_outside_a_category_reduction_is_exempt() -> None:
    rule = _project_spd(_paragraph_fragment(_SPD_MAINS_ID))
    row = _lookup(rule, **_spd_inputs(device_degradable=True, part_of_category_reduction=False))
    assert row is not None
    assert _value(row, "monitoring_required") is False
    assert _value(row, "reduction_permitted") is False
    assert _value(row, "verification_reference") == "not_required"


def test_each_spd_route_is_projected_under_its_own_id() -> None:
    """The projector is registered once per route and shares one body (Task 6 splits it).

    Each route's fragment must still come back out under that route's own rule id.
    """

    for route_id in (_SPD_MAINS_ID, _SPD_NON_MAINS_ID, _SPD_MONITORING_ID):
        rule = _project_spd(_paragraph_fragment(route_id))
        assert rule.id == route_id


def test_every_reduction_route_enforces_its_reviewed_shape() -> None:
    """All three routes' shapes are measured, so a reflowed clause blocks on any of them.

    Each route reads its own clause through its own bbox, so a reprint that splits one of
    them across a different number of nodes must stop the build rather than project a rule
    from a region nobody reviewed.
    """

    for route_id in (_SPD_MONITORING_ID, _SPD_MAINS_ID, _SPD_NON_MAINS_ID):
        malformed = _paragraph_fragment(route_id, count=2)
        with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
            project_spd_reduction_requirements(malformed, IDENTITY)


def test_the_transformer_route_needs_evidence_before_it_permits_anything() -> None:
    rule = _project_hf_transformer(_hf_fragment(("42", "kHz")))
    without = _lookup(rule, **_hf_inputs(attenuation_evidence_kind="none"))
    assert without is not None
    assert _value(without, "working_voltage_basis_permitted") is False
    assert set(str(_value(without, "required_evidence_kinds")).split("_or_")) == {
        "test",
        "simulation",
        "calculation",
    }


def test_the_transformer_threshold_is_read_from_the_fragment_not_declared() -> None:
    bounds = {}
    for quantity, unit, expected in (("42", "kHz", "42000"), ("3", "MHz", "3000000")):
        rule = _project_hf_transformer(_hf_fragment((quantity, unit)))
        matcher = next(
            matcher
            for row in rule.rows
            for matcher in row.matchers
            if matcher.input == "transformer_frequency_hz"
        )
        bounds[expected] = matcher.minimum
        assert matcher.minimum == Decimal(expected)
    assert len(set(bounds.values())) == 2


def test_a_frequency_below_the_extracted_threshold_is_not_covered() -> None:
    rule = _project_hf_transformer(_hf_fragment(("42", "kHz")))
    assert _lookup(rule, **_hf_inputs(transformer_frequency_hz=Decimal(100))) is None


def test_a_transformer_fragment_without_a_frequency_pair_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_hf_transformer_attenuation(_hf_fragment(), IDENTITY)


def test_a_transformer_fragment_with_two_frequency_pairs_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_hf_transformer_attenuation(_hf_fragment(("42", "kHz"), ("7", "MHz")), IDENTITY)


def test_no_supply_recipe_file_declares_a_frequency_threshold() -> None:
    """The licensed thresholds are extracted at import time, never committed.

    Unit names may appear (the projection has to recognise them); a number written
    next to one would be a declared threshold, which is what this guard forbids.
    """

    directory = Path("src/insulation_coordination/rules/importer/recipes/iec62477_1_2022")
    paths = sorted(directory.glob("*.py"))
    assert paths
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"[0-9][^\S\n]*[\"']?[^\S\n]*(?:k|M)?Hz", text) is None, path


def test_the_recipe_declares_and_registers_every_supply_clause() -> None:
    declared = {spec.semantic_id for spec in SUPPLY_CLAUSES}
    assert declared <= {spec.semantic_id for spec in IEC_RECIPE.clauses}
    assert declared <= set(IEC_RECIPE.clause_projectors)
    assert {
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        _SPD_MAINS_ID,
        _SPD_NON_MAINS_ID,
        _SPD_MONITORING_ID,
        ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
    } <= declared
    assert all(spec.output_kind == "decision" for spec in SUPPLY_CLAUSES)
    assert all(65.0 <= spec.expected_bbox[0] for spec in SUPPLY_CLAUSES)


def test_the_reduction_rule_is_read_from_the_clauses_that_state_it() -> None:
    """The identifier previously pointed at the monitoring clause, which does not state the rule.

    The reduction is stated once for mains supply and once for non-mains supply, with different
    permitted category steps, so it is two routes of one family rather than one rule.
    """
    by_id = {spec.semantic_id: spec for spec in SUPPLY_CLAUSES}
    mains = by_id[_SPD_MAINS_ID]
    non_mains = by_id[_SPD_NON_MAINS_ID]
    monitoring = by_id[_SPD_MONITORING_ID]

    assert (mains.clause, mains.page_number) == ("4.4.7.2.3", 65)
    assert (non_mains.clause, non_mains.page_number) == ("4.4.7.2.4", 66)
    assert (monitoring.clause, monitoring.page_number) == ("4.4.7.2.2", 65)


def test_no_supply_route_reads_a_clause_that_does_not_state_its_rule() -> None:
    """Guard against the defect returning: the bare reduction id must declare no fragment."""

    declared = {spec.semantic_id for spec in SUPPLY_CLAUSES}

    assert ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS not in declared
