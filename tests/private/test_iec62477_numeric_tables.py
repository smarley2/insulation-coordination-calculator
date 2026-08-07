from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    approve_draft,
    is_fully_resolved,
)
from insulation_coordination.rules.importer.extract import _REQUIRED_RECIPES, extract_draft
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.review import (
    accept_equation_mapping,
    accept_raw_table,
    build_reviewed_draft,
    unresolved_equation_items,
    unresolved_mapping_items,
)

pytestmark = pytest.mark.private_standard


@pytest.fixture(scope="module")
def draft(supplied_standards: dict[str, Path]):
    return extract_draft(tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES)))


def test_manifest_lists_three_distinct_source_documents(draft) -> None:
    documents = draft.manifest.source_documents
    assert len(documents) == 3
    assert len({document.sha256 for document in documents}) == 3
    assert ("IEC 62477-1", "2022") in {
        (document.standard, document.edition) for document in documents
    }


def test_table_seven_and_the_altitude_tables_are_extracted(draft) -> None:
    grid_ids = {grid.id for grid in draft.raw_grids}
    assert f"raw-{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac" in grid_ids
    assert f"raw-{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc" in grid_ids
    assert f"raw-{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac" in grid_ids
    assert f"raw-{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.dc" in grid_ids
    assert f"raw-{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e1" in grid_ids
    assert f"raw-{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e2" in grid_ids


def test_every_62477_cell_carries_full_provenance(draft) -> None:
    matched = False
    for grid in draft.raw_grids:
        if not grid.id.startswith("raw-iec62477_2022."):
            continue
        matched = True
        for cell in grid.cells:
            assert cell.source.standard == "IEC 62477-1"
            assert cell.source.edition == "2022"
            assert cell.source.table is not None
            assert cell.source.clause is not None
            assert cell.source.note is not None
    assert matched


def test_the_two_table_seven_grids_hold_different_data(draft) -> None:
    impulse, tov = (
        next(grid for grid in draft.raw_grids if grid.id == grid_id)
        for grid_id in (
            f"raw-{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac",
            f"raw-{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac",
        )
    )
    impulse_data = tuple(cell.value for cell in impulse.cells if cell.role == "data")
    tov_data = tuple(cell.value for cell in tov.cells if cell.role == "data")
    assert impulse_data
    assert tov_data
    assert impulse_data != tov_data


def test_extraction_is_reproducible(supplied_standards: dict[str, Path], draft) -> None:
    repeated = extract_draft(
        tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES))
    )
    assert repeated.checksums == draft.checksums


def test_correcting_one_table_seven_grid_without_its_pair_is_refused(draft) -> None:
    """The AC and DC specs both re-extract Table 7's shared overvoltage-category

    columns from the same physical PDF cells. Retyping one copy without retyping the
    other must not produce an approved package holding two different values for the
    same source cell.
    """
    ac_grid_id = f"raw-{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac"
    ac_grid = next(grid for grid in draft.raw_grids if grid.id == ac_grid_id)
    # Column 0 is the AC-only system-voltage axis; column 1 is the first shared
    # overvoltage-category column, present in both the AC and DC grids.
    shared_cell = next(
        cell
        for cell in ac_grid.cells
        if cell.role == "data" and cell.column == 1 and cell.value is not None
    )
    bogus_value = shared_cell.value + Decimal(1)

    reviewed = draft
    for grid in draft.raw_grids:
        corrections = (
            {(shared_cell.row, shared_cell.column): bogus_value}
            if grid.id == ac_grid_id
            else {}
        )
        reviewed = accept_raw_table(
            reviewed,
            grid_id=grid.id,
            corrections=corrections,
            actor="Private fixture reviewer",
            notes="Verified against supplied PDF",
        )
    reviewed = accept_equation_mapping(
        reviewed,
        equation_ids=tuple(item.semantic_id for item in unresolved_equation_items(reviewed)),
        mapping_ids=tuple(item.semantic_id for item in unresolved_mapping_items(reviewed)),
        actor="Private fixture reviewer",
        notes="Verified equations and mappings against supplied PDF",
    )
    built = build_reviewed_draft(
        reviewed,
        actor="Private fixture reviewer",
        notes="Projected accepted IEC artifacts",
    )
    assert is_fully_resolved(built)

    with pytest.raises(ApprovalError, match="disagree"):
        approve_draft(built, approver="Private fixture reviewer", notes="Approval attempt")
