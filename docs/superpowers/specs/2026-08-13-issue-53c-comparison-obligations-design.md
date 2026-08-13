# Issue #53C items 3-5 — permission only after a verified comparison

Three supply rules grant permission from a proxy for a requirement instead of the requirement
itself. Multiple-source propagation compares overvoltage-category ordinals where the source
requires comparing resolved impulse ratings. HF-transformer attenuation permits working-voltage
treatment because an evidence method exists, where the source requires the attenuation to be
shown sufficient. SPD reduction subtracts a category level generically where the source states
specific permitted steps, and treats the double/reinforced floor as an ignorable flag where the
source states a comparison.

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

Every normative statement of the clause stays reviewed authority. The clause states two kinds of
statement — transfer statements and comparison statements, each kind once per evaluated direction —
so the family has two variants under `fact_kind="propagation_step"`:

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

`galvanic_isolation_verified=False` answers `no_match`: the source scopes the reduce-one-level
step to verified isolation, and the unisolated case belongs to barrier transfer. The projector
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

The consumer proposes the exact pair; the reviewed rule validates it. No ordinal subtraction,
no inferred target, anywhere.

```text
spd_reduction_requirements.mains         inputs gain source_ovc, target_ovc
                                         unsupported pair -> no_match
  outputs   monitoring_requirement_reference   (consumes SpdReductionFact.monitoring_reference)
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
it is grounded in that clause's fragment with no shared-evidence scope. A new small fact family
carries the floor statement — it is its own normative sentence in each reduction clause — and it
is the **sole** floor authority: the `reinforced_floor_applies` output and the
`_FLOORED_INSULATION_CLASSES` constant are deleted with it. Two normative authorities for one
statement is the defect class this whole issue removes.

`reduced_category` is dropped as an output: the consumer proposed the target, and echoing it
back is permission-shaped noise.

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

```text
#60 first:  IEC_IMPORTER_VERSION  iec-pdf-6 -> iec-pdf-7   (#60 owns this bump)

#53C:       IEC_IMPORTER_VERSION  iec-pdf-7 -> iec-pdf-8
            LEGACY_BRANCH_AUTHORITY_RULE_IDS -> frozenset()
            removed:  working_voltage_basis_permitted, reduced_category,
                      reinforced_floor_applies, _FLOORED_INSULATION_CLASSES
            added:    hf_transformer_attenuation.verification
                      spd_reduction_requirements.mains.floor
                      spd_reduction_requirements.non_mains.floor
                      rules/comparison.py

unchanged:  evaluate_decision, DecisionValue, RulePackage archive schema
```

Archive **schema** unchanged; package **compatibility identity** changed — a package built
before this slice must be rebuilt and re-reviewed, never served as current.
