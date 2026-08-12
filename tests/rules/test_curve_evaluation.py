from decimal import Decimal, localcontext

import pytest

from insulation_coordination.domain.rules import (
    CurveAxis,
    CurvePoint,
    CurveSegment,
    FaultTimeVoltageSelector,
    FaultTimeVoltageVariant,
    PiecewiseCurveRule,
    SourceReference,
)
from insulation_coordination.rules.evaluator import (
    EvaluationError,
    evaluate_piecewise_curve,
)

SOURCE = SourceReference(
    document_id="synthetic-source",
    standard="SYNTHETIC-1",
    edition="1",
    page=1,
    clause="synthetic clause",
    figure="synthetic figure",
)


def _synthetic_curve() -> PiecewiseCurveRule:
    return PiecewiseCurveRule(
        id="synthetic-fault-time-voltage",
        variants=(
            FaultTimeVoltageVariant(
                id="synthetic-dc-dvc",
                selector=FaultTimeVoltageSelector(
                    subject="accessible_circuit",
                    voltage_basis="dc",
                    dvc_context="synthetic-dvc",
                    environment_context=None,
                ),
                x_axis=CurveAxis(
                    quantity_kind="fault-time",
                    unit="ms",
                    scale="log10",
                    minimum=Decimal(3),
                    maximum=Decimal(243),
                ),
                y_axis=CurveAxis(
                    quantity_kind="voltage-limit",
                    unit="V",
                    scale="log10",
                    minimum=Decimal(89),
                    maximum=Decimal(777),
                ),
                points=(
                    CurvePoint(x=Decimal(3), y=Decimal(777)),
                    CurvePoint(x=Decimal(27), y=Decimal(271)),
                    CurvePoint(x=Decimal(243), y=Decimal(89)),
                ),
                segments=(
                    CurveSegment(
                        start=0,
                        end=1,
                        segment_type="continuous",
                        interpolation="log_log",
                    ),
                    CurveSegment(
                        start=1,
                        end=2,
                        segment_type="continuous",
                        interpolation="log_log",
                    ),
                ),
                applicability="synthetic applicability",
                source=SOURCE,
                reviewed_artifact_sha256="a" * 64,
            ),
        ),
        source=SOURCE,
    )


def test_curve_domain_is_closed_and_never_extrapolated() -> None:
    rule = _synthetic_curve()
    exact_selector = rule.variants[0].selector

    assert evaluate_piecewise_curve(rule, exact_selector, Decimal(3)).status == "matched"
    assert evaluate_piecewise_curve(rule, exact_selector, Decimal(243)).status == "matched"
    assert evaluate_piecewise_curve(rule, exact_selector, Decimal(2)).status == "out_of_domain"
    assert evaluate_piecewise_curve(rule, exact_selector, Decimal(244)).status == "out_of_domain"


def test_exact_breakpoint_returns_the_reviewed_point() -> None:
    rule = _synthetic_curve()
    exact_selector = rule.variants[0].selector
    result = evaluate_piecewise_curve(rule, exact_selector, Decimal(27))

    assert result.value == Decimal(271)
    assert result.unit == "V"
    assert result.variant_id == "synthetic-dc-dvc"
    assert result.source == SOURCE


def test_log_log_midpoint_uses_a_34_digit_local_decimal_context() -> None:
    rule = _synthetic_curve()
    exact_selector = rule.variants[0].selector
    with localcontext() as context:
        context.prec = 34
        fraction = (Decimal(9).ln() - Decimal(3).ln()) / (Decimal(27).ln() - Decimal(3).ln())
        expected = (Decimal(777).ln() + fraction * (Decimal(271).ln() - Decimal(777).ln())).exp()

    assert evaluate_piecewise_curve(rule, exact_selector, Decimal(9)).value == expected


def test_explicit_plateau_extends_only_to_its_approved_endpoint() -> None:
    rule = _synthetic_curve()
    variant = rule.variants[0]
    plateau_variant = FaultTimeVoltageVariant.model_validate(
        {
            **variant.model_dump(mode="python"),
            "x_axis": variant.x_axis.model_copy(update={"maximum": Decimal(300)}),
            "points": (
                *variant.points,
                CurvePoint(x=Decimal(300), y=Decimal(89)),
            ),
            "segments": (
                *variant.segments,
                CurveSegment(
                    start=2,
                    end=3,
                    segment_type="plateau",
                    interpolation="constant",
                ),
            ),
        }
    )
    plateau_rule = PiecewiseCurveRule(
        id=rule.id,
        variants=(plateau_variant,),
        source=SOURCE,
    )

    at_endpoint = evaluate_piecewise_curve(
        plateau_rule,
        plateau_variant.selector,
        Decimal(300),
    )
    beyond_endpoint = evaluate_piecewise_curve(
        plateau_rule,
        plateau_variant.selector,
        Decimal(301),
    )

    assert at_endpoint.status == "matched"
    assert at_endpoint.value == Decimal(89)
    assert beyond_endpoint.status == "out_of_domain"


@pytest.mark.parametrize(
    ("interpolation", "x", "expected"),
    (
        ("linear", Decimal(2), Decimal(5)),
        ("log_x", Decimal(3), Decimal("5.000000000000000000000000000000002")),
        ("log_y", Decimal(2), Decimal("3.000000000000000000000000000000001")),
        ("log_log", Decimal(3), Decimal("3.000000000000000000000000000000001")),
        ("step_before", Decimal(2), Decimal(9)),
        ("step_after", Decimal(2), Decimal(1)),
    ),
)
def test_declared_interpolation_is_applied(
    interpolation: str,
    x: Decimal,
    expected: Decimal,
) -> None:
    segment_type = "step" if interpolation.startswith("step_") else "continuous"
    variant = FaultTimeVoltageVariant(
        id=f"synthetic-{interpolation}",
        selector=FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="dc",
            dvc_context=interpolation,
            environment_context=None,
        ),
        x_axis=CurveAxis(
            quantity_kind="fault-time",
            unit="ms",
            scale="log10" if interpolation in ("log_x", "log_log") else "linear",
            minimum=Decimal(1),
            maximum=Decimal(9) if interpolation in ("log_x", "log_log") else Decimal(3),
        ),
        y_axis=CurveAxis(
            quantity_kind="voltage-limit",
            unit="V",
            scale="log10" if interpolation in ("log_y", "log_log") else "linear",
            minimum=Decimal(1),
            maximum=Decimal(9),
        ),
        points=(
            CurvePoint(x=Decimal(1), y=Decimal(1)),
            CurvePoint(
                x=Decimal(9) if interpolation in ("log_x", "log_log") else Decimal(3),
                y=Decimal(9),
            ),
        ),
        segments=(
            CurveSegment(
                start=0,
                end=1,
                segment_type=segment_type,  # type: ignore[arg-type]
                interpolation=interpolation,  # type: ignore[arg-type]
            ),
        ),
        applicability="synthetic applicability",
        source=SOURCE,
        reviewed_artifact_sha256="b" * 64,
    )
    rule = PiecewiseCurveRule(id="synthetic-interpolation", variants=(variant,), source=SOURCE)

    assert evaluate_piecewise_curve(rule, variant.selector, x).value == expected


def test_no_selector_match_is_distinct_from_out_of_domain() -> None:
    rule = _synthetic_curve()
    selector = rule.variants[0].selector.model_copy(update={"dvc_context": None})
    result = evaluate_piecewise_curve(rule, selector, Decimal(27))

    assert result.status == "no_match"
    assert result.value is None
    assert result.variant_id is None


@pytest.mark.parametrize("x", (Decimal("NaN"), Decimal("Infinity")))
def test_curve_evaluation_rejects_non_finite_decimal_inputs(x: Decimal) -> None:
    rule = _synthetic_curve()
    with pytest.raises(EvaluationError, match="finite Decimal"):
        evaluate_piecewise_curve(rule, rule.variants[0].selector, x)


def test_curve_evaluation_rejects_float_inputs() -> None:
    rule = _synthetic_curve()
    with pytest.raises(EvaluationError, match="finite Decimal"):
        evaluate_piecewise_curve(rule, rule.variants[0].selector, 9.0)  # type: ignore[arg-type]
