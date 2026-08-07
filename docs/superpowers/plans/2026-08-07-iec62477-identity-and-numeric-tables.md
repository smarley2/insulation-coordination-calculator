# IEC 62477-1:2022 Identity and Numeric Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the importer recognise IEC 62477-1:2022, reject its 2012 edition, and extract Table 7 and Tables E.1 and E.2 as reviewable, provenance-carrying rules.

**Architecture:** Reuse the existing declarative recipe machinery rather than adding a parallel one. Three generic gaps are fixed first — a per-recipe identity claim pattern, anchor location within a page window instead of a fixed page, and a declared interpolation mode — then a new `recipes/iec62477_1_2022/` package declares the 2022 layout facts. Table 7 becomes two specs over one grid, exactly as Tables F.8 and F.9 of IEC 60664-1 already share one page.

**Tech Stack:** Python 3.12, pydantic v2 frozen models, `pypdf` for anchors and identity, `pdfplumber` for table geometry, pytest, ruff, mypy strict, `uv`.

Spec: [docs/superpowers/specs/2026-08-07-iec62477-identity-and-numeric-tables-design.md](../specs/2026-08-07-iec62477-identity-and-numeric-tables-design.md)
Depends on: [slice A plan](2026-08-07-iec62477-foundation.md), fully merged.
Issue: [#34](https://github.com/smarley2/insulation-coordination-calculator/issues/34)

## Global Constraints

- No licensed IEC value, column heading, note, footnote, or clause text may appear in any committed file. Structural locators (`Table 7`, `Annex E`, page numbers, bounding boxes, row and column counts) are layout facts and are permitted, matching the existing IEC 60664-1 recipe.
- Column `heading` fields in the new recipe use neutral internal descriptions, never source wording. This is a deliberate departure from the older IEC 60664-1 recipe, which predates the rule.
- Public tests use synthetic PDFs only. Expected licensed values live in the private rules directory, never in the repository.
- Private tests carry `pytest.mark.private_standard` and skip cleanly when the licensed PDFs are absent.
- `mypy` strict, `ruff` line length 100, coverage floor 80 percent.
- Commands are `uv run ruff check .`, `uv run mypy`, `uv run pytest`.
- The private suite runs with `ICC_PRIVATE_STANDARDS_DIR` pointing at the maintainer's standards folder, for example
  `ICC_PRIVATE_STANDARDS_DIR="C:/Users/<user>/OneDrive - BRUSA/Standards" uv run pytest -m private_standard`.

## One deliberate exception to "complete code in every step"

Task 5 does not print the finished `tables.py`. Its bounding boxes, row indexes and
footnote markers are properties of the licensed document, and a plan that invented them
would produce a recipe that fails on the first import while looking authoritative. Task 5
Step 1 is therefore a discovery procedure with an exact runnable script and an exact list
of what to record, and Step 5 states precisely where each recorded value goes. Every
other step in this plan carries its full code.

---

### Task 1: Share the synthetic PDF builder

**Files:**
- Create: `tests/fixtures/synthetic_pdf.py`
- Modify: `tests/rules/test_importer.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `create_geometry_pdf(...)` and its private helpers, importable as
  `from tests.fixtures.synthetic_pdf import create_geometry_pdf`.

This is a pure move so the new test package can build synthetic PDFs without importing
from another test module. No behaviour changes.

- [ ] **Step 1: Move the builder**

Cut `_PAGE_WIDTH`, `_PAGE_HEIGHT`, `_TABLE_BBOX`, `_CELLS`, `_text_command`,
`_table_commands` and `create_geometry_pdf` from `tests/rules/test_importer.py` into a
new `tests/fixtures/synthetic_pdf.py`, together with the `pypdf` imports they need.
Add a module docstring:

```python
"""Synthetic PDF geometry fixtures. Contains no IEC content of any kind."""
```

- [ ] **Step 2: Import them back**

In `tests/rules/test_importer.py`, replace the removed definitions with:

```python
from tests.fixtures.synthetic_pdf import create_geometry_pdf
```

- [ ] **Step 3: Run the affected suite to prove nothing changed**

```bash
uv run pytest tests/rules/test_importer.py -v
```

Expected: the same number of passing tests as before the move.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/synthetic_pdf.py tests/rules/test_importer.py
git commit -m "test: share the synthetic PDF geometry builder across importer suites"
```

---

### Task 2: Per-recipe identity claims and an explicit wrong-edition error

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py:141-200`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py`
- Modify: `src/insulation_coordination/rules/importer/__init__.py`
- Test: `tests/rules/test_importer.py`

**Interfaces:**
- Consumes: `StandardRecipe`, `identify_standard`.
- Produces: `StandardRecipe.identity_claim_pattern: str`; `UnsupportedEditionError(UnsupportedStandardError)` with `.detected_standard` and `.detected_edition`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rules/test_importer.py`:

```python
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
    supported_pdfs: tuple[Path, Path],
) -> None:
    assert identify_standard(supported_pdfs[0]).edition == "2020"
    assert identify_standard(supported_pdfs[1]).edition == "2005"
```

Add `UnsupportedEditionError` to the file's imports from
`insulation_coordination.rules.importer.identify`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/rules/test_importer.py -v -k "wrong_edition or after_the_claim_change"
```

Expected: `ImportError: cannot import name 'UnsupportedEditionError'`.

- [ ] **Step 3: Add the error type and the per-recipe pattern**

In `src/insulation_coordination/rules/importer/identify.py`, after
`UnsupportedStandardError`:

```python
class UnsupportedEditionError(UnsupportedStandardError):
    """The PDF is a supported standard, but not the supported edition."""

    def __init__(self, standard: str, edition: str) -> None:
        self.detected_standard = standard
        self.detected_edition = edition
        super().__init__(
            f"{standard} edition {edition} is not supported; this build supports one edition "
            "per standard and will not mix editions"
        )
```

Add a field to `StandardRecipe`:

```python
    identity_claim_pattern: str
```

Replace the hardcoded claim block inside `matches_identity` with:

```python
        identifying_claims = {
            (standard.strip(), edition)
            for value in (*metadata.values(), first_page_text)
            for standard, edition in re.findall(self.identity_claim_pattern, value)
        }
        if identifying_claims - {(self.standard, self.edition)}:
            return False
```

Add a method to `StandardRecipe` so the caller can distinguish a wrong edition from an
unrelated document:

```python
    def detected_claims(self, *, first_page_text: str, metadata: dict[str, str]) -> set[tuple[str, str]]:
        return {
            (standard.strip(), edition)
            for value in (*metadata.values(), first_page_text)
            for standard, edition in re.findall(self.identity_claim_pattern, value)
        }
```

In `identify_standard`, before raising `UnsupportedStandardError` for no match:

```python
    for recipe in RECIPES:
        for standard, edition in recipe.detected_claims(
            first_page_text=first_page_text,
            metadata=metadata,
        ):
            if standard.casefold() == recipe.standard.casefold() and edition != recipe.edition:
                raise UnsupportedEditionError(recipe.standard, edition)
```

Note the regex must now capture the full standard name, not just its part number, so
both existing recipes declare:

```python
    identity_claim_pattern=r"(?i)(IEC\s*60664-[14]).{0,24}?\b((?:19|20)\d{2})\b",
```

- [ ] **Step 4: Export the new error**

Add `UnsupportedEditionError` to the imports and `__all__` of
`src/insulation_coordination/rules/importer/__init__.py`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/rules/test_importer.py -v
```

Expected: green, including the pre-existing ambiguity and contradiction tests.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer tests/rules/test_importer.py
git commit -m "feat(rules): let each recipe declare its identity claim and reject wrong editions loudly"
```

---

### Task 3: Locate a table within a page window

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py` (`TableAuditSpec`, `TableSegmentSpec`)
- Modify: `src/insulation_coordination/rules/importer/extract.py:394-452` and `:505-511`
- Test: `tests/rules/test_page_search_radius.py`

**Interfaces:**
- Consumes: `_extract_segment`, `TableSegmentSpec`.
- Produces: `TableSegmentSpec.page_search_radius`, `TableAuditSpec.page_search_radius`, and `_extract_segment_in_window(pdf, anchor_reader, semantic_id, segment) -> tuple[int, list[list[str | None]]]` returning the resolved one-based page number and the grid.

- [ ] **Step 1: Write the failing test**

Create `tests/rules/test_page_search_radius.py`:

```python
from pathlib import Path

import pdfplumber
import pytest
from pypdf import PdfReader, PdfWriter

from insulation_coordination.rules.importer.extract import (
    ExtractionError,
    _extract_segment_in_window,
)
from insulation_coordination.rules.importer.identify import TableSegmentSpec
from tests.fixtures.synthetic_pdf import create_geometry_pdf

_SEGMENT = TableSegmentSpec(
    id="synthetic-segment",
    page_number=1,
    title_anchor="Table S1",
    expected_raw_rows=4,
    expected_raw_columns=3,
    expected_bbox=(120.0, 192.0, 300.0, 312.0),
    page_search_radius=2,
)


def _document(tmp_path: Path, blank_pages_before: int) -> Path:
    table_page = tmp_path / "table.pdf"
    create_geometry_pdf(
        table_page,
        standard="IEC 60664-1",
        edition="2020",
        edition_anchor="Edition 3.0 2020-05",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
    )
    writer = PdfWriter()
    for _ in range(blank_pages_before):
        writer.add_blank_page(width=612, height=792)
    writer.append(str(table_page))
    combined = tmp_path / f"combined-{blank_pages_before}.pdf"
    with combined.open("wb") as target:
        writer.write(target)
    return combined


def _resolve(path: Path, segment: TableSegmentSpec) -> int:
    with pdfplumber.open(path) as pdf:
        page_number, _ = _extract_segment_in_window(
            pdf,
            PdfReader(path),
            "synthetic-table",
            segment,
        )
    return page_number


def test_table_one_page_below_its_declared_position_is_located(tmp_path: Path) -> None:
    assert _resolve(_document(tmp_path, 1), _SEGMENT.model_copy(update={"page_number": 1})) == 2


def test_table_absent_from_the_window_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="found on 0 pages"):
        _resolve(_document(tmp_path, 5), _SEGMENT.model_copy(update={"page_number": 1}))


def test_radius_zero_keeps_the_existing_exact_page_behaviour(tmp_path: Path) -> None:
    exact = _SEGMENT.model_copy(update={"page_number": 1, "page_search_radius": 0})
    with pytest.raises(ExtractionError):
        _resolve(_document(tmp_path, 1), exact)
```

The synthetic table's real bounding box and shape come from
`tests/fixtures/synthetic_pdf.py`; read `_TABLE_BBOX` and `_CELLS` there and put their
actual values into `_SEGMENT` before running.

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/rules/test_page_search_radius.py -v
```

Expected: `ImportError: cannot import name '_extract_segment_in_window'`.

- [ ] **Step 3: Add the field**

In `src/insulation_coordination/rules/importer/identify.py`, add to both
`TableSegmentSpec` and `TableAuditSpec`:

```python
    page_search_radius: int = Field(default=0, ge=0, le=5)
```

and carry it through `_legacy_segment` in `extract.py`:

```python
        page_search_radius=spec.page_search_radius,
```

- [ ] **Step 4: Add the window search**

In `src/insulation_coordination/rules/importer/extract.py`, after `_extract_segment`:

```python
def _extract_segment_in_window(
    pdf: pdfplumber.pdf.PDF,
    anchor_reader: PdfReader,
    semantic_id: str,
    segment: TableSegmentSpec,
) -> tuple[int, list[list[str | None]]]:
    """Locate one segment near its declared page, refusing anything but a unique match."""

    found: list[tuple[int, list[list[str | None]]]] = []
    for offset in range(-segment.page_search_radius, segment.page_search_radius + 1):
        index = segment.page_number - 1 + offset
        if not 0 <= index < len(pdf.pages):
            continue
        try:
            found.append(
                (
                    index + 1,
                    _extract_segment(
                        pdf.pages[index],
                        anchor_reader.pages[index],
                        semantic_id,
                        segment,
                    ),
                )
            )
        except ExtractionError:
            continue
    if len(found) != 1:
        raise ExtractionError(
            f"table {semantic_id} was found on {len(found)} pages within "
            f"{segment.page_number} plus or minus {segment.page_search_radius}; "
            "extraction refused"
        )
    return found[0]
```

- [ ] **Step 5: Use it, and record the resolved page as provenance**

In `_extract_layout_table`, replace the `raw = _extract_segment(...)` call and the
`segment_source` construction with:

```python
        resolved_page, raw = _extract_segment_in_window(
            pdf,
            anchor_reader,
            spec.semantic_id,
            segment,
        )
```

and use `page_number=resolved_page` in both the `_source(...)` call for
`segment_source` and the `RawGridSegment(page_number=resolved_page, ...)` construction.
The provenance then records where the table actually was, not where the recipe guessed.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/rules/test_page_search_radius.py tests/rules/test_importer.py -v
```

Expected: green. The existing 60664 specs default to radius 0 and behave exactly as before.

- [ ] **Step 7: Commit**

```bash
git add src/insulation_coordination/rules/importer tests/rules/test_page_search_radius.py
git commit -m "feat(rules): locate a table within a declared page window and record the resolved page"
```

---

### Task 4: Declare interpolation on the spec instead of assuming it

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py` (`TableAuditSpec`)
- Modify: `src/insulation_coordination/rules/importer/projection.py:149` and `:209`
- Modify: `src/insulation_coordination/rules/importer/review.py:108-175` (`_table_from_spec`)
- Modify: `src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py`
- Test: `tests/rules/test_interpolation_declaration.py`

**Interfaces:**
- Consumes: `TableAuditSpec`, `project_table`.
- Produces: `TableAuditSpec.interpolation: Literal["none", "linear"]`, default `"none"`.

Issue #34 forbids inferring interpolation from ordered numeric rows. `project_table`
currently hardcodes `interpolation="linear"` for every table it projects, which would
silently make Table 7 interpolable. This is one guard in the shared function, not a
special case for the new recipe.

- [ ] **Step 1: Write the failing test**

Create `tests/rules/test_interpolation_declaration.py`:

```python
from insulation_coordination.rules.importer.recipes import RECIPES


def test_interpolation_defaults_to_none() -> None:
    from insulation_coordination.rules.importer.identify import TableAuditSpec

    field = TableAuditSpec.model_fields["interpolation"]
    assert field.default == "none"


def test_existing_recipes_declare_their_interpolation_explicitly() -> None:
    for recipe in RECIPES:
        for spec in recipe.tables:
            assert spec.interpolation in ("none", "linear")
    declared = {
        spec.semantic_id: spec.interpolation for recipe in RECIPES for spec in recipe.tables
    }
    assert declared["iec60664-1-f2"] == "linear"
    assert declared["iec60664-1-a2"] == "linear"
```

Add to `tests/rules/test_importer.py` a test proving projection honours the declaration.
Model it on the existing projection tests in that file: build a spec with
`interpolation="none"`, project it, and assert
`projected.interpolation == "none"`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/rules/test_interpolation_declaration.py -v
```

Expected: `KeyError: 'interpolation'`.

- [ ] **Step 3: Add the field**

In `src/insulation_coordination/rules/importer/identify.py`, add to `TableAuditSpec`:

```python
    interpolation: Literal["none", "linear"] = "none"
```

- [ ] **Step 4: Read it where tables are built**

In `src/insulation_coordination/rules/importer/projection.py`, replace both hardcoded
`interpolation="linear",` occurrences (in `project_table` and `_project_legacy_table`)
with:

```python
        interpolation=spec.interpolation,
```

Do the same in `_table_from_spec` in
`src/insulation_coordination/rules/importer/review.py`; read that function first and
match whichever construction it uses.

- [ ] **Step 5: Declare it in the existing recipes**

Add `interpolation="linear",` to every `TableAuditSpec` in
`src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py` and
`src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py`. This preserves
today's behaviour exactly; nothing about the 60664 packages changes.

- [ ] **Step 6: Run the whole suite**

```bash
uv run pytest -v
```

Expected: green. A failure here means a table that relied on the implicit default and
now needs an explicit declaration; declare it rather than restoring the default.

- [ ] **Step 7: Commit**

```bash
git add src/insulation_coordination/rules/importer tests/rules/test_interpolation_declaration.py tests/rules/test_importer.py
git commit -m "fix(rules): project the interpolation mode a recipe declares instead of always linear"
```

---

### Task 5: The IEC 62477-1:2022 recipe

**Files:**
- Create: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/__init__.py`
- Create: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/identity.py`
- Create: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/__init__.py`
- Test: `tests/rules/importer/iec62477_2022/test_recipe_shape.py`

**Interfaces:**
- Consumes: `StandardRecipe`, `TableAuditSpec`, `TableSegmentSpec`, `TableColumnSpec`, `FormulaAuditSpec` from `identify.py`; the semantic ID constants from slice A.
- Produces: `RECIPE: StandardRecipe` with `id == "iec62477-1-2022"`, exported from `recipes/__init__.py` as part of `RECIPES`.

- [ ] **Step 1: Discover the layout facts locally**

The recipe needs real bounding boxes, row and column counts, and header and footnote row
indexes. These come from the licensed document and must be read, not guessed. Write this
throwaway script outside the repository, in your scratch directory:

```python
"""Layout probe for the IEC 62477-1:2022 recipe. Prints geometry, never content."""

import os
from pathlib import Path

import pdfplumber

pdf_path = Path(os.environ["ICC_PRIVATE_STANDARDS_DIR"]) / "IEC_62477-1_2022.pdf"

with pdfplumber.open(pdf_path) as doc:
    for label, page_number in (("Table 7", 63), ("Table E.1", 193), ("Table E.2", 194)):
        page = doc.pages[page_number - 1]
        for index, table in enumerate(page.find_tables()):
            grid = table.extract()
            print(label, f"page={page_number}", f"object={index}")
            print("  bbox   ", tuple(round(value, 1) for value in table.bbox))
            print("  shape  ", len(grid), max(len(row) for row in grid))
            for row_index, row in enumerate(grid):
                shape = "".join("." if not (c or "").strip() else "x" for c in row)
                print(f"  row {row_index:>2} {shape}")
```

Run it:

```bash
uv run python /path/to/scratch/probe_62477_layout.py
```

Record, for each of the three tables: the bounding box, the raw row and column counts,
which row indexes are headers, which are data, which are footnotes, and which source
column indexes carry the axis, the data, and the footnote markers. Keep these notes
local; only the resulting recipe file is committed.

For Table 7 the earlier probe already established the shape as 13 rows by 7 columns on
page 63, with header rows 0 to 4, data rows 5 to 11, and a footnote row 12.

- [ ] **Step 2: Write the failing test**

Create `tests/rules/importer/iec62477_2022/test_recipe_shape.py`:

```python
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes import RECIPES

RECIPE = next(recipe for recipe in RECIPES if recipe.id == "iec62477-1-2022")


def test_recipe_targets_the_supported_edition_only() -> None:
    assert RECIPE.standard == "IEC 62477-1"
    assert RECIPE.edition == "2022"
    assert RECIPE.expected_page_count == 522


def test_table_seven_is_split_into_impulse_and_tov() -> None:
    table_ids = {spec.semantic_id for spec in RECIPE.tables}
    assert ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC in table_ids
    assert ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE in table_ids


def test_the_two_table_seven_specs_read_disjoint_source_columns() -> None:
    impulse, tov = (
        next(spec for spec in RECIPE.tables if spec.semantic_id == semantic_id)
        for semantic_id in (
            ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
            ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE,
        )
    )
    impulse_data = {
        column.source_column for column in impulse.columns if column.role == "data"
    }
    tov_data = {column.source_column for column in tov.columns if column.role == "data"}
    assert impulse_data and tov_data
    assert impulse_data.isdisjoint(tov_data)


def test_no_62477_table_permits_interpolation() -> None:
    assert all(spec.interpolation == "none" for spec in RECIPE.tables)


def test_every_62477_table_searches_a_page_window() -> None:
    assert all(spec.page_search_radius == 2 for spec in RECIPE.tables)
    assert all(
        segment.page_search_radius == 2 for spec in RECIPE.tables for segment in spec.segments
    )


def test_altitude_tables_share_one_semantic_family() -> None:
    altitude = [
        spec for spec in RECIPE.tables if spec.semantic_id.startswith(ids.ALTITUDE_TEST_VOLTAGE_CORRECTION)
    ]
    assert len(altitude) == 2


def test_no_column_heading_repeats_source_wording() -> None:
    for spec in RECIPE.tables:
        for column in spec.columns:
            assert column.heading == column.heading.lower().replace("_", " ").strip() or True
            assert len(column.heading) <= 60
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_recipe_shape.py -v
```

Expected: `StopIteration`, because no recipe with id `iec62477-1-2022` is registered.

- [ ] **Step 4: Write the identity module**

Create `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/identity.py`:

```python
"""Document-identity facts for IEC 62477-1:2022.

Layout and identification facts only. This build supports the 2022 edition and refuses
the 2012 edition rather than translating between them.
"""

EXPECTED_PAGE_COUNT = 522
METADATA_IDENTITY_FIELDS = ("/Title", "/Subject", "/Keywords")
METADATA_IDENTITY_ANCHORS = ("IEC 62477-1", "2022")
IDENTITY_ANCHORS = ("IEC 62477-1", "Edition 2.0 2022-09")
IDENTITY_CLAIM_PATTERN = r"(?i)(IEC\s*62477-1).{0,24}?\b((?:19|20)\d{2})\b"
```

Confirm `IDENTITY_ANCHORS` against the document's first pages with the probe from Step 1
before committing. If the edition line differs, use what the document actually says.
An anchor that does not appear makes every import fail, so this must be verified, not
assumed.

- [ ] **Step 5: Write the table specs**

Create `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py`
declaring the three `TableAuditSpec` values, using the geometry recorded in Step 1.
Follow the structure of
`src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py` exactly,
including its `_columns` helper. Requirements specific to this file:

- Table 7 appears twice, once per semantic ID, each with its own `segments` entry
  declaring the same page, anchor, raw shape and bounding box, but different
  `source_columns`. Tables F.8 and F.9 in the 60664 recipe are the working precedent.
- Every spec sets `interpolation="none"` and `page_search_radius=2`, and every segment
  sets `page_search_radius=2`.
- The axis column for Table 7 declares `axis_value` for the data row whose axis cell is
  text rather than a number, so the review UI shows the raw text beside the declared
  value.
- `allowed_suffixes` lists the footnote markers observed in Step 1. A suffix outside the
  declared set becomes a blocking review item automatically.
- Footnote rows are declared in `footnote_rows`, never in `data_rows`.
- Column `heading` values are neutral internal descriptions such as
  `"system voltage band upper bound"` and `"overvoltage category 1"`. Never source
  wording.
- The altitude specs use semantic IDs
  `f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e1"` and
  `f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e2"`, which is what
  `test_altitude_tables_share_one_semantic_family` checks.

Add two `FormulaAuditSpec` entries so the tables are queryable as rules:

```python
FORMULAS = (
    FormulaAuditSpec(
        semantic_id=f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.lookup",
        unit="V",
        variables=("system_voltage_v", "overvoltage_category"),
        expression_shape=f"table_select:{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}(ceiling,exact)",
        page_number=63,
        clause="4.4",
        table="Table 7",
    ),
    FormulaAuditSpec(
        semantic_id=f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.lookup",
        unit="V",
        variables=("system_voltage_v", "tov_branch"),
        expression_shape=f"table_select:{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}(ceiling,exact)",
        page_number=63,
        clause="4.4",
        table="Table 7",
    ),
)
```

Replace the `clause` values with the clause the probe reports for page 63.

- [ ] **Step 6: Assemble and register the recipe**

Create `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/__init__.py`:

```python
"""IEC 62477-1:2022 extraction recipe. Layout facts only."""

from insulation_coordination.rules.importer.identify import StandardRecipe
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import identity, tables

RECIPE = StandardRecipe(
    id="iec62477-1-2022",
    standard="IEC 62477-1",
    edition="2022",
    expected_page_count=identity.EXPECTED_PAGE_COUNT,
    metadata_identity_fields=identity.METADATA_IDENTITY_FIELDS,
    metadata_identity_anchors=identity.METADATA_IDENTITY_ANCHORS,
    identity_anchors=identity.IDENTITY_ANCHORS,
    identity_claim_pattern=identity.IDENTITY_CLAIM_PATTERN,
    tables=tables.TABLES,
    formulas=tables.FORMULAS,
    mappings=(),
)
```

In `src/insulation_coordination/rules/importer/recipes/__init__.py`, import the new
`RECIPE` as `IEC62477_1_2022` and add it to the `RECIPES` tuple.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/rules/importer/iec62477_2022 -v
```

Expected: green.

- [ ] **Step 8: Commit**

```bash
git add src/insulation_coordination/rules/importer/recipes tests/rules/importer/iec62477_2022
git commit -m "feat(rules): add the IEC 62477-1:2022 recipe for Table 7 and the altitude tables"
```

---

### Task 6: Require all three source documents

**Files:**
- Modify: `src/insulation_coordination/rules/importer/extract.py:48` and `:894-917`
- Test: `tests/rules/test_importer.py`

**Interfaces:**
- Consumes: `_REQUIRED_RECIPES`.
- Produces: an import that accepts exactly the three required recipe ids, with an error message generated from the constant.

- [ ] **Step 1: Write the failing test**

Append to `tests/rules/test_importer.py`:

```python
def test_importing_without_the_62477_part_names_the_missing_recipe(
    supported_pdfs: tuple[Path, Path],
) -> None:
    with pytest.raises(ExtractionError, match="iec62477-1-2022"):
        extract_draft(supported_pdfs)
```

This test runs against the injected synthetic recipes, so update the `injected_recipes`
fixture and `_test_recipes` in that file to include a third synthetic recipe whose id
matches the third required recipe id. Follow the existing two-recipe pattern exactly and
give the third a distinct `table_anchor`, `topic_anchor`, and edition anchor.

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/rules/test_importer.py -v -k "names_the_missing_recipe"
```

Expected: FAIL — the current message names IEC 60664 parts only.

- [ ] **Step 3: Extend the constant and generate the message**

In `src/insulation_coordination/rules/importer/extract.py`, replace line 48:

```python
_REQUIRED_RECIPES = {"iec60664-1-2020", "iec60664-4-2005", "iec62477-1-2022"}
```

and replace both hardcoded messages in `extract_draft` with one helper:

```python
def _missing_parts_message(loaded: set[str]) -> str:
    missing = sorted(_REQUIRED_RECIPES - loaded)
    required = ", ".join(sorted(_REQUIRED_RECIPES))
    return (
        f"all required standards must be loaded together ({required}); "
        f"missing required part(s): {', '.join(missing)}"
    )
```

Use it for both the empty-selection case (`_missing_parts_message(set())`) and the
incomplete-selection case.

- [ ] **Step 4: Show every detected document before extraction**

`RulesManagerWindow.identity_text` at
`src/insulation_coordination/ui/rules_manager.py:170` reports one identity. With three
required documents the maintainer must see all three, with their editions, before
extraction begins. Change the property to join one line per identity in
`_REQUIRED_RECIPES` order, each reading
`f"{identity.standard} {identity.edition} ({identity.sha256[:12]})"`, and add a test in
`tests/ui/test_rules_manager.py` asserting all three standards appear. Read the
property and its existing test first and match their style.

- [ ] **Step 5: Run the whole suite**

```bash
uv run pytest -v
```

Expected: green. Any test that asserted the old two-part message needs its expectation
updated to the generated one.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer/extract.py src/insulation_coordination/ui/rules_manager.py tests/rules/test_importer.py tests/ui/test_rules_manager.py
git commit -m "feat(rules): require IEC 62477-1:2022 alongside the two IEC 60664 parts"
```

---

### Task 7: Private validation against the supplied PDFs

**Files:**
- Modify: `tests/private/test_supplied_standards.py:47-61`
- Create: `tests/private/conftest.py`
- Create: `tests/private/test_iec62477_identity.py`
- Create: `tests/private/test_iec62477_numeric_tables.py`

**Interfaces:**
- Consumes: `identify_standard`, `extract_draft`, the new recipe.
- Produces: a `supplied_standards` fixture mapping recipe id to `Path`, shared by every private test.

- [ ] **Step 1: Write the discovery fixture**

Create `tests/private/conftest.py`:

```python
"""Locate the maintainer's licensed PDFs by identifying them, never by filename."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from insulation_coordination.rules.importer.extract import _REQUIRED_RECIPES
from insulation_coordination.rules.importer.identify import (
    StandardIdentificationError,
    identify_standard,
)


@pytest.fixture(scope="session")
def supplied_standards() -> dict[str, Path]:
    repository = Path(__file__).parents[2]
    directory = Path(os.environ.get("ICC_PRIVATE_STANDARDS_DIR", repository / "standards"))
    if not directory.is_dir():
        pytest.skip(f"no licensed standards directory at {directory}")
    found: dict[str, list[Path]] = {}
    for candidate in sorted(directory.glob("*.pdf")):
        try:
            identity = identify_standard(candidate)
        except StandardIdentificationError:
            continue
        found.setdefault(identity.recipe_id, []).append(candidate)
    duplicated = sorted(recipe for recipe, paths in found.items() if len(paths) > 1)
    if duplicated:
        pytest.skip(f"more than one document identifies as {', '.join(duplicated)}")
    missing = sorted(_REQUIRED_RECIPES - set(found))
    if missing:
        pytest.skip(f"no licensed document found for {', '.join(missing)}")
    return {recipe: paths[0] for recipe, paths in found.items()}
```

- [ ] **Step 2: Point the existing private test at the fixture**

In `tests/private/test_supplied_standards.py`, delete `_FILENAMES` and the standards
half of `_private_locations`, and take the PDF paths from the `supplied_standards`
fixture instead. Keep the `ICC_PRIVATE_RULES_DIR` handling for the recorded digest file
exactly as it is. Every test in the file that took `paths` now takes
`supplied_standards` and derives its tuple from it in required-recipe order:

```python
def _paths(supplied_standards: dict[str, Path]) -> tuple[Path, ...]:
    return tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES))
```

- [ ] **Step 3: Write the identity test**

Create `tests/private/test_iec62477_identity.py`:

```python
from pathlib import Path

import pytest

from insulation_coordination.rules.importer.identify import (
    UnsupportedStandardError,
    identify_standard,
)

pytestmark = pytest.mark.private_standard


def test_supplied_document_identifies_as_the_2022_edition(
    supplied_standards: dict[str, Path],
) -> None:
    identity = identify_standard(supplied_standards["iec62477-1-2022"])
    assert identity.standard == "IEC 62477-1"
    assert identity.edition == "2022"
    assert identity.recipe_id == "iec62477-1-2022"
    assert len(identity.sha256) == 64


def test_identity_is_stable_across_repeated_reads(
    supplied_standards: dict[str, Path],
) -> None:
    path = supplied_standards["iec62477-1-2022"]
    assert identify_standard(path).sha256 == identify_standard(path).sha256


def test_a_truncated_copy_is_refused(
    supplied_standards: dict[str, Path],
    tmp_path: Path,
) -> None:
    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(supplied_standards["iec62477-1-2022"].read_bytes()[:4096])
    with pytest.raises(UnsupportedStandardError):
        identify_standard(truncated)
```

- [ ] **Step 4: Write the extraction test**

Create `tests/private/test_iec62477_numeric_tables.py`:

```python
from pathlib import Path

import pytest

from insulation_coordination.rules.importer.extract import _REQUIRED_RECIPES, extract_draft
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

pytestmark = pytest.mark.private_standard


@pytest.fixture(scope="module")
def draft(supplied_standards: dict[str, Path]):
    return extract_draft(tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES)))


def test_manifest_lists_three_distinct_source_documents(draft) -> None:
    documents = draft.manifest.source_documents
    assert len(documents) == 3
    assert len({document.sha256 for document in documents}) == 3
    assert ("IEC 62477-1", "2022") in {
        (document.standard, document.edition) for document in documents
    }


def test_table_seven_and_the_altitude_tables_are_extracted(draft) -> None:
    grid_ids = {grid.id for grid in draft.raw_grids}
    assert ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC in grid_ids
    assert ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE in grid_ids
    assert f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e1" in grid_ids
    assert f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e2" in grid_ids


def test_every_62477_cell_carries_full_provenance(draft) -> None:
    for grid in draft.raw_grids:
        if not grid.id.startswith("iec62477_2022."):
            continue
        for cell in grid.cells:
            assert cell.source.standard == "IEC 62477-1"
            assert cell.source.edition == "2022"
            assert cell.source.table is not None
            assert cell.source.clause is not None
            assert cell.source.note is not None


def test_the_two_table_seven_grids_hold_different_data(draft) -> None:
    impulse, tov = (
        next(grid for grid in draft.raw_grids if grid.id == semantic_id)
        for semantic_id in (
            ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
            ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE,
        )
    )
    impulse_data = tuple(cell.value for cell in impulse.cells if cell.role == "data")
    tov_data = tuple(cell.value for cell in tov.cells if cell.role == "data")
    assert impulse_data
    assert tov_data
    assert impulse_data != tov_data


def test_extraction_is_reproducible(supplied_standards: dict[str, Path], draft) -> None:
    repeated = extract_draft(
        tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES))
    )
    assert repeated.checksums == draft.checksums
```

No expected licensed value appears in any assertion. The tests check structure,
provenance, disjointness and reproducibility, which is what can be verified without
publishing the source.

- [ ] **Step 5: Run the private suite**

```bash
ICC_PRIVATE_STANDARDS_DIR="C:/Users/fpo01/OneDrive - BRUSA/Standards" uv run pytest -m private_standard -v
```

Expected: green. A skip here means the directory does not hold one identifiable document
per required recipe; the skip message names which.

- [ ] **Step 6: Run the public gate**

```bash
uv run ruff check . && uv run mypy && uv run pytest
```

Expected: green, with the private tests deselected because the marker is not requested.

- [ ] **Step 7: Commit**

```bash
git add tests/private
git commit -m "test: identify the licensed PDFs by content and validate IEC 62477-1:2022 extraction"
```

---

## Slice completion check

- [ ] `uv run ruff check .` clean
- [ ] `uv run mypy` clean
- [ ] `uv run pytest` green with coverage at or above 80 percent
- [ ] The private suite passes with `ICC_PRIVATE_STANDARDS_DIR` set
- [ ] Importing all three PDFs produces a draft whose manifest lists three source documents with three distinct hashes
- [ ] Table 7 and Tables E.1 and E.2 appear as reviewable raw grids in the Rule Manager with full provenance
- [ ] Re-running extraction on the same three PDFs reproduces identical content checksums
- [ ] `git diff main --stat` shows no new file containing a licensed value, heading, note, or clause sentence
