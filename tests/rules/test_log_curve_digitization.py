"""Log-axis calibration and deterministic curve digitization. Synthetic only."""

from __future__ import annotations

from decimal import Decimal

from PIL import Image

from insulation_coordination.domain.rules import FaultTimeVoltageSelector, SourceReference
from insulation_coordination.rules.importer.curves import (
    OcrEngineIdentity,
    OcrToken,
    PixelBox,
    RawCurvePoint,
    RawCurveTrace,
    RawFigure,
    calibrate_log_axis,
    digitize_curve_figure,
)
from insulation_coordination.rules.importer.extract import canonical_model_sha256
from insulation_coordination.rules.importer.identify import CurveAuditSpec, StandardIdentity

IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="8" * 64,
    page_count=2,
    recipe_id="synthetic-curve",
)
SOURCE = SourceReference(
    document_id="synthetic-curve",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    figure="SF-9",
)


def synthetic_spec() -> CurveAuditSpec:
    return CurveAuditSpec(
        semantic_id="synthetic.curve.log",
        figure="SF-9",
        page_number=1,
        expected_bbox=(0.0, 0.0, 200.0, 200.0),
        expected_pixel_size=None,
        x_quantity_kind="duration",
        x_unit="s",
        y_quantity_kind="voltage",
        y_unit="V",
        x_scale="log10",
        y_scale="log10",
        variant_slots=(
            FaultTimeVoltageSelector(
                subject="accessible_circuit",
                voltage_basis="dc",
                dvc_context=None,
                environment_context=None,
            ),
        ),
        permitted_segment_types=("continuous", "plateau"),
        permitted_interpolations=("log_log", "constant"),
    )


class FakeOcrEngine:
    def __init__(self, tokens: tuple[OcrToken, ...]) -> None:
        self.identity = OcrEngineIdentity(name="fake", version="1", config_sha256="0" * 64)
        self._tokens = tokens

    def recognize(self, image: Image.Image) -> tuple[OcrToken, ...]:
        return self._tokens


def _tick(text: str, left: int, top: int) -> OcrToken:
    return OcrToken(
        text=text,
        confidence=Decimal("0.99"),
        box=PixelBox(left=left, top=top, right=left + 10, bottom=top + 8),
    )


def _figure(traces: tuple[RawCurveTrace, ...], tokens: tuple[OcrToken, ...]) -> RawFigure:
    figure = RawFigure(
        source=SOURCE,
        source_mode="image_xobject",
        source_bbox=(Decimal(0), Decimal(0), Decimal(200), Decimal(200)),
        pixel_size=(200, 200),
        transform=(Decimal(1), Decimal(0), Decimal(0), Decimal(1), Decimal(0), Decimal(0)),
        ocr_tokens=tokens,
        traces=traces,
        artifact_sha256="0" * 64,
    )
    return figure


def digitize_synthetic_chart(figure: RawFigure, ocr: FakeOcrEngine):
    return digitize_curve_figure(figure, synthetic_spec(), ocr, IDENTITY)


# Synthetic chart geometry: x axis pixels 20..180 map log10(s) 0..2 (1s..100s);
# y axis pixels 180..20 map log10(V) 1..3 (10V..1000V). One falling stroke, one
# plateau stroke. All values synthetic.
X_TICKS = (_tick("1", 40, 190), _tick("10", 110, 190), _tick("100", 180, 190))
Y_TICKS = (_tick("10", 2, 180), _tick("100", 2, 100), _tick("1000", 2, 20))


def _stroke(points: tuple[tuple[int, int], ...], width: str = "2") -> RawCurveTrace:
    return RawCurveTrace(
        id="trace-1",
        points=tuple(
            RawCurvePoint(
                x=Decimal(x), y=Decimal(y), space="pixel", primitive_ref=f"px-{index}"
            )
            for index, (x, y) in enumerate(points)
        ),
        stroke_width=Decimal(width),
    )


def _two_stroke_figure() -> RawFigure:
    falling = _stroke(((40, 20), (110, 100), (180, 180)))
    plateau = _stroke(((40, 100), (180, 100)))
    return RawFigure(
        source=SOURCE,
        source_mode="image_xobject",
        source_bbox=(Decimal(0), Decimal(0), Decimal(200), Decimal(200)),
        pixel_size=(200, 200),
        transform=(Decimal(1), Decimal(0), Decimal(0), Decimal(1), Decimal(0), Decimal(0)),
        ocr_tokens=(),
        traces=(falling, plateau),
        artifact_sha256="0" * 64,
    )


def test_calibration_fits_log_axes() -> None:
    calibration = calibrate_log_axis(
        ((Decimal(20), Decimal(0)), (Decimal(100), Decimal(1)), (Decimal(180), Decimal(2))),
        minor_grid_spacing_pixels=Decimal(80),
    )
    assert calibration.scale == "log10"
    assert calibration.slope > 0
    assert calibration.residual_pixels <= Decimal(40)


def test_digitize_is_deterministic() -> None:
    figure = _two_stroke_figure()
    first = digitize_synthetic_chart(figure, FakeOcrEngine((*X_TICKS, *Y_TICKS)))
    second = digitize_synthetic_chart(figure, FakeOcrEngine((*X_TICKS, *Y_TICKS)))
    assert first.proposed_rule is not None
    assert second.proposed_rule is not None
    assert first.calibration is not None
    assert first.conservatism is not None
    assert canonical_model_sha256(first.proposed_rule) == canonical_model_sha256(
        second.proposed_rule
    )
    assert first.calibration.x.scale == "log10"
    assert first.calibration.y.scale == "log10"
    assert first.conservatism.maximum_positive_voltage_error <= Decimal(0)
    assert first.conservatism.proven is True
    assert first.blocking_review_items == ()


def test_fewer_than_two_ticks_blocks() -> None:
    figure = _two_stroke_figure()
    result = digitize_synthetic_chart(figure, FakeOcrEngine((_tick("1", 20, 190),)))
    assert result.proposed_rule is None
    assert result.calibration is None
    assert any(
        item.code == "CURVE_CALIBRATION_FAILED" for item in result.blocking_review_items
    )


def test_non_monotone_ticks_block() -> None:
    figure = _two_stroke_figure()
    tokens = (
        _tick("100", 20, 190),
        _tick("10", 100, 190),
        _tick("1", 180, 190),
        *Y_TICKS,
    )
    result = digitize_synthetic_chart(figure, FakeOcrEngine(tokens))
    assert result.proposed_rule is None
    assert any(
        item.code == "CURVE_CALIBRATION_FAILED" for item in result.blocking_review_items
    )


def test_disconnected_stroke_blocks() -> None:
    figure = RawFigure(
        source=SOURCE,
        source_mode="image_xobject",
        source_bbox=(Decimal(0), Decimal(0), Decimal(200), Decimal(200)),
        pixel_size=(200, 200),
        transform=(Decimal(1), Decimal(0), Decimal(0), Decimal(1), Decimal(0), Decimal(0)),
        ocr_tokens=(),
        traces=(),
        artifact_sha256="0" * 64,
    )
    result = digitize_synthetic_chart(figure, FakeOcrEngine((*X_TICKS, *Y_TICKS)))
    assert result.proposed_rule is None
    assert any(
        item.code == "CURVE_TRACE_AMBIGUOUS" for item in result.blocking_review_items
    )


def test_out_of_domain_request_is_explicit_not_extrapolated() -> None:
    from insulation_coordination.rules.evaluator import evaluate_piecewise_curve

    figure = _two_stroke_figure()
    result = digitize_synthetic_chart(figure, FakeOcrEngine((*X_TICKS, *Y_TICKS)))
    assert result.proposed_rule is not None
    variant = result.proposed_rule.variants[0]
    outside = Decimal(10) ** (variant.x_axis.maximum + 1)
    evaluation = evaluate_piecewise_curve(
        result.proposed_rule,
        variant.selector,
        outside,
    )
    assert evaluation.status != "matched"
