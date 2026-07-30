from __future__ import annotations

import hashlib
import re

from pydantic import computed_field

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    RULE_SCHEMA_VERSION,
    Add,
    Compare,
    Divide,
    Expression,
    LinearInterpolate,
    Lookup,
    Maximum,
    Minimum,
    Multiply,
    Round,
    RulePackage,
    Select,
)
from insulation_coordination.rules.archive import CORE_MEMBERS, _core_member_payloads

_SHA256 = re.compile(r"[0-9a-f]{64}")


class ValidationResult(FrozenModel):
    code: str
    passed: bool
    message: str


class ValidationReport(FrozenModel):
    results: tuple[ValidationResult, ...]

    @computed_field  # type: ignore[prop-decorator]  # Pydantic's supported property pattern.
    @property
    def is_valid(self) -> bool:
        return all(result.passed for result in self.results)


def _result(code: str, passed: bool, message: str) -> ValidationResult:
    return ValidationResult(code=code, passed=passed, message=message)


def _expression_children(expression: Expression) -> tuple[Expression, ...]:
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


def _walk_expression(expression: Expression) -> tuple[Expression, ...]:
    return (expression,) + tuple(
        descendant
        for child in _expression_children(expression)
        for descendant in _walk_expression(child)
    )


def validate_rule_package(package: RulePackage) -> ValidationReport:
    table_ids = [table.id for table in package.tables]
    formula_ids = [formula.id for formula in package.formulas]
    mapping_ids = [mapping.id for mapping in package.mappings]
    expected_checksums = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in _core_member_payloads(package).items()
    }
    checksums_valid = (
        set(package.checksums) == set(CORE_MEMBERS)
        and all(_SHA256.fullmatch(value) is not None for value in package.checksums.values())
        and package.checksums == expected_checksums
    )
    complete_tables = all(
        {(cell.row, cell.column) for cell in table.cells}
        == {
            (row, column)
            for row in range(len(table.row_axis.values))
            for column in range(len(table.column_axis.values))
        }
        and len(table.cells)
        == len(table.row_axis.values) * len(table.column_axis.values)
        and all(cell.unit == table.unit for cell in table.cells)
        and all(
            (cell.source.table or cell.source.figure)
            and cell.source.row is not None
            and cell.source.column is not None
            for cell in table.cells
        )
        for table in package.tables
    )
    referenced_tables = {
        node.table_id
        for formula in package.formulas
        for node in _walk_expression(formula.expression)
        if isinstance(node, Lookup | LinearInterpolate)
    }
    results = (
        _result(
            "schema",
            package.manifest.schema_version == RULE_SCHEMA_VERSION,
            "schema version is supported",
        ),
        _result("approval", package.manifest.approved, "package is approved"),
        _result(
            "approval_record",
            any(
                record.action == "approval"
                for record in package.manifest.approval_records
            ),
            "approval record exists",
        ),
        _result(
            "compatibility",
            package.manifest.compatible
            and all(mapping.approved for mapping in package.mappings),
            "compatibility mappings are approved",
        ),
        _result("checksums", checksums_valid, "member checksums are valid"),
        _result(
            "package_digest",
            package.package_sha256 is not None
            and _SHA256.fullmatch(package.package_sha256) is not None,
            "archive package digest is present",
        ),
        _result(
            "unique_ids",
            len(table_ids) == len(set(table_ids))
            and len(formula_ids) == len(set(formula_ids))
            and len(mapping_ids) == len(set(mapping_ids)),
            "semantic IDs are unique",
        ),
        _result("table_cells", complete_tables, "table cells are complete and referenced"),
        _result(
            "table_references",
            referenced_tables <= set(table_ids),
            "formula table references exist",
        ),
    )
    return ValidationReport(results=results)
