from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.audit import (
    build_audit_inventory,
    export_inventory_json,
    export_table_csv,
)
from insulation_coordination.rules.validation import validate_rule_package


def test_audit_inventory_enumerates_all_package_content(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    archive_path = tmp_path / "approved.icrules"
    write_rule_package(archive_path, synthetic_package)
    loaded = load_rule_package(archive_path)

    inventory = build_audit_inventory(loaded)

    assert inventory.table_cell_count == 4
    assert inventory.formula_node_count == 21
    assert inventory.mapping_count == 1
    assert inventory.parameter_set_count == 1
    assert inventory.supported_range_count == 2
    assert inventory.source_reference_count == 10
    assert inventory.checksum_count == 4
    assert inventory.approval_record_count == 1
    assert len(inventory.table_cells) == inventory.table_cell_count
    assert len(inventory.formula_nodes) == inventory.formula_node_count
    assert inventory.formula_nodes[0].node == loaded.formulas[0].expression
    assert len(inventory.source_references) == inventory.source_reference_count
    assert inventory.validation.is_valid is True


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
    assert exported["formula_node_count"] == 21
    assert exported["validation"]["is_valid"] is True
    assert b"%PDF" not in archive_path.read_bytes()
    assert b"%PDF" not in inventory_path.read_bytes()


def test_export_unknown_table_is_rejected(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    with pytest.raises(KeyError, match="missing"):
        export_table_csv(synthetic_package, "missing", tmp_path / "missing.csv")


def test_validation_rejects_unapproved_or_incompatible_packages(
    synthetic_package: RulePackage,
) -> None:
    unapproved = synthetic_package.model_copy(
        update={
            "manifest": synthetic_package.manifest.model_copy(update={"approved": False})
        }
    )
    incompatible = synthetic_package.model_copy(
        update={
            "manifest": synthetic_package.manifest.model_copy(update={"compatible": False})
        }
    )

    assert validate_rule_package(unapproved).is_valid is False
    assert validate_rule_package(incompatible).is_valid is False
