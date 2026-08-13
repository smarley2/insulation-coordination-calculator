"""High-frequency applicability projection. Invented thresholds only; no IEC content."""

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
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.high_frequency import (
    CLAUSE_PROJECTORS,
    HIGH_FREQUENCY_CLAUSES,
    project_high_frequency_applicability,
)

SOURCE = SourceReference(
    document_id="synthetic-high-frequency",
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
    recipe_id="synthetic-high-frequency",
)
#: Invented bounds. The licensed thresholds are read from the document at import time.
LOWER = ("7", "kHz")
UPPER = ("4", "MHz")
LOWER_HZ = Decimal(7_000)
UPPER_HZ = Decimal(4_000_000)


def _fragment(*pairs: tuple[str, str], nodes: int = 1) -> RawClauseFragment:
    """A synthetic fragment whose first node states the invented bounds in prose.

    The projection reads the bounds from the reviewed node text, because the real clause
    writes its upper bound with sentence punctuation the generic tokenizer discards.
    """

    stated = ", ".join(f"greater than {quantity} {unit}," for quantity, unit in pairs)
    fragment = RawClauseFragment(
        id=f"raw-{ids.HIGH_FREQUENCY_APPLICABILITY}",
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


def _project(*pairs: tuple[str, str]) -> DecisionRule:
    rules, _proposals = project_high_frequency_applicability(
        _fragment(*(pairs or (LOWER, UPPER))), IDENTITY
    )
    return next(
        rule
        for rule in rules
        if isinstance(rule, DecisionRule) and rule.id == ids.HIGH_FREQUENCY_APPLICABILITY
    )


def _inputs(**overrides: Decimal | str) -> dict[str, Decimal | str]:
    inputs: dict[str, Decimal | str] = {
        "working_voltage_frequency_hz": LOWER_HZ * 10,
        "insulation_kind": "clearance_inhomogeneous_field",
        "stress_kind": "working_voltage",
    }
    inputs.update(overrides)
    return inputs


def _row(**overrides: Decimal | str) -> object:
    result = evaluate_decision(_project(), _inputs(**overrides))
    assert result.status == "matched", overrides
    return result


def _value(result: object, name: str) -> object:
    value = next(item for item in result.values if item.name == name)  # type: ignore[attr-defined]
    for field in (value.categorical, value.numeric, value.boolean, value.reference):
        if field is not None:
            return field
    raise AssertionError(f"decision value {name} carries nothing")


def test_the_clause_locator_is_structural_only() -> None:
    (spec,) = HIGH_FREQUENCY_CLAUSES
    assert spec.semantic_id == ids.HIGH_FREQUENCY_APPLICABILITY
    (segment,) = spec.segments
    assert (spec.clause, segment.page_number) == ("F.1", 195)
    assert segment.expected_root_kind == "paragraph"
    assert spec.output_kind == "decision"
    assert CLAUSE_PROJECTORS == {
        ids.HIGH_FREQUENCY_APPLICABILITY: project_high_frequency_applicability
    }


def test_below_the_lower_threshold_the_main_clause_governs() -> None:
    result = _row(working_voltage_frequency_hz=LOWER_HZ - 1)
    assert _value(result, "high_frequency_evaluation_required") is False
    assert _value(result, "governing_result") == "main_clause"
    assert _value(result, "applicable_design_situations") == "not_applicable"


def test_each_insulation_kind_routes_to_its_own_annex_situation() -> None:
    situations = {
        kind: _value(_row(insulation_kind=kind), "applicable_design_situations")
        for kind in (
            "clearance_inhomogeneous_field",
            "clearance_homogeneous_field",
            "creepage",
            "solid_insulation",
        )
    }
    assert len(set(situations.values())) == 4
    assert set(situations.values()) == {
        "annex_f_2_2",
        "annex_f_2_3",
        "annex_f_3",
        "annex_f_4",
    }
    for kind in situations:
        result = _row(insulation_kind=kind)
        assert _value(result, "high_frequency_evaluation_required") is True
        assert _value(result, "governing_result") == "greater_of_both"


def test_impulse_driven_spacing_stays_with_the_main_clause() -> None:
    for stress_kind in ("impulse_withstand", "temporary_overvoltage"):
        result = _row(stress_kind=stress_kind)
        assert _value(result, "high_frequency_evaluation_required") is False
        assert _value(result, "governing_result") == "main_clause"


def test_a_frequency_above_the_annex_scope_requires_engineering_review() -> None:
    result = _row(working_voltage_frequency_hz=UPPER_HZ * 5)
    assert _value(result, "governing_result") == "engineering_review_required"
    assert _value(result, "high_frequency_evaluation_required") is True


def test_both_thresholds_are_read_from_the_fragment_not_declared() -> None:
    bounds = {
        pairs: sorted(
            {
                bound
                for row in _project(*pairs).rows
                for matcher in row.matchers
                if matcher.input == "working_voltage_frequency_hz"
                for bound in (matcher.minimum, matcher.maximum)
                if bound is not None
            }
        )
        for pairs in ((LOWER, UPPER), (("3", "kHz"), ("9", "MHz")))
    }
    assert bounds[(LOWER, UPPER)] == [LOWER_HZ, UPPER_HZ]
    assert bounds[(("3", "kHz"), ("9", "MHz"))] == [Decimal(3_000), Decimal(9_000_000)]


def test_the_threshold_order_does_not_depend_on_the_token_order() -> None:
    assert _project(UPPER, LOWER).rows == _project(LOWER, UPPER).rows


@pytest.mark.parametrize(
    "pairs",
    [
        (),
        (LOWER,),
        (LOWER, UPPER, ("5", "MHz")),
    ],
)
def test_a_fragment_without_exactly_two_frequency_pairs_blocks(
    pairs: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_high_frequency_applicability(_fragment(*pairs), IDENTITY)


def test_two_equal_thresholds_block() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_high_frequency_applicability(_fragment(LOWER, LOWER), IDENTITY)


def test_a_multi_node_fragment_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_high_frequency_applicability(_fragment(LOWER, UPPER, nodes=2), IDENTITY)


def test_a_foreign_fragment_cannot_be_projected() -> None:
    foreign = _fragment(LOWER, UPPER).model_copy(update={"id": "raw-other-clause"})
    with pytest.raises(ValueError, match="high-frequency"):
        project_high_frequency_applicability(foreign, IDENTITY)


def test_the_rule_is_not_exhaustive_and_proposes_itself() -> None:
    rules, proposals = project_high_frequency_applicability(_fragment(LOWER, UPPER), IDENTITY)
    assert len(rules) == 1
    assert rules[0].exhaustive is False
    assert [proposal.semantic_id for proposal in proposals] == [ids.HIGH_FREQUENCY_APPLICABILITY]
    assert {proposal.rule_kind for proposal in proposals} == {"decision"}
