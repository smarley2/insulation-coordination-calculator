from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Literal

from pydantic import Field
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    Identifier,
    ReferenceText,
)

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


class TableAuditSpec(FrozenModel):
    semantic_id: Identifier
    source_table: ReferenceText
    title_anchor: ReferenceText
    page_number: int = Field(ge=1)
    clause: ReferenceText
    target_unit: Identifier
    expected_raw_rows: int = Field(ge=1)
    expected_raw_columns: int = Field(ge=1)
    expected_bbox: tuple[float, float, float, float]
    bbox_tolerance: float = Field(default=1.0, ge=0, le=200)
    anchor_max_vertical_gap: float = Field(default=80.0, ge=0, le=300)
    anchor_min_x_overlap: float = Field(default=0.1, ge=0, le=1)
    data_strategy: Literal["rectangle", "numeric_row_major"]
    data_row_start: int | None = Field(default=None, ge=0)
    data_column_start: int | None = Field(default=None, ge=0)
    expected_data_rows: int = Field(ge=1)
    expected_data_columns: int = Field(ge=1)
    row_axis_id: Identifier
    row_axis_unit: Identifier
    column_axis_id: Identifier
    column_axis_unit: Identifier
    allowed_suffixes: tuple[str, ...] = ()
    assertions: tuple[
        Literal[
            "complete_grid",
            "strictly_increasing_axes",
            "raw_value_correspondence",
        ],
        ...,
    ]


class FormulaAuditSpec(FrozenModel):
    semantic_id: Identifier
    unit: Identifier
    variables: tuple[Identifier, ...]
    expression_shape: ReferenceText
    page_number: int = Field(ge=1)
    clause: ReferenceText
    table: ReferenceText | None = None
    figure: ReferenceText | None = None


class MappingAuditSpec(FrozenModel):
    id: Identifier
    semantic_route: Identifier
    target_rule_id: Identifier
    family: Identifier
    page_number: int = Field(ge=1)
    clause: ReferenceText
    table: ReferenceText | None = None
    figure: ReferenceText | None = None


class StandardRecipe(FrozenModel):
    id: Identifier
    standard: Identifier
    edition: Identifier
    expected_page_count: int = Field(ge=1)
    metadata_identity_fields: tuple[str, ...]
    metadata_identity_anchors: tuple[str, ...]
    identity_anchors: tuple[str, ...]
    tables: tuple[TableAuditSpec, ...]
    formulas: tuple[FormulaAuditSpec, ...]
    mappings: tuple[MappingAuditSpec, ...]

    def matches_text(self, text: str) -> bool:
        return all(_normalized(anchor) in text for anchor in self.identity_anchors)

    def matches_identity(
        self,
        *,
        text: str,
        first_page_text: str,
        metadata: dict[str, str],
        page_count: int,
    ) -> bool:
        metadata_text = _normalized(
            " ".join(metadata.get(field, "") for field in self.metadata_identity_fields)
        )
        identifying_claims = {
            (f"IEC 60664-{part}", edition)
            for value in (*metadata.values(), first_page_text)
            for part, edition in re.findall(
                r"(?i)IEC\s*60664-([14]).{0,24}?\b((?:19|20)\d{2})\b",
                value,
            )
        }
        if identifying_claims - {(self.standard, self.edition)}:
            return False
        metadata_identifies_document = all(
            _normalized(anchor) in metadata_text
            for anchor in self.metadata_identity_anchors
        )
        return (
            metadata_identifies_document or page_count == self.expected_page_count
        ) and self.matches_text(text)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _read_pdf(
    path: Path,
) -> tuple[PdfReader, str, str, str, dict[str, str]]:
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
        page_texts = tuple(
            page.extract_text() or "" for page in reader.pages[:MAX_IDENTITY_PAGES]
        )
        text = "\n".join(page_texts)
        metadata = {
            str(key): str(value)
            for key, value in (reader.metadata or {}).items()
            if value is not None
        }
        return (
            reader,
            hashlib.sha256(payload).hexdigest(),
            _normalized(text),
            _normalized(page_texts[0]),
            metadata,
        )
    except StandardIdentificationError:
        raise
    except (OSError, EOFError, PyPdfError, TypeError, ValueError) as error:
        raise UnsupportedStandardError("standard PDF could not be read") from error


def identify_standard(path: Path) -> StandardIdentity:
    """Identify one supported edition without trusting the filename."""

    reader, digest, text, first_page_text, metadata = _read_pdf(path)
    # Imported lazily to avoid recipe registration during module initialization.
    from insulation_coordination.rules.importer.recipes import RECIPES

    text_matches = tuple(recipe for recipe in RECIPES if recipe.matches_text(text))
    if len(text_matches) > 1:
        raise AmbiguousStandardError("PDF matches more than one supported standard recipe")
    matches = tuple(
        recipe
        for recipe in RECIPES
        if recipe.matches_identity(
            text=text,
            first_page_text=first_page_text,
            metadata=metadata,
            page_count=len(reader.pages),
        )
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
