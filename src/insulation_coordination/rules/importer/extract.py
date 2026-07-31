from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypedDict
from uuid import uuid4

import pdfplumber
from pydantic import Field, ValidationError, model_validator
from pypdf import PdfReader

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    RULE_SCHEMA_VERSION,
    ApprovalRecord,
    CompatibilityMapping,
    DraftRulePackage,
    Formula,
    Manifest,
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
_SYNTHETIC_BEGIN = "ICC-SYNTHETIC-RULES-BEGIN"
_SYNTHETIC_END = "ICC-SYNTHETIC-RULES-END"
_MAX_EXTRACTED_PAYLOAD_BYTES = 32 * 1024 * 1024

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
    ]
    semantic_id: str
    kind: Literal["table", "formula", "mapping"]
    source: SourceReference


class RawGridCell(FrozenModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    value: Decimal
    qualifier: Literal["<", ">", "≤", "≥"] | None = None
    suffix: str | None = Field(default=None, max_length=16)
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
    raw_grids: tuple[RawGrid, ...] = ()


class _Payload(TypedDict):
    tables: list[object]
    formulas: list[object]
    mappings: list[object]


def _content_digest(
    tables: tuple[Table, ...],
    formulas: tuple[Formula, ...],
    mappings: tuple[CompatibilityMapping, ...],
    review_items: tuple[ImportReviewItem, ...] = (),
    raw_grids: tuple[RawGrid, ...] = (),
) -> str:
    payload = {
        "tables": [item.model_dump(mode="json") for item in tables],
        "formulas": [item.model_dump(mode="json") for item in formulas],
        "mappings": [item.model_dump(mode="json") for item in mappings],
        "review_items": [item.model_dump(mode="json") for item in review_items],
        "raw_grids": [item.model_dump(mode="json") for item in raw_grids],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _recipe(identity: StandardIdentity) -> StandardRecipe:
    from insulation_coordination.rules.importer.recipes import RECIPES

    matches = tuple(recipe for recipe in RECIPES if recipe.id == identity.recipe_id)
    if len(matches) != 1:
        raise ExtractionError(f"no unique extraction recipe for {identity.recipe_id}")
    return matches[0]


def _synthetic_payload(path: Path) -> _Payload | None:
    try:
        reader = PdfReader(path)
        metadata = {str(key): str(value) for key, value in (reader.metadata or {}).items()}
        if metadata.get("/ICC-Synthetic", "").casefold() != "true":
            return None
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        match = re.search(
            rf"{_SYNTHETIC_BEGIN}\s+([A-Za-z0-9+/=\s]+?)\s+{_SYNTHETIC_END}",
            text,
        )
        if match is None:
            raise ExtractionError("synthetic PDF has no unambiguous rule payload")
        encoded = re.sub(r"\s+", "", match.group(1))
        decoded = base64.b64decode(encoded, validate=True)
        if len(decoded) > _MAX_EXTRACTED_PAYLOAD_BYTES:
            raise ExtractionError("synthetic extraction payload exceeds the size limit")
        value = json.loads(decoded)
        if not isinstance(value, dict) or set(value) != {
            "tables",
            "formulas",
            "mappings",
        }:
            raise ExtractionError("synthetic extraction payload has an invalid shape")
        if not all(
            isinstance(value[key], list)
            for key in ("tables", "formulas", "mappings")
        ):
            raise ExtractionError("synthetic extraction payload collections must be arrays")
        return _Payload(
            tables=value["tables"],
            formulas=value["formulas"],
            mappings=value["mappings"],
        )
    except ExtractionError:
        raise
    except (
        OSError,
        EOFError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as error:
        raise ExtractionError("synthetic extraction payload could not be decoded") from error


def _references(item: Table | Formula | CompatibilityMapping) -> tuple[SourceReference, ...]:
    if isinstance(item, Table):
        return (
            item.source,
            *(cell.source for cell in item.cells),
            *(supported.source for supported in item.supported_ranges),
        )
    if isinstance(item, Formula):
        return (
            item.source,
            *(parameter_set.source for parameter_set in item.parameter_sets),
            *(supported.source for supported in item.supported_ranges),
        )
    return (item.source,)


def _require_exact_sources(
    items: tuple[Table | Formula | CompatibilityMapping, ...],
    identity: StandardIdentity,
) -> None:
    if any(
        source.standard != identity.standard or source.edition != identity.edition
        for item in items
        for source in _references(item)
    ):
        raise ExtractionError("extracted record source does not match its recognized PDF")


_NUMERIC_CELL = re.compile(
    r"^\s*([<>≤≥]?)\s*([0-9]+(?:[.,][0-9]+)?)\s*([a-zA-Z*]*)\s*$"
)


def _numeric_token(
    value: str | None,
) -> tuple[Decimal, Literal["<", ">", "≤", "≥"] | None, str | None] | None:
    if value is None:
        return None
    match = _NUMERIC_CELL.fullmatch(value.replace("\n", " "))
    if match is None:
        return None
    qualifier_text = match.group(1)
    qualifier: Literal["<", ">", "≤", "≥"] | None = (
        qualifier_text if qualifier_text else None  # type: ignore[assignment]
    )
    suffix = match.group(3) or None
    return Decimal(match.group(2).replace(",", ".")), qualifier, suffix


def _largest_numeric_rectangle(
    raw: list[list[str | None]],
) -> tuple[int, int, int, int]:
    rows = len(raw)
    columns = max((len(row) for row in raw), default=0)
    values = [
        [
            _numeric_token(raw[row][column]) if column < len(raw[row]) else None
            for column in range(columns)
        ]
        for row in range(rows)
    ]
    best_score: tuple[int, int, int] | None = None
    best_regions: list[tuple[int, int, int, int]] = []
    for row_start in range(rows):
        for row_end in range(row_start + 1, rows + 1):
            for column_start in range(columns):
                for column_end in range(column_start + 1, columns + 1):
                    if not all(
                        values[row][column] is not None
                        for row in range(row_start, row_end)
                        for column in range(column_start, column_end)
                    ):
                        continue
                    height = row_end - row_start
                    width = column_end - column_start
                    score = (
                        height * width,
                        height,
                        width,
                    )
                    region = (row_start, row_end, column_start, column_end)
                    if best_score is None or score > best_score:
                        best_score = score
                        best_regions = [region]
                    elif score == best_score:
                        best_regions.append(region)
    if best_score is None:
        raise ExtractionError("anchored table has no unambiguous numeric rectangle")
    if len(best_regions) != 1:
        raise ExtractionError("anchored table has ambiguous numeric rectangles")
    return best_regions[0]


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


def _extract_layout_table(
    page: pdfplumber.page.Page,
    anchor_text: str,
    identity: StandardIdentity,
    spec: TableAuditSpec,
) -> RawGrid:
    page_text = re.sub(r"\s+", " ", anchor_text).casefold()
    anchor = f"table {spec.source_table}".casefold()
    if anchor not in page_text:
        raise ExtractionError(
            f"layout anchor is missing for {spec.semantic_id}; extraction refused"
        )
    matching = []
    for found in page.find_tables():
        raw = found.extract()
        shape = (len(raw), max((len(row) for row in raw), default=0))
        bbox_matches = all(
            abs(float(actual) - expected) <= 1.0
            for actual, expected in zip(found.bbox, spec.expected_bbox, strict=True)
        )
        if shape == (spec.expected_raw_rows, spec.expected_raw_columns) and bbox_matches:
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
    cells = tuple(
        RawGridCell(
            row=row,
            column=column,
            value=token[0],
            qualifier=token[1],
            suffix=token[2],
            source=_source(
                identity,
                page_number=spec.page_number,
                clause=spec.clause,
                table=spec.source_table,
                row=f"grid row {row + 1}",
                column=f"grid column {column + 1}",
            ),
        )
        for row in range(spec.expected_raw_rows)
        for column in range(spec.expected_raw_columns)
        if (token := _numeric_token(raw[row][column])) is not None
    )
    if not cells:
        raise ExtractionError(f"anchored table has no numeric cells for {spec.semantic_id}")
    return RawGrid(
        id=f"raw-{spec.semantic_id}",
        rows=spec.expected_raw_rows,
        columns=spec.expected_raw_columns,
        target_unit=spec.target_unit,
        cells=cells,
        source=table_source,
    )


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
        )
        for spec in recipe.formulas
    )
    mapping_items = tuple(
        ImportReviewItem(
            code="MANUAL_MAPPING_REQUIRED",
            semantic_id=spec.semantic_route,
            kind="mapping",
            source=_source(
                identity,
                page_number=spec.page_number,
                clause=spec.clause,
                table=spec.table,
                figure=spec.figure,
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
            grids = tuple(
                _extract_layout_table(
                    pdf.pages[spec.page_number - 1],
                    anchor_reader.pages[spec.page_number - 1].extract_text() or "",
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
        TypeError,
        ValueError,
    ) as error:
        raise ExtractionError("recognized PDF layout could not be extracted") from error
    return grids, _manual_review_items(identity, recipe)


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
    payload = _synthetic_payload(path)
    if payload is None:
        grids, review_items = _extract_real_layout(path, identity, recipe)
        return (), (), (), review_items, grids
    try:
        tables = tuple(Table.model_validate(item) for item in payload["tables"])
        formulas = tuple(Formula.model_validate(item) for item in payload["formulas"])
        mappings = tuple(
            CompatibilityMapping.model_validate(item).model_copy(
                update={"approved": False}
            )
            for item in payload["mappings"]
        )
    except (TypeError, ValidationError, ValueError) as error:
        raise ExtractionError("extracted rule payload is structurally invalid") from error
    _require_exact_sources((*tables, *formulas, *mappings), identity)
    return tables, formulas, mappings, (), ()


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
    sources = tuple(
        SourceDocument(
            standard=identity.standard,
            edition=identity.edition,
            sha256=identity.sha256,
        )
        for _, identity in sorted(identified, key=lambda pair: pair[1].recipe_id)
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
    )
