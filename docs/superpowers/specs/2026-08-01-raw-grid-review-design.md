# Raw PDF Grid Review Design

## Goal

Make IEC PDF extraction review safe and usable before an `.icrules` package can
be approved. Maintainers must see every extracted table, inspect ambiguous data
cells, correct or explicitly accept each flagged value, and only then build the
typed rule content.

## Scope

This change adds an extracted-grid editor to Rules Manager. It does not embed a
PDF page viewer. The existing standard, clause, table, page, row, and column
references remain visible so the maintainer can compare values against the PDF
in an external viewer.

## Workflow

1. Import both recognized IEC PDFs. The draft contains six raw grids, 57 typed
   content requirements, 57 definition review items, and 57 raw-cell review
   items for the supplied PDFs.
2. Open `Review extracted tables…`.
3. Select one raw grid. The editor shows the complete grid using the extracted
   raw text. Numeric cells show their parsed value; flagged cells are visually
   distinct and expose the full source reference.
4. For each flagged cell, keep the extracted numeric value or enter a corrected
   decimal value. Empty, non-finite, or non-decimal corrections are rejected.
5. `Accept table` records corrections and resolves only the raw-cell review
   items belonging to that grid. Accepting the table is the explicit human
   confirmation for unchanged ambiguous values.
6. `Build reviewed content…` remains disabled until all raw-cell review items
   are resolved. It then reconstructs the six tables, ten formulas, and 41
   mappings and resolves their definition review items, except formulas that
   still contain placeholder constants.
7. `Review formula constants…` requires real user input for four formula
   definitions. Placeholder values are not prefilled.
8. Approval becomes available only when all 114 review items are resolved.

## UI Design

Rules Manager gains one `Review extracted tables…` button beside the existing
review actions. It opens a modal dialog containing:

- a raw-grid selector with semantic ID and source table;
- a `QTableWidget` showing every extracted cell;
- cell styling for numeric, ambiguous, text, and blank extraction states;
- a details label showing raw text, parsed value, parse status, and source;
- an editor for the selected flagged cell's decimal value;
- `Apply value`, `Accept table`, and `Close` actions; and
- per-grid progress plus total unresolved raw-cell count.

Only cells represented by `MANUAL_RAW_CELL_REVIEW_REQUIRED` items are editable.
Other cells remain read-only context. Selecting a flagged cell loads its parsed
value into the editor. Applying a value replaces that cell with a numeric cell,
clears its qualifier and suffix, and keeps its source reference. Accepting a
table records one correction containing all edits and resolves every flagged
cell in that table.

## Data Flow

A focused domain helper updates a `RawGridCell` in an immutable
`ImportedRuleDraft` and calls `record_correction` with the raw-cell review items
accepted for one grid. The dialog never mutates Pydantic models in place.
`RulesManagerWindow` receives the returned draft through `set_draft`, so all
existing counters and approval gates refresh through one path.

`build_reviewed_draft` stops resolving raw-cell items automatically. It rejects
construction while unresolved raw-cell items exist, then resolves only the
deterministically reconstructed table, formula, and mapping definition items.

## Validation and Errors

- Corrections must parse as finite `Decimal` values.
- A table cannot be accepted if any flagged cell lacks a numeric parsed value.
- Building typed content with unresolved raw-cell items produces a clear error.
- Formula constant fields start empty and each requires the exact literal count
  expected by its expression.
- Canceling either dialog leaves the draft unchanged.
- No PDF contents or extracted values are written outside the existing private
  draft/package flow.

## Tests

Domain tests cover editing and accepting one grid, preservation of source data,
resolution scoping, invalid decimal rejection, and the build gate. Qt tests
cover grid visibility, flagged-cell editing, per-table acceptance, action
enablement, empty formula fields, exact literal counts, and approval gating.
The real-PDF private test remains the end-to-end extraction check when licensed
standards are available.

## Success Criteria

- Maintainer can inspect all six extracted tables before typed content is built.
- No raw-cell review item is resolved without an explicit `Accept table` action.
- Typed content cannot be built while any raw-cell item is unresolved.
- Formula placeholders cannot be accepted accidentally.
- Final counts reach 57/57 present and 114/114 resolved only after both review
  stages complete.
