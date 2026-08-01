from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pdfminer.pdfdocument import PDFSyntaxError
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from insulation_coordination.domain.rules import (
    CompatibilityMapping,
    DraftRulePackage,
    Formula,
    LinearInterpolate,
    Literal,
    Parameter,
    ParameterSet,
    SourceReference,
    Table,
    TableAxis,
    TableCell,
    Variable,
)
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    approve_draft,
    is_fully_resolved,
    record_correction,
)
from insulation_coordination.rules.importer.extract import (
    ExtractedEquation,
    ExtractionError,
    ImportedRuleDraft,
    RawGridSegment,
    extract_draft,
    parse_data_cell,
)
from insulation_coordination.rules.importer.identify import (
    AmbiguousStandardError,
    FormulaAuditSpec,
    MappingAuditSpec,
    StandardRecipe,
    TableAuditSpec,
    UnsupportedStandardError,
    identify_standard,
)
from insulation_coordination.rules.importer.review import (
    accept_raw_grid,
    build_reviewed_draft,
    confirm_placeholder_formula,
    missing_required_content,
    placeholder_formula_ids,
    required_content_report,
    unresolved_raw_review_items,
)

_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_TABLE_BBOX = (72.0, 192.0, 252.0, 312.0)
_CELLS = (
    ("axis", "10", "20"),
    ("1", "1.1", "1.2"),
    ("2", "2.1", "2.2"),
)


def _pdf_string(value: str) -> bytes:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1")


def _text_command(x: float, y: float, value: str) -> bytes:
    return f"BT /F1 9 Tf {x:.1f} {y:.1f} Td (".encode() + _pdf_string(value) + b") Tj ET"


def _table_commands(
    bbox: tuple[float, float, float, float],
    cells: tuple[tuple[str, ...], ...],
) -> list[bytes]:
    x0, top, x1, bottom = bbox
    rows = len(cells)
    columns = len(cells[0])
    pdf_top = _PAGE_HEIGHT - top
    pdf_bottom = _PAGE_HEIGHT - bottom
    row_height = (pdf_top - pdf_bottom) / rows
    column_width = (x1 - x0) / columns
    commands = [b"0.7 w"]
    for column in range(columns + 1):
        x = x0 + column * column_width
        commands.append(f"{x:.1f} {pdf_bottom:.1f} m {x:.1f} {pdf_top:.1f} l S".encode())
    for row in range(rows + 1):
        y = pdf_bottom + row * row_height
        commands.append(f"{x0:.1f} {y:.1f} m {x1:.1f} {y:.1f} l S".encode())
    for row, values in enumerate(cells):
        for column, value in enumerate(values):
            x = x0 + column * column_width + 5
            y = pdf_top - (row + 1) * row_height + row_height / 2 - 3
            commands.append(_text_command(x, y, value))
    return commands


def create_geometry_pdf(
    path: Path,
    *,
    standard: str,
    edition: str,
    edition_anchor: str,
    topic_anchor: str,
    table_anchor: str,
    cells: tuple[tuple[str, ...], ...] = _CELLS,
    metadata: dict[str, str] | None = None,
    second_table: bool = False,
) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    commands = [
        _text_command(72, 750, standard),
        _text_command(72, 734, edition_anchor),
        _text_command(72, 718, topic_anchor),
        _text_command(72, 616, table_anchor),
        *_table_commands(_TABLE_BBOX, cells),
    ]
    if second_table:
        second_bbox = (300.0, 192.0, 480.0, 312.0)
        commands.extend(
            (
                _text_command(300, 616, table_anchor),
                *_table_commands(second_bbox, cells),
            )
        )
    stream = DecodedStreamObject()
    stream.set_data(b"\n".join(commands))
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata(
        {
            "/Title": f"{standard}:{edition} synthetic geometry fixture",
            "/ICC-Synthetic": "true",
            **(metadata or {}),
        }
    )
    with path.open("wb") as target:
        writer.write(target)


def _test_recipes() -> tuple[StandardRecipe, StandardRecipe]:
    def recipe(
        *,
        recipe_id: str,
        standard: str,
        edition: str,
        edition_anchor: str,
        topic_anchor: str,
        table_id: str,
        table_name: str,
        formula_id: str,
        mapping_id: str,
        route: str,
    ) -> StandardRecipe:
        return StandardRecipe(
            id=recipe_id,
            standard=standard,
            edition=edition,
            expected_page_count=1,
            metadata_identity_fields=("/Title", "/Subject", "/Keywords"),
            metadata_identity_anchors=(standard, edition),
            identity_anchors=(standard, edition_anchor, topic_anchor),
            tables=(
                TableAuditSpec(
                    semantic_id=table_id,
                    source_table=table_name,
                    title_anchor=f"Table {table_name}",
                    page_number=1,
                    clause="SYNTHETIC",
                    target_unit="mm",
                    expected_raw_rows=3,
                    expected_raw_columns=3,
                    expected_bbox=_TABLE_BBOX,
                    bbox_tolerance=1.0,
                    anchor_max_vertical_gap=24.0,
                    anchor_min_x_overlap=0.5,
                    data_strategy="rectangle",
                    data_row_start=1,
                    data_column_start=1,
                    expected_data_rows=2,
                    expected_data_columns=2,
                    row_axis_id="stress",
                    row_axis_unit="V",
                    column_axis_id="branch",
                    column_axis_unit="1",
                    assertions=(
                        "complete_grid",
                        "strictly_increasing_axes",
                        "raw_value_correspondence",
                    ),
                ),
            ),
            formulas=(
                FormulaAuditSpec(
                    semantic_id=formula_id,
                    unit="mm",
                    variables=("stress",),
                    expression_shape=(f"linear_interpolate:{table_id}(variable:stress,literal)"),
                    page_number=1,
                    clause="SYNTHETIC",
                    table=table_name,
                ),
            ),
            mappings=(
                MappingAuditSpec(
                    id=mapping_id,
                    semantic_route=route,
                    target_rule_id=formula_id,
                    family="synthetic",
                    page_number=1,
                    clause="SYNTHETIC",
                    table=table_name,
                ),
            ),
        )

    return (
        recipe(
            recipe_id="iec60664-1-2020",
            standard="IEC 60664-1",
            edition="2020",
            edition_anchor="Edition 3.0 2020-05",
            topic_anchor="synthetic low-voltage geometry",
            table_id="synthetic-part1-table",
            table_name="S1",
            formula_id="synthetic-part1-formula",
            mapping_id="synthetic-part1-mapping",
            route="synthetic:part1",
        ),
        recipe(
            recipe_id="iec60664-4-2005",
            standard="IEC 60664-4",
            edition="2005",
            edition_anchor="first edition 2005",
            topic_anchor="synthetic high-frequency geometry",
            table_id="synthetic-part4-table",
            table_name="S4",
            formula_id="synthetic-part4-formula",
            mapping_id="synthetic-part4-mapping",
            route="synthetic:part4",
        ),
    )


@pytest.fixture(autouse=True)
def injected_recipes(monkeypatch: pytest.MonkeyPatch) -> tuple[StandardRecipe, ...]:
    recipes = _test_recipes()
    monkeypatch.setattr(recipe_registry, "RECIPES", recipes)
    return recipes


@pytest.fixture
def supported_pdfs(tmp_path: Path) -> tuple[Path, Path]:
    part1 = tmp_path / "part1.pdf"
    part4 = tmp_path / "part4.pdf"
    create_geometry_pdf(
        part1,
        standard="IEC 60664-1",
        edition="2020",
        edition_anchor="Edition 3.0 2020-05",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
    )
    create_geometry_pdf(
        part4,
        standard="IEC 60664-4",
        edition="2005",
        edition_anchor="first edition 2005",
        topic_anchor="synthetic high-frequency geometry",
        table_anchor="Table S4",
    )
    return part1, part4


def _source_for(recipe: StandardRecipe) -> SourceReference:
    spec = recipe.tables[0]
    return SourceReference(
        standard=recipe.standard,
        edition=recipe.edition,
        clause=spec.clause,
        table=spec.source_table,
        note=f"PDF page {spec.page_number}",
    )


def _reviewed_content(
    draft: ImportedRuleDraft,
    recipes: tuple[StandardRecipe, ...],
) -> tuple[
    tuple[Table, ...],
    tuple[Formula, ...],
    tuple[CompatibilityMapping, ...],
]:
    grids = {grid.id: grid for grid in draft.raw_grids}
    tables: list[Table] = []
    formulas: list[Formula] = []
    mappings: list[CompatibilityMapping] = []
    for recipe in recipes:
        table_spec = recipe.tables[0]
        formula_spec = recipe.formulas[0]
        mapping_spec = recipe.mappings[0]
        grid = grids[f"raw-{table_spec.semantic_id}"]
        raw_cells = {(cell.row, cell.column): cell for cell in grid.cells}
        source = _source_for(recipe)
        table = Table(
            id=table_spec.semantic_id,
            unit=table_spec.target_unit,
            row_axis=TableAxis(
                id=table_spec.row_axis_id,
                unit=table_spec.row_axis_unit,
                values=(Decimal(1), Decimal(2)),
                labels=("row-1", "row-2"),
            ),
            column_axis=TableAxis(
                id=table_spec.column_axis_id,
                unit=table_spec.column_axis_unit,
                values=(Decimal(10), Decimal(20)),
                labels=("column-10", "column-20"),
            ),
            cells=tuple(
                TableCell(
                    row=row,
                    column=column,
                    value=raw_cells[(row + 1, column + 1)].value,
                    unit=table_spec.target_unit,
                    source=raw_cells[(row + 1, column + 1)].source,
                )
                for row in range(2)
                for column in range(2)
            ),
            interpolation="linear",
            source=source,
        )
        formula = Formula(
            id=formula_spec.semantic_id,
            expression=LinearInterpolate(
                table_id=table.id,
                x=Variable(name=table_spec.row_axis_id),
                column=Literal(value=Decimal(10)),
            ),
            unit=formula_spec.unit,
            parameter_sets=(
                ParameterSet(
                    id="reviewed",
                    parameters=(Parameter(name=table_spec.row_axis_id, unit="V"),),
                    source=source,
                ),
            ),
            source=source,
        )
        mapping = CompatibilityMapping(
            id=mapping_spec.id,
            source_rule_id=mapping_spec.semantic_route,
            target_rule_id=mapping_spec.target_rule_id,
            approved=False,
            source=source,
        )
        tables.append(table)
        formulas.append(formula)
        mappings.append(mapping)
    return tuple(tables), tuple(formulas), tuple(mappings)


def _review_all(
    draft: ImportedRuleDraft,
    recipes: tuple[StandardRecipe, ...],
) -> ImportedRuleDraft:
    tables, formulas, mappings = _reviewed_content(draft, recipes)
    changed = draft.model_copy(
        update={"tables": tables, "formulas": formulas, "mappings": mappings}
    )
    return record_correction(
        draft,
        changed,
        actor="Synthetic Reviewer",
        notes="Reviewed generated geometry and semantic contracts.",
        resolve=draft.review_items,
    )


def test_identifies_supported_document_from_recipe_specific_evidence(
    supported_pdfs: tuple[Path, Path],
) -> None:
    identity = identify_standard(supported_pdfs[0])

    assert identity.standard == "IEC 60664-1"
    assert identity.edition == "2020"
    assert identity.page_count == 1
    assert len(identity.sha256) == 64


def test_unknown_document_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unknown.pdf"
    create_geometry_pdf(
        path,
        standard="UNKNOWN",
        edition="1",
        edition_anchor="unknown edition",
        topic_anchor="unrelated",
        table_anchor="Table X",
    )

    with pytest.raises(UnsupportedStandardError):
        identify_standard(path)


def test_generic_metadata_cannot_replace_recipe_specific_identity(tmp_path: Path) -> None:
    path = tmp_path / "generic-metadata.pdf"
    create_geometry_pdf(
        path,
        standard="IEC 60664-1",
        edition="2020",
        edition_anchor="Edition 3.0 2020-05",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
        metadata={
            "/Title": "Generic document",
            "/CreationDate": "D:20260731",
            "/Producer": "Generic producer",
        },
    )
    writer = PdfWriter(clone_from=path)
    writer.add_blank_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    with path.open("wb") as target:
        writer.write(target)

    with pytest.raises(UnsupportedStandardError):
        identify_standard(path)


def test_contradictory_metadata_and_body_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "contradictory.pdf"
    create_geometry_pdf(
        path,
        standard="IEC 60664-1",
        edition="2020",
        edition_anchor="Edition 3.0 2020-05",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
        metadata={"/Subject": "IEC 60664-4:2005"},
    )

    with pytest.raises(UnsupportedStandardError):
        identify_standard(path)


def test_document_matching_two_recipes_is_rejected_as_ambiguous(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.pdf"
    create_geometry_pdf(
        path,
        standard="IEC 60664-1 IEC 60664-4",
        edition="2020 2005",
        edition_anchor="Edition 3.0 2020-05 first edition 2005",
        topic_anchor=("synthetic low-voltage geometry synthetic high-frequency geometry"),
        table_anchor="Table S1",
    )

    with pytest.raises(AmbiguousStandardError):
        identify_standard(path)


def test_metadata_marker_cannot_embed_or_auto_approve_rule_content(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)

    assert draft.tables == ()
    assert draft.formulas == ()
    assert draft.mappings == ()
    assert draft.review_items
    with pytest.raises(ApprovalError, match="manual review"):
        approve_draft(draft, approver="Reviewer", notes="No bypass")


def test_real_geometry_extracts_every_raw_cell_and_pending_contract(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)

    assert len(draft.raw_grids) == 2
    assert all((grid.rows, grid.columns) == (3, 3) for grid in draft.raw_grids)
    assert all(len(grid.cells) == 9 for grid in draft.raw_grids)
    assert all(
        len({(cell.row, cell.column) for cell in grid.cells}) == 9 for grid in draft.raw_grids
    )
    assert all(cell.raw_text is not None for grid in draft.raw_grids for cell in grid.cells)
    assert {item.kind for item in draft.review_items} == {
        "table",
        "formula",
        "mapping",
    }
    assert all(item.expected_contract for item in draft.review_items)


def test_data_cell_parser_normalizes_grouped_thousands_and_footnotes() -> None:
    parsed = parse_data_cell("1 000 d", allowed_footnotes=("d",))

    assert parsed.value == Decimal(1000)
    assert parsed.footnotes == ("d",)
    assert parsed.parse_status == "numeric"


def test_data_cell_parser_separates_multiple_footnote_markers() -> None:
    parsed = parse_data_cell("0,6 a) b)", allowed_footnotes=("a", "b"))

    assert parsed.value == Decimal("0.6")
    assert parsed.footnotes == ("a", "b")
    assert parsed.parse_status == "numeric"


@pytest.mark.parametrize(
    ("raw_text", "status"),
    (
        ("110\n120\n127", "non_scalar"),
        ("30 to 60", "range"),
    ),
)
def test_data_cell_parser_does_not_collapse_non_scalar_values(
    raw_text: str,
    status: str,
) -> None:
    parsed = parse_data_cell(raw_text)

    assert parsed.value is None
    assert parsed.parse_status == status


def test_extraction_assigns_context_roles_and_one_page_segment(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    grid = draft.raw_grids[0]
    header_number = next(cell for cell in grid.cells if (cell.row, cell.column) == (0, 1))

    assert grid.segments == (
        RawGridSegment(
            page_number=1,
            row_start=0,
            row_count=3,
            source=grid.source,
        ),
    )
    assert header_number.role == "header"
    assert header_number.value is None
    assert header_number.logical_row is None
    assert header_number.logical_column is None
    assert draft.extracted_equations == ()


def test_correction_cannot_rewrite_extracted_equation_text_or_source(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    equation = ExtractedEquation(
        id="synthetic-equation",
        raw_text="f = 1 / d",
        rendered="f = 1 / d",
        variables=("f", "d"),
        literals=(Decimal(1),),
        unit="Hz",
        applicability="synthetic",
        parse_status="parsed",
        source=SourceReference(
            standard="SYNTHETIC",
            edition="1",
            clause="4.2",
            figure="Equation (1)",
        ),
    )
    original = draft.model_copy(update={"extracted_equations": (equation,)})
    rewritten = original.model_copy(
        update={
            "extracted_equations": (
                equation.model_copy(update={"raw_text": "rewritten"}),
            )
        }
    )

    with pytest.raises(ApprovalError, match="equation text or source"):
        record_correction(
            original,
            rewritten,
            actor="Maintainer",
            notes="Must not rewrite source",
        )


@pytest.mark.parametrize("field", ("role", "logical_row", "logical_column"))
def test_correction_cannot_rewrite_raw_cell_semantics(
    supported_pdfs: tuple[Path, Path],
    field: str,
) -> None:
    draft = extract_draft(supported_pdfs)
    grid = draft.raw_grids[0]
    cell_index = 0 if field == "role" else next(
        index for index, item in enumerate(grid.cells) if item.role == "data"
    )
    cell = grid.cells[cell_index]
    updates = {
        "role": "note",
        "logical_row": 99,
        "logical_column": "rewritten",
    }
    changed_cell = cell.model_copy(update={field: updates[field]})
    changed_grid = grid.model_copy(
        update={
            "cells": tuple(
                changed_cell if index == cell_index else item
                for index, item in enumerate(grid.cells)
            )
        }
    )
    changed = draft.model_copy(update={"raw_grids": (changed_grid, *draft.raw_grids[1:])})

    with pytest.raises(ApprovalError, match="raw text or source"):
        record_correction(
            draft,
            changed,
            actor="Maintainer",
            notes="Must not rewrite semantics",
        )


def test_correction_cannot_rewrite_raw_grid_segments(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    grid = draft.raw_grids[0]
    segment = grid.segments[0].model_copy(update={"page_number": 2})
    changed_grid = grid.model_copy(update={"segments": (segment,)})
    changed = draft.model_copy(update={"raw_grids": (changed_grid, *draft.raw_grids[1:])})

    with pytest.raises(ApprovalError, match="raw grid structure"):
        record_correction(
            draft,
            changed,
            actor="Maintainer",
            notes="Must not rewrite segments",
        )


def _compound_draft(tmp_path: Path) -> ImportedRuleDraft:
    part1 = tmp_path / "part1.pdf"
    part4 = tmp_path / "part4.pdf"
    compound_cells = (
        ("axis", "10", "20"),
        ("1", "<= 1.2zz", "1.3"),
        ("2", "2.1", "2.2"),
    )
    create_geometry_pdf(
        part1,
        standard="IEC 60664-1",
        edition="2020",
        edition_anchor="Edition 3.0 2020-05",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
        cells=compound_cells,
    )
    create_geometry_pdf(
        part4,
        standard="IEC 60664-4",
        edition="2005",
        edition_anchor="first edition 2005",
        topic_anchor="synthetic high-frequency geometry",
        table_anchor="Table S4",
    )

    return extract_draft((part1, part4))


def test_unknown_compound_numeric_token_is_preserved_and_flagged(
    tmp_path: Path,
) -> None:
    draft = _compound_draft(tmp_path)

    cell = next(
        cell
        for grid in draft.raw_grids
        if grid.id == "raw-synthetic-part1-table"
        for cell in grid.cells
        if (cell.row, cell.column) == (1, 1)
    )
    assert cell.raw_text == "<= 1.2zz"
    assert cell.value == Decimal("1.2")
    assert cell.qualifier == "<="
    assert cell.suffix == "zz"
    assert cell.parse_status == "ambiguous_numeric"
    assert any(
        item.code == "MANUAL_RAW_CELL_REVIEW_REQUIRED"
        and item.semantic_id == "raw-synthetic-part1-table:1:1"
        for item in draft.review_items
    )


def test_accept_raw_grid_resolves_only_selected_grid_and_preserves_raw_text(
    tmp_path: Path,
) -> None:
    draft = _compound_draft(tmp_path)
    pending = unresolved_raw_review_items(draft)
    assert tuple(item.semantic_id for item in pending) == ("raw-synthetic-part1-table:1:1",)
    original = next(
        cell
        for grid in draft.raw_grids
        if grid.id == "raw-synthetic-part1-table"
        for cell in grid.cells
        if (cell.row, cell.column) == (1, 1)
    )

    accepted = accept_raw_grid(
        draft,
        grid_id="raw-synthetic-part1-table",
        corrections={},
        actor="Maintainer",
        notes="Compared against PDF",
    )

    reviewed = next(
        cell
        for grid in accepted.raw_grids
        if grid.id == "raw-synthetic-part1-table"
        for cell in grid.cells
        if (cell.row, cell.column) == (1, 1)
    )
    assert reviewed.raw_text == original.raw_text
    assert reviewed.source == original.source
    assert reviewed.value == Decimal("1.2")
    assert reviewed.parse_status == "numeric"
    assert reviewed.qualifier is None
    assert reviewed.suffix is None
    assert unresolved_raw_review_items(accepted) == ()
    assert {resolution.review_item_sha256 for resolution in accepted.review_resolutions} == {
        pending[0].sha256
    }


def test_accept_raw_grid_applies_finite_decimal_correction(tmp_path: Path) -> None:
    draft = _compound_draft(tmp_path)

    accepted = accept_raw_grid(
        draft,
        grid_id="raw-synthetic-part1-table",
        corrections={(1, 1): Decimal("1.25")},
        actor="Maintainer",
        notes="Corrected from PDF",
    )

    reviewed = next(
        cell
        for grid in accepted.raw_grids
        if grid.id == "raw-synthetic-part1-table"
        for cell in grid.cells
        if (cell.row, cell.column) == (1, 1)
    )
    assert reviewed.value == Decimal("1.25")
    assert reviewed.raw_text == "<= 1.2zz"


@pytest.mark.parametrize(
    ("grid_id", "corrections", "message"),
    (
        ("missing-grid", {}, "unknown raw grid"),
        (
            "raw-synthetic-part1-table",
            {(9, 9): Decimal(1)},
            "not flagged",
        ),
        (
            "raw-synthetic-part1-table",
            {(1, 1): Decimal("NaN")},
            "finite",
        ),
    ),
)
def test_accept_raw_grid_rejects_invalid_request(
    tmp_path: Path,
    grid_id: str,
    corrections: dict[tuple[int, int], Decimal],
    message: str,
) -> None:
    draft = _compound_draft(tmp_path)

    with pytest.raises(ValueError, match=message):
        accept_raw_grid(
            draft,
            grid_id=grid_id,
            corrections=corrections,
            actor="Maintainer",
            notes="Compared against PDF",
        )


def test_accept_raw_grid_rejects_already_resolved_table(tmp_path: Path) -> None:
    draft = _compound_draft(tmp_path)
    accepted = accept_raw_grid(
        draft,
        grid_id="raw-synthetic-part1-table",
        corrections={},
        actor="Maintainer",
        notes="Compared against PDF",
    )

    with pytest.raises(ValueError, match="no unresolved raw cells"):
        accept_raw_grid(
            accepted,
            grid_id="raw-synthetic-part1-table",
            corrections={},
            actor="Maintainer",
            notes="Compared again",
        )


def test_two_equally_valid_anchor_table_regions_are_rejected(
    tmp_path: Path,
    injected_recipes: tuple[StandardRecipe, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    part1 = tmp_path / "part1.pdf"
    part4 = tmp_path / "part4.pdf"
    create_geometry_pdf(
        part1,
        standard="IEC 60664-1",
        edition="2020",
        edition_anchor="Edition 3.0 2020-05",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
        second_table=True,
    )
    create_geometry_pdf(
        part4,
        standard="IEC 60664-4",
        edition="2005",
        edition_anchor="first edition 2005",
        topic_anchor="synthetic high-frequency geometry",
        table_anchor="Table S4",
    )
    part1_recipe = injected_recipes[0]
    spec = part1_recipe.tables[0]
    ambiguous_spec = spec.model_copy(
        update={
            "expected_bbox": (186.0, 192.0, 366.0, 312.0),
            "bbox_tolerance": 120.0,
        }
    )
    monkeypatch.setattr(
        recipe_registry,
        "RECIPES",
        (
            part1_recipe.model_copy(update={"tables": (ambiguous_spec,)}),
            injected_recipes[1],
        ),
    )

    with pytest.raises(ExtractionError, match="ambiguous"):
        extract_draft((part1, part4))


def test_missing_or_duplicate_supported_part_is_rejected(
    supported_pdfs: tuple[Path, Path],
) -> None:
    part1, part4 = supported_pdfs

    with pytest.raises(ExtractionError, match="must be loaded together"):
        extract_draft((part1,))
    with pytest.raises(ExtractionError, match="duplicate"):
        extract_draft((part1, part1, part4))


def test_review_inventory_and_locators_are_immutable(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    item = draft.review_items[0]
    rewritten = item.model_copy(
        update={"source": item.source.model_copy(update={"note": "rewritten locator"})}
    )
    changed = draft.model_copy(update={"review_items": (rewritten, *draft.review_items[1:])})

    with pytest.raises(ApprovalError, match="review"):
        record_correction(
            draft,
            changed,
            actor="Reviewer",
            notes="Cannot rewrite the locator",
            resolve=(rewritten,),
        )
    with pytest.raises(ApprovalError, match="review"):
        record_correction(
            draft,
            draft.model_copy(update={"review_items": draft.review_items[1:]}),
            actor="Reviewer",
            notes="Cannot delete inventory",
            resolve=(item,),
        )


def test_import_review_cannot_be_erased_by_plain_draft_conversion(
    supported_pdfs: tuple[Path, Path],
) -> None:
    imported = extract_draft(supported_pdfs)
    plain = DraftRulePackage(
        manifest=imported.manifest,
        tables=imported.tables,
        formulas=imported.formulas,
        mappings=imported.mappings,
    )

    with pytest.raises(ApprovalError, match="imported draft"):
        approve_draft(plain, approver="Reviewer", notes="Cannot erase review state")
    with pytest.raises(ApprovalError, match="imported draft"):
        record_correction(
            imported,
            plain,
            actor="Reviewer",
            notes="Cannot erase review state",
        )


def test_recorded_resolution_uses_original_full_review_item_digest(
    supported_pdfs: tuple[Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
) -> None:
    draft = extract_draft(supported_pdfs)
    corrected = _review_all(draft, injected_recipes)

    assert corrected.review_items == draft.review_items
    assert len(corrected.review_resolutions) == len(draft.review_items)
    assert {resolution.review_item_sha256 for resolution in corrected.review_resolutions} == {
        item.sha256 for item in draft.review_items
    }
    assert all(
        resolution.actor == "Synthetic Reviewer" for resolution in corrected.review_resolutions
    )


def test_build_reviewed_draft_resolves_every_item(
    supported_pdfs: tuple[Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
) -> None:
    draft = extract_draft(supported_pdfs)
    reviewed = build_reviewed_draft(draft, actor="Maintainer", notes="auto review")

    assert reviewed.review_items == draft.review_items
    assert len(reviewed.review_resolutions) == len(draft.review_items)
    assert {resolution.review_item_sha256 for resolution in reviewed.review_resolutions} == {
        item.sha256 for item in draft.review_items
    }
    assert is_fully_resolved(reviewed)


def test_build_reviewed_draft_requires_raw_grid_acceptance(tmp_path: Path) -> None:
    draft = _compound_draft(tmp_path)

    with pytest.raises(ValueError, match="review extracted table cells first"):
        build_reviewed_draft(draft, actor="Maintainer", notes="Build rules")


def test_build_reviewed_draft_keeps_explicit_raw_resolution(tmp_path: Path) -> None:
    draft = _compound_draft(tmp_path)
    accepted = accept_raw_grid(
        draft,
        grid_id="raw-synthetic-part1-table",
        corrections={},
        actor="Maintainer",
        notes="Compared against PDF",
    )

    reviewed = build_reviewed_draft(
        accepted,
        actor="Maintainer",
        notes="Build typed content",
    )

    assert is_fully_resolved(reviewed)
    assert all(item.present for item in required_content_report(reviewed))
    assert {resolution.review_item_sha256 for resolution in accepted.review_resolutions} <= {
        resolution.review_item_sha256 for resolution in reviewed.review_resolutions
    }


def test_placeholder_formula_gate_blocks_then_confirmation_unlocks(
    supported_pdfs: tuple[Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.rules.test_importer import _test_recipes

    recipe1, recipe4 = _test_recipes()
    placeholder_id = "synthetic-placeholder-formula"
    placeholder_spec = FormulaAuditSpec(
        semantic_id=placeholder_id,
        unit="bool",
        variables=(),
        expression_shape="compare(literal,literal)",
        page_number=1,
        clause="SYNTHETIC",
        table="S1",
    )
    modified = recipe1.model_copy(update={"formulas": (*recipe1.formulas, placeholder_spec)})
    monkeypatch.setattr(recipe_registry, "RECIPES", (modified, recipe4))

    assert placeholder_id in placeholder_formula_ids()

    draft = extract_draft(supported_pdfs)
    # add the placeholder's review item is present in inventory since recipe includes it
    reviewed = build_reviewed_draft(draft, actor="Maintainer", notes="auto review")
    # placeholder formula remains unresolved after build
    assert not is_fully_resolved(reviewed)
    pending = [
        item
        for item in reviewed.review_items
        if item.kind == "formula" and item.semantic_id == placeholder_id
    ]
    assert pending
    assert all(
        item.sha256 not in {r.review_item_sha256 for r in reviewed.review_resolutions}
        for item in pending
    )

    confirmed = confirm_placeholder_formula(
        reviewed,
        formula_id=placeholder_id,
        values=(Decimal(2), Decimal(3)),
        actor="Maintainer",
        notes="confirmed constants",
    )
    assert is_fully_resolved(confirmed)


def test_required_content_report_tracks_missing_then_present(
    supported_pdfs: tuple[Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
) -> None:
    draft = extract_draft(supported_pdfs)
    report = required_content_report(draft)
    # A fresh extraction has review items but no typed content yet.
    assert report
    assert all(not item.present for item in report)
    assert {i.semantic_id for i in missing_required_content(draft)} == {
        i.semantic_id for i in report
    }

    reviewed = build_reviewed_draft(draft, actor="Maintainer", notes="auto review")
    report = required_content_report(reviewed)
    assert report
    assert all(item.present for item in report)
    assert missing_required_content(reviewed) == ()


def test_correction_audits_every_changed_or_deleted_semantic_item(
    supported_pdfs: tuple[Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
) -> None:
    draft = extract_draft(supported_pdfs)
    corrected = _review_all(draft, injected_recipes)
    changed = corrected.model_copy(update={"tables": corrected.tables[1:]})

    deleted = record_correction(
        corrected,
        changed,
        actor="Synthetic Reviewer",
        notes="Delete one reviewed table.",
    )

    notes = {
        record.notes
        for record in deleted.manifest.approval_records
        if record.action == "correction"
    }
    assert f"table:{corrected.tables[0].id}" in notes


def _mutate_source_state(
    draft: ImportedRuleDraft,
    mutation: str,
) -> ImportedRuleDraft:
    sources = draft.manifest.source_documents
    identities = draft.source_identities
    if mutation == "one_hash":
        changed_sources = (
            sources[0].model_copy(update={"sha256": "0" * 64}),
            sources[1],
        )
        return draft.model_copy(
            update={
                "manifest": draft.manifest.model_copy(update={"source_documents": changed_sources})
            }
        )
    if mutation == "both_hashes":
        changed_sources = tuple(
            source.model_copy(update={"sha256": "0" * 64}) for source in sources
        )
        changed_identities = tuple(
            identity.model_copy(update={"sha256": "0" * 64}) for identity in identities
        )
        return draft.model_copy(
            update={
                "manifest": draft.manifest.model_copy(update={"source_documents": changed_sources}),
                "source_identities": changed_identities,
            }
        )
    if mutation == "edition":
        changed_sources = (
            sources[0].model_copy(update={"edition": "2019"}),
            sources[1],
        )
        changed_identities = (
            identities[0].model_copy(update={"edition": "2019"}),
            identities[1],
        )
        return draft.model_copy(
            update={
                "manifest": draft.manifest.model_copy(update={"source_documents": changed_sources}),
                "source_identities": changed_identities,
            }
        )
    if mutation == "layout":
        changed_identities = (
            identities[0].model_copy(update={"recipe_id": "other-layout"}),
            identities[1],
        )
        return draft.model_copy(update={"source_identities": changed_identities})
    if mutation == "reordered":
        return draft.model_copy(
            update={
                "manifest": draft.manifest.model_copy(
                    update={"source_documents": tuple(reversed(sources))}
                ),
                "source_identities": tuple(reversed(identities)),
            }
        )
    return draft.model_copy(
        update={
            "manifest": draft.manifest.model_copy(update={"source_documents": sources[:1]}),
            "source_identities": identities[:1],
        }
    )


@pytest.mark.parametrize(
    "mutation",
    ("one_hash", "both_hashes", "edition", "layout", "reordered", "missing"),
)
def test_source_identity_mutation_breaks_the_immutable_genesis(
    supported_pdfs: tuple[Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
    mutation: str,
) -> None:
    corrected = _review_all(extract_draft(supported_pdfs), injected_recipes)
    changed = _mutate_source_state(corrected, mutation)

    with pytest.raises(ApprovalError, match="source|audit|logged|genesis"):
        approve_draft(changed, approver="Reviewer", notes="Reject source mutation")


@pytest.mark.parametrize(
    "mutation",
    ("extra_table", "missing_formula", "wrong_formula", "wrong_mapping", "extra_mapping"),
)
def test_approval_requires_exact_recipe_content_sets_and_shapes(
    supported_pdfs: tuple[Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
    mutation: str,
) -> None:
    corrected = _review_all(extract_draft(supported_pdfs), injected_recipes)
    if mutation == "extra_table":
        changed = corrected.model_copy(
            update={
                "tables": (
                    *corrected.tables,
                    corrected.tables[0].model_copy(update={"id": "extra-table"}),
                )
            }
        )
    elif mutation == "missing_formula":
        changed = corrected.model_copy(update={"formulas": corrected.formulas[1:]})
    elif mutation == "wrong_formula":
        changed = corrected.model_copy(
            update={
                "formulas": (
                    corrected.formulas[0].model_copy(
                        update={"expression": Literal(value=Decimal(1))}
                    ),
                    *corrected.formulas[1:],
                )
            }
        )
    elif mutation == "wrong_mapping":
        changed = corrected.model_copy(
            update={
                "mappings": (
                    corrected.mappings[0].model_copy(
                        update={"target_rule_id": corrected.formulas[1].id}
                    ),
                    *corrected.mappings[1:],
                )
            }
        )
    else:
        changed = corrected.model_copy(
            update={
                "mappings": (
                    *corrected.mappings,
                    corrected.mappings[0].model_copy(
                        update={
                            "id": "extra-mapping",
                            "source_rule_id": "synthetic:extra",
                        }
                    ),
                )
            }
        )
    changed = record_correction(
        corrected,
        changed,
        actor="Synthetic Reviewer",
        notes=f"Logged invalid mutation {mutation}.",
    )

    with pytest.raises(ApprovalError, match="recipe|semantic|mapping|content"):
        approve_draft(changed, approver="Reviewer", notes="Must be exact")


def test_typed_table_cells_must_correspond_to_reviewed_raw_grid(
    supported_pdfs: tuple[Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
) -> None:
    corrected = _review_all(extract_draft(supported_pdfs), injected_recipes)
    table = corrected.tables[0]
    changed = corrected.model_copy(
        update={
            "tables": (
                table.model_copy(
                    update={
                        "cells": (
                            table.cells[0].model_copy(update={"value": table.cells[0].value + 1}),
                            *table.cells[1:],
                        )
                    }
                ),
                *corrected.tables[1:],
            )
        }
    )
    changed = record_correction(
        corrected,
        changed,
        actor="Synthetic Reviewer",
        notes="Logged but invalid raw mismatch.",
    )

    with pytest.raises(ApprovalError, match="raw|recipe|semantic"):
        approve_draft(changed, approver="Reviewer", notes="Must correspond")


def test_approval_and_archive_are_independent_of_source_pdfs(
    supported_pdfs: tuple[Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
    tmp_path: Path,
) -> None:
    corrected = _review_all(extract_draft(supported_pdfs), injected_recipes)

    approved = approve_draft(
        corrected,
        approver="Synthetic Reviewer",
        notes="All generated geometry and contracts reviewed.",
    )
    archive = tmp_path / "approved.icrules"
    write_rule_package(archive, approved)
    for source_pdf in supported_pdfs:
        source_pdf.unlink()

    loaded = load_rule_package(archive)
    assert loaded.manifest.approved is True
    assert loaded.manifest.compatible is True
    assert all(mapping.approved for mapping in loaded.mappings)


def test_malformed_pdf_is_normalized_to_stable_identification_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "malformed.pdf"
    path.write_bytes(b"%PDF-1.7\nmalformed")

    with pytest.raises(UnsupportedStandardError, match="could not be read"):
        identify_standard(path)


def test_pdfplumber_parser_error_is_normalized_at_extract_boundary(
    supported_pdfs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_open(*_args: object, **_kwargs: object) -> None:
        raise PDFSyntaxError("sensitive parser detail")

    monkeypatch.setattr(
        "insulation_coordination.rules.importer.extract.pdfplumber.open",
        fail_open,
    )

    with pytest.raises(ExtractionError) as captured:
        extract_draft(supported_pdfs)
    assert "sensitive parser detail" not in str(captured.value)
