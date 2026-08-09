from __future__ import annotations

import hashlib
import re
from decimal import Decimal, DecimalException
from itertools import pairwise

from pydantic import computed_field

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    IEC_IMPORTER_VERSION,
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
    Power,
    Round,
    RulePackage,
    Select,
    SourceReference,
    SupportedRange,
    Table,
    TableSelect,
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
        return (expression.x,) if expression.column is None else (expression.x, expression.column)
    if isinstance(expression, TableSelect):
        return (expression.row, expression.column)
    if isinstance(expression, Power):
        return (expression.base,)
    return ()


def _walk_expression(expression: Expression) -> tuple[Expression, ...]:
    return (expression,) + tuple(
        descendant
        for child in _expression_children(expression)
        for descendant in _walk_expression(child)
    )


def _strictly_increasing(values: tuple[Decimal, ...]) -> bool:
    return len(values) == len(set(values)) and all(left < right for left, right in pairwise(values))


def _record_source_valid(source: SourceReference) -> bool:
    return bool(source.clause and (source.table or source.figure))


def _clause_source_valid(source: SourceReference) -> bool:
    return bool(source.clause)


def _curve_source_valid(source: SourceReference) -> bool:
    return bool(source.figure or _record_source_valid(source))


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
        and (parameter.minimum is None or supported_range.minimum >= parameter.minimum)
        and (parameter.maximum is None or supported_range.maximum <= parameter.maximum)
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
    decision_ids = [decision.id for decision in package.decisions]
    procedure_ids = [procedure.id for procedure in package.procedures]
    guidance_ids = [guidance.id for guidance in package.guidance]
    curve_ids = [curve.id for curve in package.curves]
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
    valid_table_cells = all(
        bool(table.cells)
        and len({(cell.row, cell.column) for cell in table.cells}) == len(table.cells)
        and all(
            cell.row < len(table.row_axis.values) and cell.column < len(table.column_axis.values)
            for cell in table.cells
        )
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
            node.name for node in _walk_expression(formula.expression) if isinstance(node, Variable)
        }
        formula_parameters_valid = formula_parameters_valid and (
            len({item.id for item in parameter_sets}) == len(parameter_sets)
            and (not used or bool(parameter_sets))
            and all(
                len({parameter.name for parameter in item.parameters}) == len(item.parameters)
                and used <= {parameter.name for parameter in item.parameters}
                for item in parameter_sets
            )
        )
        range_linkage_valid = (
            range_linkage_valid
            and (not formula.supported_ranges or bool(parameter_sets))
            and all(
                _range_matches_parameter(supported_range, parameter_set.parameters)
                for supported_range in formula.supported_ranges
                for parameter_set in parameter_sets
            )
        )

    tables_by_id = {table.id: table for table in package.tables}
    referenced_tables = {
        node.table_id
        for formula in package.formulas
        for node in _walk_expression(formula.expression)
        if isinstance(node, Lookup | LinearInterpolate | TableSelect)
    }
    formula_tables_valid = referenced_tables <= set(table_ids)
    mapping_links_valid = all(mapping.target_rule_id in formula_ids for mapping in package.mappings)
    mapping_source_ids = [mapping.source_rule_id for mapping in package.mappings]
    is_iec_import = package.manifest.importer_version.startswith("iec-pdf-")
    trusted_iec_package = is_iec_import and package.manifest.approved
    if trusted_iec_package:
        from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
        from insulation_coordination.rules.importer.recipes import RECIPES

        decision_projected_tables = {
            ids.DVC_VOLTAGE_LIMITS,
            ids.DVC_PROTECTION_MATRIX,
        }
        expected_table_ids = {
            spec.semantic_id
            for recipe in RECIPES
            for spec in recipe.tables
            if spec.semantic_id not in decision_projected_tables
        }
        expected_formula_ids = {spec.semantic_id for recipe in RECIPES for spec in recipe.formulas}
        expected_mapping_ids = {spec.id for recipe in RECIPES for spec in recipe.mappings}
    else:
        expected_table_ids = set(table_ids)
        expected_formula_ids = set(formula_ids)
        expected_mapping_ids = set(mapping_ids)
    legacy_ids = (*table_ids, *formula_ids, *mapping_ids)
    rule_ids = (*decision_ids, *procedure_ids, *guidance_ids)
    identifiers = (*legacy_ids, *rule_ids, *curve_ids)
    # A decision, procedure or guidance id is what applicability_rule_id and a
    # reference output resolve against, so it must be unique against every other
    # id in the package, not merely within its own kind.
    unique_ids = (
        len(table_ids) == len(set(table_ids))
        and len(formula_ids) == len(set(formula_ids))
        and len(mapping_ids) == len(set(mapping_ids))
        and len(rule_ids) == len(set(rule_ids))
        and set(rule_ids).isdisjoint(legacy_ids)
        and len(curve_ids) == len(set(curve_ids))
        and set(curve_ids).isdisjoint((*legacy_ids, *rule_ids))
    )
    procedure_references = tuple(
        procedure.applicability_rule_id
        for procedure in package.procedures
        if procedure.applicability_rule_id is not None
    )
    decision_references = tuple(
        value.reference
        for decision in package.decisions
        for row in decision.rows
        for value in row.values
        if value.reference is not None
    )
    semantic_targets: dict[str, list[str]] = {}
    for kind, rules in (
        ("table", package.tables),
        ("formula", package.formulas),
        ("decision", package.decisions),
        ("procedure", package.procedures),
        ("guidance", package.guidance),
        ("curve", package.curves),
    ):
        for rule in rules:
            semantic_targets.setdefault(rule.id, []).append(kind)
    semantic_references_resolve = all(
        len(semantic_targets.get(reference, ())) == 1
        for reference in decision_references
    )
    rule_references_valid = (
        set(procedure_references) <= set(rule_ids) and semantic_references_resolve
    )
    obsolete_markers = (
        "raw_sequence",
        "-f3",
        "-f4",
        "table-5",
        "functional-applicability",
        "iteration-limit",
        "iteration-tolerance",
    )
    obsolete_content = any(
        marker in identifier for marker in obsolete_markers for identifier in identifiers
    ) or any(
        node.name == "raw_sequence"
        for formula in package.formulas
        for node in _walk_expression(formula.expression)
        if isinstance(node, Variable)
    )
    for formula in package.formulas:
        for node in _walk_expression(formula.expression):
            if not isinstance(node, LinearInterpolate):
                if not isinstance(node, TableSelect):
                    continue
                table = tables_by_id.get(node.table_id)
                if table is None:
                    continue
                formula_tables_valid = formula_tables_valid and (
                    (
                        "linear" not in (node.row_mode, node.column_mode)
                        or table.interpolation == "linear"
                    )
                    and (not isinstance(node.row, Variable) or node.row.name == table.row_axis.id)
                    and (
                        not isinstance(node.column, Variable)
                        or node.column.name == table.column_axis.id
                    )
                )
                continue
            table = tables_by_id.get(node.table_id)
            if table is None:
                continue
            formula_tables_valid = formula_tables_valid and (
                table.interpolation == "linear"
                and len(table.row_axis.values) >= 2
                and (node.column is not None or len(table.column_axis.values) == 1)
                and (not isinstance(node.x, Variable) or node.x.name == table.row_axis.id)
                and (
                    node.column is None
                    or not isinstance(node.column, Literal)
                    or node.column.value in table.column_axis.values
                )
            )

    sources_valid = (
        all(
            _record_source_valid(table.source)
            and all(_cell_source_valid(cell.source) for cell in table.cells)
            and all(_record_source_valid(item.source) for item in table.supported_ranges)
            for table in package.tables
        )
        and all(
            _record_source_valid(formula.source)
            and all(
                _record_source_valid(parameter_set.source)
                for parameter_set in formula.parameter_sets
            )
            and all(_record_source_valid(item.source) for item in formula.supported_ranges)
            for formula in package.formulas
        )
        and all(_record_source_valid(mapping.source) for mapping in package.mappings)
        and all(
            _clause_source_valid(decision.source)
            and all(_clause_source_valid(row.source) for row in decision.rows)
            for decision in package.decisions
        )
        and all(
            _record_source_valid(procedure.source)
            and all(
                _record_source_valid(step.source)
                for step in (*procedure.preparation_steps, *procedure.procedure_steps)
            )
            and (
                procedure.acceptance_reference is None
                or _record_source_valid(procedure.acceptance_reference)
            )
            for procedure in package.procedures
        )
        and all(_record_source_valid(guidance.source) for guidance in package.guidance)
        and all(
            _curve_source_valid(curve.source)
            and all(_curve_source_valid(variant.source) for variant in curve.variants)
            for curve in package.curves
        )
    )
    from insulation_coordination.rules.audit import _source_references

    source_document_links_valid = all(
        len(matches := tuple(
            document
            for document in package.manifest.source_documents
            if document.id == owned.reference.document_id
        )) == 1
        and matches[0].standard == owned.reference.standard
        and matches[0].edition == owned.reference.edition
        for owned in _source_references(package)
    )
    results = (
        _result(
            "schema",
            package.manifest.schema_version == RULE_SCHEMA_VERSION,
            "schema version is supported",
        ),
        _result(
            "importer_version",
            not trusted_iec_package or package.manifest.importer_version == IEC_IMPORTER_VERSION,
            "IEC package uses the current semantic PDF importer",
        ),
        _result(
            "pcb_source_inventory",
            not trusted_iec_package
            or (
                set(table_ids) == expected_table_ids
                and set(formula_ids) == expected_formula_ids
                and set(mapping_ids) == expected_mapping_ids
            ),
            "IEC package contains the complete PCB Annex G/H source inventory",
        ),
        _result(
            "obsolete_rule_content",
            not trusted_iec_package or not obsolete_content,
            "IEC package contains no obsolete placeholder rule content",
        ),
        _result("approval", package.manifest.approved, "package is approved"),
        _result(
            "approval_record",
            any(record.action == "approval" for record in package.manifest.approval_records),
            "approval record exists",
        ),
        _result(
            "compatibility",
            package.manifest.compatible and all(mapping.approved for mapping in package.mappings),
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
            unique_ids,
            "decision, procedure, guidance and curve IDs are globally unique; "
            "table, formula and mapping IDs are unique within their own kind",
        ),
        _result("table_cells", valid_table_cells, "table cells are unique and in bounds"),
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
            "rule_references",
            rule_references_valid,
            "procedure and decision rule references resolve to a rule in the package",
        ),
        _result(
            "SEMANTIC_REFERENCES_RESOLVE",
            semantic_references_resolve,
            "every decision reference resolves to exactly one final semantic rule",
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
        _result(
            "SOURCE_DOCUMENT_LINKS_VALID",
            source_document_links_valid,
            "source references resolve to exactly one matching manifest document",
        ),
    )
    return ValidationReport(results=results)
