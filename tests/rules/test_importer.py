from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pdfminer.pdfdocument import PDFSyntaxError
from pydantic import ValidationError
from pypdf import PdfWriter

from insulation_coordination.domain.rules import (
    CompatibilityMapping,
    DraftRulePackage,
    Formula,
    Literal,
    Parameter,
    ParameterSet,
    Power,
    SourceReference,
    Table,
    TableAxis,
    TableCell,
    TableSelect,
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
    PasswordRequiredError,
    StandardRecipe,
    TableAuditSpec,
    TableColumnSpec,
    TableSegmentSpec,
    UnsupportedEditionError,
    UnsupportedStandardError,
    identify_standard,
)
from insulation_coordination.rules.importer.projection import project_table
from insulation_coordination.rules.importer.recipes.iec60664_1_2020 import (
    RECIPE as PART1_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec60664_4_2005 import (
    RECIPE as PART4_RECIPE,
)
from insulation_coordination.rules.importer.review import (
    _fill_expression_literals,
    accept_equation_mapping,
    accept_raw_grid,
    accept_raw_table,
    build_reviewed_draft,
    missing_required_content,
    placeholder_formula_ids,
    placeholder_formula_values,
    recipe_derived_items,
    required_content_report,
    unresolved_equation_items,
    unresolved_mapping_items,
    unresolved_raw_review_items,
    unresolved_table_items,
)
from tests.fixtures.synthetic_pdf import (
    _PAGE_HEIGHT,
    _PAGE_WIDTH,
    _TABLE_BBOX,
    create_geometry_pdf,
)


def test_part1_recipe_contains_only_required_pcb_source_inventory() -> None:
    tables = {table.semantic_id: table for table in PART1_RECIPE.tables}

    assert set(tables) == {
        "iec60664-1-f2",
        "iec60664-1-f5",
        "iec60664-1-f8",
        "iec60664-1-f9",
        "iec60664-1-a2",
    }
    assert tuple(segment.page_number for segment in tables["iec60664-1-f5"].segments) == (
        73,
        74,
    )
    assert tuple(column.semantic_id for column in tables["iec60664-1-f5"].columns[:3]) == (
        "rms_voltage_v",
        "pcb_pollution_1",
        "pcb_pollution_2",
    )
    assert {column.semantic_id for column in tables["iec60664-1-f8"].columns} == {
        "peak_voltage_kv",
        "case_a_mm",
        "case_b_mm",
    }
    assert {column.semantic_id for column in tables["iec60664-1-a2"].columns} == {
        "altitude_m",
        "pressure_kpa",
        "clearance_factor",
    }
    assert all(
        column.fill_down for column in tables["iec60664-1-f2"].columns if column.role == "data"
    )


def test_part4_recipe_uses_tables_one_two_and_real_equation_artifacts() -> None:
    assert {table.semantic_id for table in PART4_RECIPE.tables} == {
        "iec60664-4-table-1",
        "iec60664-4-table-2",
    }
    extracted = {
        formula.semantic_id for formula in PART4_RECIPE.formulas if formula.extract_from_pdf
    }
    assert extracted == {
        "iec60664-4-equation-1-critical-frequency",
        "iec60664-4-equation-2-frequency-factor",
        "iec60664-4-minimum-frequency",
        "iec60664-4-radius-criterion",
    }
    assert all("iteration" not in formula.semantic_id for formula in PART4_RECIPE.formulas)
    assert all(mapping.table != "5" for mapping in PART4_RECIPE.mappings)


def test_no_part4_column_hardcodes_a_licensed_axis_value() -> None:
    """Table 2's frequency-band boundaries are licensed table content, so they must

    never live in this public recipe as a declared ``axis_value``; they must be read
    from the document's own header row instead. Mirrors the equivalent guard for the
    62477 recipe's altitude bands.
    """
    for spec in PART4_RECIPE.tables:
        for column in spec.columns:
            assert column.axis_value is None

    table_two = next(
        spec for spec in PART4_RECIPE.tables if spec.semantic_id == "iec60664-4-table-2"
    )
    frequency_columns = [column for column in table_two.columns if column.role == "data"]
    assert frequency_columns
    assert all(column.axis_value_source_row is not None for column in frequency_columns)


def _test_recipes() -> tuple[StandardRecipe, StandardRecipe, StandardRecipe]:
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
            identity_claim_pattern=(
                r"(?i)(IEC\s*(?:60664-[14]|62477-1)).{0,24}?\b((?:19|20)\d{2})\b"
            ),
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
                    # The paired formula below selects with a linear row mode, which
                    # package validation only accepts from an interpolable table.
                    interpolation="linear",
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
                    variables=("stress", "branch"),
                    expression_shape=f"table_select:{table_id}(linear,exact)",
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
        recipe(
            recipe_id="iec62477-1-2022",
            standard="IEC 62477-1",
            edition="2022",
            edition_anchor="Edition 2.0 2022-05",
            topic_anchor="synthetic power conversion geometry",
            table_id="synthetic-part62477-table",
            table_name="S9",
            formula_id="synthetic-part62477-formula",
            mapping_id="synthetic-part62477-mapping",
            route="synthetic:part62477",
        ),
    )


@pytest.fixture(autouse=True)
def injected_recipes(monkeypatch: pytest.MonkeyPatch) -> tuple[StandardRecipe, ...]:
    recipes = _test_recipes()
    monkeypatch.setattr(recipe_registry, "RECIPES", recipes)
    return recipes


@pytest.fixture
def supported_pdfs(tmp_path: Path) -> tuple[Path, Path, Path]:
    part1 = tmp_path / "part1.pdf"
    part4 = tmp_path / "part4.pdf"
    part62477 = tmp_path / "part62477.pdf"
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
    create_geometry_pdf(
        part62477,
        standard="IEC 62477-1",
        edition="2022",
        edition_anchor="Edition 2.0 2022-05",
        topic_anchor="synthetic power conversion geometry",
        table_anchor="Table S9",
    )
    return part1, part4, part62477


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
            expression=TableSelect(
                table_id=table.id,
                row=Variable(name=table_spec.row_axis_id),
                column=Variable(name=table_spec.column_axis_id),
                row_mode="linear",
                column_mode="exact",
            ),
            unit=formula_spec.unit,
            parameter_sets=(
                ParameterSet(
                    id="reviewed",
                    parameters=tuple(
                        Parameter(name=name, unit="1") for name in formula_spec.variables
                    ),
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
    resolved = {resolution.review_item_sha256 for resolution in draft.review_resolutions}
    return record_correction(
        draft,
        changed,
        actor="Synthetic Reviewer",
        notes="Reviewed generated geometry and semantic contracts.",
        resolve=tuple(item for item in draft.review_items if item.sha256 not in resolved),
    )


def test_identifies_supported_document_from_recipe_specific_evidence(
    supported_pdfs: tuple[Path, Path, Path],
) -> None:
    identity = identify_standard(supported_pdfs[0])

    assert identity.standard == "IEC 60664-1"
    assert identity.edition == "2020"
    assert identity.page_count == 1
    assert len(identity.sha256) == 64


def test_identifies_encrypted_document_with_empty_password(
    supported_pdfs: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    encrypted = tmp_path / "part1-empty-password.pdf"
    writer = PdfWriter(clone_from=supported_pdfs[0])
    writer.encrypt("")
    with encrypted.open("wb") as target:
        writer.write(target)

    identity = identify_standard(encrypted)

    assert identity.standard == "IEC 60664-1"


def test_reports_password_required_without_leaking_password(
    supported_pdfs: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    encrypted = tmp_path / "part1-password.pdf"
    writer = PdfWriter(clone_from=supported_pdfs[0])
    writer.encrypt("correct horse")
    with encrypted.open("wb") as target:
        writer.write(target)

    with pytest.raises(PasswordRequiredError, match="requires a password") as captured:
        identify_standard(encrypted)

    assert "correct horse" not in str(captured.value)


def test_identifies_encrypted_document_with_supplied_password(
    supported_pdfs: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    encrypted = tmp_path / "part1-password.pdf"
    writer = PdfWriter(clone_from=supported_pdfs[0])
    writer.encrypt("correct horse")
    with encrypted.open("wb") as target:
        writer.write(target)

    identity = identify_standard(encrypted, password="correct horse")

    assert identity.standard == "IEC 60664-1"


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


def test_wrong_edition_of_a_supported_standard_names_the_failed_check(
    tmp_path: Path,
) -> None:
    path = tmp_path / "part1-wrong-edition.pdf"
    create_geometry_pdf(
        path,
        standard="IEC 60664-1",
        edition="2007",
        edition_anchor="Edition 2.0 2007-04",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
    )
    with pytest.raises(UnsupportedEditionError) as error:
        identify_standard(path)
    assert error.value.detected_standard == "IEC 60664-1"
    assert error.value.detected_edition == "2007"


def test_supported_edition_still_identifies_after_the_claim_change(
    supported_pdfs: tuple[Path, Path, Path],
) -> None:
    assert identify_standard(supported_pdfs[0]).edition == "2020"
    assert identify_standard(supported_pdfs[1]).edition == "2005"


def test_metadata_marker_cannot_embed_or_auto_approve_rule_content(
    supported_pdfs: tuple[Path, Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)

    assert draft.tables == ()
    assert draft.formulas == ()
    assert draft.mappings == ()
    assert draft.review_items
    with pytest.raises(ApprovalError, match="manual review"):
        approve_draft(draft, approver="Reviewer", notes="No bypass")


def test_real_geometry_extracts_every_raw_cell_and_pending_contract(
    supported_pdfs: tuple[Path, Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)

    assert len(draft.raw_grids) == 3
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


def test_data_cell_parser_preserves_allowed_up_to_qualifier() -> None:
    parsed = parse_data_cell(
        "Up to 0,6 a) b)",
        allowed_footnotes=("a", "b"),
        allowed_qualifiers=("up_to",),
    )

    assert parsed.value == Decimal("0.6")
    assert parsed.qualifier == "up_to"
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
    supported_pdfs: tuple[Path, Path, Path],
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
    supported_pdfs: tuple[Path, Path, Path],
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
        update={"extracted_equations": (equation.model_copy(update={"raw_text": "rewritten"}),)}
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
    supported_pdfs: tuple[Path, Path, Path],
    field: str,
) -> None:
    draft = extract_draft(supported_pdfs)
    grid = draft.raw_grids[0]
    cell_index = (
        0
        if field == "role"
        else next(index for index, item in enumerate(grid.cells) if item.role == "data")
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
    supported_pdfs: tuple[Path, Path, Path],
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
    part62477 = tmp_path / "part62477.pdf"
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
    create_geometry_pdf(
        part62477,
        standard="IEC 62477-1",
        edition="2022",
        edition_anchor="Edition 2.0 2022-05",
        topic_anchor="synthetic power conversion geometry",
        table_anchor="Table S9",
    )

    return extract_draft((part1, part4, part62477))


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
    before = {resolution.review_item_sha256 for resolution in draft.review_resolutions}
    after = {resolution.review_item_sha256 for resolution in accepted.review_resolutions}
    assert after - before == {pending[0].sha256}


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
            "not correctable",
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
    part62477 = tmp_path / "part62477.pdf"
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
    create_geometry_pdf(
        part62477,
        standard="IEC 62477-1",
        edition="2022",
        edition_anchor="Edition 2.0 2022-05",
        topic_anchor="synthetic power conversion geometry",
        table_anchor="Table S9",
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
            injected_recipes[2],
        ),
    )

    with pytest.raises(ExtractionError, match="ambiguous"):
        extract_draft((part1, part4, part62477))


def test_missing_or_duplicate_supported_part_is_rejected(
    supported_pdfs: tuple[Path, Path, Path],
) -> None:
    part1, part4, _ = supported_pdfs

    with pytest.raises(ExtractionError, match="must be loaded together"):
        extract_draft((part1,))
    with pytest.raises(ExtractionError, match="duplicate"):
        extract_draft((part1, part1, part4))


def test_importing_without_the_62477_part_names_the_missing_recipe(
    supported_pdfs: tuple[Path, Path, Path],
) -> None:
    part1, part4, _ = supported_pdfs

    with pytest.raises(ExtractionError, match="iec62477-1-2022"):
        extract_draft((part1, part4))


def test_review_inventory_and_locators_are_immutable(
    supported_pdfs: tuple[Path, Path, Path],
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
    supported_pdfs: tuple[Path, Path, Path],
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
    supported_pdfs: tuple[Path, Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
) -> None:
    draft = extract_draft(supported_pdfs)
    corrected = _review_all(draft, injected_recipes)

    assert corrected.review_items == draft.review_items
    assert len(corrected.review_resolutions) == len(draft.review_items)
    assert {resolution.review_item_sha256 for resolution in corrected.review_resolutions} == {
        item.sha256 for item in draft.review_items
    }
    importer_resolved = {
        resolution.review_item_sha256
        for resolution in corrected.review_resolutions
        if resolution.actor.startswith("icc-importer/")
    }
    assert importer_resolved == {item.sha256 for item in recipe_derived_items(draft)}
    assert all(
        resolution.actor == "Synthetic Reviewer"
        for resolution in corrected.review_resolutions
        if resolution.review_item_sha256 not in importer_resolved
    )


def _accept_all_source_artifacts(draft: ImportedRuleDraft) -> ImportedRuleDraft:
    accepted = draft
    for grid in accepted.raw_grids:
        if any(
            item.semantic_id == grid.id.removeprefix("raw-")
            for item in unresolved_table_items(accepted)
        ):
            accepted = accept_raw_table(
                accepted,
                grid_id=grid.id,
                corrections={},
                actor="Maintainer",
                notes="Compared semantic table with PDF",
            )
    equation_ids = tuple(item.semantic_id for item in unresolved_equation_items(accepted))
    mapping_ids = tuple(item.semantic_id for item in unresolved_mapping_items(accepted))
    if equation_ids or mapping_ids:
        accepted = accept_equation_mapping(
            accepted,
            equation_ids=equation_ids,
            mapping_ids=mapping_ids,
            actor="Maintainer",
            notes="Reviewed equations and mappings",
        )
    return accepted


def test_project_table_honours_the_declared_interpolation_mode(
    supported_pdfs: tuple[Path, Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
) -> None:
    """project_table must read interpolation from the spec, not assume "linear"."""
    draft = extract_draft(supported_pdfs)
    recipe = injected_recipes[0]
    identity = next(i for i in draft.source_identities if i.recipe_id == recipe.id)
    table_spec = recipe.tables[0].model_copy(update={"interpolation": "none"})
    grid = next(grid for grid in draft.raw_grids if grid.id == f"raw-{table_spec.semantic_id}")

    projected = project_table(identity, table_spec, grid)

    assert projected.interpolation == "none"


def test_column_axis_value_can_be_derived_from_its_own_header_row(
    supported_pdfs: tuple[Path, Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A column can point at the header row holding its axis value instead of

    declaring the value in the recipe -- required when the value itself is licensed
    table content that must not be committed to a public recipe file.
    """
    part1_recipe = injected_recipes[0]
    legacy_spec = part1_recipe.tables[0]
    segment = TableSegmentSpec(
        id=legacy_spec.semantic_id,
        page_number=legacy_spec.page_number,
        title_anchor=legacy_spec.title_anchor,
        expected_raw_rows=3,
        expected_raw_columns=3,
        expected_bbox=legacy_spec.expected_bbox,
        bbox_tolerance=legacy_spec.bbox_tolerance,
        anchor_max_vertical_gap=legacy_spec.anchor_max_vertical_gap,
        anchor_min_x_overlap=legacy_spec.anchor_min_x_overlap,
        source_columns=(0, 1, 2),
        header_rows=(0,),
        data_rows=(1, 2),
        page_search_radius=legacy_spec.page_search_radius,
    )
    derived_spec = legacy_spec.model_copy(
        update={
            "expected_raw_rows": 3,
            "expected_raw_columns": 3,
            "expected_data_rows": 2,
            "expected_data_columns": 3,
            "segments": (segment,),
            "columns": (
                TableColumnSpec(
                    semantic_id="row-axis",
                    heading="row axis",
                    source_column=0,
                    role="axis",
                    unit="V",
                ),
                TableColumnSpec(
                    semantic_id="column-a",
                    heading="column a",
                    source_column=1,
                    role="data",
                    unit="mm",
                    axis_value_source_row=0,
                ),
                TableColumnSpec(
                    semantic_id="column-b",
                    heading="column b",
                    source_column=2,
                    role="data",
                    unit="mm",
                    axis_value_source_row=0,
                ),
            ),
        }
    )
    monkeypatch.setattr(
        recipe_registry,
        "RECIPES",
        (
            part1_recipe.model_copy(update={"tables": (derived_spec,)}),
            injected_recipes[1],
            injected_recipes[2],
        ),
    )

    draft = extract_draft(supported_pdfs)
    identity = next(i for i in draft.source_identities if i.recipe_id == part1_recipe.id)
    grid = next(grid for grid in draft.raw_grids if grid.id == f"raw-{derived_spec.semantic_id}")

    table = project_table(identity, derived_spec, grid)

    assert table.column_axis.values == (Decimal(10), Decimal(20))


def test_projected_table_source_names_the_page_the_table_was_actually_found_on(
    tmp_path: Path,
    injected_recipes: tuple[StandardRecipe, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A table located one page inside its search window must record that actual page

    in its own ``Table.source``, matching what its cells already record -- not the page
    the recipe declared.
    """
    part1_recipe, part4_recipe, part62477_recipe = injected_recipes
    shifted_spec = part1_recipe.tables[0].model_copy(update={"page_search_radius": 1})
    monkeypatch.setattr(
        recipe_registry,
        "RECIPES",
        (
            part1_recipe.model_copy(update={"tables": (shifted_spec,)}),
            part4_recipe,
            part62477_recipe,
        ),
    )

    part1_table_page = tmp_path / "part1-table.pdf"
    create_geometry_pdf(
        part1_table_page,
        standard="IEC 60664-1",
        edition="2020",
        edition_anchor="Edition 3.0 2020-05",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
    )
    writer = PdfWriter()
    writer.add_blank_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    writer.append(str(part1_table_page))
    # ``append`` copies pages only, not the source document's /Title metadata that
    # identification relies on, so it must be reapplied to the combined document.
    writer.add_metadata({"/Title": "IEC 60664-1:2020 synthetic geometry fixture"})
    part1 = tmp_path / "part1.pdf"
    with part1.open("wb") as target:
        writer.write(target)
    part4 = tmp_path / "part4.pdf"
    create_geometry_pdf(
        part4,
        standard="IEC 60664-4",
        edition="2005",
        edition_anchor="first edition 2005",
        topic_anchor="synthetic high-frequency geometry",
        table_anchor="Table S4",
    )
    part62477 = tmp_path / "part62477.pdf"
    create_geometry_pdf(
        part62477,
        standard="IEC 62477-1",
        edition="2022",
        edition_anchor="Edition 2.0 2022-05",
        topic_anchor="synthetic power conversion geometry",
        table_anchor="Table S9",
    )

    draft = extract_draft((part1, part4, part62477))
    identity = next(i for i in draft.source_identities if i.recipe_id == part1_recipe.id)
    grid = next(grid for grid in draft.raw_grids if grid.id == f"raw-{shifted_spec.semantic_id}")
    assert grid.segments[0].page_number == 2

    table = project_table(identity, shifted_spec, grid)

    assert table.source.note == "PDF page 2"
    assert all(cell.source.note == "PDF page 2" for cell in table.cells)


def test_header_axis_value_column_fails_loudly_when_its_header_cell_is_not_numeric(
    supported_pdfs: tuple[Path, Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extraction must refuse rather than silently fall back to an ordinal position.

    Column 0's header cell (row 0) is the text "axis", not a number. Pointing a data
    column's ``axis_value_source_row`` at that same physical column reuses that
    non-numeric header cell as the declared axis-value source.
    """
    part1_recipe = injected_recipes[0]
    legacy_spec = part1_recipe.tables[0]
    segment = TableSegmentSpec(
        id=legacy_spec.semantic_id,
        page_number=legacy_spec.page_number,
        title_anchor=legacy_spec.title_anchor,
        expected_raw_rows=3,
        expected_raw_columns=3,
        expected_bbox=legacy_spec.expected_bbox,
        bbox_tolerance=legacy_spec.bbox_tolerance,
        anchor_max_vertical_gap=legacy_spec.anchor_max_vertical_gap,
        anchor_min_x_overlap=legacy_spec.anchor_min_x_overlap,
        source_columns=(0, 0, 2),
        header_rows=(0,),
        data_rows=(1, 2),
        page_search_radius=legacy_spec.page_search_radius,
    )
    broken_spec = legacy_spec.model_copy(
        update={
            "expected_raw_rows": 3,
            "expected_raw_columns": 3,
            "expected_data_rows": 2,
            "expected_data_columns": 3,
            "segments": (segment,),
            "columns": (
                TableColumnSpec(
                    semantic_id="row-axis",
                    heading="row axis",
                    source_column=0,
                    role="axis",
                    unit="V",
                ),
                TableColumnSpec(
                    semantic_id="column-a",
                    heading="column a",
                    source_column=0,
                    role="data",
                    unit="mm",
                    axis_value_source_row=0,
                ),
                TableColumnSpec(
                    semantic_id="column-b",
                    heading="column b",
                    source_column=2,
                    role="data",
                    unit="mm",
                    axis_value_source_row=0,
                ),
            ),
        }
    )
    monkeypatch.setattr(
        recipe_registry,
        "RECIPES",
        (
            part1_recipe.model_copy(update={"tables": (broken_spec,)}),
            injected_recipes[1],
            injected_recipes[2],
        ),
    )

    with pytest.raises(ExtractionError, match="axis header cell is not numeric"):
        extract_draft(supported_pdfs)


def test_axis_value_source_row_must_be_declared_in_a_segments_header_rows(
    injected_recipes: tuple[StandardRecipe, ...],
) -> None:
    """A column cannot point its axis value at a row the recipe never marks as a header.

    Without this, ``axis_value_source_row`` could silently name a data row: extraction
    would never raise (the loud "not numeric" guard only checks rows already in
    ``header_rows``), and projection would read whatever data cell happens to sit there.

    ``model_copy(update=...)`` does not revalidate, so the broken spec is built through
    ``model_validate`` on a plain dict instead, the same as parsing it fresh.
    """
    legacy_spec = injected_recipes[0].tables[0]
    segment = TableSegmentSpec(
        id=legacy_spec.semantic_id,
        page_number=legacy_spec.page_number,
        title_anchor=legacy_spec.title_anchor,
        expected_raw_rows=3,
        expected_raw_columns=3,
        expected_bbox=legacy_spec.expected_bbox,
        header_rows=(0,),
        data_rows=(1, 2),
    )
    broken = {
        **legacy_spec.model_dump(),
        "expected_raw_rows": 3,
        "expected_raw_columns": 3,
        "expected_data_rows": 2,
        "expected_data_columns": 2,
        "segments": (segment,),
        "columns": (
            TableColumnSpec(
                semantic_id="row-axis",
                heading="row axis",
                source_column=0,
                role="axis",
                unit="V",
            ),
            TableColumnSpec(
                semantic_id="column-a",
                heading="column a",
                source_column=1,
                role="data",
                unit="mm",
                # Row 1 is a data row in the segment above, not a header row.
                axis_value_source_row=1,
            ),
        ),
    }
    with pytest.raises(ValidationError, match="axis_value_source_row"):
        TableAuditSpec.model_validate(broken)


def test_build_reviewed_draft_resolves_every_item(
    supported_pdfs: tuple[Path, Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
) -> None:
    draft = extract_draft(supported_pdfs)
    accepted = _accept_all_source_artifacts(draft)
    reviewed = build_reviewed_draft(accepted, actor="Maintainer", notes="Build")

    assert reviewed.review_items == draft.review_items
    assert len(reviewed.review_resolutions) == len(draft.review_items)
    assert {resolution.review_item_sha256 for resolution in reviewed.review_resolutions} == {
        item.sha256 for item in draft.review_items
    }
    assert is_fully_resolved(reviewed)
    assert all(
        len(table.supported_ranges) == 1
        and table.supported_ranges[0].variable == table.row_axis.id
        and table.supported_ranges[0].unit == table.row_axis.unit
        and table.supported_ranges[0].minimum == table.row_axis.values[0]
        and table.supported_ranges[0].maximum == table.row_axis.values[-1]
        for table in reviewed.tables
    )


def test_staged_review_requires_tables_then_equations_and_mappings(
    supported_pdfs: tuple[Path, Path, Path],
    injected_recipes: tuple[StandardRecipe, ...],
) -> None:
    draft = extract_draft(supported_pdfs)
    assert draft.tables == draft.formulas == draft.mappings == ()

    reviewed = draft
    for grid in reviewed.raw_grids:
        reviewed = accept_raw_table(
            reviewed,
            grid_id=grid.id,
            corrections={},
            actor="Maintainer",
            notes="Compared semantic table with PDF",
        )

    assert unresolved_table_items(reviewed) == ()
    # The synthetic recipes declare no PDF-extracted equations, so the importer
    # has already resolved every equation and mapping item itself.
    assert unresolved_equation_items(reviewed) == ()
    assert unresolved_mapping_items(reviewed) == ()
    built = build_reviewed_draft(reviewed, actor="Maintainer", notes="Build typed rules")

    assert is_fully_resolved(built)
    assert all(table.row_axis.labels and table.column_axis.labels for table in built.tables)
    assert "raw_sequence" not in str(
        tuple(formula.expression.model_dump(mode="json") for formula in built.formulas)
    )


def test_build_reviewed_draft_requires_equation_review(tmp_path: Path) -> None:
    """An equation item the importer did not resolve still blocks projection."""
    draft = _compound_draft(tmp_path)
    for grid in draft.raw_grids:
        draft = accept_raw_table(
            draft,
            grid_id=grid.id,
            corrections={},
            actor="Maintainer",
            notes="Compared semantic table with PDF",
        )
    formula_digests = {item.sha256 for item in draft.review_items if item.kind == "formula"}
    pending_equations = draft.model_copy(
        update={
            "review_resolutions": tuple(
                resolution
                for resolution in draft.review_resolutions
                if resolution.review_item_sha256 not in formula_digests
            )
        }
    )

    with pytest.raises(ValueError, match="Review equations and mappings first"):
        build_reviewed_draft(pending_equations, actor="Maintainer", notes="Build")


def test_build_reviewed_draft_requires_raw_grid_acceptance(tmp_path: Path) -> None:
    draft = _compound_draft(tmp_path)

    with pytest.raises(ValueError, match="Review extracted tables first"):
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

    accepted = _accept_all_source_artifacts(accepted)
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


def test_corrected_part4_recipe_has_no_placeholder_formula_gate() -> None:
    assert all(
        formula.semantic_id not in placeholder_formula_ids() for formula in PART4_RECIPE.formulas
    )


@pytest.mark.parametrize(
    "expression",
    (
        Power(base=Literal(value=Decimal(2)), numerator=3, denominator=2),
        TableSelect(
            table_id="synthetic-table",
            row=Literal(value=Decimal(1)),
            column=Literal(value=Decimal(2)),
            row_mode="ceiling",
        ),
    ),
)
def test_placeholder_literals_rebuild_through_power_and_table_select(
    expression: Power | TableSelect,
) -> None:
    # confirm_placeholder_formula rebuilds a formula's literals in place, so every
    # op that can carry a Literal child must be traversed, not refused.
    current = placeholder_formula_values(expression)
    assert current

    unchanged = _fill_expression_literals(expression.model_dump(mode="python"), list(current))
    assert unchanged == expression

    replaced = tuple(value + 1 for value in current)
    rebuilt = _fill_expression_literals(expression.model_dump(mode="python"), list(replaced))
    assert placeholder_formula_values(rebuilt) == replaced


def test_required_content_report_tracks_missing_then_present(
    supported_pdfs: tuple[Path, Path, Path],
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

    accepted = _accept_all_source_artifacts(draft)
    reviewed = build_reviewed_draft(accepted, actor="Maintainer", notes="Build")
    report = required_content_report(reviewed)
    assert report
    assert all(item.present for item in report)
    assert missing_required_content(reviewed) == ()


def test_correction_audits_every_changed_or_deleted_semantic_item(
    supported_pdfs: tuple[Path, Path, Path],
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
    supported_pdfs: tuple[Path, Path, Path],
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
    supported_pdfs: tuple[Path, Path, Path],
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
    supported_pdfs: tuple[Path, Path, Path],
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
    supported_pdfs: tuple[Path, Path, Path],
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
    supported_pdfs: tuple[Path, Path, Path],
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
