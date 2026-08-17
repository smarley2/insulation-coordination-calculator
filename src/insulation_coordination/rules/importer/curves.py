"""Verified curve-source extraction and manual log-plot helpers."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from itertools import pairwise
from typing import TYPE_CHECKING, Literal, Self

import pdfplumber
from pydantic import Field, model_validator
from pypdf._page import PageObject

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import CurvePoint, CurveSegment, SourceReference
from insulation_coordination.rules.importer.artifacts import ExtractionError

if TYPE_CHECKING:
    from insulation_coordination.rules.importer.identify import (
        CurveAuditSpec,
        StandardIdentity,
    )

__all__ = [
    "LocatedCurveSource",
    "ManualPlotCalibration",
    "RawFigure",
    "extract_raw_figure",
    "infer_curve_segments",
    "locate_curve_source",
    "source_point_to_pixel",
]


class RawFigure(FrozenModel):
    """Immutable local source evidence for one recipe-declared figure."""

    source: SourceReference
    source_mode: Literal["vector_path", "image_xobject"]
    source_bbox: tuple[Decimal, Decimal, Decimal, Decimal]
    pixel_size: tuple[int, int] | None
    transform: tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ManualPlotCalibration(FrozenModel):
    """The reviewed log-axis domain of one source figure.

    Holds no pixel geometry: manual review reads values off the printed axes
    rather than tracing the figure, so there is no reviewed plot rectangle.
    """

    figure_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    x_min: Decimal
    x_max: Decimal
    y_min: Decimal
    y_max: Decimal

    @model_validator(mode="after")
    def _valid_bounds(self) -> Self:
        values = (self.x_min, self.x_max, self.y_min, self.y_max)
        if any(not value.is_finite() for value in values):
            raise ValueError("manual curve calibration values must be finite")
        if self.x_min <= 0 or self.y_min <= 0:
            raise ValueError("manual log-axis bounds must be positive")
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError("manual curve axis bounds must be ordered")
        return self


class LocatedCurveSource(FrozenModel):
    """Verified source mode and image placement, when applicable."""

    mode: Literal["vector_path", "image_xobject"]
    image_name: str | None = None
    transform: tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]


_PAINT_OPERATORS = {"S", "s", "f", "f*", "B", "B*", "b", "b*"}
_PATH_POINT_OPERATORS = ("m", "l", "re")
_LOSSLESS_IMAGE_FILTERS = frozenset({"/FlateDecode", "/LZWDecode", ""})


def locate_curve_source(
    reader_page: PageObject,
    spec: CurveAuditSpec,
) -> Literal["vector_path", "image_xobject"]:
    """Prefer vector content in the declared box; otherwise require one image."""

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
            corners = ((e, f), (a + e, f), (e, d + f), (a + e, d + f))
            ix0 = min(point[0] for point in corners)
            ix1 = max(point[0] for point in corners)
            iy0 = min(point[1] for point in corners)
            iy1 = max(point[1] for point in corners)
            if ix0 < x1 and ix1 > x0 and iy0 < pdf_top and iy1 > pdf_bottom:
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
            raise ExtractionError(f"CURVE_SOURCE_CLIPPED: clipping path present for {spec.figure}")
        return LocatedCurveSource(
            mode="vector_path",
            transform=(
                Decimal(1),
                Decimal(0),
                Decimal(0),
                Decimal(1),
                Decimal(0),
                Decimal(0),
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


def _artifact_sha256(*parts: object, payload: bytes) -> str:
    digest = hashlib.sha256()
    digest.update("|".join(str(part) for part in parts).encode("utf-8"))
    digest.update(payload)
    return digest.hexdigest()


def extract_raw_figure(
    reader_page: PageObject,
    plumber_page: pdfplumber.page.Page,
    spec: CurveAuditSpec,
    identity: StandardIdentity,
) -> RawFigure:
    """Extract immutable source evidence without interpreting curve content."""

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
        image = plumber_page.crop(spec.expected_bbox).to_image(resolution=110).original
        width, height = image.size
        x0, top, x1, bottom = spec.expected_bbox
        page_height = float(reader_page.mediabox.height)
        pdf_top = page_height - top
        scale_x = Decimal(width) / Decimal(str(x1 - x0))
        scale_y = Decimal(height) / Decimal(str(bottom - top))
        transform = (
            scale_x,
            Decimal(0),
            Decimal(0),
            -scale_y,
            -Decimal(str(x0)) * scale_x,
            Decimal(str(pdf_top)) * scale_y,
        )
        return RawFigure(
            source=source,
            source_mode="vector_path",
            source_bbox=bbox,  # type: ignore[arg-type]
            pixel_size=(width, height),
            transform=transform,
            artifact_sha256=_artifact_sha256(
                identity.sha256,
                spec.semantic_id,
                spec.expected_bbox,
                image.mode,
                image.size,
                payload=image.tobytes(),
            ),
        )

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
            f"CURVE_SOURCE_AMBIGUOUS: {len(matched)} images match {image_name} for {spec.figure}"
        )
    image_file = matched[0]
    raster_image = image_file.image
    if raster_image is None:
        raise ExtractionError(f"CURVE_SOURCE_MISSING: image bytes for {spec.figure}")
    if spec.expected_pixel_size is not None and raster_image.size != spec.expected_pixel_size:
        raise ExtractionError(f"CURVE_SOURCE_MISMATCH: pixel size differs for {spec.figure}")
    if image_file.indirect_reference is None:
        raise ExtractionError("CURVE_SOURCE_MISSING: image has no indirect reference")
    get_data = getattr(xobject, "get_data", None)
    if get_data is None:
        raise ExtractionError(f"CURVE_SOURCE_MISSING: image stream for {spec.figure}")
    return RawFigure(
        source=source,
        source_mode="image_xobject",
        source_bbox=bbox,  # type: ignore[arg-type]
        pixel_size=(int(raster_image.size[0]), int(raster_image.size[1])),
        transform=located.transform,
        artifact_sha256=_artifact_sha256(
            identity.sha256,
            spec.semantic_id,
            spec.expected_bbox,
            located.transform,
            payload=get_data(),
        ),
    )


def _require_finite(value: Decimal, name: str) -> None:
    if not value.is_finite():
        raise ValueError(f"manual curve {name} must be finite")


def source_point_to_pixel(
    point: CurvePoint,
    calibration: ManualPlotCalibration,
    rectangle: tuple[Decimal, Decimal, Decimal, Decimal],
) -> tuple[Decimal, Decimal]:
    """Place a log-log source point inside a display rectangle.

    The rectangle is ``(left, top, right, bottom)`` in the caller's own
    coordinates; nothing about it is reviewed evidence.
    """

    left, top, right, bottom = rectangle
    _require_finite(point.x, "source x")
    _require_finite(point.y, "source y")
    if left >= right or top >= bottom:
        raise ValueError("display rectangle must be ordered")
    if not (
        calibration.x_min <= point.x <= calibration.x_max
        and calibration.y_min <= point.y <= calibration.y_max
    ):
        raise ValueError("point is outside reviewed source axis bounds")
    if point.x == calibration.x_min:
        x = left
    elif point.x == calibration.x_max:
        x = right
    else:
        x_fraction = (point.x.log10() - calibration.x_min.log10()) / (
            calibration.x_max.log10() - calibration.x_min.log10()
        )
        x = left + x_fraction * (right - left)
    if point.y == calibration.y_min:
        y = bottom
    elif point.y == calibration.y_max:
        y = top
    else:
        y_fraction = (point.y.log10() - calibration.y_min.log10()) / (
            calibration.y_max.log10() - calibration.y_min.log10()
        )
        y = bottom - y_fraction * (bottom - top)
    return x, y


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
