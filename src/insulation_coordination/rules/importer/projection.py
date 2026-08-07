"""Deterministic projection of accepted source artifacts into typed rules."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import cast

from insulation_coordination.domain.rules import (
    Add,
    AxisSelectionMode,
    Compare,
    CompatibilityMapping,
    Divide,
    Formula,
    LinearInterpolate,
    Literal,
    Multiply,
    Parameter,
    ParameterSet,
    SourceReference,
    SupportedRange,
    Table,
    TableAxis,
    TableCell,
    TableSelect,
    Variable,
)
from insulation_coordination.domain.rules import Expression as RuleExpression
from insulation_coordination.rules.importer.extract import (
    ExtractedEquation,
    RawGrid,
    RawGridCell,
)
from insulation_coordination.rules.importer.identify import (
    FormulaAuditSpec,
    MappingAuditSpec,
    StandardIdentity,
    TableAuditSpec,
    TableColumnSpec,
)


def _source(
    identity: StandardIdentity,
    *,
    page_number: int,
    clause: str,
    table: str | None = None,
    figure: str | None = None,
) -> SourceReference:
    return SourceReference(
        standard=identity.standard,
        edition=identity.edition,
        clause=clause,
        table=table,
        figure=figure,
        note=f"PDF page {page_number}",
    )


def _segment_row_start(grid: RawGrid, row: int) -> int:
    """The row_start of the segment whose physical rows contain this global row."""
    for segment in grid.segments:
        if segment.row_start <= row < segment.row_start + segment.row_count:
            return segment.row_start
    raise ValueError(f"row {row} is outside every declared segment")


def _column_axis_value(
    spec: TableAuditSpec,
    column: TableColumnSpec,
    grid_column: int,
    grid: RawGrid,
    ordinal: int,
) -> Decimal:
    """A data column's axis value: declared, read from its own header row, or ordinal.

    ``axis_value_source_row`` is segment-local, the same space ``header_rows`` uses
    (extraction marks a cell "header" only when its own segment-local row is both in
    that segment's ``header_rows`` and equal to this value) -- so the row is resolved
    per-segment here too, rather than against the cell's global, row_start-offset row.
    The ``role == "header"`` check keeps a data cell that happens to land on the same
    row number in a different segment from being picked up instead.
    """
    if column.axis_value is not None:
        return column.axis_value
    if column.axis_value_source_row is not None:
        cell = next(
            (
                cell
                for cell in grid.cells
                if cell.column == grid_column
                and cell.role == "header"
                and cell.row - _segment_row_start(grid, cell.row) == column.axis_value_source_row
            ),
            None,
        )
        if cell is None or cell.value is None:
            raise ValueError(
                f"table {spec.semantic_id} column {column.semantic_id!r} has no numeric "
                "axis value in its declared header row"
            )
        return cell.value
    return Decimal(ordinal)


def project_table(
    identity: StandardIdentity,
    spec: TableAuditSpec,
    grid: RawGrid,
) -> Table:
    """Project one reviewed grid without flattening semantic coordinates."""
    if not spec.columns:
        return _project_legacy_table(identity, spec, grid)
    axis_columns = tuple(column for column in spec.columns if column.role == "axis")
    data_columns = tuple(column for column in spec.columns if column.role == "data")
    if len(axis_columns) != 1 or not data_columns:
        raise ValueError(f"table {spec.semantic_id} needs one axis and numeric data columns")
    axis_column = axis_columns[0]
    logical = {
        (cell.logical_row, cell.logical_column): cell
        for cell in grid.cells
        if cell.logical_row is not None and cell.logical_column is not None
    }
    logical_rows = tuple(sorted({row for row, _ in logical}))
    axis_cells = tuple(logical.get((row, axis_column.semantic_id)) for row in logical_rows)
    if any(cell is None or cell.value is None for cell in axis_cells):
        raise ValueError(f"table {spec.semantic_id} has an incomplete row axis")
    row_values = tuple(
        cell.value for cell in axis_cells if cell is not None and cell.value is not None
    )
    row_labels = tuple(
        re.sub(r"\W+", "-", cell.raw_text.strip().casefold()).strip("-") or f"row-{index + 1}"
        for index, cell in enumerate(axis_cells)
        if cell is not None
    )
    grid_column_index = {column.semantic_id: index for index, column in enumerate(spec.columns)}
    column_values = tuple(
        _column_axis_value(spec, column, grid_column_index[column.semantic_id], grid, ordinal)
        for ordinal, column in enumerate(data_columns, start=1)
    )
    cells: list[TableCell] = []
    previous_by_column: dict[str, RawGridCell] = {}
    for row_index, logical_row in enumerate(logical_rows):
        for column_index, column in enumerate(data_columns):
            raw = logical.get((logical_row, column.semantic_id))
            if raw is not None and raw.value is not None:
                previous_by_column[column.semantic_id] = raw
            elif column.fill_down:
                raw = previous_by_column.get(column.semantic_id)
            if raw is None or raw.value is None:
                continue
            cells.append(
                TableCell(
                    row=row_index,
                    column=column_index,
                    value=raw.value,
                    unit=spec.target_unit,
                    source=raw.source,
                )
            )
    if not cells:
        raise ValueError(f"table {spec.semantic_id} has no projectable numeric cells")
    source = _source(
        identity,
        page_number=grid.segments[0].page_number,
        clause=spec.clause,
        table=spec.source_table,
    )
    row_axis = TableAxis(
        id=spec.row_axis_id,
        unit=spec.row_axis_unit,
        values=row_values,
        labels=row_labels,
    )
    return Table(
        id=spec.semantic_id,
        unit=spec.target_unit,
        row_axis=row_axis,
        column_axis=TableAxis(
            id=spec.column_axis_id,
            unit=spec.column_axis_unit,
            values=column_values,
            labels=tuple(column.semantic_id for column in data_columns),
        ),
        cells=tuple(cells),
        supported_ranges=(
            SupportedRange(
                variable=row_axis.id,
                minimum=row_axis.values[0],
                maximum=row_axis.values[-1],
                unit=row_axis.unit,
                source=source,
            ),
        ),
        interpolation=spec.interpolation,
        source=source,
    )


def _project_legacy_table(
    identity: StandardIdentity,
    spec: TableAuditSpec,
    grid: RawGrid,
) -> Table:
    if spec.data_row_start is None or spec.data_column_start is None:
        raise ValueError(f"legacy table {spec.semantic_id} has no data rectangle")
    raw = {(cell.row, cell.column): cell for cell in grid.cells}
    cells: list[TableCell] = []
    for row in range(spec.expected_data_rows):
        for column in range(spec.expected_data_columns):
            raw_cell = raw[(spec.data_row_start + row, spec.data_column_start + column)]
            if raw_cell.value is None:
                continue
            cells.append(
                TableCell(
                    row=row,
                    column=column,
                    value=raw_cell.value,
                    unit=spec.target_unit,
                    source=raw_cell.source,
                )
            )
    source = _source(
        identity,
        page_number=grid.segments[0].page_number,
        clause=spec.clause,
        table=spec.source_table,
    )
    row_values = tuple(Decimal(index + 1) for index in range(spec.expected_data_rows))
    row_axis = TableAxis(
        id=spec.row_axis_id,
        unit=spec.row_axis_unit,
        values=row_values,
        labels=tuple(f"row-{index + 1}" for index in range(spec.expected_data_rows)),
    )
    return Table(
        id=spec.semantic_id,
        unit=spec.target_unit,
        row_axis=row_axis,
        column_axis=TableAxis(
            id=spec.column_axis_id,
            unit=spec.column_axis_unit,
            values=tuple(Decimal(index + 1) for index in range(spec.expected_data_columns)),
            labels=tuple(f"column-{index + 1}" for index in range(spec.expected_data_columns)),
        ),
        cells=tuple(cells),
        supported_ranges=(
            SupportedRange(
                variable=row_axis.id,
                minimum=row_axis.values[0],
                maximum=row_axis.values[-1],
                unit=row_axis.unit,
                source=source,
            ),
        ),
        interpolation=spec.interpolation,
        source=source,
    )


def project_formula(
    identity: StandardIdentity,
    spec: FormulaAuditSpec,
    equations: dict[str, ExtractedEquation],
) -> Formula:
    source = _source(
        identity,
        page_number=spec.page_number,
        clause=spec.clause,
        table=spec.table,
        figure=spec.figure,
    )
    table_match = re.fullmatch(
        r"table_select:([a-z0-9][a-z0-9._:-]*)\((exact|ceiling|linear),(exact|ceiling|linear)\)",
        spec.expression_shape,
    )
    expression: RuleExpression
    if table_match is not None:
        if len(spec.variables) != 2:
            raise ValueError(f"table formula {spec.semantic_id} needs two variables")
        expression = TableSelect(
            table_id=table_match.group(1),
            row=Variable(name=spec.variables[0]),
            column=Variable(name=spec.variables[1]),
            row_mode=cast(AxisSelectionMode, table_match.group(2)),
            column_mode=cast(AxisSelectionMode, table_match.group(3)),
        )
        applicability = spec.applicability
    elif spec.expression_shape.startswith("linear_interpolate:"):
        table_id = spec.expression_shape.split(":", 1)[1].split("(", 1)[0]
        if len(spec.variables) != 1:
            raise ValueError(f"linear table formula {spec.semantic_id} needs one variable")
        expression = LinearInterpolate(
            table_id=table_id,
            x=Variable(name=spec.variables[0]),
        )
        applicability = spec.applicability
    else:
        equation = equations.get(spec.semantic_id)
        if equation is None or equation.parse_status != "parsed":
            raise ValueError(f"reviewed equation is unavailable for {spec.semantic_id}")
        expression = _equation_expression(spec, equation)
        applicability = equation.applicability
    return Formula(
        id=spec.semantic_id,
        expression=expression,
        unit=spec.unit,
        parameter_sets=(
            ParameterSet(
                id="reviewed",
                parameters=tuple(Parameter(name=name, unit="1") for name in spec.variables),
                source=source,
            ),
        ),
        applicability=applicability,
        source=source,
    )


def _equation_expression(
    spec: FormulaAuditSpec,
    equation: ExtractedEquation,
) -> RuleExpression:
    values = equation.literals
    if spec.expression_shape == "critical_frequency_inverse_clearance" and len(values) == 1:
        return Divide(
            numerator=Literal(value=values[0]),
            denominator=Variable(name=spec.variables[0]),
        )
    if spec.expression_shape == "linear_frequency_factor" and len(values) == 2:
        frequency, critical, minimum = (Variable(name=name) for name in spec.variables)
        negative_critical = Multiply(
            operands=(Literal(value=Decimal(-1)), critical),
        )
        return Add(
            operands=(
                Literal(value=values[0]),
                Multiply(
                    operands=(
                        Divide(
                            numerator=Add(operands=(frequency, negative_critical)),
                            denominator=Add(operands=(minimum, negative_critical)),
                        ),
                        Literal(value=values[1]),
                    )
                ),
            )
        )
    if spec.expression_shape == "minimum_frequency_statement" and len(values) == 1:
        return Literal(value=values[0])
    if spec.expression_shape == "radius_to_clearance_criterion" and len(values) == 1:
        return Compare(
            comparison="ge",
            left=Divide(
                numerator=Variable(name=spec.variables[0]),
                denominator=Variable(name=spec.variables[1]),
            ),
            right=Literal(value=values[0] / Decimal(100)),
        )
    raise ValueError(f"equation shape does not match extracted literals: {spec.semantic_id}")


def project_mapping(
    identity: StandardIdentity,
    spec: MappingAuditSpec,
) -> CompatibilityMapping:
    return CompatibilityMapping(
        id=spec.id,
        source_rule_id=spec.semantic_route,
        target_rule_id=spec.target_rule_id,
        approved=False,
        source=_source(
            identity,
            page_number=spec.page_number,
            clause=spec.clause,
            table=spec.table,
            figure=spec.figure,
        ),
    )
