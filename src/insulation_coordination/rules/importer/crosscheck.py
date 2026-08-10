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
    return {cell_id(cell): cell for cell in grid.cells if cell.role == "data"}


def _comparable(cell: RawGridCell) -> Decimal | str:
    """What equality means for one cell.

    A parsed number compares as a number, so a difference in printed form is not read as
    a difference in requirement. A cell the extractor could not parse compares as its
    stripped source text, so an unparsed cell can still be proven identical rather than
    silently skipped.
    """
    return cell.value if cell.value is not None else cell.raw_text.strip()


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
        rule_id
        for rule_id in (spec.source_rule_id, spec.target_rule_id)
        if rule_id not in grids
    )
    if absent:
        return None, (
            _item(
                spec,
                "CROSS_STANDARD_GRID_MISSING",
                f"draft holds no grid for {', '.join(absent)}",
            ),
        )
    source_grid = grids[spec.source_rule_id]
    target_grid = grids[spec.target_rule_id]
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
                    f"source cell {source_id} is absent from {spec.source_rule_id}",
                )
            )
            continue
        if target_cell is None:
            items.append(
                _item(
                    spec,
                    "CROSS_STANDARD_TARGET_MISSING",
                    f"target cell {target_id} is absent from {spec.target_rule_id}",
                )
            )
            continue
        if _comparable(source_cell) != _comparable(target_cell):
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
