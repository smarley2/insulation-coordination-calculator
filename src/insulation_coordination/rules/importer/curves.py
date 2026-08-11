"""Curve digitization boundary: OCR protocol and the deterministic Tesseract adapter.

OCR tokens carry pixel geometry only; calibration to engineering units lives in the
curve pipeline, and source images never leave the private draft. Tesseract runs as a
local CLI with fixed argv, no shell, and a timeout; every failure mode raises a
blocking ``OcrError`` instead of returning a guessed result.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import subprocess
import tempfile
from collections import deque
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast, runtime_checkable

import pdfplumber
from PIL import Image
from pydantic import Field, model_validator
from pydantic import ValidationError as PydanticValidationError
from pypdf._page import PageObject

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.rules.importer.extract import ExtractionError, ImportReviewItem

if TYPE_CHECKING:
    from insulation_coordination.rules.importer.identify import (
        CurveAuditSpec,
        StandardIdentity,
    )
from insulation_coordination.domain.rules import (
    CurvePoint,
    CurveSegment,
    FaultTimeVoltageVariant,
    Identifier,
    PiecewiseCurveRule,
    SourceReference,
)


class OcrError(ValueError):
    """OCR could not produce a trustworthy result; extraction must block."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class PixelBox(FrozenModel):
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    right: int = Field(gt=0)
    bottom: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> PixelBox:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("pixel box edges must be ordered")
        return self


class OcrToken(FrozenModel):
    text: str
    confidence: Decimal = Field(ge=0, le=1)
    box: PixelBox


class OcrEngineIdentity(FrozenModel):
    name: Identifier
    version: str
    config_sha256: str = Field(pattern=r"[0-9a-f]{64}")


@runtime_checkable
class OcrEngine(Protocol):
    @property
    def identity(self) -> OcrEngineIdentity: ...

    def recognize(self, image: Image.Image) -> tuple[OcrToken, ...]: ...


class TesseractOcrEngine:
    """Local Tesseract CLI adapter: fixed argv, TSV stdout, deterministic order."""

    def __init__(
        self,
        *,
        executable: str = "tesseract",
        version: str = "unknown",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._executable = executable
        self._version = version
        self.timeout_seconds = timeout_seconds

    @property
    def identity(self) -> OcrEngineIdentity:
        config = f"argv:--psm 6 tsv;timeout:{self.timeout_seconds}"
        return OcrEngineIdentity(
            name="tesseract",
            version=self._version,
            config_sha256=hashlib.sha256(config.encode("utf-8")).hexdigest(),
        )

    def recognize(self, image: Image.Image) -> tuple[OcrToken, ...]:
        fd, name = tempfile.mkstemp(suffix=".png")
        path = Path(name)
        try:
            image.save(path, format="PNG")
            argv = [self._executable, str(path), "stdout", "--psm", "6", "tsv"]
            try:
                completed = subprocess.run(
                    argv,
                    shell=False,
                    check=False,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                )
            except FileNotFoundError as error:
                raise OcrError(
                    "OCR_UNAVAILABLE", f"OCR executable not found: {self._executable}"
                ) from error
            except subprocess.TimeoutExpired as error:
                raise OcrError(
                    "OCR_FAILED", f"OCR timed out after {self.timeout_seconds}s"
                ) from error
            if completed.returncode != 0:
                raise OcrError(
                    "OCR_FAILED", f"OCR exited with status {completed.returncode}"
                )
            return _parse_tsv(completed.stdout)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            path.unlink(missing_ok=True)


def _parse_tsv(payload: bytes) -> tuple[OcrToken, ...]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OcrError("OCR_FAILED", "OCR returned non-UTF-8 output") from error
    rows = csv.DictReader(io.StringIO(text), delimiter="\t")
    tokens: list[tuple[tuple[int, int, int, int], OcrToken]] = []
    for row in rows:
        word = (row.get("text") or "").strip()
        if not word or row.get("level") != "5":
            continue
        try:
            confidence = Decimal(row["conf"]) / Decimal(100)
            left = int(row["left"])
            top = int(row["top"])
            sort_key = (
                top,
                left,
                int(row["line_num"]),
                int(row["word_num"]),
            )
            token = OcrToken(
                text=word,
                confidence=confidence,
                box=PixelBox(
                    left=left,
                    top=top,
                    right=left + int(row["width"]),
                    bottom=top + int(row["height"]),
                ),
            )
        except (
            InvalidOperation,
            TypeError,
            ValueError,
            KeyError,
            PydanticValidationError,
        ) as error:
            raise OcrError("OCR_FAILED", "OCR returned malformed TSV") from error
        tokens.append((sort_key, token))
    return tuple(token for _, token in sorted(tokens, key=lambda pair: pair[0]))


__all__ = [
    "LocatedCurveSource",
    "ManualPlotCalibration",
    "OcrEngine",
    "OcrEngineIdentity",
    "OcrError",
    "OcrToken",
    "PixelBox",
    "RawCurvePoint",
    "RawCurveTrace",
    "RawFigure",
    "TesseractOcrEngine",
    "extract_raw_figure",
    "infer_curve_segments",
    "locate_curve_source",
    "pixel_to_source_point",
    "source_point_to_pixel",
]


class RawCurvePoint(FrozenModel):
    """One source-geometry point: PDF or pixel space, plus its primitive identity."""

    x: Decimal
    y: Decimal
    space: Literal["pdf", "pixel"]
    primitive_ref: str


class RawCurveTrace(FrozenModel):
    id: Identifier
    points: tuple[RawCurvePoint, ...] = Field(min_length=1)
    stroke_width: Decimal = Field(gt=0)


class RawFigure(FrozenModel):
    source: SourceReference
    source_mode: Literal["vector_path", "image_xobject"]
    source_bbox: tuple[Decimal, Decimal, Decimal, Decimal]
    pixel_size: tuple[int, int] | None
    transform: tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]
    ocr_tokens: tuple[OcrToken, ...]
    traces: tuple[RawCurveTrace, ...]
    artifact_sha256: str = Field(pattern=r"[0-9a-f]{64}")


class ManualPlotCalibration(FrozenModel):
    figure_artifact_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    left: Decimal
    top: Decimal
    right: Decimal
    bottom: Decimal
    x_min: Decimal
    x_max: Decimal
    y_min: Decimal
    y_max: Decimal

    @model_validator(mode="after")
    def _valid_bounds(self) -> Self:
        values = (
            self.left,
            self.top,
            self.right,
            self.bottom,
            self.x_min,
            self.x_max,
            self.y_min,
            self.y_max,
        )
        if any(not value.is_finite() for value in values):
            raise ValueError("manual curve calibration values must be finite")
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("manual curve plot rectangle must be ordered")
        if self.x_min <= 0 or self.y_min <= 0:
            raise ValueError("manual log-axis bounds must be positive")
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError("manual curve axis bounds must be ordered")
        return self


_PATH_OPERATORS = {"m", "l", "c", "v", "y", "h", "re"}
_PAINT_OPERATORS = {"S", "s", "f", "f*", "B", "B*", "b", "b*"}
_PATH_POINT_OPERATORS = ("m", "l", "re")
_LOSSLESS_IMAGE_FILTERS = frozenset({"/FlateDecode", "/LZWDecode", ""})


def _decimal(value: object) -> Decimal:
    return Decimal(str(float(str(value))))


class LocatedCurveSource(FrozenModel):
    """The located source for one figure: mode plus, for images, the XObject name
    and its placement matrix at `Do` time."""

    mode: Literal["vector_path", "image_xobject"]
    image_name: str | None = None
    transform: tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]


def locate_curve_source(
    reader_page: PageObject,
    spec: CurveAuditSpec,
) -> Literal["vector_path", "image_xobject"]:
    """Decide the source mode: vector paths inside the recipe bbox win; a single
    recipe-matching lossless image XObject is the fallback; anything else blocks."""

    return _locate(reader_page, spec).mode


def _locate(reader_page: PageObject, spec: CurveAuditSpec) -> LocatedCurveSource:
    reader = reader_page.indirect_reference.pdf if reader_page.indirect_reference else None
    content = reader_page.get_contents()
    if content is None:
        raise ExtractionError(f"CURVE_SOURCE_MISSING: no content stream for {spec.figure}")
    from pypdf.generic import ContentStream

    stream = ContentStream(content, reader)
    x0, top, x1, bottom = spec.expected_bbox
    page_height = float(reader_page.mediabox.height)
    pdf_bottom = page_height - bottom
    pdf_top = page_height - top

    vector_points = 0
    image_operands: list[tuple[str, tuple[float, float, float, float, float, float]]] = []
    current_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    active_clip: tuple[float, float, float, float] | None = None
    pending_rectangle: tuple[float, float, float, float] | None = None
    clipping_seen = False
    stack: list[
        tuple[
            tuple[float, float, float, float, float, float],
            tuple[float, float, float, float] | None,
        ]
    ] = []
    for operands, operator in stream.operations:
        op = operator.decode() if isinstance(operator, bytes) else str(operator)
        if op == "q":
            stack.append((current_matrix, active_clip))
        elif op == "Q":
            if stack:
                current_matrix, active_clip = stack.pop()
        elif op in {"W", "W*"}:
            clipping_seen = True
            if pending_rectangle is None:
                raise ExtractionError(
                    f"CURVE_SOURCE_CLIPPED: non-rectangular clipping path for {spec.figure}"
                )
            if active_clip is None:
                active_clip = pending_rectangle
            else:
                active_clip = (
                    max(active_clip[0], pending_rectangle[0]),
                    max(active_clip[1], pending_rectangle[1]),
                    min(active_clip[2], pending_rectangle[2]),
                    min(active_clip[3], pending_rectangle[3]),
                )
        elif op == "cm":
            a, b, c, d, e, f = (float(str(value)) for value in operands)
            current_matrix = (a, b, c, d, e, f)
        elif op == "Do":
            a, b, c, d, e, f = current_matrix
            # Axis-aligned placement only; rotation/skew coefficients are ignored
            # here and would need a reviewed generalization.
            corners = (
                (e, f),
                (a + e, f),
                (e, d + f),
                (a + e, d + f),
            )
            ix0 = min(point[0] for point in corners)
            ix1 = max(point[0] for point in corners)
            iy0 = min(point[1] for point in corners)
            iy1 = max(point[1] for point in corners)
            if ix0 < x1 and ix1 > x0 and iy0 < pdf_top and iy1 > pdf_bottom:
                # PDF producers commonly round a clip rectangle and the matching
                # image matrix independently. Sub-point differences preserve the
                # same source geometry; larger crops still block.
                clip_tolerance = 0.1
                if active_clip is not None and not (
                    active_clip[0] <= ix0 + clip_tolerance
                    and active_clip[1] <= iy0 + clip_tolerance
                    and active_clip[2] >= ix1 - clip_tolerance
                    and active_clip[3] >= iy1 - clip_tolerance
                ):
                    raise ExtractionError(
                        f"CURVE_SOURCE_CLIPPED: image is cropped for {spec.figure}"
                    )
                image_operands.append((str(operands[0]), current_matrix))
        elif op in _PATH_POINT_OPERATORS:
            numbers = [float(str(value)) for value in operands]
            px, py = numbers[0], numbers[1]
            tx = current_matrix[0] * px + current_matrix[2] * py + current_matrix[4]
            ty = current_matrix[1] * px + current_matrix[3] * py + current_matrix[5]
            if x0 <= tx <= x1 and pdf_bottom <= ty <= pdf_top:
                vector_points += 1
            if op == "re":
                width, height = numbers[2], numbers[3]
                rectangle_corners = tuple(
                    (
                        current_matrix[0] * rx + current_matrix[2] * ry + current_matrix[4],
                        current_matrix[1] * rx + current_matrix[3] * ry + current_matrix[5],
                    )
                    for rx, ry in (
                        (px, py),
                        (px + width, py),
                        (px, py + height),
                        (px + width, py + height),
                    )
                )
                pending_rectangle = (
                    min(point[0] for point in rectangle_corners),
                    min(point[1] for point in rectangle_corners),
                    max(point[0] for point in rectangle_corners),
                    max(point[1] for point in rectangle_corners),
                )
            else:
                pending_rectangle = None
        elif op in {"n", *_PAINT_OPERATORS}:
            pending_rectangle = None
    if vector_points >= 2:
        if clipping_seen:
            raise ExtractionError(
                f"CURVE_SOURCE_CLIPPED: clipping path present for {spec.figure}"
            )
        return LocatedCurveSource(
            mode="vector_path",
            image_name=None,
            transform=(
                Decimal(1), Decimal(0), Decimal(0), Decimal(1), Decimal(0), Decimal(0),
            ),
        )
    names = {name for name, _ in image_operands}
    if len(names) > 1:
        raise ExtractionError(
            f"CURVE_SOURCE_AMBIGUOUS: {len(names)} image candidates for {spec.figure}"
        )
    if not image_operands:
        raise ExtractionError(f"CURVE_SOURCE_MISSING: no vector paths or image for {spec.figure}")
    name, matrix = image_operands[0]
    return LocatedCurveSource(
        mode="image_xobject",
        image_name=name,
        transform=tuple(Decimal(str(value)) for value in matrix),  # type: ignore[arg-type]
    )


def _vector_traces(
    reader_page: PageObject,
    spec: CurveAuditSpec,
) -> tuple[RawCurveTrace, ...]:
    reader = reader_page.indirect_reference.pdf if reader_page.indirect_reference else None
    from pypdf.generic import ContentStream

    stream = ContentStream(reader_page.get_contents(), reader)
    x0, top, x1, bottom = spec.expected_bbox
    page_height = float(reader_page.mediabox.height)
    pdf_bottom = page_height - bottom
    pdf_top = page_height - top

    traces: list[RawCurveTrace] = []
    current_points: list[RawCurvePoint] = []
    stroke_width = Decimal(1)
    current_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    stack: list[tuple[float, float, float, float, float, float]] = []
    primitive_index = 0

    def flush() -> None:
        nonlocal current_points
        if len(current_points) >= 2:
            traces.append(
                RawCurveTrace(
                    id=f"trace-{len(traces) + 1}",
                    points=tuple(current_points),
                    stroke_width=stroke_width,
                )
            )
        current_points = []

    for operands, operator in stream.operations:
        op = operator.decode() if isinstance(operator, bytes) else str(operator)
        if op == "q":
            stack.append(current_matrix)
        elif op == "Q":
            if stack:
                current_matrix = stack.pop()
        elif op == "cm":
            a, b, c, d, e, f = (float(str(value)) for value in operands)
            current_matrix = (a, b, c, d, e, f)
        elif op == "w":
            stroke_width = _decimal(operands[0])
        elif op in _PATH_POINT_OPERATORS:
            primitive_index += 1
            numbers = [float(str(value)) for value in operands]
            px, py = numbers[0], numbers[1]
            tx = current_matrix[0] * px + current_matrix[2] * py + current_matrix[4]
            ty = current_matrix[1] * px + current_matrix[3] * py + current_matrix[5]
            if not (x0 <= tx <= x1 and pdf_bottom <= ty <= pdf_top):
                continue
            if op == "m":
                flush()
            current_points.append(
                RawCurvePoint(
                    x=_decimal(tx),
                    y=_decimal(ty),
                    space="pdf",
                    primitive_ref=f"op-{primitive_index}:{op}",
                )
            )
        elif op in _PAINT_OPERATORS:
            flush()
    flush()
    if not traces:
        raise ExtractionError(
            f"CURVE_SOURCE_MISSING: no complete vector traces for {spec.figure}"
        )
    return tuple(traces)


def _raster_traces(
    image: Image.Image,
    tokens: tuple[OcrToken, ...],
    expected_traces: int | None = None,
) -> tuple[RawCurveTrace, ...]:
    """Recover unambiguous long dark strokes from a lossless chart image.

    OCR boxes and full-length grid/axis rows are removed first. Multiple equally
    plausible long components are deliberately returned as separate traces so the
    digitizer blocks for maintainer association instead of guessing.
    """

    rgb = image.convert("RGB")
    width, height = rgb.size
    colored: list[tuple[int, int, tuple[int, int, int]]] = []
    for y in range(max(1, int(height * 0.02)), min(height, int(height * 0.88))):
        for x in range(max(1, int(width * 0.04)), min(width, int(width * 0.98))):
            red, green, blue = cast(tuple[int, int, int], rgb.getpixel((x, y)))
            if max(red, green, blue) - min(red, green, blue) >= 35:
                colored.append((x, y, (red, green, blue)))
    if colored:
        histogram: dict[tuple[int, int, int], int] = {}
        for _x, _y, color in colored:
            histogram[color] = histogram.get(color, 0) + 1
        minimum_pixels = max(20, width // 8)
        candidates = {
            color: count for color, count in histogram.items() if count >= minimum_pixels
        }
        anchors: list[tuple[int, int, int]] = []
        while candidates and (
            expected_traces is None or len(anchors) < expected_traces
        ):
            if not anchors:
                selected = max(candidates, key=lambda color: (candidates[color], color))
            else:
                selected = max(
                    candidates,
                    key=lambda color: (
                        min(
                            sum(
                                (component - existing) ** 2
                                for component, existing in zip(color, anchor)
                            )
                            for anchor in anchors
                        )
                        * candidates[color],
                        color,
                    ),
                )
            anchors.append(selected)
            candidates = {
                color: count
                for color, count in candidates.items()
                if sum(
                    (component - existing) ** 2
                    for component, existing in zip(color, selected)
                )
                >= 45**2
            }
        color_traces: list[RawCurveTrace] = []
        for anchor in anchors:
            cluster = set()
            for x, y, color in colored:
                distances = tuple(
                    sum(
                        (component - expected) ** 2
                        for component, expected in zip(color, candidate)
                    )
                    for candidate in anchors
                )
                if distances.index(min(distances)) == anchors.index(anchor) and min(distances) <= 100**2:
                    cluster.add((x, y))
            if not cluster:
                continue
            x_span = max(x for x, _ in cluster) - min(x for x, _ in cluster)
            if x_span < width // 3:
                continue
            color_by_x: dict[int, list[int]] = {}
            for x, y in cluster:
                color_by_x.setdefault(x, []).append(y)
            points = tuple(
                RawCurvePoint(
                    x=Decimal(x),
                    y=Decimal(sorted(ys)[len(ys) // 2]),
                    space="pixel",
                    primitive_ref=f"color-column-{x}",
                )
                for x, ys in sorted(color_by_x.items())
            )
            color_traces.append(
                RawCurveTrace(
                    id=f"trace-{len(color_traces) + 1}",
                    points=points,
                    stroke_width=max(
                        Decimal(1), Decimal(len(cluster)) / Decimal(len(points))
                    ),
                )
            )
        if color_traces:

            def same_stroke(
                left: RawCurveTrace, right: RawCurveTrace
            ) -> bool:
                left_y = {point.x: point.y for point in left.points}
                right_y = {point.x: point.y for point in right.points}
                shared = left_y.keys() & right_y.keys()
                required_overlap = Decimal("0.8") * Decimal(
                    min(len(left_y), len(right_y))
                )
                if Decimal(len(shared)) < required_overlap:
                    return False
                close = sum(
                    abs(left_y[x] - right_y[x]) <= Decimal(3) for x in shared
                )
                return Decimal(close) >= Decimal("0.8") * Decimal(len(shared))

            distinct: list[RawCurveTrace] = []
            for trace in color_traces:
                if not any(same_stroke(trace, existing) for existing in distinct):
                    distinct.append(trace)

            def same_ink_hue(
                left: tuple[int, int, int], right: tuple[int, int, int]
            ) -> bool:
                left_ink = tuple(255 - component for component in left)
                right_ink = tuple(255 - component for component in right)
                dot = sum(
                    component * existing
                    for component, existing in zip(left_ink, right_ink)
                )
                return (
                    dot**2 * 10_000
                    >= 9_604
                    * sum(component**2 for component in left_ink)
                    * sum(component**2 for component in right_ink)
                )

            def same_antialiased_stroke(
                left: RawCurveTrace, right: RawCurveTrace
            ) -> bool:
                left_y = {point.x: point.y for point in left.points}
                right_y = {point.x: point.y for point in right.points}
                shared = left_y.keys() & right_y.keys()
                if Decimal(len(shared)) < Decimal("0.8") * Decimal(
                    min(len(left_y), len(right_y))
                ):
                    return False
                close = sum(
                    abs(left_y[x] - right_y[x]) <= Decimal(10) for x in shared
                )
                return Decimal(close) >= Decimal("0.8") * Decimal(len(shared))

            def direct_color_trace(
                color: tuple[int, int, int], trace_id: str
            ) -> RawCurveTrace | None:
                pixels = {
                    (x, y)
                    for x, y, observed in colored
                    if sum(
                        (component - expected) ** 2
                        for component, expected in zip(observed, color)
                    )
                    <= 35**2
                }
                if not pixels:
                    return None
                x_span = max(x for x, _ in pixels) - min(x for x, _ in pixels)
                if x_span < width // 3:
                    return None
                by_x: dict[int, list[int]] = {}
                for x, y in pixels:
                    by_x.setdefault(x, []).append(y)
                return RawCurveTrace(
                    id=trace_id,
                    points=tuple(
                        RawCurvePoint(
                            x=Decimal(x),
                            y=Decimal(sorted(ys)[len(ys) // 2]),
                            space="pixel",
                            primitive_ref=f"color-column-{x}",
                        )
                        for x, ys in sorted(by_x.items())
                    ),
                    stroke_width=max(
                        Decimal(1),
                        Decimal(len(pixels)) / Decimal(len(by_x)),
                    ),
                )

            direct_anchors = tuple(
                direct_color_trace(selected, f"anchor-{index}")
                for index, selected in enumerate(anchors, start=1)
            )
            for color in candidates:
                extra = direct_color_trace(color, f"trace-{len(distinct) + 1}")
                if extra is None:
                    continue
                if any(
                    same_ink_hue(color, selected)
                    and direct_anchor is not None
                    and same_antialiased_stroke(extra, direct_anchor)
                    for selected, direct_anchor in zip(
                        anchors, direct_anchors, strict=True
                    )
                ):
                    continue
                if not any(same_stroke(extra, existing) for existing in distinct):
                    distinct.append(extra)
            color_traces = distinct

            def endpoint_y(trace: RawCurveTrace) -> Decimal:
                count = max(3, len(trace.points) // 20)
                tail = trace.points[-count:]
                return sum(point.y for point in tail) / Decimal(len(tail))

            ordered = sorted(color_traces, key=endpoint_y)
            return tuple(
                trace.model_copy(update={"id": f"trace-{index}"})
                for index, trace in enumerate(ordered, start=1)
            )

    gray = rgb.convert("L")
    width, height = gray.size
    dark: set[tuple[int, int]] = set()
    for y in range(height):
        for x in range(width):
            value = gray.getpixel((x, y))
            if isinstance(value, int) and value < 96:
                dark.add((x, y))
    for token in tokens:
        for y in range(max(0, token.box.top - 1), min(height, token.box.bottom + 1)):
            for x in range(max(0, token.box.left - 1), min(width, token.box.right + 1)):
                dark.discard((x, y))
    row_counts = [sum((x, y) in dark for x in range(width)) for y in range(height)]
    column_counts = [sum((x, y) in dark for y in range(height)) for x in range(width)]
    grid_rows = {y for y, count in enumerate(row_counts) if count >= max(3, width // 2)}
    grid_columns = {
        x for x, count in enumerate(column_counts) if count >= max(3, height // 2)
    }
    dark = {
        point for point in dark if point[0] not in grid_columns and point[1] not in grid_rows
    }

    components: list[set[tuple[int, int]]] = []
    remaining = set(dark)
    while remaining:
        seed = min(remaining, key=lambda point: (point[0], point[1]))
        remaining.remove(seed)
        component = {seed}
        pending = deque((seed,))
        while pending:
            x, y = pending.popleft()
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    candidate = (x + dx, y + dy)
                    if candidate in remaining:
                        remaining.remove(candidate)
                        component.add(candidate)
                        pending.append(candidate)
        x_span = max(x for x, _ in component) - min(x for x, _ in component)
        if x_span >= max(4, width // 5) and len(component) >= max(8, width // 10):
            components.append(component)
    if not components:
        return ()
    maximum_span = max(
        max(x for x, _ in component) - min(x for x, _ in component)
        for component in components
    )
    plausible = tuple(
        component
        for component in components
        if max(x for x, _ in component) - min(x for x, _ in component)
        >= Decimal("0.8") * maximum_span
    )
    traces: list[RawCurveTrace] = []
    for index, component in enumerate(plausible, start=1):
        raster_by_x: dict[int, list[int]] = {}
        for x, y in component:
            raster_by_x.setdefault(x, []).append(y)
        points = tuple(
            RawCurvePoint(
                x=Decimal(x),
                y=Decimal(sorted(ys)[len(ys) // 2]),
                space="pixel",
                primitive_ref=f"raster-column-{x}",
            )
            for x, ys in sorted(raster_by_x.items())
        )
        traces.append(
            RawCurveTrace(
                id=f"trace-{index}",
                points=points,
                stroke_width=max(Decimal(1), Decimal(len(component)) / Decimal(len(points))),
            )
        )
    return tuple(traces)


def _curve_ocr_tokens(image: Image.Image, ocr: OcrEngine) -> tuple[OcrToken, ...]:
    """OCR the complete artifact plus enlarged axis strips in source-pixel space."""

    tokens = list(ocr.recognize(image))
    width, height = image.size
    crop_boxes = (
        (int(width * 0.05), int(height * 0.75), width, int(height * 0.90)),
        (0, 0, int(width * 0.17), int(height * 0.88)),
    )
    scale = 2
    for left, top, right, bottom in crop_boxes:
        crop = image.crop((left, top, right, bottom))
        enlarged = crop.resize((crop.width * scale, crop.height * scale))
        for token in ocr.recognize(enlarged):
            tokens.append(
                token.model_copy(
                    update={
                        "box": PixelBox(
                            left=left + token.box.left // scale,
                            top=top + token.box.top // scale,
                            right=left + max(token.box.left // scale + 1, token.box.right // scale),
                            bottom=top + max(token.box.top // scale + 1, token.box.bottom // scale),
                        )
                    }
                )
            )
    return tuple(tokens)


def extract_raw_figure(
    reader_page: PageObject,
    plumber_page: pdfplumber.page.Page,
    spec: CurveAuditSpec,
    ocr: OcrEngine,
    identity: StandardIdentity,
) -> RawFigure:
    """Extract reviewed source geometry for one curve figure, vector-first."""

    source = SourceReference(
        document_id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        page=spec.page_number,
        figure=spec.figure,
    )
    bbox = tuple(Decimal(str(value)) for value in spec.expected_bbox)
    located = _locate(reader_page, spec)
    if located.mode == "vector_path":
        pdf_traces = _vector_traces(reader_page, spec)
        rendered = plumber_page.crop(spec.expected_bbox).to_image(resolution=110).original
        try:
            tokens = _curve_ocr_tokens(rendered, ocr)
        except OcrError:
            tokens = ()
        width, height = rendered.size
        x0, top, x1, bottom = spec.expected_bbox
        page_height = float(reader_page.mediabox.height)
        pdf_top = page_height - top
        scale_x = Decimal(width) / Decimal(str(x1 - x0))
        scale_y = Decimal(height) / Decimal(str(bottom - top))
        traces = tuple(
            trace.model_copy(
                update={
                    "points": tuple(
                        point.model_copy(
                            update={
                                "x": (point.x - Decimal(str(x0))) * scale_x,
                                "y": (Decimal(str(pdf_top)) - point.y) * scale_y,
                                "space": "pixel",
                            }
                        )
                        for point in trace.points
                    )
                }
            )
            for trace in pdf_traces
        )
        payload = (
            f"vector:{spec.semantic_id}:{spec.expected_bbox}:"
            f"{ocr.identity.name}:{ocr.identity.version}:{ocr.identity.config_sha256}:"
            + ";".join(token.text for token in tokens)
            + ":"
            + ";".join(
                f"{trace.id}:{','.join(f'{p.x}/{p.y}' for p in trace.points)}"
                for trace in traces
            )
        )
        return RawFigure(
            source=source,
            source_mode="vector_path",
            source_bbox=bbox,  # type: ignore[arg-type]
            pixel_size=(width, height),
            transform=(
                scale_x,
                Decimal(0),
                Decimal(0),
                -scale_y,
                -Decimal(str(x0)) * scale_x,
                Decimal(str(pdf_top)) * scale_y,
            ),
            ocr_tokens=tokens,
            traces=traces,
            artifact_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        )

    # Match the located XObject by name, not page-global position: decorative
    # images elsewhere on the page must not enter the figure artifact.
    # The filter gate runs on the raw XObject dictionary first: a lossy or
    # undecodable image must block before any decode attempt, because Pillow
    # failure modes are not trustworthy evidence about the source bytes.
    resources = reader_page.get("/Resources")
    xobjects = getattr(resources, "get", lambda _key: None)("/XObject")
    xobject = None
    if xobjects is not None:
        entry = getattr(xobjects, "get", lambda _key: None)(located.image_name)
        if entry is not None:
            xobject = entry.get_object()
    if xobject is None:
        raise ExtractionError(
            f"CURVE_SOURCE_MISSING: image XObject {located.image_name} for {spec.figure}"
        )
    filters = xobject.get("/Filter")
    if isinstance(filters, list):
        filter_names = {str(item) for item in filters}
    elif filters is None:
        filter_names = set()
    else:
        filter_names = {str(filters)}
    if not filter_names <= _LOSSLESS_IMAGE_FILTERS:
        raise ExtractionError(
            f"CURVE_SOURCE_LOSSY: unsupported image filter "
            f"{sorted(filter_names - _LOSSLESS_IMAGE_FILTERS)} for {spec.figure}"
        )
    image_name = located.image_name
    assert image_name is not None
    bare_name = image_name.removeprefix("/")
    expected_names = {image_name, bare_name, f"{image_name}.png", f"{bare_name}.png"}
    matched = [image for image in reader_page.images if image.name in expected_names]
    if len(matched) != 1:
        raise ExtractionError(
            f"CURVE_SOURCE_AMBIGUOUS: {len(matched)} images match {located.image_name} "
            f"for {spec.figure}"
        )
    image_file = matched[0]
    image = image_file.image
    if image is None:
        raise ExtractionError(f"CURVE_SOURCE_MISSING: image bytes for {spec.figure}")
    if spec.expected_pixel_size is not None and image.size != spec.expected_pixel_size:
        raise ExtractionError(
            f"CURVE_SOURCE_MISMATCH: pixel size differs for {spec.figure}"
        )
    try:
        tokens = _curve_ocr_tokens(image, ocr)
    except OcrError:
        tokens = ()
    traces = _raster_traces(image, tokens, len(spec.variant_slots))
    if image_file.indirect_reference is None:
        raise ExtractionError("CURVE_SOURCE_MISSING: image has no indirect reference")
    get_data = getattr(xobject, "get_data", None)
    if get_data is None:
        raise ExtractionError(f"CURVE_SOURCE_MISSING: image stream for {spec.figure}")
    byte_hash = hashlib.sha256(get_data()).hexdigest()
    payload = (
        f"image:{spec.semantic_id}:{spec.expected_bbox}:{byte_hash}:"
        f"transform:{located.transform}:"
        f"{ocr.identity.name}:{ocr.identity.version}:{ocr.identity.config_sha256}:"
        + ";".join(token.text for token in tokens)
    )
    return RawFigure(
        source=source,
        source_mode="image_xobject",
        source_bbox=bbox,  # type: ignore[arg-type]
        pixel_size=(int(image.size[0]), int(image.size[1])),
        transform=located.transform,
        ocr_tokens=tokens,
        traces=traces,
        artifact_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


class AxisCalibration(FrozenModel):
    scale: Literal["log10"]
    slope: Decimal
    intercept: Decimal
    residual_pixels: Decimal
    minor_grid_spacing_pixels: Decimal

    @model_validator(mode="after")
    def _valid_axis_fit(self) -> AxisCalibration:
        if self.slope <= 0:
            raise ValueError("log-axis calibration slope must be positive")
        if self.residual_pixels < 0 or self.minor_grid_spacing_pixels <= 0:
            raise ValueError("axis calibration pixel errors must be non-negative")
        if self.residual_pixels > self.minor_grid_spacing_pixels / 2:
            raise ValueError("axis calibration residual exceeds half minor-grid spacing")
        return self


class PlotCalibration(FrozenModel):
    x: AxisCalibration
    y: AxisCalibration


class ConservatismReport(FrozenModel):
    maximum_positive_voltage_error: Decimal
    maximum_fidelity_error_pixels: Decimal
    proven: bool


class CurveDigitizationResult(FrozenModel):
    proposed_rule: PiecewiseCurveRule | None
    calibration: PlotCalibration | None
    conservatism: ConservatismReport | None
    blocking_review_items: tuple[ImportReviewItem, ...]


CurveDigitizationResult.model_rebuild()


def calibrate_log_axis(
    ticks: tuple[tuple[Decimal, Decimal], ...],
    *,
    minor_grid_spacing_pixels: Decimal,
) -> AxisCalibration:
    """Least-squares fit of log10(value) = slope * pixel + intercept.

    Requires at least two ticks and a monotone pixel→log mapping; residual must not
    exceed half the declared minor-grid spacing.
    """

    if len(ticks) < 2:
        raise ExtractionError("CURVE_CALIBRATION_FAILED: fewer than two ticks")
    pixels = [pixel for pixel, _ in ticks]
    logs = [log for _, log in ticks]
    if any(right <= left for left, right in pairwise(pixels)) or any(
        right <= left for left, right in pairwise(logs)
    ):
        raise ExtractionError("CURVE_CALIBRATION_FAILED: non-monotone tick mapping")
    n = Decimal(len(ticks))
    sum_x = sum(pixels)
    sum_y = sum(logs)
    sum_xx = sum(pixel * pixel for pixel in pixels)
    sum_xy = sum(pixel * log for pixel, log in ticks)
    denominator = n * sum_xx - sum_x * sum_x
    if denominator == 0:
        raise ExtractionError("CURVE_CALIBRATION_FAILED: degenerate tick spread")
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n
    residual = max(
        abs(slope * pixel + intercept - log) for pixel, log in ticks
    )
    if residual > minor_grid_spacing_pixels / 2:
        raise ExtractionError(
            "CURVE_CALIBRATION_FAILED: tick residual exceeds half minor-grid spacing"
        )
    return AxisCalibration(
        scale="log10",
        slope=slope,
        intercept=intercept,
        residual_pixels=residual,
        minor_grid_spacing_pixels=minor_grid_spacing_pixels,
    )


def _lower_envelope(
    source: tuple[tuple[Decimal, Decimal], ...], x: Decimal
) -> Decimal | None:
    """Lowest source y at column x, interpolating between neighboring samples.

    Points must arrive sorted: the proof probes thousands of columns against the
    same trace, and re-sorting per probe dominated the runtime.

    Columns outside the traced endpoints have no source evidence: no curve is
    extrapolated there, so they contribute no envelope constraint.
    """

    if not source:
        return None
    if x < source[0][0] or x > source[-1][0]:
        return None
    for (lx, ly), (rx, ry) in pairwise(source):
        if lx <= x <= rx:
            if rx == lx:
                return min(ly, ry)
            fraction = (x - lx) / (rx - lx)
            return ly + fraction * (ry - ly)
    return source[-1][1]


def conservative_simplify(
    points: list[tuple[Decimal, Decimal]] | tuple[tuple[Decimal, Decimal], ...],
    tolerance: Decimal,
) -> tuple[tuple[Decimal, Decimal], ...]:
    """Round time outward and voltage downward at the declared tolerance.

    For a maximum-voltage rule, conservative means: earliest times shift earlier,
    latest times shift later, voltages shift down — never the reverse.
    """

    ordered = tuple(sorted(points))
    if len(ordered) < 2:
        return ordered
    # Time rounds outward (earliest earlier, latest later); voltage rounds down.
    # For a monotonically DECREASING front this strictly widens the conservative
    # region: the earlier endpoint follows the slope down-left; the later endpoint
    # keeps the final (lowest) voltage rather than extrapolating below the traced
    # endpoint, where no source evidence exists.
    simplified: list[tuple[Decimal, Decimal]] = []
    last_index = len(ordered) - 1
    for index, (x, y) in enumerate(ordered):
        if index == 0:
            slope = (ordered[1][1] - ordered[0][1]) / (ordered[1][0] - ordered[0][0])
            rounded_x = x - tolerance
            rounded_y = y + slope * (rounded_x - x) - tolerance
        elif index == last_index:
            rounded_x = x + tolerance
            rounded_y = y - tolerance
        else:
            rounded_x = x
            rounded_y = y - tolerance
        simplified.append((rounded_x, rounded_y))
    return tuple(simplified)


def _blocking_item(code: str, spec: CurveAuditSpec, contract: str) -> ImportReviewItem:
    from insulation_coordination.domain.rules import SourceReference
    from insulation_coordination.rules.importer.extract import ImportReviewItem

    return ImportReviewItem(
        code=code,
        semantic_id=f"{spec.semantic_id}.{spec.figure}",
        kind="curve",
        source=SourceReference(
            document_id="importer",
            standard="internal",
            edition="internal",
            page=spec.page_number,
            figure=spec.figure,
        ),
        expected_contract=contract,
    )


def _tick_value(token: OcrToken) -> Decimal | None:
    try:
        compact = re.sub(r"[\s\u00a0]", "", token.text).replace(",", ".")
        return Decimal(compact)
    except InvalidOperation:
        return None


def _axis_ticks(
    tokens: tuple[OcrToken, ...],
    *,
    axis: Literal["x", "y"],
    pixel_size: tuple[int, int],
    source_to_target: Decimal = Decimal(1),
) -> tuple[tuple[Decimal, Decimal], ...]:
    """Numeric tokens in image-pixel axis strips, reduced to a longest monotone
    log sequence so split thousands and in-plot annotations cannot become ticks."""

    width, height = (Decimal(item) for item in pixel_size)
    by_value: dict[Decimal, tuple[Decimal, Decimal]] = {}
    for token in tokens:
        value = _tick_value(token)
        if value is None or value <= 0:
            continue
        center_x = Decimal(token.box.left + token.box.right) / 2
        center_y = Decimal(token.box.top + token.box.bottom) / 2
        if axis == "x":
            if not (
                Decimal("0.75") * height <= center_y <= Decimal("0.99") * height
                and Decimal("0.05") * width <= center_x <= Decimal("0.97") * width
            ):
                continue
            position = center_x
            current = by_value.get(value)
            if current is None or position < current[0]:
                by_value[value] = (position, _log10(value * source_to_target))
        else:
            if not (
                Decimal("0.03") * width <= center_x <= Decimal("0.15") * width
                and Decimal("0.03") * height <= center_y <= Decimal("0.88") * height
            ):
                continue
            position = -center_y
            current = by_value.get(value)
            if current is None:
                by_value[value] = (position, _log10(value))
    ordered = sorted(by_value.values())
    longest: list[list[tuple[Decimal, Decimal]]] = []
    for index, tick in enumerate(ordered):
        preceding = [
            longest[prior]
            for prior in range(index)
            if ordered[prior][0] < tick[0] and ordered[prior][1] < tick[1]
        ]
        longest.append(
            [*(max(preceding, key=lambda sequence: len(sequence)) if preceding else []), tick]
        )
    if not longest:
        return ()
    longest.sort(key=lambda sequence: len(sequence))
    return tuple(longest[-1])


def _log10(value: Decimal) -> Decimal:
    return value.log10()


def _log10_to_value(log_value: Decimal) -> Decimal:
    return (log_value * Decimal(10).ln()).exp()


def _require_finite(value: Decimal, name: str) -> None:
    if not value.is_finite():
        raise ValueError(f"manual curve {name} must be finite")


def pixel_to_source_point(
    pixel_x: Decimal,
    pixel_y: Decimal,
    calibration: ManualPlotCalibration,
) -> CurvePoint:
    """Convert a reviewed plot pixel to a log-log source point."""

    _require_finite(pixel_x, "pixel x")
    _require_finite(pixel_y, "pixel y")
    if not (
        calibration.left <= pixel_x <= calibration.right
        and calibration.top <= pixel_y <= calibration.bottom
    ):
        raise ValueError("point is outside reviewed plot rectangle")
    x_fraction = (pixel_x - calibration.left) / (calibration.right - calibration.left)
    y_fraction = (calibration.bottom - pixel_y) / (
        calibration.bottom - calibration.top
    )
    x_log = calibration.x_min.log10() + x_fraction * (
        calibration.x_max.log10() - calibration.x_min.log10()
    )
    y_log = calibration.y_min.log10() + y_fraction * (
        calibration.y_max.log10() - calibration.y_min.log10()
    )
    return CurvePoint(x=_log10_to_value(x_log), y=_log10_to_value(y_log))


def source_point_to_pixel(
    point: CurvePoint,
    calibration: ManualPlotCalibration,
) -> tuple[Decimal, Decimal]:
    """Convert a log-log source point to a reviewed plot pixel."""

    _require_finite(point.x, "source x")
    _require_finite(point.y, "source y")
    if not (
        calibration.x_min <= point.x <= calibration.x_max
        and calibration.y_min <= point.y <= calibration.y_max
    ):
        raise ValueError("point is outside reviewed source axis bounds")
    x_fraction = (point.x.log10() - calibration.x_min.log10()) / (
        calibration.x_max.log10() - calibration.x_min.log10()
    )
    y_fraction = (point.y.log10() - calibration.y_min.log10()) / (
        calibration.y_max.log10() - calibration.y_min.log10()
    )
    return (
        calibration.left + x_fraction * (calibration.right - calibration.left),
        calibration.bottom - y_fraction * (calibration.bottom - calibration.top),
    )


def infer_curve_segments(points: tuple[CurvePoint, ...]) -> tuple[CurveSegment, ...]:
    """Infer constant plateaus and continuous log-log intervals in one pass."""

    return tuple(
        CurveSegment(
            start=index,
            end=index + 1,
            segment_type="plateau" if left.y == right.y else "continuous",
            interpolation="constant" if left.y == right.y else "log_log",
        )
        for index, (left, right) in enumerate(pairwise(points))
    )


def _log_space_point(point: RawCurvePoint, calibration: PlotCalibration) -> tuple[Decimal, Decimal]:
    """Pixel → log10 space for envelope math."""

    x_log = calibration.x.slope * point.x + calibration.x.intercept
    y_log = calibration.y.slope * (-point.y) + calibration.y.intercept
    return x_log, y_log


def _fidelity_tolerance(trace: RawCurveTrace) -> Decimal:
    """max(1 pixel, ceil(stroke_width / 2)) — the mandated fidelity tolerance."""

    half = trace.stroke_width / 2
    ceiling = half.to_integral_value(rounding="ROUND_CEILING")
    return max(Decimal(1), ceiling)


def _pixel_tolerance_to_value(tolerance: Decimal, slope: Decimal) -> Decimal:
    """Pixel tolerance → log10-value tolerance through the axis slope magnitude."""

    return abs(slope) * tolerance


def prove_conservative(
    source: list[tuple[Decimal, Decimal]] | tuple[tuple[Decimal, Decimal], ...],
    candidate: list[tuple[Decimal, Decimal]] | tuple[tuple[Decimal, Decimal], ...],
    tolerance: Decimal,
) -> ConservatismReport:
    """Prove the candidate never exceeds the source's lower uncertainty boundary.

    Both inputs live in the same coordinate space (log10 space for the digitizer).
    Checks every source column, every candidate breakpoint, and the analytic
    intersection of each candidate segment with each source segment, including the
    case where the segment runs strictly above the envelope between two columns
    without crossing it (endpoint-extremum coverage).
    """

    source_points = tuple(sorted(source))
    candidate_points = tuple(sorted(candidate))
    roundtrip_epsilon = Decimal("1e-24")
    maximum_positive = Decimal(0)
    proven = True
    probe_xs = {x for x, _ in source_points} | {x for x, _ in candidate_points}
    for (lx, ly), (rx, ry) in pairwise(candidate_points):
        for (sx0, sy0), (sx1, sy1) in pairwise(source_points):
            # Solve candidate == envelope inside the overlap of both segments.
            overlap_lo = max(lx, sx0)
            overlap_hi = min(rx, sx1)
            if overlap_lo > overlap_hi:
                continue
            probe_xs.add(overlap_lo)
            probe_xs.add(overlap_hi)
            candidate_slope = (ry - ly) / (rx - lx) if rx != lx else Decimal(0)
            source_slope = (sy1 - sy0) / (sx1 - sx0) if sx1 != sx0 else Decimal(0)
            denominator = candidate_slope - source_slope
            if denominator == 0:
                continue
            intersection = (
                (sy0 - ly) + source_slope * (lx - sx0)
            ) / denominator + lx
            if overlap_lo < intersection < overlap_hi:
                probe_xs.add(intersection)
    for x in sorted(probe_xs):
        envelope = _lower_envelope(source_points, x)
        if envelope is None:
            continue
        lower = envelope - tolerance
        # The candidate is a piecewise curve, so its own envelope is its value at x.
        candidate_y = _lower_envelope(candidate_points, x)
        if candidate_y is None:
            continue
        error = candidate_y - lower
        if error > roundtrip_epsilon:
            maximum_positive = max(maximum_positive, error)
            proven = False
    return ConservatismReport(
        maximum_positive_voltage_error=maximum_positive,
        maximum_fidelity_error_pixels=tolerance,
        proven=proven,
    )


def prove_variant_conservative(
    figure: RawFigure,
    trace: RawCurveTrace,
    calibration: PlotCalibration,
    variant: FaultTimeVoltageVariant,
) -> ConservatismReport:
    """Re-run the source-envelope proof for a reviewed semantic variant."""

    if any(point.space != "pixel" for point in trace.points):
        raise ValueError("curve proof requires source-pixel trace geometry")
    source_log = tuple(_log_space_point(point, calibration) for point in trace.points)
    candidate_log = tuple((_log10(point.x), _log10(point.y)) for point in variant.points)
    if not source_log or not candidate_log:
        return ConservatismReport(
            maximum_positive_voltage_error=Decimal(0),
            maximum_fidelity_error_pixels=Decimal(0),
            proven=False,
        )
    tolerance_pixels = _fidelity_tolerance(trace)
    tolerance_log = _pixel_tolerance_to_value(tolerance_pixels, calibration.y.slope)
    report = prove_conservative(source_log, candidate_log, tolerance_log)
    return report


def rebuild_variant_from_calibration(
    trace: RawCurveTrace,
    calibration: PlotCalibration,
    variant: FaultTimeVoltageVariant,
) -> FaultTimeVoltageVariant:
    """Reconstruct engineering points when reviewed pixel calibration changes."""

    from insulation_coordination.domain.rules import CurvePoint, CurveSegment

    source_log = tuple(sorted(_log_space_point(point, calibration) for point in trace.points))
    if len(source_log) < 2:
        raise ValueError("curve trace has fewer than two points")
    tolerance_pixels = _fidelity_tolerance(trace)
    y_margin = _pixel_tolerance_to_value(tolerance_pixels, calibration.y.slope)
    candidate_log = tuple((x, y - y_margin) for x, y in source_log)
    values = tuple(
        CurvePoint(x=_log10_to_value(x), y=_log10_to_value(y))
        for x, y in candidate_log
    )
    return variant.model_copy(
        update={
            "x_axis": variant.x_axis.model_copy(
                update={
                    "minimum": min(point.x for point in values),
                    "maximum": max(point.x for point in values),
                }
            ),
            "y_axis": variant.y_axis.model_copy(
                update={
                    "minimum": min(point.y for point in values),
                    "maximum": max(point.y for point in values),
                }
            ),
            "points": values,
            "segments": tuple(
                CurveSegment(
                    start=index,
                    end=index + 1,
                    segment_type="continuous",
                    interpolation="log_log",
                )
                for index in range(len(values) - 1)
            ),
        }
    )


def digitize_curve_figure(
    figure: RawFigure,
    spec: CurveAuditSpec,
    ocr: OcrEngine,
    identity: StandardIdentity,
) -> CurveDigitizationResult:
    """Digitize one reviewed figure into a proposed conservative curve rule."""

    try:
        tokens = (
            ocr.recognize(_blank_image(figure))
            if not figure.ocr_tokens
            else figure.ocr_tokens
        )
    except OcrError as error:
        return CurveDigitizationResult(
            proposed_rule=None,
            calibration=None,
            conservatism=None,
            blocking_review_items=(
                _blocking_item("CURVE_OCR_FAILED", spec, str(error)),
            ),
        )
    source_unit = spec.x_source_unit or spec.x_unit
    if (source_unit, spec.x_unit) == ("ms", "s"):
        x_source_to_target = Decimal("0.001")
    elif source_unit == spec.x_unit:
        x_source_to_target = Decimal(1)
    else:
        return CurveDigitizationResult(
            proposed_rule=None,
            calibration=None,
            conservatism=None,
            blocking_review_items=(
                _blocking_item(
                    "CURVE_CALIBRATION_FAILED",
                    spec,
                    "unsupported source-axis unit conversion",
                ),
            ),
        )
    pixel_size = figure.pixel_size or (1, 1)
    try:
        x_calibration = calibrate_log_axis(
            _axis_ticks(
                tokens,
                axis="x",
                pixel_size=pixel_size,
                source_to_target=x_source_to_target,
            ),
            minor_grid_spacing_pixels=Decimal(80),
        )
        y_calibration = calibrate_log_axis(
            _axis_ticks(tokens, axis="y", pixel_size=pixel_size),
            minor_grid_spacing_pixels=Decimal(80),
        )
    except ExtractionError as error:
        return CurveDigitizationResult(
            proposed_rule=None,
            calibration=None,
            conservatism=None,
            blocking_review_items=(
                _blocking_item("CURVE_CALIBRATION_FAILED", spec, str(error)),
            ),
        )
    calibration = PlotCalibration(x=x_calibration, y=y_calibration)
    if len(figure.traces) != len(spec.variant_slots):
        return CurveDigitizationResult(
            proposed_rule=None,
            calibration=calibration,
            conservatism=None,
            blocking_review_items=(
                _blocking_item(
                    "CURVE_TRACE_AMBIGUOUS",
                    spec,
                    f"expected {len(spec.variant_slots)} reviewed strokes, "
                    f"found {len(figure.traces)}",
                ),
            ),
        )
    if any(len(trace.points) < 2 for trace in figure.traces):
        return CurveDigitizationResult(
            proposed_rule=None,
            calibration=calibration,
            conservatism=None,
            blocking_review_items=(
                _blocking_item(
                    "CURVE_TRACE_AMBIGUOUS", spec, "trace has fewer than two points"
                ),
            ),
        )
    from insulation_coordination.domain.rules import (
        CurveAxis,
        CurvePoint,
        CurveSegment,
        FaultTimeVoltageVariant,
    )

    variants: list[FaultTimeVoltageVariant] = []
    reports: list[ConservatismReport] = []
    for index, (trace, selector) in enumerate(
        zip(figure.traces, spec.variant_slots, strict=True), start=1
    ):
        tolerance_pixels = _fidelity_tolerance(trace)
        y_tolerance = _pixel_tolerance_to_value(
            tolerance_pixels, calibration.y.slope
        )
        source_log = tuple(
            sorted(_log_space_point(point, calibration) for point in trace.points)
        )
        candidate_log = tuple((x, y - y_tolerance) for x, y in source_log)
        report = prove_conservative(source_log, candidate_log, y_tolerance)
        reports.append(report)
        if not report.proven:
            return CurveDigitizationResult(
                proposed_rule=None,
                calibration=calibration,
                conservatism=report,
                blocking_review_items=(
                    _blocking_item(
                        "CURVE_CONSERVATISM_UNPROVEN",
                        spec,
                        "candidate segment exceeds the lower uncertainty envelope",
                    ),
                ),
            )
        value_points = tuple(
            (_log10_to_value(x_log), _log10_to_value(y_log))
            for x_log, y_log in candidate_log
        )
        if any(x <= 0 or y <= 0 for x, y in value_points):
            return CurveDigitizationResult(
                proposed_rule=None,
                calibration=calibration,
                conservatism=report,
                blocking_review_items=(
                    _blocking_item(
                        "CURVE_CONSERVATISM_UNPROVEN",
                        spec,
                        "conservative rounding left the log domain",
                    ),
                ),
            )
        x_values = [x for x, _ in value_points]
        y_values = [y for _, y in value_points]
        variant_id = f"{spec.semantic_id}.{spec.figure}"
        if len(spec.variant_slots) > 1:
            variant_id = f"{variant_id}.{index}"
        variants.append(
            FaultTimeVoltageVariant(
                id=variant_id,
                selector=selector,
                x_axis=CurveAxis(
                    quantity_kind=spec.x_quantity_kind,
                    unit=spec.x_unit,
                    scale="log10",
                    minimum=min(x_values),
                    maximum=max(x_values),
                ),
                y_axis=CurveAxis(
                    quantity_kind=spec.y_quantity_kind,
                    unit=spec.y_unit,
                    scale="log10",
                    minimum=min(y_values),
                    maximum=max(y_values),
                ),
                points=tuple(CurvePoint(x=x, y=y) for x, y in value_points),
                segments=tuple(
                    CurveSegment(
                        start=segment_index,
                        end=segment_index + 1,
                        segment_type="continuous",
                        interpolation="log_log",
                    )
                    for segment_index in range(len(value_points) - 1)
                ),
                applicability="review required",
                source=figure.source,
                reviewed_artifact_sha256=figure.artifact_sha256,
            )
        )
    rule = PiecewiseCurveRule(
        id=spec.semantic_id,
        variants=tuple(variants),
        source=figure.source,
    )
    combined_report = ConservatismReport(
        maximum_positive_voltage_error=max(
            report.maximum_positive_voltage_error for report in reports
        ),
        maximum_fidelity_error_pixels=max(
            report.maximum_fidelity_error_pixels for report in reports
        ),
        proven=all(report.proven for report in reports),
    )
    return CurveDigitizationResult(
        proposed_rule=rule,
        calibration=calibration,
        conservatism=combined_report,
        blocking_review_items=(),
    )


def _blank_image(figure: RawFigure) -> Image.Image:
    width, height = figure.pixel_size or (1, 1)
    return Image.new("L", (width, height), color=255)
