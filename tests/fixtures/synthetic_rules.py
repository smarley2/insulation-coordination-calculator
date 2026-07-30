from datetime import UTC, datetime
from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import (
    Add,
    ApprovalRecord,
    Compare,
    CompatibilityMapping,
    Divide,
    Formula,
    LinearInterpolate,
    Literal,
    Lookup,
    Manifest,
    Maximum,
    Minimum,
    Multiply,
    Parameter,
    ParameterSet,
    Round,
    RulePackage,
    Select,
    SourceDocument,
    SourceReference,
    SupportedRange,
    Table,
    TableAxis,
    TableCell,
    Variable,
)


def synthetic_rule_package() -> RulePackage:
    reference = SourceReference(
        standard="SYNTHETIC-1",
        edition="1",
        clause="4.2",
        table="T-1",
        figure=None,
        row="synthetic row",
        column="synthetic column",
        note="Synthetic fixture only.",
    )
    table_range = SupportedRange(
        variable="voltage",
        minimum=Decimal(0),
        maximum=Decimal(20),
        unit="V",
        source=reference,
    )
    table = Table(
        id="synthetic-distance",
        unit="mm",
        row_axis=TableAxis(
            id="voltage",
            unit="V",
            values=(Decimal(0), Decimal(20)),
        ),
        column_axis=TableAxis(
            id="category",
            unit="1",
            values=(Decimal(1), Decimal(2)),
        ),
        cells=(
            TableCell(
                row=0,
                column=0,
                value=Decimal("1.00"),
                unit="mm",
                source=reference.model_copy(update={"row": "0", "column": "1"}),
            ),
            TableCell(
                row=0,
                column=1,
                value=Decimal("1.50"),
                unit="mm",
                source=reference.model_copy(update={"row": "0", "column": "2"}),
            ),
            TableCell(
                row=1,
                column=0,
                value=Decimal("2.00"),
                unit="mm",
                source=reference.model_copy(update={"row": "20", "column": "1"}),
            ),
            TableCell(
                row=1,
                column=1,
                value=Decimal("2.50"),
                unit="mm",
                source=reference.model_copy(update={"row": "20", "column": "2"}),
            ),
        ),
        supported_ranges=(table_range,),
        interpolation="linear",
        rounding_places=2,
        rounding_mode="ROUND_HALF_UP",
        source=reference,
    )
    expression = Select(
        condition=Compare(
            comparison="gt",
            left=Variable(name="voltage"),
            right=Literal(value=Decimal(10)),
        ),
        if_true=Round(
            value=Divide(
                numerator=Multiply(
                    operands=(
                        Variable(name="voltage"),
                        Literal(value=Decimal(2)),
                    )
                ),
                denominator=Literal(value=Decimal(4)),
            ),
            places=2,
            mode="ROUND_HALF_EVEN",
        ),
        if_false=Maximum(
            operands=(
                Minimum(
                    operands=(
                        Literal(value=Decimal(1)),
                        Literal(value=Decimal(2)),
                    )
                ),
                Add(
                    operands=(
                        Literal(value=Decimal(3)),
                        Lookup(
                            table_id="synthetic-distance",
                            row=Literal(value=Decimal(0)),
                            column=Literal(value=Decimal(1)),
                        ),
                    )
                ),
                LinearInterpolate(
                    table_id="synthetic-distance",
                    x=Variable(name="voltage"),
                    column=Literal(value=Decimal(1)),
                ),
            )
        ),
    )
    formula_range = SupportedRange(
        variable="voltage",
        minimum=Decimal(0),
        maximum=Decimal(20),
        unit="V",
        source=reference,
    )
    formula = Formula(
        id="synthetic-formula",
        expression=expression,
        unit="mm",
        parameter_sets=(
            ParameterSet(
                id="default",
                parameters=(
                    Parameter(
                        name="voltage",
                        unit="V",
                        minimum=Decimal(0),
                        maximum=Decimal(20),
                    ),
                ),
                source=reference,
            ),
        ),
        supported_ranges=(formula_range,),
        latex="d = f(U)",
        source=reference,
    )
    return RulePackage(
        manifest=Manifest(
            schema_version=1,
            package_id="00000000-0000-0000-0000-000000000001",
            version="1.0",
            importer_version="test-1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_documents=(
                SourceDocument(
                    standard="SYNTHETIC-1",
                    edition="1",
                    sha256="a" * 64,
                ),
            ),
            approved=True,
            compatible=True,
            approval_records=(
                ApprovalRecord(
                    action="approval",
                    actor="Synthetic Reviewer",
                    recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
                    notes="Synthetic data reviewed.",
                ),
            ),
        ),
        tables=(table,),
        formulas=(formula,),
        mappings=(
            CompatibilityMapping(
                id="synthetic-compatibility",
                source_rule_id="synthetic-part-a",
                target_rule_id="synthetic-part-b",
                approved=True,
                source=reference,
            ),
        ),
    )


def synthetic_part1_rule_package() -> RulePackage:
    reference = SourceReference(
        standard="SYNTHETIC-PART-1",
        edition="1",
        clause="synthetic",
        table="synthetic-distance",
        row="synthetic row",
        column="synthetic column",
        note="Visibly synthetic fixture only; contains no IEC numeric values.",
    )

    def distance_table(
        table_id: str,
        maximum_stress: Decimal,
        low_distance: str,
        high_distance: str,
    ) -> Table:
        return Table(
            id=table_id,
            unit="mm",
            row_axis=TableAxis(
                id="stress_v",
                unit="V",
                values=(Decimal(100), maximum_stress),
            ),
            column_axis=TableAxis(id="synthetic_branch", unit="1", values=(Decimal(1),)),
            cells=(
                TableCell(
                    row=0,
                    column=0,
                    value=Decimal(low_distance),
                    unit="mm",
                    source=reference.model_copy(update={"row": "low", "column": "1"}),
                ),
                TableCell(
                    row=1,
                    column=0,
                    value=Decimal(high_distance),
                    unit="mm",
                    source=reference.model_copy(update={"row": "high", "column": "1"}),
                ),
            ),
            supported_ranges=(
                SupportedRange(
                    variable="stress_v",
                    minimum=Decimal(100),
                    maximum=maximum_stress,
                    unit="V",
                    source=reference,
                ),
            ),
            interpolation="linear",
            rounding_places=2,
            rounding_mode="ROUND_HALF_UP",
            source=reference,
        )

    table_specs = (
        ("synthetic-clearance-functional-impulse", Decimal(1000), "0.50", "2.00"),
        ("synthetic-clearance-basic-impulse", Decimal(1000), "1.00", "3.00"),
        ("synthetic-clearance-reinforced-impulse", Decimal(1000), "2.00", "5.50"),
        ("synthetic-clearance-functional-periodic", Decimal(1000), "0.25", "1.50"),
        ("synthetic-clearance-basic-periodic", Decimal(1000), "0.50", "2.00"),
        ("synthetic-clearance-reinforced-periodic", Decimal(1000), "1.00", "4.00"),
        ("synthetic-creepage-functional", Decimal(500), "1.00", "3.00"),
        ("synthetic-creepage-basic", Decimal(500), "1.50", "4.00"),
        ("synthetic-creepage-reinforced", Decimal(500), "2.50", "8.00"),
    )
    tables = tuple(
        distance_table(table_id, maximum, low, high) for table_id, maximum, low, high in table_specs
    )
    formulas = tuple(
        Formula(
            id=f"{table.id}-formula",
            expression=LinearInterpolate(
                table_id=table.id,
                x=Variable(name="stress_v"),
            ),
            unit="mm",
            parameter_sets=(
                ParameterSet(
                    id="synthetic-default",
                    parameters=(
                        Parameter(
                            name="stress_v",
                            unit="V",
                            minimum=table.row_axis.values[0],
                            maximum=table.row_axis.values[-1],
                        ),
                    ),
                    source=reference,
                ),
            ),
            supported_ranges=table.supported_ranges,
            latex="d_{synthetic} = f(U_{synthetic})",
            applicability="Synthetic Part 1 route only.",
            source=reference,
        )
        for table in tables
    )
    mapping_specs = (
        (
            "functional_clearance_impulse",
            (
                "iec60664-1:5.2.4:functional_clearance:"
                "candidate=impulse:field=inhomogeneous:pollution=2"
            ),
            "synthetic-clearance-functional-impulse-formula",
        ),
        (
            "basic_clearance_impulse",
            ("iec60664-1:5.2.5:basic_clearance:candidate=impulse:field=inhomogeneous:pollution=2"),
            "synthetic-clearance-basic-impulse-formula",
        ),
        (
            "reinforced_clearance_impulse",
            (
                "iec60664-1:5.2.5:reinforced_clearance:"
                "candidate=impulse:field=inhomogeneous:pollution=2"
            ),
            "synthetic-clearance-reinforced-impulse-formula",
        ),
        (
            "functional_clearance_periodic",
            (
                "iec60664-1:5.2.4:functional_clearance:"
                "candidate=periodic:field=inhomogeneous:pollution=2"
            ),
            "synthetic-clearance-functional-periodic-formula",
        ),
        (
            "basic_clearance_periodic",
            ("iec60664-1:5.2.5:basic_clearance:candidate=periodic:field=inhomogeneous:pollution=2"),
            "synthetic-clearance-basic-periodic-formula",
        ),
        (
            "reinforced_clearance_periodic",
            (
                "iec60664-1:5.2.5:reinforced_clearance:"
                "candidate=periodic:field=inhomogeneous:pollution=2"
            ),
            "synthetic-clearance-reinforced-periodic-formula",
        ),
        (
            "functional_creepage",
            ("iec60664-1:5.3.4:functional_creepage:construction=other:pollution=2:material=I"),
            "synthetic-creepage-functional-formula",
        ),
        (
            "basic_creepage",
            ("iec60664-1:5.3.5:basic_creepage:construction=other:pollution=2:material=I"),
            "synthetic-creepage-basic-formula",
        ),
        (
            "reinforced_creepage",
            ("iec60664-1:5.3.5:reinforced_creepage:construction=other:pollution=2:material=I"),
            "synthetic-creepage-reinforced-formula",
        ),
    )
    return RulePackage(
        manifest=Manifest(
            schema_version=1,
            package_id="00000000-0000-0000-0000-000000000006",
            version="part1-synthetic-1",
            importer_version="test-1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_documents=(
                SourceDocument(
                    standard="SYNTHETIC-PART-1",
                    edition="1",
                    sha256="b" * 64,
                ),
            ),
            approved=True,
            compatible=True,
            approval_records=(
                ApprovalRecord(
                    action="approval",
                    actor="Synthetic Reviewer",
                    recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
                    notes="Synthetic Part 1 data reviewed.",
                ),
            ),
        ),
        tables=tables,
        formulas=formulas,
        mappings=tuple(
            CompatibilityMapping(
                id=mapping_id,
                source_rule_id=source_rule_id,
                target_rule_id=target_rule_id,
                approved=True,
                source=reference,
            )
            for mapping_id, source_rule_id, target_rule_id in mapping_specs
        ),
    )


@pytest.fixture
def synthetic_package() -> RulePackage:
    return synthetic_rule_package()


@pytest.fixture
def package_dict(synthetic_package: RulePackage) -> dict[str, object]:
    return synthetic_package.model_dump(mode="json")
