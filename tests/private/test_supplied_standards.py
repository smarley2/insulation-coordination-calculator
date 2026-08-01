from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import DraftRulePackage, RulePackage
from insulation_coordination.rules.importer.extract import ExtractionError, extract_draft
from insulation_coordination.rules.importer.identify import (
    StandardIdentificationError,
    identify_standard,
)
from insulation_coordination.rules.importer.review import (
    accept_equation_mapping,
    accept_raw_table,
    build_reviewed_draft,
    unresolved_equation_items,
    unresolved_mapping_items,
)
from insulation_coordination.rules.validation import validate_rule_package

pytestmark = pytest.mark.private_standard

_FILENAMES = (
    "IEC 60664-1 2020 isbn13 9782832282878.pdf",
    "IEC 60664-4 2005 -- isbn13 9782831881973.pdf",
)


def _private_locations() -> tuple[tuple[Path, Path], Path]:
    repository = Path(__file__).parents[2]
    standards = Path(os.environ.get("ICC_PRIVATE_STANDARDS_DIR", repository / "standards"))
    private_rules = Path(os.environ.get("ICC_PRIVATE_RULES_DIR", repository / "private-rules"))
    return (
        (standards / _FILENAMES[0], standards / _FILENAMES[1]),
        private_rules / "supplied-standards-draft.sha256",
    )


def _review_digest(draft: DraftRulePackage) -> str:
    payload = draft.model_dump(mode="json")
    manifest = payload["manifest"]
    stable = {
        "source_documents": manifest["source_documents"],
        "tables": payload["tables"],
        "formulas": payload["formulas"],
        "mappings": payload["mappings"],
        "review_items": payload["review_items"],
        "raw_grids": payload["raw_grids"],
        "extracted_equations": payload["extracted_equations"],
    }
    canonical = json.dumps(
        stable,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def test_supplied_standards_match_human_reviewed_draft(
    caplog: pytest.LogCaptureFixture,
) -> None:
    paths, golden_path = _private_locations()
    missing = tuple(path.name for path in paths if not path.is_file())
    if missing:
        pytest.skip("licensed IEC PDFs are unavailable")

    try:
        with caplog.at_level(logging.ERROR, logger="pypdf._page"):
            identities = tuple(identify_standard(path) for path in paths)
            draft = extract_draft(paths)
    except (ExtractionError, StandardIdentificationError):
        pytest.fail(
            "private standard identification or structural extraction failed", pytrace=False
        )
    assert {(item.standard, item.edition) for item in identities} == {
        ("IEC 60664-1", "2020"),
        ("IEC 60664-4", "2005"),
    }
    assert {grid.id for grid in draft.raw_grids} == {
        "raw-iec60664-1-f2",
        "raw-iec60664-1-f5",
        "raw-iec60664-1-f8",
        "raw-iec60664-1-f9",
        "raw-iec60664-1-a2",
        "raw-iec60664-4-table-1",
        "raw-iec60664-4-table-2",
    }
    assert {grid.id: (grid.rows, grid.columns) for grid in draft.raw_grids} == {
        "raw-iec60664-1-f2": (30, 7),
        "raw-iec60664-1-f5": (49, 10),
        "raw-iec60664-1-f8": (35, 3),
        "raw-iec60664-1-f9": (35, 2),
        "raw-iec60664-1-a2": (12, 3),
        "raw-iec60664-4-table-1": (10, 2),
        "raw-iec60664-4-table-2": (20, 8),
    }
    assert draft.review_items
    assert {item.code for item in draft.review_items} <= {
        "MANUAL_TABLE_DEFINITION_REQUIRED",
        "MANUAL_RULE_DEFINITION_REQUIRED",
        "MANUAL_MAPPING_REQUIRED",
        "MANUAL_RAW_CELL_REVIEW_REQUIRED",
    }
    assert all(
        cell.source.row is not None and cell.source.column is not None
        for grid in draft.raw_grids
        for cell in grid.cells
    )
    assert any(
        cell.qualifier is not None or cell.suffix is not None
        for grid in draft.raw_grids
        for cell in grid.cells
    )
    f5 = next(grid for grid in draft.raw_grids if grid.id == "raw-iec60664-1-f5")
    assert tuple(segment.page_number for segment in f5.segments) == (73, 74)
    assert tuple(segment.row_start for segment in f5.segments) == (0, 30)
    assert all(cell.role in {"header", "data", "blank", "note", "footnote"} for cell in f5.cells)
    assert max(cell.logical_row for cell in f5.cells if cell.logical_row is not None) == 38
    assert any(
        cell.source.note == "PDF page 74" and cell.logical_row is not None for cell in f5.cells
    )
    assert any(
        " " in cell.raw_text.strip() and cell.value is not None
        for cell in f5.cells
        if cell.logical_column == "rms_voltage_v"
    )
    assert any(cell.footnotes for grid in draft.raw_grids for cell in grid.cells)
    assert {equation.id for equation in draft.extracted_equations} == {
        "iec60664-4-equation-1-critical-frequency",
        "iec60664-4-equation-2-frequency-factor",
        "iec60664-4-minimum-frequency",
        "iec60664-4-radius-criterion",
    }
    assert all(equation.parse_status == "parsed" for equation in draft.extracted_equations)
    assert all(equation.raw_text and equation.rendered for equation in draft.extracted_equations)
    assert all(
        equation.source.clause and equation.source.note for equation in draft.extracted_equations
    )
    accepted = draft
    for grid in draft.raw_grids:
        accepted = accept_raw_table(
            accepted,
            grid_id=grid.id,
            corrections={},
            actor="Private fixture reviewer",
            notes="Verified against supplied PDF",
        )
    accepted = accept_equation_mapping(
        accepted,
        equation_ids=tuple(item.semantic_id for item in unresolved_equation_items(accepted)),
        mapping_ids=tuple(item.semantic_id for item in unresolved_mapping_items(accepted)),
        actor="Private fixture reviewer",
        notes="Verified equations and mappings against supplied PDF",
    )
    built = build_reviewed_draft(
        accepted,
        actor="Private fixture reviewer",
        notes="Projected accepted IEC artifacts",
    )
    assert {table.id for table in built.tables} == {
        "iec60664-1-f2",
        "iec60664-1-f5",
        "iec60664-1-f8",
        "iec60664-1-f9",
        "iec60664-1-a2",
        "iec60664-4-table-1",
        "iec60664-4-table-2",
    }
    f5_table = next(table for table in built.tables if table.id == "iec60664-1-f5")
    assert len(f5_table.row_axis.values) == 39
    assert f5_table.row_axis.values[-1] == 63_000
    assert all(cell.source.note == "PDF page 73" for cell in f5_table.cells)
    assert all(table.row_axis.labels and table.column_axis.labels for table in built.tables)
    assert all("raw_sequence" not in str(formula.expression) for formula in built.formulas)
    expected_draft_failures = {
        "approval",
        "approval_record",
        "compatibility",
        "checksums",
        "package_digest",
    }
    package_view = RulePackage(
        manifest=draft.manifest,
        tables=draft.tables,
        formulas=draft.formulas,
        mappings=draft.mappings,
    )
    assert {
        result.code for result in validate_rule_package(package_view).results if not result.passed
    } <= expected_draft_failures
    if not golden_path.is_file():
        pytest.skip("separately human-reviewed private draft digest is unavailable")
    golden = golden_path.read_text(encoding="ascii").strip()
    assert re.fullmatch(r"[0-9a-f]{64}", golden), "private golden digest is malformed"

    assert draft.raw_grids
    assert len({grid.id for grid in draft.raw_grids}) == len(draft.raw_grids)
    assert _review_digest(draft) == golden, "private extraction differs from reviewed digest"
