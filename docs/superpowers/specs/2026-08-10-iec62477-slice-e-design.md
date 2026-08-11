# IEC 62477-1:2022 verification procedures and package closure (Slice E)

Issue: [#34](https://github.com/smarley2/insulation-coordination-calculator/issues/34),
the final slice, after Slice D.
Date: 2026-08-10.

## Purpose

Slice E extracts the IEC 62477-1:2022 verification content Issue #37 consumes and closes
Issue #34: the last ten required source items, the completeness gate with an empty deferred
set, and the end-to-end demonstration the issue's Definition of Done requires — extract from
the licensed PDF, review, approve, export, re-import, and query every semantic ID.

The public repository keeps generic extraction code, structural locators, neutral semantic
identifiers, and synthetic fixtures. Licensed values, headings, notes, and clause wording stay
in private draft artifacts, private tests, and approved private `.icrules` packages.

## Existing foundation

Slice E extends the merged Slices A through D. In particular it reuses, unchanged:

- the recipe-declared projector registry (`grid_projectors`, `clause_projectors`);
- `ProcedureRule`, `DecisionRule`, and `GuidanceRule`, already in `domain/rules.py`;
- the `comparison_only` and `row_strategy` spec fields Slice D added;
- `inventory_report` and the approval gate driven by `REQUIRED_SOURCE_ITEMS`;
- the clause-fragment extraction and `AMBIGUOUS_CLAUSE_STRUCTURE` failure convention.

No schema bump is required.

## Source structure

Measured from the maintained 2022 printing:

| Content | Clause | PDF page | Raw shape |
| --- | --- | --- | --- |
| Table 26 | 5.2.3.2 | 124 | 20 rows x 4 columns |
| Table 27 | 5.2.3.2 | 125 | 12 rows x 6 columns |
| Table 28 | 5.2.3.4.2 | 127 | 10 rows x 5 columns |
| Table 29, first segment | 5.2.3.4.2 | 127 | 16 rows x 5 columns |
| Table 29, second segment | 5.2.3.4.2 | 128 | 9 rows x 5 columns |
| Table 30 | 5.2.3.5 | 131 | 13 rows x 2 columns |
| Test cross-reference matrix | 5.2.2 | 113-114 | 36 and 22 rows x 6 columns |
| Preconditioning, general | 5.2.3.1 | 123 | paragraph |
| Preconditioning of material | 5.2.3.16 | 142 | paragraph |
| Internal SPD monitoring test | 5.2.3.15 | 142 | paragraph |
| Working-voltage determination | 5.2.3.16 area, referred from 4.4.7.1.2 | 142 | paragraph |
| Accessible insulating surface, metal foil | 5.2.3.4.3 and 142 | 130, 142 | paragraph, Figures 23 and 24 |
| Assembled-equipment routine exemption | 5.2.3.1, 5.2.3.4 | 123, 125 | paragraph |

Every bounding box is measured at implementation time. Page numbers, clause and table
identifiers, row and column counts, and footnote markers are structural; source headings,
values, and prose are not copied into public code.

Two structural facts shape the recipes:

- **Table 29 spans a page break.** Its two segments share one column structure, so one spec
  declares two `TableSegmentSpec` entries, exactly as the Table 7 pair already does.
- **Tables 26 and 30 are field tables, not numeric grids.** Each row is a subject and its
  test condition, so they project to `ProcedureRule`, not `Table`. Their subjects are source
  wording, so recipes address rows positionally and never carry the subject text.

## Semantic rules

### `iec62477_2022.test.impulse_procedure`

Table 26, projected as a `ProcedureRule`. Each source row becomes one typed field addressed
by its row index, with a neutral author-written name: test reference, requirement reference,
what is tested, preconditioning, waveform, polarity, number of applications, interval,
preparation, acceptance reference, and test classification. A row the recipe does not
declare blocks rather than being dropped, so a printing that adds a subject cannot pass
through unnoticed.

### `iec62477_2022.test.impulse_selection`

Table 27, a decision table. Its row axis is the system voltage, carried in parallel AC and DC
columns exactly as Table 7 carries them, so the spec splits into an AC route and a DC route
rather than mixing two quantities in one axis. The data columns select the test voltage; the
column axis is positional and neutral.

### `iec62477_2022.test.mains_dielectric_values` and `...non_mains_dielectric_values`

Tables 28 and 29. Both carry, per row, an AC RMS value and a DC value for each of two test
purposes, so each table splits into routes by purpose and by AC or DC, keeping type-test and
routine-test values in separate rules. Table 28's row axis is the system voltage; Table 29's
is the working voltage (recurring peak), and its two segments are declared as one spec.

The known-TOV formula path stays distinct from the no-TOV table lookup: where the source
gives a formula rather than a tabulated value, it is extracted as a reviewed formula, never
precomputed.

### `iec62477_2022.test.partial_discharge`

Table 30 as a `ProcedureRule`, plus a separate `DecisionRule` for applicability so a missing
engineering input yields an engineering-input-required outcome rather than a not-required one.
Material and thickness exemptions, the relation to impulse testing, and the high-frequency
review trigger are typed outputs, not prose.

### The four remaining procedures

Each is a `ProcedureRule` from its clause, with a `DecisionRule` for applicability where the
source gates the test:

- `iec62477_2022.test.working_voltage_determination` — inputs are the quantity kind and the
  measurement condition; outputs name which measurement applies. No arithmetic is projected
  unless the source states it.
- `iec62477_2022.test.internal_spd_monitoring` — clause 5.2.3.15, gated by the SPD decision
  Slice D already extracted, which this rule references by ID rather than restating.
- `iec62477_2022.test.preconditioning` — the general clause, the material clause, and Table
  26's own preconditioning row must agree; a disagreement is a blocking review item rather
  than a precedence rule invented here.
- `iec62477_2022.test.accessible_surface_foil` — topology and procedure, including the foil
  geometry and placement the source figures define. Figure references are retained as source
  references; no figure is digitized, because the geometry is stated in the clause text.

### `iec62477_2022.test.assembled_routine_exemption`

A `DecisionRule` over whether a test performed on a component before assembly exempts the
assembled equipment. Inputs: what was tested, when, and against which requirement. The
outcome is explicit; an unsupported combination fails rather than defaulting to exempt.

## Test classification comes from the document

The cross-reference matrix on pages 113 and 114 states, per requirement, which test applies
and whether it is a type, sample, or routine test. Slice E extracts it as a comparison
source for the `test_classification` field of every procedure above: a procedure whose
declared classification disagrees with the matrix produces a blocking review item. This
prevents a classification being inferred from a table title.

The matrix is extracted as a `comparison_only` grid, the mechanism Slice D added, because it
duplicates information the procedures carry rather than being a rule the calculator executes.

## Package closure

- `DEFERRED_SEMANTIC_IDS` becomes empty. The existing test that every deferred identifier is
  a required item then holds trivially, and the build-time coverage test widens from the
  Slice D subset to all twenty-five items with no code change.
- The Rules Manager panel needs no new field: its counts already read the inventory, so they
  reach twenty-five of twenty-five when this slice lands.
- Approval gains no new gate. The inventory gate Slice D added starts refusing any draft
  missing these ten items the moment their recipes exist, which is the intended behaviour.

## End-to-end verification

One private test carries the Definition of Done: extract from the three licensed PDFs, resolve
every review item, approve, export a private `.icrules` package, re-import it, and query every
one of the twenty-five semantic IDs, executing one representative request per consumer issue —
DVC guidance for #35, an impulse and TOV derivation for #36, and a test-procedure lookup for
#37.

This test requires a local `tesseract` binary, because the curve rules Slice C digitizes are
part of the package and their OCR path has no offline substitute. Without it the run cannot
demonstrate the Definition of Done, and the final pull request must not claim it.

## Delivery

Two pull requests, both `Refs #34` until the last one:

- **E1** — Tables 26 through 30: the impulse procedure, the impulse selection table, both
  dielectric-value tables, and the partial-discharge procedure.
- **E2** — the four remaining procedures, the assembled-equipment exemption, the
  classification cross-check, the empty deferred set, and the end-to-end test. Only this pull
  request may use `Closes #34`, and only if the end-to-end run passes.

## Out of scope

Consumer calculations in Issues #35 through #37. Any IEC 62477-1:2012 behaviour. Renaming the
IEC 60664-4 identifiers that spell out band figures, still an open decision. Comparing Tables
8 and 9 against IEC 60664-1, which Slice D deferred and which is tracked separately.

## Risks

Table 26 has twenty rows and Table 30 thirteen, each a subject and a condition. The risk is
not extraction but modelling: a field named for what the author assumes a row means, rather
than for what the row is, would mislead every consumer. Field names are therefore positional
first, with the neutral description second, and the private test asserts each field resolves
to the row index the recipe declares.

The classification cross-check may find genuine disagreements between the matrix and a table.
That is a finding to record, not a reason to relax the check.
