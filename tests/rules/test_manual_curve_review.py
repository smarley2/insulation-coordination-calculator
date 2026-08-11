# The task brief specifies these exact Decimal string literals.
# ruff: noqa: FURB157

from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import CurvePoint
from insulation_coordination.rules.importer.curves import (
    ManualPlotCalibration,
    infer_curve_segments,
    pixel_to_source_point,
    source_point_to_pixel,
)


def _calibration() -> ManualPlotCalibration:
    return ManualPlotCalibration(
        figure_artifact_sha256="0" * 64,
        left=Decimal("20"),
        top=Decimal("10"),
        right=Decimal("320"),
        bottom=Decimal("210"),
        x_min=Decimal("1"),
        x_max=Decimal("1000"),
        y_min=Decimal("1"),
        y_max=Decimal("100"),
    )


def test_manual_log_calibration_round_trips_without_float() -> None:
    calibration = _calibration()
    point = pixel_to_source_point(Decimal("120"), Decimal("110"), calibration)

    assert point.x == Decimal("10")
    assert point.y == Decimal("10")
    assert source_point_to_pixel(point, calibration) == (
        Decimal("120"),
        Decimal("110"),
    )


def test_segments_are_inferred_from_adjacent_y_values() -> None:
    points = (
        CurvePoint(x=Decimal("1"), y=Decimal("100")),
        CurvePoint(x=Decimal("10"), y=Decimal("100")),
        CurvePoint(x=Decimal("100"), y=Decimal("20")),
        CurvePoint(x=Decimal("1000"), y=Decimal("20")),
    )

    assert tuple(
        (segment.start, segment.end, segment.segment_type, segment.interpolation)
        for segment in infer_curve_segments(points)
    ) == (
        (0, 1, "plateau", "constant"),
        (1, 2, "continuous", "log_log"),
        (2, 3, "plateau", "constant"),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (("right", "20"), ("bottom", "10"), ("x_min", "0"), ("y_max", "1")),
)
def test_manual_calibration_rejects_invalid_bounds(field: str, value: str) -> None:
    payload = _calibration().model_dump(mode="python")
    payload[field] = Decimal(value)
    with pytest.raises(ValueError):
        ManualPlotCalibration.model_validate(payload)


def test_pixel_conversion_rejects_point_outside_plot() -> None:
    with pytest.raises(ValueError, match="outside reviewed plot rectangle"):
        pixel_to_source_point(Decimal("19"), Decimal("110"), _calibration())
