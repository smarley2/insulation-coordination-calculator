"""The Annex F band grid: a typed band read from its cells, and the rule it projects.

Every band and every factor here is invented. The licensed bounds and factors are read from
the document at import time and confirmed by a reviewer; nothing in this file states one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import (
    DecisionRule,
    RulePackageError,
    SourceReference,
)
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.axis_selectors import (
    ConfirmedAxes,
    FrequencyBandSelector,
)
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    RawGrid,
    RawGridCell,
    RawGridSegment,
    parse_data_cell,
    parse_frequency_band,
    propose_axis_selectors,
)
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.annex_f import (
    GRID_PROJECTORS,
    TABLE_F2,
    project_high_frequency_band_factor,
)
from insulation_coordination.rules.importer.review import (
    resolve_confirmed_axis_selectors,
    review_axis_selector,
)
from tests.conftest import _logged
from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft

SOURCE = SourceReference(
    document_id="synthetic-band-grid",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    table="SF2",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="4" * 64,
    page_count=44,
    recipe_id="synthetic-band-grid",
)
#: Invented bands and factors, in a kilo-prefixed unit. The axis header states the prefix, so
#: extraction scales the bounds to hertz without anything here declaring the scale.
_AXIS_HEADER = "synthetic band axis\nkHz"
_KILO = Decimal(1_000)
_BAND_LOWER, _BAND_UPPER = "7", "40"


def _band_text(lower_sign: str, upper_sign: str) -> str:
    return f"{_BAND_LOWER} {lower_sign} f {upper_sign} {_BAND_UPPER}"


_BANDS = (
    (_band_text("<", "≤"), "1"),
    ("40 < f ≤ 90", "2"),
    ("90 < f ≤ 400", "3"),
    ("400 < f ≤ 900", "4"),
)
_FIRST_BAND_HZ = (Decimal(_BAND_LOWER) * _KILO, Decimal(_BAND_UPPER) * _KILO)


def _cell(row: int, column: int, text: str, *, role: str) -> RawGridCell:
    """One synthetic cell, typed by the same parser extraction runs over the real page."""

    parsed = parse_data_cell(text) if role == "data" else None
    return RawGridCell(
        row=row,
        column=column,
        raw_text=text,
        role=role,  # type: ignore[arg-type]
        logical_row=row - 1 if role == "data" else None,
        logical_column=TABLE_F2.columns[column].semantic_id if role == "data" else None,
        value=None if parsed is None else parsed.value,
        parse_status="text" if parsed is None else parsed.parse_status,
        source=SOURCE.model_copy(
            update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
        ),
    )


def _band_grid(
    bands: tuple[tuple[str, str], ...] = _BANDS, *, header: str = _AXIS_HEADER
) -> RawGrid:
    cells = [
        _cell(0, 0, header, role="header"),
        _cell(0, 1, "synthetic factor heading", role="header"),
    ]
    for offset, (band, factor) in enumerate(bands):
        cells.append(_cell(offset + 1, 0, band, role="data"))
        cells.append(_cell(offset + 1, 1, factor, role="data"))
    return RawGrid(
        id=f"raw-{TABLE_F2.semantic_id}",
        rows=TABLE_F2.expected_raw_rows,
        columns=TABLE_F2.expected_raw_columns,
        target_unit=TABLE_F2.target_unit,
        segments=(
            RawGridSegment(
                page_number=TABLE_F2.page_number,
                row_start=0,
                row_count=TABLE_F2.expected_raw_rows,
                source=SOURCE,
            ),
        ),
        cells=tuple(cells),
        source=SOURCE,
    )


def _confirmed(grid: RawGrid) -> ConfirmedAxes:
    """What resolution hands a projector once every position has been confirmed as read."""

    return ConfirmedAxes(
        rows={
            proposal.index: proposal.selector
            for proposal in propose_axis_selectors(TABLE_F2, grid)
            if proposal.selector is not None
        }
    )


def _projected(grid: RawGrid, axes: ConfirmedAxes | None = None) -> DecisionRule:
    rules, _proposals = project_high_frequency_band_factor(
        grid, IDENTITY, _confirmed(grid) if axes is None else axes
    )
    return rules[0]


def _factor(rule: DecisionRule, frequency_hz: Decimal) -> Decimal | str | None:
    """The factor a frequency resolves to, or the status where it resolves to none."""

    result = evaluate_decision(rule, {"working_voltage_frequency_hz": frequency_hz})
    if result.status != "matched":
        return result.status
    return next(value.numeric for value in result.values if value.name == "band_factor")


# -- The band grammar ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("signs", "inclusive"),
    [
        (("<", "≤"), "upper"),
        (("≤", "<"), "lower"),
        (("≤", "≤"), "both"),
        (("<", "<"), "neither"),
    ],
)
def test_each_pair_of_comparisons_names_the_end_the_source_closes(
    signs: tuple[str, str], inclusive: str
) -> None:
    lower_sign, upper_sign = signs

    band = parse_frequency_band(_band_text(lower_sign, upper_sign), _AXIS_HEADER, "Hz")

    assert band is not None
    assert (band.inclusive_bound, band.lower_hz, band.upper_hz) == (inclusive, *_FIRST_BAND_HZ)


def test_a_band_stated_the_other_way_round_reads_as_the_same_band() -> None:
    """The reading follows the comparisons, not the order the two quantities are printed in."""

    ascending = parse_frequency_band(_band_text("≤", "<"), _AXIS_HEADER, "Hz")
    descending = parse_frequency_band(f"{_BAND_UPPER} > f ≥ {_BAND_LOWER}", _AXIS_HEADER, "Hz")

    assert ascending is not None
    assert descending == ascending


def test_a_quantity_the_layout_broke_onto_its_own_line_still_reads() -> None:
    band = parse_frequency_band(f"{_band_text('<', '≤')}\nsubscript", _AXIS_HEADER, "Hz")

    assert band is not None
    assert (band.lower_hz, band.upper_hz) == _FIRST_BAND_HZ


def test_a_thousands_separator_and_a_decimal_comma_are_the_documents_own() -> None:
    band = parse_frequency_band(f"{_BAND_LOWER} < f ≤ 1 500,5", _AXIS_HEADER, "Hz")

    assert band is not None
    assert band.upper_hz == Decimal("1500.5") * _KILO


@pytest.mark.parametrize(
    "cell",
    [
        "f ≤ 40",
        "7 < f",
        "7 < f ≤ 40 ≤ 90",
        # Comparisons pointing opposite ways state no interval this parser can order.
        "7 < f ≥ 40",
        # A band whose bounds do not increase is a misread, not a band.
        "40 < f ≤ 7",
        "40 < f ≤ 40",
        "synthetic prose with no bound",
    ],
)
def test_anything_but_one_two_bounded_band_reads_as_nothing(cell: str) -> None:
    assert parse_frequency_band(cell, _AXIS_HEADER, "Hz") is None


def test_a_header_stating_no_scaled_unit_reads_no_band() -> None:
    """The scale belongs to the document. Without it the bounds have no meaning to convert."""

    assert parse_frequency_band(_band_text("<", "≤"), "synthetic axis with no unit", "Hz") is None


def test_the_scale_comes_from_the_header_rather_than_from_the_recipe() -> None:
    scaled = {
        prefix: parse_frequency_band(_band_text("<", "≤"), f"synthetic axis {prefix}Hz", "Hz")
        for prefix in ("", "k", "M")
    }

    assert all(band is not None for band in scaled.values())
    bare, kilo, mega = (band.lower_hz for band in scaled.values() if band is not None)
    assert (kilo, mega) == (bare * _KILO, bare * _KILO * _KILO)


# -- The reviewed proposal ----------------------------------------------------------------


def test_the_band_axis_declares_no_grammar_and_no_reviewer_supplied_reading() -> None:
    (axis_spec,) = TABLE_F2.axis_selectors

    assert (axis_spec.axis, axis_spec.selector_kind) == ("row", "frequency_band")
    assert axis_spec.keyword_rules == ()
    assert axis_spec.reviewer_supplied is False
    assert axis_spec.expected_positions == TABLE_F2.expected_data_rows


def test_every_band_position_proposes_the_band_its_own_cell_states() -> None:
    proposals = propose_axis_selectors(TABLE_F2, _band_grid())

    assert len(proposals) == TABLE_F2.expected_data_rows
    assert {proposal.selector_kind for proposal in proposals} == {"frequency_band"}
    first = proposals[0].selector
    assert isinstance(first, FrequencyBandSelector)
    assert (first.lower_hz, first.upper_hz) == _FIRST_BAND_HZ


def test_a_position_whose_cell_states_no_band_proposes_nothing() -> None:
    """Unread rather than guessed: the reviewer sees an empty position instead of a band."""

    unreadable = (("synthetic prose", "1"), *_BANDS[1:])
    proposals = propose_axis_selectors(TABLE_F2, _band_grid(unreadable))

    assert proposals[0].selector is None
    assert all(proposal.selector is not None for proposal in proposals[1:])


def test_each_position_binds_to_its_own_band_cell_rather_than_to_the_whole_grid() -> None:
    """Without per-position evidence a re-extracted band would leave its review current."""

    digests = {
        proposal.evidence_sha256 for proposal in propose_axis_selectors(TABLE_F2, _band_grid())
    }

    assert len(digests) == TABLE_F2.expected_data_rows


def test_a_changed_band_cell_disturbs_only_its_own_positions_evidence() -> None:
    original = {
        proposal.index: proposal.evidence_sha256
        for proposal in propose_axis_selectors(TABLE_F2, _band_grid())
    }
    moved = (_BANDS[0], ("40 < f ≤ 95", "2"), *_BANDS[2:])
    changed = {
        proposal.index: proposal.evidence_sha256
        for proposal in propose_axis_selectors(TABLE_F2, _band_grid(moved))
    }

    assert changed[2] != original[2]
    assert {index: changed[index] for index in changed if index != 2} == {
        index: original[index] for index in original if index != 2
    }


def test_the_reviewed_band_is_what_resolution_hands_the_projection() -> None:
    """The whole flow: extraction proposes, the reviewer confirms, resolution returns it."""

    grid = _band_grid()
    draft: ImportedRuleDraft = _logged(
        _draft(grid).model_copy(
            update={"axis_selector_proposals": propose_axis_selectors(TABLE_F2, grid)}
        )
    )
    for proposal in draft.axis_selector_proposals:
        assert proposal.selector is not None
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=proposal.selector,
            actor="tester",
            notes="confirmed",
        )

    axes = resolve_confirmed_axis_selectors(TABLE_F2, grid, draft)

    assert len(axes.rows) == TABLE_F2.expected_data_rows
    assert all(isinstance(band, FrequencyBandSelector) for band in axes.rows.values())


# -- The projected rule -------------------------------------------------------------------


def test_the_recipe_registers_the_band_grid_projector() -> None:
    assert set(GRID_PROJECTORS) == {ids.HIGH_FREQUENCY_BAND_FACTOR}
    assert TABLE_F2.decision_route_ids == (ids.HIGH_FREQUENCY_BAND_FACTOR,)
    assert TABLE_F2.comparison_only is False


def test_a_frequency_inside_a_band_resolves_that_bands_factor() -> None:
    rule = _projected(_band_grid())

    assert rule.id == ids.HIGH_FREQUENCY_BAND_FACTOR
    assert _factor(rule, Decimal(20_000)) == Decimal(1)
    assert _factor(rule, Decimal(60_000)) == Decimal(2)


def test_a_frequency_outside_every_declared_band_answers_no_match() -> None:
    """The source settles nothing there, so neither does the rule. Never a nearest factor."""

    rule = _projected(_band_grid())

    assert rule.exhaustive is False
    assert _factor(rule, Decimal(1)) == "no_match"
    assert _factor(rule, Decimal(9_000_000)) == "no_match"


def test_a_frequency_on_a_boundary_lands_in_the_band_the_source_closes() -> None:
    """The whole point of typing inclusivity: the open end must not answer."""

    rule = _projected(_band_grid())

    # The first band's own lower bound is open, and no band below it declares that frequency.
    assert _factor(rule, _FIRST_BAND_HZ[0]) == "no_match"
    assert _factor(rule, _FIRST_BAND_HZ[1]) == Decimal(1)


def test_the_matchers_carry_the_reviewed_bounds_rather_than_a_declared_one() -> None:
    widened = (("7 < f ≤ 25", "1"), ("25 < f ≤ 90", "2"), *_BANDS[2:])

    bounds = {
        band: sorted(
            {
                value
                for row in _projected(_band_grid(band)).rows
                for matcher in row.matchers
                for value in (matcher.minimum, matcher.maximum)
                if value is not None
            }
        )
        for band in (_BANDS, widened)
    }

    assert bounds[_BANDS] != bounds[widened]
    assert Decimal(25_000) in bounds[widened]
    assert Decimal(25_000) not in bounds[_BANDS]


def test_two_overlapping_reviewed_bands_are_refused_rather_than_served_by_row_order() -> None:
    overlapping = (("7 < f ≤ 90", "1"), ("40 < f ≤ 95", "2"), *_BANDS[2:])

    with pytest.raises(RulePackageError, match="overlapping"):
        _projected(_band_grid(overlapping))


def test_two_bands_meeting_at_one_closed_bound_are_refused() -> None:
    """One frequency in two bands is an overlap however narrow it is."""

    touching = (("7 ≤ f ≤ 40", "1"), ("40 ≤ f ≤ 90", "2"), *_BANDS[2:])

    with pytest.raises(RulePackageError, match="overlapping"):
        _projected(_band_grid(touching))


def test_a_band_without_a_numeric_factor_beside_it_is_refused() -> None:
    unreadable = ((_BANDS[0][0], "synthetic prose"), *_BANDS[1:])

    with pytest.raises(RulePackageError, match="factor"):
        _projected(_band_grid(unreadable))


def test_an_incomplete_review_cannot_be_projected() -> None:
    grid = _band_grid()
    partial = ConfirmedAxes(rows=dict(list(_confirmed(grid).rows.items())[:2]))

    with pytest.raises(ValueError, match="every reviewed band"):
        project_high_frequency_band_factor(grid, IDENTITY, partial)


def test_a_foreign_grid_cannot_be_projected() -> None:
    foreign = _band_grid().model_copy(update={"id": "raw-other-grid"})

    with pytest.raises(ValueError, match="band grid"):
        project_high_frequency_band_factor(foreign, IDENTITY, ConfirmedAxes())
