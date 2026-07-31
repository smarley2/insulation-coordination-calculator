from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import RulePackage, RulePackageError
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.ui.rules_manager import (
    ImportResult,
    RulesManagerWindow,
)
from tests.fixtures.synthetic_rules import synthetic_rule_package as _build_synthetic_package


def _installed_dir(tmp_path: Path) -> Path:
    return tmp_path / "rules"


@pytest.fixture
def rules_manager(qtbot, tmp_path: Path) -> RulesManagerWindow:
    window = RulesManagerWindow(rules_dir=_installed_dir(tmp_path))
    qtbot.addWidget(window)
    return window


@pytest.fixture
def synthetic_rule_package() -> RulePackage:
    return _build_synthetic_package()


@pytest.fixture
def approved_icrules(tmp_path: Path) -> Path:
    path = tmp_path / "approved.icrules"
    write_rule_package(path, _build_synthetic_package())
    return path


def test_imported_package_is_usable_without_pdfs(
    qtbot, rules_manager, approved_icrules: Path
) -> None:
    rules_manager.import_package(approved_icrules)
    assert rules_manager.active_package is not None
    assert rules_manager.active_package.manifest.approved is True
    assert rules_manager.pdf_required is False


def test_audit_tree_enumerates_every_table_cell_and_formula(
    qtbot, rules_manager, synthetic_rule_package: RulePackage
) -> None:
    rules_manager.set_package(synthetic_rule_package)
    assert rules_manager.audit_cell_count == synthetic_rule_package.total_cell_count
    assert rules_manager.audit_formula_count == len(synthetic_rule_package.formulas) * 22


def test_import_copies_exact_package_and_rejects_altered_copy(
    qtbot, rules_manager, approved_icrules: Path, tmp_path: Path
) -> None:
    result = rules_manager.import_package(approved_icrules)
    assert isinstance(result, ImportResult)
    assert result.path is not None
    assert result.path.exists()
    loaded = load_rule_package(result.path)
    assert loaded.manifest.package_id == rules_manager.active_package.manifest.package_id
    assert loaded.package_sha256 == rules_manager.active_package.package_sha256
    assert rules_manager.identity_text.startswith(str(rules_manager.active_package.manifest.package_id))

    original = result.path.read_bytes()
    altered = tmp_path / "altered.icrules"
    altered.write_bytes(original[:-1] + (b"\x00" if original[-1:] != b"\x00" else b"\x01"))
    with pytest.raises(RulePackageError):
        rules_manager.import_package(altered)


def test_audit_browser_sections_and_semantic_search(
    qtbot, rules_manager, synthetic_rule_package: RulePackage
) -> None:
    rules_manager.set_package(synthetic_rule_package)
    rules_manager.search("synthetic-distance")
    matches = rules_manager.search_matches
    assert len(matches) >= 1
    assert "synthetic-distance" in matches[0]


def test_inventory_export_writes_csv_and_json(
    qtbot, rules_manager, synthetic_rule_package: RulePackage, tmp_path: Path
) -> None:
    rules_manager.set_package(synthetic_rule_package)
    destination = tmp_path / "export"
    destination.mkdir()
    rules_manager.export_inventory(destination)
    assert (destination / "audit-inventory.json").exists()
    assert (destination / "table-synthetic-distance.csv").exists()
    with (destination / "table-synthetic-distance.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == rules_manager.audit_cell_count
    exported = json.loads((destination / "audit-inventory.json").read_text(encoding="utf-8"))
    assert exported["table_cell_count"] == rules_manager.audit_cell_count


def test_approval_button_requires_approved_package(
    qtbot, rules_manager, synthetic_rule_package: RulePackage
) -> None:
    unapproved = synthetic_rule_package.model_copy(
        update={
            "manifest": synthetic_rule_package.manifest.model_copy(
                update={"approved": False, "compatible": False}
            ),
            "mappings": tuple(
                mapping.model_copy(update={"approved": False})
                for mapping in synthetic_rule_package.mappings
            ),
        }
    )
    rules_manager.set_package(unapproved)
    assert rules_manager.export_approved_enabled is False
    rules_manager.set_package(synthetic_rule_package)
    assert rules_manager.export_approved_enabled is True
    assert rules_manager.total_cell_count == rules_manager.audit_cell_count
    assert Decimal("1.00") in rules_manager.cell_values
