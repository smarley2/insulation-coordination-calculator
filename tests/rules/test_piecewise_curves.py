from decimal import Decimal
from typing import get_args

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.rules import (
    CurveAxis,
    CurvePoint,
    CurveSegment,
    FaultTimeVoltageSelector,
    FaultTimeVoltageVariant,
    PiecewiseCurveRule,
    RuleKind,
    SourceReference,
)
from insulation_coordination.rules.evaluator import EvaluationError, select_curve_variant

SOURCE = SourceReference(
    document_id="synthetic-source",
    standard="SYNTHETIC-1",
    edition="1",
    page=1,
    clause="synthetic clause",
    figure="synthetic figure",
)
ARTIFACT_SHA256 = "a" * 64


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
                reviewed_artifact_sha256=ARTIFACT_SHA256,
            ),
        ),
        source=SOURCE,
    )


def test_curve_point_contains_only_semantic_engineering_coordinates() -> None:
    assert set(CurvePoint.model_fields) == {"x", "y"}


def test_rule_kind_is_shared_and_includes_mapping_and_curve() -> None:
    assert set(get_args(RuleKind)) == {
        "table",
        "formula",
        "mapping",
        "decision",
        "procedure",
        "guidance",
        "curve",
    }


def test_selector_matches_only_when_all_dimensions_are_exact() -> None:
    rule = _synthetic_curve()
    exact_selector = rule.variants[0].selector

    assert select_curve_variant(rule, exact_selector).status == "matched"
    assert (
        select_curve_variant(
            rule,
            exact_selector.model_copy(update={"dvc_context": None}),
        ).status
        == "no_match"
    )


def test_selector_requires_explicit_nullable_dimensions() -> None:
    with pytest.raises(ValidationError, match="dvc_context|environment_context"):
        FaultTimeVoltageSelector(  # type: ignore[call-arg]
            subject="accessible_circuit",
            voltage_basis="dc",
        )


def test_piecewise_curve_rejects_duplicate_selectors() -> None:
    rule = _synthetic_curve()
    with pytest.raises(ValueError, match="selector"):
        PiecewiseCurveRule(
            id=rule.id,
            variants=(rule.variants[0], rule.variants[0]),
            source=SOURCE,
        )


def test_piecewise_curve_rejects_duplicate_variant_ids() -> None:
    rule = _synthetic_curve()
    duplicate_id = rule.variants[0].model_copy(
        update={
            "selector": rule.variants[0].selector.model_copy(
                update={"dvc_context": "other-synthetic-dvc"}
            )
        }
    )
    with pytest.raises(ValueError, match="variant ID"):
        PiecewiseCurveRule(
            id=rule.id,
            variants=(rule.variants[0], duplicate_id),
            source=SOURCE,
        )


def test_selector_defends_against_unvalidated_runtime_duplicates() -> None:
    rule = _synthetic_curve()
    exact_selector = rule.variants[0].selector
    unvalidated_duplicate_rule = PiecewiseCurveRule.model_construct(
        id=rule.id,
        variants=(rule.variants[0], rule.variants[0]),
        source=SOURCE,
    )

    with pytest.raises(EvaluationError, match="multiple"):
        select_curve_variant(unvalidated_duplicate_rule, exact_selector)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("minimum", Decimal("NaN"), "finite"),
        ("maximum", Decimal("Infinity"), "finite"),
        ("maximum", Decimal(3), "exceed"),
    ),
)
def test_curve_axis_requires_ordered_finite_bounds(
    field: str,
    value: Decimal,
    message: str,
) -> None:
    values = {
        "quantity_kind": "fault-time",
        "unit": "ms",
        "scale": "linear",
        "minimum": Decimal(3),
        "maximum": Decimal(243),
        field: value,
    }
    with pytest.raises(ValidationError, match=message):
        CurveAxis(**values)  # type: ignore[arg-type]


def test_log_axis_requires_positive_bounds() -> None:
    with pytest.raises(ValidationError, match="positive"):
        CurveAxis(
            quantity_kind="fault-time",
            unit="ms",
            scale="log10",
            minimum=Decimal(0),
            maximum=Decimal(243),
        )


@pytest.mark.parametrize(
    ("update", "message"),
    (
        (
            {
                "points": (
                    CurvePoint(x=Decimal(3), y=Decimal(777)),
                    CurvePoint(x=Decimal(3), y=Decimal(271)),
                    CurvePoint(x=Decimal(243), y=Decimal(89)),
                )
            },
            "increasing",
        ),
        (
            {
                "points": (
                    {"x": Decimal(3), "y": Decimal(777)},
                    {"x": Decimal(27), "y": Decimal("NaN")},
                    {"x": Decimal(243), "y": Decimal(89)},
                )
            },
            "finite",
        ),
        (
            {
                "points": (
                    CurvePoint(x=Decimal(2), y=Decimal(777)),
                    CurvePoint(x=Decimal(27), y=Decimal(271)),
                    CurvePoint(x=Decimal(243), y=Decimal(89)),
                )
            },
            "axis range",
        ),
        (
            {
                "segments": (
                    CurveSegment(
                        start=0,
                        end=1,
                        segment_type="continuous",
                        interpolation="log_log",
                    ),
                )
            },
            "cover",
        ),
    ),
)
def test_variant_rejects_invalid_points_and_incomplete_segments(
    update: dict[str, object],
    message: str,
) -> None:
    variant = _synthetic_curve().variants[0]
    with pytest.raises(ValidationError, match=message):
        FaultTimeVoltageVariant.model_validate({**variant.model_dump(mode="python"), **update})


@pytest.mark.parametrize(
    ("segment_type", "interpolation"),
    (
        ("continuous", "constant"),
        ("plateau", "linear"),
        ("step", "log_log"),
    ),
)
def test_segment_type_requires_compatible_interpolation(
    segment_type: str,
    interpolation: str,
) -> None:
    variant = _synthetic_curve().variants[0]
    segments = (
        CurveSegment(
            start=0,
            end=1,
            segment_type=segment_type,  # type: ignore[arg-type]
            interpolation=interpolation,  # type: ignore[arg-type]
        ),
        variant.segments[1],
    )
    with pytest.raises(ValidationError, match="interpolation"):
        FaultTimeVoltageVariant.model_validate(
            {**variant.model_dump(mode="python"), "segments": segments}
        )


def test_plateau_requires_equal_endpoint_values() -> None:
    variant = _synthetic_curve().variants[0]
    segments = (
        CurveSegment(
            start=0,
            end=1,
            segment_type="plateau",
            interpolation="constant",
        ),
        variant.segments[1],
    )
    with pytest.raises(ValidationError, match="equal endpoint"):
        FaultTimeVoltageVariant.model_validate(
            {**variant.model_dump(mode="python"), "segments": segments}
        )


@pytest.mark.parametrize(
    ("axis", "points", "interpolation"),
    (
        (
            "x_axis",
            (
                CurvePoint(x=Decimal(0), y=Decimal(777)),
                CurvePoint(x=Decimal(27), y=Decimal(271)),
                CurvePoint(x=Decimal(243), y=Decimal(89)),
            ),
            "log_x",
        ),
        (
            "y_axis",
            (
                CurvePoint(x=Decimal(3), y=Decimal(0)),
                CurvePoint(x=Decimal(27), y=Decimal(271)),
                CurvePoint(x=Decimal(243), y=Decimal(89)),
            ),
            "log_y",
        ),
    ),
)
def test_log_interpolation_requires_positive_transformed_coordinates(
    axis: str,
    points: tuple[CurvePoint, ...],
    interpolation: str,
) -> None:
    variant = _synthetic_curve().variants[0]
    updated_axis = getattr(variant, axis).model_copy(
        update={"scale": "linear", "minimum": Decimal(0)}
    )
    segments = (
        variant.segments[0].model_copy(update={"interpolation": interpolation}),
        variant.segments[1],
    )
    with pytest.raises(ValidationError, match="positive"):
        FaultTimeVoltageVariant.model_validate(
            {
                **variant.model_dump(mode="python"),
                axis: updated_axis,
                "points": points,
                "segments": segments,
            }
        )


def test_variant_requires_valid_reviewed_artifact_sha256() -> None:
    variant = _synthetic_curve().variants[0]
    with pytest.raises(ValidationError, match="SHA-256"):
        FaultTimeVoltageVariant.model_validate(
            {**variant.model_dump(mode="python"), "reviewed_artifact_sha256": "not-a-hash"}
        )


def test_voltage_basis_vocabulary_carries_an_unspecified_ac_token() -> None:
    """Figure 7 identifies its variant as AC without specifying RMS or peak.

    The token exists so that contract can be stated exactly, instead of a specific basis
    being asserted on the source's behalf.
    """
    permitted = get_args(FaultTimeVoltageSelector.model_fields["voltage_basis"].annotation)
    assert set(permitted) == {"ac_rms", "ac_peak", "ac_unspecified", "dc"}


def test_a_selector_can_carry_the_unspecified_ac_basis() -> None:
    selector = FaultTimeVoltageSelector(
        subject="conductive_accessible_part",
        voltage_basis="ac_unspecified",
        dvc_context=None,
        environment_context=None,
    )
    assert selector.voltage_basis == "ac_unspecified"
