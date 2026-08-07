from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
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
    IEC_IMPORTER_VERSION,
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
    EquationAuditSpec,
    FormulaAuditSpec,
    MappingAuditSpec,
    StandardIdentity,
    StandardRecipe,
    TableAuditSpec,
    TableSegmentSpec,
    identify_standard,
)

IMPORTER_VERSION = IEC_IMPORTER_VERSION
_REQUIRED_RECIPES = {"iec60664-1-2020", "iec60664-4-2005", "iec62477-1-2022"}


def _missing_parts_message(loaded: set[str]) -> str:
    missing = sorted(_REQUIRED_RECIPES - loaded)
    required = ", ".join(sorted(_REQUIRED_RECIPES))
    return (
        f"all required standards must be loaded together ({required}); "
        f"missing required part(s): {', '.join(missing)}"
    )

__all__ = [
    "EquationAuditSpec",
    "ExtractedEquation",
    "ExtractionError",
    "FormulaAuditSpec",
    "ImportReviewItem",
    "ImportedRuleDraft",
    "MappingAuditSpec",
    "RawGrid",
    "RawGridCell",
    "RawGridSegment",
    "StandardRecipe",
    "TableAuditSpec",
    "extract_draft",
    "is_recipe_derived",
    "parse_data_cell",
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


class ParsedDataCell(FrozenModel):
    value: Decimal | None = None
    qualifier: str | None = Field(default=None, max_length=8)
    suffix: str | None = Field(default=None, max_length=32)
    footnotes: tuple[str, ...] = ()
    parse_status: Literal[
        "blank",
        "numeric",
        "ambiguous_numeric",
        "non_scalar",
        "range",
    ]


class RawGridSegment(FrozenModel):
    page_number: int = Field(ge=1)
    row_start: int = Field(ge=0)
    row_count: int = Field(ge=1)
    source: SourceReference


class RawGridCell(FrozenModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    raw_text: str = Field(max_length=2_000)
    role: Literal["header", "data", "blank", "note", "footnote"]
    logical_row: int | None = Field(default=None, ge=0)
    logical_column: str | None = None
    value: Decimal | None = None
    qualifier: str | None = Field(default=None, max_length=8)
    suffix: str | None = Field(default=None, max_length=32)
    footnotes: tuple[str, ...] = ()
    parse_status: Literal[
        "blank",
        "text",
        "numeric",
        "ambiguous_numeric",
        "non_scalar",
        "range",
    ]
    source: SourceReference


class RawGrid(FrozenModel):
    id: str
    rows: int = Field(ge=1)
    columns: int = Field(ge=1)
    target_unit: str
    segments: tuple[RawGridSegment, ...] = Field(min_length=1)
    cells: tuple[RawGridCell, ...]
    source: SourceReference

    @model_validator(mode="after")
    def _valid_coordinates(self) -> RawGrid:
        coordinates = tuple((cell.row, cell.column) for cell in self.cells)
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("raw grid cell coordinates must be unique")
        if any(cell.row >= self.rows or cell.column >= self.columns for cell in self.cells):
            raise ValueError("raw grid cell coordinate is outside declared dimensions")
        if (
            tuple(segment.row_start for segment in self.segments)
            != tuple(
                sum(item.row_count for item in self.segments[:index])
                for index in range(len(self.segments))
            )
            or sum(segment.row_count for segment in self.segments) != self.rows
        ):
            raise ValueError("raw grid segments must cover rows once in order")
        if any(
            (
                cell.logical_row is None or cell.logical_column is None
                if cell.role == "data"
                else (
                    (cell.logical_row is None) != (cell.logical_column is None)
                    if cell.role == "blank"
                    else (cell.logical_row is not None or cell.logical_column is not None)
                )
            )
            for cell in self.cells
        ):
            raise ValueError("raw grid logical coordinates do not match cell roles")
        return self


class ExtractedEquation(FrozenModel):
    id: str
    raw_text: str = Field(max_length=4_000)
    rendered: str = Field(max_length=4_000)
    variables: tuple[str, ...]
    literals: tuple[Decimal, ...]
    unit: str
    applicability: str = Field(max_length=1_000)
    parse_status: Literal["parsed", "review_required"]
    source: SourceReference


class ImportedRuleDraft(DraftRulePackage):
    review_items: tuple[ImportReviewItem, ...] = ()
    review_resolutions: tuple[ImportReviewResolution, ...] = ()
    raw_grids: tuple[RawGrid, ...] = ()
    extracted_equations: tuple[ExtractedEquation, ...] = ()
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
    extracted_equations: tuple[ExtractedEquation, ...] = (),
) -> str:
    payload = {
        "tables": [item.model_dump(mode="json") for item in tables],
        "formulas": [item.model_dump(mode="json") for item in formulas],
        "mappings": [item.model_dump(mode="json") for item in mappings],
        "review_items": [item.model_dump(mode="json") for item in review_items],
        "review_resolutions": [item.model_dump(mode="json") for item in review_resolutions],
        "raw_grids": [item.model_dump(mode="json") for item in raw_grids],
        "extracted_equations": [item.model_dump(mode="json") for item in extracted_equations],
        "source_documents": [item.model_dump(mode="json") for item in source_documents],
        "source_identities": [item.model_dump(mode="json") for item in source_identities],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _recipe(identity: StandardIdentity) -> StandardRecipe:
    from insulation_coordination.rules.importer.recipes import RECIPES

    matches = tuple(recipe for recipe in RECIPES if recipe.id == identity.recipe_id)
    if len(matches) != 1:
        raise ExtractionError(f"no unique extraction recipe for {identity.recipe_id}")
    recipe = matches[0]
    offset = dict(recipe.page_number_offsets).get(identity.page_count, 0)
    if offset == 0:
        return recipe

    tables = tuple(
        table.model_copy(
            update={
                "page_number": table.page_number + offset,
                "segments": tuple(
                    segment.model_copy(update={"page_number": segment.page_number + offset})
                    for segment in table.segments
                ),
            }
        )
        for table in recipe.tables
    )
    formulas = tuple(
        formula.model_copy(update={"page_number": formula.page_number + offset})
        for formula in recipe.formulas
    )
    mappings = tuple(
        mapping.model_copy(update={"page_number": mapping.page_number + offset})
        for mapping in recipe.mappings
    )
    return recipe.model_copy(update={"tables": tables, "formulas": formulas, "mappings": mappings})


_NUMBER_TOKEN = r"(?:[0-9]{1,3}(?:[ \u00a0][0-9]{3})+|[0-9]+)(?:[.,][0-9]+)?"
_NUMERIC_CELL = re.compile(rf'^\s*(<=|>=|<|>|≤|≥)?\s*({_NUMBER_TOKEN})\s*(.*?)\s*$')
_RANGE_CELL = re.compile(
    r"^\s*[0-9]+(?:[.,][0-9]+)?\s*(?:to|[-–—])\s*"
    r"[0-9]+(?:[.,][0-9]+)?\s*$",
    re.IGNORECASE,
)
#: SI prefixes this importer understands when a header states a bound with a unit
#: (e.g. "f <= 0,4 MHz") instead of a bare number. Generic across any base unit.
_SI_PREFIX_MULTIPLIERS: dict[str, Decimal] = {
    "": Decimal(1),
    "k": Decimal(1_000),
    "M": Decimal(1_000_000),
    "G": Decimal(1_000_000_000),
}


def _header_bound_in_base_unit(text: str, base_unit: str) -> Decimal | None:
    """The rightmost "<number> <SI-prefixed base_unit>" quantity in free header text.

    A table's own header row sometimes states a data column's applicability as an
    upper bound in prose (for example "f <= 0,4 MHz") rather than as a bare number in
    that column's own header cell. The rightmost match is used because a range like
    "30 kHz < f <= 100 kHz" always states its ceiling last. Trailing characters (a
    footnote marker glued to the unit, a closing parenthesis) are ignored rather than
    required to match, since they carry no numeric meaning.
    """
    pattern = re.compile(rf"({_NUMBER_TOKEN})\s*([kMG]?){re.escape(base_unit)}")
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    value, prefix = matches[-1].groups()
    normalized = re.sub(r"[ \u00a0]", "", value).replace(",", ".")
    return Decimal(normalized) * _SI_PREFIX_MULTIPLIERS[prefix]


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
    normalized = re.sub(r"[ \u00a0]", "", match.group(2)).replace(",", ".")
    return Decimal(normalized), qualifier, suffix


def parse_data_cell(
    value: str | None,
    *,
    allowed_footnotes: tuple[str, ...] = (),
    allowed_qualifiers: tuple[str, ...] = (),
) -> ParsedDataCell:
    raw_text = "" if value is None else value
    if len(raw_text) > 2_000:
        raise ExtractionError("raw table cell exceeds the fidelity size limit")
    if not raw_text.strip():
        return ParsedDataCell(parse_status="blank")
    semantic_qualifier = None
    if "up_to" in allowed_qualifiers and re.match(r"(?i)^\s*up\s+to\s+", raw_text):
        raw_text = re.sub(r"(?i)^\s*up\s+to\s+", "", raw_text, count=1)
        semantic_qualifier = "up_to"
    if "\n" in raw_text and len(tuple(line for line in raw_text.splitlines() if line.strip())) > 1:
        return ParsedDataCell(parse_status="non_scalar")
    if _RANGE_CELL.fullmatch(raw_text):
        return ParsedDataCell(parse_status="range")
    token = _numeric_token(raw_text)
    if token is None:
        return ParsedDataCell(parse_status="non_scalar")
    number, qualifier, suffix = token
    qualifier = semantic_qualifier or qualifier
    normalized_suffix = (suffix or "").strip()
    markers = tuple(re.findall(r"[A-Za-z]+", normalized_suffix))
    footnotes = markers if markers and all(item in allowed_footnotes for item in markers) else ()
    unknown_suffix = bool(normalized_suffix and not footnotes)
    ambiguous = qualifier in {"<=", ">="} or unknown_suffix
    return ParsedDataCell(
        value=number,
        qualifier=qualifier,
        suffix=suffix or None,
        footnotes=footnotes,
        parse_status="ambiguous_numeric" if ambiguous else "numeric",
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

    def normalized(value: str) -> str:
        compact = re.sub(r"\s+", " ", value).strip().casefold()
        return re.sub(r"\s*\.\s*", ".", compact)

    normalized_anchor = normalized(anchor_text)

    def visitor(
        text: str,
        current_matrix: list[float],
        text_matrix: list[float],
        _font: object,
        font_size: float,
    ) -> None:
        normalized_text = normalized(text)
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


def _legacy_segment(spec: TableAuditSpec) -> TableSegmentSpec:
    return TableSegmentSpec(
        id=spec.semantic_id,
        page_number=spec.page_number,
        title_anchor=spec.title_anchor,
        expected_raw_rows=spec.expected_raw_rows,
        expected_raw_columns=spec.expected_raw_columns,
        expected_bbox=spec.expected_bbox,
        bbox_tolerance=spec.bbox_tolerance,
        anchor_max_vertical_gap=spec.anchor_max_vertical_gap,
        anchor_min_x_overlap=spec.anchor_min_x_overlap,
        page_search_radius=spec.page_search_radius,
    )


def _extract_segment(
    page: pdfplumber.page.Page,
    anchor_page: PageObject,
    semantic_id: str,
    segment: TableSegmentSpec,
) -> tuple[list[list[str | None]], pdfplumber.table.Table]:
    anchors = _anchor_boxes(anchor_page, anchor_text=segment.title_anchor)
    if not anchors:
        raise ExtractionError(f"layout anchor is missing for {semantic_id}; extraction refused")
    matching = []
    for found in page.find_tables():
        raw = found.extract()
        shape = (len(raw), max((len(row) for row in raw), default=0))
        bbox_matches = all(
            abs(float(actual) - expected) <= segment.bbox_tolerance
            for actual, expected in zip(found.bbox, segment.expected_bbox, strict=True)
        )
        spatially_bound = any(
            found.bbox[1] >= anchor["bottom"]
            and found.bbox[1] - anchor["bottom"] <= segment.anchor_max_vertical_gap
            and max(
                0.0,
                min(found.bbox[2], anchor["x1"]) - max(found.bbox[0], anchor["x0"]),
            )
            / max(
                1.0,
                min(
                    found.bbox[2] - found.bbox[0],
                    anchor["x1"] - anchor["x0"],
                ),
            )
            >= segment.anchor_min_x_overlap
            for anchor in anchors
        )
        if (
            shape == (segment.expected_raw_rows, segment.expected_raw_columns)
            and bbox_matches
            and spatially_bound
        ):
            matching.append(found)
    if len(matching) != 1:
        raise ExtractionError(
            f"layout dimensions are ambiguous for {semantic_id}; extraction refused"
        )
    return matching[0].extract(), matching[0]


def _extract_segment_in_window(
    pdf: pdfplumber.pdf.PDF,
    anchor_reader: PdfReader,
    semantic_id: str,
    segment: TableSegmentSpec,
) -> tuple[int, list[list[str | None]], pdfplumber.table.Table]:
    """Locate one segment near its declared page, refusing anything but a unique match."""

    candidates = [
        index
        for offset in range(-segment.page_search_radius, segment.page_search_radius + 1)
        if 0 <= (index := segment.page_number - 1 + offset) < len(pdf.pages)
    ]
    if len(candidates) == 1:
        # Only one page is in range (this is always true when radius is 0): there is no
        # ambiguity about *which* page to search, so let the underlying shape/bbox/anchor
        # failure surface with its own specific message instead of being folded into a
        # generic "found on N pages" refusal.
        index = candidates[0]
        raw, table = _extract_segment(
            pdf.pages[index],
            anchor_reader.pages[index],
            semantic_id,
            segment,
        )
        return index + 1, raw, table
    found: list[tuple[int, list[list[str | None]], pdfplumber.table.Table]] = []
    for index in candidates:
        try:
            raw, table = _extract_segment(
                pdf.pages[index],
                anchor_reader.pages[index],
                semantic_id,
                segment,
            )
            found.append((index + 1, raw, table))
        except ExtractionError:
            continue
    if len(found) != 1:
        raise ExtractionError(
            f"table {semantic_id} was found on {len(found)} pages within "
            f"{segment.page_number} plus or minus {segment.page_search_radius}; "
            "extraction refused"
        )
    return found[0]


def _header_cell_text(
    page: pdfplumber.page.Page,
    table: pdfplumber.table.Table,
    *,
    header_row: int,
    reference_row: int,
    column: int,
) -> str:
    """The text physically positioned under one column of a header row.

    Table lattice detection sometimes finds no vertical divider inside a header row
    (a banner header with per-column sub-labels but no ruling between them), so the
    table's own per-cell text for that row merges several columns together instead of
    splitting them. This recovers one column's own text by reusing its known x-range
    from a row where the divider is present -- ``reference_row`` -- intersected with
    the header row's y-range, rather than trusting the table's own cell split for the
    header row.
    """
    column_bbox = table.rows[reference_row].cells[column]
    if column_bbox is None:
        return ""
    header_bbox = table.rows[header_row].bbox
    crop_bbox = (column_bbox[0], header_bbox[1], column_bbox[2], header_bbox[3])
    return page.crop(crop_bbox).extract_text() or ""


def _legacy_data_logical(
    spec: TableAuditSpec,
    raw: list[list[str | None]],
) -> dict[tuple[int, int], tuple[int, int]]:
    if spec.data_strategy == "rectangle":
        if spec.data_row_start is None or spec.data_column_start is None:
            raise ExtractionError("rectangle data contract has no starting coordinate")
        return {
            (spec.data_row_start + row, spec.data_column_start + column): (row, column)
            for row in range(spec.expected_data_rows)
            for column in range(spec.expected_data_columns)
        }
    numeric_coordinates = tuple(
        (row, column)
        for row in range(spec.expected_raw_rows)
        for column in range(spec.expected_raw_columns)
        if parse_data_cell(
            raw[row][column],
            allowed_footnotes=spec.allowed_suffixes,
        ).value
        is not None
    )
    if len(numeric_coordinates) != spec.expected_data_rows * spec.expected_data_columns:
        raise ExtractionError(f"layout data dimensions do not match for {spec.semantic_id}")
    return {
        coordinate: (
            index // spec.expected_data_columns,
            index % spec.expected_data_columns,
        )
        for index, coordinate in enumerate(numeric_coordinates)
    }


def _extract_layout_table(
    pdf: pdfplumber.pdf.PDF,
    anchor_reader: PdfReader,
    identity: StandardIdentity,
    spec: TableAuditSpec,
) -> tuple[RawGrid, tuple[ImportReviewItem, ...]]:
    segment_specs = spec.segments or (_legacy_segment(spec),)
    table_source = _source(
        identity,
        page_number=spec.page_number,
        clause=spec.clause,
        table=spec.source_table,
    )
    cells: list[RawGridCell] = []
    segments: list[RawGridSegment] = []
    row_start = 0
    grid_columns: int | None = None
    for segment in segment_specs:
        resolved_page, raw, table = _extract_segment_in_window(
            pdf,
            anchor_reader,
            spec.semantic_id,
            segment,
        )
        page = pdf.pages[resolved_page - 1]
        source_columns = segment.source_columns or tuple(range(segment.expected_raw_columns))
        if spec.columns and source_columns != tuple(
            column.source_column for column in spec.columns
        ):
            raise ExtractionError(f"column contract is inconsistent for {spec.semantic_id}")
        if grid_columns is None:
            grid_columns = len(source_columns)
        elif grid_columns != len(source_columns):
            raise ExtractionError(f"continuation columns differ for {spec.semantic_id}")
        data_rows = tuple(segment.data_rows)
        data_row_indexes = {row: index for index, row in enumerate(data_rows)}
        legacy_logical = {} if spec.segments else _legacy_data_logical(spec, raw)
        segment_source = _source(
            identity,
            page_number=resolved_page,
            clause=spec.clause,
            table=spec.source_table,
        )
        segments.append(
            RawGridSegment(
                page_number=resolved_page,
                row_start=row_start,
                row_count=segment.expected_raw_rows,
                source=segment_source,
            )
        )
        for physical_row in range(segment.expected_raw_rows):
            for column, source_column in enumerate(source_columns):
                raw_text = raw[physical_row][source_column] or ""
                logical: tuple[int, str] | None = None
                parsed: ParsedDataCell | None = None
                role: Literal["header", "data", "blank", "note", "footnote"]
                if spec.segments:
                    column_spec = spec.columns[column]
                    if physical_row in segment.header_rows:
                        if column_spec.axis_value_source_row == physical_row:
                            parsed = parse_data_cell(
                                raw_text, allowed_footnotes=spec.allowed_suffixes
                            )
                            if parsed.value is None and segment.data_rows:
                                # The table's own cell split for this header row may
                                # merge several columns together (no ruling divides
                                # them there); recover this column's own text by its
                                # x-range and read the bound it states, in whatever
                                # unit the document uses, as this table's axis unit.
                                header_text = _header_cell_text(
                                    page,
                                    table,
                                    header_row=physical_row,
                                    reference_row=segment.data_rows[0],
                                    column=source_column,
                                )
                                bound = _header_bound_in_base_unit(
                                    header_text, spec.column_axis_unit
                                )
                                if bound is not None:
                                    parsed = ParsedDataCell(value=bound, parse_status="numeric")
                                    raw_text = header_text
                            if parsed.value is None:
                                raise ExtractionError(
                                    f"axis header cell is not numeric for {spec.semantic_id} "
                                    f"column {column_spec.semantic_id} row {physical_row}"
                                )
                            role = "header"
                        else:
                            role = "blank" if not raw_text.strip() else "header"
                    elif physical_row in segment.note_rows:
                        role = "blank" if not raw_text.strip() else "note"
                    elif physical_row in segment.footnote_rows:
                        role = "blank" if not raw_text.strip() else "footnote"
                    elif (physical_row, source_column) in segment.context_cells:
                        role = "blank" if not raw_text.strip() else "note"
                    elif physical_row in data_row_indexes and column_spec.role != "context":
                        logical = (
                            segment.logical_row_offset + data_row_indexes[physical_row],
                            column_spec.semantic_id,
                        )
                        if raw_text.strip():
                            role = "data"
                            parsed = parse_data_cell(
                                raw_text,
                                allowed_footnotes=spec.allowed_suffixes,
                                allowed_qualifiers=spec.allowed_qualifiers,
                            )
                        else:
                            role = "blank"
                    elif physical_row in data_row_indexes:
                        role = "blank" if not raw_text.strip() else "note"
                    else:
                        role = "blank" if not raw_text.strip() else "note"
                else:
                    legacy = legacy_logical.get((physical_row, source_column))
                    if legacy is None:
                        role = "blank" if not raw_text.strip() else "header"
                    else:
                        logical = (legacy[0], f"column-{legacy[1] + 1}")
                        role = "data"
                        parsed = parse_data_cell(
                            raw_text,
                            allowed_footnotes=spec.allowed_suffixes,
                            allowed_qualifiers=spec.allowed_qualifiers,
                        )
                parse_status = (
                    parsed.parse_status
                    if parsed is not None
                    else ("blank" if not raw_text.strip() else "text")
                )
                cells.append(
                    RawGridCell(
                        row=row_start + physical_row,
                        column=column,
                        raw_text=raw_text,
                        role=role,
                        logical_row=None if logical is None else logical[0],
                        logical_column=None if logical is None else logical[1],
                        value=None if parsed is None else parsed.value,
                        qualifier=None if parsed is None else parsed.qualifier,
                        suffix=None if parsed is None else parsed.suffix,
                        footnotes=() if parsed is None else parsed.footnotes,
                        parse_status=parse_status,
                        source=_source(
                            identity,
                            page_number=resolved_page,
                            clause=spec.clause,
                            table=spec.source_table,
                            row=f"grid row {physical_row + 1}",
                            column=f"grid column {source_column + 1}",
                        ),
                    )
                )
        row_start += segment.expected_raw_rows

    if grid_columns is None or (row_start, grid_columns) != (
        spec.expected_raw_rows,
        spec.expected_raw_columns,
    ):
        raise ExtractionError(f"logical grid dimensions differ for {spec.semantic_id}")
    if spec.segments:
        logical_rows = {cell.logical_row for cell in cells if cell.logical_row is not None}
        logical_columns = {
            column.semantic_id for column in spec.columns if column.role != "context"
        }
        if (
            len(logical_rows) != spec.expected_data_rows
            or len(logical_columns) != spec.expected_data_columns
        ):
            raise ExtractionError(f"semantic data dimensions differ for {spec.semantic_id}")
    grid = RawGrid(
        id=f"raw-{spec.semantic_id}",
        rows=row_start,
        columns=grid_columns,
        target_unit=spec.target_unit,
        segments=tuple(segments),
        cells=tuple(cells),
        source=table_source,
    )
    reviews = tuple(
        ImportReviewItem(
            code="MANUAL_RAW_CELL_REVIEW_REQUIRED",
            semantic_id=f"{grid.id}:{cell.row}:{cell.column}",
            kind="raw_cell",
            source=cell.source,
            expected_contract=f"raw-cell:{spec.semantic_id}:numeric",
        )
        for cell in cells
        if cell.role == "data" and cell.parse_status != "numeric"
    )
    return grid, reviews


def is_recipe_derived(item: ImportReviewItem) -> bool:
    """True when the item's content comes from this app's recipe, not from a PDF.

    Semantic mappings and table-selection formulas are constants declared in
    ``recipes/``; the PDF contributes nothing to them, so a maintainer clicking
    through them proves nothing about the extraction.  The importer resolves
    them itself and names the recipe contract in the resolution notes.
    """
    from insulation_coordination.rules.importer.recipes import RECIPES

    if item.kind == "mapping":
        return True
    if item.kind != "formula":
        return False
    return any(
        spec.semantic_id == item.semantic_id and not spec.extract_from_pdf
        for recipe in RECIPES
        for spec in recipe.formulas
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
                    pdf,
                    anchor_reader,
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


def _decimal_literal(value: str) -> Decimal:
    return Decimal(value.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def _extract_equations(
    path: Path,
    identity: StandardIdentity,
    recipe: StandardRecipe,
) -> tuple[ExtractedEquation, ...]:
    specs = tuple(spec for spec in recipe.formulas if spec.extract_from_pdf)
    if not specs:
        return ()
    equations: list[ExtractedEquation] = []
    try:
        with pdfplumber.open(path) as pdf:
            for spec in specs:
                page = pdf.pages[spec.page_number - 1]
                page_text = page.extract_text() or ""
                cropped_text = (
                    page.crop(spec.expected_bbox).extract_text() or ""
                    if spec.expected_bbox is not None
                    else page_text
                )
                literals: tuple[Decimal, ...]
                if spec.expression_shape == "critical_frequency_inverse_clearance":
                    match = re.search(r"(?<!\d)(0[,.]2)(?!\d)", cropped_text)
                    if match is None or "crit" not in cropped_text or "(1)" not in cropped_text:
                        raise ExtractionError("IEC 60664-4 Equation (1) could not be verified")
                    literals = (_decimal_literal(match.group(1)),)
                    raw_text = cropped_text
                    rendered = f"f_crit = {literals[0]} / (d / mm) MHz"
                elif spec.expression_shape == "linear_frequency_factor":
                    base = re.search(r"(?<!\d)(100)\s*%", cropped_text)
                    factor = re.search(r"(?<!\d)(25)\s*%", cropped_text)
                    if base is None or factor is None or "(2)" not in cropped_text:
                        raise ExtractionError("IEC 60664-4 Equation (2) could not be verified")
                    literals = (
                        _decimal_literal(base.group(1)),
                        _decimal_literal(factor.group(1)),
                    )
                    raw_text = cropped_text
                    rendered = "100% + ((f - f_crit) / (f_min - f_crit)) * 25%"
                elif spec.expression_shape == "minimum_frequency_statement":
                    match = re.search(
                        r"(?im)^.*fmin.*accepted\s+as\s+([0-9]+(?:[,.][0-9]+)?)\s*MHz.*$",
                        page_text,
                    )
                    if match is None:
                        raise ExtractionError("IEC 60664-4 minimum frequency could not be verified")
                    literals = (_decimal_literal(match.group(1)),)
                    raw_text = match.group(0).strip()
                    rendered = f"f_min = {literals[0]} MHz"
                elif spec.expression_shape == "radius_to_clearance_criterion":
                    match = re.search(
                        r"(?im)^.*radius of curvature.*equal or greater than\s+"
                        r"([0-9]+(?:[,.][0-9]+)?)\s*%.*$",
                        page_text,
                    )
                    if match is None:
                        raise ExtractionError("IEC 60664-4 radius criterion could not be verified")
                    literals = (_decimal_literal(match.group(1)),)
                    raw_text = match.group(0).strip()
                    rendered = f"radius / clearance >= {literals[0]}%"
                else:
                    raise ExtractionError(
                        f"unsupported equation extraction contract {spec.expression_shape}"
                    )
                equations.append(
                    ExtractedEquation(
                        id=spec.semantic_id,
                        raw_text=raw_text,
                        rendered=rendered,
                        variables=spec.variables,
                        literals=literals,
                        unit=spec.unit,
                        applicability=spec.applicability,
                        parse_status="parsed",
                        source=_source(
                            identity,
                            page_number=spec.page_number,
                            clause=spec.clause,
                            table=spec.table,
                            figure=spec.figure,
                        ),
                    )
                )
    except ExtractionError:
        raise
    except (OSError, IndexError, PDFException, PSException, TypeError, ValueError) as error:
        raise ExtractionError("recognized PDF equations could not be extracted") from error
    return tuple(equations)


def _extract_one(
    path: Path, identity: StandardIdentity
) -> tuple[
    tuple[Table, ...],
    tuple[Formula, ...],
    tuple[CompatibilityMapping, ...],
    tuple[ImportReviewItem, ...],
    tuple[RawGrid, ...],
    tuple[ExtractedEquation, ...],
]:
    recipe = _recipe(identity)
    grids, review_items = _extract_real_layout(path, identity, recipe)
    equations = _extract_equations(path, identity, recipe)
    return (), (), (), review_items, grids, equations


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


def extract_draft(
    paths: tuple[Path, ...],
    passwords: Mapping[Path, str] | None = None,
) -> ImportedRuleDraft:
    """Extract recognized sources into a deliberately unusable immutable draft."""

    if not paths:
        raise ExtractionError(_missing_parts_message(set()))
    identified = tuple(
        (path, identify_standard(path, password=(passwords or {}).get(path))) for path in paths
    )
    recipe_ids = tuple(identity.recipe_id for _, identity in identified)
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ExtractionError("duplicate supported IEC part")
    if set(recipe_ids) != _REQUIRED_RECIPES:
        loaded = {identity.recipe_id for _, identity in identified}
        raise ExtractionError(_missing_parts_message(loaded))

    tables: tuple[Table, ...] = ()
    formulas: tuple[Formula, ...] = ()
    mappings: tuple[CompatibilityMapping, ...] = ()
    review_items: tuple[ImportReviewItem, ...] = ()
    raw_grids: tuple[RawGrid, ...] = ()
    extracted_equations: tuple[ExtractedEquation, ...] = ()
    for path, identity in sorted(identified, key=lambda pair: pair[1].recipe_id):
        (
            extracted_tables,
            extracted_formulas,
            extracted_mappings,
            extracted_reviews,
            extracted_grids,
            extracted_source_equations,
        ) = _extract_one(path, identity)
        tables += extracted_tables
        formulas += extracted_formulas
        mappings += extracted_mappings
        review_items += extracted_reviews
        raw_grids += extracted_grids
        extracted_equations += extracted_source_equations
    _require_unique_ids(tables, formulas, mappings)

    recorded_at = datetime.now(UTC)
    review_resolutions = tuple(
        ImportReviewResolution(
            review_item_sha256=item.sha256,
            actor=f"icc-importer/{IMPORTER_VERSION}",
            recorded_at=recorded_at,
            notes=f"recipe-defined, no PDF content: {item.expected_contract}",
        )
        for item in review_items
        if is_recipe_derived(item)
    )
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
            *(f"equation:{equation.id}" for equation in extracted_equations),
            *(f"review:{item.code}:{item.semantic_id}" for item in review_items),
            f"content:{_content_digest(tables, formulas, mappings, review_items, raw_grids, extracted_equations=extracted_equations)}",
        )
    )
    ordered_identities = tuple(
        identity for _, identity in sorted(identified, key=lambda pair: pair[1].recipe_id)
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
        review_resolutions,
        extracted_equations=extracted_equations,
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
        review_resolutions=review_resolutions,
        raw_grids=raw_grids,
        extracted_equations=extracted_equations,
        source_identities=ordered_identities,
    )
