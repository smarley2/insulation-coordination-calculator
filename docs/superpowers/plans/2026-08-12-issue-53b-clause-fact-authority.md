# Clause Fact Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move normative branch authority for the IEC 62477-1:2022 supply rules out of Python
constants and into typed facts a maintainer authors from the licensed clause fragment.

**Architecture:** The importer proposes a clause's node inventory and nothing more. The maintainer
authors typed `SupplyFact` statements, each citing the nodes it rests on, plus one completion
record per `(clause, rule route)`. A private-side grammar may *prefill* a statement's dimensions as
a suggestion the maintainer reviews and then explicitly authors; the suggestion carries no
authority and never reaches a projector except through an authored fact (Amendment A1). A fact's review binds a digest of exactly the evidence it cites,
so changing a cited node re-opens exactly the dependent facts. A resolver turns current reviews
into `ConfirmedFacts`, and each ported projector builds its rule from those alone. One projector —
multiple-source propagation — keeps legacy constants, recorded in an assertable set, because
porting it faithfully would change behaviour; that change is #53C's first acceptance criterion.

**Tech Stack:** Python 3.13, Pydantic 2 frozen models, PySide6, pytest (+ pytest-qt, pytest-xdist),
mypy strict, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-08-12-issue-53b-clause-fact-authority-design.md`

## Global Constraints

- PUBLIC repository holding rules imported from licensed IEC documents. Committed files may carry
  semantic identifiers, neutral field vocabularies, clause and table locators, structural indexes,
  bounding boxes, and typed model shapes. They may **not** carry statement text, clause or heading
  wording, numeric source content, per-clause normative statement counts, or the mapping from a
  physical node to a statement.
- Nobody proposes a statement from public code. The importer proposes the node inventory; the
  maintainer authors every fact. **No public grammar may read clause prose to infer a branch** — any
  mapping from source phrasing to typed normative meaning is licensed-derived material and loads
  only from where the licensed material lives. The public tree carries the generic proposal engine
  and the generic typed proposal shape, never a rule that names source phrasing. See Amendment A1.
- One explicit authoring action records exactly one statement. No action may certify several
  machine-derived facts at once.
- Completion is asserted per `(clause, rule route)`, never per fragment: a fragment may carry
  statements belonging to rules outside the route.
- `LEGACY_BRANCH_AUTHORITY_RULE_IDS` contains exactly one member, the multiple-source-propagation
  identifier. Every other supply rule must refuse to project without facts.
- Review invalidation follows #53A's principle: changed authority, fact set or hash requires
  renewed review; unchanged proposal and hash keeps its existing review current; propagation is not
  invalidated merely because this slice exists.
- `uv` is not on PATH. Prefix every command with:
  `$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"`
- Qt tests need `$env:QT_QPA_PLATFORM = "offscreen"`.
- Type-check with bare `uv run mypy`. Never `mypy src tests`.
- Full suite as CI runs it:
  `uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing`
- Private licensed tests skip without the PDFs. Never report a private result a run did not produce.
- Do not implement #53C's contracts. Do not wire #36 consumers. Do not change the generic decision
  evaluator.
- Commit messages end with: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- The Bash tool refuses compound commands it cannot verify stay inside the worktree; use plain
  separate commands and `git commit -F <file>`.

## Contracts the ports must preserve

Read from the current projectors. A ported rule keeps its id, inputs, outputs and row semantics;
only its authority changes.

```text
supply.system_voltage_resolution
  inputs   supply_kind, phase_system, earthing_arrangement, input_topology, calculation_purpose
  outputs  system_voltage_measure (categorical)
  routes   the rule and its .guidance sibling

supply.verified_barrier_transfer
  inputs   galvanic_isolation_verified, isolation_evidence_kind, downstream_connection_kind
  outputs  transfer_permitted (boolean), combined_circuit_requirement (categorical),
           propagates_to_connected_circuits (boolean)

supply.hf_transformer_attenuation
  inputs   circuit_dvc, transformer_frequency_hz (numeric, Hz), isolation_provided,
           attenuation_evidence_kind
  outputs  working_voltage_basis_permitted (boolean), required_evidence_kinds (categorical)

supply.spd_reduction_requirements        <- gains .mains and .non_mains routes in this slice
  inputs   device_placement, insulation_class, device_degradable, part_of_category_reduction
  outputs  reduction_permitted, reduced_category, monitoring_required,
           status_indication_required, verification_reference, reinforced_floor_applies

supply.multiple_source_propagation       <- NOT ported here
  inputs   evaluated_side, mains_overvoltage_category, non_mains_overvoltage_category,
           galvanic_isolation_present
```

## File Structure

Create:

- `src/insulation_coordination/rules/importer/clause_facts.py` — the `SupplyFact` union, the review
  and completion records, `ConfirmedFacts`, and the evidence digest helper.
- `src/insulation_coordination/ui/clause_fact_review.py` — authoring model and dialog.
- `tests/rules/importer/test_clause_facts.py`, `tests/rules/importer/test_clause_fact_review_api.py`,
  `tests/rules/importer/test_clause_fact_resolution.py`, `tests/ui/test_clause_fact_review.py`.

Modify:

- `rules/importer/extract.py` — two draft collections and their digest coverage.
- `rules/importer/approval.py` — the blocker, the change-detection tuple, four digest rebuild sites.
- `rules/importer/review.py` — authoring API, completion API, resolver, and the clause projector
  call site.
- `rules/importer/recipes/iec62477_1_2022/supply.py` — two new clause specs, the SPD route split,
  four ports, the legacy set, and the deletion of the branch constants.
- `domain/rules.py` — `IEC_IMPORTER_VERSION`.
- `ui/rules_manager.py` — one button.
- `tests/private/` — the per-route inventory tests.

---

### Task 1: Fact models, draft collections and digest coverage

**Files:**
- Create: `src/insulation_coordination/rules/importer/clause_facts.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py` (`ImportedRuleDraft`, `_content_digest`)
- Modify: `src/insulation_coordination/rules/importer/approval.py` (change-detection tuple at `:475-493`, digest rebuilds at `:527`, `:558`, `:602`, `:717-718`)
- Test: `tests/rules/importer/test_clause_facts.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SystemVoltageFact`, `PropagationStepFact`, `BarrierTransferFact`, `SpdReductionFact`, `SpdMonitoringFact`, `HfAttenuationFact`, the `SupplyFact` union, `CitedNode`, `evidence_sha256`, `ClauseFactReview`, `ClauseFactCompletion`, `ConfirmedFacts`, and the draft fields `clause_fact_reviews` / `clause_fact_completions`.

- [ ] **Step 1: Write the failing tests**

Create `tests/rules/importer/test_clause_facts.py`:

```python
"""Fact models: typed per family, and bound to exactly the evidence they cite."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from insulation_coordination.rules.importer.clause_facts import (
    CitedNode,
    ClauseFactCompletion,
    ClauseFactReview,
    ConfirmedFacts,
    SpdReductionFact,
    SystemVoltageFact,
    evidence_sha256,
)


def _spd_fact() -> SpdReductionFact:
    return SpdReductionFact(
        statement_index=0,
        node_references=(CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64),),
        obligation="permission",
        supply_kind="mains",
        source_ovc="ovc_iv",
        target_ovc="ovc_iii",
        insulation_class="basic",
        degradable=True,
        participates_in_reduction=True,
        monitoring_obligation="required",
    )


def test_each_family_is_its_own_type_under_one_discriminator() -> None:
    fact = _spd_fact()
    system = SystemVoltageFact(
        statement_index=1,
        node_references=(CitedNode(fragment_id="raw-b", node_order=2, node_sha256="b" * 64),),
        obligation="requirement",
        phase_system="three_phase_it",
        earthing="it",
        purpose="impulse",
        measure="phase_to_artificial_neutral_rms",
    )

    assert fact.fact_kind == "spd_reduction"
    assert system.fact_kind == "system_voltage"


def test_a_fact_must_cite_at_least_one_node() -> None:
    """A statement with no evidence could not go stale, which defeats the whole mechanism."""

    with pytest.raises(ValidationError):
        SpdReductionFact(
            statement_index=0,
            node_references=(),
            obligation="permission",
            supply_kind="mains",
            source_ovc="ovc_iv",
            target_ovc="ovc_iii",
            insulation_class="basic",
            degradable=True,
            participates_in_reduction=True,
            monitoring_obligation="required",
        )


def test_the_evidence_digest_covers_every_cited_node_and_ignores_order_of_citation() -> None:
    first = CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64)
    second = CitedNode(fragment_id="raw-b", node_order=3, node_sha256="b" * 64)

    assert evidence_sha256((first, second)) == evidence_sha256((second, first))


def test_a_changed_cited_node_changes_the_evidence_digest() -> None:
    original = (CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64),)
    changed = (CitedNode(fragment_id="raw-a", node_order=0, node_sha256="c" * 64),)

    assert evidence_sha256(original) != evidence_sha256(changed)


def test_a_reordered_node_changes_the_evidence_digest() -> None:
    """A node's order is part of the identity a fact cited, so a reorder invalidates."""

    original = (CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64),)
    moved = (CitedNode(fragment_id="raw-a", node_order=1, node_sha256="a" * 64),)

    assert evidence_sha256(original) != evidence_sha256(moved)


def test_a_review_carries_the_authored_fact_and_both_digests() -> None:
    fact = _spd_fact()
    review = ClauseFactReview(
        rule_route="iec62477_2022.supply.spd_reduction_requirements.mains",
        statement_index=0,
        fact=fact,
        fact_sha256="d" * 64,
        evidence_sha256=evidence_sha256(fact.node_references),
        actor="tester",
        recorded_at=datetime(2026, 8, 12, tzinfo=UTC),
        notes="authored",
    )

    assert review.fact == fact
    assert ClauseFactReview.model_validate(review.model_dump(mode="json")) == review


def test_completion_is_scoped_to_a_route_and_binds_both_hashes() -> None:
    completion = ClauseFactCompletion(
        rule_route="iec62477_2022.supply.spd_reduction_requirements.mains",
        fragment_id="raw-a",
        fragment_sha256="e" * 64,
        fact_set_sha256="f" * 64,
        actor="tester",
        recorded_at=datetime(2026, 8, 12, tzinfo=UTC),
        notes="complete for this route",
    )

    assert completion.rule_route.endswith(".mains")


def test_confirmed_facts_reads_back_by_route() -> None:
    fact = _spd_fact()
    facts = ConfirmedFacts(
        by_route={"iec62477_2022.supply.spd_reduction_requirements.mains": (fact,)}
    )

    assert facts.for_route("iec62477_2022.supply.spd_reduction_requirements.mains") == (fact,)
    assert facts.for_route("iec62477_2022.supply.hf_transformer_attenuation") == ()
```

- [ ] **Step 2: Run to verify failure**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/test_clause_facts.py -q
```

Expected: `ModuleNotFoundError: No module named
'insulation_coordination.rules.importer.clause_facts'`.

- [ ] **Step 3: Write the module**

Create `src/insulation_coordination/rules/importer/clause_facts.py`:

```python
"""Reviewed normative statements: the licensed clause as the authority for its own branches.

A statement is authored by a maintainer from the private fragment, never proposed by public code,
and binds a digest of exactly the nodes it cites. No statement text, clause wording or numeric
source content belongs here: only the neutral vocabulary each field draws from.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import Identifier, NotesText

Obligation = Literal["requirement", "permission"]


class CitedNode(FrozenModel):
    """One fragment node a statement rests on, by identity and content."""

    fragment_id: Identifier
    node_order: int = Field(ge=0)
    node_sha256: str = Field(pattern=r"[0-9a-f]{64}")


class _Fact(FrozenModel):
    statement_index: int = Field(ge=0)
    node_references: tuple[CitedNode, ...] = Field(min_length=1)
    obligation: Obligation


class SystemVoltageFact(_Fact):
    fact_kind: Literal["system_voltage"] = "system_voltage"
    phase_system: Literal[
        "three_phase_it",
        "single_phase_it",
        "rectified_from_mains",
        "series_rectifier_bridges",
        "isolated_secondary",
        "non_mains",
    ]
    earthing: Literal["tn", "tt", "it", "unspecified"]
    purpose: Literal["impulse", "temporary_overvoltage"]
    measure: Literal[
        "phase_to_artificial_neutral_rms",
        "phase_to_phase_rms",
        "between_supply_conductors_rms",
        "pre_rectifier_ac_rms",
        "highest_pre_rectifier_ac_rms_at_bridge",
    ]


class PropagationStepFact(_Fact):
    fact_kind: Literal["propagation_step"] = "propagation_step"
    step: Literal["a", "b", "c", "d"]
    evaluated_side: Literal["mains", "non_mains"]
    operation: Literal["reduce_one_level", "resolve_rating", "take_more_severe_rating"]
    rating_source_side: Literal["mains", "non_mains"]


class BarrierTransferFact(_Fact):
    fact_kind: Literal["barrier_transfer"] = "barrier_transfer"
    isolation_present: bool
    combined_circuit_rule: Literal["more_severe_of_both_sides", "side_specific_from_transfer"]


class SpdReductionFact(_Fact):
    fact_kind: Literal["spd_reduction"] = "spd_reduction"
    supply_kind: Literal["mains", "non_mains"]
    source_ovc: Literal["ovc_i", "ovc_ii", "ovc_iii", "ovc_iv"]
    target_ovc: Literal["ovc_i", "ovc_ii", "ovc_iii", "ovc_iv"]
    insulation_class: Literal["functional", "basic", "supplementary", "double", "reinforced"]
    degradable: bool
    monitoring_obligation: Literal["required", "not_required"]
    monitoring_reference: Identifier


#: Monitoring is its own normative concern, not a dimension of reduction. Verified against the
#: licensed clauses: placement and participation are dimensions only the monitoring clause's
#: readings carry, while a reduction reading refers to the monitoring route rather than restating
#: it. A placement field on SpdReductionFact would be a dimension its own clause never scopes.
class SpdMonitoringFact(_Fact):
    fact_kind: Literal["spd_monitoring"] = "spd_monitoring"
    device_placement: Literal["internal_to_pecs", "external_to_pecs"]
    participates_in_reduction: bool
    monitoring_required: bool
    compliance_evidence: Literal["visual_inspection", "monitoring_test", "not_required"]


class HfAttenuationFact(_Fact):
    fact_kind: Literal["hf_attenuation"] = "hf_attenuation"
    dvc_gate: Literal["dvc_as", "dvc_b"]
    evidence_kind: Literal["test", "simulation", "calculation"]
    threshold_reference: Identifier
    comparison_required: bool


SupplyFact = Annotated[
    SystemVoltageFact
    | PropagationStepFact
    | BarrierTransferFact
    | SpdReductionFact
    | SpdMonitoringFact
    | HfAttenuationFact,
    Field(discriminator="fact_kind"),
]


def evidence_sha256(nodes: tuple[CitedNode, ...]) -> str:
    """Digest of every cited node's identity and content, independent of citation order.

    Changing a cited node, or moving it, changes this digest and re-opens exactly the facts that
    cited it. A change to an uncited sibling node does not appear here at all.
    """

    members = sorted(f"{node.fragment_id}|{node.node_order}|{node.node_sha256}" for node in nodes)
    return hashlib.sha256("\n".join(members).encode("utf-8")).hexdigest()


class ClauseFactReview(FrozenModel):
    """Exact draft-only review of one authored statement."""

    rule_route: Identifier
    statement_index: int = Field(ge=0)
    fact: SupplyFact
    fact_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    evidence_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    actor: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    notes: NotesText


class ClauseFactCompletion(FrozenModel):
    """The reviewer's assertion that one route's fact set is complete.

    Scoped to a route, never to a fragment: a fragment may carry statements belonging to rules
    outside this route, and this record must not claim those were reviewed.
    """

    rule_route: Identifier
    fragment_id: Identifier
    fragment_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    fact_set_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    actor: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    notes: NotesText


class ConfirmedFacts(FrozenModel):
    """Resolved reviewed facts handed to a clause projector."""

    by_route: dict[str, tuple[SupplyFact, ...]] = Field(default_factory=dict)

    def for_route(self, rule_route: str) -> tuple[SupplyFact, ...]:
        return self.by_route.get(rule_route, ())
```

- [ ] **Step 4: Add the draft collections**

In `extract.py`, add to `ImportedRuleDraft` after `axis_selector_reviews`:

```python
    clause_fact_reviews: tuple[ClauseFactReview, ...] = ()
    clause_fact_completions: tuple[ClauseFactCompletion, ...] = ()
```

Extend `_content_digest` with two keyword parameters of the same names and defaults and digest
them exactly as `curve_variant_reviews` is digested.

- [ ] **Step 5: Add them to approval's change detection and digest rebuilds**

This is the step #53A's first task got wrong; do it deliberately. In `approval.py`, add both
collections:

- to the `raw_changed` comparison tuple, on both the `changed` and the `original` side;
- to each of the four `_content_digest` rebuild sites that name draft-only collections explicitly;
- to the `ImportedRuleDraft(...)` construction that `record_correction` returns.

Follow each site's local style — positional in the tuples, keyword elsewhere.

- [ ] **Step 6: Prove the coverage with tests that fail without it**

Append to `tests/rules/importer/test_clause_facts.py` two tests: one that a draft differing from
another only by one recorded `ClauseFactReview` is detected as changed by `record_correction`, and
one that the rebuilt audit digest differs between those two drafts. Find the existing pattern with
`grep -rn "record_correction(" tests/ | head` and follow the nearest one. Verify both fail before
Step 5's edit by reverse-applying it, then restore.

- [ ] **Step 7: Run everything and commit**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer -q
```

Then ruff and bare mypy, both clean. Commit message:

```text
feat(rules): add reviewed clause fact models (#53)

A clause's normative branches should come from the licensed clause, not from
Python constants. Adds the typed per-family fact union a maintainer authors, the
review and completion records, and the evidence digest that binds a fact to
exactly the nodes it cites, so changing one cited node re-opens exactly the
facts resting on it and leaves the rest current.

Both new draft collections reach approval's change detection and every digest
rebuild, not only _content_digest, so a fact-only change cannot compare equal to
its original.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 2: The two missing fragments and the SPD route split

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py:47-95` (`SUPPLY_CLAUSES`)
- Test: `tests/rules/importer/iec62477_2022/test_supply_clause_recipes.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: clause specs for routes `…spd_reduction_requirements.mains` and `.non_mains`, with the monitoring clause retained under `…spd_reduction_requirements.monitoring`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/rules/importer/iec62477_2022/test_supply_clause_recipes.py`:

```python
def test_the_reduction_rule_is_read_from_the_clauses_that_state_it() -> None:
    """The identifier previously pointed at the monitoring clause, which does not state the rule.

    The reduction is stated once for mains supply and once for non-mains supply, with different
    permitted category steps, so it is two routes of one family rather than one rule.
    """
    by_id = {spec.semantic_id: spec for spec in SUPPLY_CLAUSES}
    mains = by_id[f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"]
    non_mains = by_id[f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains"]
    monitoring = by_id[f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"]

    assert (mains.clause, mains.page_number) == ("4.4.7.2.3", 65)
    assert (non_mains.clause, non_mains.page_number) == ("4.4.7.2.4", 66)
    assert (monitoring.clause, monitoring.page_number) == ("4.4.7.2.2", 65)


def test_no_supply_route_reads_a_clause_that_does_not_state_its_rule() -> None:
    """Guard against the defect returning: the bare reduction id must declare no fragment."""

    declared = {spec.semantic_id for spec in SUPPLY_CLAUSES}

    assert ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS not in declared
```

- [ ] **Step 2: Run to verify failure**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_supply_clause_recipes.py -q
```

Expected: `KeyError` on the `.mains` route.

- [ ] **Step 3: Replace the single SPD clause spec with three**

In `supply.py`, replace the `ClauseAuditSpec` whose `semantic_id` is
`ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS` with these three. The bboxes were measured against the
licensed document with pdfplumber, with the x range excluding the licence watermark columns
exactly as the sibling specs' comment records:

```python
(
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains",
        clause="4.4.7.2.3",
        page_number=65,
        expected_bbox=(65.0, 390.0, 535.0, 518.0),
        expected_root_kind="paragraph",
        output_kind="decision",
        projected_rule_ids=(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains",),
    ),
)
(
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains",
        clause="4.4.7.2.4",
        page_number=66,
        expected_bbox=(65.0, 385.0, 535.0, 512.0),
        expected_root_kind="paragraph",
        output_kind="decision",
        projected_rule_ids=(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains",),
    ),
)
# Retained as cited evidence, not as the source of the reduction rule: the monitoring
# obligation each reduction route defers to is stated here.
(
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",
        clause="4.4.7.2.2",
        page_number=65,
        expected_bbox=(65.0, 110.0, 535.0, 258.0),
        expected_root_kind="paragraph",
        output_kind="decision",
        projected_rule_ids=(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",),
    ),
)
```

Every clause spec needs exactly one registered projector (`StandardRecipe` validates this), so
register all three route ids in `CLAUSE_PROJECTORS` pointing at the existing SPD projector for
now; Task 6 replaces its body. The inventory item for the bare identifier still resolves, because
`_covers` matches a declared child by prefix.

- [ ] **Step 4: Run to verify passing, then the recipe suite**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022 -q
```

Expected: no failures. A failure naming `expected_root_kind` or a bbox means the measured region
does not bracket whole nodes — adjust the bbox by reading the fragment the extractor produces, not
by relaxing the assertion.

- [ ] **Step 5: Commit**

```text
fix(rules): read the reduction rule from the clauses that state it (#53)

SUPPLY_SPD_REDUCTION_REQUIREMENTS was specced against the clause stating the SPD
monitoring requirement. The reduction rule is stated once for mains supply and
once for non-mains supply, each permitting its own category steps, and neither
clause was extracted. The identifier now has a route per supply kind, and the
monitoring clause is retained as cited evidence rather than as the rule's source.

Provenance and authority only: the supply-kind-dependent reduction contract
itself is #53C item 5.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 3: Authoring and completion API, and the blocker

**Files:**
- Modify: `src/insulation_coordination/rules/importer/review.py` (new functions beside `review_curve_variant`)
- Modify: `src/insulation_coordination/rules/importer/approval.py` (new blocker beside the curve-variant blocker)
- Test: `tests/rules/importer/test_clause_fact_review_api.py`

**Interfaces:**
- Consumes: Task 1's models; Task 2's route ids.
- Produces: `author_clause_fact(draft, *, rule_route, fact, actor, notes) -> ImportedRuleDraft`, `record_fact_completion(draft, *, rule_route, fragment_id, actor, notes) -> ImportedRuleDraft`, `fact_set_sha256(facts) -> str`, and the `CLAUSE_FACT_REVIEW_REQUIRED` blocker code.

- [ ] **Step 1: Write the failing tests**

Create `tests/rules/importer/test_clause_fact_review_api.py`. Build the draft from the synthetic
clause-fragment helpers the supply tests already use — find them with
`grep -rn "def _fragment" tests/rules/importer/iec62477_2022/test_supply_clause_recipes.py`.

```python
"""Authoring facts, asserting completion, and the gate that requires both."""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.approval import ApprovalError, approval_blockers
from insulation_coordination.rules.importer.review import (
    author_clause_fact,
    record_fact_completion,
)


def test_a_route_without_facts_blocks_approval(draft_with_supply_fragments) -> None:
    codes = {item.code for item in approval_blockers(draft_with_supply_fragments)}

    assert "CLAUSE_FACT_REVIEW_REQUIRED" in codes


def test_facts_without_a_completion_record_still_block(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Authoring fewer statements than the clause carries would silently narrow the rule."""

    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route="iec62477_2022.supply.hf_transformer_attenuation",
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )

    codes = {item.code for item in approval_blockers(draft)}

    assert "CLAUSE_FACT_REVIEW_REQUIRED" in codes


def test_facts_plus_completion_clear_the_gate_for_that_route(
    draft_with_supply_fragments, hf_fact
) -> None:
    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route="iec62477_2022.supply.hf_transformer_attenuation",
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )
    draft = record_fact_completion(
        draft,
        rule_route="iec62477_2022.supply.hf_transformer_attenuation",
        fragment_id="raw-iec62477_2022.supply.hf_transformer_attenuation",
        actor="tester",
        notes="complete for this route",
    )

    blocked = {
        item.semantic_id
        for item in approval_blockers(draft)
        if item.code == "CLAUSE_FACT_REVIEW_REQUIRED"
    }

    assert "iec62477_2022.supply.hf_transformer_attenuation" not in blocked


def test_completion_recorded_before_a_later_fact_goes_stale(
    draft_with_supply_fragments, hf_fact, second_hf_fact
) -> None:
    """The completion binds the fact-set digest, so authoring another fact invalidates it."""

    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route="iec62477_2022.supply.hf_transformer_attenuation",
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )
    draft = record_fact_completion(
        draft,
        rule_route="iec62477_2022.supply.hf_transformer_attenuation",
        fragment_id="raw-iec62477_2022.supply.hf_transformer_attenuation",
        actor="tester",
        notes="complete",
    )
    draft = author_clause_fact(
        draft,
        rule_route="iec62477_2022.supply.hf_transformer_attenuation",
        fact=second_hf_fact,
        actor="tester",
        notes="one more",
    )

    codes = {item.code for item in approval_blockers(draft)}

    assert "CLAUSE_FACT_REVIEW_REQUIRED" in codes


def test_authoring_the_same_statement_index_twice_replaces_it(
    draft_with_supply_fragments, hf_fact
) -> None:
    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route="iec62477_2022.supply.hf_transformer_attenuation",
        fact=hf_fact,
        actor="tester",
        notes="first",
    )
    corrected = hf_fact.model_copy(update={"comparison_required": False})
    draft = author_clause_fact(
        draft,
        rule_route="iec62477_2022.supply.hf_transformer_attenuation",
        fact=corrected,
        actor="tester",
        notes="corrected",
    )

    matching = [
        item
        for item in draft.clause_fact_reviews
        if item.rule_route == "iec62477_2022.supply.hf_transformer_attenuation"
        and item.statement_index == hf_fact.statement_index
    ]

    assert len(matching) == 1
    assert matching[0].fact.comparison_required is False


def test_actor_and_notes_are_required(draft_with_supply_fragments, hf_fact) -> None:
    with pytest.raises(ApprovalError):
        author_clause_fact(
            draft_with_supply_fragments,
            rule_route="iec62477_2022.supply.hf_transformer_attenuation",
            fact=hf_fact,
            actor=" ",
            notes="",
        )


def test_a_fact_citing_a_node_that_does_not_exist_is_refused(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Evidence must be real, or the digest binds nothing."""

    invented = hf_fact.model_copy(
        update={
            "node_references": (hf_fact.node_references[0].model_copy(update={"node_order": 99}),)
        }
    )

    with pytest.raises(ValueError):
        author_clause_fact(
            draft_with_supply_fragments,
            rule_route="iec62477_2022.supply.hf_transformer_attenuation",
            fact=invented,
            actor="tester",
            notes="bad citation",
        )
```

The `hf_fact` and `second_hf_fact` fixtures build `HfAttenuationFact`s whose `node_references`
cite real nodes of the synthetic fragment, with `statement_index` 0 and 1, `dvc_gate="dvc_as"`,
`evidence_kind="test"`, `threshold_reference=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC` and
`comparison_required=True`. Compute each `CitedNode.node_sha256` with
`canonical_model_sha256(node)` over the fragment's own node.

- [ ] **Step 2: Run to verify failure**

Expected: `ImportError: cannot import name 'author_clause_fact'`.

- [ ] **Step 3: Implement the authoring and completion API**

In `review.py`:

```python
def fact_set_sha256(facts: tuple[SupplyFact, ...]) -> str:
    """Digest of one route's authored fact set, so a completion record binds what it approved."""

    members = sorted(canonical_model_sha256(fact) for fact in facts)
    return hashlib.sha256("\n".join(members).encode("utf-8")).hexdigest()


def author_clause_fact(
    draft: ImportedRuleDraft,
    *,
    rule_route: str,
    fact: SupplyFact,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Record one maintainer-authored normative statement for a rule route.

    Nothing proposes a statement: the reviewer reads the private fragment and authors it. The
    review binds the fact's own hash and a digest of exactly the nodes it cites.
    """

    if not actor.strip() or not notes.strip():
        raise ApprovalError("clause fact actor and notes are required")
    for cited in fact.node_references:
        fragment = next(
            (item for item in draft.raw_clause_fragments if item.id == cited.fragment_id), None
        )
        if fragment is None:
            raise ValueError(f"unknown fragment cited: {cited.fragment_id}")
        node = next((node for node in fragment.nodes if node.order == cited.node_order), None)
        if node is None or canonical_model_sha256(node) != cited.node_sha256:
            raise ValueError(
                f"citation does not match a current node: {cited.fragment_id} "
                f"node {cited.node_order}"
            )
    review = ClauseFactReview(
        rule_route=rule_route,
        statement_index=fact.statement_index,
        fact=fact,
        fact_sha256=canonical_model_sha256(fact),
        evidence_sha256=evidence_sha256(fact.node_references),
        actor=actor.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    kept = tuple(
        item
        for item in draft.clause_fact_reviews
        if not (item.rule_route == rule_route and item.statement_index == fact.statement_index)
    )
    changed = draft.model_copy(update={"clause_fact_reviews": (*kept, review)})
    return record_correction(draft, changed, actor=actor, notes=f"author clause fact: {notes}")


def record_fact_completion(
    draft: ImportedRuleDraft,
    *,
    rule_route: str,
    fragment_id: str,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Assert that one route's fact set is complete for the current fragment."""

    if not actor.strip() or not notes.strip():
        raise ApprovalError("completion actor and notes are required")
    fragment = next((item for item in draft.raw_clause_fragments if item.id == fragment_id), None)
    if fragment is None:
        raise ValueError(f"unknown fragment: {fragment_id}")
    facts = tuple(item.fact for item in draft.clause_fact_reviews if item.rule_route == rule_route)
    if not facts:
        raise ApprovalError("a route with no authored facts cannot be complete")
    completion = ClauseFactCompletion(
        rule_route=rule_route,
        fragment_id=fragment_id,
        fragment_sha256=fragment.raw_sha256,
        fact_set_sha256=fact_set_sha256(facts),
        actor=actor.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    kept = tuple(item for item in draft.clause_fact_completions if item.rule_route != rule_route)
    changed = draft.model_copy(update={"clause_fact_completions": (*kept, completion)})
    return record_correction(
        draft, changed, actor=actor, notes=f"record clause fact completion: {notes}"
    )
```

Match `record_correction`'s real argument shape by reading its call in `review_curve_variant`.

- [ ] **Step 4: Implement the blocker**

In `approval.py`, beside the curve-variant blocker, add a loop over every clause spec of every
recipe whose `semantic_id` is a supply route this slice covers — that is, every clause spec except
the one whose id is in `LEGACY_BRANCH_AUTHORITY_RULE_IDS`, which Task 7 introduces; until then,
loop over all clause specs whose projector has been ported. For each, block when:

- the route has no authored facts;
- it has no completion record;
- the completion's `fragment_sha256` differs from the current fragment's `raw_sha256`;
- the completion's `fact_set_sha256` differs from `fact_set_sha256` of the route's current facts;
- any fact's `evidence_sha256` differs from `evidence_sha256(fact.node_references)` recomputed
  against the current fragments.

All five use one code, `CLAUSE_FACT_REVIEW_REQUIRED`, with a message naming the route and which of
the five conditions failed.

- [ ] **Step 5: Run to verify passing, then commit**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/test_clause_fact_review_api.py -q
```

Expected: 7 passed. Then ruff, bare mypy, `uv run pytest tests/rules -q`. Commit message:

```text
feat(rules): author and complete clause facts under review (#53)

author_clause_fact records one maintainer-authored statement, refusing a
citation that does not match a current node, and record_fact_completion asserts
one route's fact set complete against the current fragment and fact-set digests.
Approval blocks a route with no facts, no completion, a stale completion, or a
fact whose cited evidence has moved.

Completion is scoped per route rather than per fragment: a fragment may carry
statements belonging to rules this route does not cover.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 4: The resolver

**Files:**
- Modify: `src/insulation_coordination/rules/importer/review.py` (resolver plus the clause projector call site at `:1235`)
- Test: `tests/rules/importer/test_clause_fact_resolution.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: `resolve_confirmed_clause_facts(spec, fragment, draft) -> ConfirmedFacts` and `ClauseFactResolutionError`.

- [ ] **Step 1: Write the failing tests**

Create `tests/rules/importer/test_clause_fact_resolution.py`, one test per case:

```python
"""Resolution refuses anything not current, and refuses nothing that is."""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.review import (
    ClauseFactResolutionError,
    resolve_confirmed_clause_facts,
)


def test_a_completed_route_resolves(completed_draft, hf_spec, hf_fragment) -> None:
    facts = resolve_confirmed_clause_facts(hf_spec, hf_fragment, completed_draft)

    assert len(facts.for_route("iec62477_2022.supply.hf_transformer_attenuation")) == 1


def test_a_route_without_completion_refuses(authored_draft, hf_spec, hf_fragment) -> None:
    with pytest.raises(ClauseFactResolutionError):
        resolve_confirmed_clause_facts(hf_spec, hf_fragment, authored_draft)


def test_a_stale_fragment_hash_refuses(completed_draft, hf_spec, hf_fragment) -> None:
    stale = tuple(
        item.model_copy(update={"fragment_sha256": "0" * 64})
        for item in completed_draft.clause_fact_completions
    )
    draft = completed_draft.model_copy(update={"clause_fact_completions": stale})

    with pytest.raises(ClauseFactResolutionError):
        resolve_confirmed_clause_facts(hf_spec, hf_fragment, draft)


def test_a_stale_fact_set_digest_refuses(completed_draft, hf_spec, hf_fragment) -> None:
    stale = tuple(
        item.model_copy(update={"fact_set_sha256": "0" * 64})
        for item in completed_draft.clause_fact_completions
    )
    draft = completed_draft.model_copy(update={"clause_fact_completions": stale})

    with pytest.raises(ClauseFactResolutionError):
        resolve_confirmed_clause_facts(hf_spec, hf_fragment, draft)


def test_a_changed_cited_node_refuses(completed_draft, hf_spec, hf_fragment) -> None:
    """Changing evidence a fact rests on must re-open that fact."""

    stale = tuple(
        item.model_copy(update={"evidence_sha256": "0" * 64})
        for item in completed_draft.clause_fact_reviews
    )
    draft = completed_draft.model_copy(update={"clause_fact_reviews": stale})

    with pytest.raises(ClauseFactResolutionError):
        resolve_confirmed_clause_facts(hf_spec, hf_fragment, draft)


def test_an_uncited_sibling_node_changing_keeps_its_siblings_reviews_current(
    completed_system_voltage_draft, system_voltage_fragment_with_changed_third_node
) -> None:
    """Selective invalidation, on a route whose fragment really has several nodes.

    System voltage extracts as three bullet nodes, so a fact citing the first can be shown to
    survive a change to the third. Propagation is the only other multi-node route and the
    resolver skips it as the legacy exception, so this is the one route that can carry this.

    Both directions are asserted against the *changed* draft, and through
    ``live_evidence_sha256``. Comparing a review's stored digest with
    ``evidence_sha256(review.fact.node_references)`` proves nothing: both sides read the citation
    records stored inside the fact, so every review ``author_clause_fact`` ever produced satisfies
    it whatever happened to the document -- the exact tautology ``live_evidence_sha256`` exists to
    break. And only the ``!=`` half catches an implementation that recomputed at fragment
    granularity by mistake, which is the way this property is actually lost.
    """

    changed_draft = completed_system_voltage_draft.model_copy(
        update={"raw_clause_fragments": (system_voltage_fragment_with_changed_third_node,)}
    )
    by_cited_node = {
        review.fact.node_references[0].node_order: review
        for review in changed_draft.clause_fact_reviews
    }
    unchanged, moved = by_cited_node[0], by_cited_node[2]

    assert unchanged.evidence_sha256 == live_evidence_sha256(
        changed_draft, unchanged.fact.node_references
    ), "a fact citing an unchanged node keeps its own review current"
    assert moved.evidence_sha256 != live_evidence_sha256(
        changed_draft, moved.fact.node_references
    ), "a fact citing the changed node goes stale"


def test_facts_come_back_ordered_by_statement_index(completed_draft, hf_spec, hf_fragment) -> None:
    facts = resolve_confirmed_clause_facts(hf_spec, hf_fragment, completed_draft)
    indexes = [
        fact.statement_index
        for fact in facts.for_route("iec62477_2022.supply.hf_transformer_attenuation")
    ]

    assert indexes == sorted(indexes)
```

**Correction to this plan's earlier shape, made before implementation.** The original test here
resolved a fragment with one **uncited** node appended and asserted the route still resolves. That
cannot pass, and not because node-level binding fails: appending a node changes the fragment's own
`raw_sha256`, and the completion record binds exactly that hash, so the resolver refuses at the
completion check before any fact's evidence is consulted. That refusal is correct — a fragment that
gained a node may have gained a normative statement, so "this fact set is complete" has to be
re-asserted — but it means route-level resolution is fragment-granular by design even though
review invalidation is node-granular.

So the two properties are asserted at the levels where they actually hold:

- **Node granularity, at the review level.** A fact citing an unchanged node keeps its own review
  current when a sibling node changes, and a fact citing the changed node does not. Assert both
  through `live_evidence_sha256` against the draft carrying the changed fragment, never through
  `evidence_sha256(review.fact.node_references)` — that recomputes from the citation records
  stored inside the fact, so it is a tautology no document change can break, and it is why
  `live_evidence_sha256` exists.
- **Fragment granularity, at the route level.** Add a test that a fragment which gained a node
  makes the route's completion stale and the resolver refuse, naming re-assertion of completeness
  as the reason.

`completed_system_voltage_draft` therefore has to carry at least two authored facts on the system
voltage route, one citing node 0 and one citing node 2, and
`system_voltage_fragment_with_changed_third_node` is that route's fragment with node 2's text
changed and its `raw_sha256` recomputed. One fact is not enough to assert both directions.

Single-node routes (`hf_transformer_attenuation`, `verified_barrier_transfer`, all three SPD
routes) cannot distinguish the two levels at all, so they assert the simpler property: changing
their one cited node makes both the fact review and the route completion stale.

- [ ] **Step 2: Run to verify failure**

Expected: `ImportError: cannot import name 'ClauseFactResolutionError'`.

- [ ] **Step 3: Implement the resolver and thread it into projection**

```python
class ClauseFactResolutionError(RulePackageError):
    """A route's reviewed facts are missing, incomplete or stale."""


def resolve_confirmed_clause_facts(
    spec: ClauseAuditSpec,
    fragment: RawClauseFragment,
    draft: ImportedRuleDraft,
) -> ConfirmedFacts:
    """Current reviewed facts for one clause spec's routes, or an exception.

    Resolution owns every refusal so a projector receives a complete context and never inspects
    review state itself.
    """

    routes = spec.projected_rule_ids or (spec.semantic_id,)
    by_route: dict[str, tuple[SupplyFact, ...]] = {}
    for route in routes:
        if route in LEGACY_BRANCH_AUTHORITY_RULE_IDS:
            continue
        reviews = sorted(
            (item for item in draft.clause_fact_reviews if item.rule_route == route),
            key=lambda item: item.statement_index,
        )
        if not reviews:
            raise ClauseFactResolutionError(f"{route} has no authored facts")
        for review in reviews:
            if review.evidence_sha256 != live_evidence_sha256(draft, review.fact.node_references):
                raise ClauseFactResolutionError(
                    f"{route} statement {review.statement_index} cites evidence that has moved"
                )
        facts = tuple(review.fact for review in reviews)
        completion = next(
            (item for item in draft.clause_fact_completions if item.rule_route == route), None
        )
        if completion is None:
            raise ClauseFactResolutionError(f"{route} has no completion record")
        if completion.fragment_sha256 != fragment.raw_sha256:
            raise ClauseFactResolutionError(f"{route} completion is bound to an older fragment")
        if completion.fact_set_sha256 != fact_set_sha256(facts):
            raise ClauseFactResolutionError(f"{route} completion predates its current fact set")
        by_route[route] = facts
    return ConfirmedFacts(by_route=by_route)
```

Note the evidence check recomputes from the draft's own current nodes, the same way the approval
gate Task 3 shipped does. Recomputing from the stored citations instead would compare a digest
with itself: the citation records live inside the fact, so nothing a reprint does to the document
could ever make that comparison fail.

Then, at `review.py:1235`, resolve before projecting:

```python
            confirmed_facts = resolve_confirmed_clause_facts(clause_spec, fragment, draft)
            projected, _proposals = recipe.clause_projectors[clause_spec.semantic_id](
                fragment, identity, draft, confirmed_facts
            )
```

and widen `ClauseProjector` in `identify.py:558` to four parameters. Update every registered clause
projector's signature to accept `confirmed_facts`; the ones not yet ported ignore it with a
`# ponytail: ported in a later task of this slice` comment.

- [ ] **Step 4: Run the tests, then the whole importer suite**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer -q
```

Expected: the seven new tests pass and no existing test fails. A signature error anywhere means a
clause projector was missed — every one must take the new parameter.

- [ ] **Step 5: Gates and commit**

Run ruff and bare mypy. Commit message:

```text
feat(rules): resolve reviewed clause facts before projecting (#53)

Resolution turns current reviews into ConfirmedFacts and owns every refusal: no
facts, no completion, a completion bound to an older fragment or an older fact
set, or a fact whose cited evidence has moved. Review invalidation is node-level,
so a fact citing an unchanged node keeps its review when a sibling changes; route
completion stays fragment-level, because a fragment that gained a node may have
gained a statement and completeness has to be re-asserted.

ClauseProjector takes ConfirmedFacts as a fourth parameter, uniformly.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 5: Port system voltage resolution and barrier transfer

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py` (`project_system_voltage_resolution` at `:223`, `project_verified_barrier_transfer` at `:413`, and the constants they use)
- Test: `tests/rules/importer/iec62477_2022/test_supply_clause_recipes.py`

**Interfaces:**
- Consumes: `ConfirmedFacts`, `SystemVoltageFact`, `BarrierTransferFact`.
- Produces: both projectors deriving their rules from facts, with the contracts listed in this plan's "Contracts the ports must preserve" section unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/rules/importer/iec62477_2022/test_supply_clause_recipes.py`:

```python
def test_system_voltage_rows_follow_the_reviewed_facts_not_the_old_constants() -> None:
    """Authority moved: facts the constants never contained must reach the rule."""

    facts = _confirmed_system_voltage_facts(
        measures=("phase_to_phase_rms", "highest_pre_rectifier_ac_rms_at_bridge")
    )
    rules, _ = project_system_voltage_resolution(_fragment(), synthetic_identity(), _draft(), facts)
    rule = next(item for item in rules if item.id == ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)

    emitted = {
        value.categorical
        for row in rule.rows
        for value in row.values
        if value.name == "system_voltage_measure"
    }

    assert emitted == {"phase_to_phase_rms", "highest_pre_rectifier_ac_rms_at_bridge"}


def test_system_voltage_refuses_to_project_without_facts() -> None:
    """No fallback: a factless projection would silently restore the deleted inventory."""

    with pytest.raises(ClauseStructureError):
        project_system_voltage_resolution(
            _fragment(), synthetic_identity(), _draft(), ConfirmedFacts()
        )


def test_system_voltage_keeps_its_declared_contract() -> None:
    facts = _confirmed_system_voltage_facts(measures=("phase_to_phase_rms",))
    rules, _ = project_system_voltage_resolution(_fragment(), synthetic_identity(), _draft(), facts)
    rule = next(item for item in rules if item.id == ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)

    assert {item.name for item in rule.inputs} == {
        "supply_kind",
        "phase_system",
        "earthing_arrangement",
        "input_topology",
        "calculation_purpose",
    }
    assert {item.name for item in rule.outputs} == {"system_voltage_measure"}


def test_barrier_transfer_follows_the_reviewed_facts() -> None:
    facts = _confirmed_barrier_facts(combined_rule="side_specific_from_transfer")
    rules, _ = project_verified_barrier_transfer(
        _barrier_fragment(), synthetic_identity(), _draft(), facts
    )
    rule = rules[0]

    emitted = {
        value.categorical
        for row in rule.rows
        for value in row.values
        if value.name == "combined_circuit_requirement"
    }

    assert emitted == {"side_specific_from_transfer"}


def test_barrier_transfer_refuses_to_project_without_facts() -> None:
    with pytest.raises(ClauseStructureError):
        project_verified_barrier_transfer(
            _barrier_fragment(), synthetic_identity(), _draft(), ConfirmedFacts()
        )


def test_barrier_transfer_keeps_its_declared_contract() -> None:
    facts = _confirmed_barrier_facts(combined_rule="more_severe_of_both_sides")
    rules, _ = project_verified_barrier_transfer(
        _barrier_fragment(), synthetic_identity(), _draft(), facts
    )

    assert {item.name for item in rules[0].inputs} == {
        "galvanic_isolation_verified",
        "isolation_evidence_kind",
        "downstream_connection_kind",
    }
    assert {item.name for item in rules[0].outputs} == {
        "transfer_permitted",
        "combined_circuit_requirement",
        "propagates_to_connected_circuits",
    }
```

`_confirmed_system_voltage_facts` and `_confirmed_barrier_facts` build a `ConfirmedFacts` whose
route maps to facts citing the synthetic fragment's nodes.

- [ ] **Step 2: Run to verify failure**

Expected: `TypeError` about the fourth positional argument.

- [ ] **Step 3: Port both projectors**

Read each projector's current body. Keep its structure, its rule ids, its inputs, its outputs and
its row shape; replace only the source of the branch values:

- `project_system_voltage_resolution` derives its rows from
  `confirmed_facts.for_route(ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)`, one row per fact, matching on
  the fact's `phase_system`, `earthing` and `purpose`, and emitting its `measure`. Raise
  `ClauseStructureError` when the route has no facts.
- `project_verified_barrier_transfer` derives its rows from its route's `BarrierTransferFact`s,
  matching on `isolation_present` and emitting `combined_circuit_rule`. Raise
  `ClauseStructureError` when the route has no facts.

Then delete the constants that encoded those branches — `_SYSTEM_VOLTAGE_MEASURES`,
`_CALCULATION_PURPOSES`, `_COMBINED_CIRCUIT_REQUIREMENTS` and any helper that existed only to pick
among them. Keep the vocabularies that remain the rules' declared `allowed_values`
(`_SUPPLY_KINDS`, `_PHASE_SYSTEMS`, `_EARTHING_ARRANGEMENTS`, `_INPUT_TOPOLOGIES`,
`_ISOLATION_EVIDENCE_KINDS`, `_DOWNSTREAM_CONNECTION_KINDS`): a vocabulary is permitted public
content, a branch inventory is not. If deleting a constant leaves a rule's `allowed_values`
without a source, derive those values from the facts, not from a reinstated constant.

- [ ] **Step 4: Run the tests and the shape suite**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022 -q
```

Expected: no failures. Existing tests that asserted the old constant-derived rows must be updated
to build facts — that is the port, not a regression.

- [ ] **Step 5: Gates and commit**

```text
feat(rules): system voltage and barrier transfer follow reviewed facts (#53)

Both projectors now derive their branches from the maintainer-authored facts for
their route and refuse to project without them, so the deleted constants cannot
be silently restored by a fallback. Rule ids, inputs, outputs and row semantics
are unchanged: this moves authority, not contract.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 6: Port HF attenuation and the two SPD routes

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py` (`project_spd_reduction_requirements` at `:513`, `project_hf_transformer_attenuation` at `:691`, and their constants)
- Test: `tests/rules/importer/iec62477_2022/test_supply_clause_recipes.py`

**Interfaces:**
- Consumes: `ConfirmedFacts`, `SpdReductionFact`, `HfAttenuationFact`, Task 2's three route ids.
- Produces: both projectors fact-driven; the SPD projector emitting one rule per supply-kind route.

- [ ] **Step 1: Write the failing tests**

```python
def test_hf_attenuation_follows_the_reviewed_facts() -> None:
    facts = _confirmed_hf_facts(evidence_kinds=("test", "simulation"))
    rules, _ = project_hf_transformer_attenuation(
        _hf_fragment(), synthetic_identity(), _draft(), facts
    )

    emitted = {
        value.categorical
        for row in rules[0].rows
        for value in row.values
        if value.name == "required_evidence_kinds"
    }

    assert emitted == {"test", "simulation"}


def test_hf_attenuation_refuses_to_project_without_facts() -> None:
    with pytest.raises(ClauseStructureError):
        project_hf_transformer_attenuation(
            _hf_fragment(), synthetic_identity(), _draft(), ConfirmedFacts()
        )


def test_hf_attenuation_keeps_its_declared_contract() -> None:
    facts = _confirmed_hf_facts(evidence_kinds=("test",))
    rules, _ = project_hf_transformer_attenuation(
        _hf_fragment(), synthetic_identity(), _draft(), facts
    )

    assert {item.name for item in rules[0].inputs} == {
        "circuit_dvc",
        "transformer_frequency_hz",
        "isolation_provided",
        "attenuation_evidence_kind",
    }
    assert {item.name for item in rules[0].outputs} == {
        "working_voltage_basis_permitted",
        "required_evidence_kinds",
    }


def test_each_supply_kind_route_projects_its_own_rule() -> None:
    """The source states the reduction twice, so one route cannot answer for both."""

    mains, _ = project_spd_reduction_requirements(
        _spd_fragment("mains"),
        synthetic_identity(),
        _draft(),
        _confirmed_spd_facts("mains", source_ovc="ovc_iv", target_ovc="ovc_iii"),
    )
    non_mains, _ = project_spd_reduction_requirements(
        _spd_fragment("non_mains"),
        synthetic_identity(),
        _draft(),
        _confirmed_spd_facts("non_mains", source_ovc="ovc_iii", target_ovc="ovc_ii"),
    )

    assert mains[0].id == f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"
    assert non_mains[0].id == f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains"


def test_the_reduced_category_comes_from_the_reviewed_fact() -> None:
    rules, _ = project_spd_reduction_requirements(
        _spd_fragment("non_mains"),
        synthetic_identity(),
        _draft(),
        _confirmed_spd_facts("non_mains", source_ovc="ovc_ii", target_ovc="ovc_i"),
    )

    emitted = {
        value.categorical
        for row in rules[0].rows
        for value in row.values
        if value.name == "reduced_category"
    }

    assert emitted == {"ovc_i"}


def test_spd_refuses_to_project_without_facts() -> None:
    with pytest.raises(ClauseStructureError):
        project_spd_reduction_requirements(
            _spd_fragment("mains"), synthetic_identity(), _draft(), ConfirmedFacts()
        )
```

- [ ] **Step 2: Run to verify failure**

Expected: `TypeError` on the fourth argument, then assertion failures naming the old generic
`one_level_lower` value where a category token is now expected.

- [ ] **Step 3: Port both projectors**

`project_hf_transformer_attenuation` derives its rows from its route's `HfAttenuationFact`s,
matching on `dvc_gate` and emitting `evidence_kind` values; it raises `ClauseStructureError`
without facts.

**Correction, after this step was first written and then reviewed against the document:** this text
said to delete `_ATTENUATION_EVIDENCE_KINDS` and `_REQUIRED_EVIDENCE_KINDS`. Deleting the first was
wrong and was reverted. It is the declared vocabulary of an *input*, and an input's vocabulary is
the consumer's question space, not the reviewed answer space — driving it from the authored facts
dropped `none` from the domain, so the first question a consumer asks, designing before the
attenuation is shown, raised instead of answering. Derive the **rows** from facts and leave both
vocabularies declared. Keep `_DVC_DESIGNATIONS` and `_HF_TRANSFORMER_DVC_GATE` on the same
grounds. The `threshold_reference` and `comparison_required` fields are carried
but not yet executable: #53C item 4 turns them into the verification-result contract, and this
task must not.

`project_spd_reduction_requirements` becomes route-aware: it reads the route from the fragment id
it was given, projects one rule per route, and emits `reduced_category` from the fact's
`target_ovc` rather than a generic one-level token. Delete `_REDUCED_CATEGORIES` and
`_reduced_by_one_level`. Keep `_INSULATION_CLASSES`, `_FLOORED_INSULATION_CLASSES`,
`_REDUCIBLE_INSULATION_CLASSES` and `_VERIFICATION_REFERENCES` only where they are declared
vocabularies. The full supply-kind-dependent context — enumerated permitted steps, the floor as an
executable input, the monitoring obligation — is #53C item 5.

- [ ] **Step 4: Run and commit**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules -q
```

Expected: no failures. Commit message:

```text
feat(rules): HF attenuation and both reduction routes follow reviewed facts (#53)

The reduction rule now projects one rule per supply-kind route and takes its
reduced category from the reviewed fact instead of a generic one-level token, and
HF attenuation takes its evidence kinds from facts. Both refuse to project
without them.

Carried but not yet executable: the attenuation threshold reference and the
comparison requirement, which #53C item 4 turns into a verification result, and
the full reduction context, which is #53C item 5.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 6B: One clause, several physical segments

**Inserted after Task 6 was written, and it corrects Task 5.** Reading clause 4.4.7.1.7 in full
against the licensed document showed the system voltage route's evidence model is wrong, not its
rule. The subclause for mains supply spans a page break — part of it sits at the foot of one page
and the rest continues on the next — and the recipe's single `(page_number, expected_bbox)`
reaches only the region inside its one rectangle. A separate subclause then covers non-mains
supply, and had no spec at all. Task 5 deleted a branch constant and left a fact family unable to
express every reviewed case, with no citable evidence for the statements outside the rectangle —
which the public suite cannot see, because every fixture is synthetic.

`ClauseAuditSpec` assumed *one semantic clause = one rectangle on one page*. The source disproves
that assumption, so the fix belongs in the extraction model. Structural locators are permitted
public content, which is exactly why a generic multi-segment mechanism is the right correction.

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py` (`ClauseAuditSpec`, new `ClauseSegmentSpec`)
- Modify: `src/insulation_coordination/rules/importer/clauses.py` (fragment assembly and digest)
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py` and every other recipe declaring clause specs
- Modify: `src/insulation_coordination/rules/importer/clause_facts.py` (`SystemVoltageFact`)
- Test: `tests/rules/importer/` clause extraction and supply recipe modules; `tests/private/` for the real inventory

**Interfaces:**
- Produces: `ClauseSegmentSpec(page_number, expected_bbox, ...)`, `ClauseAuditSpec.segments`, a `system_voltage_resolution` evidence scope per subclause, and a widened `SystemVoltageFact`.

- [ ] **Step 1: Multi-segment clause specs**

`ClauseSegmentSpec` carries one page number and one bbox, plus any segment-local shape expectation.
`ClauseAuditSpec` replaces `page_number` and `expected_bbox` with `segments: tuple[ClauseSegmentSpec, ...]`,
minimum length one. A simple clause declares one segment; the mains system voltage subclause declares
two. Every existing spec becomes a one-segment spec — mechanical, and it must not change any
extracted fragment.

Extraction concatenates each segment's nodes **in declared segment order**, and every node keeps its
own page and segment provenance rather than inheriting the spec's first page. The fragment digest
covers the ordered segment inventory *and* the extracted nodes, so changing either physical part
makes the right evidence stale.

- [ ] **Step 2: Two evidence scopes, one rule**

Keep one reviewed fragment per subclause: the mains subclause is one fragment of two segments, the
non-mains subclause a separate fragment. Do **not** merge them into a fragment whose nominal clause
is one subclause while quietly carrying material from the other, and do **not** let physical
pagination create runtime routes — the consumer still wants a single
`supply.system_voltage_resolution` rule.

Completion is already scoped per `(clause, rule route)`, so the rule now has two evidence scopes,
both of which must be reviewed and complete before it projects.

**Binding: do not solve this by declaring the same projected rule on two ordinary clause specs.**
Two current behaviours make that unsafe, both verified against the code:

- `_source_semantic_id` (`review.py`) resolves a projected route to a spec by returning the **first**
  match. Worse, it short-circuits before the loop when the proposal's own identifier is itself a
  declared spec id — which `supply.system_voltage_resolution` is — so the mains spec would win
  before declaration order even mattered.
- `_required_review_items` builds its gating set from `{proposal.semantic_id,
  _source_semantic_id(proposal)}`, so the second fragment's review items would never gate the
  proposal.
- `package_expectations` derives typed results per clause spec from `projected_rule_ids`.

Two declared evidence owners for one rule would therefore give one silent winner and a second
fragment that contributes nothing to proposal grounding — undoing exactly what this task exists to
fix.

Introduce an explicit distinction in the generic clause model instead, along the lines of
`projection_role = "rule" | "evidence"`:

```text
mains 4.4.7.1.7.1     role = rule       segments = [three regions]   projects the rule
non-mains 4.4.7.1.7.2 role = evidence   segments = [one region]      contributes facts only
```

**"One segment per page" is wrong, and a literal reading of it would silently drop part of the
clause.** Measured against the document: one region sits at the foot of the previous page, one is
the current rectangle on the following page, and a further region sits on that *same* page
**below** the rectangle. So the mains subclause needs **three** segments, two of them on one page,
and the segment tuple must be ordered by reading order rather than by page. The non-mains
subclause starts on that same page again, which is why it is its own fragment.

**`_require_shape` cannot express the result as it stands.** It takes one `(kind, count)` pair and
rejects any node whose kind differs, while the mains subclause's later region is paragraphs
following bullets. Either give each `ClauseSegmentSpec` its own shape expectation and check
segment-wise, or replace the pair with an ordered per-node kind sequence. Do not relax the check
into "any kind" — the shape guard is what makes a reflowed clause stop the build.

Then refine the projector validator deliberately rather than loosening it: a rule-producing clause
requires **exactly one** projector, and an evidence-only clause **prohibits** one. "Projector
optional for anything" is the wrong weakening, and a dummy no-op projector for the second fragment
is the wrong dodge.

The projected rule and its `SemanticProposal` must be grounded in the **aggregate** of both
completed fact scopes, never in whichever spec a first-match lookup happens to reach. Either update
that source-resolution mechanism for multi-fragment rules, or bypass it with an explicit aggregate
over the exact confirmed fact and evidence sets the projector consumed. Exactly one `DecisionRule`
and one `SemanticProposal` come out.

- [ ] **Step 3: Rebuild `SystemVoltageFact` against the rule's declared inputs**

Widening is not enough — a review of Tasks 4-6 verified against the document that the family is
wrong in a way widening cannot fix. **Four of `phase_system`'s six tokens are not phase systems at
all:** `series_rectifier_bridges` and `isolated_secondary` are verbatim members of
`_INPUT_TOPOLOGIES`, `rectified_from_mains` is a second spelling of that tuple's `rectified_dc`,
and `non_mains` is a member of `_SUPPLY_KINDS`. Authoring any of the four raises immediately, since
the projector emits them as a `phase_system` matcher:

```text
three_phase_it, single_phase_it   -> project
the other four                   -> ValidationError: Matcher on 'phase_system' uses values
                                    outside its allowed values
```

Meanwhile the projector wires `supply_kind` and `input_topology` to `op="any"`, so both are
declared-but-dead in every row with no fact field able to revive them. One field collapsed three
declared inputs. This is the same defect `080f1fa` fixed for `device_placement`, four times over.

So: give `SystemVoltageFact` its own `supply_kind` and `input_topology` fields drawn from the
rule's own tuples, each with an explicit "not stated" token, keep `phase_system` to actual phase
systems (adding the earthed arrangements stated before the page break), and emit real matchers
for all four dimensions. Then check every value — new and existing — against the projected rule's
declared `allowed_values`.

**Also fix the empty-vocabulary crash this exposes.** The projector filters `any_purpose` out
before feeding `calculation_purposes` into a categorical `DecisionInput`, so a fact set where every
statement is `any_purpose` yields an empty tuple and `DecisionRule` refuses with "a categorical
input must declare its allowed values". That is not hypothetical: **several of the clause's
statements restrict no purpose**, so a maintainer authoring those first hits a crash naming a
pydantic field rather than their mistake. Declare `("impulse", "temporary_overvoltage")` as a
constant input vocabulary and derive only the rows — a declared input's vocabulary is the
consumer's question space, not the reviewed answer space.

**Do not restore `not_derived_from_mains_supply`.** The review checked the source: that deleted
token stood for the isolated-secondary case, and the source states there that such voltages *are*
system voltages for impulse determination. That is an applicability statement, not a measure, so it
cannot be expressed as one — it needs its own shape or it belongs to a later slice. Say which in
your report rather than forcing it into `measure`.

Do **not** restore the deleted branch constant. The shape is
`full source evidence -> reviewed SystemVoltageFacts -> rule rows`, never
`partial source evidence + a public branch inventory -> rule rows`.

Do **not** add system voltage to `LEGACY_BRANCH_AUTHORITY_RULE_IDS`. That set has exactly one
member, and #53C's first acceptance criterion is removing it; a second member would mean merging
#53B knowing its reviewed-fact authority is incomplete.

- [ ] **Step 4: Tests, public then private**

Public, synthetic, and written before the mechanism:

- A two-segment clause spec whose segments carry nodes 1-2 and 3-4 extracts **one** fragment with a
  stable ordered node inventory, and each node retains its own segment and page provenance.
- The fragment digest changes when the segment inventory changes, not only when node content does.
- Changing a segment-1 node leaves a fact citing only segment-2 nodes current at the review level,
  while a fact citing a segment-1 node goes stale. This is where node-level evidence finally earns
  its keep — every single-node route so far could not distinguish it. Assert currency at the review
  level via `live_evidence_sha256`; route-level resolution still refuses, because the fragment's own
  hash changed and completeness must be re-asserted.
- Every pre-existing one-segment spec extracts exactly the fragment it extracted before.

The two-scope arrangement needs its own four:

```text
both scopes complete        -> exactly one system_voltage_resolution rule and one proposal
mains scope incomplete      -> no projection
non-mains scope incomplete  -> no projection
either fragment or fact set changes -> that single rule and proposal go stale
```

And one more that kills the class of bug rather than the instance: **reverse the order of the two
clause specs in the recipe and prove the projected rule and its provenance are identical.** Any
accidental "first declared spec wins" dependency fails that test, which is the whole reason the
explicit role exists instead of two look-alike specs.

Private, licensed: prove the real system voltage evidence inventory is complete across both scopes,
by fact family and typed identity. Keep the count and the per-route inventory private, consistent
with the decision already recorded for the other routes.

- [ ] **Step 5: Gates and commit**

```text
feat(rules): one clause may span several physical segments (#53)

ClauseAuditSpec assumed one semantic clause is one rectangle on one page. The
mains system-voltage subclause disproves it: its first cases sit at the foot of
one page, the next continue at the head of the following one, and the rest resume
on that same later page below the declared rectangle, so the single rectangle
reached only the middle region, and the sibling non-mains subclause had no spec
at all. A slice whose premise is that the licensed clause is the authority cannot
read one region of it.

ClauseAuditSpec now declares an ordered tuple of segments, each one page and one
bbox. Extraction concatenates their nodes in declared order, every node keeps its
own segment and page provenance, and the fragment digest covers the segment
inventory as well as the nodes, so changing either physical part re-opens the
right evidence. Every other clause declares a single segment and extracts exactly
what it did before.

The two subclauses stay two reviewed fragments feeding one rule, rather than one
fragment spanning both or one runtime route per page: completion is scoped per
clause and rule route, so the rule now has two evidence scopes and needs both.
Physical pagination is provenance, not application semantics.

SystemVoltageFact widens to express every reviewed case rather than only those
the partial fragment happened to reach. The deleted branch inventory is not
restored: the authority is the evidence, not a constant standing in for the part
of the clause nobody extracted.

Refs #53

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 7: The legacy exception, made assertable

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py`
- Test: `tests/rules/importer/iec62477_2022/test_supply_clause_recipes.py`

**Interfaces:**
- Consumes: Tasks 5 and 6.
- Produces: `LEGACY_BRANCH_AUTHORITY_RULE_IDS: frozenset[str]`.

- [ ] **Step 1: Write the failing test**

```python
def test_exactly_one_supply_rule_still_carries_legacy_branch_authority() -> None:
    """Propagation is the sole exception, because porting it faithfully changes behaviour.

    Its ordinal category comparison cannot be expressed as a reviewed fact, so #53C item 3
    replaces the contract. Removing this exception is #53C's first acceptance criterion, and
    this test is what records that it is still outstanding.
    """

    assert LEGACY_BRANCH_AUTHORITY_RULE_IDS == frozenset({ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION})


def test_every_other_supply_route_refuses_to_project_without_facts() -> None:
    """The exception is one rule, not a habit."""

    factless = ConfirmedFacts()
    for projector, fragment in (
        (project_system_voltage_resolution, _fragment()),
        (project_verified_barrier_transfer, _barrier_fragment()),
        (project_hf_transformer_attenuation, _hf_fragment()),
        (project_spd_reduction_requirements, _spd_fragment("mains")),
    ):
        with pytest.raises(ClauseStructureError):
            projector(fragment, synthetic_identity(), _draft(), factless)
```

- [ ] **Step 2: Run to verify failure**

Expected: `ImportError: cannot import name 'LEGACY_BRANCH_AUTHORITY_RULE_IDS'`.

- [ ] **Step 3: Declare the set**

In `supply.py`:

```python
#: Supply rules whose normative branches still come from constants in this module rather than
#: from reviewed facts. Exactly one: multiple-source propagation's current contract *is* an
#: ordinal overvoltage-category comparison, and no honest reviewed fact says "compare ordinals",
#: so porting it faithfully would change behaviour. That change is #53C item 3, and removing this
#: exception is #53C's first acceptance criterion.
LEGACY_BRANCH_AUTHORITY_RULE_IDS: frozenset[str] = frozenset(
    {ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION}
)
```

Import it where the resolver skips legacy routes (Task 4) and where the blocker decides which
routes to gate (Task 3), replacing whatever provisional condition those tasks used.

- [ ] **Step 4: Run and commit**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules -q
```

```text
feat(rules): record the single legacy branch-authority exception (#53)

Propagation keeps its constants because its contract is the ordinal category
comparison itself, which no reviewed fact can honestly express; replacing it is
#53C item 3. The exception is now a frozenset a test asserts rather than a
comment, and a companion test proves every other supply route refuses to project
without facts.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 8: The authoring surface

**Files:**
- Create: `src/insulation_coordination/ui/clause_fact_review.py`
- Modify: `src/insulation_coordination/ui/rules_manager.py` (one button beside the curve-review button at `:146`)
- Test: `tests/ui/test_clause_fact_review.py`

**Interfaces:**
- Consumes: `author_clause_fact`, `record_fact_completion`, `draft.clause_fact_reviews`, `draft.clause_fact_completions`, `draft.raw_clause_fragments`.
- Produces: `ClauseFactReviewModel` with `.routes()`, `.nodes(fragment_id)`, `.author(...)`, `.complete(...)`, and `ClauseFactReviewDialog`.

- [ ] **Step 1: Write the failing tests**

```python
"""The authoring surface: the reviewer reads nodes and writes facts. No logic in Qt."""

from __future__ import annotations

from insulation_coordination.ui.clause_fact_review import (
    ClauseFactReviewDialog,
    ClauseFactReviewModel,
)


def test_the_model_lists_each_route_with_its_completion_state(draft_with_supply_fragments) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)

    routes = model.routes()

    assert routes
    assert all(route.status == "needs_facts" for route in routes)


def test_the_model_exposes_the_nodes_a_reviewer_must_read(draft_with_supply_fragments) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    route = model.routes()[0]

    nodes = model.nodes(route.fragment_id)

    assert nodes
    assert all(node.node_sha256 for node in nodes)


def test_authoring_then_completing_moves_a_route_to_complete(
    draft_with_supply_fragments, hf_fact
) -> None:
    model = ClauseFactReviewModel(draft_with_supply_fragments)
    route_id = "iec62477_2022.supply.hf_transformer_attenuation"

    model.author(route_id, hf_fact, actor="tester", notes="authored")
    model.complete(
        route_id,
        f"raw-{route_id}",
        actor="tester",
        notes="complete",
    )

    status = next(route.status for route in model.routes() if route.rule_route == route_id)
    assert status == "complete"


def test_the_dialog_shows_one_row_per_route(qtbot, draft_with_supply_fragments) -> None:
    dialog = ClauseFactReviewDialog(ClauseFactReviewModel(draft_with_supply_fragments))
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == len(
        ClauseFactReviewModel(draft_with_supply_fragments).routes()
    )
    assert dialog.table.columnCount() == 4
```

- [ ] **Step 2: Run to verify failure**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; $env:QT_QPA_PLATFORM = "offscreen"; uv run pytest tests/ui/test_clause_fact_review.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write the model and dialog**

Create `src/insulation_coordination/ui/clause_fact_review.py`, following `ui/curve_review.py`'s
separation exactly: the model delegates every mutation to `author_clause_fact` and
`record_fact_completion`, and Qt only displays and gathers.

```python
class ClauseFactRouteRow(FrozenModel):
    """One rule route as the reviewer sees it."""

    rule_route: str
    fragment_id: str
    authored: int
    status: Literal["needs_facts", "needs_completion", "complete", "stale"]


class ClauseFactNodeRow(FrozenModel):
    """One fragment node the reviewer reads in order to author a statement."""

    fragment_id: str
    node_order: int
    node_kind: str
    node_sha256: str
    raw_text: str
```

`ClauseFactReviewModel.routes()` walks the recipes' clause specs, skipping any route in
`LEGACY_BRANCH_AUTHORITY_RULE_IDS`, and reports `needs_facts` with no reviews, `needs_completion`
with reviews but no current completion, `stale` when a completion's digests no longer match, and
`complete` otherwise. `nodes(fragment_id)` returns the fragment's nodes with
`canonical_model_sha256(node)` so the reviewer's citation is exact.

`ClauseFactReviewDialog` is a four-column table — route, authored count, status, fragment — plus a
node pane showing `nodes(...)` for the selected route.

**The fact editor ships here, in this task.** An earlier draft deferred it, and that repeats the
mistake #53A made: its axis dialog shipped without a confirm affordance, so the gate could only be
satisfied from test code, and the affordance had to be retrofitted before merge. #53B's whole claim
is that a maintainer is the authority for normative facts. A slice that ends with a gate only an API
call can clear is architecturally present and operationally incomplete, and it would let Task 9
"prove" the workflow while the shipped surface cannot perform it.

Minimum usable surface, and no more:

```text
route / fact inventory
source-node reader
fact-family selector
typed field editor
author / replace / delete fact
completion action
status + stale indicators
```

No wizard, no automation, no source-derived suggestions, no clever defaults. The form may be
family-specific and boring — six families, each with a handful of `Literal` dimensions, so a combo
per field read from the model's own annotations is enough. Reuse the pattern `ui/axis_review.py`
already uses for exactly this, including its rule that a dimension starts unchosen and the confirm
action stays disabled until every dimension has a value: a reviewer must never record a reading they
did not pick.

The model keeps every mutation behind `author_clause_fact` and `record_fact_completion`, so Qt holds
no review logic and every refusal a reviewer can trigger — wrong family for the route, a citation to
another clause's node, a duplicate statement — surfaces from the importer rather than being
re-implemented in the dialog.

So #53B finishes as `licensed PDF -> extracted evidence -> maintainer authors typed facts in the UI
-> completion -> fact-derived rules -> approved package`, rather than `licensed PDF -> test code
authors facts -> package passes`.

`raw_text` reaches the UI because a reviewer must read the licensed clause to author a statement —
it is displayed from the private draft and never written to a committed file.

- [ ] **Step 4: Wire the Rules Manager button**

Add a `"Review clause facts…"` button beside the curve-review button, opening
`ClauseFactReviewDialog(ClauseFactReviewModel(draft))` and storing the model's draft back on
close, exactly as `_on_review_curves_clicked` does.

- [ ] **Step 5: Run and commit**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; $env:QT_QPA_PLATFORM = "offscreen"; uv run pytest tests/ui -q
```

```text
feat(ui): review clause facts from the Rules Manager (#53)

Fact authoring is an approval gate, so its surface ships with the gate. One
dialog lists every route with its authored count and completion status and shows
the fragment nodes a reviewer must read; the model delegates authoring and
completion to the importer, so Qt holds no review logic.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 9: Importer version, private tests, gates and the PR

**Files:**
- Modify: `src/insulation_coordination/domain/rules.py:17`
- Modify: `tests/private/` — the supply-clause module
- Test: as below

**Interfaces:**
- Consumes: every earlier task.
- Produces: `IEC_IMPORTER_VERSION = "iec-pdf-6"`, the private per-route inventory tests, and the PR.

- [ ] **Step 1: Bump the importer version**

```python
IEC_IMPORTER_VERSION = "iec-pdf-6"
```

Rule authority changed and the SPD routes changed shape, so a package built before this slice must
be rebuilt rather than served as current. Run the full suite and update whatever pinned the old
value; do not weaken an assertion that a stale importer version is rejected.

- [ ] **Step 2: Add the private per-route inventory tests**

In the private supply-clause test module, add tests asserting — structurally, by fact family and
typed identity rather than by cardinality alone — the expected statement inventory each licensed
route yields, and that a reviewed, completed licensed draft projects the three faithfully-ported
rules identically to today. Keep every assertion structural: no numeric source value, no clause
wording, no statement text.

Because these tests must author facts to reach a projection, they call `author_clause_fact` and
`record_fact_completion` directly with citations computed from the real fragments' nodes.

- [ ] **Step 3: Run the private suite**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest -m private_standard -q
```

On a machine without the PDFs: all skipped, zero collection errors. Record the number. This is not
the private suite passing.

- [ ] **Step 4: Full gates**

Run ruff, bare mypy, and the CI coverage command. Expected: clean, clean, 0 failed, and coverage at
or above the 80% floor. Record the real numbers.

- [ ] **Step 5: Audit the whole diff for licensed content**

```bash
git diff origin/main --unified=0
```

Read every added line. Confirm no statement text, clause or heading wording, numeric source
content, per-clause statement count, or node-to-statement mapping appears anywhere — including in
synthetic fixtures, which must use invented text, and in commit messages. A public push is not
reversible.

- [ ] **Step 6: Commit, push, open the PR**

```text
feat(rules): reject packages built before clause-fact authority (#53)

Branch authority moved from Python constants to reviewed facts, and the
reduction identifier gained a route per supply kind, so a package built earlier
is stale rather than merely older. Bumping IEC_IMPORTER_VERSION makes the
package say which importer contract it belongs to.

Adds the private per-route statement inventories, asserted by fact family and
typed identity rather than by count, and the check that a reviewed licensed
draft still projects the faithfully-ported rules identically.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

The PR body must carry, in order: `Refs #53` (never `Closes`, since #53A and #53C remain); what
changed; the provenance correction and why it belongs to this slice; the single legacy exception and
that removing it is #53C's first acceptance criterion; the contract impact including the importer
bump and the rebuild-and-reauthor lifecycle; the review-invalidation rule, stating explicitly that
propagation is not invalidated merely because this slice exists; the gate numbers; a clearly headed
section stating the private suite has **not** run, that the PR must not merge until it has, with
the command
`$env:ICC_PRIVATE_STANDARDS_DIR = "<directory holding the licensed PDFs>"; uv run pytest -m private_standard -q`
and the note that the maintainer has previously reduced this gate to the tests covering the change;
and what is out of scope.

---

## Self-Review

**Spec coverage.** Fact models and evidence binding → Task 1. Provenance correction → Task 2.
Authoring, completion and the blocker → Task 3. Resolver and refusals → Task 4. The three faithful
ports → Tasks 5 and 6, with the SPD route split in 6. The legacy exception → Task 7. Authoring
surface → Task 8. Importer bump, private inventories, audit → Task 9. "Nobody proposes a statement"
is enforced by there being no proposal code anywhere in the plan and by Task 7's factless-refusal
test. The public-record limit is enforced by Task 9 Step 5 and by every fixture using invented text.

**Placeholders.** Every code step carries real code or an exact contract to preserve. Five steps
deliberately send the implementer to read an existing definition instead of quoting it —
`record_correction`'s argument shape, each of the four projector bodies being ported, and the
synthetic fragment helpers in the supply tests — because a port must match the body that exists,
and quoting four bodies I have not read line by line would be worse than naming them.

**Type consistency.** `SupplyFact`, `CitedNode`, `evidence_sha256`, `fact_set_sha256`,
`ClauseFactReview`, `ClauseFactCompletion`, `ConfirmedFacts.for_route`, `author_clause_fact`,
`record_fact_completion`, `resolve_confirmed_clause_facts`, `ClauseFactResolutionError` and
`LEGACY_BRANCH_AUTHORITY_RULE_IDS` are spelled identically in every task. The clause projector
signature is `(fragment, identity, draft, confirmed_facts)` in Tasks 4 through 7. Every rule id,
input name and output name in Tasks 5 and 6 matches the "Contracts the ports must preserve" section.

---

## Amendments (2026-08-14) — approved after live maintainer review of five clause families

The binding decisions live in the design spec as **Amendments A1-A7**
(`docs/superpowers/specs/2026-08-12-issue-53b-clause-fact-authority-design.md`). The Global
Constraints above are edited in place where an original line became false. Summary of what changed
for the remaining #53B work:

| Amendment | Effect on this plan |
| --- | --- |
| **A1** | Any grammar mapping source phrasing to typed meaning relocates beside the licensed material. Public keeps the generic engine. The route-level multi-statement authoring action is removed; one explicit action records one fact. |
| **A2** + **A2-C** | `DimensionScope` replaces per-dimension `any_*` tokens. `exact_one -> equals`, `exact_set -> in`; `unrestricted -> any` **only when the reviewed domain equals the consumer domain**, otherwise `in(reviewed_domain)` — the wildcard alone does not fix the over-match. The combined-designation token for the DVC gate is dropped in favour of `exact_set`. |
| **A3** + **A3-C** | Five families gain `statement_kind` variants. Structured pairs are one ordered collection, never two sets. Collections need canonical ordering, or the fact hash is order-dependent and the duplicate refusal is defeated. External route/family contract unchanged; **internal family-model validation may be adapted to the union.** |
| **A4** | Barrier isolation state becomes route-declared structural scope. Context nodes yield no proposal; a statement completing an opener cites both nodes. |
| **A5** + **A5-C** | Completion is prohibited while a known proposal is uncovered, and still requires the maintainer's assertion — a lower bound, not a redefinition. Coverage binds to **source-statement identity plus cited evidence**, never to proposal-value equality: a corrected fact still covers its statement, and one fact never covers two statements. |
| **A6** + **A6-C** | Inspection run: a pre-correction package **can** exist and **would** differ, because A2 changes projected rule semantics for two dimensions whose reviewed domain is a strict subset of the consumer domain. **A compatibility bump is required and this branch already carries it** — no second increment; its recorded reason widens to cover projection semantics. The region slice runs its own inspection. |
| **A7** | Duplicate draft rows disappear through A2/A3, never through presentation-layer deduplication. |

### Remaining slices, in order

- [x] `DimensionScope` + the wildcard over-match fix — `dfa84a3`
- [ ] Per-family `statement_kind` variants, **one commit per family, smallest first**, each green on
      the full public suite and on the private suite where it moves the licensed path or the
      placeholders:
  - [x] **1. hf_attenuation** — the gate becomes a scope. This is the commit that teaches the shared
        machinery; see "Handoff: what family 1 must touch" below.
  - [x] **2. system_voltage** — measure | applicability. Introduces `statement_kind` and the
        carried-not-projected variant.
  - [x] **3. spd_monitoring** — requirement | exemption | compliance. Also converted
        `any_placement` to a scope, deleting `_placement_matcher`.
  - [ ] **4. spd_reduction** — permission | floor | monitoring. **Blocked on a contract decision,
        not on effort — see "Handoff: why family 4 stopped" below.** The three variants cannot all
        project into this route's declared row shape, and the one that must project cannot fill two
        of the six declared outputs from what it states.
  - [x] **5. barrier_transfer** — rating_resolution | combined_requirement |
        downstream_inheritance. The route-declared isolation scope and the invalid positive-isolation
        placeholder were pulled forward into this commit: the isolation field leaves the model, so
        the placeholder could not have been left as it was.
- [ ] Grammar relocation, context-node handling, set/pair collections — **family 4's pair collection
      now lives here, or in whichever slice resolves the contract question below**
- [ ] Variant editor: value-set widgets, repeating pair rows, `statement_kind` switching
- [ ] Removal of multi-statement authoring; per-statement suggestion action
- [ ] Completion guard
- [ ] Private placeholder replacement, including the invalid positive-isolation placeholder
- [ ] **Separate, separately reviewed, mandatory before #53B completes:** clause-region widening,
      with the private normative-paragraph inventory and the version inspection A6 requires

### Handoff: what family 1 (hf_attenuation) must touch

Written from the analysis already done, so a successor does not repeat it. Nothing below is
implemented; `dfa84a3` is the last code commit and the tree is green there.

`HfAttenuationFact.dvc_gate` is the smallest scope conversion and the one whose reviewed domain is
already narrower than its consumer input, so it exercises the `in`-not-wildcard path immediately.

**1. The fact model.** `dvc_gate` becomes `DimensionScope[DvcGate]` with
`DvcGate = Literal["dvc_as", "dvc_b"]`. Nothing else on the family changes; the gate's own union
reading needs no extra token, which is why the combined-designation token was dropped in A2.

**2. `fact_dimensions` must learn the scope kind — this is the blocker that forces the machinery
into this commit.** It currently raises `RulePackageError` for any annotation that is not a
`Literal`, `bool` or `str`, so putting a scope on a fact field without teaching it breaks the editor
and its vocabulary tests. Add `"scope"` to `DimensionKind`; detect it with
`get_origin(annotation) is DimensionScope`, and read the vocabulary out of the type argument:
`get_args(get_args(annotation)[0])`. Annotations resolve to real type objects despite
`from __future__ import annotations`, so `get_origin`/`get_args` work as written.

**3. The proposal payload needs a wire form for a set.** `ClauseFactProposal.chosen` is
`dict[str, str]`. Proposed shape: `"*"` for unrestricted, otherwise the sorted tokens joined by
`"|"`; absent key still means unchosen. One encode point in the proposer and one decode point in
`proposed_fact`. Deliberately cheap because the grammar relocates to the private side in the next
slice and this payload will be revisited there — do not build a typed payload model for it now.

**4. `keyword_proposer` must union, not multiply, for a scope dimension.** Today two rules matching
one dimension produce two drafts; for a scope they must produce **one** draft whose scope carries
both values. That is the A7 duplicate-expansion fix arriving for this family, and it is why the HF
sentence stops yielding two rows. The proposer learns which dimensions are scopes from
`fact_dimensions`.

**5. The projector.** The `shown` rows take `_scope_matcher("circuit_dvc", fact.dvc_gate,
reviewed_domain, _DVC_DESIGNATIONS)`. The `outstanding` rows are one per distinct concrete
designation across every fact's scope values, not one per fact. The projection-time expansion of a
union token discussed before A2 is **not** needed — `in` handles it, and `_require_distinct_branches`
already compares `in` matchers by value-set intersection.

**6. Call sites that will fail to construct until updated:** the HF fact builders in
`tests/rules/importer/test_clause_fact_review_api.py` (`_hf_fact`), the UI helper
`_fill_hf_dimensions` and the vocabulary expectation `_expected_options` in
`tests/ui/test_clause_fact_review.py`, and the HF placeholder in
`tests/private/test_iec62477_supply_clause_facts.py`. The private suite is mandatory for this commit
because that placeholder moves.

**7. The editor widget.** A scope needs a multi-select over its vocabulary plus an explicit
unrestricted entry. Do not conflate "every value selected" with unrestricted: they project
differently wherever the reviewed and consumer domains coincide. A multi-select list with a leading
`(unrestricted)` row is the smallest control that keeps all three modes reachable, and it is the same
widget the later editor slice needs for ordinary categorical sets, so it is not throwaway.

**8. Regressions this commit owns.** One reviewed statement naming both designations authors as a
single fact and projects a single row; the unreviewed third designation reaches no row; the sentence
that previously yielded two drafts now yields one.

For the completion guard slice, the A5 statement anchor should be **route + cited-node identity +
evidence hash**, never the sentence index, because the region-widening slice renumbers sentences.

### Handoff: what families 3 to 5 inherit

Written after families 1 and 2 landed. The shared machinery is in place; each remaining family is a
model change plus its projector, and the two corrections below are things the family 1 handoff got
wrong or could not know.

**1. Scope detection is not `get_origin`.** The family 1 handoff said to detect a scope field with
`get_origin(annotation) is DimensionScope`. It does not work: pydantic builds `DimensionScope[X]` as
a concrete model *class*, so `get_origin`/`get_args` return nothing and the type argument lives in
`__pydantic_generic_metadata__`. `clause_facts.scope_vocabulary` is the one reader for it; call that
rather than re-deriving it.

**2. The family-to-model map is now family-to-variants.** `FACT_MODELS_BY_KIND` maps a family to its
declared variants in order, and `fact_model(fact_kind, statement_kind)` / `fact_variants(fact_kind)`
are how every caller resolves one. `statement_kind` is required exactly when the family declares
variants and refused when it does not, so a family gaining variants makes its own callers fail loudly
rather than silently authoring whichever variant is declared first. What a variant family must also
update:

- its `ClauseFactGrammar` declares `statement_kind` (the grammar's rules are validated against that
  one variant's model);
- `propose_clause_facts` and `ClauseFactProposal` carry the kind, and `proposed_fact` reads it;
- nothing in the editor — it already asks for the statement kind before offering any dimension, and
  rebuilds the dimension rows when the kind changes.

**3. A carried-not-projected variant costs nothing extra now.** Resolution, the fact-set digest and
the approval gate need no change for one: they are per route, not per variant. The projector filters
to the variants it can answer with and refuses when none of them is present, rather than emitting a
zero-row rule. `spd_monitoring`'s **compliance** variant is the next one of these — this route's
declared `verification_reference` output carries none of `compliance_evidence`'s tokens, and widening
it is #53C item 5.

**4. spd_monitoring specifically.** `_spd_monitoring_row` reads `fact.monitoring_required` and
`fact.participates_in_reduction` as branch values today. With **requirement | exemption**, the
obligation is what the variant *is*, so the boolean field goes and the row's `monitoring_required`
comes from the variant — check `_require_distinct_branches` still separates the two, since a
requirement and an exemption over one placement must not both answer.

**5. Still outstanding, and not part of the variant commits.** The five `any_*` tokens on
`SystemVoltageStatement`/`SystemVoltageMeasureFact`, plus `any_placement` and `any_evidence`, remain
scalar-plus-token. Their projection is already correct through `_dimension_matcher` and
`_placement_matcher`, which both build a `DimensionScope` from the token, so this is a modelling
tidy-up rather than a behaviour fix — and it is what deletes those two shims. Do it per family or as
one commit after family 5; say which in your report.

**6. The private placeholders are one statement per route.** `_placeholder_facts` returns a
`dict[str, SupplyFact]`, so the licensed path exercises one variant per route -- the measure one for
system voltage. The carried variant is proven in the public suite only. Widening that dict to several
statements per route belongs to the private placeholder slice, which has to replace the invalid
positive-isolation placeholder anyway.

### Handoff: families 3 and 5 landed, and why family 4 stopped

Written after families 3 and 5. Both are on the branch and green on the public and private suites.
Family 4 is **not** an effort problem: its model reshape is straightforward, and the reshape makes
the route's declared rule unprojectable. That needs a contract decision, so it was reported rather
than guessed at.

**What families 3 and 5 changed that a successor inherits.**

- A carried-not-projected variant costs nothing new, as family 2's handoff said. Three more of them
  landed (`spd_monitoring.compliance`, `barrier_transfer.rating_resolution`,
  `barrier_transfer.downstream_inheritance`) with no change to resolution, the digest or the gate.
  The pattern is: filter the route's facts to the variants the rule's declared outputs can carry,
  refuse with `ClauseStructureError` when none is present, and assert in a test that the projected
  rule is *identical* with and without the carried statement.
- **Route-declared structural scope has a second member.** `SUPPLY_FACT_ISOLATION_BY_ROUTE` joins
  `SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE`, with its own import-time symmetric-difference check and its own
  branch in `clause_fact_defect`. Both halves are live: the projector reads the declared scope for
  every answer that follows from it, and the defect predicate refuses the one dimension a statement
  still spells that could contradict it. A third such dimension should follow the same three pieces.
- `_placement_matcher` is gone; `_dimension_matcher` is the last shim, and item 5 above still stands
  for it.
- `_placeholder_facts` is still `dict[str, SupplyFact]` and did not need widening: every route's
  projected variant is a single statement. It will need widening only when a route's projection needs
  two statements at once.

**Why family 4 stopped, so nobody re-derives it.** `supply.spd_reduction_requirements.{mains,
non_mains}` declares four inputs -- device placement, insulation class, device degradability,
participation in a category reduction -- and six outputs, and `DecisionRule` requires **every** row to
set **exactly** the declared outputs (`_rows_agree_with_declarations`). Today one `SpdReductionFact`
fills all six because it is a merge of the three statements A3 splits apart. After the split:

1. **The permission cannot fill `reduced_category`.** A `DecisionValue` carries one categorical
   value, and the permission's reviewed content is an ordered collection of source-to-target steps,
   which A3 requires and which may hold more than one member. One row per step gives rows whose
   matchers are identical -- `_require_distinct_branches` refuses them, and it zips facts against
   rows strictly, so a statement producing several rows is not even the shape that function takes.
   There is no source-category input to separate them by.
2. **The permission's row and the monitoring statement's row necessarily overlap.** The permission
   scopes the insulation class and states no degradability; the monitoring statement states the
   degradability and no insulation class; both are inside a category reduction. `_rows_overlap`
   treats a wildcard as never discriminating, so the two rows collide and the projector refuses the
   pair. Making them disjoint means the projector inventing a dimension one of the statements does
   not state, which is the defect A3 forbids from the other side.
3. **Whichever variant is dropped to a carried one takes two of the six outputs with it**, and the
   surviving row must still assert them. A permission-only projection asserts that monitoring is not
   required, which for a degradable device is a wrong answer rather than an absent one -- and a row
   may not omit an output to stay silent.

The floor variant is the one part that is clean: it is carried by instruction, and a consumer asking
about the double or reinforced classes reaches **no** row rather than a wrong one, because the
permission's own class scope excludes them.

Three ways out, for the maintainer to choose:

- **(c), and the one the amendments' own pointers keep naming.** Let #53C item 5's contract change
  land first -- a source-category input, and the monitoring and floor outputs right-sized off these
  routes -- and family 4 then projects all three variants with no loss. Every note in the recipe that
  says "#53C item 5" is about exactly this output tuple.
- **(a)** Ship the model reshape now, project the permission only, and accept a deferral token for
  `reduced_category` plus a wrong monitoring answer for a degradable device. Needs a version decision
  under A6-C, since it changes projected rule semantics.
- **(b)** As (a), but let the projector narrow the permission's row to the non-degradable case so the
  degradable branch is uncovered instead of wrongly answered. Cheaper than (c) and honest at runtime,
  but it is the projector adding a matcher no statement states.

Nothing about family 4 is implemented, so the tree carries no half-finished shape.
