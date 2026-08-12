# Manual Curve Review Design

## Goal

Replace fragile automatic curve reconstruction in Rule Manager with a small, explicit
maintainer workflow. The reviewer reads each licensed source figure locally, defines its log
plot calibration, and enters the few engineering points needed by each piecewise curve.

The final package remains deterministic, auditable, and executable. Licensed source pixels,
labels, coordinates, and values remain local and are never added to public source, tests, or
documentation.

## Decision

Manual review is authoritative. Automatic reconstruction may prefill an unreviewed suggestion
only while that code remains useful, but approval never treats it as trusted evidence. The same
manual editor handles an empty curve, an automatic suggestion, and a rejected suggestion.

The editor uses a synchronized table and overlay:

- the table is authoritative and holds exact engineering values;
- draggable handles offer visual placement and update the table;
- table edits immediately redraw the overlay;
- the reviewer explicitly accepts each variant with notes.

No global fitted equation is stored or requested from the reviewer.

## Variant identity and labels

Existing variant IDs remain stable for package compatibility and audit references. They are not
shown as the primary name.

Rule Manager derives a readable label from the variant's source figure and typed selector fields:
subject, voltage basis, DVC context, and environment context. The stable positional ID appears as
secondary text for diagnostics. Source legend text is not OCRed, persisted, or copied into public
code.

This removes curve-to-slot guessing: the reviewer selects a semantic variant by meaning, then
places that variant's points on the corresponding visible source curve.

## Figure calibration

Calibration happens once per source figure:

1. The verified local PDF crop is displayed.
2. The reviewer marks opposite corners of the plot rectangle.
3. The reviewer enters the visible X and Y axis bounds.
4. Both axes use the recipe-declared logarithmic scale and units.

The source duration unit remains visible in the editor. Conversion to the package's canonical
duration unit happens exactly once when values enter the domain model.

Plot-corner coordinates and axis bounds belong to local draft review evidence. They are hashed
into the review record but do not enter the approved runtime curve.

## Curve editing

Each semantic variant has an ordered point table with add/remove controls. Point count and values
come from the maintainer's local review; public recipes do not encode licensed topology or values.

Validation requires:

- at least two finite points;
- strictly increasing X values;
- positive values on logarithmic axes;
- every point inside the reviewed axis bounds;
- first and last points covering the intended reviewed domain; and
- complete adjacent segment coverage.

Dragging converts source pixels through the reviewed log calibration using `Decimal`. Exact table
entry replaces any visually estimated value. Handles cannot cross neighboring X coordinates or
leave the plot rectangle.

Segment semantics are inferred with one rule:

- equal adjacent Y values produce a `constant` plateau;
- unequal adjacent Y values produce a continuous `log_log` segment.

The preview distinguishes the selected variant from other reviewed variants and shows handles only
for the selected one.

## Runtime representation

The approved `PiecewiseCurveRule`, `FaultTimeVoltageVariant`, `CurvePoint`, and `CurveSegment`
models remain unchanged.

At runtime, `select_curve_variant` matches the complete typed selector. `evaluate_piecewise_curve`
then:

- returns the stored value at a breakpoint;
- uses constant interpolation on plateaus;
- uses power-law interpolation between log-log points; and
- refuses extrapolation outside the reviewed domain.

Therefore no polynomial, regression, or separately stored equation is needed.

## Review, audit, and approval

Manual acceptance records:

- reviewer and notes;
- source document, page, figure, and verified document hash;
- plot rectangle and axis calibration hash;
- semantic variant selector and stable ID;
- exact point and segment hash; and
- whether the table started empty or from an automatic suggestion.

The UI must say `manually reviewed`; it must not claim machine-proven conservatism. Approval blocks
until every recipe-declared variant has current manual review evidence matching the final curve
hash and source hash. Editing calibration or points invalidates affected reviews.

## Cleanup scope

Remove code made obsolete by this workflow:

- separate calibration, trace-association, breakpoint, and segment correction dialogs;
- rejection-only gating for manual entry;
- automatic trace-to-selector ordering as an approval dependency;
- proof state and approval blockers used only by automatic reconstruction;
- duplicate mutation paths superseded by one atomic manual curve replacement; and
- tests covering deleted UI actions or unreachable automatic-correction branches.

Keep:

- verified local PDF identity and source rendering;
- figure/page/bounding-box locators;
- typed selector recipes and stable IDs;
- final curve domain models, evaluator, archive format, and audit inventory;
- deterministic `Decimal` conversion and validation; and
- loading of existing approved packages.

Automatic OCR/tracing code stays only if it still supplies a tested, isolated prefill. Any portion
with no remaining caller is deleted rather than retained for possible future use. No new image or
numerical dependency is added.

## Compatibility

Existing approved `.icrules` packages continue loading because final curve schema and evaluator do
not change. They do not require migration or renewed review.

New drafts use manual-review evidence. Old in-memory unapproved drafts need no migration; source
PDFs can be imported again. Public rule recipes retain only structural locators and neutral
selectors.

## Error handling

The editor blocks acceptance with a focused message when source verification fails, calibration is
incomplete, values are invalid, selector inventory is incomplete, or review evidence is stale.
Parsing errors remain in the editor and never partially mutate the draft.

One atomic save replaces a variant's complete point/segment set, recalculates hashes, clears its
old review, and records one correction entry.

## Tests

Public tests use synthetic figures and values only. They cover:

- readable labels derived from typed selectors;
- log calibration from a manually selected plot rectangle;
- synchronized table and drag updates;
- point ordering, bounds, positivity, and unit conversion;
- automatic constant/log-log segment inference;
- atomic replacement and stale-review invalidation;
- exact per-variant approval gating;
- no extrapolation and existing evaluator behavior;
- approved archive compatibility; and
- transformed raster placement, preventing regression of the current overlay bug.

Private tests verify only structure, review completion, determinism, and end-to-end package use.
They do not commit source labels, values, coordinates, screenshots, reconstructed curves, or
digests.

## Out of scope

- General-purpose graph digitization.
- Polynomial or spline fitting.
- Automatic legend interpretation as trusted evidence.
- Editing already-approved package contents.
- Copying licensed source labels or values into public fixtures.

## Acceptance criteria

- Reviewer can identify every curve by semantic meaning rather than a positional ID.
- Reviewer can calibrate each log plot and create every variant through table entry, dragging, or a
  mix of both.
- Overlay follows the reviewed plot rectangle and remains aligned while zooming.
- Final package stores only typed points, segments, selectors, and provenance needed at runtime.
- Approval requires current manual review for every required variant.
- Existing approved packages still load and evaluate unchanged.
- Obsolete automatic-review code has no remaining dead callers or UI controls.
