# Clause Fact Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move normative branch authority for the IEC 62477-1:2022 supply rules out of Python
constants and into typed facts a maintainer authors from the licensed clause fragment.

**Architecture:** The importer proposes a clause's node inventory and nothing more. The maintainer
authors typed `SupplyFact` statements, each citing the nodes it rests on, plus one completion
record per `(clause, rule route)`. A fact's review binds a digest of exactly the evidence it cites,
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
- Nobody proposes a statement. The importer proposes the node inventory; the maintainer authors
  every fact. No public grammar may read clause prose to infer a branch.
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
#: licensed clauses: the reduction clauses state a permitted category step and its floor and then
#: refer to the monitoring clause, while the monitoring clause is the one that distinguishes a
#: bundled external device from an internal one and excuses monitoring for a device taking no part
#: in a reduction. A placement field on SpdReductionFact would be irrelevant to every statement
#: its own clause makes.
class SpdMonitoringFact(_Fact):
    fact_kind: Literal["spd_monitoring"] = "spd_monitoring"
    device_placement: Literal["bundled_external", "internal"]
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
    """Authoring three statements where the source states four would silently narrow the rule."""

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
without facts. Delete `_ATTENUATION_EVIDENCE_KINDS` and `_REQUIRED_EVIDENCE_KINDS`; keep
`_DVC_DESIGNATIONS` and `_HF_TRANSFORMER_DVC_GATE` only if they remain a declared vocabulary
rather than a branch list. The `threshold_reference` and `comparison_required` fields are carried
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
rule. The subclause for mains supply states eight cases: two sit at the foot of one page, the rest
continue on the next, and the recipe's single `(page_number, expected_bbox)` reaches only the three
bullets inside its rectangle. A separate subclause then states the ninth case, for non-mains supply,
and had no spec at all. Task 5 deleted a nine-branch constant and left a fact family able to
express six of the nine, with no citable evidence for the rest — which the public suite cannot see,
because every fixture is synthetic.

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
both of which must be reviewed and complete before it projects. Exactly one spec may project the
rule; the other contributes evidence only. Read `StandardRecipe`'s own validation before choosing
the mechanism — it requires a registered projector per spec and checks produced ids against
declared ones — and pick the arrangement that satisfies it without weakening a validator. Report
which you chose and why.

- [ ] **Step 3: Widen `SystemVoltageFact` to every reviewed case**

The family currently cannot express the two earthed-system arrangements stated before the page
break, nor the non-mains measure. Widen `phase_system` and `measure` so every reviewed case is
expressible, and check each new value against the projected rule's declared `allowed_values` — a
fact carrying a value the rule does not declare fails `DecisionRule`'s matcher validation only when
someone finally authors it, which for licensed content means much later.

Do **not** restore the deleted nine-branch constant. The shape is
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

Private, licensed: prove the real system voltage evidence inventory is complete across both scopes,
by fact family and typed identity. Keep the count and the per-route inventory private, consistent
with the decision already recorded for the other routes.

- [ ] **Step 5: Gates and commit**

```text
feat(rules): one clause may span several physical segments (#53)

ClauseAuditSpec assumed one semantic clause is one rectangle on one page. The
mains system-voltage subclause disproves it: two of its cases sit at the foot of
one page and the rest continue on the next, so the single declared rectangle
reached three of eight, and the non-mains subclause stating the ninth had no spec
at all. A slice whose premise is that the licensed clause is the authority cannot
read two thirds of a clause.

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

SystemVoltageFact widens to express every reviewed case rather than the six the
partial fragment happened to reach. The deleted branch inventory is not restored:
the authority is the evidence, not a constant standing in for the part of the
clause nobody extracted.

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
node pane showing `nodes(...)` for the selected route, and a Close button. Authoring a fact's
typed fields is the next increment; this task's deliverable is that the reviewer can see every
route, read its nodes, and that `author`/`complete` are the seam the editor will call. Do not add
an editor that is not tested.

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
