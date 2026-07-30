from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path

from pydantic import computed_field

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    Add,
    ApprovalRecord,
    Compare,
    CompatibilityMapping,
    Divide,
    Expression,
    LinearInterpolate,
    Lookup,
    Maximum,
    Minimum,
    Multiply,
    ParameterSet,
    Round,
    RulePackage,
    Select,
    SourceDocument,
    SourceReference,
    SupportedRange,
    TableCell,
)
from insulation_coordination.rules.validation import ValidationReport, validate_rule_package


class AuditedTableCell(FrozenModel):
    table_id: str
    row_index: int
    column_index: int
    cell: TableCell


class AuditedFormulaNode(FrozenModel):
    formula_id: str
    path: str
    op: str
    node: Expression


class ChecksumRecord(FrozenModel):
    member: str
    sha256: str


class AuditInventory(FrozenModel):
    package_id: str
    version: str
    schema_version: int
    package_sha256: str | None
    source_documents: tuple[SourceDocument, ...]
    table_cells: tuple[AuditedTableCell, ...]
    formula_nodes: tuple[AuditedFormulaNode, ...]
    mappings: tuple[CompatibilityMapping, ...]
    parameter_sets: tuple[ParameterSet, ...]
    supported_ranges: tuple[SupportedRange, ...]
    source_references: tuple[SourceReference, ...]
    checksums: tuple[ChecksumRecord, ...]
    approval_records: tuple[ApprovalRecord, ...]
    validation: ValidationReport

    @computed_field  # type: ignore[prop-decorator]  # Pydantic's supported property pattern.
    @property
    def table_cell_count(self) -> int:
        return len(self.table_cells)

    @computed_field  # type: ignore[prop-decorator]  # Pydantic's supported property pattern.
    @property
    def formula_node_count(self) -> int:
        return len(self.formula_nodes)

    @computed_field  # type: ignore[prop-decorator]  # Pydantic's supported property pattern.
    @property
    def mapping_count(self) -> int:
        return len(self.mappings)

    @computed_field  # type: ignore[prop-decorator]  # Pydantic's supported property pattern.
    @property
    def parameter_set_count(self) -> int:
        return len(self.parameter_sets)

    @computed_field  # type: ignore[prop-decorator]  # Pydantic's supported property pattern.
    @property
    def supported_range_count(self) -> int:
        return len(self.supported_ranges)

    @computed_field  # type: ignore[prop-decorator]  # Pydantic's supported property pattern.
    @property
    def source_reference_count(self) -> int:
        return len(self.source_references)

    @computed_field  # type: ignore[prop-decorator]  # Pydantic's supported property pattern.
    @property
    def checksum_count(self) -> int:
        return len(self.checksums)

    @computed_field  # type: ignore[prop-decorator]  # Pydantic's supported property pattern.
    @property
    def approval_record_count(self) -> int:
        return len(self.approval_records)


def _children(expression: Expression) -> tuple[Expression, ...]:
    if isinstance(expression, Add | Multiply | Minimum | Maximum):
        return expression.operands
    if isinstance(expression, Divide):
        return (expression.numerator, expression.denominator)
    if isinstance(expression, Compare):
        return (expression.left, expression.right)
    if isinstance(expression, Select):
        return (expression.condition, expression.if_true, expression.if_false)
    if isinstance(expression, Round):
        return (expression.value,)
    if isinstance(expression, Lookup):
        return (expression.row, expression.column)
    if isinstance(expression, LinearInterpolate):
        return (expression.x,)
    return ()


def iter_formula_nodes(
    expression: Expression, path: str = "expression"
) -> Iterator[tuple[str, Expression]]:
    yield path, expression
    for index, child in enumerate(_children(expression)):
        yield from iter_formula_nodes(child, f"{path}.{index}")


def _source_references(package: RulePackage) -> tuple[SourceReference, ...]:
    references: list[SourceReference] = []
    for table in package.tables:
        references.append(table.source)
        references.extend(cell.source for cell in table.cells)
        references.extend(item.source for item in table.supported_ranges)
    for formula in package.formulas:
        references.append(formula.source)
        references.extend(
            parameter_set.source
            for parameter_set in formula.parameter_sets
            if parameter_set.source is not None
        )
        references.extend(item.source for item in formula.supported_ranges)
    references.extend(mapping.source for mapping in package.mappings)
    return tuple(references)


def build_audit_inventory(package: RulePackage) -> AuditInventory:
    cells = tuple(
        AuditedTableCell(
            table_id=table.id,
            row_index=cell.row,
            column_index=cell.column,
            cell=cell,
        )
        for table in package.tables
        for cell in table.cells
    )
    nodes = tuple(
        AuditedFormulaNode(
            formula_id=formula.id,
            path=path,
            op=node.op,
            node=node,
        )
        for formula in package.formulas
        for path, node in iter_formula_nodes(formula.expression)
    )
    return AuditInventory(
        package_id=str(package.manifest.package_id),
        version=package.manifest.version,
        schema_version=package.manifest.schema_version,
        package_sha256=package.package_sha256,
        source_documents=package.manifest.source_documents,
        table_cells=cells,
        formula_nodes=nodes,
        mappings=package.mappings,
        parameter_sets=tuple(
            parameter_set
            for formula in package.formulas
            for parameter_set in formula.parameter_sets
        ),
        supported_ranges=tuple(
            supported_range
            for table in package.tables
            for supported_range in table.supported_ranges
        )
        + tuple(
            supported_range
            for formula in package.formulas
            for supported_range in formula.supported_ranges
        ),
        source_references=_source_references(package),
        checksums=tuple(
            ChecksumRecord(member=member, sha256=digest)
            for member, digest in sorted(package.checksums.items())
        ),
        approval_records=package.manifest.approval_records,
        validation=validate_rule_package(package),
    )


def export_table_csv(package: RulePackage, table_id: str, path: Path) -> None:
    try:
        table = next(table for table in package.tables if table.id == table_id)
    except StopIteration as error:
        raise KeyError(f"missing table {table_id}") from error
    fields = (
        "table_id",
        "row_index",
        "row_value",
        "column_index",
        "column_value",
        "value",
        "unit",
        "standard",
        "edition",
        "clause",
        "table",
        "figure",
        "source_row",
        "source_column",
        "note",
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for cell in table.cells:
            source = cell.source
            writer.writerow(
                {
                    "table_id": table.id,
                    "row_index": cell.row,
                    "row_value": str(table.row_axis.values[cell.row]),
                    "column_index": cell.column,
                    "column_value": str(table.column_axis.values[cell.column]),
                    "value": str(cell.value),
                    "unit": cell.unit,
                    "standard": source.standard,
                    "edition": source.edition,
                    "clause": source.clause or "",
                    "table": source.table or "",
                    "figure": source.figure or "",
                    "source_row": source.row or "",
                    "source_column": source.column or "",
                    "note": source.note or "",
                }
            )


def export_inventory_json(inventory: AuditInventory, path: Path) -> None:
    content = json.dumps(
        inventory.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    path.write_text(content + "\n", encoding="utf-8")
