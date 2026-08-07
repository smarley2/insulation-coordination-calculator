from decimal import Decimal
from uuid import UUID

import pytest

from insulation_coordination.domain.display import pair_label, render_expression
from insulation_coordination.domain.project import (
    NetClass,
    PairCase,
    Project,
    ProjectDefaults,
    ProjectMetadata,
)
from insulation_coordination.domain.rules import (
    Add,
    Compare,
    Divide,
    LinearInterpolate,
    Literal,
    Lookup,
    Maximum,
    Minimum,
    Multiply,
    Power,
    Round,
    Select,
    TableSelect,
    Variable,
)
from insulation_coordination.project.pairs import canonical_pair_key


def test_pair_label_uses_net_class_names() -> None:
    nets = (
        NetClass(id=UUID(int=1), name="HV+"),
        NetClass(id=UUID(int=2), name="HV-"),
    )
    pair = PairCase(
        key=canonical_pair_key(nets[0].id, nets[1].id),
        net_a=nets[0].id,
        net_b=nets[1].id,
    )
    project = Project(
        id=UUID(int=100),
        metadata=ProjectMetadata(title="Test"),
        application_version="test",
        defaults=ProjectDefaults(),
        net_classes=nets,
        pairs=(pair,),
    )

    assert pair_label(project, pair) == "HV+ ↔ HV-"


def _table_select() -> TableSelect:
    return TableSelect(
        table_id="iec60664-1-f2",
        row=Variable(name="impulse_withstand_kv"),
        column=Variable(name="clearance_branch"),
        row_mode="ceiling",
        column_mode="exact",
    )


@pytest.mark.parametrize(
    ("expression", "expected"),
    (
        (Literal(value=Decimal("0.2")), "0.2"),
        (Variable(name="clearance_mm"), "clearance_mm"),
        (
            Divide(numerator=Literal(value=Decimal("0.2")), denominator=Variable(name="d")),
            "(0.2 / d)",
        ),
        (
            Add(operands=(Variable(name="a"), Literal(value=Decimal(1)))),
            "(a + 1)",
        ),
        (
            Multiply(operands=(Variable(name="a"), Variable(name="b"))),
            "(a * b)",
        ),
        (
            Minimum(operands=(Variable(name="a"), Variable(name="b"))),
            "minimum(a, b)",
        ),
        (
            Maximum(operands=(Variable(name="a"), Variable(name="b"))),
            "maximum(a, b)",
        ),
        (
            Compare(comparison="ge", left=Variable(name="a"), right=Literal(value=Decimal(1))),
            "a >= 1",
        ),
        (
            Select(
                condition=Compare(
                    comparison="lt",
                    left=Variable(name="a"),
                    right=Literal(value=Decimal(1)),
                ),
                if_true=Variable(name="b"),
                if_false=Variable(name="c"),
            ),
            "if a < 1 then b else c",
        ),
        (
            Round(places=2, mode="ROUND_HALF_UP", value=Variable(name="a")),
            "round(a, 2, ROUND_HALF_UP)",
        ),
        (
            Lookup(
                table_id="t",
                row=Literal(value=Decimal(1)),
                column=Literal(value=Decimal(2)),
            ),
            "table t[row 1, column 2]",
        ),
        (
            LinearInterpolate(table_id="t", x=Variable(name="a")),
            "table t[interpolate a]",
        ),
        (
            LinearInterpolate(table_id="t", x=Variable(name="a"), column=Literal(value=Decimal(3))),
            "table t[interpolate a, column 3]",
        ),
        (
            Power(base=Variable(name="a"), numerator=2),
            "a ^ (2/1)",
        ),
        (
            Power(
                base=Add(operands=(Variable(name="a"), Literal(value=Decimal(1)))),
                numerator=1,
                denominator=2,
            ),
            "(a + 1) ^ (1/2)",
        ),
        (
            _table_select(),
            (
                "table iec60664-1-f2[row impulse_withstand_kv (next value up), "
                "column clearance_branch (exact match)]"
            ),
        ),
    ),
)
def test_render_expression_reads_as_ordinary_arithmetic(expression, expected: str) -> None:
    assert render_expression(expression) == expected


def test_render_expression_passes_through_non_expressions() -> None:
    assert render_expression("already text") == "already text"
