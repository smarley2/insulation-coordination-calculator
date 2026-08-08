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
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol, runtime_checkable

from PIL import Image
from pydantic import Field, model_validator

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import Identifier


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
            path.unlink(missing_ok=True)
            if fd is not None:
                import os

                try:
                    os.close(fd)
                except OSError:
                    pass


def _parse_tsv(payload: bytes) -> tuple[OcrToken, ...]:
    text = payload.decode("utf-8")
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
            box = PixelBox(
                left=left,
                top=top,
                right=left + int(row["width"]),
                bottom=top + int(row["height"]),
            )
            sort_key = (
                top,
                left,
                int(row["line_num"]),
                int(row["word_num"]),
            )
        except (InvalidOperation, TypeError, ValueError, KeyError) as error:
            raise OcrError("OCR_FAILED", "OCR returned malformed TSV") from error
        tokens.append((sort_key, OcrToken(text=word, confidence=confidence, box=box)))
    return tuple(token for _, token in sorted(tokens, key=lambda pair: pair[0]))


__all__ = [
    "OcrEngine",
    "OcrEngineIdentity",
    "OcrError",
    "OcrToken",
    "PixelBox",
    "TesseractOcrEngine",
]
