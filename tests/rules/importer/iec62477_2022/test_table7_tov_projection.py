from __future__ import annotations

from decimal import Decimal

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


def _spec(
    route: str,
    component_id: str,
    component_ids: tuple[str, ...] = ("ac", "dc"),
) -> TableAuditSpec:
    compound = CompoundQuantitySpec(component_ids=component_ids)
    return TableAuditSpec(
        semantic_id=route,
        source_table="S7",
        title_anchor="Synthetic table S7",
        page_number=3,
        clause="S.7",
        target_unit="V",
        expected_raw_rows=2,
        expected_raw_columns=2,
        expected_bbox=(0, 0, 10, 10),
        data_strategy="rectangle",
        expected_data_rows=2,
        expected_data_columns=2,
        row_axis_id="system_voltage",
        row_axis_unit="V",
        column_axis_id="branch",
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
            TableColumnSpec(
                semantic_id="output",
                heading="synthetic compound output",
                source_column=1,
                role="data",
                unit="V",
                compound_quantity=compound,
                projected_component_id=component_id,
            ),
        ),
    )


def _grid() -> RawGrid:
    cells = []
    for row, (axis, raw) in enumerate((("1", "11 ac / 17 dc"), ("2", "13 ac / 19 dc"))):
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
            spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
            source=SOURCE.model_copy(update={"row": f"row {row + 1}", "column": "output"}),
        )
        cells.append(
            RawGridCell(
                row=row,
                column=1,
                raw_text=raw,
                role="data",
                logical_row=row,
                logical_column="output",
                components=parsed.components,
                compound_component_ids=parsed.compound_component_ids,
                parse_status=parsed.parse_status,
                source=parsed.components[0].source,
            )
        )
    return RawGrid(
        id="raw-synthetic-compound",
        rows=2,
        columns=2,
        target_unit="V",
        segments=(RawGridSegment(page_number=3, row_start=0, row_count=2, source=SOURCE),),
        cells=tuple(cells),
        source=SOURCE,
    )


def test_table_projection_keeps_ac_and_dc_routes_distinct() -> None:
    grid = _grid()

    ac = project_table(IDENTITY, _spec("synthetic.tov.ac", "ac"), grid)
    dc = project_table(IDENTITY, _spec("synthetic.tov.dc", "dc"), grid)

    assert [cell.value for cell in ac.cells] == [Decimal(11), Decimal(13)]
    assert [cell.value for cell in dc.cells] == [Decimal(17), Decimal(19)]
    assert ac.id == "synthetic.tov.ac"
    assert dc.id == "synthetic.tov.dc"


def test_projection_never_crosses_impulse_and_tov_components() -> None:
    grid = _grid()
    remapped_cells = tuple(
        cell
        if not cell.components
        else cell.model_copy(
            update={
                "components": tuple(
                    part.model_copy(
                        update={
                            "component_id": "impulse" if part.component_id == "ac" else "tov"
                        }
                    )
                    for part in cell.components
                )
            }
        )
        for cell in grid.cells
    )
    remapped = grid.model_copy(update={"cells": remapped_cells})

    component_ids = ("impulse", "tov")
    impulse = project_table(
        IDENTITY, _spec("synthetic.impulse", "impulse", component_ids), remapped
    )
    tov = project_table(IDENTITY, _spec("synthetic.tov", "tov", component_ids), remapped)

    assert [cell.value for cell in impulse.cells] == [Decimal(11), Decimal(13)]
    assert [cell.value for cell in tov.cells] == [Decimal(17), Decimal(19)]
