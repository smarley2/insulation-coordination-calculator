"""Solid-insulation partial-discharge projection. Invented thresholds only; no IEC content."""

from __future__ import annotations

from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import DecisionRule, SourceReference
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.clauses import (
    ClauseNode,
    ClauseToken,
    RawClauseFragment,
)
from insulation_coordination.rules.importer.extract import canonical_model_sha256
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.clauses import (
    ClauseStructureError,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.partial_discharge import (
    CLASSIFICATION_ID,
    CLAUSE_PROJECTORS,
    PARTIAL_DISCHARGE_CLAUSES,
    project_solid_insulation_partial_discharge,
)

SOURCE = SourceReference(
    document_id="synthetic-partial-discharge",
    standard="SYNTHETIC",
    edition="1",
    page=9,
    clause="9.9",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="7" * 64,
    page_count=44,
    recipe_id="synthetic-partial-discharge",
)
#: Invented thresholds. The licensed ones are read from the document at import time.
PEAK = ("6", "kV")
STRESS = ("3", "V/mm")
PEAK_V = Decimal(6_000)
STRESS_V_PER_MM = Decimal(3)


def _fragment(*pairs: tuple[str, str], nodes: int = 3) -> RawClauseFragment:
    """A synthetic fragment whose first node states the invented thresholds in prose."""

    stated = " and ".join(f"greater than {quantity} {unit}" for quantity, unit in pairs)
    fragment = RawClauseFragment(
        id=f"raw-{ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE}",
        raw_sha256="0" * 64,
        nodes=tuple(
            ClauseNode(
                order=order,
                kind="paragraph",
                raw_text=f"synthetic neutral paragraph {order} {stated if order == 0 else ''}",
                source=SOURCE.model_copy(update={"row": f"node {order}"}),
            )
            for order in range(nodes)
        ),
        tokens=(
            ClauseToken(
                kind="condition", raw_text="synthetic", normalized="synthetic", source=SOURCE
            ),
        ),
        source=SOURCE,
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def _rules(*pairs: tuple[str, str]) -> dict[str, DecisionRule]:
    rules, _proposals = project_solid_insulation_partial_discharge(
        _fragment(*(pairs or (PEAK, STRESS))), IDENTITY
    )
    return {rule.id: rule for rule in rules}


def _applicability(*pairs: tuple[str, str]) -> DecisionRule:
    return _rules(*pairs)[ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE]


def _required(peak: Decimal, stress: Decimal) -> bool:
    result = evaluate_decision(
        _applicability(),
        {"working_voltage_recurring_peak_v": peak, "voltage_stress_v_per_mm": stress},
    )
    assert result.status == "matched", (peak, stress)
    (value,) = result.values
    assert value.name == "partial_discharge_test_required"
    assert value.boolean is not None
    return value.boolean


def _classification(single_layer: bool) -> dict[str, bool | None]:
    result = evaluate_decision(
        _rules()[CLASSIFICATION_ID],
        {"insulation_is_single_layer_of_material": single_layer},
    )
    assert result.status == "matched"
    return {value.name: value.boolean for value in result.values}


def test_the_clause_locator_is_structural_only() -> None:
    (spec,) = PARTIAL_DISCHARGE_CLAUSES
    assert spec.semantic_id == ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE
    assert spec.clause == "4.4.7.10.3"
    assert spec.output_kind == "decision"
    assert len(spec.segments) == 3
    assert {segment.page_number for segment in spec.segments} == {77}
    assert {segment.expected_root_kind for segment in spec.segments} == {"paragraph"}
    assert spec.projected_rule_ids == (
        ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE,
        CLASSIFICATION_ID,
    )
    assert CLAUSE_PROJECTORS == {
        ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE: project_solid_insulation_partial_discharge
    }


def test_the_clause_projects_both_of_the_routes_it_declares() -> None:
    rules, proposals = project_solid_insulation_partial_discharge(_fragment(PEAK, STRESS), IDENTITY)
    assert [rule.id for rule in rules] == [
        ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE,
        CLASSIFICATION_ID,
    ]
    assert [proposal.semantic_id for proposal in proposals] == [rule.id for rule in rules]
    assert {proposal.rule_kind for proposal in proposals} == {"decision"}


def test_both_conditions_together_settle_a_yes() -> None:
    assert _required(PEAK_V + 1, STRESS_V_PER_MM + 1) is True


@pytest.mark.parametrize(
    ("peak", "stress"),
    [
        (PEAK_V, STRESS_V_PER_MM + 1),
        (PEAK_V + 1, STRESS_V_PER_MM),
        (PEAK_V - 1, STRESS_V_PER_MM - 1),
    ],
)
def test_either_condition_alone_settles_a_no(peak: Decimal, stress: Decimal) -> None:
    """The source joins the two with *and*, and the answer is settled rather than unreachable."""

    assert _required(peak, stress) is False


def test_a_threshold_is_exceeded_rather_than_reached() -> None:
    assert _required(PEAK_V, STRESS_V_PER_MM) is False


def test_both_thresholds_are_read_from_the_fragment_not_declared() -> None:
    bounds = {
        pairs: {
            matcher.input: matcher.minimum
            for row in _applicability(*pairs).rows
            for matcher in row.matchers
            if matcher.minimum is not None
        }
        for pairs in ((PEAK, STRESS), (("9", "V"), ("2", "kV/mm")))
    }
    assert bounds[(PEAK, STRESS)] == {
        "working_voltage_recurring_peak_v": PEAK_V,
        "voltage_stress_v_per_mm": STRESS_V_PER_MM,
    }
    assert bounds[(("9", "V"), ("2", "kV/mm"))] == {
        "working_voltage_recurring_peak_v": Decimal(9),
        "voltage_stress_v_per_mm": Decimal(2_000),
    }


def test_each_threshold_is_placed_by_its_unit_not_by_its_position() -> None:
    assert _applicability(STRESS, PEAK).rows == _applicability(PEAK, STRESS).rows


def test_the_classification_is_the_type_test_always_and_the_sample_test_on_one_layer() -> None:
    assert _classification(single_layer=False) == {
        "type_test_required": True,
        "sample_test_required": False,
    }
    assert _classification(single_layer=True) == {
        "type_test_required": True,
        "sample_test_required": True,
    }


def test_the_classification_answers_every_construction_it_declares() -> None:
    assert _rules()[CLASSIFICATION_ID].exhaustive is True


@pytest.mark.parametrize(
    "pairs",
    [
        (),
        (PEAK,),
        (STRESS,),
        (PEAK, PEAK, STRESS),
        (PEAK, STRESS, STRESS),
    ],
)
def test_a_fragment_without_one_threshold_of_each_kind_blocks(
    pairs: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_solid_insulation_partial_discharge(_fragment(*pairs), IDENTITY)


@pytest.mark.parametrize("nodes", [1, 2, 4])
def test_a_fragment_of_the_wrong_shape_blocks(nodes: int) -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_solid_insulation_partial_discharge(_fragment(PEAK, STRESS, nodes=nodes), IDENTITY)


def test_a_foreign_fragment_cannot_be_projected() -> None:
    foreign = _fragment(PEAK, STRESS).model_copy(update={"id": "raw-other-clause"})
    with pytest.raises(ValueError, match="solid insulation partial discharge"):
        project_solid_insulation_partial_discharge(foreign, IDENTITY)
