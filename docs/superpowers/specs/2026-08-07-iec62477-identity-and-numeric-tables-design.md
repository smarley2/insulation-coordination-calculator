# IEC 62477-1:2022 identity and numeric tables (Slice B)

Issue: [#34](https://github.com/smarley2/insulation-coordination-calculator/issues/34), slice B of five.
Depends on: [slice A](2026-08-07-iec62477-foundation-design.md).
Date: 2026-08-07.

## Purpose

Slice A adds the schema and the inventory but reads no PDF. This slice makes the
importer recognise IEC 62477-1:2022 and extract its first three numeric sources, so the
whole path — identify, locate, extract, review, project, approve — is proven against the
real document before the harder content arrives.

Scope is deliberately narrow:

- document identity and edition validation, including explicit rejection of the 2012
  edition;
- Table 7, projected as two separate semantic rules, impulse and TOV;
- Tables E.1 and E.2, altitude and test-voltage correction.

Tables 8, 9, 2, 3 and 26 through 30 are not in this slice. A structural probe of the
document shows Tables 8 and 9 contain ragged rows and blank separator columns, so they
need the blank-cell classification machinery that slice C builds. Tables 2 and 3 are
categorical and need decision projection, also slice C.

## What the document looks like

Structural facts established by probing the licensed PDF. No content is reproduced here
or in any committed file.

- 522 pages, encrypted, opens with an empty password. `pypdf` and `pdfplumber` both read
  it, every page yields extractable text.
- Bilingual. The French half titles its tables `Tableau N`, the English half `Table N`,
  so an English title anchor never collides with the French copy.
- Each English `Table N` title line appears on exactly two pages: the table of contents
  and the table itself.
- `pdfplumber.find_tables()` returns exactly one table object on each target page.
- Body pages: Table 7 on 63, Table E.1 on 193, Table E.2 on 194.

## Document identity

New module `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/identity.py`,
exporting the anchors and page expectations consumed by `StandardRecipe`.

`identify_standard` already computes the SHA-256 before extraction, reads metadata and
first-page text, and refuses an ambiguous match. Three changes are needed:

1. `StandardRecipe.matches_identity` at
   `src/insulation_coordination/rules/importer/identify.py:183` hardcodes an
   `IEC 60664-([14])` claim regex. Replace it with a per-recipe
   `identity_claim_pattern` so each recipe declares the family it must not be confused
   with. The 62477 recipe declares a pattern matching `IEC 62477-1` followed by a year,
   so a 2012 document produces a claim of `("IEC 62477-1", "2012")`, which differs from
   the recipe's declared `("IEC 62477-1", "2022")` and fails the match.
2. A 2012 or mixed-edition document must fail with a message naming the failed check,
   not the generic "not a recognized supported IEC edition". Add
   `UnsupportedEditionError(UnsupportedStandardError)` carrying the detected standard and
   edition, raised when a claim matches the recipe's standard but not its edition.
3. The detected identity is already returned as `StandardIdentity` and shown before
   extraction by the Rule Manager. Extend the Rule Manager identity line so it lists all
   loaded documents, not the first one.

The recipe declares `expected_page_count = 522` with no accepted alternatives until a
second print run is observed. Page-count mismatch alone does not reject the document
when the metadata anchors identify it, which is the behaviour already implemented.

## Anchor location without a fixed page number

Issue #34 requires an expected page neighbourhood rather than a hard page number.

`TableAuditSpec` and `TableSegmentSpec` gain one field:

```python
page_search_radius: int = Field(default=0, ge=0, le=5)
```

Location becomes: search pages `page_number - radius` through `page_number + radius` for
the title anchor. Exactly one page must carry it. Zero matches, or more than one, raises
a blocking review item naming the semantic ID and the searched range. The 62477 specs
use a radius of 2. Existing 60664 specs keep the default of 0 and behave as they do
today.

This is a smaller change than a document-wide search and it keeps the failure mode
loud: a table that has moved gets a review item, never a silently different table.

## Table 7

One raw grid on page 63, 13 rows by 7 columns. Header rows 0 to 4, data rows 5 to 11,
footnote row 12. Column 6 carries footnote markers on the data rows.

Table 7 becomes **two** `TableAuditSpec` entries over the same page and the same
segment, distinguished by `source_columns`, exactly as Tables F.8 and F.9 already share
page 76 of IEC 60664-1:

- `iec62477_2022.supply.impulse_by_system_voltage_ovc` — system-voltage axis plus the
  four overvoltage-category columns.
- `iec62477_2022.supply.tov_by_system_voltage` — system-voltage axis plus the temporary
  overvoltage column.

Splitting at the recipe level, not after projection, means the two rules carry their own
provenance, their own supported ranges, and their own review status. A consumer asking
for impulse can never accidentally read a TOV cell.

### Row axis

The row axis is a set of system-voltage bands, not single values. The axis takes each
band's upper bound as its value and selects with `ceiling`, which is how
`iec60664-1:f2-clearance` already handles impulse bands.

Data row 11 carries a text label in the axis column rather than a number. `TableColumnSpec`
already has an `axis_value` field for exactly this. The recipe declares the value
explicitly, and the review UI shows the raw text beside the declared value so the
maintainer confirms it rather than trusting it.

An explicit `SupportedRange` records the first and last band, so a query outside the
table's range fails rather than extrapolating.

### Interpolation

Issue #34 forbids inferring interpolation from ordered numeric rows. Table 7 must be
`interpolation="none"`.

`project_table` at `src/insulation_coordination/rules/importer/projection.py:149`
hardcodes `interpolation="linear"` for every table it projects. This is a live defect
for any non-interpolable table, not only for 62477. Fix it at the source: add
`interpolation: Literal["none", "linear"]` to `TableAuditSpec`, default `"none"`, and
have both projection paths read it. The four existing 60664 specs declare `"linear"`
explicitly, preserving today's behaviour. That is one guard in the shared function
rather than a special case for the new recipe.

### Suffixes and footnotes

The data cells carry footnote markers. The recipe declares `allowed_suffixes`, and the
existing parser already separates value from suffix into `RawGridCell.suffix` and
`footnotes`. Any suffix outside the declared set is a blocking review item. Footnote row
12 is declared as a `footnote_rows` entry so it is never mistaken for data.

## Tables E.1 and E.2

Both project into the single semantic ID
`iec62477_2022.altitude.test_voltage_correction`, as two tables under one inventory item,
because the inventory item names the pair.

- E.1, page 193: 13 rows by 3 columns. Header row, 11 numeric data rows, footnote row.
- E.2, page 194: 22 rows by 5 columns. Two title rows, a header row carrying suffixes,
  18 numeric data rows, footnote row.

Both are clean rectangles and need no new machinery beyond the interpolation field.

Validation specific to altitude, enforced by tests rather than by extraction: altitude
correction must not modify a source impulse or TOV value. In this slice that means the
altitude tables are projected as standalone rules with no formula linking them to the
Table 7 outputs. The clearance and test-stage application is slice C and slice D work.

## Package composition

`_REQUIRED_RECIPES` at `src/insulation_coordination/rules/importer/extract.py:48` gains
`"iec62477-1-2022"`. Import now requires all three PDFs together, and the manifest lists
three source documents with three hashes.

The error message when a part is missing is currently hardcoded to name IEC 60664-1 and
IEC 60664-4 in two places. Generate it from `_REQUIRED_RECIPES` instead, so the message
cannot drift from the constant again.

## Private tests

This is the first slice that needs the licensed PDF, so the private harness is fixed
here.

`tests/private/test_supplied_standards.py` currently hardcodes filenames such as
`"IEC 60664-1 2020 isbn13 9782832282878.pdf"`. Replace filename matching with discovery:
scan `ICC_PRIVATE_STANDARDS_DIR` for `*.pdf`, run `identify_standard` on each, and select
one document per required recipe id. A directory that yields two documents for the same
recipe, or none for a required one, skips with a message naming what is missing. This
matches how the application itself identifies documents and removes a class of silent
skips.

New private tests:

- `tests/private/test_iec62477_identity.py` — the supplied 2022 PDF identifies as
  `IEC 62477-1` / `2022` with a stable SHA-256; a truncated copy fails to read; a
  2012 document, when present, raises `UnsupportedEditionError`.
- `tests/private/test_iec62477_numeric_tables.py` — Table 7 and Tables E.1 and E.2
  locate, extract, and project; the two Table 7 rules carry disjoint cells; every
  projected cell carries page, clause, table, row and column provenance; a second
  extraction run over the same PDF produces identical content checksums.

Expected values live only in the private rules directory, never in the repository.

## Public tests

All synthetic. `tests/rules/importer/iec62477_2022/`:

- `test_identity.py` — a synthetic PDF carrying 2022 anchors identifies; one carrying
  2012 anchors raises `UnsupportedEditionError`; one carrying both raises
  `AmbiguousStandardError`; the existing 60664 recipes still identify unchanged.
- `test_page_search_radius.py` — an anchor one page from its declared position is
  located; an anchor absent from the window raises a blocking review item; an anchor
  present twice in the window raises a blocking review item.
- `test_interpolation_declaration.py` — a spec declaring `"none"` projects a table that
  refuses interpolated lookup; the 60664 specs still project `"linear"`.
- `test_table7_split.py` — two specs over one synthetic grid produce two tables with
  disjoint cells and independent supported ranges.
- `test_required_recipes.py` — importing two of the three parts fails with a message
  naming the missing part, generated from the constant.

## Out of scope

- Tables 2, 3, 8, 9, 26 through 30.
- Blank-cell classification.
- Any prose clause, decision, procedure, or guidance content.
- The completeness dashboard and inventory-driven approval gates.
- Consumer queries for issues #35, #36 and #37.

## Definition of done

- `uv run ruff check .`, `uv run mypy`, and `uv run pytest` all pass.
- The private suite passes against the supplied PDFs in the licensed environment.
- Importing the three PDFs produces a draft whose manifest lists three source documents
  with three distinct hashes.
- Table 7 and Tables E.1 and E.2 appear as reviewable raw grids in the Rule Manager with
  full provenance.
- Re-running extraction on the same three PDFs reproduces identical content checksums.
- No licensed value, heading, note, or clause text appears in any committed file.
