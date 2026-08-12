"""Prove or refute that one standard's grid says the same thing as another's.

IEC 62477-1 reproduces spacing requirements that the approved IEC 60664-1 and
IEC 60664-4 rules already carry. A package must not hold two copies of the same
requirement, and must not assume the two documents agree either: similar numbers are not
proof of equivalence. So a check either proves every mapped cell equal and yields a
mapping, or it blocks with one review item per divergence and leaves both rules standing
until a maintainer rules on them.

Which cell answers which depends on how the two documents lay their tables out. Where the
rows align, a check names the pairs outright. Where they do not -- one document printing a
subset of the other's rows, in another unit -- the check pairs rows by the axis value they
carry and declares, with a reason, whatever the target standard has no counterpart for.

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
from insulation_coordination.rules.importer.identify import (
    CrossStandardAxisMatchSpec,
    CrossStandardCheckSpec,
)


def cell_id(cell: RawGridCell) -> str:
    """The stable identifier of one data cell inside its grid."""

    return f"{cell.logical_row}/{cell.logical_column}"


def _by_coordinate(grid: RawGrid) -> dict[tuple[int, str], RawGridCell]:
    """Every cell that occupies a logical coordinate, blanks included.

    A blank inside the data region carries meaning -- both of these tables step their
    requirements, leaving cells empty where a row does not apply -- so a blank compares
    against a blank as agreement, and against a value as a divergence. Dropping blanks
    would silently narrow the comparison to the cells that happen to be filled in.
    """
    cells: dict[tuple[int, str], RawGridCell] = {}
    for cell in grid.cells:
        if cell.logical_row is not None and cell.logical_column is not None:
            cells[(cell.logical_row, cell.logical_column)] = cell
    return cells


def _data_cells(grid: RawGrid) -> dict[str, RawGridCell]:
    """The same cells, keyed the way an explicit cell map names them."""

    return {f"{row}/{column}": cell for (row, column), cell in _by_coordinate(grid).items()}


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


def _outcome(
    spec: CrossStandardCheckSpec,
    items: tuple[ImportReviewItem, ...],
) -> tuple[CompatibilityMapping | None, tuple[ImportReviewItem, ...]]:
    """One mapping when nothing diverged, otherwise the divergences and no mapping."""

    if items:
        return None, items
    mapping = CompatibilityMapping(
        id=spec.id,
        source_rule_id=spec.source_rule_id,
        target_rule_id=spec.target_rule_id,
        approved=False,
        source=spec.source,
        notes=_claim_notes(spec),
    )
    return mapping, ()


def _axis_values(
    cells: Mapping[tuple[int, str], RawGridCell],
    column: str,
) -> tuple[dict[int, Decimal], tuple[int, ...]]:
    """Each row's axis value, and the rows whose axis cell holds no readable number."""

    values: dict[int, Decimal] = {}
    unreadable: list[int] = []
    for (row, name), cell in cells.items():
        if name != column:
            continue
        if cell.value is None:
            unreadable.append(row)
        else:
            values[row] = cell.value
    return values, tuple(sorted(unreadable))


def _matched_columns(
    spec: CrossStandardCheckSpec,
    match: CrossStandardAxisMatchSpec,
    source_cells: Mapping[tuple[int, str], RawGridCell],
    target_cells: Mapping[tuple[int, str], RawGridCell],
) -> tuple[ImportReviewItem, ...]:
    """Check the declaration against the columns the two grids actually carry."""

    items: list[ImportReviewItem] = []
    source_columns = {column for _row, column in source_cells}
    target_columns = {column for _row, column in target_cells}
    declared = {
        match.source_axis_column,
        *(source for source, _target in match.column_pairs),
        *(source for source, _reason in match.uncompared_source_columns),
    }
    for column in sorted(source_columns - declared):
        items.append(
            _item(
                spec,
                "CROSS_STANDARD_COLUMN_UNDECLARED",
                f"source column {column} is neither paired with a target column nor "
                "declared as having no counterpart in the target standard",
            )
        )
    for column in sorted(declared - source_columns):
        items.append(
            _item(
                spec,
                "CROSS_STANDARD_SOURCE_MISSING",
                f"source column {column} is absent from {spec.source_rule_id}",
            )
        )
    for column in sorted(
        {match.target_axis_column, *(target for _source, target in match.column_pairs)}
        - target_columns
    ):
        items.append(
            _item(
                spec,
                "CROSS_STANDARD_TARGET_MISSING",
                f"target column {column} is absent from {spec.target_rule_id}",
            )
        )
    return tuple(items)


def _compare_by_axis_value(
    source_grid: RawGrid,
    target_grid: RawGrid,
    spec: CrossStandardCheckSpec,
    match: CrossStandardAxisMatchSpec,
) -> tuple[ImportReviewItem, ...]:
    """Pair rows by the axis value they carry, then compare the declared columns.

    Only what the check declares is left out: an unmatched row it did not name blocks,
    and so does a named row the target does turn out to carry, because an exclusion that
    is not needed understates what the two standards agree on.
    """
    source_cells = _by_coordinate(source_grid)
    target_cells = _by_coordinate(target_grid)
    items: list[ImportReviewItem] = list(_matched_columns(spec, match, source_cells, target_cells))
    source_axis, source_unreadable = _axis_values(source_cells, match.source_axis_column)
    target_axis, target_unreadable = _axis_values(target_cells, match.target_axis_column)
    for rule_id, rows in (
        (spec.source_rule_id, source_unreadable),
        (spec.target_rule_id, target_unreadable),
    ):
        items.extend(
            _item(
                spec,
                "CROSS_STANDARD_AXIS_UNREADABLE",
                f"row {row} of {rule_id} carries no readable axis value, so it cannot be "
                "paired by what it is about",
            )
            for row in rows
        )
    target_row_of: dict[Decimal, int] = {}
    for row, value in sorted(target_axis.items()):
        if value in target_row_of:
            items.append(
                _item(
                    spec,
                    "CROSS_STANDARD_TARGET_AXIS_AMBIGUOUS",
                    f"rows {target_row_of[value]} and {row} of {spec.target_rule_id} "
                    "repeat one axis value, so a source row cannot be paired with one "
                    "of them",
                )
            )
        else:
            target_row_of[value] = row

    excluded = {row for row, _reason in match.uncompared_source_rows}
    for row in sorted(excluded - set(source_axis)):
        items.append(
            _item(
                spec,
                "CROSS_STANDARD_SOURCE_MISSING",
                f"row {row} is declared as having no counterpart but {spec.source_rule_id} "
                "has no such row",
            )
        )
    for source_row, axis_value in sorted(source_axis.items()):
        target_row = target_row_of.get(axis_value * match.axis_value_scale)
        if target_row is None:
            if source_row not in excluded:
                items.append(
                    _item(
                        spec,
                        "CROSS_STANDARD_AXIS_ROW_UNMATCHED",
                        f"source row {source_row} has no row of the same axis value in "
                        f"{spec.target_rule_id}; either the two standards differ there or "
                        "the check must declare the row as having no counterpart",
                    )
                )
            continue
        differences = tuple(
            _item(
                spec,
                "CROSS_STANDARD_VALUE_DIVERGENCE",
                f"source cell {source_row}/{source_column} and target cell "
                f"{target_row}/{target_column} differ; a maintainer decides whether the "
                "two standards are equivalent here",
            )
            for source_column, target_column in match.column_pairs
            if _differs(
                source_cells.get((source_row, source_column)),
                target_cells.get((target_row, target_column)),
                spec.no_requirement_tokens,
            )
        )
        if source_row not in excluded:
            items.extend(differences)
        elif not differences:
            # The target does carry this row, and carries the same requirement on it. An
            # exclusion is then understating what the two standards agree on, which is as
            # misleading as claiming an agreement that is not there.
            items.append(
                _item(
                    spec,
                    "CROSS_STANDARD_ROW_EXCLUSION_UNNEEDED",
                    f"source row {source_row} is declared as having no counterpart, but "
                    f"row {target_row} of {spec.target_rule_id} carries the same axis "
                    "value and agrees on every compared column",
                )
            )
    return tuple(items)


def _differs(
    source_cell: RawGridCell | None,
    target_cell: RawGridCell | None,
    no_requirement_tokens: tuple[str, ...],
) -> bool:
    """Whether one pair of cells disagrees.

    A column absent from either grid is already reported once against that grid, rather
    than once per row, so an absent cell is not a difference here.
    """
    if source_cell is None or target_cell is None:
        return False
    return _comparable(source_cell, no_requirement_tokens) != _comparable(
        target_cell, no_requirement_tokens
    )


def _claim_notes(spec: CrossStandardCheckSpec) -> str:
    """The mapping's notes, naming everything the equivalence claim leaves out.

    The claim covers the cells that were compared, and nothing else. Recording the
    exclusions on the mapping keeps that visible to whoever reads the package, rather than
    only to whoever reads the recipe.
    """
    if spec.axis_match is None:
        return spec.notes
    excluded = (
        *(
            f"excluded from this claim: source column {column} -- {reason}"
            for column, reason in spec.axis_match.uncompared_source_columns
        ),
        *(
            f"excluded from this claim: source row {row} -- {reason}"
            for row, reason in spec.axis_match.uncompared_source_rows
        ),
    )
    return "\n".join(line for line in (spec.notes, *excluded) if line)


def compare_across_standards(
    grids: Mapping[str, RawGrid],
    spec: CrossStandardCheckSpec,
) -> tuple[CompatibilityMapping | None, tuple[ImportReviewItem, ...]]:
    """Compare two grids cell by cell; map them only when every mapped pair agrees."""

    absent = tuple(
        grid_id for grid_id in (spec.source_grid_id, spec.target_grid_id) if grid_id not in grids
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

    if spec.axis_match is not None:
        items = list(_compare_by_axis_value(source_grid, target_grid, spec, spec.axis_match))
        return _outcome(spec, tuple(items))

    source_cells = _data_cells(source_grid)
    target_cells = _data_cells(target_grid)
    items = []
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
    return _outcome(spec, tuple(items))


__all__ = [
    "CrossStandardAxisMatchSpec",
    "CrossStandardCheckSpec",
    "cell_id",
    "compare_across_standards",
]
