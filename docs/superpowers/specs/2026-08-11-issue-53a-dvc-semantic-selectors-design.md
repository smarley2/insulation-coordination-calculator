# Issue #53A — Tables 2 and 3 get reviewed semantic selectors

`iec62477_2022.dvc.voltage_limits` and `iec62477_2022.dvc.protection_matrix` expose positional
identifiers as their runtime contract: `dvc-1..dvc-4`, `voltage-quantity-1..5` and
`protection-context-1..6`, each derived from a physical grid coordinate. A consumer resolving
those has to know that a particular physical row means a particular designation, which is a
fact about the document's layout rather than about the requirement. It is the defect class of
#48 (invented DVC designations), #50 (an unstated Figure 7 basis) and #52 (a name claiming the
wrong job), in the one place where it is also a blocker: PR #55's adapter cannot stop being
provisional until this contract is semantic.

## Scope

#53 spans seven items across two slices and two subsystems. It is decomposed into three
sub-projects, each with its own spec, plan and PR, in this order:

- **#53A, this spec** — #53 items 1 and 2: semantic selectors for both DVC tables.
- **#53B** — #53 item 7: clause-derived rules must depend on reviewed private facts rather
  than source-shape checks plus pre-authored branch inventories.
- **#53C** — #53 items 3 to 6: the four Slice D supply rule contracts, written once, on top of
  #53B's pipeline rather than against the Python constants #53B removes.

#53A covers all four axes of both tables. #53 item 1 names Table 2 only, but Table 3 carries
the identical defect and PR #55 adapts both, so splitting them would leave the protection
matrix positional and force a second pass through the same module and the same vocabulary
decisions.

## The vocabularies

Three frozen selector models, discriminated by an explicit `selector_kind` literal so canonical
hashing and JSON round-trip stay unambiguous.

`DvcDesignationSelector`, serving the row axis of both tables:

```text
designation    dvc_as | dvc_b | dvc_c
environment    dry | wet_and_saltwater_wet | not_applicable
```

`Table2QuantitySelector`, for Table 2's column axis:

```text
operating_context   normal | single_fault_or_abnormal
quantity            working_voltage | impulse_withstand | fault_voltage
basis               ac_rms | ac_peak | dc_mean | ac_peak_or_dc | not_applicable
```

`ProtectionTargetSelector`, for Table 3's column axis:

```text
target            accessible_part | adjacent_circuit
pe_relationship   connected_to_pe | not_connected_to_pe | not_applicable
access_context    general_access | service_or_restricted_access | not_applicable
person_scope      ordinary_or_skilled | skilled_only | not_applicable
adjacent_dvc      dvc_as | dvc_b | dvc_c | not_applicable
```

### Every dimension is total

The generic evaluator makes each declared input mandatory — `evaluate_decision` returns
`input_required` when one is absent, and raises when a value is outside its declared
`allowed_values`. So a structurally irrelevant dimension is an explicit `not_applicable` token,
never an omitted input. This sub-project does not change the evaluator.

### The curve selector's basis vocabulary does not move

`FaultTimeVoltageSelector.voltage_basis` stays `dc | ac_rms | ac_peak | ac_unspecified`. #50
pinned that four-token contract in six places against exactly this kind of widening.

Table 2's basis shares the spellings `ac_rms` and `ac_peak`, where the meaning is the same, and
diverges deliberately at `dc_mean` and `ac_peak_or_dc`. The divergence is the safety property:
`dc_mean` is a Table 2 working-voltage quantity and the curve's `dc` is a Figure 5 curve basis,
so a consumer that ever relates the two must do so through an explicit mapping. Nothing may
translate them automatically, exactly as #50 established for `ac_unspecified`.

## Authority: the licensed content decides, the public recipe supplies vocabulary

Per axis position:

```text
reviewed header cell(s)
  -> recipe's neutral token grammar proposes a typed selector
  -> AXIS_SELECTOR_REVIEW_REQUIRED blocks approval until exactly one exact review matches
  -> the confirmed selector is what the projection reads
```

Two models, mirroring the proposal-and-review pattern `SemanticProposal` and
`CurveVariantReview` already establish:

```python
class AxisSelectorProposal(FrozenModel):
    grid_id: Identifier
    axis: Literal["row", "column"]
    index: int
    selector: AxisSelector | None  # None = the grammar could not propose
    proposal_sha256: str  # proposal plus its evidence
    grid_artifact_sha256: str


class AxisSelectorReview(FrozenModel):
    grid_id: Identifier
    axis: Literal["row", "column"]
    index: int
    proposal_sha256: str
    grid_artifact_sha256: str
    confirmed_selector: AxisSelector
    actor: str
    recorded_at: datetime
    notes: NotesText
```

The review carries the outcome, not merely an affirmation, because three workflows must all
work: the reviewer confirms the proposal, corrects it, or supplies a selector where the grammar
matched nothing. A record holding only a hash could express the first and none of the others.

Each review binds both the current proposal hash and the current raw-grid artifact hash, so a
changed header reading, a changed grammar or a re-extracted grid drops the review and re-opens
it. That is the `CurveVariantReview` property, kept deliberately.

### What the grammar may read, and where there is no grammar

A public grammar matches short neutral keywords only — single generic words, never a phrase, a
heading or the header hierarchy's wording, exactly as the existing `basic` / `enhanced` token
grammar does. Three axes get one: both tables' row axes and Table 2's column axis.

**Table 3's column axis has no grammar and no proposal.** Its six selectors are supplied by the
reviewer outright, through the workflow this design already supports for an unmatched position.
The asymmetry is deliberate: a text-matching grammar for that axis would need the header
hierarchy's wording in public code, which the public-record limit below forbids. Its proposals
therefore carry `selector=None` by construction, and approval stays blocked until six reviews
supply them.

Nothing falls back to position. A grammar that matches nothing yields a proposal whose selector
is `None`, and approval stays blocked until a review supplies one. One blocker code,
`AXIS_SELECTOR_REVIEW_REQUIRED`, covers both the unmatched and the merely unreviewed case: both
are "this position has no confirmed selector", and the reviewer's action is the same. This is what makes a
reprint that reorders or rewords a header stop the build instead of silently regenerating the
old contract.

## The projection boundary

`GridProjector` grows one parameter, uniformly:

```python
GridProjector(grid, identity, confirmed_axes) -> (rules, proposals)
```

Four projectors are registered today — Tables 2 and 3 plus two verification projectors — so
this is a small controlled migration. A second `axis_aware_grid_projectors` registry was
rejected: the distinction is not between two kinds of projector but one projection operation
with reviewed semantic facts optionally available, and two registries would add routing logic
and another place to register a spec incorrectly. A generic `ProjectionContext` was also
rejected as abstraction ahead of need; the clause projector already has its own
three-parameter contract.

Resolution happens before projection and owns every refusal:

```text
grid + draft
  -> resolve_confirmed_axis_selectors(spec, grid, draft)
  -> ConfirmedAxes
  -> grid_projector(grid, identity, confirmed_axes)
```

For a spec that declares axis-selector grammars, resolution fails if any position lacks a
review, carries more than one, or is bound to a stale proposal or grid artifact. For
every other spec it yields an empty `ConfirmedAxes`. Each projector therefore receives a valid
context and never repeats review-state validation. Tables 2 and 3 may still assert that their
resolved selector inventory is complete, as a defensive invariant, but they must not know how
review matching works.

The dependency direction is one-way: review machinery, then resolved facts, then projection.
No projector reads arbitrary draft state.

## What the projections emit

Route identifiers and outputs do not change. Table 2 keeps `dvc.voltage_limits`,
`.fault_time_reference`, `.impulse_reference` and `.not_applicable`; Table 3 keeps
`dvc.protection_matrix` with its `none | basic_protection | enhanced_protection` output. The
two reference routes stay references — the curve route to `dvc.fault_time_voltage`, the impulse
route to the `.ac` and `.dc` Table 7 routes — so #53's requirement that Table 2 must resolve
rather than duplicate is preserved unchanged.

The inputs change:

```text
Table 2   dvc, environment, operating_context, quantity, basis, unit
Table 3   dvc, target, pe_relationship, access_context, person_scope, adjacent_dvc
```

What `ConfirmedAxes` controls, and what it does not:

```text
from ConfirmedAxes    Table 2: dvc, environment, operating_context, quantity, basis
                      Table 3: dvc, target, pe_relationship, access_context,
                               person_scope, adjacent_dvc

not from ConfirmedAxes  Table 2 unit                    <- the reviewed grid's target_unit
                        Table 2 outputs                 <- existing route semantics
                        Table 3 protection_requirement   <- existing reviewed cell grammar
```

### Structural identifiers are non-contractual

`protection-context-1..6`, `dvc_row` and `voltage_quantity` remain, and are not renamed:
renaming would churn the audit layer without improving the consumer contract. They are
explicitly non-contractual extraction identities. They may appear in raw-grid and audit
metadata. They must not appear in projected `DecisionInput.allowed_values`, in matcher values,
or in any application-facing API.

Physical coordinates survive in exactly three places, none of them a runtime selector: the raw
grid's cells, each `AxisSelectorProposal`'s `index`, and each `DecisionRow`'s `source`.

### The reviewed selector inventories

Published as unordered semantic sets. Which physical position produced which selector is
provenance, held in the private review layer, and is not part of this public contract.

Table 2's row axis supports exactly four reviewed designation selectors:

```text
dvc_as / dry
dvc_as / wet_and_saltwater_wet
dvc_b  / not_applicable
dvc_c  / not_applicable
```

Table 2's column axis supports exactly five reviewed quantity selectors:

```text
normal                    / working_voltage    / ac_rms
normal                    / working_voltage    / ac_peak
normal                    / working_voltage    / dc_mean
normal                    / impulse_withstand  / not_applicable
single_fault_or_abnormal   / fault_voltage      / ac_peak_or_dc
```

Table 3's row axis supports the three designations with `environment=not_applicable`. Its
column axis supports exactly six reviewed protection-target selectors:

```text
accessible_part  / connected_to_pe      / not_applicable               / not_applicable       / not_applicable
accessible_part  / not_connected_to_pe  / general_access               / ordinary_or_skilled  / not_applicable
accessible_part  / not_connected_to_pe  / service_or_restricted_access / skilled_only         / not_applicable
adjacent_circuit / not_applicable       / not_applicable               / not_applicable       / dvc_as
adjacent_circuit / not_applicable       / not_applicable               / not_applicable       / dvc_b
adjacent_circuit / not_applicable       / not_applicable               / not_applicable       / dvc_c
```

The impulse-withstand entry carries `operating_context=normal`, confirmed against the licensed
source: that column belongs to the same operating-condition group as the three working-voltage
columns. Its `basis` stays `not_applicable` because `quantity` already identifies the
measurement. No column requires an `operating_context` of `not_applicable`, so that token is not
part of the dimension's vocabulary.

## Item 2 requires no implementation

#53 item 2 asks that #50's reviewed Figure 7 basis propagate through the curve selector, the
`dvc.fault_time_voltage` variant identity, `dvc.fault_applicability`, and the private curve
tests. All of that is already true on main: the curve recipe declares `ac_unspecified`,
`recipes/iec62477_1_2022/clauses.py` derives its `(subject, voltage_basis)` vocabulary directly
from `CURVES` so the applicability rule followed automatically, and
`test_dvc_clause_projection.py` already exercises all four routes including
`("conductive_accessible_part", "ac_unspecified")`.

Its one open bullet, "any #35 adapter already written against the old selector", is PR #55's
own work.

## The PR #55 handoff

Once this lands, `domain/dvc.py` deletes its positional mapping table and its
`PROTECTION_MATRIX_ROW_ORDER_CONFIRMED` flag: both tables hand it designations, environments,
quantities and protection targets directly. PR #55 rebases onto this and its blocked phases
open.

## The review surface

Axis review is an approval gate, not optional tooling, so the surface for recording it ships
here. Producing a draft nobody can approve until a later PR would make this an incomplete
slice and would not, in fact, unblock PR #55.

Domain layer, mirroring `review_curve_variant` and `reject_curve_variant`:
`review_axis_selector()` owns validation and state change.

UI, mirroring `ui/curve_review.py` driven from a Rules Manager button, deliberately minimal:

```text
Rules Manager -> "Review axis selectors…" -> one dialog:
    table / axis / position | proposed selector | confirmed selector | status | notes
    confirm | correct | supply
```

No wizard. Qt displays proposals and gathers the decision; it holds no review logic.

## Package contract and rebuild cost

**The importer version bumps: `iec-pdf-4` becomes `iec-pdf-5`.** Rule identifiers do not
change here, so trusted-package validation would otherwise accept a package built before this
change and keep serving the positional vocabulary as if current. `validation.py` already
requires a trusted IEC package's manifest importer version to equal
`domain/rules.py`'s `IEC_IMPORTER_VERSION`, and the foundation design established that an
incompatible importer change bumps that version rather than offering a migration. Putting the
refusal in the package contract is safer than putting it in one consumer: the package should
advertise whether it belongs to the current importer contract.

Lifecycle:

```text
old approved positional package
  -> rejected as stale importer output
  -> rebuild from the licensed PDFs
  -> confirm eighteen axis selectors (Table 2: four rows, five columns;
     Table 3: three rows, six columns)
  -> review the changed Table 2 and Table 3 semantic proposals
  -> approve
```

No source geometry or extraction strategy changes. Rebuilding re-extracts the same regions and
should reproduce the same raw grids. Existing unrelated cell and table review state should
remain current wherever its hashed artifact and review identity are unchanged, and a regression
test proves this sub-project does not invalidate those reviews unnecessarily.

Axis proposals and reviews are draft-only, like `curve_variant_reviews`: `approve_draft`
constructs the package from the rules themselves, so the `.icrules` archive format does not
grow a new concept.

## Tests

**1. No positional identifier in any runtime contract.** Over synthetically projected Table 2
and Table 3 rules, no `DecisionInput.allowed_values` entry and no matcher value matches
`dvc-\d+`, `voltage-quantity-\d+` or `protection-context-\d+`. This is the guard a future
"cleanup" PR trips over.

**2. Selector inventories, stated independently of the recipe**, as unordered sets: the four
Table 2 designation selectors, the five Table 2 quantity selectors, the three Table 3
designations, and the six Table 3 protection-target selectors. Set equality, never ordered
pairs of physical position and selector — the physical pairing stays private.

**3. The correction path.** The grammar proposes A, the reviewer confirms B, the projection
emits B. This is what a hash-only review record could not express, so it is the test that
justifies the design.

**4. Resolver behaviour**, each case its own test:

```text
grammar unmatched, no exact review        -> refuse
grammar unmatched, review supplies one    -> succeed
no review                                 -> refuse
duplicate exact reviews for one position   -> refuse
stale proposal hash                        -> refuse
stale grid artifact hash                   -> refuse
```

The second case matters as much as the refusals: the reviewer is allowed to supply a selector
outright, and a suite that refused every unmatched grammar would forbid one of the three
designed workflows.

**5. Physical reordering does not change meaning.** A synthetic grid whose data rows or columns
are reordered, with reviewed axis facts to match, must project matchers that follow the
semantic facts: a selector confirmed as `dvc_b` stays `dvc_b` whichever physical position it
occupies. This proves "coordinates are provenance only" behaviourally rather than by banning
token strings.

**6. Empty `ConfirmedAxes` is valid.** Both verification projectors keep working through the
widened interface — the migration's blast radius, asserted rather than assumed.

**7. The evaluator contract, on both structured selector types.** Omitting `basis` yields
`input_required`; `quantity=impulse_withstand` with `basis=not_applicable` matches its intended
Table 2 route; and at least one Table 3 case exercises its `not_applicable` dimensions.

### Private tests

Targeted licensed tests prove the chain end to end for this change:

```text
real Table 2 and Table 3 extraction
  -> the expected axis proposal inventories
  -> reviewed axis facts
  -> semantic Table 2 and Table 3 projection
  -> no positional runtime selectors
```

The existing full reviewed-round-trip test runs too where the environment permits, but this
sub-project does not depend on it alone: that fixture is currently blocked on unrelated
environment gaps (`OCR_UNAVAILABLE: tesseract` and unreviewed `dvc.fault_time_voltage` curve
variants, reproducible on merged main). If it is still blocked, its result is recorded
separately and never presented as this sub-project's evidence.

## Public-record limit

Committed files carry semantic identifiers, neutral token vocabularies, structural indexes,
bounding boxes, table and clause locators, and the unordered selector inventories above.

They do not carry source wording, headings or header hierarchy phrasing, numeric content, the
physical order of rows or columns, the pairing of a physical position to a selector, or the
evidence used to derive a selector. Those remain in the licensed documents and the private
review layer.

## Out of scope

#53 items 3 to 7 are #53B and #53C. The generic decision evaluator is unchanged, including its
requirement that every declared input be present. No generic projection context. No renaming of
audit-layer structural identifiers. PR #55's adapter rewrite stays in PR #55. No new runtime
consumer wiring for either table.
