from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import ApprovalRecord, DecisionRule, SourceReference
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    approval_blockers,
    record_correction,
)
from insulation_coordination.rules.importer.axis_selectors import ConfirmedAxes
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ImportedRuleDraft,
    ImportReviewItem,
    ImportReviewResolution,
    RawGrid,
    RawGridCell,
    RawGridSegment,
    _content_digest,
    apply_table_structure,
    propose_axis_selectors,
)
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    projection as table2_projection,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.projection import (
    project_dvc_voltage_limits,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLE_2
from insulation_coordination.rules.importer.review import (
    build_reviewed_draft,
    mark_proposal_reviewed,
    resolve_confirmed_axis_selectors,
    review_axis_selector,
)
from tests.fixtures.synthetic_rules import synthetic_rule_package

SOURCE = SourceReference(
    document_id="synthetic-table-2",
    standard="SYNTHETIC",
    edition="1",
    page=44,
    table="S2",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="2" * 64,
    page_count=44,
    recipe_id="synthetic-table-2",
)
REFERENCE_COORDINATES = {(3, 5), (5, 4)}
STRUCTURAL_BLANKS = {(7, column) for column in range(1, 6)}
INHERITED_BLANKS = {
    (1, 0),
    (2, 0),
    (0, 2),
    (0, 3),
    (0, 4),
    (0, 5),
    (1, 2),
    (1, 3),
    (1, 4),
    (4, 4),
    (4, 5),
    (5, 5),
    (6, 4),
}
#: Header text at physical row's column 0, carrying the axis grammar's keywords, and at
#: physical column 0 of row 2 for the column headers. Both pairings are deranged against the
#: licensed table -- no physical position carries the keyword the source assigns it -- and
#: neither axis is the source's order displaced by a fixed step, so one recovered pairing
#: yields nothing about the others. Every expectation below reads these maps, never the
#: source: which physical position means what is the licensed part, and is not stated here.
_ROW_HEADER_TEXT = {3: "c", 4: "b", 5: "as wet", 6: "as dry"}
_COLUMN_HEADER_TEXT = {1: "peak", 2: "mean", 3: "fault", 4: "rms", 5: "impulse"}
_REORDER_ROWS = (3, 4)


def _cell(row: int, column: int, *, reorder_rows: bool = False) -> RawGridCell:
    source = SOURCE.model_copy(
        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
    )
    data = row in range(3, 7) and column in range(1, 6)
    not_applicable = (row, column) == (6, 5)
    blank = (
        (row, column) in INHERITED_BLANKS or (row, column) in STRUCTURAL_BLANKS or not_applicable
    )
    reference = (row, column) in REFERENCE_COORDINATES
    swapped_row = _REORDER_ROWS[1] if row == _REORDER_ROWS[0] else _REORDER_ROWS[0]
    value_row = (
        swapped_row if reorder_rows and row in _REORDER_ROWS and column in (1, 2, 3) else row
    )
    value = Decimal(value_row * 100 + column * 7) if data and not blank else None
    if reference:
        value = None
    if column == 0 and row in _ROW_HEADER_TEXT:
        header_row = swapped_row if reorder_rows and row in _REORDER_ROWS else row
        header_text = _ROW_HEADER_TEXT[header_row]
    elif row == 2 and column in _COLUMN_HEADER_TEXT:
        header_text = _COLUMN_HEADER_TEXT[column]
    else:
        header_text = "HEADER"
    text = "NA" if not_applicable else ("" if blank else ("REF" if reference else header_text))
    return RawGridCell(
        row=row,
        column=column,
        raw_text=text if value is None else str(value),
        role="data" if data else ("blank" if blank else "header"),
        logical_row=row - 3 if data else None,
        logical_column=f"column-{column}" if data else None,
        value=value,
        parse_status=(
            "non_scalar"
            if not_applicable
            else ("blank" if blank else ("numeric" if value is not None else "text"))
        ),
        source=source,
    )


def _grid(*, reorder_rows: bool = False) -> RawGrid:
    return RawGrid(
        id=f"raw-{ids.DVC_VOLTAGE_LIMITS}",
        rows=8,
        columns=6,
        target_unit="V",
        segments=(RawGridSegment(page_number=44, row_start=0, row_count=8, source=SOURCE),),
        cells=tuple(
            _cell(row, column, reorder_rows=reorder_rows) for row in range(8) for column in range(6)
        ),
        source=SOURCE,
    )


def _confirmed_axes(grid: RawGrid) -> ConfirmedAxes:
    """Propose, review and resolve every Table 2 axis position for a synthetic grid.

    Mirrors the review lifecycle a real import goes through: propose from header text,
    record one exact review per position, then resolve. The projector under test never
    inspects review state itself -- it only ever consumes the ``ConfirmedAxes`` this builds.
    """

    proposals = propose_axis_selectors(TABLE_2, grid)
    package = synthetic_rule_package()
    draft = ImportedRuleDraft(
        manifest=package.manifest.model_copy(
            update={
                "approved": False,
                "compatible": False,
                "source_documents": (),
                "approval_records": (),
            }
        ),
        tables=(),
        formulas=(),
        mappings=(),
        raw_grids=(grid,),
        source_identities=(IDENTITY,),
        axis_selector_proposals=proposals,
    )
    digest = _content_digest(
        draft.tables,
        draft.formulas,
        draft.mappings,
        raw_grids=draft.raw_grids,
        source_documents=draft.manifest.source_documents,
        source_identities=draft.source_identities,
        axis_selector_proposals=draft.axis_selector_proposals,
    )
    record = ApprovalRecord(
        action="extraction",
        actor=f"icc-importer/{IMPORTER_VERSION}",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes=f"content:{digest}",
    )
    draft = draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": (record,)})}
    )
    for proposal in proposals:
        assert proposal.selector is not None, "every synthetic axis position proposes a reading"
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=proposal.selector,
            actor="Synthetic Axis Reviewer",
            notes="Confirmed the synthetic axis reading.",
        )
    return resolve_confirmed_axis_selectors(TABLE_2, grid, draft)


def _project(*, reorder_rows: bool = False) -> tuple[tuple[DecisionRule, ...], ConfirmedAxes]:
    """Build a synthetic grid, review its axes, and project Table 2's decisions."""

    grid = _grid(reorder_rows=reorder_rows)
    axes = _confirmed_axes(grid)
    rules, _ = project_dvc_voltage_limits(grid, IDENTITY, axes)
    return rules, axes


def test_projection_rows_carry_full_provenance_and_no_synthetic_inputs() -> None:
    rules, _ = _project()
    numeric = next(rule for rule in rules if rule.id == ids.DVC_VOLTAGE_LIMITS)
    assert not any(
        matcher.input in {"operating_condition", "conditional_alternative"}
        for row in numeric.rows
        for matcher in row.matchers
    )
    assert all(
        row.source.page is not None
        and row.source.table is not None
        and row.source.row is not None
        and row.source.column is not None
        for rule in rules
        for row in rule.rows
    )
    for rule in rules:
        matcher_sets = {
            tuple(sorted((matcher.input, tuple(matcher.values)) for matcher in row.matchers))
            for row in rule.rows
        }
        assert len(matcher_sets) == len(rule.rows), (
            f"{rule.id} has two rows sharing one matcher combination"
        )


def test_curve_reference_rule_targets_only_the_fault_time_curve() -> None:
    rules, _ = _project()
    rule = next(
        item for item in rules if item.id == f"{ids.DVC_VOLTAGE_LIMITS}.fault_time_reference"
    )
    assert [output.name for output in rule.outputs] == ["fault_time_voltage"]
    assert {value.reference for row in rule.rows for value in row.values} == {
        ids.DVC_FAULT_TIME_VOLTAGE
    }
    assert all(value.numeric is None for row in rule.rows for value in row.values)


def test_impulse_reference_rule_targets_exact_ac_and_dc_tables() -> None:
    rules, _ = _project()
    rule = next(item for item in rules if item.id == f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference")
    assert {output.name for output in rule.outputs} == {"ac_reference", "dc_reference"}
    assert all(
        {value.reference for value in row.values}
        == {
            f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac",
            f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc",
        }
        for row in rule.rows
    )


def test_numeric_rule_evaluates_a_physical_row_and_quantity_column() -> None:
    """The expected value follows from this fixture's own header maps, not from the source.

    ``_cell`` derives every value from its physical coordinates, so the answer is the one
    ``_ROW_HEADER_TEXT`` and ``_COLUMN_HEADER_TEXT`` place this selector pair at.
    """
    rules, _ = _project()
    numeric = next(rule for rule in rules if rule.id == ids.DVC_VOLTAGE_LIMITS)
    result = evaluate_decision(
        numeric,
        {
            "dvc": "dvc_as",
            "environment": "dry",
            "operating_context": "normal",
            "quantity": "working_voltage",
            "basis": "dc_mean",
            "unit": "V",
        },
    )
    assert result.values[0].numeric == Decimal(614)


def test_unresolved_neutral_token_blocks_projection() -> None:
    grid = _grid()
    axes = _confirmed_axes(grid)
    cells = tuple(
        cell.model_copy(update={"raw_text": "UNKNOWN", "value": None, "parse_status": "text"})
        if (cell.row, cell.column) == (3, 1)
        else cell
        for cell in grid.cells
    )

    with pytest.raises(ValueError, match="unresolved outcome"):
        project_dvc_voltage_limits(grid.model_copy(update={"cells": cells}), IDENTITY, axes)


def _logged_table2_extraction(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    grid = apply_table_structure(_grid(), TABLE_2)
    axis_proposals = propose_axis_selectors(TABLE_2, grid)
    review_item = ImportReviewItem(
        code="SYNTHETIC_TABLE_2_REVIEW",
        semantic_id=ids.DVC_VOLTAGE_LIMITS,
        kind="table",
        source=SOURCE,
        expected_contract="synthetic structural Table 2 review",
    )
    resolution = ImportReviewResolution(
        review_item_sha256=review_item.sha256,
        actor="Synthetic Source Reviewer",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes="Reviewed the synthetic Table 2 source artifact.",
    )
    recipe = IEC_RECIPE.model_copy(
        update={
            "id": IDENTITY.recipe_id,
            "standard": IDENTITY.standard,
            "edition": IDENTITY.edition,
            "tables": (TABLE_2,),
            "formulas": (),
            "mappings": (),
        }
    )
    monkeypatch.setattr(recipe_registry, "RECIPES", (recipe,))
    package = synthetic_rule_package()
    draft = ImportedRuleDraft(
        manifest=package.manifest.model_copy(
            update={
                "approved": False,
                "compatible": False,
                "source_documents": (),
                "approval_records": (),
            }
        ),
        tables=(),
        formulas=(),
        mappings=(),
        review_items=(review_item,),
        review_resolutions=(resolution,),
        raw_grids=(grid,),
        source_identities=(IDENTITY,),
        axis_selector_proposals=axis_proposals,
    )
    digest = _content_digest(
        draft.tables,
        draft.formulas,
        draft.mappings,
        draft.review_items,
        draft.raw_grids,
        draft.raw_clause_fragments,
        draft.manifest.source_documents,
        draft.source_identities,
        draft.review_resolutions,
        axis_selector_proposals=draft.axis_selector_proposals,
    )
    extraction = ApprovalRecord(
        action="extraction",
        actor=f"icc-importer/{IMPORTER_VERSION}",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes=f"content:{digest}",
    )
    draft = draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": (extraction,)})}
    )
    for proposal in axis_proposals:
        assert proposal.selector is not None, "every synthetic axis position proposes a reading"
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=proposal.selector,
            actor="Synthetic Axis Reviewer",
            notes="Confirmed the synthetic axis reading.",
        )
    return draft


def test_build_and_review_lifecycle_resets_after_authoritative_grid_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = build_reviewed_draft(
        _logged_table2_extraction(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build Table 2 decisions.",
    )
    assert built.semantic_proposals
    assert all(proposal.state == "proposed" for proposal in built.semantic_proposals)

    reviewed = built
    for proposal in built.semantic_proposals:
        reviewed = mark_proposal_reviewed(
            reviewed,
            proposal.semantic_id,
            actor="Synthetic Semantic Reviewer",
            notes="Reviewed the generated decision.",
        )
    assert all(proposal.state == "reviewed" for proposal in reviewed.semantic_proposals)

    grid = reviewed.raw_grids[0]
    cells = tuple(
        cell.model_copy(update={"value": cell.value + Decimal(1)})
        if (cell.row, cell.column) == (3, 1) and cell.value is not None
        else cell
        for cell in grid.cells
    )
    corrected = record_correction(
        reviewed,
        reviewed.model_copy(update={"raw_grids": (grid.model_copy(update={"cells": cells}),)}),
        actor="Synthetic Source Reviewer",
        notes="Correct one reviewed synthetic source quantity.",
    )

    assert all(proposal.state == "proposed" for proposal in corrected.semantic_proposals)
    assert {blocker.code for blocker in approval_blockers(corrected)} >= {
        "SEMANTIC_PROPOSAL_PROPOSED"
    }


def _project_with_proposals() -> tuple:
    """Project Table 2 and return both rules and proposals."""
    grid = _grid()
    axes = _confirmed_axes(grid)
    rules, proposals = project_dvc_voltage_limits(grid, IDENTITY, axes)
    return rules, proposals


def test_every_projected_rule_arrives_as_a_proposal_awaiting_review() -> None:
    """A projected rule must not reach an approved package without a review of its own.

    Each of this table's routes therefore yields a semantic proposal in the proposed state.
    """
    rules, proposals = _project_with_proposals()

    assert {proposal.semantic_id for proposal in proposals} == {rule.id for rule in rules}
    assert all(proposal.state == "proposed" for proposal in proposals)


def test_unrelated_prefixed_decision_cannot_borrow_table2_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = build_reviewed_draft(
        _logged_table2_extraction(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build Table 2 decisions.",
    )
    unrelated = built.decisions[0].model_copy(update={"id": f"{ids.DVC_VOLTAGE_LIMITS}.unrelated"})

    with pytest.raises(ApprovalError, match="review item inventory"):
        record_correction(
            built,
            built.model_copy(update={"decisions": (*built.decisions, unrelated)}),
            actor="Synthetic Rule Builder",
            notes="Attempt an unrelated prefixed decision.",
        )


def test_reference_target_kind_mismatch_blocks_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = TABLE_2.reference_slots[0].model_copy(update={"target_kind": "table"})
    broken = TABLE_2.model_copy(update={"reference_slots": (first, *TABLE_2.reference_slots[1:])})
    monkeypatch.setattr(table2_projection, "TABLE_2", broken)
    grid = _grid()
    axes = _confirmed_axes(grid)

    with pytest.raises(ValueError, match="target kind"):
        project_dvc_voltage_limits(grid, IDENTITY, axes)


EXPECTED_ROW_SELECTORS = {
    ("dvc_as", "dry"),
    ("dvc_as", "wet_and_saltwater_wet"),
    ("dvc_b", "not_applicable"),
    ("dvc_c", "not_applicable"),
}
EXPECTED_COLUMN_SELECTORS = {
    ("normal", "working_voltage", "ac_rms"),
    ("normal", "working_voltage", "ac_peak"),
    ("normal", "working_voltage", "dc_mean"),
    ("normal", "impulse_withstand", "not_applicable"),
    ("single_fault_or_abnormal", "fault_voltage", "ac_peak_or_dc"),
}


def test_no_positional_identifier_reaches_the_runtime_contract() -> None:
    rules, _ = _project()

    for rule in rules:
        for declared in rule.inputs:
            for value in declared.allowed_values:
                assert not re.fullmatch(r"dvc-\d+|voltage-quantity-\d+", value)
        for row in rule.rows:
            for matcher in row.matchers:
                for value in matcher.values:
                    assert not re.fullmatch(r"dvc-\d+|voltage-quantity-\d+", str(value))


def test_the_declared_inputs_are_the_semantic_dimensions() -> None:
    rules, _ = _project()

    for rule in rules:
        assert {item.name for item in rule.inputs} == {
            "dvc",
            "environment",
            "operating_context",
            "quantity",
            "basis",
            "unit",
        }


def test_the_confirmed_selector_inventories_match_the_expected_sets() -> None:
    """Stated here independently of the recipe, as unordered sets, so the two can disagree.

    Which physical position produced which selector is provenance and deliberately not asserted:
    the contract is the set of selectors, not their order.
    """
    _rules, axes = _project()

    rows = {(item.designation, item.environment) for item in axes.rows.values()}
    columns = {
        (item.operating_context, item.quantity, item.basis) for item in axes.columns.values()
    }

    assert rows == EXPECTED_ROW_SELECTORS
    assert columns == EXPECTED_COLUMN_SELECTORS


def test_allowed_values_come_from_the_confirmed_selectors() -> None:
    rules, _ = _project()
    rule = rules[0]
    allowed = {item.name: set(item.allowed_values) for item in rule.inputs}

    assert allowed["dvc"] == {"dvc_as", "dvc_b", "dvc_c"}
    assert allowed["environment"] == {"dry", "wet_and_saltwater_wet", "not_applicable"}
    assert allowed["quantity"] == {"working_voltage", "impulse_withstand", "fault_voltage"}
    assert allowed["operating_context"] == {"normal", "single_fault_or_abnormal"}
    assert allowed["basis"] == {
        "ac_rms",
        "ac_peak",
        "dc_mean",
        "ac_peak_or_dc",
        "not_applicable",
    }


def test_a_reordered_grid_projects_the_same_semantics() -> None:
    """Coordinates are provenance. Reordering physical rows must not change any matcher."""

    straight, _ = _project()
    reordered, _ = _project(reorder_rows=True)

    def semantics(rules):
        return {
            (
                rule.id,
                tuple(sorted((m.input, tuple(map(str, m.values))) for m in row.matchers)),
                tuple(
                    str(value.numeric or value.reference or value.boolean) for value in row.values
                ),
            )
            for rule in rules
            for row in rule.rows
        }

    assert semantics(reordered) == semantics(straight)


def test_the_impulse_column_evaluates_with_its_not_applicable_sentinel() -> None:
    """The queried selectors are the ones this fixture's header maps put on the sentinel cell.

    The spec declares that cell's coordinates; which selector pair meets there is the
    fixture's own invented pairing, and deliberately not the source's.
    """
    rules, _ = _project()
    rule = next(item for item in rules if item.id.endswith(".not_applicable"))

    result = evaluate_decision(
        rule,
        {
            "dvc": "dvc_as",
            "environment": "dry",
            "operating_context": "normal",
            "quantity": "impulse_withstand",
            "basis": "not_applicable",
            "unit": "V",
        },
    )

    assert result.status == "matched"
    assert result.values[0].boolean is False


def test_omitting_a_dimension_is_input_required_not_a_guess() -> None:
    rules, _ = _project()

    result = evaluate_decision(rules[0], {"dvc": "dvc_b"})

    assert result.status == "input_required"
    assert "basis" in result.missing_inputs
