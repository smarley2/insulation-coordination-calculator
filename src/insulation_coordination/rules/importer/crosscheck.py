"""Prove or refute that one standard's grid says the same thing as another's.

IEC 62477-1 reproduces spacing requirements that the approved IEC 60664-1 and
IEC 60664-4 rules already carry. A package must not hold two copies of the same
requirement, and must not assume the two documents agree either: similar numbers are not
proof of equivalence. So a check either proves every mapped cell equal and yields a
mapping, or it blocks with one review item per divergence and leaves both rules standing
until a maintainer rules on them.

The comparison is a pure function of grids already inside the draft. It never re-reads a
PDF, so it is reproducible for a given draft and adds no source-document dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from insulation_coordination.domain.rules import CompatibilityMapping
from insulation_coordination.rules.importer.extract import (
    ImportReviewItem,
    RawGrid,
    RawGridCell,
)
from insulation_coordination.rules.importer.identify import CrossStandardCheckSpec


def cell_id(cell: RawGridCell) -> str:
    """The stable identifier of one data cell inside its grid."""

    return f"{cell.logical_row}/{cell.logical_column}"


def _data_cells(grid: RawGrid) -> dict[str, RawGridCell]:
    """Every cell that occupies a logical coordinate, blanks included.

    A blank inside the data region carries meaning -- both of these tables step their
    requirements, leaving cells empty where a row does not apply -- so a blank compares
    against a blank as agreement, and against a value as a divergence. Dropping blanks
    would silently narrow the comparison to the cells that happen to be filled in.
    """
    return {
        cell_id(cell): cell
        for cell in grid.cells
        if cell.logical_row is not None and cell.logical_column is not None
    }


#: What a cell with no parsed value and no declared marker compares as.
_NO_REQUIREMENT = "\x00no-requirement"


def _comparable(cell: RawGridCell, no_requirement_tokens: tuple[str, ...]) -> Decimal | str:
    """What equality means for one cell.

    A parsed number compares as a number, so a difference in printed form is not read as a
    difference in requirement. A cell holding nothing, or holding one of the markers the
    check declares for "no requirement here", compares equal to any other such cell. Any
    other unparsed text compares as itself, so it can only ever match the same text.
    """
    if cell.value is not None:
        return cell.value
    text = cell.raw_text.strip()
    if not text or text in no_requirement_tokens:
        return _NO_REQUIREMENT
    return text


def _item(spec: CrossStandardCheckSpec, code: str, detail: str) -> ImportReviewItem:
    return ImportReviewItem(
        code=code,
        semantic_id=spec.id,
        kind="mapping",
        source=spec.source,
        expected_contract=detail,
    )


def compare_across_standards(
    grids: Mapping[str, RawGrid],
    spec: CrossStandardCheckSpec,
) -> tuple[CompatibilityMapping | None, tuple[ImportReviewItem, ...]]:
    """Compare two grids cell by cell; map them only when every mapped pair agrees."""

    absent = tuple(
        grid_id
        for grid_id in (spec.source_grid_id, spec.target_grid_id)
        if grid_id not in grids
    )
    if absent:
        return None, (
            _item(
                spec,
                "CROSS_STANDARD_GRID_MISSING",
                f"draft holds no grid for {', '.join(absent)}",
            ),
        )
    source_grid = grids[spec.source_grid_id]
    target_grid = grids[spec.target_grid_id]
    if source_grid.target_unit != target_grid.target_unit:
        return None, (
            _item(
                spec,
                "CROSS_STANDARD_UNIT_MISMATCH",
                "the two grids are expressed in different units, so equal numbers would "
                "not prove equal requirements",
            ),
        )

    source_cells = _data_cells(source_grid)
    target_cells = _data_cells(target_grid)
    items: list[ImportReviewItem] = []
    for source_id, target_id in spec.cell_map:
        source_cell = source_cells.get(source_id)
        target_cell = target_cells.get(target_id)
        if source_cell is None:
            items.append(
                _item(
                    spec,
                    "CROSS_STANDARD_SOURCE_MISSING",
                    f"source cell {source_id} is absent from {spec.source_grid_id}",
                )
            )
            continue
        if target_cell is None:
            items.append(
                _item(
                    spec,
                    "CROSS_STANDARD_TARGET_MISSING",
                    f"target cell {target_id} is absent from {spec.target_grid_id}",
                )
            )
            continue
        tokens = spec.no_requirement_tokens
        if _comparable(source_cell, tokens) != _comparable(target_cell, tokens):
            items.append(
                _item(
                    spec,
                    "CROSS_STANDARD_VALUE_DIVERGENCE",
                    f"source cell {source_id} and target cell {target_id} differ; a "
                    "maintainer decides whether the two standards are equivalent here",
                )
            )
    if items:
        return None, tuple(items)
    mapping = CompatibilityMapping(
        id=spec.id,
        source_rule_id=spec.source_rule_id,
        target_rule_id=spec.target_rule_id,
        approved=False,
        source=spec.source,
        notes=spec.notes,
    )
    return mapping, ()


__all__ = [
    "CrossStandardCheckSpec",
    "cell_id",
    "compare_across_standards",
]
