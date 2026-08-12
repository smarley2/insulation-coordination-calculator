"""Typed projection for IEC 62477-1:2022 Tables 2 and 3.

The recipe supplies coordinates and semantic targets; all quantities remain extracted
source data. No curve or Table 7 value is copied into the resulting decisions.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, NamedTuple, cast

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Identifier,
    Matcher,
    SourceReference,
)
from insulation_coordination.rules.importer.axis_selectors import (
    ConfirmedAxes,
    DvcDesignationSelector,
    ProtectionTargetSelector,
    Table2QuantitySelector,
)
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridCell,
    SemanticProposal,
    apply_table_structure,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import (
    TABLE_2,
    TABLE_3,
)

OutcomeKind = Literal["numeric", "reference", "not_applicable"]
_REFERENCE_TARGET_KINDS = {
    ids.DVC_FAULT_TIME_VOLTAGE: "curve",
    ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC: "table",
}


class _Outcome(NamedTuple):
    row: int
    column: int
    kind: OutcomeKind
    value: Decimal | str | bool
    source: SourceReference


def _outcomes(grid: RawGrid) -> tuple[_Outcome, ...]:
    by_coordinate = {(cell.row, cell.column): cell for cell in grid.cells}
    outcomes: list[_Outcome] = []
    assert TABLE_2.data_row_start is not None
    assert TABLE_2.data_column_start is not None
    for row in range(
        TABLE_2.data_row_start,
        TABLE_2.data_row_start + TABLE_2.expected_data_rows,
    ):
        for column in range(
            TABLE_2.data_column_start,
            TABLE_2.data_column_start + TABLE_2.expected_data_columns,
        ):
            cell = by_coordinate[(row, column)]
            if any(
                value is None
                for value in (
                    cell.source.page,
                    cell.source.table,
                    cell.source.row,
                    cell.source.column,
                )
            ):
                raise ValueError("Table 2 outcome has incomplete typed provenance")
            if cell.reference_token is not None:
                expected_kind = _REFERENCE_TARGET_KINDS.get(cell.reference_token.target_rule_id)
                if expected_kind != cell.reference_token.target_kind:
                    raise ValueError("Table 2 semantic reference has an invalid target kind")
                outcomes.append(
                    _Outcome(
                        row,
                        column,
                        "reference",
                        cell.reference_token.target_rule_id,
                        cell.reference_token.source,
                    )
                )
            elif cell.parse_status == "numeric" and cell.value is not None:
                outcomes.append(_Outcome(row, column, "numeric", cell.value, cell.source))
            elif cell.blank_semantics == "not_applicable":
                outcomes.append(_Outcome(row, column, "not_applicable", False, cell.source))
            else:
                raise ValueError(f"Table 2 has an unresolved outcome at {(row, column)}")
    return tuple(outcomes)


def _table_2_inputs(grid: RawGrid, axes: ConfirmedAxes) -> tuple[DecisionInput, ...]:
    """Runtime inputs from the reviewed selectors, never from a physical coordinate."""

    rows = tuple(cast(DvcDesignationSelector, item) for item in axes.rows.values())
    columns = tuple(cast(Table2QuantitySelector, item) for item in axes.columns.values())
    return (
        DecisionInput(
            name="dvc",
            kind="categorical",
            allowed_values=tuple(sorted({item.designation for item in rows})),
        ),
        DecisionInput(
            name="environment",
            kind="categorical",
            allowed_values=tuple(sorted({item.environment for item in rows})),
        ),
        DecisionInput(
            name="operating_context",
            kind="categorical",
            allowed_values=tuple(sorted({item.operating_context for item in columns})),
        ),
        DecisionInput(
            name="quantity",
            kind="categorical",
            allowed_values=tuple(sorted({item.quantity for item in columns})),
        ),
        DecisionInput(
            name="basis",
            kind="categorical",
            allowed_values=tuple(sorted({item.basis for item in columns})),
        ),
        DecisionInput(name="unit", kind="categorical", allowed_values=(grid.target_unit,)),
    )


def _matchers(outcome: _Outcome, unit: str, axes: ConfirmedAxes) -> tuple[Matcher, ...]:
    row = cast(DvcDesignationSelector, axes.row(outcome.row))
    column = cast(Table2QuantitySelector, axes.column(outcome.column))
    return (
        Matcher(input="dvc", op="equals", values=(row.designation,)),
        Matcher(input="environment", op="equals", values=(row.environment,)),
        Matcher(input="operating_context", op="equals", values=(column.operating_context,)),
        Matcher(input="quantity", op="equals", values=(column.quantity,)),
        Matcher(input="basis", op="equals", values=(column.basis,)),
        Matcher(input="unit", op="equals", values=(unit,)),
    )


def _numeric_rule(
    grid: RawGrid, outcomes: tuple[_Outcome, ...], axes: ConfirmedAxes
) -> DecisionRule:
    output = DecisionOutput(name="voltage_limit", kind="numeric", unit=grid.target_unit)
    return DecisionRule(
        id=ids.DVC_VOLTAGE_LIMITS,
        inputs=_table_2_inputs(grid, axes),
        outputs=(output,),
        rows=tuple(
            DecisionRow(
                matchers=_matchers(outcome, grid.target_unit, axes),
                values=(
                    DecisionValue(
                        name=output.name,
                        numeric=cast(Decimal, outcome.value),
                        unit=grid.target_unit,
                    ),
                ),
                source=outcome.source,
            )
            for outcome in outcomes
        ),
        exhaustive=False,
        source=grid.source,
    )


def _curve_reference_rule(
    grid: RawGrid, outcomes: tuple[_Outcome, ...], axes: ConfirmedAxes
) -> DecisionRule:
    return DecisionRule(
        id=f"{ids.DVC_VOLTAGE_LIMITS}.fault_time_reference",
        inputs=_table_2_inputs(grid, axes),
        outputs=(DecisionOutput(name="fault_time_voltage", kind="reference"),),
        rows=tuple(
            DecisionRow(
                matchers=_matchers(outcome, grid.target_unit, axes),
                values=(
                    DecisionValue(
                        name="fault_time_voltage",
                        reference=ids.DVC_FAULT_TIME_VOLTAGE,
                    ),
                ),
                source=outcome.source,
            )
            for outcome in outcomes
        ),
        exhaustive=False,
        source=grid.source,
    )


def _impulse_reference_rule(
    grid: RawGrid, outcomes: tuple[_Outcome, ...], axes: ConfirmedAxes
) -> DecisionRule:
    return DecisionRule(
        id=f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference",
        inputs=_table_2_inputs(grid, axes),
        outputs=(
            DecisionOutput(name="ac_reference", kind="reference"),
            DecisionOutput(name="dc_reference", kind="reference"),
        ),
        rows=tuple(
            DecisionRow(
                matchers=_matchers(outcome, grid.target_unit, axes),
                values=(
                    DecisionValue(
                        name="ac_reference",
                        reference=f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac",
                    ),
                    DecisionValue(
                        name="dc_reference",
                        reference=f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc",
                    ),
                ),
                source=outcome.source,
            )
            for outcome in outcomes
        ),
        exhaustive=False,
        source=grid.source,
    )


def _not_applicable_rule(
    grid: RawGrid, outcomes: tuple[_Outcome, ...], axes: ConfirmedAxes
) -> DecisionRule:
    return DecisionRule(
        id=f"{ids.DVC_VOLTAGE_LIMITS}.not_applicable",
        inputs=_table_2_inputs(grid, axes),
        outputs=(DecisionOutput(name="applicable", kind="boolean"),),
        rows=tuple(
            DecisionRow(
                matchers=_matchers(outcome, grid.target_unit, axes),
                values=(DecisionValue(name="applicable", boolean=False),),
                source=outcome.source,
            )
            for outcome in outcomes
        ),
        exhaustive=False,
        source=grid.source,
    )


def project_dvc_voltage_limits(
    grid: RawGrid,
    identity: StandardIdentity,
    confirmed_axes: ConfirmedAxes,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project a complete reviewed Table 2 grid into proposed typed decisions."""

    if grid.id != f"raw-{ids.DVC_VOLTAGE_LIMITS}":
        raise ValueError("Table 2 projection requires the DVC voltage-limit grid")
    if grid.source.standard != identity.standard or grid.source.edition != identity.edition:
        raise ValueError("Table 2 grid does not match its identified source")
    if (
        len(confirmed_axes.rows) != TABLE_2.expected_data_rows
        or len(confirmed_axes.columns) != TABLE_2.expected_data_columns
    ):
        raise ValueError("Table 2 projection needs every reviewed axis selector")
    structured = apply_table_structure(grid, TABLE_2)
    outcomes = _outcomes(structured)
    numeric = tuple(item for item in outcomes if item.kind == "numeric")
    curve = tuple(item for item in outcomes if item.value == ids.DVC_FAULT_TIME_VOLTAGE)
    impulse = tuple(
        item for item in outcomes if item.value == ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC
    )
    not_applicable = tuple(item for item in outcomes if item.kind == "not_applicable")
    rules = (
        _numeric_rule(structured, numeric, confirmed_axes),
        _curve_reference_rule(structured, curve, confirmed_axes),
        _impulse_reference_rule(structured, impulse, confirmed_axes),
        _not_applicable_rule(structured, not_applicable, confirmed_axes),
    )
    artifact_sha256 = canonical_model_sha256(structured)
    proposals = tuple(
        SemanticProposal(
            semantic_id=rule.id,
            rule_kind="decision",
            state="proposed",
            rule_sha256=canonical_model_sha256(rule),
            source_artifact_sha256=artifact_sha256,
        )
        for rule in rules
    )
    return rules, proposals


class _ProtectionCell(NamedTuple):
    physical_row: int
    physical_column: int
    requirement: Identifier
    source: SourceReference


_PROTECTION_REQUIREMENTS = (
    "none",
    "basic_protection",
    "enhanced_protection",
)


def _protection_cells(grid: RawGrid) -> tuple[_ProtectionCell, ...]:
    cells: list[_ProtectionCell] = []
    for cell in grid.cells:
        if cell.role != "data":
            continue
        if any(
            value is None
            for value in (
                cell.logical_row,
                cell.logical_column,
                cell.source.page,
                cell.source.table,
                cell.source.row,
                cell.source.column,
            )
        ):
            raise ValueError("Table 3 outcome has incomplete typed provenance")
        token = _protection_token(cell)
        if cell.value is not None or token is None:
            raise ValueError(
                f"Table 3 has an unknown categorical token at {(cell.row, cell.column)}"
            )
        cells.append(
            _ProtectionCell(
                cell.row,
                cell.column,
                token,
                cell.source,
            )
        )
    return tuple(cells)


def _protection_token(cell: RawGridCell) -> Identifier | None:
    grammar = TABLE_3.token_grammar
    if grammar is None or grammar.target != "categorical":
        raise ValueError("Table 3 requires a categorical token grammar")
    resolved = grammar.resolve(cell.raw_text)
    return resolved if isinstance(resolved, str) else None


def _protection_rule(
    grid: RawGrid,
    cells: tuple[_ProtectionCell, ...],
    axes: ConfirmedAxes,
) -> DecisionRule:
    rows = tuple(cast(DvcDesignationSelector, item) for item in axes.rows.values())
    columns = tuple(cast(ProtectionTargetSelector, item) for item in axes.columns.values())
    return DecisionRule(
        id=ids.DVC_PROTECTION_MATRIX,
        inputs=(
            DecisionInput(
                name="dvc",
                kind="categorical",
                allowed_values=tuple(sorted({item.designation for item in rows})),
            ),
            DecisionInput(
                name="target",
                kind="categorical",
                allowed_values=tuple(sorted({item.target for item in columns})),
            ),
            DecisionInput(
                name="pe_relationship",
                kind="categorical",
                allowed_values=tuple(sorted({item.pe_relationship for item in columns})),
            ),
            DecisionInput(
                name="access_context",
                kind="categorical",
                allowed_values=tuple(sorted({item.access_context for item in columns})),
            ),
            DecisionInput(
                name="person_scope",
                kind="categorical",
                allowed_values=tuple(sorted({item.person_scope for item in columns})),
            ),
            DecisionInput(
                name="adjacent_dvc",
                kind="categorical",
                allowed_values=tuple(sorted({item.adjacent_dvc for item in columns})),
            ),
        ),
        outputs=(
            DecisionOutput(
                name="protection_requirement",
                kind="categorical",
                allowed_values=_PROTECTION_REQUIREMENTS,
            ),
        ),
        rows=tuple(
            DecisionRow(
                matchers=_protection_matchers(cell, axes),
                values=(
                    DecisionValue(name="protection_requirement", categorical=cell.requirement),
                ),
                source=cell.source,
            )
            for cell in cells
        ),
        # Forced, not chosen: exhaustive requires a row per combination of the six declared
        # vocabularies, and that cartesian product dwarfs the reviewed combinations. Coverage
        # of every reviewed combination is asserted by test instead.
        exhaustive=False,
        source=grid.source,
    )


def _protection_matchers(cell: _ProtectionCell, axes: ConfirmedAxes) -> tuple[Matcher, ...]:
    row = cast(DvcDesignationSelector, axes.row(cell.physical_row))
    column = cast(ProtectionTargetSelector, axes.column(cell.physical_column))
    return (
        Matcher(input="dvc", op="equals", values=(row.designation,)),
        Matcher(input="target", op="equals", values=(column.target,)),
        Matcher(input="pe_relationship", op="equals", values=(column.pe_relationship,)),
        Matcher(input="access_context", op="equals", values=(column.access_context,)),
        Matcher(input="person_scope", op="equals", values=(column.person_scope,)),
        Matcher(input="adjacent_dvc", op="equals", values=(column.adjacent_dvc,)),
    )


def project_dvc_protection_matrix(
    grid: RawGrid,
    identity: StandardIdentity,
    confirmed_axes: ConfirmedAxes,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project a complete reviewed Table 3 grid into proposed typed decisions."""

    if grid.id != f"raw-{ids.DVC_PROTECTION_MATRIX}":
        raise ValueError("Table 3 projection requires the DVC protection matrix grid")
    if grid.source.standard != identity.standard or grid.source.edition != identity.edition:
        raise ValueError("Table 3 grid does not match its identified source")
    if (
        len(confirmed_axes.rows) != TABLE_3.expected_data_rows
        or len(confirmed_axes.columns) != TABLE_3.expected_data_columns
    ):
        raise ValueError("Table 3 projection needs every reviewed axis selector")
    structured = apply_table_structure(grid, TABLE_3)
    expected = {
        (row, column.semantic_id)
        for row in range(TABLE_3.expected_data_rows)
        for column in TABLE_3.columns
        if column.role == "data"
    }
    present = {
        (cell.logical_row, cell.logical_column) for cell in structured.cells if cell.role == "data"
    }
    if present != expected:
        raise ValueError("Table 3 has incomplete Cartesian coverage")
    cells = _protection_cells(structured)
    rules = (_protection_rule(structured, cells, confirmed_axes),)
    artifact_sha256 = canonical_model_sha256(structured)
    proposals = tuple(
        SemanticProposal(
            semantic_id=rule.id,
            rule_kind="decision",
            state="proposed",
            rule_sha256=canonical_model_sha256(rule),
            source_artifact_sha256=artifact_sha256,
        )
        for rule in rules
    )
    return rules, proposals


__all__ = [
    "project_dvc_protection_matrix",
    "project_dvc_voltage_limits",
]
