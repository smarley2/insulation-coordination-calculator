# IEC 62477-1:2022 remaining procedures and Issue #34 closure (Slice E2)

Issue: [#34](https://github.com/smarley2/insulation-coordination-calculator/issues/34), final slice.
Date: 2026-08-10. Follows Slice E1.

## Purpose

Slice E2 extracts the last five required source items, empties the deferred set, and
demonstrates Issue #34's Definition of Done end to end. It is the only slice permitted to
close #34, and only if that demonstration passes.

## Existing foundation

E2 changes no mechanism. Everything it needs exists:

- `ProcedureRule`, `DecisionRule`, `GuidanceRule` in `domain/rules.py`;
- recipe-declared `grid_projectors` and `clause_projectors`;
- `comparison_only` and `text_field_table` spec kinds;
- the cross-standard comparison and its review artifact;
- `package_expectations` as the single derivation the five gates consult;
- session-scoped licensed fixtures, and a green baseline of 18 passed, 1 skipped.

## Source structure

Measured from the maintained printing; bounding boxes are measured at implementation time.

| Content | Clause | PDF page | Shape |
| --- | --- | --- | --- |
| Test cross-reference matrix | 5.2.2 | 113, 114 | 36 and 22 rows x 6 columns |
| Working-voltage determination | referred from 4.4.7.1.2 | 142 | paragraph |
| Internal SPD monitoring test | 5.2.3.15 | 142 | paragraph |
| Preconditioning of material | 5.2.3.16 | 143 | paragraph |
| Preconditioning, general | 5.2.3.1 | 123 | paragraph |
| Accessible insulating surface, foil | 5.2.3.4.4 | 130 | paragraph, no figures |
| Assembled-equipment routine exemption | 5.2.3.1, 5.2.3.4 | 123, 125 | paragraph |

## Test classification comes from the matrix, not from a table title

The cross-reference matrix states, per requirement, which test applies and whether it is a
type, sample, or routine test. E2 extracts it as a `comparison_only` grid and cross-checks
every procedure's declared classification against it. A procedure whose classification
disagrees with the matrix produces a blocking review item.

This lands **first**, so the four procedures below have their classification validated as
they are written rather than retrofitted. Table 30, delivered in E1, deliberately declares
no classifications for exactly this reason: the fact lives in the matrix.

The matrix is comparison-only because it duplicates what the procedures carry; it is
evidence, not a rule the calculator executes.

## Semantic rules

Each is a `ProcedureRule`, with a `DecisionRule` for applicability wherever the source gates
the test. Inputs and outputs are neutral author-written names.

### `iec62477_2022.test.working_voltage_determination`

Inputs: the quantity kind sought and the measurement condition. Outputs name which
measurement applies. No arithmetic is projected unless the source states it; a NOTE becomes
guidance.

### `iec62477_2022.test.internal_spd_monitoring`

Clause 5.2.3.15, gated by the SPD decision Slice D already extracted. This rule references
that decision by ID rather than restating its conditions, so one source clause stays one
rule.

### `iec62477_2022.test.preconditioning`

Two routes under one required item, decided by the maintainer after extraction blocked on a
genuine disagreement between the sources. The general clause names two preconditioning
clauses and governs the electrical tests; clause 5.2.3.16 enumerates three stages and
governs the solid-insulation and material requirements; Table 26 states no inventory of its
own and defers to the general clause. The two gates differ legitimately, so one identifier
cannot carry both readings:

- `…preconditioning.electrical_tests`, from the general clause;
- `…preconditioning.material`, from clause 5.2.3.16.

The applicability decision selects between them, and its material rows are keyed to the
specific requirements 5.2.3.16 names as invoking it — not to a broad "material" label, which
would make that clause universal. Each route still blocks when its own inventory is not the
reviewed shape, and Table 26's row must still defer rather than state an inventory.

### `iec62477_2022.test.accessible_surface_foil`

Grounded solely in clause 5.2.3.4.4, the accessible-surface rule inside the AC/DC voltage
test: a non-conductive accessible surface is wrapped in conductive foil, the insulation test
is performed, and the routine test may become a sample test. That substitution is modelled
as a conditional permission on the gate, because the matrix classifies the general AC/DC
voltage test as type and routine with no sample classification.

This family carries **no** figure reference and no foil geometry. The metal foil in the
thin-sheet mandrel clause is an unrelated requirement — a specimen foil for an
electric-strength verification after mechanical conditioning — and belongs to the thin-sheet
procedure, which is not one of the twenty-five required items and is not extracted. An
earlier draft of this slice grounded the family in that clause because it is the foil the
matrix names; the accessible-surface foil sits in a sub-clause the matrix does not list.

### `iec62477_2022.test.assembled_routine_exemption`

A `DecisionRule` over whether a test performed on a component before assembly exempts the
assembled equipment. Inputs: what was tested, when, and against which requirement. An
unsupported combination fails explicitly; the rule is not exhaustive and never defaults to
exempt.

## Two corrections carried from earlier slices

**Check identifiers get their own namespace.** A cross-standard check ID is currently a
suffix of the semantic ID it compares, so `inventory_report`'s route matching reads a check
as a route of the rule. It is harmless while those items resolve, but an unresolved check
would block the rule it exists to support. E2 moves check IDs out of the rule namespace and
adds the test that would have caught it.

**A text field table must declare its projector at import time.** `package_expectations`
raises when it reads an invalid combination, which is late: the recipe author should be
stopped when the spec is constructed. E2 adds that validator to `TableAuditSpec`.

## Package closure

`DEFERRED_SEMANTIC_IDS` becomes empty. The existing build-time coverage test then widens
from twenty items to all twenty-five with no code change, and the Rules Manager's inventory
counts reach twenty-five of twenty-five because they already read the inventory.

No new gate is added. The inventory gate refuses any draft missing these five items the
moment their recipes exist, which is the intended behaviour.

## End-to-end verification

One private test carries the Definition of Done: extract from the three licensed PDFs,
resolve every review item, approve, export a private `.icrules` package, re-import it, query
all twenty-five semantic IDs, and execute one representative request per consumer issue —
DVC guidance for #35, an impulse and TOV derivation for #36, a test-procedure lookup for #37.

It requires a local `tesseract` binary, because the curve rules are part of the package and
their OCR path has no offline substitute. The environment used for this work has it at
`C:\Users\fpo01\AppData\Local\Programs\Tesseract-OCR`.

## Risks

The classification cross-check may find genuine disagreements between the matrix and a
table. That is a finding to record, not a reason to relax the check.

The end-to-end is the first test to exercise export and re-import with procedures and
comparison-only grids present. Slices D and E each found gates that assumed older content
kinds; the archive layer has not yet been exercised with these. Expect it to surface
something, and treat that as the test doing its job.

## Closure rule

Only E2's pull request may use `Closes #34`, and only if the end-to-end passes. If it does
not, the pull request states plainly what was demonstrated and what was not, and #34 stays
open.

## Out of scope

Consumer calculations in #35 to #37. IEC 62477-1:2012 behaviour. Renaming the IEC 60664-4
identifiers that spell band figures, still an open decision. Comparing Tables 8 and 9
against IEC 60664-1, tracked separately. Import performance.

