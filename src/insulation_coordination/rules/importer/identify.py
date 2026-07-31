from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field
from pypdf import PdfReader

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import Identifier

LOGGER = logging.getLogger(__name__)
MAX_STANDARD_PDF_BYTES = 128 * 1024 * 1024
MAX_IDENTITY_PAGES = 20


class StandardIdentificationError(ValueError):
    """A PDF cannot be identified safely."""


class UnsupportedStandardError(StandardIdentificationError):
    """The PDF is not one of the explicitly supported editions."""


class AmbiguousStandardError(StandardIdentificationError):
    """More than one recipe matched the PDF."""


class StandardIdentity(FrozenModel):
    standard: Identifier
    edition: Identifier
    sha256: str = Field(pattern=r"[0-9a-f]{64}")
    page_count: int = Field(ge=1)
    recipe_id: Identifier


@dataclass(frozen=True)
class TableAuditSpec:
    semantic_id: str
    source_table: str
    page_number: int
    clause: str
    target_unit: str
    expected_raw_rows: int
    expected_raw_columns: int
    expected_bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class FormulaAuditSpec:
    semantic_id: str
    unit: str
    page_number: int
    clause: str
    table: str | None = None
    figure: str | None = None


@dataclass(frozen=True)
class MappingAuditSpec:
    semantic_route: str
    family: str
    page_number: int
    clause: str
    table: str | None = None
    figure: str | None = None


@dataclass(frozen=True)
class StandardRecipe:
    id: str
    standard: str
    edition: str
    metadata_keys: tuple[str, ...]
    identity_anchors: tuple[str, ...]
    tables: tuple[TableAuditSpec, ...]
    formulas: tuple[FormulaAuditSpec, ...]
    mappings: tuple[MappingAuditSpec, ...]

    def matches_text(self, text: str) -> bool:
        return all(_normalized(anchor) in text for anchor in self.identity_anchors)

    def matches_identity(self, *, text: str, metadata: dict[str, str]) -> bool:
        metadata_text = _normalized(" ".join(metadata.values()))
        supported_metadata_claims = {
            (f"IEC 60664-{part}", edition)
            for value in metadata.values()
            for part, edition in re.findall(
                r"(?i)IEC\s*60664-([14]).{0,24}?\b((?:19|20)\d{2})\b",
                value,
            )
        }
        if supported_metadata_claims - {(self.standard, self.edition)}:
            return False
        metadata_identifies_document = (
            _normalized(self.standard) in metadata_text
            and _normalized(self.edition) in metadata_text
        )
        metadata_has_layout_fingerprint = all(
            metadata.get(key, "").strip() for key in self.metadata_keys
        )
        return (
            metadata_identifies_document or metadata_has_layout_fingerprint
        ) and self.matches_text(text)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _read_pdf(path: Path) -> tuple[PdfReader, str, str, dict[str, str]]:
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_STANDARD_PDF_BYTES:
            raise UnsupportedStandardError("standard PDF has an invalid or excessive size")
        payload = path.read_bytes()
        if not payload.startswith(b"%PDF-"):
            raise UnsupportedStandardError("standard source is not a PDF")
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise UnsupportedStandardError("encrypted standards are not supported")
        if not reader.pages:
            raise UnsupportedStandardError("standard PDF has no pages")
        text = "\n".join(
            page.extract_text() or "" for page in reader.pages[:MAX_IDENTITY_PAGES]
        )
        metadata = {
            str(key): str(value)
            for key, value in (reader.metadata or {}).items()
            if value is not None
        }
        return reader, hashlib.sha256(payload).hexdigest(), _normalized(text), metadata
    except StandardIdentificationError:
        raise
    except (OSError, EOFError, TypeError, ValueError) as error:
        raise UnsupportedStandardError("standard PDF could not be read") from error


def identify_standard(path: Path) -> StandardIdentity:
    """Identify one supported edition without trusting the filename."""

    reader, digest, text, metadata = _read_pdf(path)
    # Imported lazily to avoid recipe registration during module initialization.
    from insulation_coordination.rules.importer.recipes import RECIPES

    text_matches = tuple(recipe for recipe in RECIPES if recipe.matches_text(text))
    if len(text_matches) > 1:
        raise AmbiguousStandardError("PDF matches more than one supported standard recipe")
    matches = tuple(
        recipe
        for recipe in RECIPES
        if recipe.matches_identity(text=text, metadata=metadata)
    )
    if not matches:
        raise UnsupportedStandardError("PDF is not a recognized supported IEC edition")
    if len(matches) != 1:
        raise AmbiguousStandardError("PDF matches more than one supported standard recipe")
    recipe = matches[0]
    LOGGER.info(
        "recognized standard recipe=%s pages=%d",
        recipe.id,
        len(reader.pages),
    )
    return StandardIdentity(
        standard=recipe.standard,
        edition=recipe.edition,
        sha256=digest,
        page_count=len(reader.pages),
        recipe_id=recipe.id,
    )
