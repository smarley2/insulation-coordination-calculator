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
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

import pdfplumber
from PIL import Image
from pydantic import Field, model_validator
from pydantic import ValidationError as PydanticValidationError
from pypdf._page import PageObject

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.rules.importer.extract import ExtractionError

if TYPE_CHECKING:
    from insulation_coordination.rules.importer.identify import (
        CurveAuditSpec,
        StandardIdentity,
    )
from insulation_coordination.domain.rules import Identifier, SourceReference


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


def _decimal(value: object) -> Decimal:
    return Decimal(str(float(str(value))))


def locate_curve_source(
    reader_page: PageObject,
    spec: CurveAuditSpec,
) -> Literal["vector_path", "image_xobject"]:
    """Decide the source mode: vector paths inside the recipe bbox win; a single
    recipe-matching lossless image XObject is the fallback; anything else blocks."""

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
        elif op == "cm":
            a, b, c, d, e, f = (float(str(value)) for value in operands)
            current_matrix = (a, b, c, d, e, f)
        elif op == "Do":
            a, b, c, d, e, f = current_matrix
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
        return "vector_path"
    if len({name for name, _ in image_operands}) > 1:
        raise ExtractionError(
            f"CURVE_SOURCE_AMBIGUOUS: "
            f"{len({name for name, _ in image_operands})} image candidates for {spec.figure}"
        )
    if not image_operands:
        raise ExtractionError(f"CURVE_SOURCE_MISSING: no vector paths or image for {spec.figure}")
    return "image_xobject"


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
    mode = locate_curve_source(reader_page, spec)
    if mode == "vector_path":
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

    images = list(reader_page.images)
    if len(images) == 0:
        raise ExtractionError(
            f"CURVE_SOURCE_MISSING: no image XObject for {spec.figure}"
        )
    if len(images) != 1:
        raise ExtractionError(
            f"CURVE_SOURCE_AMBIGUOUS: {len(images)} image candidates for {spec.figure}"
        )
    image_file = images[0]
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
    xobject = image_file.indirect_reference.get_object()
    get_data = getattr(xobject, "get_data", None)
    if get_data is None:
        raise ExtractionError(f"CURVE_SOURCE_MISSING: image stream for {spec.figure}")
    byte_hash = hashlib.sha256(get_data()).hexdigest()
    payload = (
        f"image:{spec.semantic_id}:{spec.expected_bbox}:{byte_hash}:"
        f"{ocr.identity.name}:{ocr.identity.version}:{ocr.identity.config_sha256}:"
        + ";".join(token.text for token in tokens)
    )
    return RawFigure(
        source=source,
        source_mode="image_xobject",
        source_bbox=bbox,  # type: ignore[arg-type]
        pixel_size=(int(image.size[0]), int(image.size[1])),
        transform=(
            Decimal(1), Decimal(0), Decimal(0), Decimal(1), Decimal(0), Decimal(0),
        ),
        ocr_tokens=tokens,
        traces=(),
        artifact_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )
