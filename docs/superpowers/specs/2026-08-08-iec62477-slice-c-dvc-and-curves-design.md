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

### Proposal and execution lifecycle

Final rule objects do not carry an `executable` flag. A `RulePackage` is executable by
construction: it can exist as an approved package only after validation and approval succeed.
Imported content remains a `DraftRulePackage` and carries separate `SemanticProposal` records:

`RuleKind` becomes one shared schema type with `table`, `formula`, `mapping`, `decision`,
`procedure`, `guidance`, and `curve`; IEC inventory and proposal records import that type.

```python
ProposalState = Literal["proposed", "reviewed"]

class SemanticProposal(FrozenModel):
    semantic_id: Identifier
    rule_kind: RuleKind
    state: ProposalState
    rule_sha256: str
    source_artifact_sha256: str
    review_item_sha256s: tuple[str, ...] = ()
```

The typed candidate rules remain in the draft's existing rule collections, while proposal records
state whether their exact canonical payload has been reviewed. Any correction changes the rule
hash and returns that proposal to `proposed`. Approval requires every required proposal to be
`reviewed`, requires its current rule hash and source-artifact hash to match, and then constructs a
final `RulePackage` without proposal metadata. Draft proposal state is never archived in an
approved `.icrules` package. This prevents the contradictory state “approved package containing a
non-executable rule” and applies the same lifecycle to tables, formulas, decisions, procedures,
guidance, mappings, and curves.

`source_artifact_sha256` is the artifact digest for a single-source proposal. For a rule assembled
from multiple artifacts, including `fault_time_voltage`, it is the canonical SHA-256 of the ordered
`(artifact_id, artifact_sha256)` pairs. Every variant retains its own reviewed-artifact digest and
required review-item digest. The aggregate proposal can become `reviewed` only when every member
artifact/variant review matches; changing any member changes the aggregate digest and resets the
proposal.

### Typed source-document provenance

`SourceDocument` gains a stable `id`, using the recipe ID for imported IEC documents. The source
hash remains stored once in the manifest document. `SourceReference` gains required
`document_id`, typed `page: int | None`, and optional `geometry: SourceGeometryReference | None`:

```python
class SourceGeometryReference(FrozenModel):
    artifact_sha256: str
    bbox: tuple[DecimalValue, DecimalValue, DecimalValue, DecimalValue] | None = None

class SourceReference(FrozenModel):
    document_id: Identifier
    standard: Identifier
    edition: Identifier
    page: int | None = Field(default=None, ge=1)
    clause: ReferenceText | None = None
    table: ReferenceText | None = None
    figure: ReferenceText | None = None
    row: ReferenceText | None = None
    column: ReferenceText | None = None
    geometry: SourceGeometryReference | None = None
    note: ReferenceText | None = None
```

Package validation requires every reference's `document_id` to resolve uniquely in the manifest
and requires its standard/edition to agree with that document. `note` remains optional human
context and no longer carries the primary PDF page. Version 3 archives require rebuild; no
migration guesses missing page or document identity.

### Boolean decision matching

`Matcher` gains `boolean: bool | None`. For a boolean input, `equals` requires this field and
forbids string `values`; categorical equality continues to use `values`. Decision validation,
exhaustive coverage, and evaluation enumerate `False` and `True` as a real two-value domain.
Mixed categorical/boolean exhaustive coverage uses their Cartesian product. Numeric ranges and
categorical `in` matching remain unchanged.

### Piecewise curves

Add first-class curve models to `domain/rules.py`:

```python
CurveAxisScale = Literal["linear", "log10"]
CurveSegmentType = Literal["continuous", "plateau", "step"]
CurveInterpolation = Literal[
    "linear", "log_x", "log_y", "log_log", "constant", "step_before", "step_after"
]

class CurveAxis(FrozenModel):
    quantity_kind: Identifier
    unit: Identifier
    scale: CurveAxisScale
    minimum: DecimalValue
    maximum: DecimalValue

class CurvePoint(FrozenModel):
    x: DecimalValue
    y: DecimalValue

class CurveSegment(FrozenModel):
    start: int
    end: int
    segment_type: CurveSegmentType
    interpolation: CurveInterpolation

class FaultTimeVoltageSelector(FrozenModel):
    subject: Literal["accessible_circuit", "conductive_accessible_part"]
    voltage_basis: Literal["ac_rms", "ac_peak", "dc"]
    dvc_context: Identifier | None
    environment_context: Identifier | None

class FaultTimeVoltageVariant(FrozenModel):
    id: Identifier
    selector: FaultTimeVoltageSelector
    x_axis: CurveAxis
    y_axis: CurveAxis
    points: tuple[CurvePoint, ...]
    segments: tuple[CurveSegment, ...]
    applicability: ApplicabilityText
    source: SourceReference
    reviewed_artifact_sha256: str

class PiecewiseCurveRule(FrozenModel):
    id: Identifier
    variants: tuple[FaultTimeVoltageVariant, ...]
    source: SourceReference
```

Model validation requires ordered, finite, positive values on logarithmic axes; complete,
non-overlapping segment coverage; in-range points; unique variant identities; and source
provenance for every variant. A `continuous` segment uses linear/log interpolation, a `plateau`
requires equal endpoint voltage and `constant`, and a `step` uses `step_before` or `step_after`.
`CurvePoint` contains only engineering quantities. Source
pixel/vector coordinates live only in `RawCurvePoint` inside the private extraction/review
artifact. Each approved variant links to that artifact through `reviewed_artifact_sha256`; it does
not embed source-image geometry into runtime points.

`RulePackage` gains `curves`, persisted as `curves.json`, checksummed and included in audit and
report inventories. Curve evaluation selects one typed variant, finds its segment using explicit
boundary policy, and applies only that segment's declared interpolation. It never extrapolates.
Runtime callers never inspect extraction artifacts.

## Generic figure extraction

### Recipe

`CurveAuditSpec` declares only:

- semantic ID and neutral variant slot IDs;
- figure number, page neighborhood, and expected source bounding box;
- expected x/y quantity kinds and units;
- expected axis scale (`log10` for Figures 5 through 7);
- expected curve count and permitted segment types/interpolation kinds; and
- structural validation and provenance requirements.

It contains no expected tick values, thresholds, curve coordinates, curve labels, or normative
formula constants.

### Raw artifact

`RawFigure` retains the source document hash, page/figure locator, image-XObject hash, source
bbox, pixel dimensions, extraction method, OCR tokens with pixel bboxes, detected grid geometry,
raw curve traces, diagnostics, and content hash. Each `RawCurvePoint` contains source x/y
coordinates plus a stable primitive/path/pixel reference. These raw coordinates never enter
`CurvePoint`. Image bytes and raw geometry remain in the local rule workspace; they do not enter a
public artifact, audit export, or final `.icrules` archive.

### OCR abstraction and image dependency

```python
class OcrEngine(Protocol):
    @property
    def identity(self) -> OcrEngineIdentity: ...

    def recognize(self, image: Image.Image) -> tuple[OcrToken, ...]: ...
```

`TesseractOcrEngine` is the local production implementation. It uses `shutil.which`,
`subprocess.run` without a shell, fixed arguments, an explicit timeout, and TSV output. Engine
name/version are part of extraction provenance and the deterministic draft digest. Public tests
inject `FakeOcrEngine`; they never require a Tesseract installation or call the network.

The plan adds `pillow` as an explicit bounded runtime dependency. `pdfplumber` currently installs
Pillow transitively, but production code must not rely on that undeclared relationship. Pillow is
sufficient for lossless XObject decoding, palette inspection, projections, masks, and connected
pixel traces. PySide6/QImage remains the UI renderer. OpenCV and NumPy are not added.

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
10. Emit a typed `PiecewiseCurveRule` plus `SemanticProposal(state="proposed")` and its review
    items.

Tesseract is an optional local executable, not a Python package dependency. A missing executable
produces a blocking review item and exposes manual calibration/point entry as fallback. It never
silently changes extraction method.

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

### Conservative reconstruction

The approved reconstructed limit must never become less conservative than the reviewed source
because of tracing error, simplification, coordinate conversion, rounding, or interpolation. For
these maximum-voltage curves, “conservative” means the executable voltage limit is never above
the lowest source value consistent with the detected stroke and calibration uncertainty.

The deterministic policy is:

1. Preserve the complete source stroke as a pixel/vector uncertainty band rather than a
   centreline.
2. Convert every band edge through the reviewed log-axis calibration using `Decimal`.
3. Choose the lower voltage bound at each source sample. At a descending breakpoint choose the
   earliest time consistent with the horizontal source uncertainty.
4. Quantize voltage downward and time toward the conservative side at precision derived from the
   reviewed axis labels; never round to nearest.
5. Simplify only in calibrated log space. Evaluate every proposed segment at every source-column
   sample, every breakpoint, and every segment intersection. The proposal must never rise above
   the conservative source envelope.
6. Permit a proposal to fall below that envelope by no more than
   `max(1 pixel, ceil(detected_stroke_width / 2))`, measured back in source pixels. Greater loss of
   fidelity requires review even though it is conservative.
7. Include calibration residual in the uncertainty band. If the residual exceeds half the
   detected minor-grid spacing, or if no conservative ordering can be proved, create a blocking
   review item.

Reviewer corrections re-run the same proof. A rule cannot become reviewed while the proof fails.

Curve domains are closed and explicit. Evaluation at either approved endpoint is allowed. A value
below the lower endpoint or above the upper endpoint returns `out_of_domain`; the evaluator never
continues the first or last sloped segment. A plateau extends only when its approved constant
segment and domain explicitly include the requested coordinate.

### Variant selection

Every variant has one exact `FaultTimeVoltageSelector` key. Callers provide all four dimensions;
`None` explicitly means “not applicable” for DVC/environment, never wildcard. Subject and voltage
basis are always required. Figure 7 variants use `subject="conductive_accessible_part"` and
`None` for dimensions that do not apply; Figures 5 and 6 use
`subject="accessible_circuit"` with their reviewed DVC/environment keys.

`select_curve_variant` compares complete keys:

- zero matches returns a typed `no_match` result;
- exactly one match returns that variant; and
- more than one match raises a semantic/package error.

Package validation rejects duplicate selector keys, so first-match-wins is never used for curves.
Construction of `FaultTimeVoltageSelector` requires all four dimensions, including explicit
`None` values. `evaluate_piecewise_curve` therefore returns `no_match`, `out_of_domain`, or
`matched`; a structurally incomplete selector is rejected before evaluation rather than reported
as a runtime status.

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
Only approval copies the reviewed `fault_time_voltage` candidate into the final executable
`RulePackage`; proposal metadata stays in the draft.

## Table 2 semantic extraction

Table 2 uses a dedicated `TableAuditSpec` with explicit merged-cell inheritance, structural row
roles, header paths, footnote scopes, and blank classifications. Generic compound-cell parsing
preserves every scalar token and reference token separately.

Private-fixture verification corrected the original synthetic layout assumption. The physical
grid remains 8 by 6, but its semantic body is four DVC rows by five distinct voltage-quantity
columns, beginning at physical row 3 and column 1. The structural recipe declares the following
merged regions without embedding source text or values:

- the top-left header spans rows 0 through 2;
- the top quantity header spans columns 1 through 5;
- the normal-condition header spans columns 1 through 4;
- the first impulse value spans physical rows 3 and 4;
- the Figure 5/6 reference spans physical rows 3 through 5; and
- the Table 7 impulse reference spans physical rows 5 and 6.

The final body cell at row 6, column 5 is explicitly not applicable. Empty continuation cells in
the footnote row are declared as structural blanks. Every other physical blank inside a declared
merged region is inherited from its anchor; an undeclared blank remains a blocking extraction
error. Inherited data cells retain their own logical row/column position but use the anchor's
reviewed value or reference token and source span.

Projection creates `iec62477_2022.dvc.voltage_limits` as a `DecisionRule`, not as a runtime table.
Its typed inputs and outputs distinguish:

- DVC identity;
- the five distinct voltage quantity kinds;
- unit;
- numeric, not-applicable, or semantic-reference outcomes.

There is no invented conditional-alternative pairing: each physical quantity column is a distinct
selector. Merged source cells are inherited only across recipe-declared spans. Figure references
project into a dedicated decision whose single reference output resolves to
`iec62477_2022.dvc.fault_time_voltage`; curve values are never copied into Table 2. The Table 7
reference is an impulse-withstand reference, not a temporary-overvoltage reference. It projects
into a separate decision with explicit AC and DC reference outputs resolving to the existing
`iec62477_2022.supply.impulse_by_system_voltage_ovc.ac` and `.dc` tables. This represents the one
physical merged reference without falsely assigning AC/DC supply type to different DVC rows.

Unresolved merged cells, references, quantities, units, blanks, or footnotes block
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
in `SemanticProposal(state="proposed")` and blocks approval. Reviewer resolution is required
before the TOV semantic family enters a final package. Existing impulse rules and AC/DC routing
remain unchanged.

## Approval and package gates

Slice C extends approval with focused gates, leaving the full inventory completeness dashboard
to Slice E. Approval refuses a draft when:

- any Slice C review item remains unresolved;
- a required Slice C proposal is absent, not reviewed, or has a stale rule/source-artifact hash;
- any Table 2 curve/Table 7 reference is unresolved;
- any required Figure 5 through 7 variant is missing or duplicated;
- curve calibration, segment coverage, or provenance is incomplete;
- Table 7 quantity components disagree across shared source cells; or
- semantic projection does not reproduce the corrected private artifact hashes.

Approved export/re-import preserves decisions, formulas, curve variants, points, segments,
interpolation semantics, provenance, and deterministic checksums. Approved archives contain no
draft proposal state or raw extraction geometry.

## Three implementation PRs

Slice C is one conceptual milestone delivered through three independently testable PRs. Each PR
uses `Refs #34`; none closes the issue.

### C1 — semantic foundation

- schema v4 and importer version bump;
- typed source-document/page/geometry provenance;
- deterministic boolean decision matching and exhaustive coverage;
- proposal/review/final-package lifecycle;
- `PiecewiseCurveRule`, exact selector, evaluator, conservative domain behavior;
- archive, validation, audit, report counts, and synthetic fixtures.

### C2 — structured DVC extraction

- Table 2 and Table 3 structural recipes and semantic decision projection;
- generic `ClauseAuditSpec`, subdivision/bullet extraction, and DVC applicability;
- compound Table 7 TOV quantity parsing, reviewed formula association, and independent AC/DC
  and impulse/TOV routes.

### C3 — Figures 5 through 7

- vector-first and embedded-XObject source extraction;
- OCR abstraction and local Tesseract adapter;
- log-axis calibration, tracing, conservative simplification, and variant association;
- curve review overlay and corrections;
- Table 2 reference resolution;
- private extraction, approval, archive round-trip, and semantic API verification.

Slice C is complete only when C3 passes its private and public gates.

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
  unique selection, ambiguity refusal, no extrapolation, conservative reconstruction, unsafe
  simplification blocking, serialization, archive round-trip, checksum, and provenance.
- Decision tests cover boolean true/false equality, missing input, boolean exhaustiveness, and
  mixed categorical/boolean coverage.
- Provenance tests reject missing document IDs, unknown manifest links, page-in-note-only
  references, and mismatched standard/edition links.
- OCR tests inject a deterministic fake and separately test the local Tesseract adapter's fixed,
  shell-free command contract without requiring the executable.
- Rule Manager tests cover overlay alignment, corrections, review records, and approval gating.
- Table 7 tests prove distinct source quantities, proposed/reviewed lifecycle, reviewer resolution,
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
- proposed curves cannot enter a final package before review;
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
  rules, and enter an executable package only after approval.
- Schema v4 supports deterministic boolean matching and exhaustive boolean coverage.
- Source document identity, page, and optional geometry/artifact provenance are typed.
- Raw raster/vector coordinates remain separate from semantic curve points.
- Proposal/review/final-package lifecycle cannot create contradictory approved states.
- Curve selection is exact and unique; multiple matches are rejected.
- Curve evaluation performs no implicit extrapolation.
- Conservative reconstruction is proved before review; uncertainty blocks approval.
- OCR is abstracted and public tests require no local Tesseract installation.
- `iec62477_2022.dvc.fault_time_voltage` is queryable and executable after review.
- Table 2 semantic references resolve without duplicated curve values.
- Table 7 TOV source quantities and formulas are distinct, typed, reviewable, and executable only
  after approval; AC/DC and impulse/TOV routes remain independent.
- C1, C2, and C3 each pass their independent test gate and use `Refs #34`.
- Public tests contain only synthetic content.
- Private tests pass against the maintainer-supplied IEC 62477-1:2022 PDF.
- `uv run ruff check .` passes.
- `uv run mypy` passes.
- `uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing
  --cov-fail-under=80` passes.
