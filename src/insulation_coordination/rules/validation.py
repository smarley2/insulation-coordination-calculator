from __future__ import annotations

import hashlib
import re
from decimal import Decimal, DecimalException
from itertools import pairwise

from pydantic import computed_field

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    RULE_SCHEMA_VERSION,
    Add,
    Compare,
    Divide,
    Expression,
    LinearInterpolate,
    Literal,
    Lookup,
    Maximum,
    Minimum,
    Multiply,
    Parameter,
    Round,
    RulePackage,
    Select,
    SourceReference,
    SupportedRange,
    Table,
    Variable,
)
from insulation_coordination.rules.archive import (
    CORE_MEMBERS,
    _archive_bytes,
    _core_member_payloads,
)

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


def _package_structure_failure() -> ValidationReport:
    return ValidationReport(
        results=(
            _result(
                "package_structure",
                False,
                "rule package has invalid structure or non-finite numeric content",
            ),
        )
    )


def _finite_decimals(value: object) -> bool:
    if isinstance(value, Decimal):
        return value.is_finite()
    if isinstance(value, dict):
        return all(_finite_decimals(item) for item in value.values())
    if isinstance(value, list | tuple):
        return all(_finite_decimals(item) for item in value)
    return True


def _revalidate_package(package: RulePackage) -> RulePackage:
    raw = package.model_dump(mode="python", warnings=False)
    raw["package_sha256"] = package.package_sha256
    return RulePackage.model_validate(raw)


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
        return (
            (expression.x,)
            if expression.column is None
            else (expression.x, expression.column)
        )
    return ()


def _walk_expression(expression: Expression) -> tuple[Expression, ...]:
    return (expression,) + tuple(
        descendant
        for child in _expression_children(expression)
        for descendant in _walk_expression(child)
    )


def _strictly_increasing(values: tuple[Decimal, ...]) -> bool:
    return len(values) == len(set(values)) and all(
        left < right for left, right in pairwise(values)
    )


def _record_source_valid(source: SourceReference) -> bool:
    return bool(source.clause and (source.table or source.figure))


def _cell_source_valid(source: SourceReference) -> bool:
    return bool(
        source.clause
        and (source.table or source.figure)
        and source.row is not None
        and source.column is not None
    )


def _range_matches_parameter(
    supported_range: SupportedRange, parameters: tuple[Parameter, ...]
) -> bool:
    return any(
        parameter.name == supported_range.variable
        and parameter.unit == supported_range.unit
        and (
            parameter.minimum is None
            or supported_range.minimum >= parameter.minimum
        )
        and (
            parameter.maximum is None
            or supported_range.maximum <= parameter.maximum
        )
        for parameter in parameters
    )


def _table_range_linked(table: Table, supported_range: SupportedRange) -> bool:
    axes = {
        table.row_axis.id: table.row_axis,
        table.column_axis.id: table.column_axis,
    }
    axis = axes.get(supported_range.variable)
    return bool(
        axis is not None
        and axis.unit == supported_range.unit
        and supported_range.minimum >= min(axis.values)
        and supported_range.maximum <= max(axis.values)
    )


def validate_rule_package(package: RulePackage) -> ValidationReport:
    try:
        package = _revalidate_package(package)
        if not _finite_decimals(package.model_dump(mode="python", warnings=False)):
            return _package_structure_failure()
        return _validate_rule_package(package)
    except (
        AttributeError,
        DecimalException,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        return _package_structure_failure()


def _validate_rule_package(package: RulePackage) -> ValidationReport:
    table_ids = [table.id for table in package.tables]
    formula_ids = [formula.id for formula in package.formulas]
    mapping_ids = [mapping.id for mapping in package.mappings]
    try:
        expected_checksums = {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in _core_member_payloads(package).items()
        }
        archive_content, _ = _archive_bytes(package)
        expected_package_digest = hashlib.sha256(archive_content).hexdigest()
    except (AttributeError, RecursionError, TypeError, ValueError):
        expected_checksums = {}
        expected_package_digest = ""
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
        for table in package.tables
    )
    table_axes_valid = all(
        table.row_axis.id != table.column_axis.id
        and _strictly_increasing(table.row_axis.values)
        and _strictly_increasing(table.column_axis.values)
        for table in package.tables
    )
    formula_parameters_valid = True
    range_linkage_valid = all(
        _table_range_linked(table, supported_range)
        for table in package.tables
        for supported_range in table.supported_ranges
    )
    for formula in package.formulas:
        parameter_sets = formula.parameter_sets
        used = {
            node.name
            for node in _walk_expression(formula.expression)
            if isinstance(node, Variable)
        }
        formula_parameters_valid = formula_parameters_valid and (
            len({item.id for item in parameter_sets}) == len(parameter_sets)
            and (not used or bool(parameter_sets))
            and all(
                len({parameter.name for parameter in item.parameters})
                == len(item.parameters)
                and used <= {parameter.name for parameter in item.parameters}
                for item in parameter_sets
            )
        )
        range_linkage_valid = range_linkage_valid and (
            not formula.supported_ranges or bool(parameter_sets)
        ) and all(
            _range_matches_parameter(supported_range, parameter_set.parameters)
            for supported_range in formula.supported_ranges
            for parameter_set in parameter_sets
        )

    tables_by_id = {table.id: table for table in package.tables}
    referenced_tables = {
        node.table_id
        for formula in package.formulas
        for node in _walk_expression(formula.expression)
        if isinstance(node, Lookup | LinearInterpolate)
    }
    formula_tables_valid = referenced_tables <= set(table_ids)
    mapping_links_valid = all(mapping.target_rule_id in formula_ids for mapping in package.mappings)
    mapping_source_ids = [mapping.source_rule_id for mapping in package.mappings]
    for formula in package.formulas:
        for node in _walk_expression(formula.expression):
            if not isinstance(node, LinearInterpolate):
                continue
            table = tables_by_id.get(node.table_id)
            if table is None:
                continue
            formula_tables_valid = formula_tables_valid and (
                table.interpolation == "linear"
                and len(table.row_axis.values) >= 2
                and (node.column is not None or len(table.column_axis.values) == 1)
                and (
                    not isinstance(node.x, Variable)
                    or node.x.name == table.row_axis.id
                )
                and (
                    node.column is None
                    or not isinstance(node.column, Literal)
                    or node.column.value in table.column_axis.values
                )
            )

    sources_valid = all(
        _record_source_valid(table.source)
        and all(_cell_source_valid(cell.source) for cell in table.cells)
        and all(_record_source_valid(item.source) for item in table.supported_ranges)
        for table in package.tables
    ) and all(
        _record_source_valid(formula.source)
        and all(
            _record_source_valid(parameter_set.source)
            for parameter_set in formula.parameter_sets
        )
        and all(_record_source_valid(item.source) for item in formula.supported_ranges)
        for formula in package.formulas
    ) and all(_record_source_valid(mapping.source) for mapping in package.mappings)
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
            and _SHA256.fullmatch(package.package_sha256) is not None
            and package.package_sha256 == expected_package_digest,
            "archive package digest matches deterministic content",
        ),
        _result(
            "unique_ids",
            len(table_ids) == len(set(table_ids))
            and len(formula_ids) == len(set(formula_ids))
            and len(mapping_ids) == len(set(mapping_ids)),
            "semantic IDs are unique",
        ),
        _result("table_cells", complete_tables, "table cells are complete and referenced"),
        _result("table_axes", table_axes_valid, "table axes are unique and monotonic"),
        _result(
            "formula_parameters",
            formula_parameters_valid,
            "formula variables are declared by parameter sets",
        ),
        _result(
            "range_linkage",
            range_linkage_valid,
            "supported ranges link to declared axes or parameters",
        ),
        _result(
            "table_references",
            referenced_tables <= set(table_ids),
            "formula table references exist",
        ),
        _result(
            "mapping_links",
            mapping_links_valid,
            "compatibility mappings target existing formulas",
        ),
        _result(
            "mapping_routes",
            len(mapping_source_ids) == len(set(mapping_source_ids)),
            "compatibility mapping source routes are unique",
        ),
        _result(
            "formula_tables",
            formula_tables_valid,
            "lookup and interpolation dimensions are unambiguous",
        ),
        _result(
            "source_references",
            sources_valid,
            "all package records have meaningful source locators",
        ),
    )
    return ValidationReport(results=results)
