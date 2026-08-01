import sys
from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import (
    Add,
    Compare,
    CompatibilityMapping,
    Divide,
    Formula,
    Literal,
    Multiply,
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
    source = base.tables[0].source.model_copy(update={"row": None, "column": None})

    def table(
        table_id: str,
        row_id: str,
        rows: tuple[Decimal, ...],
        column_id: str,
        labels: tuple[str, ...],
    ) -> Table:
        table_source = source.model_copy(
            update={"table": "F.2" if table_id.endswith("f2") else "F.8"}
        )
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
                    source=table_source.model_copy(update={"row": str(row_value), "column": label}),
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
                    source=table_source,
                ),
            ),
            interpolation="none",
            source=table_source,
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
        tuple(map(Decimal, ("0.3", "0.5", "0.8", "1.0", "1.6", "2.5", "3.0", "4.0"))),
        "field_case",
        ("case_a_mm", "case_b_mm"),
    )
    a2_source = source.model_copy(update={"table": "A.2"})
    a2 = Table(
        id="iec60664-1-a2",
        unit="1",
        row_axis=TableAxis(
            id="altitude_m",
            unit="m",
            values=tuple(map(Decimal, ("2000", "3000", "4000"))),
            labels=("2000", "3000", "4000"),
        ),
        column_axis=TableAxis(
            id="clearance_factor",
            unit="1",
            values=(Decimal(1),),
            labels=("clearance_factor",),
        ),
        cells=tuple(
            TableCell(
                row=index,
                column=0,
                value=value,
                unit="1",
                source=a2_source.model_copy(update={"row": altitude, "column": "factor"}),
            )
            for index, (altitude, value) in enumerate(
                zip(("2000", "3000", "4000"), map(Decimal, ("1", "1.1", "1.2")), strict=True)
            )
        ),
        supported_ranges=(
            SupportedRange(
                variable="altitude_m",
                minimum=Decimal(2000),
                maximum=Decimal(4000),
                unit="m",
                source=a2_source,
            ),
        ),
        interpolation="linear",
        source=a2_source,
    )
    f9_source = source.model_copy(update={"table": "F.9"})
    f9 = Table(
        id="iec60664-1-f9",
        unit="mm",
        row_axis=TableAxis(
            id="peak_voltage_kv",
            unit="kV",
            values=tuple(map(Decimal, ("2.5", "3", "4"))),
            labels=("2.5", "3", "4"),
        ),
        column_axis=TableAxis(
            id="partial_discharge_advice",
            unit="1",
            values=(Decimal(1),),
            labels=("case_a_mm",),
        ),
        cells=tuple(
            TableCell(
                row=index,
                column=0,
                value=value,
                unit="mm",
                source=f9_source.model_copy(update={"row": voltage, "column": "case_a_mm"}),
            )
            for index, (voltage, value) in enumerate(
                zip(("2.5", "3", "4"), map(Decimal, ("2", "3.2", "11")), strict=True)
            )
        ),
        supported_ranges=(
            SupportedRange(
                variable="peak_voltage_kv",
                minimum=Decimal("2.5"),
                maximum=Decimal(4),
                unit="kV",
                source=f9_source,
            ),
        ),
        interpolation="linear",
        source=f9_source,
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
            unit=table.unit,
            parameter_sets=(
                ParameterSet(
                    id="synthetic-annex-g",
                    parameters=(
                        Parameter(name=table.row_axis.id, unit=table.row_axis.unit),
                        Parameter(name=table.column_axis.id, unit=table.column_axis.unit),
                    ),
                    source=table.source,
                ),
            ),
            source=table.source,
        )

    formulas = (
        formula("iec60664-1:f2-clearance", f2, "ceiling"),
        formula("iec60664-1:f8-clearance", f8, "ceiling"),
        formula("iec60664-1:a2-altitude-factor", a2, "linear"),
    )
    mappings = tuple(
        CompatibilityMapping(
            id=f"annex-g-{kind}-{candidate}-{field}",
            source_rule_id=(
                f"iec60664-1:{'5.2.4' if kind == 'functional' else '5.2.5'}:"
                f"{kind}_clearance:candidate={candidate}:field={field}:pollution=2"
            ),
            target_rule_id=(
                "iec60664-1:f2-clearance" if candidate == "impulse" else "iec60664-1:f8-clearance"
            ),
            approved=True,
            source=(f2.source if candidate == "impulse" else f8.source),
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
    retained_mappings = tuple(item for item in base.mappings if "_clearance_" not in item.id)
    candidate = base.model_copy(
        update={
            "tables": (*retained_tables, f2, f8, f9, a2),
            "formulas": (*retained_formulas, *formulas),
            "mappings": (
                *retained_mappings,
                *mappings,
                CompatibilityMapping(
                    id="annex-a2-altitude",
                    source_rule_id="iec60664-1:altitude_correction:base=2000m",
                    target_rule_id="iec60664-1:a2-altitude-factor",
                    approved=True,
                    source=a2_source,
                ),
            ),
            "checksums": {},
            "package_sha256": None,
        }
    )
    path = tmp_path / "synthetic-annex-g.icrules"
    write_rule_package(path, candidate)
    return load_rule_package(path)


@pytest.fixture
def semantic_part4_rules(
    tmp_path: Path,
    semantic_annex_g_rules: RulePackage,
) -> RulePackage:
    source = semantic_annex_g_rules.tables[0].source.model_copy(
        update={"table": None, "figure": "Equation"}
    )
    table_source = source.model_copy(update={"table": "1", "figure": None})
    table_1 = Table(
        id="iec60664-4-table-1",
        unit="mm",
        row_axis=TableAxis(
            id="peak_voltage_kv",
            unit="kV",
            values=tuple(map(Decimal, ("0.5", "0.8", "1.0", "1.6"))),
            labels=("0.5", "0.8", "1.0", "1.6"),
        ),
        column_axis=TableAxis(
            id="clearance_branch",
            unit="1",
            values=(Decimal(1),),
            labels=("inhomogeneous_mm",),
        ),
        cells=tuple(
            TableCell(
                row=index,
                column=0,
                value=value,
                unit="mm",
                source=table_source.model_copy(update={"row": label, "column": "clearance"}),
            )
            for index, (label, value) in enumerate(
                zip(("0.5", "0.8", "1.0", "1.6"), map(Decimal, ("1", "2", "3", "5")), strict=True)
            )
        ),
        supported_ranges=(
            SupportedRange(
                variable="peak_voltage_kv",
                minimum=Decimal("0.5"),
                maximum=Decimal("1.6"),
                unit="kV",
                source=table_source,
            ),
        ),
        interpolation="none",
        source=table_source,
    )

    def scalar_formula(
        formula_id: str,
        expression: object,
        unit: str,
        parameters: tuple[str, ...],
    ) -> Formula:
        return Formula(
            id=formula_id,
            expression=expression,
            unit=unit,
            parameter_sets=(
                ParameterSet(
                    id=f"{formula_id}-parameters",
                    parameters=tuple(Parameter(name=name, unit="1") for name in parameters),
                    source=source,
                ),
            ),
            source=source,
        )

    critical = scalar_formula(
        "iec60664-4-equation-1-critical-frequency",
        Divide(numerator=Literal(value=Decimal("0.2")), denominator=Variable(name="clearance_mm")),
        "MHz",
        ("clearance_mm",),
    )
    factor = scalar_formula(
        "iec60664-4-equation-2-frequency-factor",
        Add(
            operands=(
                Literal(value=Decimal(100)),
                Multiply(
                    operands=(
                        Divide(
                            numerator=Add(
                                operands=(
                                    Variable(name="frequency_mhz"),
                                    Multiply(
                                        operands=(
                                            Literal(value=Decimal(-1)),
                                            Variable(name="critical_frequency_mhz"),
                                        )
                                    ),
                                )
                            ),
                            denominator=Add(
                                operands=(
                                    Variable(name="minimum_frequency_mhz"),
                                    Multiply(
                                        operands=(
                                            Literal(value=Decimal(-1)),
                                            Variable(name="critical_frequency_mhz"),
                                        )
                                    ),
                                )
                            ),
                        ),
                        Literal(value=Decimal(25)),
                    )
                ),
            )
        ),
        "percent",
        ("frequency_mhz", "critical_frequency_mhz", "minimum_frequency_mhz"),
    )
    minimum = scalar_formula(
        "iec60664-4-minimum-frequency",
        Literal(value=Decimal(3)),
        "MHz",
        (),
    )
    radius = scalar_formula(
        "iec60664-4-radius-criterion",
        Compare(
            comparison="ge",
            left=Divide(
                numerator=Variable(name="radius_mm"),
                denominator=Variable(name="clearance_mm"),
            ),
            right=Literal(value=Decimal("0.2")),
        ),
        "bool",
        ("radius_mm", "clearance_mm"),
    )
    clearance = Formula(
        id="iec60664-4:hf-clearance-table",
        expression=TableSelect(
            table_id=table_1.id,
            row=Variable(name="peak_voltage_kv"),
            column=Variable(name="clearance_branch"),
            row_mode="ceiling",
            column_mode="exact",
        ),
        unit="mm",
        parameter_sets=(
            ParameterSet(
                id="part4-table-1-parameters",
                parameters=(
                    Parameter(name="peak_voltage_kv", unit="kV"),
                    Parameter(name="clearance_branch", unit="1"),
                ),
                source=table_source,
            ),
        ),
        source=table_source,
    )
    mappings = tuple(
        CompatibilityMapping(
            id=f"part4-clearance-{kind}",
            source_rule_id=(
                f"iec60664-4:clearance:{kind}:stress=periodic_peak_v:"
                "frequency=frequency_hz:pollution=2"
            ),
            target_rule_id=clearance.id,
            approved=True,
            source=table_source,
        )
        for kind in ("functional", "basic", "supplementary", "reinforced")
    )
    candidate = semantic_annex_g_rules.model_copy(
        update={
            "tables": (*semantic_annex_g_rules.tables, table_1),
            "formulas": (
                *semantic_annex_g_rules.formulas,
                critical,
                factor,
                minimum,
                radius,
                clearance,
            ),
            "mappings": (*semantic_annex_g_rules.mappings, *mappings),
            "checksums": {},
            "package_sha256": None,
        }
    )
    path = tmp_path / "synthetic-part4.icrules"
    write_rule_package(path, candidate)
    return load_rule_package(path)
