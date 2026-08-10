# IEC 62477-1:2022 supply, spacing, and high-frequency extraction (Slice D)

Issue: [#34](https://github.com/smarley2/insulation-coordination-calculator/issues/34),
slice D after the merged foundation, identity/numeric-table, and DVC/curve slices.
Date: 2026-08-10.

## Purpose

Slice D extracts the IEC 62477-1:2022 content Issue #36 consumes: how the system voltage is
resolved, how impulse requirements propagate between supplies and across galvanic barriers,
what a transient-limiting device permits, the clearance and creepage tables, and when a
high-frequency evaluation applies. It closes eight of the twenty-five required source items.

The public repository keeps generic extraction code, structural locators, neutral semantic
identifiers, and synthetic fixtures. Licensed values, headings, notes, and clause wording stay
in private draft artifacts, private tests, and approved private `.icrules` packages.

## Existing foundation

This slice extends the merged work described by:

- `2026-08-07-iec62477-foundation-design.md`;
- `2026-08-07-iec62477-identity-and-numeric-tables-design.md`; and
- `2026-08-08-iec62477-slice-c-dvc-and-curves-design.md`.

The schema, review lifecycle, approval gates, `TableAuditSpec`/`ClauseAuditSpec` contracts,
raw-grid and clause-fragment extraction, and the deterministic archive remain unchanged. No
schema bump is required: `DecisionRule`, `CompatibilityMapping`, `Table`, and `GuidanceRule`
already carry everything this slice projects.

## Source structure

Structural locators for the Slice D content, all in the maintained 2022 printing:

| Content | Clause | PDF page | Raw shape |
| --- | --- | --- | --- |
| System voltage, mains | 4.4.7.1.7.1 | 63 | bullet list |
| System voltage, non-mains | 4.4.7.1.7.2 | 64 | paragraph |
| SPD monitoring | 4.4.7.2.2 | 65 | paragraph |
| Reduction downstream of a limiter, mains | 4.4.7.2.3 | 65 | paragraph |
| Reduction downstream of a limiter, non-mains | 4.4.7.2.4 | 65–66 | paragraph |
| Both supplies, one level of transfer | 4.4.7.2.5 | 66 | lettered alternatives |
| No galvanic isolation, combined circuit | 4.4.7.2.5 tail | 67 | paragraph |
| High-frequency isolating transformer | 4.4.7.2.6 | 67 | paragraph |
| Insulation between circuits | 4.4.7.2.7 | 67 | bullet list |
| Table 8 | 4.4.7.4 | 68 | 15 rows x 7 columns |
| Above 2 000 m and above the frequency threshold | 4.4.7.4.3 | 69 | paragraph |
| Table 9 | 4.4.7.5 | 71 | 15 grid rows x 12 columns |
| Annex F general | F.1 | 195 | paragraph plus bullet list |
| Table F.1 | F.2.2 | 197 | 10 rows x 2 columns |
| Table F.2 | F.2.3 | 197 | 5 rows x 2 columns |
| Table F.3 | F.3 | 199 | 21 rows x 8 columns |

Page numbers, table identifiers, clause numbers, row and column counts, bounding boxes, and
footnote marker characters are structural. Every bounding box is measured from the document at
implementation time, never estimated. Source headings and values are not copied into public
code; column headings in recipes are neutral descriptions written by the author, and any axis
value belonging to the source table is read through `TableColumnSpec.axis_value_source_row`.

Two frequency thresholds govern this slice — the isolating-transformer threshold in 4.4.7.2.6
and the Annex F threshold in F.1 and 4.4.7.4.3. Both are licensed table-class values and are
extracted from the document at import time. Neither appears as a literal in a recipe, a
semantic identifier, or a test fixture.

## Cross-standard comparison

Annex F states that the design for frequencies above its threshold follows IEC 60664-4:2005
together with IEC 60664-1:2020, and Tables 8 and 9 carry referrals to IEC 60664-1:2020 tables.
The approved package already contains reviewed IEC 60664-1 and IEC 60664-4 rules, so this slice
must not add a second copy of the same numbers, and must not assume equivalence either.

A new module `rules/importer/crosscheck.py` provides one deterministic comparison used by both
call sites:

```python
class CrossStandardCheckSpec(FrozenModel):
    id: Identifier
    source_rule_id: Identifier      # the IEC 62477-1 grid
    target_rule_id: Identifier      # the already-reviewed rule in the same draft
    family: Identifier
    cell_map: tuple[tuple[Identifier, Identifier], ...]   # source cell -> target cell
    source: SourceReference

def compare_across_standards(
    draft: ImportedRuleDraft, spec: CrossStandardCheckSpec
) -> tuple[CompatibilityMapping | None, tuple[ImportReviewItem, ...]]: ...
```

Outcomes:

- every mapped cell compares equal, and no mapped cell is missing: return an unapproved
  `CompatibilityMapping` and no review item, and do not project a duplicate 62477 rule;
- any mapped pair differs, any mapped cell is absent, or the two grids disagree in shape:
  return no mapping and one `ImportReviewItem` per divergence, naming the coordinates. The
  62477 content stays as its own rule until the maintainer resolves the item.

The comparison reads only content already inside the draft. It never re-parses a PDF, so it is
reproducible for a given draft and adds no source-document dependency.

Both drafts are present because one package carries all three source documents; the private
manifest test already asserts that.

## Semantic rules

### `iec62477_2022.clearance.requirements`

Table 8, one raw grid. Header rows carry the column-number row, the merged title row, the
pollution-degree spanner, and the pollution-degree axis row; the data rows follow; the final row
is a note. Column roles: an impulse-withstand row axis, a temporary-overvoltage column, a
working-voltage column, and one clearance column per pollution degree whose axis value is read
from the declared header row.

Blank cells inside the clearance columns are not guessed. Each one that the maintainer has not
already classified produces a blocking review item offering the classifications the issue
defines — explicit not-applicable, inherited or continued value, reference to another rule,
intentionally blank, or extraction failure. Once classified, the classification lives in the
recipe as a `BlankCellSpec`, the same way Table 2 records its own.

The clause referrals for out-of-range values, homogeneous fields, and altitude become
`CrossStandardCheckSpec` entries against the reviewed IEC 60664-1 rules, not copied numbers.

### `iec62477_2022.creepage.requirements`

Table 9, one raw grid whose detected shape is 15 rows by 12 columns. Two of those columns are
artifacts of merged header spans and are excluded through the segment's `source_columns`. Each
data cell packs several logical rows as a newline-separated stack, so normalization splits the
stacks and requires an equal count across every data column of a row group; an unequal count is
blocking. The working-voltage axis comes from column 0, split the same way.

The table permits interpolation, unlike Tables 7 and 8. The projected rule therefore sets
`interpolation="linear"` explicitly, and a test asserts the three tables do not share a default.

### `iec62477_2022.high_frequency.applicability`

A decision rule from F.1 and 4.4.7.4.3. Inputs: `working_voltage_frequency_hz`,
`insulation_kind`, `stress_kind`. Outputs: `high_frequency_evaluation_required` (boolean),
`applicable_design_situations` (categorical, the four Annex F situations), and
`governing_result` (categorical: the greater of the two investigations). The frequency
thresholds are extracted quantities, and a frequency above the upper bound of the annex's scope
yields an engineering-review outcome rather than a silent pass.

Impulse-driven and temporary-overvoltage-driven spacings remain governed by 4.4.7.4, which the
rule states as an explicit output rather than leaving to the consumer.

### Annex F tables

Tables F.1 and F.3 are extracted as raw grids for comparison only and compare against
`iec60664-4:hf-clearance-table` and `iec60664-4:hf-creepage-table`. Table F.2 has no counterpart
among the approved IEC 60664-4 rules, so it is projected as a 62477-owned table with no mapping;
that absence is recorded in the recipe as a comment, not silently.

### `iec62477_2022.supply.system_voltage_resolution`

A decision rule over the branches in 4.4.7.1.7.1 and 4.4.7.1.7.2. Inputs: `supply_kind`,
`phase_system`, `earthing_arrangement`, `input_topology`, `calculation_purpose`. The single
output `system_voltage_measure` is categorical — it names which voltage the consumer must use,
for example a phase-to-earth RMS value or an RMS value taken ahead of a rectifier. No arithmetic
is projected: the source's division-by-root-three sentence is a NOTE, so it becomes a
`GuidanceRule` attached to the branch, never a formula. The impulse and temporary-overvoltage
branches stay separate rows, because the source treats them differently for one phase system.

An input combination the source does not cover fails explicitly rather than falling through to a
default row; the rule is not exhaustive.

### `iec62477_2022.supply.multiple_source_propagation`

The lettered alternatives of 4.4.7.2.5. Inputs: `evaluated_side`, `mains_overvoltage_category`,
`non_mains_overvoltage_category`, `galvanic_isolation_present`. Named outputs:
`source_requirement`, `transferred_requirement`, and `governing_requirement`. The transfer is one
category level and is evaluated in both directions; the governing value is the more severe of the
side's own requirement and the transferred one.

### `iec62477_2022.supply.verified_barrier_transfer`

The isolation and no-isolation paths of 4.4.7.2.5 and 4.4.7.2.7. Inputs:
`galvanic_isolation_verified`, `isolation_evidence_kind`, `downstream_connection_kind`. Outputs:
`transfer_permitted`, `combined_circuit_requirement`, and `propagates_to_connected_circuits`.
Without verified isolation, the combined-circuit requirement is the more severe of the two sides
and propagates to every circuit connected without isolation.

### `iec62477_2022.supply.spd_reduction_requirements`

4.4.7.2.2 plus the reduction paragraphs of 4.4.7.2.3, 4.4.7.2.4, and 4.4.7.3. Inputs:
`device_placement`, `insulation_class`, `device_degradable`, `part_of_category_reduction`.
Outputs: `reduction_permitted`, `reduced_category`, `monitoring_required`,
`status_indication_required`, `verification_reference`, and `reinforced_floor_applies`. The floor
that forbids reducing double or reinforced insulation below the unreduced basic requirement is a
typed output, not warning text. The exemption for devices outside a category reduction is its own
row.

### `iec62477_2022.supply.hf_transformer_attenuation`

4.4.7.2.6. Inputs: `circuit_dvc`, `transformer_frequency_hz`, `isolation_provided`,
`attenuation_evidence_kind`. Outputs: `working_voltage_basis_permitted` and
`required_evidence_kinds` (test, simulation, or calculation). Without evidence, the outcome is an
engineering-input requirement, never a permission.

## Projection dispatch

`build_reviewed_draft` and `required_content_report` in `rules/importer/review.py` currently
branch on IEC 62477 semantic identifiers with `if`/`elif` chains and a hard-coded decision-route
dictionary. Slice D would add eight more branches to generic code that should not know any
standard's identifiers.

This slice moves that knowledge to the recipe. `StandardRecipe` gains two mappings, and
`TableAuditSpec` gains one field:

```python
GridProjector = Callable[[RawGrid, StandardIdentity], tuple[tuple[RuleObject, ...], tuple[SemanticProposal, ...]]]
ClauseProjector = Callable[[RawClauseFragment, StandardIdentity], tuple[tuple[RuleObject, ...], tuple[SemanticProposal, ...]]]

class StandardRecipe(FrozenModel):
    ...
    grid_projectors: Mapping[Identifier, GridProjector] = {}
    clause_projectors: Mapping[Identifier, ClauseProjector] = {}
    cross_standard_checks: tuple[CrossStandardCheckSpec, ...] = ()

class TableAuditSpec(FrozenModel):
    ...
    decision_route_ids: tuple[Identifier, ...] = ()
```

`review.py` then dispatches by lookup: a spec with a registered projector is projected through
it, a spec without one goes through `project_table`, and a clause spec with no registered
projector is a recipe error at import time rather than a runtime `ValueError`. Existing
behaviour for Slices A through C is preserved; the DVC and curve projections move into the
registry unchanged, and their route identifiers move onto their own specs.

This is the only refactor in scope. Nothing else in `review.py` changes.

## Package completeness from the inventory

`REQUIRED_SOURCE_ITEMS` is currently referenced only by its own test. This slice makes it the
authority the issue requires.

A new function in `rules/importer/review.py`:

```python
class InventoryStatus(FrozenModel):
    semantic_id: Identifier
    consumer_issue_ids: tuple[int, ...]
    located: bool
    extracted: bool
    typed: bool
    approved: bool
    deferred: bool

def inventory_report(draft: ImportedRuleDraft) -> tuple[InventoryStatus, ...]: ...
```

Each item resolves against recipe coverage and draft content: `located` when a recipe declares
the item, `extracted` when the draft holds its raw artifact, `typed` when a rule or the item's
declared decision routes exist, `approved` when the reviewed draft carries it with no unresolved
review item.

Slice E's ten `test.*` identifiers are declared in one frozen `DEFERRED_SEMANTIC_IDS` set in
`iec62477_2022/inventory.py`, reported as `deferred`, and excluded from the approval gate. A test
asserts every deferred identifier is a required inventory item, so the set cannot hide an
identifier that does not exist, and the set is expected to be empty when Slice E closes.

Approval fails when a required, non-deferred item is not approved. The Rules Manager's existing
required-content line gains the inventory counts beside it, per consumer issue, so the panel
shows how much of #35, #36, and #37 the current draft can serve.

## Identification robustness

`identify_standard` raises whatever the PDF layer raises when a document is malformed in a way
`_read_pdf` does not anticipate: a real unrelated PDF in the maintainer's standards folder raises
`KeyError: '/DescendantFonts'` out of text extraction. Identification must fail closed instead,
because the maintainer picks the file and the folder holds unrelated documents.

`_read_pdf` widens its caught set to include `LookupError`, so a missing key or index during
identification becomes `UnsupportedStandardError`. A public test feeds a synthetic PDF whose font
dictionary is incomplete and asserts `StandardIdentificationError`.

## Tests

Public, synthetic fixtures only:

- `tests/rules/importer/iec62477_2022/test_table8_recipe.py` — shape, blank-cell classification,
  footnote retention, pollution-degree axis read from the header row;
- `tests/rules/importer/iec62477_2022/test_table9_recipe.py` — stack splitting, unequal-stack
  blocking, span-artifact exclusion, interpolation flag;
- `tests/rules/importer/iec62477_2022/test_annex_f_recipes.py` — Annex F shapes, and F.2 having
  no mapping;
- `tests/rules/importer/test_crosscheck.py` — equal grids yield a mapping, one divergent cell
  yields a blocking item, shape mismatch yields a blocking item, absent target yields a blocking
  item;
- `tests/rules/importer/iec62477_2022/test_supply_clause_recipes.py` — one test per supply rule:
  branch coverage, unsupported combinations failing, guidance kept out of the arithmetic path,
  both propagation directions;
- `tests/rules/importer/iec62477_2022/test_high_frequency_applicability.py` — threshold read from
  the document, out-of-scope frequency yielding engineering review;
- `tests/rules/importer/iec62477_2022/test_inventory.py` — extended for the deferred set and the
  inventory report;
- `tests/rules/importer/test_identify.py` — the malformed-font case;
- `tests/rules/importer/iec62477_2022/test_slice_d_integration.py` — a synthetic document through
  extract, review, project, and gate.

Private, against the licensed PDF:

- extend `tests/private/test_iec62477_numeric_tables.py` with Tables 8, 9, F.1, F.2, F.3 shapes
  and provenance;
- new `tests/private/test_iec62477_slice_d_roundtrip.py`: extract, resolve, approve, export,
  re-import, and query all eight Slice D identifiers plus the cross-standard mappings;
- assert the two extracted frequency thresholds appear in no public file.

## Out of scope

Slice E content: Tables 26 through 30 and the five remaining test procedures. Consumer
calculations in Issues #35 through #37. Any IEC 62477-1:2012 behaviour. Renaming the IEC 60664-4
identifiers that spell out band figures; that decision is still open and is a breaking change.

## Implementation notes

Recorded after building the slice, where the documents required something the design above
did not anticipate.

**Table 9 needed a row strategy, not a splitting pass.** The table rules one box around
several working-voltage lines, so its ruling lines cannot separate logical rows and every
cell arrives holding three or six stacked values. Instead of a cell-splitting pass, a
segment declares that its rows come from text lines; that yields one grid row per working
voltage and no new normalization stage. Every other table keeps the line strategy. The
table is also split by construction rather than one spec, because it answers a four-way
question — construction, pollution degree, material group, working voltage — that two axes
cannot hold. The printed-wiring lookup covers the rows carrying values and leaves the
footnote stating its limit in the raw grid.

**Table 8's blanks fill down.** The source prints a clearance only where it changes, so a
blank repeats the last printed value in its own column. Recorded as inherited rather than
left to block, because the reading is checkable: after filling down, no row decreases
across the pollution degrees, asserted both publicly and against the document.

**Comparison-only grids.** A spec can declare that its grid is evidence for a
cross-standard check rather than an executable rule. Such a grid is never projected and its
cells are never flagged for numeric review — they are only ever read as the source printed
them, and a cell the parser cannot turn into a number could not be resolved at all. The
three Annex F grids are comparison-only.

**Notation versus requirement.** The IEC 62477-1 and IEC 60664-4 creepage tables agree on
every numeric cell but mark an inapplicable cell differently: one prints a dash, the other
leaves it empty. A check therefore declares the markers that mean "no requirement here".
Any other unparsed text remains a divergence, and blanks inside the data region are
compared rather than dropped.

**Cross-standard mappings are reviewable artifacts.** A produced mapping carries its own
review item and its source artifact is the pair of grids it compared, so a maintainer signs
the equivalence off and a change to either grid resets that review.

**Tables 8 and 9 against IEC 60664-1 are not yet compared.** The two documents' clearance
tables do not align cell for cell: IEC 60664-1 Table F.2 lists 26 impulse rows against
case A and case B for three pollution degrees, where Table 8 lists ten rows against four
pollution degrees, and pollution degree 4 has no counterpart there at all. An index-based
cell map would therefore assert correspondences the documents do not support. Comparing
them needs matching by axis value plus a way to declare a column with no counterpart, which
is left as follow-up work rather than approximated here. The Annex F comparisons, whose
grids do align, are implemented.

## Risks

The Table 9 stack splitting is the least certain part: if the licensed printing groups rows
differently from the current probe, the equal-count check blocks and the maintainer sees a review
item. That is the intended failure mode, but it means the private fixture must be run early, not
at the end of the slice.

The cross-standard comparison can only prove equivalence for the cells it maps. A partial cell
map that quietly compares a subset would be worse than no mapping, so `CrossStandardCheckSpec`
declares the source grid's data cells separately from the map and rejects, at construction, any
map that does not cover every one of them.
