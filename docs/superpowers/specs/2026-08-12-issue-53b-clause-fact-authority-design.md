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
                     degradable, monitoring_obligation, monitoring_reference
SpdMonitoringFact    device_placement, participates_in_reduction, monitoring_required,
                     compliance_evidence
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

## Where proposed statements come from: nobody in public code

The importer proposes the **node inventory only**. **Public code never proposes a statement.** The
maintainer reads the fragment in the review surface and authors each statement as typed fields with
the nodes it rests on.

This is stricter than #53A, where three of four axes get a keyword grammar. The reason is the
public-record limit: a grammar that proposed statements would need vocabulary chosen against the
source's own phrasing, and for clause prose that is not a short neutral keyword but the shape of
the sentence. Authoring is real review work, repeated whenever cited evidence changes, and it is
the price of the licensed clause being the authority in fact and not only in wording.

**Amendment A1 refines where such a grammar may live, not whether it may exist.** A grammar mapping
source phrasing to typed normative meaning is licensed-derived material: it loads only from beside
the licensed extraction and review material, never from the public tree. What stays public is the
generic engine — sentence segmentation, the generic typed proposal shape, prefill rendering, and
validation that a proposal names only declared dimensions and declared values. A proposal is a
suggestion the maintainer reviews against the statement and its evidence and then explicitly
authors, one statement per action. It carries no authority and reaches no projector except as an
authored fact.

## The pipeline

```text
reviewed clause fragment (nodes + tokens, private)
  -> importer proposes the node inventory
  -> [private grammar, where the licensed material lives] suggests dimensions per statement
  -> reviewer reviews ONE statement's suggested dimensions and its evidence
  -> reviewer authors typed SupplyFacts, each citing the nodes it rests on, one action per fact
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
`(fragment_id, node_order, canonical_model_sha256(node))` for every node the fact cites. The model
therefore permits a fact to rest on more than one fragment, where a statement genuinely does.

The SPD routes are not such a case, which the family split settled: the reduction clause refers to
the monitoring obligation, it does not restate it, so `SpdReductionFact.monitoring_reference` is an
`Identifier` naming the monitoring route rather than a citation of it. A reduction fact cites only
its own clause. Every fact must cite its own route's fragment, and may cite a second only in
addition — never instead.

The granularity is deliberate. Reprinting the monitoring clause re-opens the `.monitoring` route
alone: `monitoring_obligation="required"` stays current on the mains and non-mains reduction facts,
because their own clause still says monitoring is required per that clause. What changed is what
the monitoring clause *requires*, and the monitoring route re-opens to carry it. Reordering nodes
does invalidate, because a node's order is part of the identity a fact cited.

How much that granularity buys depends on the route, and the claim is narrower than it first
looks: node-level evidence permits **selective** invalidation only where a route's fragment
carries several independently citable nodes. Measured against the licensed document, only
`supply.system_voltage_resolution` (three bullet nodes) and `supply.multiple_source_propagation`
(four) do — and propagation is the legacy route resolution skips. Every other supply route
extracts as a single paragraph node, so for those routes node-level and fragment-level
invalidation are the same thing. Nothing is lost by that; the mechanism is simply not doing extra
work where a clause has one node. It does mean a regression test for selective invalidation
belongs on a genuinely multi-node route, and that a single-node route should instead prove the
property it actually has: changing its one cited node makes both the fact review and the route's
completion stale.

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
4. **Evidence granularity.** Changing a cited node re-opens exactly the facts citing it, and
   reordering nodes re-opens the facts that cited the moved nodes. Selective invalidation — an
   uncited node changing in the same fragment re-opening nothing — is asserted on a route whose
   fragment really has several nodes, which means `supply.system_voltage_resolution`, since
   propagation is the legacy route resolution skips. Single-node routes assert instead that
   changing their one cited node makes both the fact review and the route completion stale.
5. **The provenance correction.** The SPD identifier's reduction routes read the mains and
   non-mains fragments, each citing only its own clause; the monitoring clause is no longer the
   reduction's source but the `.monitoring` route's own fragment, carrying its own fact family.
6. **Private, licensed.** Per-route expected statement inventory by fact family and typed identity,
   and a reviewed, completed licensed draft projecting the three faithfully-ported rules
   identically to today.

## Package and review consequences

```text
IEC_IMPORTER_VERSION   bumped once for this whole stack; the number is assigned in merge
                       order at implementation time and is currently iec-pdf-8
    => a package built before #53B is rejected and rebuilt
```

See A6-C for what the bump covers -- extracted evidence *and* projected rule semantics -- and why
one increment is enough for the whole stack.

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

---

# Amendments (2026-08-14) — approved after live maintainer review of five clause families

Decisions and structures only. No source wording, no statement inventory, no per-clause counts, no
node-to-statement mapping. Amendments A1-A7 are binding on the remaining #53B work.

## A1 — Proposer boundary: private grammar, public engine, one fact per action

The original rule ("nobody proposes a statement") was implemented as a keyword grammar in **public
recipe code** that derived complete typed normative readings from licensed text, plus a route-level
action that authored every complete reading at once. Audit verdict: a deviation. A mapping from
source phrasing to typed normative meaning is normative content however generic each half looks in
isolation, and one click certifying several machine-derived facts is not review.

Binding:

- **Public** keeps the generic engine only: sentence segmentation, the generic typed proposal shape,
  prefill/highlight rendering, and validation that a proposal names only declared dimensions and
  declared values. Nothing in the public tree may name source phrasing.
- **Private** carries any grammar mapping phrasing to meaning. It loads only from where the licensed
  extraction and review material lives, exactly as the licensed documents do.
- **Flow:** private proposal -> prefill/highlight suggested dimensions -> maintainer reviews **one**
  statement, its dimensions and its evidence -> maintainer explicitly authors that fact.
- **Removed:** any action authoring several statements at once. A per-statement "use suggested
  values" action is permitted, provided the reviewer still explicitly authors after seeing the
  dimensions and the evidence.
- Consequence: the module contract "a statement is authored by a maintainer from the private
  fragment, never proposed by public code" becomes true again, and is asserted rather than stated.

## A2 — `DimensionScope`: the reusable categorical scope, and the wildcard defect

A single generic representation replaces per-dimension `any_*` tokens:

```text
DimensionScope
    mode:   unrestricted | exact_one | exact_set
    values: ()            | (one,)   | (two or more,)
```

Projection maps to matchers that already exist: `unrestricted -> op="any"`,
`exact_one -> op="equals"`, `exact_set -> op="in"`. Row-overlap rejection already compares
categorical `equals`/`in` by value-set intersection and needs no change.

**Where the source enumerates a finite set, the authored scope is `exact_set` — never
`unrestricted`.** One reviewed statement projects to exactly one row; a set is never expanded into
several facts or several rows.

**Wildcard defect, fixed in the same work.** `unrestricted` previously mapped to a matcher over the
whole *declared consumer* vocabulary, which is wider than the reviewed vocabulary, so an
unrestricted reading silently answered for consumer-only states that no reviewed token names.
`unrestricted` now means unrestricted over the intended reviewed scope and never widens to a
consumer-only state.

The precedent already in the codebase is the attenuation route's evidence matcher, which maps its
collective token to an explicit set over "every declared kind except the absence of one" rather
than to a bare wildcard. `DimensionScope` generalizes that one correct case.

Six per-dimension `any_*` tokens and the two ad-hoc matcher translators that exist only to
interpret them are deleted. The separate combined-designation token considered for the DVC gate is
**dropped**: that reading is `exact_set` over two designations, needing no new token and no
projection-time expansion.

## A3 — Statement variants: `statement_kind` inside `fact_kind`

Where one clause states normatively different *kinds* of reading, the family gains a secondary
discriminator rather than forcing every field onto one shape. Route-to-family declaration, the
family check in the fact defect predicate, resolution and the archive schema are all unchanged.

```text
system_voltage      measure       | applicability
spd_reduction       permission    | floor        | monitoring
spd_monitoring      requirement   | exemption    | compliance
barrier_transfer    rating_resolution | combined_requirement | downstream_inheritance
hf_attenuation      (one kind; the gate becomes a DimensionScope)
```

Rules that follow from it:

- A variant carries only the dimensions its own kind of statement states. No variant may force a
  dimension its statements do not state, and no projector may manufacture one to fit its output.
- **Structured pairs are one field, not two sets.** A statement enumerating category steps carries
  an ordered collection of source-to-target pairs. Two independent value sets would fabricate a
  cartesian product the reviewer never stated.
- **Collections need canonical ordering.** A validator sorts collection values by their declared
  vocabulary order and rejects duplicates. Without it a fact's hash is order-dependent and the
  duplicate-reading refusal is defeated.
- An applicability-style variant is **carried, not projected**: accepted by resolution, hashed into
  the fact-set digest so completion and the approval gate know the statement was reviewed, and
  contributing no row and no output. The executable output contract does not change. A route whose
  reviewed set cannot answer the rule's question refuses to project rather than emitting a
  zero-row rule.

## A4 — Route-declared structural scope, and context nodes

**Barrier transfer's isolation state becomes route-declared structural scope**, the way the supply
kind already is: it leaves the fact model, the fact defect predicate enforces it, and a statement
contradicting the route's declared scope cannot be authored at all. Authoring a positive-isolation
statement from a fragment whose scope is the unisolated case becomes impossible rather than merely
undocumented. The recipe's evidence-kind branch that only that impossible statement reached is
deleted as dead. The private placeholder that authored exactly that contradiction is invalid and is
replaced.

**Context nodes are not statements.** A node that scopes the statements following it — the opening
sentence a bullet list completes — selects no branch. It stays in the fragment as evidence and as
the modality source, but no proposal may be offered for it alone, and no statement may be
manufactured for it by filling its unstated dimensions with wildcards and an arbitrary answer. A
statement completing such an opener cites **both** nodes, which the plural citation shape and the
order-independent evidence digest already support, so the opener's movement re-opens the dependent
statement.

## A5 — Completion guard: a lower bound, never a redefinition

Completion could previously be recorded with one statement authored out of several, because nothing
compared authored statements against anything.

- **An uncovered known proposal prohibits completion.** A route with a proposal whose reading no
  authored statement carries cannot be completed.
- **No uncovered proposals permits completion; it does not constitute it.** Completion remains the
  maintainer's explicit assertion that no *additional* statement was missed. Completion is **not**
  redefined as "all proposals consumed", and the approval gate preserves that distinction: the guard
  is a lower bound on review, not a definition of it.
- Context-only nodes are not uncovered normative proposals.
- The guard is knowingly partial: it cannot catch a statement no proposal ever suggested. That is
  precisely why the maintainer's assertion remains the definition.

## A6 — Versioning

The importer version boundary is for changed **extracted evidence**. The statement-shape work in
this slice changes no fragment, and reviewed facts are draft-only and committed nowhere, so it
requires **no importer version change**: reshaped facts simply re-author and re-complete.

The clause-region correction is a separate, separately reviewed slice and does change extracted
evidence. That slice must first inspect whether any trusted or approved package was ever produced
under the affected versions before choosing its version, and must not assume the previously planned
numbering: this branch has already consumed one increment for the opener-region correction. The
reserved numbering for the following issues shifts accordingly and is decided in that slice's
report, not here.

## A7 — Duplicate proposals

Repeated draft rows for one statement were the proposer expanding a set-valued reading into one
draft per value. They disappear through `exact_set` and the structured-pair collections of A2/A3.
**No deduplication at the presentation layer**: a duplicate row is a modelling defect, and hiding it
would leave the defect and lose the signal.

---

# Amendment corrections (2026-08-14, follow-up) — maintainer interrupt during the DimensionScope slice

A2, A3, A5 and A6 as first committed were wrong or incomplete in the ways below. These corrections
supersede those paragraphs; the originals stay above as the record of what was corrected.

## A2-C — `unrestricted` does not unconditionally translate to a wildcard matcher

A2 as committed said `unrestricted -> op="any"` **and** claimed to fix the consumer-vocabulary
over-match. Those contradict each other: the evaluator's wildcard matcher returns true for every
value without inspecting it, so it still matches the whole declared consumer domain and the defect
survives.

Corrected generic translation contract:

```text
exact_one(value)   -> equals(value)
exact_set(values)  -> in(values)
unrestricted       -> any            ONLY when the reviewed domain equals the complete
                                     consumer input domain
                   -> in(reviewed_domain)   otherwise
```

`unrestricted` means unrestricted **within the statement family's reviewed semantic domain**, never
automatically over every value the consumer API declares. The matcher helper therefore takes both
the scope and the **reviewed dimension domain**, and chooses the wildcard or the set accordingly.

This generalizes the one place that already behaved correctly — the attenuation route's evidence
handling, which maps its collective token to an explicit set over the reviewed kinds precisely
because the declared vocabulary carries a value no reviewed reading may grant. Unconditional
`unrestricted -> any` is **not** preserved anywhere.

Required regression: reviewed domain `{A, B}`, consumer vocabulary `{A, B, unspecified}`, scope
`unrestricted` -> the projected row matches `A` and `B` and **not** `unspecified`.

## A3-C — internal family-model validation may change

A3 as committed promised the family check was unchanged. Corrected scope of that promise:

**External route/family contract unchanged; internal family-model validation may be adapted to the
discriminated union.** The route-to-family declaration, the family discriminator itself and the
archive schema are unchanged. The internal helper that maps a family to one concrete model class and
inspects its declared fields must be allowed to understand a variant union or a shared base instead,
because a family with variants no longer has a single model whose fields answer for all of it.

## A5-C — coverage binds to source-statement identity, not to proposal values

A5 as committed left coverage implicitly bound to the equality of the proposal's suggested values
and the authored fact's values. That is wrong, and it would invert the authority rule: a maintainer
who reviews the source, finds the suggestion wrong and authors corrected values would leave the
statement permanently "uncovered", and completion permanently blocked, **because they exercised
judgement**.

Corrected contract — coverage binds to the proposal's stable statement anchor plus its cited
evidence bundle:

```text
proposal P describes source statement S
authored fact F is explicitly authored for source statement S
-> P is covered
   even when hash(P.suggested_dimensions) != hash(F.reviewed_dimensions)
```

The proposal is assistance; the maintainer is authority. Corrections must count as coverage.

Both directions are required and tested:
- a corrected fact covers the statement it was authored for, whatever its values;
- **one authored fact never marks two distinct source statements as covered.**

## A6-C — the version inspection, run now, and its verdict

A6 as committed justified "no importer version change" on the grounds that no fragment moves and
reviewed facts are draft-only. **That reasoning is invalid.** Importer compatibility is judged
against produced package semantics, not fragment bytes or draft schema — and A2 changes projected
runtime rule semantics, since a reviewed scope that previously projected a wildcard matcher can now
project a set matcher. The same reviewed fact set can therefore produce a different decision rule.

### Inspection performed

Two questions: can a trusted package exist under the pre-correction version at all, and would this
correction change its projected rules?

**Can it exist: yes.** The fact-authored projectors are on merged main. A maintainer authors facts
and a completion record in a draft, the clause-fact approval blocker clears, and the package is
approved and carries the projected rules. Reviewed facts stay draft-only, but the *rules they
projected* are in the package. The private licensed suite performs exactly this sequence, which is
the existence proof.

**Would it change: yes, for two dimensions.** Comparing each reviewed dimension's authorable domain
against the consumer input domain it projects into:

| Dimension | Reviewed domain vs consumer domain | Wildcard reading changes? |
| --- | --- | --- |
| supply kind, calculation purpose | equal | no |
| earthing arrangement | equal — every consumer value is authorable | no |
| input topology | equal | no |
| **phase system** | reviewed is a strict subset; the consumer domain carries two further states | **yes** |
| **device placement** | reviewed is a strict subset; the consumer domain carries one further state | **yes** |
| attenuation evidence | already projected as an explicit reviewed set, not a wildcard | no |

Both changing dimensions are authorable as an unrestricted reading today, with nothing refusing it.
The device-placement case is the sharper one: that route's own design note says a consumer asking
about the unreviewed placement must reach no row, and the wildcard reading grants it one — so the
pre-correction projection contradicts its own recorded intent.

### Verdict

**A compatibility bump is required**: a package approved under the pre-correction version can carry a
projected rule this correction would not produce, so it must stop being trusted.

**This branch already carries that bump**, taken earlier for the clause-opener region correction. No
*second* increment is needed: the increment is unreleased and branch-only, so its definition widens
to cover this slice's projection semantics as well. What changes is the **reason** recorded for it —
not "a fragment moved" but "extracted evidence and projected rule semantics both changed" — and the
branch must not ship without it. Recorded beside the constant, which now names both halves.

Its **number** is not fixed by this document: it is assigned in merge order at implementation time.
Issue #60 is based on main and merges first, so it owns `iec-pdf-7` and this stack carries
`iec-pdf-8`.

The following region-widening slice still runs its own inspection before deciding whether it needs a
further increment or can widen this same unreleased one again.
