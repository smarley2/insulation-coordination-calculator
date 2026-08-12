# Issue #53B — the licensed clause becomes the authority for its own branches

The Slice D supply rules are derived from a pipeline that checks a clause's *shape* and then
builds its normative branches from Python constants. `ClauseAuditSpec` confirms a root kind and
a node count; `recipes/iec62477_1_2022/supply.py` independently encodes the categories, the
permitted reductions, the evidence kinds and the comparison. A reprint that changed a branch
while keeping the same rough bullet shape would satisfy extraction and silently regenerate the
old branch inventory.

This is #53 item 7. It is the second of three sub-projects: #53A gave both DVC tables reviewed
semantic selectors; #53B moves branch authority from public constants to reviewed private facts;
#53C then writes the four Slice D supply contracts (#53 items 3 to 6) on top of this pipeline
rather than against the constants #53B removes.

## What a reviewed statement is

The reviewed unit is one **normative statement**, which may draw on several clause nodes and cite
others. It is not free text, because a projection has to execute it, so it is typed per rule
family — a discriminated union, as `AxisSelector` is in #53A:

```text
SupplyFact = SystemVoltageFact | PropagationStepFact | BarrierTransferFact
           | SpdReductionFact  | HfAttenuationFact

every member carries:
    statement_index    which statement of this route this is
    node_references    the fragment nodes it rests on, plural
    obligation         requirement | permission
```

Per-family payloads, fixed by the source reading that preceded this design:

```text
SystemVoltageFact    phase_system, earthing, purpose, measure
PropagationStepFact  step, evaluated_side, operation, rating_source_side
SpdReductionFact     supply_kind, source_ovc, target_ovc, insulation_class,
                     degradable, participates_in_reduction, monitoring_obligation
HfAttenuationFact    dvc_gate, evidence_kind, threshold_reference, comparison_required
BarrierTransferFact  isolation_present, combined_circuit_rule
```

Three consequences of this shape:

**The branch inventories are deleted, not refactored.** `_OVERVOLTAGE_CATEGORIES`,
`_reduced_by_one_level`, `_more_severe`, `_REDUCED_CATEGORIES`, `_ATTENUATION_EVIDENCE_KINDS`,
`_REQUIRED_EVIDENCE_KINDS` and their siblings stop being the authority. What stays in public code
is the neutral vocabulary each field draws from, which #53 item 7 explicitly permits, and nothing
that says which combinations the source licenses.

**The token machinery is demoted, not deleted.** `ClauseToken` remains private evidence a
reviewer reads. It no longer decides a branch.

**`(node kind, node count)` stops being the contract.** After #53B a statement's review binds the
evidence it rests on, so any change to that evidence re-opens it. The "same rough shape, different
branch" failure becomes impossible rather than merely unlikely.

## Where proposed statements come from: nobody

The importer proposes the **node inventory only**. It never proposes a statement. The maintainer
reads the fragment in the review surface and authors each statement as typed fields with the
nodes it rests on.

This is stricter than #53A, where three of four axes get a keyword grammar. The reason is the
public-record limit: a grammar that proposed statements would need vocabulary chosen against the
source's own phrasing, and for clause prose that is not a short neutral keyword but the shape of
the sentence. Authoring is real review work, repeated whenever cited evidence changes, and it is
the price of the licensed clause being the authority in fact and not only in wording.

## The pipeline

```text
reviewed clause fragment (nodes + tokens, private)
  -> importer proposes the node inventory
  -> reviewer authors typed SupplyFacts, each citing the nodes it rests on
  -> reviewer records a completion record for that (clause, rule route)
  -> CLAUSE_FACT_REVIEW_REQUIRED blocks approval until facts and completion are current
  -> resolve_confirmed_clause_facts(spec, fragment, draft) -> ConfirmedFacts
  -> the clause projector builds its rule from approved facts only
```

The clause projector already takes three parameters and has `draft` in scope at its call site, so
unlike #53A there is no projector-interface migration.

### Binding: each fact binds the evidence it actually cites

```python
class ClauseFactReview(FrozenModel):
    rule_route: Identifier
    statement_index: int
    fact: SupplyFact
    fact_sha256: str  # canonical hash of the authored fact
    evidence_sha256: str  # canonical digest of every cited node's identity and content
    actor: str
    recorded_at: datetime
    notes: NotesText
```

`evidence_sha256` is the canonical digest over the sorted tuple of
`(fragment_id, node_order, canonical_model_sha256(node))` for every node the fact cites. A fact
may therefore rest on more than one fragment, which the SPD routes require: the reduction
statements rest on their own clause, and the monitoring-obligation statement additionally cites
the monitoring clause.

The granularity is deliberate. If the monitoring clause changes while the reduction clause does
not, exactly the facts citing the monitoring clause go stale. A change to an uncited sibling node
in the same fragment re-opens nothing, because no fact ever rested on it. Reordering nodes does
invalidate, because a node's order is part of the identity a fact cited.

### Completeness: a reviewed assertion, not a published number

Nothing can force a reviewer to author every statement a clause contains, and the completeness
gate must not become a published account of the source's normative structure. So:

- **Public gate:** a `ClauseFactCompletion` record per `(clause, rule route)`, asserting the fact
  set for that route is complete, bound to both the exact fragment hash and the exact digest of
  the reviewed fact set. Approval blocks without a current one.
- **Private gate:** the licensed-document tests independently assert the expected statement
  inventory per route, by fact family and typed identity rather than by cardinality alone.

No per-clause normative statement count appears in the public recipe.

The completion scope is `(clause, rule route)` and not the fragment, because a fragment may carry
statements belonging to rules outside this route. `4.4.7.2.3` and `4.4.7.2.4` also state
overvoltage-category selection, which #53B does not author: a completion record asserts that this
route's fact families are complete, never that the clause has been exhausted.

## The provenance correction the reduction rule needs

`SUPPLY_SPD_REDUCTION_REQUIREMENTS` is specced against the clause that states the SPD monitoring
requirement. The category-reduction rule it claims to carry is stated in the mains clause
`4.4.7.2.3` and again in the non-mains clause `4.4.7.2.4`, each permitting its own source-to-target
category steps, each carrying the same floor for double and reinforced insulation, and each
deferring monitoring to `4.4.7.2.2`. Neither of those two clauses is extracted today.

A reviewed-fact layer cannot be built against a fragment that does not contain the rule, so #53B
corrects the provenance:

```text
iec62477_2022.supply.spd_reduction_requirements
    .mains       <- new fragment, clause 4.4.7.2.3
    .non_mains   <- new fragment, clause 4.4.7.2.4
    monitoring   <- clause 4.4.7.2.2 stays extracted, cited as evidence
```

Two suffixed routes, because the source states the rule twice with different permitted steps — a
family that genuinely fans out, which is what a suffix is for, and the opposite of #52 where one
identifier covered two unrelated jobs.

This is a provenance and authority correction, not an implementation of #53 item 5. The full
supply-kind-dependent reduction contract — the typed context, the enumerated permitted steps, the
floor behaviour and the monitoring obligation as executable inputs — is #53C's work, consuming
these reviewed facts.

## The seam with #53C

Every projector whose existing executable contract can be faithfully generated from reviewed facts
migrates in #53B. One cannot, and it is the documented exception:

```text
ported in #53B      supply.system_voltage_resolution
                    supply.verified_barrier_transfer
                    supply.hf_transformer_attenuation
                    supply.spd_reduction_requirements   (route structure also corrected)

legacy in #53B      supply.multiple_source_propagation
```

Propagation's current contract *is* the ordinal category comparison, and no honest fact says
"compare ordinals": porting it faithfully would mean changing behaviour, which is #53 item 3 and
belongs to #53C. It therefore keeps legacy branch authority in #53B, recorded in an explicit
`LEGACY_BRANCH_AUTHORITY_RULE_IDS` frozenset rather than a comment, so it is assertable.

**Removing that exception is #53C's first acceptance criterion.**

## Tests

1. **Facts are the only authority.** For each ported projector: approved facts that differ from the
   deleted constants produce the changed rule, and projecting without `ConfirmedFacts` raises
   rather than falling back. Together these prove the constants dead, not merely unreferenced.
2. **The exception is exactly one.** `LEGACY_BRANCH_AUTHORITY_RULE_IDS` contains the propagation
   identifier and nothing else, and every other supply rule refuses to project factless. This
   test failing is #53C's first criterion being met.
3. **Completion gating**, one case each: facts authored with no completion record; completion bound
   to a stale fragment hash; completion bound to a stale fact-set digest; no facts at all. All
   block approval.
4. **Evidence granularity.** Changing a cited node re-opens exactly the facts citing it; changing
   an uncited node in the same fragment re-opens nothing; reordering nodes re-opens the facts that
   cited the moved nodes.
5. **The provenance correction.** The SPD identifier's two routes read the mains and non-mains
   fragments; the monitoring clause remains extracted and is cited by the monitoring-obligation
   fact rather than being the reduction's source.
6. **Private, licensed.** Per-route expected statement inventory by fact family and typed identity,
   and a reviewed, completed licensed draft projecting the three faithfully-ported rules
   identically to today.

## Package and review consequences

```text
IEC_IMPORTER_VERSION   iec-pdf-5 -> iec-pdf-6
    => a package built before #53B is rejected and rebuilt
```

For the rebuilt draft, review state follows the #53A principle that nothing unchanged is
invalidated unnecessarily:

```text
changed authority, fact set or hash   -> renewed review required
unchanged proposal and hash           -> the existing review remains current
propagation                            -> legacy authority in #53B, so no semantic-review
                                          invalidation merely because #53B exists
```

The SPD routes do need new review: their route structure and provenance genuinely change.

The two new draft collections — authored facts and completion records — must be added to
`approval.py`'s change-detection tuple and to every digest rebuild site that names each draft-only
collection explicitly, not only to `_content_digest`'s signature. #53A's first task missed exactly
this and a fact-only change compared equal to its original; the plan must carry it as a step with
a test that fails without it.

Facts and completion records are draft-only, like `curve_variant_reviews` and #53A's axis reviews:
`approve_draft` builds the package from the rules themselves, so the `.icrules` archive format does
not grow a new concept.

## Public-record limit

Committed files carry semantic identifiers, neutral field vocabularies, clause and table locators,
structural indexes, and the typed shapes above.

They do not carry statement text, clause or heading wording, numeric source content, per-clause
statement counts, or the mapping from a physical node to a statement. Those stay in the licensed
documents and the private review layer.

## Out of scope

#53C's four contracts, including propagation's comparison, the HF verification result, the full
SPD reduction context and the system-voltage distinctions. The overvoltage-category selection
statements that share the two new fragments. Any #36 consumer wiring. The generic decision
evaluator, which is unchanged.
