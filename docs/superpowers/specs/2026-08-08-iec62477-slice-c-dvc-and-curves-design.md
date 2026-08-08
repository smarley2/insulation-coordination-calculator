# IEC 62477-1:2022 DVC and curve extraction (Slice C)

Issue: [#34](https://github.com/smarley2/insulation-coordination-calculator/issues/34),
slice C after the merged foundation and document/numeric-table work.
Date: 2026-08-08.

## Purpose

Slice C completes the IEC 62477 DVC rules needed by Issue #35 and resolves the known
Table 7 temporary-overvoltage limitation left by slices A and B. It adds:

- typed extraction and decision projection for Tables 2 and 3;
- generic clause and bullet extraction for non-tabular normative rules;
- deterministic digitization, review, approval, and evaluation of Figures 5 through 7;
- the executable semantic rule `iec62477_2022.dvc.fault_time_voltage`; and
- typed separation of the distinct quantities stored in each Table 7 TOV source cell.

The public repository contains only generic extraction code, structural locators, neutral
semantic identifiers, and synthetic fixtures. Licensed values, wording, curve coordinates,
screenshots, and reconstructed source figures remain in private draft artifacts, private tests,
and approved private `.icrules` packages.

## Existing foundation

This slice extends, rather than replaces, the merged work described by:

- `2026-08-07-iec62477-foundation-design.md`; and
- `2026-08-07-iec62477-identity-and-numeric-tables-design.md`.

The existing schema-v3 decisions, procedures, guidance, `Power` expression, source inventory,
AC/DC Table 7 split, review records, deterministic archive, and approval checks remain the
foundation. Table 7 impulse and TOV stay separate semantic families. AC and DC remain separate
routes.

## Source structure

The maintained IEC 62477-1:2022 source has these relevant structural locations:

- Table 2: PDF page 44, one 8-row by 6-column grid;
- Table 3: PDF page 45, one 9-row by 7-column grid;
- Figures 5, 6, and 7: PDF pages 54, 55, and 56; and
- the DVC determination and time-voltage applicability clauses in clause group 4.4.2.

Page numbers, table/figure identifiers, bounding boxes, row/column counts, and merged-cell
metadata are public structural locators. Source headings, labels, numeric values, notes, and
footnotes are not copied into public code.

The current licensed PDF stores Figures 5 through 7 as high-resolution `FlateDecode` image
XObjects. It exposes no path primitives for those plots. The extractor remains vector-first for
other printings, but uses the embedded image losslessly for this printing. It never traces a
rendered whole-page screenshot when the source XObject is available.

## Schema version 4

This slice bumps the rule schema and importer version once. Version 3 packages continue to fail
with the existing explicit rebuild requirement; no migration path is added.

### Execution state

`Formula`, `DecisionRule`, and the new curve rule gain `executable: bool = True`. Existing
approved rule construction remains executable by default. Imported semantic proposals set it to
`False`. Evaluators reject a non-executable rule. Approval rejects a required rule that remains
non-executable and rebuilds reviewed proposals with `executable=True` only after all blocking
items and dependencies resolve.

### Piecewise curves

Add first-class curve models to `domain/rules.py`:

```python
CurveAxisScale = Literal["linear", "log10"]
CurveInterpolation = Literal["linear", "log_x", "log_y", "log_log", "step_before", "step_after"]

class CurveAxis(FrozenModel):
    quantity_kind: Identifier
    unit: Identifier
    scale: CurveAxisScale
    minimum: DecimalValue
    maximum: DecimalValue

class CurvePoint(FrozenModel):
    x: DecimalValue
    y: DecimalValue
    source_x: int
    source_y: int

class CurveSegment(FrozenModel):
    start: int
    end: int
    interpolation: CurveInterpolation

class FaultTimeVoltageVariant(FrozenModel):
    id: Identifier
    subject: Literal["accessible_circuit", "conductive_accessible_part"]
    voltage_basis: Literal["ac_rms", "ac_peak", "dc"]
    dvc_context: tuple[Identifier, ...]
    environment_context: tuple[Identifier, ...]
    x_axis: CurveAxis
    y_axis: CurveAxis
    points: tuple[CurvePoint, ...]
    segments: tuple[CurveSegment, ...]
    applicability: ApplicabilityText
    source: SourceReference

class PiecewiseCurveRule(FrozenModel):
    id: Identifier
    variants: tuple[FaultTimeVoltageVariant, ...]
    executable: bool
    source: SourceReference
```

Model validation requires ordered, finite, positive values on logarithmic axes; complete,
non-overlapping segment coverage; in-range points; unique variant identities; and source
provenance for every variant. Source pixel coordinates are audit evidence tying a reviewed point
to the private source image. They are stored only in the private package alongside the licensed
derived coordinates.

`RulePackage` gains `curves`, persisted as `curves.json`, checksummed and included in audit and
report inventories. Curve evaluation selects one typed variant, finds its segment using explicit
boundary policy, and applies only that segment's declared interpolation. Runtime callers never
inspect extraction artifacts.

## Generic figure extraction

### Recipe

`CurveAuditSpec` declares only:

- semantic ID and neutral variant slot IDs;
- figure number, page neighborhood, and expected source bounding box;
- expected x/y quantity kinds and units;
- expected axis scale (`log10` for Figures 5 through 7);
- expected curve count and permitted segment/interpolation kinds; and
- structural validation and provenance requirements.

It contains no expected tick values, thresholds, curve coordinates, curve labels, or normative
formula constants.

### Raw artifact

`RawFigure` retains the source document hash, page/figure locator, image-XObject hash, source
bbox, pixel dimensions, extraction method, OCR tokens with pixel bboxes, detected grid geometry,
raw curve traces, diagnostics, and content hash. Image bytes remain in the local rule workspace;
they do not enter a public artifact, audit export, or final `.icrules` archive.

### Extraction order

1. Locate the figure uniquely within the declared page window.
2. Prefer PDF path geometry when a printing provides path primitives.
3. Otherwise extract the embedded image XObject without page resampling.
4. Detect plot frame and major/minor grid lines from source geometry.
5. OCR only tick-label and legend regions with a local Tesseract process using fixed arguments,
   a timeout, and no network access.
6. Fit the pixel-to-value transform in log space from independently read ticks.
7. Trace each curve from vector strokes or source pixels, retaining discontinuities and dashes.
8. Associate traces with neutral variant slots only when legend geometry and OCR resolve
   uniquely.
9. Simplify in calibrated log space with a deterministic resolution-derived tolerance.
10. Emit a proposed `PiecewiseCurveRule(executable=False)` and its review items.

Tesseract is not a package runtime dependency. The extractor discovers the local executable with
`shutil.which`, invokes it through `subprocess.run` without a shell, and records its version. A
missing executable produces a blocking review item and exposes manual calibration/point entry as
fallback. It never silently changes extraction method.

### Determinism and ambiguity

The same source image hash, extractor version, OCR version, recipe, and review resolutions must
produce identical Decimal axes, points, segments, semantic content, and checksums. Decimal values
are derived from integer source-pixel coordinates and the reviewed log calibration; floating
point values never enter package semantics.

Digitization blocks when any of these occur:

- plot frame or axis cannot be found uniquely;
- fewer than two independent ticks calibrate an axis;
- ticks are unordered or inconsistent with the declared log scale;
- OCR tokens conflict or have no unique axis/legend association;
- curve count differs from the structural contract;
- two curves merge without a unique split;
- a trace is discontinuous without a declared segment boundary;
- a curve leaves the plot frame;
- simplification exceeds the pixel-derived fidelity bound;
- a variant association is missing or duplicated; or
- extraction/projection lacks complete provenance.

No confidence threshold turns uncertainty into executable content. Every uncertain state creates
a blocking review item.

## Figure review and approval

The Rule Manager adds a curve-review view. It renders the licensed source XObject locally and
draws the proposed curve as a separate Qt overlay. The overlay can be toggled and zooms with the
source without modifying it.

The maintainer can correct:

- x/y axis calibration and tick association;
- curve-to-variant association;
- breakpoint coordinates;
- segment boundaries and segment type; and
- interpolation semantics.

Manual point entry is available only after extraction is blocked or the reviewer rejects a
proposal. It is not the default path.

Every correction stores actor, timestamp, notes, original/corrected hashes, affected review-item
hashes, and complete source reference. Approval is blocked until every required Figure 5 through
7 variant is present, uniquely associated, reviewed, provenance-complete, and internally valid.
Only approval converts `fault_time_voltage` to `executable=True`.

## Table 2 semantic extraction

Table 2 uses a dedicated `TableAuditSpec` with explicit merged-cell inheritance, structural row
roles, header paths, footnote scopes, and blank classifications. Generic compound-cell parsing
preserves every scalar token and reference token separately.

Projection creates `iec62477_2022.dvc.voltage_limits` as a `DecisionRule`, not as a runtime table.
Its typed inputs and outputs distinguish:

- DVC identity;
- operating-condition category;
- voltage quantity kind;
- unit;
- conditional alternative/applicability context; and
- numeric, not-applicable, or semantic-reference outcomes.

Conditional alternatives become separate decision rows with explicit matchers. Merged source
cells are inherited only across recipe-declared spans. A source reference to Table 7 resolves to
the existing Table 7 semantic family. A source reference to Figures 5 through 7 resolves to
`iec62477_2022.dvc.fault_time_voltage`; curve values are never copied into Table 2.

Unresolved merged cells, alternatives, references, quantities, units, blanks, or footnotes block
projection or execution.

## Table 3 semantic extraction

Table 3 uses a dedicated structural recipe and projects
`iec62477_2022.dvc.protection_matrix` as a `DecisionRule`. Typed inputs cover circuit DVC,
surroundings or adjacent-circuit context, accessibility context, and applicable exceptions.
Typed outputs use neutral protection categories and evidence/applicability states.

Every supported source combination becomes one ordered row or an explicit outside-scope result.
Notes and exceptions remain source-scoped review artifacts; copied IEC prose is not stored in
public code. Missing combinations, duplicate combinations, ambiguous merged headers, or
unresolved exceptions block execution.

## Generic clause and bullet extraction

`ClauseAuditSpec` declares semantic ID, clause locator, page neighborhood, output kind, and
neutral structural expectations. It never declares a numeric result expected from the clause.

The pipeline is:

```text
clause locator
-> raw private fragment with source spans
-> paragraph and bullet tree
-> typed tokens and conditional branches
-> proposed DecisionRule / ProcedureRule
-> blocking review items
-> correction and approval
-> executable semantic rule
```

`RawClauseFragment`, subdivisions, tokens, and proposed facts live in `ImportedRuleDraft` with
stable content hashes and source bboxes. Numeric tokens and operators come from the PDF. Generic
normalization recognizes paragraph boundaries, bullets, enumerated alternatives, references,
quantities, and units while preserving the raw source span. Unsupported grammar or uncertain
branch attachment blocks; it is never flattened into guessed prose.

The DVC fault/time applicability clauses use this machinery and reference the reviewed curve
variants. Clause rules do not duplicate curve coordinates.

## Table 7 TOV completion

The current TOV parser treats a multi-quantity source cell as one scalar and correctly creates an
ambiguity. Slice C replaces that temporary behavior with generic compound-quantity extraction:

- retain the raw cell and source span;
- extract ordered scalar components independently;
- retain source quantity labels/markers separately from values;
- propose typed component associations;
- preserve AC and DC row axes independently; and
- preserve declared interpolation without sharing the impulse route.

Projection creates distinct typed TOV components and any reviewed conversion formula needed to
relate them. A component association or formula interpretation that is not unique remains
`executable=False` and blocks approval. Reviewer resolution is required before the TOV semantic
family becomes executable. Existing impulse rules and AC/DC routing remain unchanged.

## Approval and package gates

Slice C extends approval with focused gates, leaving the full inventory completeness dashboard
to Slice E. Approval refuses a draft when:

- any Slice C review item remains unresolved;
- a required Slice C decision, formula, or curve is non-executable;
- any Table 2 curve/Table 7 reference is unresolved;
- any required Figure 5 through 7 variant is missing or duplicated;
- curve calibration, segment coverage, or provenance is incomplete;
- Table 7 quantity components disagree across shared source cells; or
- semantic projection does not reproduce the corrected private artifact hashes.

Approved export/re-import preserves decisions, formulas, curve variants, points, segments,
interpolation semantics, execution state, provenance, and deterministic checksums.

## Rule Manager surfaces

The Rule Manager gains focused, generic review views for:

- normalized decision rows for Tables 2 and 3;
- clause subdivisions and proposed conditional branches;
- compound TOV quantities and formulas; and
- source-figure curve overlay and correction.

Public UI labels are neutral internal descriptions. Licensed source text is shown only from the
maintainer's local PDF while that private draft is open.

## Public tests

All public fixtures use unrelated synthetic values and wording.

- Synthetic merged/categorical tables verify inheritance, alternatives, reference outcomes,
  footnote scopes, blank classification, and decision projection.
- Synthetic clauses verify paragraph/bullet structure, numeric extraction from the source,
  conditional branches, unresolved grammar, correction, and approval.
- Synthetic vector and embedded-raster figures verify vector preference, XObject fallback,
  log-axis calibration, OCR token handling, curve association, deterministic simplification,
  ambiguity blocking, and manual fallback.
- Curve model/evaluator tests cover validation, every interpolation kind, boundaries,
  non-executable refusal, serialization, archive round-trip, checksum, and provenance.
- Rule Manager tests cover overlay alignment, corrections, review records, and approval gating.
- Table 7 tests prove distinct source quantities, non-executable proposals, reviewer resolution,
  AC/DC independence, and impulse/TOV independence.

Every behavior follows strict red-green-refactor TDD. No test asserts source code text or uses a
licensed expected value.

## Private tests

Private tests use the maintainer-supplied licensed standards directory and commit no expected
licensed content. They prove:

- exact IEC 62477-1:2022 identity and source hash handling;
- deterministic location and extraction of Tables 2 and 3;
- deterministic location and digitization of Figures 5, 6, and 7;
- log-axis calibration and complete source provenance;
- proposed curves are non-executable before review;
- all required curve variants can be reviewed and approved;
- Table 2 references resolve to the reviewed curve semantic rule;
- Table 7 compound quantities remain distinct across AC/DC routes;
- approved `.icrules` export/re-import preserves the curve semantics; and
- the semantic API can evaluate every reviewed fault/time-voltage variant.

Expected coordinates, values, labels, screenshots, and digests live only in ignored private test
artifacts or maintainer review records.

## Out of scope

- Supply-topology, clearance, creepage, cross-standard mapping, and high-frequency rules from
  Slice D.
- Verification procedures, package-wide completeness dashboard, and final end-to-end package
  completion from Slice E.
- Issue #35, #36, or #37 runtime UI.
- Bundling Tesseract in release installers. Missing local OCR remains a blocking extraction state
  with manual fallback until packaging support is separately requested.

## Definition of done

- Tables 2 and 3 extract from the licensed PDF and project to their required semantic IDs.
- Figures 5 through 7 digitize automatically from source XObjects, produce reviewed piecewise
  rules, and become executable only after approval.
- `iec62477_2022.dvc.fault_time_voltage` is queryable and executable after review.
- Table 2 semantic references resolve without duplicated curve values.
- Table 7 TOV source quantities and formulas are distinct, typed, reviewable, and executable only
  after approval; AC/DC and impulse/TOV routes remain independent.
- Public tests contain only synthetic content.
- Private tests pass against the maintainer-supplied IEC 62477-1:2022 PDF.
- `uv run ruff check .` passes.
- `uv run mypy` passes.
- `uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing
  --cov-fail-under=80` passes.
