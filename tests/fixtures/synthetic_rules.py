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


@pytest.fixture
def synthetic_package() -> RulePackage:
    return synthetic_rule_package()


@pytest.fixture
def package_dict(synthetic_package: RulePackage) -> dict[str, object]:
    return synthetic_package.model_dump(mode="json")
