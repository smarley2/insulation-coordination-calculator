from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import RulePackage, RulePackageError
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.extract import extract_draft
from insulation_coordination.ui.rules_manager import (
    ImportResult,
    RulesManagerWindow,
)
from tests.fixtures.synthetic_pdf import create_geometry_pdf
from tests.fixtures.synthetic_rules import synthetic_rule_package as _build_synthetic_package
from tests.rules.test_importer import _test_recipes


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


def test_rules_manager_exposes_draft_extraction(qtbot, rules_manager):
    assert rules_manager._extract_draft_button.isEnabled()
    assert rules_manager._review_curves_button.text() == "Review manual curves…"


def test_draft_identity_shows_all_three_required_standards(
    qtbot, rules_manager, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(recipe_registry, "RECIPES", _test_recipes())
    part1 = tmp_path / "part1.pdf"
    part4 = tmp_path / "part4.pdf"
    part62477 = tmp_path / "part62477.pdf"
    create_geometry_pdf(
        part1,
        standard="IEC 60664-1",
        edition="2020",
        edition_anchor="Edition 3.0 2020-05",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
    )
    create_geometry_pdf(
        part4,
        standard="IEC 60664-4",
        edition="2005",
        edition_anchor="first edition 2005",
        topic_anchor="synthetic high-frequency geometry",
        table_anchor="Table S4",
    )
    create_geometry_pdf(
        part62477,
        standard="IEC 62477-1",
        edition="2022",
        edition_anchor="Edition 2.0 2022-05",
        topic_anchor="synthetic power conversion geometry",
        table_anchor="Table S9",
    )

    rules_manager.set_draft(extract_draft((part1, part4, part62477)))

    assert "IEC 60664-1" in rules_manager.identity_text
    assert "IEC 60664-4" in rules_manager.identity_text
    assert "IEC 62477-1" in rules_manager.identity_text
    # The standards lines are extra detail; a maintainer must still see, in the same
    # label, that this draft has not been approved.
    assert "unapproved; review required" in rules_manager.identity_text


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
    assert rules_manager.identity_text.startswith(
        str(rules_manager.active_package.manifest.package_id)
    )

    original = result.path.read_bytes()
    altered = tmp_path / "altered.icrules"
    altered.write_bytes(original[:-1] + (b"\x00" if original[-1:] != b"\x00" else b"\x01"))
    with pytest.raises(RulePackageError):
        rules_manager.import_package(altered)


def test_audit_tree_lists_the_new_rule_sections(
    qtbot, rules_manager, synthetic_rule_package: RulePackage
) -> None:
    rules_manager.set_package(synthetic_rule_package)
    labels = {
        rules_manager._tree.topLevelItem(index).text(0)
        for index in range(rules_manager._tree.topLevelItemCount())
    }
    assert {"Decisions", "Procedures", "Guidance", "Curves"} <= labels


def test_audit_tree_counts_and_lists_curves(
    qtbot, rules_manager, synthetic_rule_package: RulePackage
) -> None:
    rules_manager.set_package(synthetic_rule_package)
    sections = {
        rules_manager._tree.topLevelItem(index).text(0):
        rules_manager._tree.topLevelItem(index)
        for index in range(rules_manager._tree.topLevelItemCount())
    }

    assert rules_manager.audit_curve_count == 1
    assert sections["Curves"].childCount() == 1
    assert synthetic_rule_package.curves[0].id in sections["Curves"].child(0).text(0)


def test_audit_tree_decision_procedure_guidance_children_show_id_and_source(
    qtbot, rules_manager, synthetic_rule_package: RulePackage
) -> None:
    rules_manager.set_package(synthetic_rule_package)
    tree = rules_manager._tree
    sections = {
        tree.topLevelItem(index).text(0): tree.topLevelItem(index)
        for index in range(tree.topLevelItemCount())
    }
    decision = synthetic_rule_package.decisions[0]
    procedure = synthetic_rule_package.procedures[0]
    guidance = synthetic_rule_package.guidance[0]

    assert sections["Decisions"].childCount() == len(synthetic_rule_package.decisions)
    assert decision.id in sections["Decisions"].child(0).text(0)
    assert decision.source.standard in sections["Decisions"].child(0).text(0)

    assert sections["Procedures"].childCount() == len(synthetic_rule_package.procedures)
    assert procedure.id in sections["Procedures"].child(0).text(0)

    assert sections["Guidance"].childCount() == len(synthetic_rule_package.guidance)
    assert guidance.id in sections["Guidance"].child(0).text(0)


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
