from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import (
    Literal,
    Parameter,
    ParameterSet,
    Power,
    RulePackage,
    RulePackageError,
    Variable,
)
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.audit import (
    build_audit_inventory,
    export_inventory_json,
    export_table_csv,
)
from insulation_coordination.rules.validation import (
    ValidationReport,
    ValidationResult,
    validate_rule_package,
)


def test_audit_inventory_enumerates_all_package_content(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    archive_path = tmp_path / "approved.icrules"
    write_rule_package(archive_path, synthetic_package)
    loaded = load_rule_package(archive_path)

    inventory = build_audit_inventory(loaded)

    assert inventory.table_cell_count == 4
    assert inventory.formula_node_count == 22
    assert inventory.mapping_count == 1
    assert inventory.parameter_set_count == 1
    assert inventory.supported_range_count == 2
    assert inventory.source_reference_count == 17
    assert inventory.checksum_count == 7
    assert inventory.approval_record_count == 1
    assert len(inventory.table_cells) == inventory.table_cell_count
    assert len(inventory.formula_nodes) == inventory.formula_node_count
    assert inventory.formula_nodes[0].node == loaded.formulas[0].expression
    assert len(inventory.source_references) == inventory.source_reference_count
    assert inventory.validation.is_valid is True
    assert inventory.manifest == loaded.manifest
    assert inventory.tables == loaded.tables
    assert inventory.formulas == loaded.formulas
    assert inventory.parameter_sets[0].owner_type == "formula"
    assert inventory.parameter_sets[0].owner_id == "synthetic-formula"
    assert inventory.parameter_sets[0].path == "parameter_sets.0"
    assert {item.owner_type for item in inventory.supported_ranges} == {
        "formula",
        "table",
    }
    assert all(item.owner_id and item.path for item in inventory.source_references)


def test_inventory_counts_decisions_procedures_and_guidance(
    synthetic_package: RulePackage,
) -> None:
    inventory = build_audit_inventory(synthetic_package)
    assert inventory.decision_count == len(synthetic_package.decisions)
    assert inventory.procedure_count == len(synthetic_package.procedures)
    assert inventory.guidance_count == len(synthetic_package.guidance)


def test_source_references_reach_decision_rows_and_procedure_steps(
    synthetic_package: RulePackage,
) -> None:
    inventory = build_audit_inventory(synthetic_package)
    decision = synthetic_package.decisions[0]
    procedure = synthetic_package.procedures[0]
    guidance = synthetic_package.guidance[0]

    decision_refs = [item for item in inventory.source_references if item.owner_type == "decision"]
    procedure_refs = [
        item for item in inventory.source_references if item.owner_type == "procedure"
    ]
    guidance_refs = [item for item in inventory.source_references if item.owner_type == "guidance"]

    # One reference for the rule-level source, plus one per row/step — not just the rule level.
    assert len(decision_refs) == 1 + len(decision.rows)
    assert len(procedure_refs) == 1 + len(procedure.procedure_steps)
    assert len(guidance_refs) == 1
    assert {item.owner_id for item in decision_refs} == {decision.id}
    assert {item.owner_id for item in procedure_refs} == {procedure.id}
    assert {item.owner_id for item in guidance_refs} == {guidance.id}
    assert any(item.path == "rows.0.source" for item in decision_refs)
    assert any(item.path == "rows.1.source" for item in decision_refs)
    assert any(item.path == "procedure_steps.0.source" for item in procedure_refs)
    assert any(item.path == "procedure_steps.1.source" for item in procedure_refs)


def test_audit_inventory_includes_nodes_nested_under_power_base(
    synthetic_package: RulePackage,
) -> None:
    formula = synthetic_package.formulas[0]
    nested_variable = Variable(name="voltage")
    with_power = synthetic_package.model_copy(
        update={
            "formulas": (
                formula.model_copy(
                    update={"expression": Power(base=nested_variable, numerator=2)}
                ),
            )
        }
    )

    inventory = build_audit_inventory(with_power)

    assert any(
        node.op == "variable" and node.node == nested_variable for node in inventory.formula_nodes
    )


def test_table_csv_has_one_row_per_cell_with_exact_reference_fields(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    path = tmp_path / "table.csv"

    export_table_csv(synthetic_package, "synthetic-distance", path)

    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4
    assert rows[0] == {
        "table_id": "synthetic-distance",
        "row_index": "0",
        "row_value": "0",
        "column_index": "0",
        "column_value": "1",
        "value": "1.00",
        "unit": "mm",
        "standard": "SYNTHETIC-1",
        "edition": "1",
        "clause": "4.2",
        "table": "T-1",
        "figure": "",
        "source_row": "0",
        "source_column": "1",
        "note": "Synthetic fixture only.",
    }


def test_inventory_json_records_counts_and_validation_without_pdf_bytes(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    archive_path = tmp_path / "approved.icrules"
    inventory_path = tmp_path / "inventory.json"
    write_rule_package(archive_path, synthetic_package)
    inventory = build_audit_inventory(load_rule_package(archive_path))

    export_inventory_json(inventory, inventory_path)

    exported = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert exported["table_cell_count"] == 4
    assert exported["formula_node_count"] == 22
    assert exported["validation"]["is_valid"] is True
    assert exported["manifest"]["importer_version"] == "test-1"
    assert exported["manifest"]["approved"] is True
    assert exported["manifest"]["compatible"] is True
    assert exported["tables"][0]["row_axis"]["id"] == "voltage"
    assert exported["tables"][0]["interpolation"] == "linear"
    assert exported["tables"][0]["rounding_places"] == 2
    assert exported["formulas"][0]["latex"] == "d = f(U)"
    assert exported["formulas"][0]["expression"]["op"] == "select"
    assert exported["parameter_sets"][0]["owner_id"] == "synthetic-formula"
    assert b"%PDF" not in archive_path.read_bytes()
    assert b"%PDF" not in inventory_path.read_bytes()


def test_export_unknown_table_is_rejected(synthetic_package: RulePackage, tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="missing"):
        export_table_csv(synthetic_package, "missing", tmp_path / "missing.csv")


def test_validation_rejects_unapproved_or_incompatible_packages(
    synthetic_package: RulePackage,
) -> None:
    unapproved = synthetic_package.model_copy(
        update={"manifest": synthetic_package.manifest.model_copy(update={"approved": False})}
    )
    incompatible = synthetic_package.model_copy(
        update={"manifest": synthetic_package.manifest.model_copy(update={"compatible": False})}
    )

    assert validate_rule_package(unapproved).is_valid is False
    assert validate_rule_package(incompatible).is_valid is False


def test_validation_rejects_obsolete_or_incomplete_iec_imports(
    synthetic_package: RulePackage,
) -> None:
    old_importer = synthetic_package.model_copy(
        update={
            "manifest": synthetic_package.manifest.model_copy(
                update={"importer_version": "iec-pdf-1"}
            )
        }
    )
    incomplete = old_importer.model_copy(
        update={
            "manifest": old_importer.manifest.model_copy(update={"importer_version": "iec-pdf-2"})
        }
    )
    obsolete_formula = synthetic_package.formulas[0].model_copy(
        update={"id": "iec60664-4-iteration-limit-formula"}
    )
    obsolete = incomplete.model_copy(update={"formulas": (obsolete_formula,)})

    assert _result(validate_rule_package(old_importer), "importer_version").passed is False
    assert _result(validate_rule_package(incomplete), "pcb_source_inventory").passed is False
    assert _result(validate_rule_package(obsolete), "obsolete_rule_content").passed is False


def test_validation_rejects_a_duplicate_decision_id(synthetic_package: RulePackage) -> None:
    decision = synthetic_package.decisions[0]
    package = synthetic_package.model_copy(update={"decisions": (decision, decision)})

    assert _result(validate_rule_package(package), "unique_ids").passed is False


def test_validation_rejects_a_decision_id_colliding_with_a_formula_id(
    synthetic_package: RulePackage,
) -> None:
    # DecisionOutput(kind="reference") resolves a rule by id, so an id shared with
    # another kind would be resolved against whichever comes first — a guess.
    decision = synthetic_package.decisions[0]
    package = synthetic_package.model_copy(
        update={"decisions": (decision.model_copy(update={"id": "synthetic-formula"}),)}
    )

    assert _result(validate_rule_package(package), "unique_ids").passed is False


def test_validation_accepts_a_sparse_table_with_unique_in_bounds_cells(
    synthetic_package: RulePackage,
) -> None:
    table = synthetic_package.tables[0]
    sparse = synthetic_package.model_copy(
        update={"tables": (table.model_copy(update={"cells": table.cells[:-1]}),)}
    )

    assert _result(validate_rule_package(sparse), "table_cells").passed is True


def test_validation_recomputes_package_digest_and_audit_reflects_tampering(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    path = tmp_path / "approved.icrules"
    write_rule_package(path, synthetic_package)
    loaded = load_rule_package(path)
    tampered = loaded.model_copy(update={"package_sha256": "b" * 64})

    report = validate_rule_package(tampered)
    inventory = build_audit_inventory(tampered)

    assert _result(report, "package_digest").passed is False
    assert inventory.validation.is_valid is False


def test_validation_rejects_undeclared_variables_and_unlinked_ranges(
    synthetic_package: RulePackage,
) -> None:
    formula = synthetic_package.formulas[0]
    undeclared = synthetic_package.model_copy(
        update={"formulas": (formula.model_copy(update={"expression": Variable(name="missing")}),)}
    )
    unlinked = synthetic_package.model_copy(
        update={
            "formulas": (
                formula.model_copy(
                    update={
                        "supported_ranges": (
                            formula.supported_ranges[0].model_copy(update={"variable": "missing"}),
                        )
                    }
                ),
            )
        }
    )

    assert _result(validate_rule_package(undeclared), "formula_parameters").passed is False
    assert _result(validate_rule_package(unlinked), "range_linkage").passed is False


def test_validation_rejects_undeclared_variable_nested_under_power_base(
    synthetic_package: RulePackage,
) -> None:
    formula = synthetic_package.formulas[0]
    undeclared = synthetic_package.model_copy(
        update={
            "formulas": (
                formula.model_copy(
                    update={"expression": Power(base=Variable(name="missing"), numerator=2)}
                ),
            )
        }
    )

    assert _result(validate_rule_package(undeclared), "formula_parameters").passed is False


@pytest.mark.parametrize(
    ("alternative", "result_code"),
    [
        (
            lambda formula: ParameterSet(
                id="empty",
                parameters=(),
                source=formula.source,
            ),
            "formula_parameters",
        ),
        (
            lambda formula: ParameterSet(
                id="wrong-unit",
                parameters=(
                    Parameter(
                        name="voltage",
                        unit="kV",
                        minimum=0,
                        maximum=20,
                    ),
                ),
                source=formula.source,
            ),
            "range_linkage",
        ),
    ],
)
def test_each_parameter_set_alternative_must_independently_satisfy_formula(
    synthetic_package: RulePackage, alternative: object, result_code: str
) -> None:
    formula = synthetic_package.formulas[0]
    changed = formula.model_copy(
        update={"parameter_sets": (*formula.parameter_sets, alternative(formula))}
    )
    package = synthetic_package.model_copy(update={"formulas": (changed,)})

    assert _result(validate_rule_package(package), result_code).passed is False


def test_interpolation_requires_table_linear_permission(
    synthetic_package: RulePackage,
) -> None:
    table = synthetic_package.tables[0]
    package = synthetic_package.model_copy(
        update={"tables": (table.model_copy(update={"interpolation": "none"}),)}
    )

    assert _result(validate_rule_package(package), "formula_tables").passed is False


def test_validation_rejects_ambiguous_interpolation_and_non_unique_axes(
    synthetic_package: RulePackage,
) -> None:
    formula = synthetic_package.formulas[0]
    expression = formula.expression
    interpolation = expression.if_false.operands[2]
    assert interpolation.op == "linear_interpolate"
    ambiguous_expression = expression.model_copy(
        update={
            "if_false": expression.if_false.model_copy(
                update={
                    "operands": (
                        *expression.if_false.operands[:2],
                        interpolation.model_copy(update={"column": None}),
                    )
                }
            )
        }
    )
    ambiguous = synthetic_package.model_copy(
        update={"formulas": (formula.model_copy(update={"expression": ambiguous_expression}),)}
    )
    table = synthetic_package.tables[0]
    duplicate_axis = synthetic_package.model_copy(
        update={
            "tables": (
                table.model_copy(
                    update={
                        "row_axis": table.row_axis.model_copy(
                            update={"values": (Literal(value=0).value,) * 2}
                        )
                    }
                ),
            )
        }
    )

    assert _result(validate_rule_package(ambiguous), "formula_tables").passed is False
    assert _result(validate_rule_package(duplicate_axis), "package_structure").passed is False


@pytest.mark.parametrize(
    "location",
    ["table", "formula", "range", "parameter_set", "mapping", "cell"],
)
def test_validation_rejects_incomplete_source_locators(
    synthetic_package: RulePackage, location: str
) -> None:
    table = synthetic_package.tables[0]
    formula = synthetic_package.formulas[0]
    mapping = synthetic_package.mappings[0]
    if location == "cell":
        cells = (
            table.cells[0].model_copy(
                update={"source": table.cells[0].source.model_copy(update={"row": None})}
            ),
            *table.cells[1:],
        )
        package = synthetic_package.model_copy(
            update={"tables": (table.model_copy(update={"cells": cells}),)}
        )
    elif location in {"table", "range"}:
        if location == "table":
            changed = table.model_copy(
                update={"source": table.source.model_copy(update={"clause": None})}
            )
        else:
            changed = table.model_copy(
                update={
                    "supported_ranges": (
                        table.supported_ranges[0].model_copy(
                            update={
                                "source": table.supported_ranges[0].source.model_copy(
                                    update={"clause": None}
                                )
                            }
                        ),
                    )
                }
            )
        package = synthetic_package.model_copy(update={"tables": (changed,)})
    elif location in {"formula", "parameter_set"}:
        if location == "formula":
            changed_formula = formula.model_copy(
                update={"source": formula.source.model_copy(update={"clause": None})}
            )
        else:
            changed_formula = formula.model_copy(
                update={
                    "parameter_sets": (
                        formula.parameter_sets[0].model_copy(
                            update={
                                "source": formula.parameter_sets[0].source.model_copy(
                                    update={"clause": None}
                                )
                            }
                        ),
                    )
                }
            )
        package = synthetic_package.model_copy(update={"formulas": (changed_formula,)})
    else:
        package = synthetic_package.model_copy(
            update={
                "mappings": (
                    mapping.model_copy(
                        update={"source": mapping.source.model_copy(update={"clause": None})}
                    ),
                )
            }
        )

    assert _result(validate_rule_package(package), "source_references").passed is False


def test_owner_note_does_not_replace_table_or_figure_locator(
    synthetic_package: RulePackage,
) -> None:
    table = synthetic_package.tables[0]
    source = table.source.model_copy(update={"table": None, "figure": None})
    package = synthetic_package.model_copy(
        update={"tables": (table.model_copy(update={"source": source}),)}
    )

    assert _result(validate_rule_package(package), "source_references").passed is False


def test_cell_table_coordinates_do_not_replace_clause_locator(
    synthetic_package: RulePackage,
) -> None:
    table = synthetic_package.tables[0]
    first = table.cells[0]
    cells = (
        first.model_copy(update={"source": first.source.model_copy(update={"clause": None})}),
        *table.cells[1:],
    )
    package = synthetic_package.model_copy(
        update={"tables": (table.model_copy(update={"cells": cells}),)}
    )

    assert _result(validate_rule_package(package), "source_references").passed is False


def test_parameter_set_source_is_required(package_dict: dict[str, object]) -> None:
    package_dict["formulas"][0]["parameter_sets"][0]["source"] = None

    with pytest.raises(RulePackageError, match="source"):
        RulePackage.model_validate(package_dict)


def _result(report: ValidationReport, code: str) -> ValidationResult:
    return next(result for result in report.results if result.code == code)
