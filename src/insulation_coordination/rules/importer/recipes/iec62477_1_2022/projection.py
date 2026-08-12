"""Typed projection for IEC 62477-1:2022 Tables 2 and 3.

The recipe supplies coordinates and semantic targets; all quantities remain extracted
source data. No curve or Table 7 value is copied into the resulting decisions.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, NamedTuple, cast

from insulation_coordination.domain.project import FrozenModel
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


def _dvc(row: int) -> str:
    assert TABLE_2.data_row_start is not None
    return f"dvc-{row - TABLE_2.data_row_start + 1}"


def _quantity(column: int) -> str:
    assert TABLE_2.data_column_start is not None
    return f"voltage-quantity-{column - TABLE_2.data_column_start + 1}"


def _table_2_inputs(grid: RawGrid) -> tuple[DecisionInput, ...]:
    return (
        DecisionInput(
            name="dvc",
            kind="categorical",
            # Positional row and column ids, not designations: Table 2 carries four data
            # rows over the document's three DVC designations because DVC As is split
            # into a wet and a dry row. The counts come from the audited spec so the
            # contract cannot drift from the grid the reviewer approved.
            allowed_values=tuple(
                f"dvc-{index}" for index in range(1, TABLE_2.expected_data_rows + 1)
            ),
        ),
        DecisionInput(
            name="voltage_quantity",
            kind="categorical",
            allowed_values=tuple(
                f"voltage-quantity-{index}" for index in range(1, TABLE_2.expected_data_columns + 1)
            ),
        ),
        DecisionInput(name="unit", kind="categorical", allowed_values=(grid.target_unit,)),
    )


def _matchers(outcome: _Outcome, unit: str) -> tuple[Matcher, ...]:
    return (
        Matcher(input="dvc", op="equals", values=(_dvc(outcome.row),)),
        Matcher(input="voltage_quantity", op="equals", values=(_quantity(outcome.column),)),
        Matcher(input="unit", op="equals", values=(unit,)),
    )


def _numeric_rule(grid: RawGrid, outcomes: tuple[_Outcome, ...]) -> DecisionRule:
    output = DecisionOutput(name="voltage_limit", kind="numeric", unit=grid.target_unit)
    return DecisionRule(
        id=ids.DVC_VOLTAGE_LIMITS,
        inputs=_table_2_inputs(grid),
        outputs=(output,),
        rows=tuple(
            DecisionRow(
                matchers=_matchers(outcome, grid.target_unit),
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


def _curve_reference_rule(grid: RawGrid, outcomes: tuple[_Outcome, ...]) -> DecisionRule:
    return DecisionRule(
        id=f"{ids.DVC_VOLTAGE_LIMITS}.fault_time_reference",
        inputs=_table_2_inputs(grid),
        outputs=(DecisionOutput(name="fault_time_voltage", kind="reference"),),
        rows=tuple(
            DecisionRow(
                matchers=_matchers(outcome, grid.target_unit),
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


def _impulse_reference_rule(grid: RawGrid, outcomes: tuple[_Outcome, ...]) -> DecisionRule:
    return DecisionRule(
        id=f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference",
        inputs=_table_2_inputs(grid),
        outputs=(
            DecisionOutput(name="ac_reference", kind="reference"),
            DecisionOutput(name="dc_reference", kind="reference"),
        ),
        rows=tuple(
            DecisionRow(
                matchers=_matchers(outcome, grid.target_unit),
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


def _not_applicable_rule(grid: RawGrid, outcomes: tuple[_Outcome, ...]) -> DecisionRule:
    return DecisionRule(
        id=f"{ids.DVC_VOLTAGE_LIMITS}.not_applicable",
        inputs=_table_2_inputs(grid),
        outputs=(DecisionOutput(name="applicable", kind="boolean"),),
        rows=tuple(
            DecisionRow(
                matchers=_matchers(outcome, grid.target_unit),
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
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project a complete reviewed Table 2 grid into proposed typed decisions."""

    if grid.id != f"raw-{ids.DVC_VOLTAGE_LIMITS}":
        raise ValueError("Table 2 projection requires the DVC voltage-limit grid")
    if grid.source.standard != identity.standard or grid.source.edition != identity.edition:
        raise ValueError("Table 2 grid does not match its identified source")
    structured = apply_table_structure(grid, TABLE_2)
    outcomes = _outcomes(structured)
    numeric = tuple(item for item in outcomes if item.kind == "numeric")
    curve = tuple(item for item in outcomes if item.value == ids.DVC_FAULT_TIME_VOLTAGE)
    impulse = tuple(
        item for item in outcomes if item.value == ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC
    )
    not_applicable = tuple(item for item in outcomes if item.kind == "not_applicable")
    rules = (
        _numeric_rule(structured, numeric),
        _curve_reference_rule(structured, curve),
        _impulse_reference_rule(structured, impulse),
        _not_applicable_rule(structured, not_applicable),
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


class ProtectionOutcome(FrozenModel):
    """One reviewed Table 3 data cell as a typed protection outcome."""

    dvc: Identifier
    protection_context: Identifier
    requirement: Literal["none", "basic_protection", "enhanced_protection"]
    source: SourceReference


class _ProtectionCell(NamedTuple):
    logical_row: int
    logical_column: Identifier
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
        assert cell.logical_row is not None
        assert cell.logical_column is not None
        token = _protection_token(cell)
        if cell.value is not None or token is None:
            raise ValueError(
                f"Table 3 has an unknown categorical token at {(cell.row, cell.column)}"
            )
        cells.append(
            _ProtectionCell(
                cell.logical_row,
                cell.logical_column,
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
) -> DecisionRule:
    dvcs = tuple(f"dvc-{row + 1}" for row in range(TABLE_3.expected_data_rows))
    contexts = tuple(column.semantic_id for column in TABLE_3.columns if column.role == "data")
    outcomes = tuple(
        ProtectionOutcome(
            dvc=dvcs[cell.logical_row],
            protection_context=cell.logical_column,
            requirement=cast(
                Literal["none", "basic_protection", "enhanced_protection"],
                cell.requirement,
            ),
            source=cell.source,
        )
        for cell in cells
    )
    return DecisionRule(
        id=ids.DVC_PROTECTION_MATRIX,
        inputs=(
            DecisionInput(
                name="dvc",
                kind="categorical",
                allowed_values=dvcs,
            ),
            DecisionInput(
                name="protection_context",
                kind="categorical",
                allowed_values=contexts,
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
                matchers=(
                    Matcher(
                        input="dvc",
                        op="equals",
                        values=(outcome.dvc,),
                    ),
                    Matcher(
                        input="protection_context",
                        op="equals",
                        values=(outcome.protection_context,),
                    ),
                ),
                values=(
                    DecisionValue(
                        name="protection_requirement",
                        categorical=outcome.requirement,
                    ),
                ),
                source=outcome.source,
            )
            for outcome in outcomes
        ),
        exhaustive=True,
        source=grid.source,
    )


def project_dvc_protection_matrix(
    grid: RawGrid,
    identity: StandardIdentity,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project a complete reviewed Table 3 grid into proposed typed decisions."""

    if grid.id != f"raw-{ids.DVC_PROTECTION_MATRIX}":
        raise ValueError("Table 3 projection requires the DVC protection matrix grid")
    if grid.source.standard != identity.standard or grid.source.edition != identity.edition:
        raise ValueError("Table 3 grid does not match its identified source")
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
    rules = (_protection_rule(structured, cells),)
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
    "ProtectionOutcome",
    "project_dvc_protection_matrix",
    "project_dvc_voltage_limits",
]
