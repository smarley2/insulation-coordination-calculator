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
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

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
    "locate_curve_source",
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
    stack: list[tuple[float, float, float, float, float, float]] = []
    for operands, operator in stream.operations:
        op = operator.decode() if isinstance(operator, bytes) else str(operator)
        if op == "q":
            stack.append(current_matrix)
        elif op == "Q":
            if stack:
                current_matrix = stack.pop()
        elif op == "W":
            # Clipping changes which geometry lands inside the figure; rather than
            # interpret the clip path, block so a reviewer confirms the figure.
            raise ExtractionError(
                f"CURVE_SOURCE_CLIPPED: clipping path present for {spec.figure}"
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
                image_operands.append((str(operands[0]), current_matrix))
        elif op in _PATH_POINT_OPERATORS:
            numbers = [float(str(value)) for value in operands]
            px, py = numbers[0], numbers[1]
            tx = current_matrix[0] * px + current_matrix[2] * py + current_matrix[4]
            ty = current_matrix[1] * px + current_matrix[3] * py + current_matrix[5]
            if x0 <= tx <= x1 and pdf_bottom <= ty <= pdf_top:
                vector_points += 1
    if vector_points >= 2:
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
        traces = _vector_traces(reader_page, spec)
        payload = (
            f"vector:{spec.semantic_id}:{spec.expected_bbox}:"
            f"{ocr.identity.config_sha256}:"
            + ";".join(
                f"{trace.id}:{','.join(f'{p.x}/{p.y}' for p in trace.points)}"
                for trace in traces
            )
        )
        return RawFigure(
            source=source,
            source_mode="vector_path",
            source_bbox=bbox,  # type: ignore[arg-type]
            pixel_size=None,
            transform=(
                Decimal(1), Decimal(0), Decimal(0), Decimal(1), Decimal(0), Decimal(0),
            ),
            ocr_tokens=(),
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
    tokens = ocr.recognize(image)
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
        traces=(),
        artifact_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


class AxisCalibration(FrozenModel):
    scale: Literal["log10"]
    slope: Decimal
    intercept: Decimal
    residual_pixels: Decimal
    minor_grid_spacing_pixels: Decimal


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


def prove_conservative(
    source: list[tuple[Decimal, Decimal]] | tuple[tuple[Decimal, Decimal], ...],
    candidate: list[tuple[Decimal, Decimal]] | tuple[tuple[Decimal, Decimal], ...],
    tolerance: Decimal,
) -> ConservatismReport:
    """Prove the candidate never exceeds the source's lower uncertainty boundary.

    For a maximum-voltage rule the reconstructed curve must sit at or below the
    source geometry minus the fidelity tolerance at every source column and every
    candidate breakpoint.
    """

    maximum_positive = Decimal(0)
    proven = True
    source_points = tuple(source)
    for x, _y in (*candidate, *source_points):
        envelope = _lower_envelope(source_points, x)
        if envelope is None:
            continue
        lower = envelope - tolerance
        candidate_y = _piecewise_value(candidate, x)
        if candidate_y is None:
            continue
        error = candidate_y - lower
        maximum_positive = max(maximum_positive, error)
        if candidate_y > lower:
            proven = False
    return ConservatismReport(
        maximum_positive_voltage_error=maximum_positive,
        maximum_fidelity_error_pixels=tolerance,
        proven=proven,
    )


def _lower_envelope(
    source: tuple[tuple[Decimal, Decimal], ...], x: Decimal
) -> Decimal | None:
    """Lowest source y at column x, interpolating between neighboring samples.

    Columns outside the traced endpoints have no source evidence: no curve is
    extrapolated there, so they contribute no envelope constraint.
    """

    if not source:
        return None
    ordered = sorted(source)
    if x < ordered[0][0] or x > ordered[-1][0]:
        return None
    for (lx, ly), (rx, ry) in pairwise(ordered):
        if lx <= x <= rx:
            if rx == lx:
                return min(ly, ry)
            fraction = (x - lx) / (rx - lx)
            return ly + fraction * (ry - ly)
    return ordered[-1][1]


def _piecewise_value(
    candidate: list[tuple[Decimal, Decimal]] | tuple[tuple[Decimal, Decimal], ...],
    x: Decimal,
) -> Decimal | None:
    ordered = tuple(sorted(candidate))
    if not ordered or x < ordered[0][0] or x > ordered[-1][0]:
        return None
    return _lower_envelope(ordered, x)


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
        semantic_id=spec.semantic_id,
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
        return Decimal(token.text.replace(",", "."))
    except InvalidOperation:
        return None


def _axis_ticks(
    tokens: tuple[OcrToken, ...],
    *,
    axis: Literal["x", "y"],
    bbox: tuple[float, float, float, float],
) -> tuple[tuple[Decimal, Decimal], ...]:
    """Numeric tokens in the axis strip: bottom 15% of the bbox for x (sorted by
    pixel x), left 15% for y (sorted by descending pixel y = ascending value)."""

    x0, top, x1, bottom = bbox
    width = Decimal(str(x1 - x0))
    height = Decimal(str(bottom - top))
    x_strip = Decimal(str(bottom)) - Decimal("0.15") * height
    y_strip = Decimal(str(x0)) + Decimal("0.15") * width
    ticks: list[tuple[Decimal, Decimal]] = []
    for token in tokens:
        value = _tick_value(token)
        if value is None or value <= 0:
            continue
        center_x = Decimal(token.box.left + token.box.right) / 2
        center_y = Decimal(token.box.top + token.box.bottom) / 2
        if axis == "x":
            if center_y < x_strip or center_x < y_strip:
                continue
            ticks.append((center_x, _log10(value)))
        else:
            if center_x > y_strip or center_y > x_strip:
                continue
            ticks.append((center_y, _log10(value)))
    # y pixel grows downward while value grows upward; calibrate on -pixel so both
    # axes feed the fit a strictly increasing pixel→log mapping.
    if axis == "y":
        return tuple(sorted((-pixel, log) for pixel, log in ticks))
    return tuple(sorted(ticks))


def _log10(value: Decimal) -> Decimal:
    return value.log10()


def digitize_curve_figure(
    figure: RawFigure,
    spec: CurveAuditSpec,
    ocr: OcrEngine,
    identity: StandardIdentity,
) -> CurveDigitizationResult:
    """Digitize one reviewed figure into a proposed conservative curve rule."""

    tokens = ocr.recognize(_blank_image(figure)) if not figure.ocr_tokens else figure.ocr_tokens
    try:
        x_calibration = calibrate_log_axis(
            _axis_ticks(tokens, axis="x", bbox=spec.expected_bbox),
            minor_grid_spacing_pixels=Decimal(80),
        )
        y_calibration = calibrate_log_axis(
            _axis_ticks(tokens, axis="y", bbox=spec.expected_bbox),
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
    if not figure.traces:
        return CurveDigitizationResult(
            proposed_rule=None,
            calibration=calibration,
            conservatism=None,
            blocking_review_items=(
                _blocking_item(
                    "CURVE_TRACE_AMBIGUOUS", spec, "no connected stroke was traced"
                ),
            ),
        )
    trace = max(figure.traces, key=lambda item: len(item.points))
    tolerance = max(Decimal(1), (trace.stroke_width / 2).to_integral_value())
    source_points = tuple(
        (point.x, point.y) for point in sorted(trace.points, key=lambda point: point.x)
    )
    breakpoints = (source_points[0], source_points[-1])
    simplified = conservative_simplify(breakpoints, tolerance)
    report = prove_conservative(source_points, simplified, tolerance)
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
    from insulation_coordination.domain.rules import (
        CurveAxis,
        CurvePoint,
        CurveSegment,
        FaultTimeVoltageVariant,
    )

    x_values = [point[0] for point in simplified]
    y_values = [point[1] for point in simplified]
    variant = FaultTimeVoltageVariant(
        id=f"{spec.semantic_id}.{spec.figure}",
        selector=spec.variant_slots[0],
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
        points=tuple(
            CurvePoint(x=x, y=y) for x, y in simplified
        ),
        segments=(
            CurveSegment(
                start=0,
                end=len(simplified) - 1,
                segment_type="continuous",
                interpolation="log_log",
            ),
        ),
        applicability="review required",
        source=figure.source,
        reviewed_artifact_sha256=figure.artifact_sha256,
    )
    rule = PiecewiseCurveRule(
        id=spec.semantic_id,
        variants=(variant,),
        source=figure.source,
    )
    return CurveDigitizationResult(
        proposed_rule=rule,
        calibration=calibration,
        conservatism=report,
        blocking_review_items=(),
    )


def _blank_image(figure: RawFigure) -> Image.Image:
    width, height = figure.pixel_size or (1, 1)
    return Image.new("L", (width, height), color=255)
