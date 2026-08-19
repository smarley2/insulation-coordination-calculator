"""Rule packages for the calculation suite, invented end to end.

Every axis key, cell value and equation constant below is made up for the test
suite: repeated-digit numbers that no source table could carry. The packages
keep the *shape* the real ones have - the same table and formula identities,
selection modes, branch vocabularies and range declarations - because that is
what the engine routes on. The altitude table is the one place where the first
row and its factor are not free: the A.2 rule validator in the engine dictates
both, so they are shape here too, not data.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.calculation.high_frequency import A2_ALTITUDE_ROUTE
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
        tuple(map(Decimal, ("0.11", "0.22", "1.1", "2.2", "9.9"))),
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
        tuple(map(Decimal, ("0.22", "0.44", "0.88", "1.1", "2.2", "4.4", "7.7", "9.9"))),
        "field_case",
        ("case_a_mm", "case_b_mm"),
    )
    a2_source = source.model_copy(update={"table": "A.2"})
    # First factor: dictated by the engine's A.2 validator, which reads the row it sits on as
    # the altitude the correction is referred to. The altitudes themselves are invented.
    a2_rows = tuple(map(Decimal, ("2200", "4200", "6600", "9900")))
    a2_values = tuple(map(Decimal, ("1", "2", "4", "8")))
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
            values=tuple(map(Decimal, ("1.1", "3.3", "9.9"))),
            labels=("1.1", "3.3", "9.9"),
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
                zip(("1.1", "3.3", "9.9"), map(Decimal, ("1.1", "2.2", "9.9")), strict=True)
            )
        ),
        supported_ranges=(
            SupportedRange(
                variable="peak_voltage_kv",
                minimum=Decimal("1.1"),
                maximum=Decimal("9.9"),
                unit="kV",
                source=f9_source,
            ),
        ),
        interpolation="linear",
        source=f9_source,
    )
    f5_source = source.model_copy(update={"table": "F.5"})
    f5_rows = tuple(map(Decimal, ("11", "110", "1100", "3300", "9900")))
    f5_values = (
        ("0.11", "0.22"),
        ("1.1", "2.2"),
        ("3.3", "6.6"),
        ("5.5", "11"),
        ("11", "33"),
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
    retained_mappings = tuple(
        item
        for item in base.mappings
        # The base package states its own altitude correction; this one replaces it, and two
        # mappings on one semantic route are an ambiguity the engine refuses outright.
        if "_clearance_" not in item.id and item.source_rule_id != A2_ALTITUDE_ROUTE
    )
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
            values=tuple(map(Decimal, ("0.22", "0.88", "1.1", "2.2"))),
            labels=("0.22", "0.88", "1.1", "2.2"),
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
                zip(
                    ("0.22", "0.88", "1.1", "2.2"),
                    map(Decimal, ("1.1", "2.2", "3.3", "5.5")),
                    strict=True,
                )
            )
        ),
        supported_ranges=(
            SupportedRange(
                variable="peak_voltage_kv",
                minimum=Decimal("0.22"),
                maximum=Decimal("2.2"),
                unit="kV",
                source=table_source,
            ),
        ),
        interpolation="none",
        source=table_source,
    )
    table_2_source = source.model_copy(update={"table": "2", "figure": None})
    table_2_rows = tuple(map(Decimal, ("0.11", "0.22", "0.55", "0.88", "1.1")))
    table_2_frequencies = tuple(
        map(Decimal, ("110000", "220000", "440000", "770000", "1100000", "2200000", "3300000"))
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
            labels=tuple(f"band-{index + 1}" for index in range(len(table_2_frequencies))),
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
        Divide(numerator=Literal(value=Decimal("1.1")), denominator=Variable(name="clearance_mm")),
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
                        Literal(value=Decimal(99)),
                    )
                ),
            )
        ),
        "percent",
        ("frequency_mhz", "critical_frequency_mhz", "minimum_frequency_mhz"),
    )
    minimum = scalar_formula(
        "iec60664-4-minimum-frequency",
        Literal(value=Decimal("9.9")),
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
            right=Literal(value=Decimal("0.55")),
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
