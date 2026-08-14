"""Projection of a compound temporary-overvoltage cell into its two measures.

Synthetic throughout: the grid, its labels and its values are invented here. What is
pinned is the shape of the contract -- one physical cell carrying two measures of one
quantity, projected into one column axis position each, under a row axis that selects
the supply's own system voltage.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridCell,
    RawGridSegment,
    parse_compound_data_cell,
)
from insulation_coordination.rules.importer.identify import (
    CompoundQuantitySpec,
    StandardIdentity,
    TableAuditSpec,
    TableColumnSpec,
)
from insulation_coordination.rules.importer.projection import project_table

SOURCE = SourceReference(
    document_id="synthetic-compound",
    standard="SYNTHETIC",
    edition="1",
    page=3,
    table="S7",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="1" * 64,
    page_count=3,
    recipe_id="synthetic-compound",
)
MEASURES = ("rms", "peak")


def _spec(
    route: str,
    component_ids: tuple[str, ...] = MEASURES,
    *,
    projected: tuple[str, ...] = MEASURES,
) -> TableAuditSpec:
    """One route reading a compound cell into one logical column per component."""

    compound = CompoundQuantitySpec(component_ids=component_ids)
    return TableAuditSpec(
        semantic_id=route,
        source_table="S7",
        title_anchor="Synthetic table S7",
        page_number=3,
        clause="S.7",
        target_unit="V",
        expected_raw_rows=2,
        expected_raw_columns=1 + len(component_ids),
        expected_bbox=(0, 0, 10, 10),
        data_strategy="rectangle",
        expected_data_rows=2,
        expected_data_columns=1 + len(projected),
        row_axis_id="system_voltage",
        row_axis_unit="V",
        column_axis_id="tov_basis",
        column_axis_unit="1",
        assertions=("raw_value_correspondence",),
        columns=(
            TableColumnSpec(
                semantic_id="axis",
                heading="synthetic system voltage",
                source_column=0,
                role="axis",
                unit="V",
            ),
            *(
                TableColumnSpec(
                    semantic_id=f"output_{component_id}",
                    heading=f"synthetic compound output {component_id}",
                    source_column=1,
                    role="data",
                    unit="V",
                    compound_quantity=compound,
                    projected_component_id=component_id,
                )
                for component_id in projected
            ),
        ),
    )


def _grid(component_ids: tuple[str, ...] = MEASURES) -> RawGrid:
    """Two rows; the one compound cell of each row is read into both data columns."""

    cells = []
    for row, (axis, raw) in enumerate(
        (
            ("1", f"11 {component_ids[0]} / 17 {component_ids[1]}"),
            ("2", f"13 {component_ids[0]} / 19 {component_ids[1]}"),
        )
    ):
        cells.append(
            RawGridCell(
                row=row,
                column=0,
                raw_text=axis,
                role="data",
                logical_row=row,
                logical_column="axis",
                value=Decimal(axis),
                parse_status="numeric",
                source=SOURCE.model_copy(update={"row": f"row {row + 1}", "column": "axis"}),
            )
        )
        parsed = parse_compound_data_cell(
            text=raw,
            spec=CompoundQuantitySpec(component_ids=component_ids),
            source=SOURCE.model_copy(update={"row": f"row {row + 1}", "column": "output"}),
        )
        for offset, component_id in enumerate(component_ids, start=1):
            cells.append(
                RawGridCell(
                    row=row,
                    column=offset,
                    raw_text=raw,
                    role="data",
                    logical_row=row,
                    logical_column=f"output_{component_id}",
                    components=parsed.components,
                    compound_component_ids=parsed.compound_component_ids,
                    parse_status=parsed.parse_status,
                    source=parsed.components[0].source,
                )
            )
    return RawGrid(
        id="raw-synthetic-compound",
        rows=2,
        columns=1 + len(component_ids),
        target_unit="V",
        segments=(RawGridSegment(page_number=3, row_start=0, row_count=2, source=SOURCE),),
        cells=tuple(cells),
        source=SOURCE,
    )


def test_one_compound_cell_projects_both_measures_of_the_same_row() -> None:
    """Both readings survive into one table, on separate column axis positions.

    A projection that selected the component by the route's own supply form would keep
    one reading per route and lose the other, which is the defect issue #60 names.
    """
    table = project_table(IDENTITY, _spec("synthetic.tov.ac"), _grid())

    assert table.column_axis.id == "tov_basis"
    assert table.column_axis.labels == ("output_rms", "output_peak")
    assert {(cell.row, cell.column): cell.value for cell in table.cells} == {
        (0, 0): Decimal(11),
        (0, 1): Decimal(17),
        (1, 0): Decimal(13),
        (1, 1): Decimal(19),
    }


def test_both_system_voltage_routes_keep_the_same_two_measures() -> None:
    """The supply form selects the route, never which measure the route answers with."""
    grid = _grid()

    ac = project_table(IDENTITY, _spec("synthetic.tov.ac"), grid)
    dc = project_table(IDENTITY, _spec("synthetic.tov.dc"), grid)

    assert (ac.id, dc.id) == ("synthetic.tov.ac", "synthetic.tov.dc")
    assert ac.column_axis.labels == dc.column_axis.labels
    assert [cell.value for cell in ac.cells] == [cell.value for cell in dc.cells]


def test_a_supply_form_is_not_a_component_of_the_compound_cell() -> None:
    """A column may not claim a component the compound quantity does not carry.

    This is the query that used to resolve: a data column projecting ``ac`` out of the
    temporary-overvoltage cell. It now names nothing in the inventory, and the contract
    refuses it rather than answering with a measure that was never asked for.
    """
    with pytest.raises(ValidationError, match="projected component"):
        _spec("synthetic.tov.ac", projected=("ac",))


def test_projection_never_crosses_impulse_and_tov_components() -> None:
    component_ids = ("impulse", "tov")
    grid = _grid(component_ids)

    impulse = project_table(
        IDENTITY,
        _spec("synthetic.impulse", component_ids, projected=("impulse",)),
        grid,
    )
    tov = project_table(
        IDENTITY,
        _spec("synthetic.tov", component_ids, projected=("tov",)),
        grid,
    )

    assert [cell.value for cell in impulse.cells] == [Decimal(11), Decimal(13)]
    assert [cell.value for cell in tov.cells] == [Decimal(17), Decimal(19)]
