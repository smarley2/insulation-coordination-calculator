import sys
from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import (
    CompatibilityMapping,
    Formula,
    Parameter,
    ParameterSet,
    RulePackage,
    SupportedRange,
    Table,
    TableAxis,
    TableCell,
    TableSelect,
    Variable,
)
from insulation_coordination.rules.archive import load_rule_package, write_rule_package

sys.path.insert(0, str(Path(__file__).parents[2]))

from tests.fixtures.synthetic_rules import synthetic_part1_rule_package


@pytest.fixture
def synthetic_rules(tmp_path: Path) -> RulePackage:
    path = tmp_path / "synthetic-part1.icrules"
    write_rule_package(path, synthetic_part1_rule_package())
    return load_rule_package(path)


@pytest.fixture
def semantic_annex_g_rules(tmp_path: Path) -> RulePackage:
    base = synthetic_part1_rule_package()
    source = base.tables[0].source.model_copy(
        update={"table": "F.2/F.8 synthetic", "row": None, "column": None}
    )

    def table(
        table_id: str,
        row_id: str,
        rows: tuple[Decimal, ...],
        column_id: str,
        labels: tuple[str, ...],
    ) -> Table:
        columns = tuple(Decimal(index + 1) for index in range(len(labels)))
        return Table(
            id=table_id,
            unit="mm",
            row_axis=TableAxis(
                id=row_id,
                unit="kV",
                values=rows,
                labels=tuple(f"{row_id}-{value}" for value in rows),
            ),
            column_axis=TableAxis(
                id=column_id,
                unit="1",
                values=columns,
                labels=labels,
            ),
            cells=tuple(
                TableCell(
                    row=row_index,
                    column=column_index,
                    value=Decimal(row_index + 1) + Decimal(column_index + 1) / Decimal(10),
                    unit="mm",
                    source=source.model_copy(
                        update={"row": str(row_value), "column": label}
                    ),
                )
                for row_index, row_value in enumerate(rows)
                for column_index, label in enumerate(labels)
            ),
            supported_ranges=(
                SupportedRange(
                    variable=row_id,
                    minimum=rows[0],
                    maximum=rows[-1],
                    unit="kV",
                    source=source,
                ),
            ),
            interpolation="none",
            source=source,
        )

    f2 = table(
        "iec60664-1-f2",
        "impulse_withstand_kv",
        tuple(map(Decimal, ("0.5", "0.8", "1.0", "1.5", "2.5"))),
        "clearance_branch",
        (
            "case_a_pd1_mm",
            "case_a_pd2_mm",
            "case_a_pd3_mm",
            "case_b_pd1_mm",
            "case_b_pd2_mm",
            "case_b_pd3_mm",
        ),
    )
    f8 = table(
        "iec60664-1-f8",
        "peak_voltage_kv",
        tuple(map(Decimal, ("0.3", "0.5", "0.8", "1.0", "1.6"))),
        "field_case",
        ("case_a_mm", "case_b_mm"),
    )

    def formula(formula_id: str, table: Table, row_mode: str) -> Formula:
        expression = TableSelect(
            table_id=table.id,
            row=Variable(name=table.row_axis.id),
            column=Variable(name=table.column_axis.id),
            row_mode=row_mode,
            column_mode="exact",
        )
        return Formula(
            id=formula_id,
            expression=expression,
            unit="mm",
            parameter_sets=(
                ParameterSet(
                    id="synthetic-annex-g",
                    parameters=(
                        Parameter(name=table.row_axis.id, unit=table.row_axis.unit),
                        Parameter(name=table.column_axis.id, unit=table.column_axis.unit),
                    ),
                    source=source,
                ),
            ),
            source=source,
        )

    formulas = (
        formula("iec60664-1:f2-clearance", f2, "ceiling"),
        formula("iec60664-1:f8-clearance", f8, "ceiling"),
    )
    mappings = tuple(
        CompatibilityMapping(
            id=f"annex-g-{kind}-{candidate}-{field}",
            source_rule_id=(
                f"iec60664-1:{'5.2.4' if kind == 'functional' else '5.2.5'}:"
                f"{kind}_clearance:candidate={candidate}:field={field}:pollution=2"
            ),
            target_rule_id=(
                "iec60664-1:f2-clearance"
                if candidate == "impulse"
                else "iec60664-1:f8-clearance"
            ),
            approved=True,
            source=source,
        )
        for kind in ("functional", "basic", "supplementary", "reinforced")
        for candidate in ("impulse", "periodic")
        for field in ("inhomogeneous", "homogeneous", "approximately_homogeneous")
    )
    retained_tables = tuple(
        item for item in base.tables if not item.id.startswith("synthetic-clearance-")
    )
    retained_formulas = tuple(
        item for item in base.formulas if not item.id.startswith("synthetic-clearance-")
    )
    retained_mappings = tuple(
        item for item in base.mappings if "_clearance_" not in item.id
    )
    candidate = base.model_copy(
        update={
            "tables": (*retained_tables, f2, f8),
            "formulas": (*retained_formulas, *formulas),
            "mappings": (*retained_mappings, *mappings),
            "checksums": {},
            "package_sha256": None,
        }
    )
    path = tmp_path / "synthetic-annex-g.icrules"
    write_rule_package(path, candidate)
    return load_rule_package(path)
