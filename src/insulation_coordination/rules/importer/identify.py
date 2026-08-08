from __future__ import annotations

import hashlib
import logging
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
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


class UnsupportedEditionError(UnsupportedStandardError):
    """The PDF is a supported standard, but not the supported edition."""

    def __init__(self, standard: str, edition: str) -> None:
        self.detected_standard = standard
        self.detected_edition = edition
        super().__init__(
            f"{standard} edition {edition} is not supported; this build supports one edition "
            "per standard and will not mix editions"
        )


class PasswordRequiredError(StandardIdentificationError):
    """The PDF could not be unlocked with the available password."""

    def __init__(self, path: Path, *, supplied: bool = False) -> None:
        self.path = path
        message = (
            "could not unlock encrypted standard PDF with the supplied password"
            if supplied
            else "encrypted standard PDF requires a password"
        )
        super().__init__(f"{message}: {path.name}")


class AmbiguousStandardError(StandardIdentificationError):
    """More than one recipe matched the PDF."""


class StandardIdentity(FrozenModel):
    standard: Identifier
    edition: Identifier
    sha256: str = Field(pattern=r"[0-9a-f]{64}")
    page_count: int = Field(ge=1)
    recipe_id: Identifier


class TableSegmentSpec(FrozenModel):
    id: Identifier
    page_number: int = Field(ge=1)
    title_anchor: ReferenceText
    expected_raw_rows: int = Field(ge=1)
    expected_raw_columns: int = Field(ge=1)
    expected_bbox: tuple[float, float, float, float]
    bbox_tolerance: float = Field(default=1.0, ge=0, le=200)
    anchor_max_vertical_gap: float = Field(default=80.0, ge=0, le=300)
    anchor_min_x_overlap: float = Field(default=0.1, ge=0, le=1)
    logical_row_offset: int = Field(default=0, ge=0)
    source_columns: tuple[int, ...] = ()
    header_rows: tuple[int, ...] = ()
    data_rows: tuple[int, ...] = ()
    note_rows: tuple[int, ...] = ()
    footnote_rows: tuple[int, ...] = ()
    context_cells: tuple[tuple[int, int], ...] = ()
    page_search_radius: int = Field(default=0, ge=0, le=5)


class CompoundQuantitySpec(FrozenModel):
    component_ids: tuple[Identifier, ...] = Field(min_length=1)
    formula_candidates: tuple[tuple[Identifier, Identifier | None], ...] = ()

    @model_validator(mode="after")
    def _valid_component_contract(self) -> CompoundQuantitySpec:
        if len(self.component_ids) != len(set(self.component_ids)):
            raise ValueError("compound component IDs must be unique")
        unknown = {
            component_id
            for component_id, _formula_id in self.formula_candidates
            if component_id not in self.component_ids
        }
        if unknown:
            raise ValueError("formula candidate refers to an undeclared compound component")
        return self


class TableColumnSpec(FrozenModel):
    semantic_id: Identifier
    heading: ReferenceText
    source_column: int = Field(ge=0)
    role: Literal["axis", "data", "context"]
    unit: Identifier
    axis_value: Decimal | None = None
    #: This column's axis value is the number found in this row of its own header,
    #: instead of a value declared in the recipe. Use this for axis values that come
    #: from a licensed table's own header row rather than a value safe to hardcode.
    axis_value_source_row: int | None = Field(default=None, ge=0)
    fill_down: bool = False
    compound_quantity: CompoundQuantitySpec | None = None
    projected_component_id: Identifier | None = None

    @model_validator(mode="after")
    def _valid_projected_component(self) -> TableColumnSpec:
        if self.projected_component_id is not None and (
            self.compound_quantity is None
            or self.projected_component_id not in self.compound_quantity.component_ids
        ):
            raise ValueError("projected component must belong to the compound quantity")
        if self.compound_quantity is not None and self.role != "data":
            raise ValueError("only data columns may declare compound quantities")
        return self


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
    allowed_qualifiers: tuple[Literal["up_to"], ...] = ()
    assertions: tuple[
        Literal[
            "complete_grid",
            "strictly_increasing_axes",
            "raw_value_correspondence",
        ],
        ...,
    ]
    segments: tuple[TableSegmentSpec, ...] = ()
    columns: tuple[TableColumnSpec, ...] = ()
    page_search_radius: int = Field(default=0, ge=0, le=5)
    interpolation: Literal["none", "linear"] = "none"

    @model_validator(mode="after")
    def _axis_value_source_row_is_a_declared_header_row(self) -> TableAuditSpec:
        """A column's declared axis-value row must be one extraction will mark as a

        header, in segment-local numbering -- the same space ``header_rows`` already
        uses. Otherwise the row could resolve to a data cell at runtime instead of
        raising, silently feeding a data value into the column axis.
        """
        for column in self.columns:
            if column.axis_value_source_row is None:
                continue
            if not any(
                column.axis_value_source_row in segment.header_rows for segment in self.segments
            ):
                raise ValueError(
                    f"column {column.semantic_id!r} axis_value_source_row "
                    f"{column.axis_value_source_row} is not declared in any segment's "
                    "header_rows"
                )
        return self


class EquationAuditSpec(FrozenModel):
    semantic_id: Identifier
    unit: Identifier
    variables: tuple[Identifier, ...]
    expression_shape: ReferenceText
    page_number: int = Field(ge=1)
    clause: ReferenceText
    table: ReferenceText | None = None
    figure: ReferenceText | None = None
    rendered_anchor: ReferenceText | None = None
    applicability: ReferenceText = "review required"
    extract_from_pdf: bool = False
    expected_bbox: tuple[float, float, float, float] | None = None


FormulaAuditSpec = EquationAuditSpec


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
    identity_claim_pattern: str
    expected_page_count: int = Field(ge=1)
    accepted_page_counts: tuple[int, ...] = ()
    page_number_offsets: tuple[tuple[int, int], ...] = ()
    metadata_identity_fields: tuple[str, ...]
    metadata_identity_anchors: tuple[str, ...]
    identity_anchors: tuple[str, ...]
    tables: tuple[TableAuditSpec, ...]
    formulas: tuple[FormulaAuditSpec, ...]
    mappings: tuple[MappingAuditSpec, ...]

    def matches_text(self, text: str) -> bool:
        return all(_normalized(anchor) in text for anchor in self.identity_anchors)

    def detected_claims(
        self, *, first_page_text: str, metadata: dict[str, str]
    ) -> set[tuple[str, str]]:
        """Every (standard, edition) pair this recipe's pattern finds in the document.

        The standard is normalized because PDF text extraction produces irregular
        whitespace: a document rendering "IEC  60664-1" would otherwise never equal the
        recipe's own name, and the document would be rejected as unrecognized.
        """
        return {
            (_normalized(standard), edition)
            for value in (*metadata.values(), first_page_text)
            for standard, edition in re.findall(self.identity_claim_pattern, value)
        }

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
        identifying_claims = self.detected_claims(
            first_page_text=first_page_text, metadata=metadata
        )
        if identifying_claims - {(_normalized(self.standard), self.edition)}:
            return False
        metadata_identifies_document = all(
            _normalized(anchor) in metadata_text for anchor in self.metadata_identity_anchors
        )
        return (
            metadata_identifies_document
            or page_count in (self.expected_page_count, *self.accepted_page_counts)
        ) and self.matches_text(text)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _read_pdf(
    path: Path,
    password: str | None = None,
) -> tuple[PdfReader, str, str, str, dict[str, str]]:
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_STANDARD_PDF_BYTES:
            raise UnsupportedStandardError("standard PDF has an invalid or excessive size")
        payload = path.read_bytes()
        if not payload.startswith(b"%PDF-"):
            raise UnsupportedStandardError("standard source is not a PDF")
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(password or ""):
            raise PasswordRequiredError(path, supplied=password is not None)
        if not reader.pages:
            raise UnsupportedStandardError("standard PDF has no pages")
        page_texts = tuple(page.extract_text() or "" for page in reader.pages[:MAX_IDENTITY_PAGES])
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


def identify_standard(path: Path, password: str | None = None) -> StandardIdentity:
    """Identify one supported edition without trusting the filename."""

    reader, digest, text, first_page_text, metadata = _read_pdf(path, password=password)
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
        for recipe in RECIPES:
            for standard, edition in recipe.detected_claims(
                first_page_text=first_page_text,
                metadata=metadata,
            ):
                if standard == _normalized(recipe.standard) and edition != recipe.edition:
                    raise UnsupportedEditionError(recipe.standard, edition)
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
