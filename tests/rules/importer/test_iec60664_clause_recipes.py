"""The two IEC 60664 boundary clauses and their projections. Invented figures only.

Every quantity below is author-invented. The licensed ones are read from the reviewed
fragment's own node text at import time and never reach this file.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import DecisionRule, SourceReference
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.artifacts import ExtractionError
from insulation_coordination.rules.importer.clauses import (
    ClauseNode,
    ClauseToken,
    RawClauseFragment,
)
from insulation_coordination.rules.importer.extract import canonical_model_sha256
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.recipes import RECIPES
from insulation_coordination.rules.importer.recipes.iec60664_1_2020 import (
    RECIPE as PART1_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec60664_4_2005 import (
    RECIPE as PART4_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec60664_clauses import (
    PART4_SCOPE_CLAUSES,
    PART4_SCOPE_FREQUENCY_APPLICABILITY,
    PARTIAL_DISCHARGE_ADVICE,
    PARTIAL_DISCHARGE_ADVICE_CLAUSES,
    project_part4_frequency_scope,
    project_partial_discharge_advice,
)

PART4_IDENTITY = StandardIdentity(
    standard="SYNTHETIC-4",
    edition="1",
    sha256="4" * 64,
    page_count=44,
    recipe_id="synthetic-part4-scope",
)
PART1_IDENTITY = StandardIdentity(
    standard="SYNTHETIC-1",
    edition="1",
    sha256="1" * 64,
    page_count=44,
    recipe_id="synthetic-partial-discharge-advice",
)

#: Invented band, stated in two different units so the projection has to normalize.
LOWER = ("7", "kHz")
UPPER = ("3", "MHz")
LOWER_HZ = Decimal(7_000)
UPPER_HZ = Decimal(3_000_000)

#: Invented advisory boundary.
ADVICE = ("9", "kV")
ADVICE_V = Decimal(9_000)


def _fragment(
    semantic_id: str,
    identity: StandardIdentity,
    *quantities: tuple[str, str],
    nodes: int = 1,
) -> RawClauseFragment:
    """A synthetic fragment whose first node states the invented quantities in prose."""

    source = SourceReference(
        document_id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        page=9,
        clause="9.9",
    )
    stated = " ".join(f"{quantity} {unit}" for quantity, unit in quantities)
    fragment = RawClauseFragment(
        id=f"raw-{semantic_id}",
        raw_sha256="0" * 64,
        nodes=tuple(
            ClauseNode(
                order=order,
                kind="paragraph",
                raw_text=f"synthetic neutral paragraph {order} {stated if order == 0 else ''}",
                source=source.model_copy(update={"row": f"node {order}"}),
            )
            for order in range(nodes)
        ),
        tokens=(
            ClauseToken(
                kind="condition", raw_text="synthetic", normalized="synthetic", source=source
            ),
        ),
        source=source,
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def _scope_rule(quantities: tuple[tuple[str, str], ...] = (LOWER, UPPER)) -> DecisionRule:
    fragment = _fragment(PART4_SCOPE_FREQUENCY_APPLICABILITY, PART4_IDENTITY, *quantities)
    (rule,), _proposals = project_part4_frequency_scope(fragment, PART4_IDENTITY)
    return rule


def _advice_rule(quantities: tuple[tuple[str, str], ...] = (ADVICE,)) -> DecisionRule:
    fragment = _fragment(PARTIAL_DISCHARGE_ADVICE, PART1_IDENTITY, *quantities)
    (rule,), _proposals = project_partial_discharge_advice(fragment, PART1_IDENTITY)
    return rule


def _answer(rule: DecisionRule, inputs: dict[str, Decimal], output: str) -> bool:
    result = evaluate_decision(rule, inputs)
    assert result.status == "matched", inputs
    (value,) = result.values
    assert value.name == output
    assert value.boolean is not None
    return value.boolean


def _applies(frequency: Decimal) -> bool:
    return _answer(_scope_rule(), {"frequency_hz": frequency}, "part4_dimensioning_applies")


def _advised(peak: Decimal) -> bool:
    return _answer(
        _advice_rule(), {"steady_state_peak_v": peak}, "partial_discharge_review_advised"
    )


# --- the locators ------------------------------------------------------------------


def test_the_part4_scope_locator_is_structural_only() -> None:
    (spec,) = PART4_SCOPE_CLAUSES
    assert spec.semantic_id == PART4_SCOPE_FREQUENCY_APPLICABILITY
    assert spec.clause == "1"
    assert spec.output_kind == "decision"
    assert len(spec.segments) == 1
    assert spec.segments[0].expected_root_kind == "paragraph"
    assert spec.projection_role == "rule"
    assert not spec.projected_rule_ids


def test_the_advisory_locator_carries_the_identifier_the_warning_already_names() -> None:
    (spec,) = PARTIAL_DISCHARGE_ADVICE_CLAUSES
    assert spec.semantic_id == "iec60664-1:f9-partial-discharge-advice"
    assert spec.clause == "Annex F"
    assert spec.output_kind == "decision"
    assert len(spec.segments) == 1
    assert spec.segments[0].expected_root_kind == "paragraph"


def test_both_recipes_declare_their_clause_and_exactly_one_projector_each() -> None:
    assert PART4_RECIPE.clauses == PART4_SCOPE_CLAUSES
    assert set(PART4_RECIPE.clause_projectors) == {PART4_SCOPE_FREQUENCY_APPLICABILITY}
    assert PART1_RECIPE.clauses == PARTIAL_DISCHARGE_ADVICE_CLAUSES
    assert set(PART1_RECIPE.clause_projectors) == {PARTIAL_DISCHARGE_ADVICE}


def test_the_two_boundaries_are_declared_by_the_registry() -> None:
    declared = {spec.semantic_id for recipe in RECIPES for spec in recipe.clauses}
    assert {PART4_SCOPE_FREQUENCY_APPLICABILITY, PARTIAL_DISCHARGE_ADVICE} <= declared


# --- the Part 4 scope rule ---------------------------------------------------------


def test_the_scope_rule_answers_the_frequency_gate() -> None:
    assert _applies(LOWER_HZ + 1) is True
    assert _applies(UPPER_HZ) is True


def test_the_scope_rule_excludes_its_lower_bound_and_includes_its_upper_bound() -> None:
    """The clause states the lower bound as an exclusion and the upper bound as an inclusion."""

    assert _applies(LOWER_HZ) is False
    assert _applies(UPPER_HZ + 1) is False


def test_a_frequency_outside_the_band_reaches_a_settled_no() -> None:
    assert _applies(Decimal(1)) is False


def test_the_band_is_read_from_the_fragment_and_normalized_to_hertz() -> None:
    def bounds(
        quantities: tuple[tuple[str, str], ...] = (LOWER, UPPER),
    ) -> set[tuple[Decimal | None, Decimal | None]]:
        return {
            (matcher.minimum, matcher.maximum)
            for row in _scope_rule(quantities).rows
            for matcher in row.matchers
            if matcher.op == "range"
        }

    assert bounds() == {(LOWER_HZ, UPPER_HZ)}
    assert bounds((("2", "Hz"), ("5", "GHz"))) == {(Decimal(2), Decimal(5_000_000_000))}


def test_the_bounds_are_placed_by_magnitude_not_by_position() -> None:
    assert _scope_rule((UPPER, LOWER)).rows == _scope_rule((LOWER, UPPER)).rows


@pytest.mark.parametrize("quantities", [(), (LOWER,), (LOWER, UPPER, ("5", "MHz"))])
def test_a_scope_fragment_without_exactly_two_bounds_blocks(
    quantities: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ExtractionError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        _scope_rule(quantities)


# --- the Annex F advisory rule -----------------------------------------------------


def test_the_advisory_boundary_is_reached_rather_than_exceeded() -> None:
    """The clause states its boundary as a value the stress reaches, not one it passes."""

    assert _advised(ADVICE_V) is True
    assert _advised(ADVICE_V + 1) is True
    assert _advised(ADVICE_V - 1) is False


def test_the_advisory_boundary_is_read_from_the_fragment_and_normalized_to_volts() -> None:
    def minimums(quantities: tuple[tuple[str, str], ...] = (ADVICE,)) -> set[Decimal | None]:
        return {
            matcher.minimum for row in _advice_rule(quantities).rows for matcher in row.matchers
        } - {None}

    assert minimums() == {ADVICE_V}
    assert minimums((("8", "V"),)) == {Decimal(8)}


@pytest.mark.parametrize("quantities", [(), (ADVICE, ("4", "V"))])
def test_an_advisory_fragment_without_exactly_one_boundary_blocks(
    quantities: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ExtractionError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        _advice_rule(quantities)


# --- shared refusals ---------------------------------------------------------------


@pytest.mark.parametrize("nodes", [2, 3])
def test_a_fragment_of_the_wrong_shape_blocks(nodes: int) -> None:
    scope = _fragment(
        PART4_SCOPE_FREQUENCY_APPLICABILITY, PART4_IDENTITY, LOWER, UPPER, nodes=nodes
    )
    with pytest.raises(ExtractionError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_part4_frequency_scope(scope, PART4_IDENTITY)
    advice = _fragment(PARTIAL_DISCHARGE_ADVICE, PART1_IDENTITY, ADVICE, nodes=nodes)
    with pytest.raises(ExtractionError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_partial_discharge_advice(advice, PART1_IDENTITY)


def test_a_foreign_fragment_cannot_be_projected() -> None:
    own = _fragment(PART4_SCOPE_FREQUENCY_APPLICABILITY, PART4_IDENTITY, LOWER, UPPER)
    foreign = own.model_copy(update={"id": "raw-other-clause"})
    with pytest.raises(ValueError, match="Part 4 frequency scope"):
        project_part4_frequency_scope(foreign, PART4_IDENTITY)


def test_a_fragment_from_another_document_cannot_be_projected() -> None:
    stray = _fragment(PARTIAL_DISCHARGE_ADVICE, PART4_IDENTITY, ADVICE)
    with pytest.raises(ValueError, match="partial-discharge advice"):
        project_partial_discharge_advice(stray, PART1_IDENTITY)


def test_each_projection_proposes_exactly_the_rule_it_returns() -> None:
    cases = (
        (
            project_part4_frequency_scope,
            PART4_SCOPE_FREQUENCY_APPLICABILITY,
            PART4_IDENTITY,
            (LOWER, UPPER),
        ),
        (project_partial_discharge_advice, PARTIAL_DISCHARGE_ADVICE, PART1_IDENTITY, (ADVICE,)),
    )
    for project, semantic_id, identity, quantities in cases:
        rules, proposals = project(_fragment(semantic_id, identity, *quantities), identity)
        assert [rule.id for rule in rules] == [semantic_id]
        assert [proposal.semantic_id for proposal in proposals] == [semantic_id]
        assert [proposal.rule_kind for proposal in proposals] == ["decision"]
