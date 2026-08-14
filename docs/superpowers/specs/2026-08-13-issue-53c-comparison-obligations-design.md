# Issue #53C items 3-5 — permission only after a verified comparison

Three supply rules grant permission from a proxy for a requirement instead of the requirement
itself, and #53 items 3-5 name each one. Multiple-source propagation compares overvoltage-category
ordinals where the reviewed reading calls for comparing resolved impulse ratings. HF-transformer
attenuation permits working-voltage treatment on the presence of an evidence method rather than on
a demonstrated result. SPD reduction computes a category step by generic ordinal subtraction rather
than validating the step against a reviewed statement, and carries the double/reinforced floor as
an ignorable boolean output rather than as a comparison.

This design fixes all three with one mechanism. It covers #53 items 3, 4 and 5.

**Out of scope:** item 6 (system-voltage semantics) follows Task 6B's review as its own pass.
Issue #60's Table 7 TOV correction lands before this work; these contracts consume the corrected
Table 7 API and are impulse-side, so there is no further interaction. `evaluate_decision`,
`DecisionValue` and the `.icrules` archive schema are unchanged throughout.

## The spine

```text
reviewed rule   -> emits an atomic ComparisonObligation as a bundle of ordinary decision outputs
                   (operation + semantic operand roles + per-operand source kind and constraints)

consumer (#36)  -> ComparisonObligation.from_decision(result)      [only sanctioned reader]
                -> materializes each operand according to its typed source:
                     package_lookup          resolved against the approved package
                     demonstrated_evidence   bound to a concrete evidence record
                -> binds exact provenance and values, including the origin decision

rules package   -> replays the origin decision and re-derives the obligation
                -> independently re-resolves every package_lookup
                -> validates the binding of every demonstrated_evidence record
                -> recomputes the comparison
                -> VerifiedComparisonResult, or refusal

downstream      -> consumes only a successfully recomputed result; no rule output alone
                   reads as permission
```

The guarantee is **verifiable and tamper-detecting, not unforgeable**. Trust comes from the
recomputation; the binding detects tampering, a stale package, or a different input set. Replay
proves *this approved package emits this obligation for these recorded inputs* — it does not
prove the consumer chose the correct engineering inputs, which remains #36's own review burden.

### Operand sources and their trust levels

```text
package_lookup          independently reproducible from the approved package
demonstrated_evidence   provenance, binding and method verifiable;
                        the underlying engineering evidence is not reproducible by the package
```

The demonstrated side binds to a concrete evidence record — identity and digest, method,
demonstrated quantity, value, unit, and test or simulation context — never to a caller asserting
a number. The verifier establishes that the record is the one supplied, that its method is the
one the origin decision matched on, and that the comparison used its exact result. It cannot
establish that the underlying laboratory test or simulation was physically correct, and the spec
never claims otherwise.

Which role may take which source kind is a constraint of the obligation contract itself,
validated at projection time and re-checked by `from_decision`: a withstand-requirement role is
`package_lookup` only, a demonstrated-result role `demonstrated_evidence` only. Otherwise
permission-by-assertion returns through the operand model.

## The operations

One closed vocabulary, explicitly directional. Asymmetric operations identify each operand's
semantic role, so reversing operands cannot silently change the result — reversing the floor
comparison would permit exactly what the floor forbids.

| Operation | Symmetric | Result payload |
|---|---|---|
| `TAKE_MORE_SEVERE` | yes | the selected resolved requirement |
| `MUST_NOT_EXCEED` | no | verified satisfaction or failure |
| `MUST_NOT_FALL_BELOW` | no | verified satisfaction or failure |

Operation-specific outcome data lives inside one `VerifiedComparisonResult` framework. There is
one verifier, one arithmetic implementation, one binding format.

## The bundle encoding

An obligation travels as an atomic, named bundle of ordinary declared decision outputs — no
change to `DecisionValue` or the archive:

```text
comparison_operation                  categorical, closed vocabulary
comparison_<role>_source_kind         categorical: package_lookup | demonstrated_evidence
comparison_<role>_reference           reference: the route a package_lookup resolves
```

Role names are fixed per rule, since `DecisionRule` declares outputs once. There is **no
"not applicable" state**: a route whose rows sometimes carry no obligation is split so that the
obligation-emitting route answers `no_match` where no obligation exists. Every matched row on an
obligation route therefore carries a complete, real bundle.

`ComparisonObligation.from_decision(result)` is the only sanctioned reader. It refuses partial,
duplicated or contradictory bundles; an operation outside the vocabulary; a role the operation
does not define; a source kind the operation does not permit for that role; a `package_lookup`
operand without a reference or a `demonstrated_evidence` operand with one.

### Constrained lookups

A `package_lookup` operand does not merely name a route. It carries **required lookup bindings**
assembled from the origin decision's outputs and inputs — the normatively determined selectors:

```text
propagation   transferred_requirement:      overvoltage_category <- origin.transferred_ovc
                                            supply_side          <- origin.rating_basis_side
floor         reduced_requirement:          overvoltage_category <- origin.target_ovc
              unreduced_basic_requirement:  overvoltage_category <- origin.source_ovc
```

The verifier rejects a concrete lookup whose normalized inputs violate these bindings. Without
this, a consumer could faithfully rerun the *wrong* Table 7 query and have it pronounced
verified. The split is: normatively determined selectors are enforced by the obligation;
actual engineering quantities (the system voltage of the correct circuit) are supplied by #36
and bound-and-replayed.

## Origin replay

The binding also binds the decision that emitted the obligation:

```text
origin:  decision_rule_id, decision_rule_sha256, normalized_decision_inputs,
         matched_row, obligation_sha256
```

Verification begins by locating the origin rule in the current approved package, verifying its
hash, re-running `evaluate_decision` with the recorded inputs, requiring the same matched row,
re-deriving the obligation through `from_decision`, and requiring the same obligation hash. Only
then are operands materialized and the comparison recomputed. The trust chain:

```text
reviewed fact -> approved DecisionRule -> verified replay -> verified obligation
             -> verified/recomputed operands -> recomputed comparison
             -> VerifiedComparisonResult
```

Origin replay is also what enforces the permitted evidence method at runtime with no importer
reach-back: the origin decision's `attenuation_evidence_kind` input is among the recorded
inputs, and the verifier requires the demonstrated record's method to equal it exactly. Method
and result are never collapsed into one field.

## The full binding

```text
package_content_digest        (importer version alone is not package identity)
operation
origin                        (as above)
per operand:
  role, source_kind
  package_lookup              rule_id, rule_sha256, required_lookup_bindings,
                              normalized_lookup_inputs, resolved_value, unit
  demonstrated_evidence       record_id, record_sha256, method, quantity, value, unit, context
```

Mismatched units are refused outright, never compared as raw magnitudes.

## Refusal taxonomy

The distinction below is load-bearing and must never blur: a comparison **failure** means the
engineering candidate genuinely fails the requirement; a verification **error** means what was
compared could not be established.

```text
comparison result   satisfies | fails            (first-class VerifiedComparisonResult)

verification error  from_decision refusals; origin replay mismatch (rule hash, matched row,
                    obligation hash); binding invalidity (package digest, rule hash,
                    lookup-binding violation, unit mismatch, evidence method differing from
                    the origin's recorded evidence-kind input)      (exceptions)

no_match            unsupported reduction pair; ineligible verification query;
                    no floor for this insulation class
```

## The three contracts

### Item 3 — multiple-source propagation

Ported to reviewed facts; leaves `LEGACY_BRANCH_AUTHORITY_RULE_IDS`, which becomes the empty
frozenset — #53C's first acceptance criterion.

Every normative statement stays reviewed authority, including the comparison itself — the whole
point of this item is that `TAKE_MORE_SEVERE` must come from a reviewed statement rather than from
the projector knowing which route it is. So the family carries a variant per statement kind under
`fact_kind="propagation_step"`:

```text
PropagationTransferFact       (a transfer statement)
    evaluated_side, source_side, permitted_transitions (enumerated in the one fact),
    rating_basis_side

PropagationComparisonFact     (a comparison statement)
    evaluated_side, candidate_roles, comparison = take_more_severe
```

Which physical item of the clause carries which statement is the reviewer's reading, recorded
privately through each fact's citations — never in this public document.

The comparison operation comes from the reviewed comparison statement, never from the projector
knowing it happens to be propagation. The permitted one-level transitions are enumerated inside
one transfer fact, preserving one fact per normative statement. Enumeration is expressible as
reviewed facts; comparison-as-operation was not, which is why this route was the legacy
exception.

```text
inputs    evaluated_side, source_side_ovc, galvanic_isolation_verified
outputs   transferred_ovc (categorical, from the enumerated transition)
          + one TAKE_MORE_SEVERE bundle:
              transferred_requirement    package_lookup, bound to origin.transferred_ovc
                                         and origin.rating_basis_side
              destination_requirement    package_lookup, the destination side's own rating route
```

`galvanic_isolation_verified=False` answers `no_match`: the reviewed transfer statements are scoped
to verified isolation, and the unisolated case is barrier transfer's route. The projector
refuses (`ClauseStructureError`) to emit a bundle when the route's comparison fact is missing —
a fact-derived comparison whose fact is absent is an incomplete review, not a default.

### Item 4 — HF-transformer attenuation

The existing route keeps its informational rows — an absent evidence method still answers
"requirement outstanding, permitted methods are these" and emits no bundle. The permission
boolean `working_voltage_basis_permitted` is **deleted**, not defaulted false: its existence is
a permission-shaped output, and permission exists only as a verified result.

A new route emits the obligation, gated on the complete eligibility the source states:

```text
supply.hf_transformer_attenuation.verification
  inputs    circuit_dvc, transformer_frequency_hz, isolation_provided,
            attenuation_evidence_kind
  matched   only when DVC gate AND frequency threshold AND galvanic isolation AND
            permitted evidence kind all hold
  outputs   one MUST_NOT_EXCEED bundle:
              demonstrated_impulse     demonstrated_evidence
              withstand_requirement    package_lookup -> the Table 7 route for the
                                       working-voltage-associated requirement
```

Eligibility lives in the origin decision so that replay proves the obligation was emitted under
the complete conditions — frequency or isolation missing from the origin would let a valid
comparison become permission outside the clause's scope. The frequency threshold remains
fragment-derived (an existing test pins this); it is never a declared constant.
`HfAttenuationFact.threshold_reference` and `comparison_required` become consumed, closing the
disclosure recorded at review finding F9. `DemonstratedEvidenceRecord` lives in
`rules/comparison.py`: it is runtime consumer input, not a reviewed fact.

### Item 5 — SPD / category reduction

> **Partly landed in #53B — see L6.** The right-sizing half of this item shipped with #53B's
> `spd_reduction` family split, because the split made the merged rule unprojectable. Start from the
> shipped contract below rather than from the pre-split one; what remains here is the comparison half.

The consumer proposes the exact pair; the reviewed rule validates it. No ordinal subtraction,
no inferred target, anywhere.

```text
spd_reduction_requirements.mains         input source_overvoltage_category landed in #53B;
                                         this item adds target_ovc and validates the pair
                                         unsupported pair -> no_match
  outputs   monitoring_requirement_reference   (consumes SpdReductionMonitoringFact
                                                .monitoring_reference -- see L2)
            floor_obligation_reference

spd_reduction_requirements.mains.floor   matches supported pair + insulation_class in
                                         (double, reinforced); basic/supplementary -> no_match
  outputs   one MUST_NOT_FALL_BELOW bundle:
              reduced_requirement            package_lookup, bound to origin.target_ovc
              unreduced_basic_requirement    package_lookup, bound to origin.source_ovc,
                                             basic insulation

(non_mains and non_mains.floor identically)
```

A pair match is a **validated candidate, not final permission**: its outputs are references into
the rest of the chain, so monitoring stays in the chain structurally rather than relying on #36
to remember an unrelated route. The two `no_match` meanings are deliberately separated by route:
on the pair route it is a refusal; on the floor route it means no floor exists for this class.

Each floor route is projected by its own reduction clause spec through `projected_rule_ids`, so
it is grounded in that clause's fragment with no shared-evidence scope. The floor reading is carried
by #53B's `SpdReductionFloorFact` variant rather than by a new family, and the floor route becomes the
**sole** floor authority: the `reinforced_floor_applies` output goes with it. (Both
`_FLOORED_INSULATION_CLASSES` and that output are already gone from the reduction routes — #53B
deleted the first in `fbe8ab5` and the second with the right-sizing in L6.) Two authorities for one
reading is the defect class this whole issue removes.

`reduced_category` is dropped as an output: the consumer proposed the target, and echoing it
back is permission-shaped noise. It survives on the shipped contract only because nothing proposes a
target yet.

## Module ownership

One new module, `rules/comparison.py`: the obligation and operand types,
`DemonstratedEvidenceRecord`, the binding types, the arithmetic, and the verifier. It mirrors
`rules/evaluator.py` as the runtime import surface and must not import the importer — obligations
are a runtime contract; the importer is a build-time concern. Nothing in `domain/rules.py`
changes.

## Testing

Public, synthetic throughout — no IEC numeric content:

- **The ordinal-vs-rating regression (issue-mandated):** synthetic Table 7-style rules where,
  because the two sides use different system voltages, the *lower* OVC candidate resolves to the
  *higher* numeric impulse requirement. Proves selection by resolved severity, not category
  ordinal.
- **`LEGACY_BRANCH_AUTHORITY_RULE_IDS == frozenset()`**, plus the stronger pair: propagation
  refuses projection when the transfer fact is missing, and when the comparison fact is missing.
- Projection-time completeness: every matched row on every obligation route parses through
  `from_decision`.
- Parser refusals, one per malformed-bundle class.
- Verifier refusals, one per class: stale package digest, tampered rule hash, origin replay
  row/obligation mismatch, lookup-binding violation (the wrong-query case), unit mismatch,
  operand reversal on the floor, evidence method differing from the origin's recorded input.
- Comparison failure as a first-class result — a floor genuinely not met is `fails`, never an
  exception, and never conflated with a verification error.
- HF eligibility: one `no_match` per unsatisfied condition.

Private, licensed: per-route statement inventories gain the propagation variants and the floor
family, by fact family and typed identity, never by count in public code; and the full authored
round-trip proves the three contracts project from real facts.

## Contract impact

An importer version is **assigned at implementation time, in merge order** — never reserved here.
See ledger note L5. The settled sequence today is #60 = ``iec-pdf-7``, the #53B stack =
``iec-pdf-8``, and this spec = ``iec-pdf-9``; that is the current expectation, and this spec's own
number is decided when it is implemented.

```text
#53C:       IEC_IMPORTER_VERSION  bumped once, number assigned on implementation
            LEGACY_BRANCH_AUTHORITY_RULE_IDS -> frozenset()
            removed:  working_voltage_basis_permitted, reduced_category,
                      reinforced_floor_applies
                      (_FLOORED_INSULATION_CLASSES already deleted by #53B)
            added:    hf_transformer_attenuation.verification
                      spd_reduction_requirements.mains.floor
                      spd_reduction_requirements.non_mains.floor
                      rules/comparison.py

unchanged:  evaluate_decision, DecisionValue, RulePackage archive schema
```

Archive **schema** unchanged; package **compatibility identity** changed — a package built
before this slice must be rebuilt and re-reviewed, never served as current.

---

# Amendment ledger (2026-08-14) — carried in from the #53B five-family review

Ledger notes only. **No item is implemented by #53B**; each is a correction or addition to this
spec's own scope, recorded so the #53C work starts from the reviewed shapes rather than from the
shapes this document assumed. Decisions and structures only; no source wording, no inventory.

## L1 — Missing acceptance criterion: the unisolated combined circuit

Item 3 defines the more-severe comparison bundle for the **isolated** propagation route, and states
that the unisolated case answers no match because it belongs to barrier transfer's route. **No item
of this spec then upgrades that route.** Barrier transfer keeps a semantic token naming the
selection instead of performing it — the exact shape item 3 exists to eliminate.

Added criterion: after #53C, the unisolated combined circuit must **select the higher of the two
resolved side ratings** through a real comparison, and must not remain a semantic token. It shares
item 3's comparison bundle rather than introducing a second mechanism.

The reviewed shape #53B is landing already fits: barrier transfer's `combined_requirement` variant
carries the candidate roles and the selection, which mirrors item 3's own pairing of candidate roles
with a comparison.

## L2 — Correction: the monitoring reference moves off the permission statement

This spec's reduction outputs describe the monitoring-requirement reference as consumed from the
**permission** statement. After #53B's family split (design amendment A3) that reference belongs to
the reduction family's **monitoring** variant.

The reason is substantive, not cosmetic: the source states a separate normative monitoring
statement, so the runtime chain must compose from separately reviewed authorities rather than
reading a reference the permission statement never makes.

## L3 — New item needed: the system-voltage applicability output

#53B's system-voltage family gains an **applicability** variant for a statement that establishes
which voltages count as system voltages for impulse determination and selects no measure. #53B
carries such a statement without projecting it: resolution accepts it, the fact-set digest covers
it so completion and the approval gate know it was reviewed, and it contributes no row and no
output. The executable output contract is unchanged.

This spec needs an item that **consumes** it — an applicability output alongside the measure
selection. Until then the gap is explicit rather than papered over, and no projector manufactures a
measure to fit.

## L4 — Confirmed unaffected: the floor route stays the sole floor authority

This spec's plan for a dedicated floor route, projected from the reduction clause spec and becoming
the sole floor authority, survives the family split and is helped by it: #53B's reviewed **floor**
variant is what that route will consume, so the reviewed shape now lands ahead of the runtime route
rather than after it.

## L5 — Versioning numbers are no longer reserved

This spec assumed a reserved importer-version increment. The #53B branch has consumed one increment
for a clause-region correction, and a further region-widening slice may consume another after
inspecting whether any trusted package exists under the affected versions. **This spec's version
number is decided when it is implemented**, not reserved here.

## L6 — Item 5's contract change has landed in #53B; start from the shipped contract

Item 5 bundled two separable things: **right-sizing** the reduction routes' inputs and outputs, and
the **comparison** that validates a proposed pair against a floor. #53B's `spd_reduction` family split
forced the first half forward, because the split made the merged rule unprojectable: with the
family's three readings separated, the permission's ordered step collection could not fill a
single-valued `reduced_category`, and the permission's row and the monitoring statement's row
necessarily overlapped on every degradable device inside a reduction. The maintainer authorized
pulling the right-sizing in rather than accepting either a wrong runtime answer or a projector-invented
matcher. The full analysis and the rejected alternatives are in the #53B plan's handoff.

**Shipped in #53B, for `.mains` and `.non_mains` only:**

```text
spd_reduction_requirements.<supply kind>
  inputs   source_overvoltage_category, insulation_class, part_of_category_reduction
  outputs  reduction_permitted, reduced_category

spd_reduction_requirements.<supply kind>.device_monitoring
  inputs   device_degradable
  outputs  monitoring_required, status_indication_required, monitoring_reference
```

`device_placement` and `device_degradable` are gone from the permission rule -- the permission scopes
neither -- and the monitoring, verification and floor outputs are gone with them. The second rule is
projected only when a `monitoring` statement is reviewed for the route, and both ids are declared in
the clause specs' `projected_rule_ids`, so the inventory gate requires them.

**Still this spec's, unchanged:** everything comparison-shaped. The `target_ovc` input and the
pair validation, the `.floor` route and its `MUST_NOT_FALL_BELOW` bundle, `floor_obligation_reference`,
and turning `monitoring_reference` from a reference output into a resolved chain step. #53B's floor
variant is reviewed and carried, projecting nothing, which is exactly the shape the floor route
consumes.

**Not in scope of the #53B change, and still this item's:** the SPD *placement* monitoring route
(`spd_reduction_requirements.monitoring`) keeps its four inputs and six outputs, three of which it
still fills with a fixed uninformative value. Right-sizing that route is unchanged work here.
