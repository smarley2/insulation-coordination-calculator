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
    a2_rows = tuple(map(Decimal, ("2000", "3000", "4000", "5000")))
    a2_values = tuple(map(Decimal, ("1", "1.1", "1.2", "1.3")))
    a2 = Table(
        id="iec60664-1-a2",
        unit="1",
        row_axis=TableAxis(
            id="altitude_m",
            unit="m",
            values=a2_rows,
            labels=tuple(str(value) for value in a2_rows),
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
                source=a2_source.model_copy(update={"row": str(altitude), "column": "factor"}),
            )
            for index, (altitude, value) in enumerate(zip(a2_rows, a2_values, strict=True))
        ),
        supported_ranges=(
            SupportedRange(
                variable="altitude_m",
                minimum=a2_rows[0],
                maximum=a2_rows[-1],
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
    f5_source = source.model_copy(update={"table": "F.5"})
    f5_rows = tuple(map(Decimal, ("10", "100", "1000", "3200", "4000")))
    f5_values = (
        ("0.025", "0.040"),
        ("0.100", "0.160"),
        ("3.2", "5.0"),
        ("12.5", "16.0"),
        ("16.0", "20.0"),
    )
    f5 = Table(
        id="iec60664-1-f5",
        unit="mm",
        row_axis=TableAxis(
            id="rms_voltage_v",
            unit="V",
            values=f5_rows,
            labels=tuple(str(value) for value in f5_rows),
        ),
        column_axis=TableAxis(
            id="pcb_pollution_branch",
            unit="1",
            values=(Decimal(1), Decimal(2)),
            labels=("pcb_pollution_1", "pcb_pollution_2"),
        ),
        cells=tuple(
            TableCell(
                row=row,
                column=column,
                value=Decimal(f5_values[row][column]),
                unit="mm",
                source=f5_source.model_copy(
                    update={
                        "row": str(f5_rows[row]),
                        "column": f"pcb_pollution_{column + 1}",
                    }
                ),
            )
            for row in range(len(f5_rows))
            for column in range(2)
        ),
        supported_ranges=(
            SupportedRange(
                variable="rms_voltage_v",
                minimum=f5_rows[0],
                maximum=f5_rows[-1],
                unit="V",
                source=f5_source,
            ),
        ),
        interpolation="linear",
        source=f5_source,
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
        formula("iec60664-1:f5-pcb-creepage", f5, "linear"),
        formula("iec60664-1:a2-altitude-factor", a2, "linear"),
    )
    mappings = tuple(
        CompatibilityMapping(
            id=f"annex-g-{kind}-{candidate}-{field}-pd{pollution}",
            source_rule_id=(
                f"iec60664-1:{'5.2.4' if kind == 'functional' else '5.2.5'}:"
                f"{kind}_clearance:candidate={candidate}:field={field}:pollution={pollution}"
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
        for pollution in (1, 2)
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
            "tables": (*retained_tables, f2, f5, f8, f9, a2),
            "formulas": (*retained_formulas, *formulas),
            "mappings": (
                *retained_mappings,
                *mappings,
                *(
                    CompatibilityMapping(
                        id=f"annex-h-{kind}-pd{pollution}",
                        source_rule_id=(
                            f"iec60664-1:{'5.3.4' if kind == 'functional' else '5.3.5'}:"
                            f"{kind}_creepage:construction=printed_wiring:pollution={pollution}"
                        ),
                        target_rule_id="iec60664-1:f5-pcb-creepage",
                        approved=True,
                        source=f5_source,
                    )
                    for kind in ("functional", "basic", "supplementary", "reinforced")
                    for pollution in (1, 2)
                ),
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
    table_2_source = source.model_copy(update={"table": "2", "figure": None})
    table_2_rows = tuple(map(Decimal, ("0.1", "0.3", "0.5", "0.8", "1.0")))
    table_2_frequencies = tuple(
        map(Decimal, ("100000", "200000", "400000", "700000", "1000000", "2000000", "3000000"))
    )
    table_2 = Table(
        id="iec60664-4-table-2",
        unit="mm",
        row_axis=TableAxis(
            id="peak_voltage_kv",
            unit="kV",
            values=table_2_rows,
            labels=tuple(str(value) for value in table_2_rows),
        ),
        column_axis=TableAxis(
            id="frequency_hz",
            unit="Hz",
            values=table_2_frequencies,
            labels=(
                "30-100 kHz",
                "200 kHz",
                "400 kHz",
                "700 kHz",
                "1 MHz",
                "2 MHz",
                "3 MHz",
            ),
        ),
        cells=tuple(
            TableCell(
                row=row,
                column=column,
                value=Decimal(row + 1) * Decimal(column + 1),
                unit="mm",
                source=table_2_source.model_copy(
                    update={
                        "row": str(table_2_rows[row]),
                        "column": str(table_2_frequencies[column]),
                    }
                ),
            )
            for row in range(len(table_2_rows))
            for column in range(len(table_2_frequencies))
        ),
        supported_ranges=(
            SupportedRange(
                variable="peak_voltage_kv",
                minimum=table_2_rows[0],
                maximum=table_2_rows[-1],
                unit="kV",
                source=table_2_source,
            ),
            SupportedRange(
                variable="frequency_hz",
                minimum=table_2_frequencies[0],
                maximum=table_2_frequencies[-1],
                unit="Hz",
                source=table_2_source,
            ),
        ),
        interpolation="linear",
        source=table_2_source,
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
    table_2_formula = Formula(
        id="iec60664-4:hf-creepage-table",
        expression=TableSelect(
            table_id=table_2.id,
            row=Variable(name="peak_voltage_kv"),
            column=Variable(name="frequency_hz"),
            row_mode="ceiling",
            column_mode="linear",
        ),
        unit="mm",
        parameter_sets=(
            ParameterSet(
                id="part4-table-2-parameters",
                parameters=(
                    Parameter(name="peak_voltage_kv", unit="kV"),
                    Parameter(name="frequency_hz", unit="Hz"),
                ),
                source=table_2_source,
            ),
        ),
        source=table_2_source,
    )
    mappings = tuple(
        CompatibilityMapping(
            id=f"part4-clearance-{kind}-pd{pollution}",
            source_rule_id=(
                f"iec60664-4:clearance:{kind}:stress=periodic_peak_v:"
                f"frequency=frequency_hz:pollution={pollution}"
            ),
            target_rule_id=clearance.id,
            approved=True,
            source=table_source,
        )
        for kind in ("functional", "basic", "supplementary", "reinforced")
        for pollution in (1, 2)
    )
    candidate = semantic_annex_g_rules.model_copy(
        update={
            "tables": (*semantic_annex_g_rules.tables, table_1, table_2),
            "formulas": (
                *semantic_annex_g_rules.formulas,
                critical,
                factor,
                minimum,
                radius,
                clearance,
                table_2_formula,
            ),
            "mappings": (
                *semantic_annex_g_rules.mappings,
                *mappings,
                *(
                    CompatibilityMapping(
                        id=f"part4-creepage-{kind}-pd{pollution}",
                        source_rule_id=(
                            f"iec60664-4:creepage:{kind}:stress=periodic_peak_v:"
                            f"frequency=frequency_hz:construction=printed_wiring:pollution={pollution}"
                        ),
                        target_rule_id=table_2_formula.id,
                        approved=True,
                        source=table_2_source,
                    )
                    for kind in ("functional", "basic", "supplementary", "reinforced")
                    for pollution in (1, 2)
                ),
            ),
            "checksums": {},
            "package_sha256": None,
        }
    )
    path = tmp_path / "synthetic-part4.icrules"
    write_rule_package(path, candidate)
    return load_rule_package(path)
