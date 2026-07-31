from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pdfplumber
from pdfminer.pdfexceptions import PDFException
from pdfminer.psparser import PSException
from pydantic import Field, model_validator
from pypdf import PdfReader
from pypdf._page import PageObject
from pypdf._text_extraction import mult
from pypdf.errors import PyPdfError

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    RULE_SCHEMA_VERSION,
    ApprovalRecord,
    CompatibilityMapping,
    DraftRulePackage,
    Formula,
    Manifest,
    NotesText,
    SourceDocument,
    SourceReference,
    Table,
)
from insulation_coordination.rules.archive import _canonical_json
from insulation_coordination.rules.importer.identify import (
    FormulaAuditSpec,
    MappingAuditSpec,
    StandardIdentity,
    StandardRecipe,
    TableAuditSpec,
    identify_standard,
)

IMPORTER_VERSION = "iec-pdf-1"
_REQUIRED_RECIPES = {"iec60664-1-2020", "iec60664-4-2005"}

__all__ = [
    "ExtractionError",
    "FormulaAuditSpec",
    "ImportReviewItem",
    "ImportedRuleDraft",
    "MappingAuditSpec",
    "RawGrid",
    "RawGridCell",
    "StandardRecipe",
    "TableAuditSpec",
    "extract_draft",
]


class ExtractionError(ValueError):
    """Recognized input could not be extracted without guessing."""


class ImportReviewItem(FrozenModel):
    code: Literal[
        "MANUAL_TABLE_DEFINITION_REQUIRED",
        "MANUAL_RULE_DEFINITION_REQUIRED",
        "MANUAL_MAPPING_REQUIRED",
        "MANUAL_RAW_CELL_REVIEW_REQUIRED",
    ]
    semantic_id: str
    kind: Literal["table", "formula", "mapping", "raw_cell"]
    source: SourceReference
    expected_contract: NotesText

    @property
    def sha256(self) -> str:
        payload = self.model_dump(mode="json", warnings=False)
        return hashlib.sha256(_canonical_json(payload)).hexdigest()


class ImportReviewResolution(FrozenModel):
    review_item_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    actor: str
    recorded_at: datetime
    notes: NotesText


class RawGridCell(FrozenModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    raw_text: str = Field(max_length=2_000)
    value: Decimal | None = None
    qualifier: str | None = Field(default=None, max_length=8)
    suffix: str | None = Field(default=None, max_length=32)
    parse_status: Literal["blank", "text", "numeric", "ambiguous_numeric"]
    source: SourceReference


class RawGrid(FrozenModel):
    id: str
    rows: int = Field(ge=1)
    columns: int = Field(ge=1)
    target_unit: str
    cells: tuple[RawGridCell, ...]
    source: SourceReference

    @model_validator(mode="after")
    def _valid_coordinates(self) -> RawGrid:
        coordinates = tuple((cell.row, cell.column) for cell in self.cells)
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("raw grid cell coordinates must be unique")
        if any(
            cell.row >= self.rows or cell.column >= self.columns
            for cell in self.cells
        ):
            raise ValueError("raw grid cell coordinate is outside declared dimensions")
        return self


class ImportedRuleDraft(DraftRulePackage):
    review_items: tuple[ImportReviewItem, ...] = ()
    review_resolutions: tuple[ImportReviewResolution, ...] = ()
    raw_grids: tuple[RawGrid, ...] = ()
    source_identities: tuple[StandardIdentity, ...]


def _content_digest(
    tables: tuple[Table, ...],
    formulas: tuple[Formula, ...],
    mappings: tuple[CompatibilityMapping, ...],
    review_items: tuple[ImportReviewItem, ...] = (),
    raw_grids: tuple[RawGrid, ...] = (),
    source_documents: tuple[SourceDocument, ...] = (),
    source_identities: tuple[StandardIdentity, ...] = (),
    review_resolutions: tuple[ImportReviewResolution, ...] = (),
) -> str:
    payload = {
        "tables": [item.model_dump(mode="json") for item in tables],
        "formulas": [item.model_dump(mode="json") for item in formulas],
        "mappings": [item.model_dump(mode="json") for item in mappings],
        "review_items": [item.model_dump(mode="json") for item in review_items],
        "review_resolutions": [
            item.model_dump(mode="json") for item in review_resolutions
        ],
        "raw_grids": [item.model_dump(mode="json") for item in raw_grids],
        "source_documents": [
            item.model_dump(mode="json") for item in source_documents
        ],
        "source_identities": [
            item.model_dump(mode="json") for item in source_identities
        ],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _recipe(identity: StandardIdentity) -> StandardRecipe:
    from insulation_coordination.rules.importer.recipes import RECIPES

    matches = tuple(recipe for recipe in RECIPES if recipe.id == identity.recipe_id)
    if len(matches) != 1:
        raise ExtractionError(f"no unique extraction recipe for {identity.recipe_id}")
    return matches[0]


_NUMERIC_CELL = re.compile(
    r"^\s*(<=|>=|<|>|≤|≥)?\s*([0-9]+(?:[.,][0-9]+)?)\s*(\S*)\s*$"
)


def _numeric_token(
    value: str | None,
) -> tuple[Decimal, str | None, str | None] | None:
    if value is None:
        return None
    match = _NUMERIC_CELL.fullmatch(value.replace("\n", " "))
    if match is None:
        return None
    qualifier = match.group(1) or None
    suffix = match.group(3) or None
    return Decimal(match.group(2).replace(",", ".")), qualifier, suffix


def _parsed_cell(
    value: str | None,
    *,
    allowed_suffixes: tuple[str, ...],
) -> tuple[str, Decimal | None, str | None, str | None, str]:
    raw_text = "" if value is None else value
    if len(raw_text) > 2_000:
        raise ExtractionError("raw table cell exceeds the fidelity size limit")
    if not raw_text.strip():
        return raw_text, None, None, None, "blank"
    token = _numeric_token(raw_text)
    if token is None:
        return raw_text, None, None, None, "text"
    number, qualifier, suffix = token
    ambiguous = qualifier in {"<=", ">="} or (
        suffix is not None and suffix not in allowed_suffixes
    )
    return (
        raw_text,
        number,
        qualifier,
        suffix,
        "ambiguous_numeric" if ambiguous else "numeric",
    )


def _source(
    identity: StandardIdentity,
    *,
    page_number: int,
    clause: str,
    table: str | None = None,
    figure: str | None = None,
    row: str | None = None,
    column: str | None = None,
) -> SourceReference:
    return SourceReference(
        standard=identity.standard,
        edition=identity.edition,
        clause=clause,
        table=table,
        figure=figure,
        row=row,
        column=column,
        note=f"PDF page {page_number}",
    )


def _anchor_boxes(
    page: PageObject,
    *,
    anchor_text: str,
) -> tuple[dict[str, float], ...]:
    matches: list[dict[str, float]] = []
    page_height = float(page.mediabox.height)
    normalized_anchor = re.sub(r"\s+", " ", anchor_text).strip().casefold()

    def visitor(
        text: str,
        current_matrix: list[float],
        text_matrix: list[float],
        _font: object,
        font_size: float,
    ) -> None:
        normalized_text = re.sub(r"\s+", " ", text).strip().casefold()
        if normalized_anchor not in normalized_text:
            return
        matrix = mult(text_matrix, current_matrix)
        height = max(
            1.0,
            abs(font_size * current_matrix[3]),
            abs(text_matrix[3]),
        )
        x0 = float(matrix[4])
        bottom = page_height - float(matrix[5]) + height * 0.25
        top = bottom - height * 1.25
        width = max(height, len(normalized_text) * height * 0.5)
        matches.append(
            {
                "x0": x0,
                "x1": x0 + width,
                "top": top,
                "bottom": bottom,
            }
        )

    page.extract_text(visitor_text=visitor)
    return tuple(matches)


def _extract_layout_table(
    page: pdfplumber.page.Page,
    anchor_page: PageObject,
    identity: StandardIdentity,
    spec: TableAuditSpec,
) -> tuple[RawGrid, tuple[ImportReviewItem, ...]]:
    anchors = _anchor_boxes(anchor_page, anchor_text=spec.title_anchor)
    if not anchors:
        raise ExtractionError(
            f"layout anchor is missing for {spec.semantic_id}; extraction refused"
        )
    matching = []
    for found in page.find_tables():
        raw = found.extract()
        shape = (len(raw), max((len(row) for row in raw), default=0))
        bbox_matches = all(
            abs(float(actual) - expected) <= spec.bbox_tolerance
            for actual, expected in zip(found.bbox, spec.expected_bbox, strict=True)
        )
        spatially_bound = any(
            found.bbox[1] >= anchor["bottom"]
            and found.bbox[1] - anchor["bottom"] <= spec.anchor_max_vertical_gap
            and max(
                0.0,
                min(found.bbox[2], anchor["x1"])
                - max(found.bbox[0], anchor["x0"]),
            )
            / max(
                1.0,
                min(
                    found.bbox[2] - found.bbox[0],
                    anchor["x1"] - anchor["x0"],
                ),
            )
            >= spec.anchor_min_x_overlap
            for anchor in anchors
        )
        if (
            shape == (spec.expected_raw_rows, spec.expected_raw_columns)
            and bbox_matches
            and spatially_bound
        ):
            matching.append(found)
    if len(matching) != 1:
        raise ExtractionError(
            f"layout dimensions are ambiguous for {spec.semantic_id}; extraction refused"
        )
    raw = matching[0].extract()
    table_source = _source(
        identity,
        page_number=spec.page_number,
        clause=spec.clause,
        table=spec.source_table,
    )
    cells: list[RawGridCell] = []
    for row in range(spec.expected_raw_rows):
        for column in range(spec.expected_raw_columns):
            raw_text, value, qualifier, suffix, parse_status = _parsed_cell(
                raw[row][column],
                allowed_suffixes=spec.allowed_suffixes,
            )
            cells.append(
                RawGridCell(
                    row=row,
                    column=column,
                    raw_text=raw_text,
                    value=value,
                    qualifier=qualifier,
                    suffix=suffix,
                    parse_status=parse_status,  # type: ignore[arg-type]
                    source=_source(
                        identity,
                        page_number=spec.page_number,
                        clause=spec.clause,
                        table=spec.source_table,
                        row=f"grid row {row + 1}",
                        column=f"grid column {column + 1}",
                    ),
                )
            )
    grid = RawGrid(
        id=f"raw-{spec.semantic_id}",
        rows=spec.expected_raw_rows,
        columns=spec.expected_raw_columns,
        target_unit=spec.target_unit,
        cells=tuple(cells),
        source=table_source,
    )
    if spec.data_strategy == "rectangle":
        if spec.data_row_start is None or spec.data_column_start is None:
            raise ExtractionError("rectangle data contract has no starting coordinate")
        data_coordinates = {
            (spec.data_row_start + row, spec.data_column_start + column)
            for row in range(spec.expected_data_rows)
            for column in range(spec.expected_data_columns)
        }
    else:
        numeric = tuple(cell for cell in cells if cell.value is not None)
        if len(numeric) != spec.expected_data_rows * spec.expected_data_columns:
            raise ExtractionError(
                f"layout data dimensions do not match for {spec.semantic_id}"
            )
        data_coordinates = {(cell.row, cell.column) for cell in numeric}
    reviews = tuple(
        ImportReviewItem(
            code="MANUAL_RAW_CELL_REVIEW_REQUIRED",
            semantic_id=f"{grid.id}:{cell.row}:{cell.column}",
            kind="raw_cell",
            source=cell.source,
            expected_contract=f"raw-cell:{spec.semantic_id}:numeric",
        )
        for cell in cells
        if (cell.row, cell.column) in data_coordinates
        and cell.parse_status != "numeric"
    )
    return grid, reviews


def _manual_review_items(
    identity: StandardIdentity,
    recipe: StandardRecipe,
) -> tuple[ImportReviewItem, ...]:
    table_items = tuple(
        ImportReviewItem(
            code="MANUAL_TABLE_DEFINITION_REQUIRED",
            semantic_id=spec.semantic_id,
            kind="table",
            source=_source(
                identity,
                page_number=spec.page_number,
                clause=spec.clause,
                table=spec.source_table,
            ),
            expected_contract=(
                f"table:{spec.semantic_id}:"
                f"{hashlib.sha256(_canonical_json(spec.model_dump(mode='json'))).hexdigest()}"
            ),
        )
        for spec in recipe.tables
    )
    formula_items = tuple(
        ImportReviewItem(
            code="MANUAL_RULE_DEFINITION_REQUIRED",
            semantic_id=spec.semantic_id,
            kind="formula",
            source=_source(
                identity,
                page_number=spec.page_number,
                clause=spec.clause,
                table=spec.table,
                figure=spec.figure,
            ),
            expected_contract=(
                f"formula:{spec.semantic_id}:"
                f"{hashlib.sha256(_canonical_json(spec.model_dump(mode='json'))).hexdigest()}"
            ),
        )
        for spec in recipe.formulas
    )
    mapping_items = tuple(
        ImportReviewItem(
            code="MANUAL_MAPPING_REQUIRED",
            semantic_id=spec.id,
            kind="mapping",
            source=_source(
                identity,
                page_number=spec.page_number,
                clause=spec.clause,
                table=spec.table,
                figure=spec.figure,
            ),
            expected_contract=(
                f"mapping:{spec.id}:"
                f"{hashlib.sha256(_canonical_json(spec.model_dump(mode='json'))).hexdigest()}"
            ),
        )
        for spec in recipe.mappings
    )
    return (*table_items, *formula_items, *mapping_items)


def _extract_real_layout(
    path: Path,
    identity: StandardIdentity,
    recipe: StandardRecipe,
) -> tuple[tuple[RawGrid, ...], tuple[ImportReviewItem, ...]]:
    try:
        anchor_reader = PdfReader(path)
        with pdfplumber.open(path) as pdf:
            extracted = tuple(
                _extract_layout_table(
                    pdf.pages[spec.page_number - 1],
                    anchor_reader.pages[spec.page_number - 1],
                    identity,
                    spec,
                )
                for spec in recipe.tables
            )
    except ExtractionError:
        raise
    except (
        OSError,
        EOFError,
        IndexError,
        PDFException,
        PyPdfError,
        PSException,
        TypeError,
        ValueError,
    ) as error:
        raise ExtractionError("recognized PDF layout could not be extracted") from error
    grids = tuple(grid for grid, _ in extracted)
    raw_reviews = tuple(item for _, reviews in extracted for item in reviews)
    return grids, (*_manual_review_items(identity, recipe), *raw_reviews)


def _extract_one(
    path: Path, identity: StandardIdentity
) -> tuple[
    tuple[Table, ...],
    tuple[Formula, ...],
    tuple[CompatibilityMapping, ...],
    tuple[ImportReviewItem, ...],
    tuple[RawGrid, ...],
]:
    recipe = _recipe(identity)
    grids, review_items = _extract_real_layout(path, identity, recipe)
    return (), (), (), review_items, grids


def _require_unique_ids(
    tables: tuple[Table, ...],
    formulas: tuple[Formula, ...],
    mappings: tuple[CompatibilityMapping, ...],
) -> None:
    for label, values in (
        ("table", tuple(item.id for item in tables)),
        ("formula", tuple(item.id for item in formulas)),
        ("mapping", tuple(item.id for item in mappings)),
    ):
        if len(values) != len(set(values)):
            raise ExtractionError(f"duplicate extracted {label} semantic ID")


def extract_draft(paths: tuple[Path, ...]) -> ImportedRuleDraft:
    """Extract recognized sources into a deliberately unusable immutable draft."""

    if not paths:
        raise ExtractionError("exactly one PDF for each supported IEC part is required")
    identified = tuple((path, identify_standard(path)) for path in paths)
    recipe_ids = tuple(identity.recipe_id for _, identity in identified)
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ExtractionError("duplicate supported IEC part")
    if set(recipe_ids) != _REQUIRED_RECIPES:
        raise ExtractionError("exactly one PDF for each supported IEC part is required")

    tables: tuple[Table, ...] = ()
    formulas: tuple[Formula, ...] = ()
    mappings: tuple[CompatibilityMapping, ...] = ()
    review_items: tuple[ImportReviewItem, ...] = ()
    raw_grids: tuple[RawGrid, ...] = ()
    for path, identity in sorted(identified, key=lambda pair: pair[1].recipe_id):
        (
            extracted_tables,
            extracted_formulas,
            extracted_mappings,
            extracted_reviews,
            extracted_grids,
        ) = _extract_one(path, identity)
        tables += extracted_tables
        formulas += extracted_formulas
        mappings += extracted_mappings
        review_items += extracted_reviews
        raw_grids += extracted_grids
    _require_unique_ids(tables, formulas, mappings)

    recorded_at = datetime.now(UTC)
    records = tuple(
        ApprovalRecord(
            action="extraction",
            actor=f"icc-importer/{IMPORTER_VERSION}",
            recorded_at=recorded_at,
            notes=note,
        )
        for note in (
            *(
                note
                for _, identity in identified
                for note in (
                    f"identity:{identity.recipe_id}",
                    f"layout:{identity.recipe_id}",
                )
            ),
            *(f"table:{table.id}" for table in tables),
            *(f"formula:{formula.id}" for formula in formulas),
            *(f"mapping:{mapping.id}" for mapping in mappings),
            *(f"raw-grid:{grid.id}" for grid in raw_grids),
            *(
                f"review:{item.code}:{item.semantic_id}"
                for item in review_items
            ),
            f"content:{_content_digest(tables, formulas, mappings, review_items, raw_grids)}",
        )
    )
    ordered_identities = tuple(
        identity
        for _, identity in sorted(identified, key=lambda pair: pair[1].recipe_id)
    )
    sources = tuple(
        SourceDocument(
            standard=identity.standard,
            edition=identity.edition,
            sha256=identity.sha256,
        )
        for identity in ordered_identities
    )
    content_digest = _content_digest(
        tables,
        formulas,
        mappings,
        review_items,
        raw_grids,
        sources,
        ordered_identities,
    )
    records = tuple(
        record.model_copy(update={"notes": f"content:{content_digest}"})
        if record.notes.startswith("content:")
        else record
        for record in records
    )
    return ImportedRuleDraft(
        manifest=Manifest(
            schema_version=RULE_SCHEMA_VERSION,
            package_id=uuid4(),
            version="iec60664-v1-draft",
            importer_version=IMPORTER_VERSION,
            created_at=recorded_at,
            source_documents=sources,
            approved=False,
            compatible=False,
            approval_records=records,
            notes="",
        ),
        tables=tables,
        formulas=formulas,
        mappings=mappings,
        review_items=review_items,
        raw_grids=raw_grids,
        source_identities=ordered_identities,
    )
