# DVC Semantic Selectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the positional runtime contract of `iec62477_2022.dvc.voltage_limits` and
`iec62477_2022.dvc.protection_matrix` with reviewed semantic selectors, so no consumer needs to
know that a physical row means a particular DVC designation.

**Architecture:** Each data row and column of both DVC tables gets an `AxisSelectorProposal`
during extraction — read by a public short-keyword grammar for three axes, and left empty by
construction for Table 3's columns. A maintainer confirms, corrects or supplies each one as an
`AxisSelectorReview` bound to both the proposal hash and the raw-grid artifact hash. A resolver
turns exact reviews into `ConfirmedAxes` and refuses anything missing, duplicated or stale; the
two projections then build their decision inputs and matchers from confirmed selectors only.
Physical coordinates survive in provenance.

**Tech Stack:** Python 3.13, Pydantic 2 frozen models, PySide6, pytest (+ pytest-qt,
pytest-xdist), mypy strict, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-08-11-issue-53a-dvc-semantic-selectors-design.md`

## Global Constraints

- Public repository holding rules imported from licensed IEC documents. Committed files may
  carry semantic identifiers, neutral token vocabularies, structural indexes, bounding boxes,
  and table and clause locators. They may **not** carry source wording, headings or header
  hierarchy phrasing, numeric content, the physical order of rows or columns, the pairing of a
  physical position to a selector, or the evidence used to derive a selector.
- A public grammar matches **short neutral keywords only** — single generic words, never a
  phrase or a heading. Table 3's column axis has no grammar and no proposal; its six selectors
  are supplied by the reviewer.
- `FaultTimeVoltageSelector.voltage_basis` stays exactly `dc | ac_rms | ac_peak |
  ac_unspecified`. Never add `dc_mean` or `ac_peak_or_dc` to it.
- Structural identifiers `protection-context-N`, `dvc_row` and `voltage_quantity` stay, and must
  never appear in projected `DecisionInput.allowed_values`, in matcher values, or in any
  application-facing API.
- Every declared decision input is mandatory (`evaluator.py:831`), so a structurally irrelevant
  selector dimension is an explicit `not_applicable` token, never an omitted input. Do not
  change the evaluator.
- `uv` is not on PATH. Prefix every command with:
  `$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"`
- Qt tests need `$env:QT_QPA_PLATFORM = "offscreen"`.
- Type-check with bare `uv run mypy` (pyproject scopes it to the package). Never `mypy src tests`.
- Full suite with coverage, exactly as CI runs it:
  `uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing`
- Private licensed-document tests skip without the PDFs. Never report a private-suite result a
  run did not produce.
- Do not implement #53 items 3-7. Do not touch PR #55's adapter.
- Commit messages end with: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- The Bash tool refuses compound commands it cannot verify stay inside the worktree; use plain
  separate commands, and `git commit -F <file>` with the message written to a file.

## The reviewed selector inventories

These are the semantic contract, as unordered sets. Which physical position produced which
selector is private. Every task that needs them uses exactly these values.

```text
Table 2 rows      dvc_as / dry
                  dvc_as / wet_and_saltwater_wet
                  dvc_b  / not_applicable
                  dvc_c  / not_applicable

Table 2 columns   normal                   / working_voltage   / ac_rms
                  normal                   / working_voltage   / ac_peak
                  normal                   / working_voltage   / dc_mean
                  normal                   / impulse_withstand / not_applicable
                  single_fault_or_abnormal / fault_voltage     / ac_peak_or_dc

Table 3 rows      dvc_as / not_applicable
                  dvc_b  / not_applicable
                  dvc_c  / not_applicable

Table 3 columns   accessible_part  / connected_to_pe     / not_applicable                / not_applicable      / not_applicable
                  accessible_part  / not_connected_to_pe / general_access                / ordinary_or_skilled / not_applicable
                  accessible_part  / not_connected_to_pe / service_or_restricted_access  / skilled_only        / not_applicable
                  adjacent_circuit / not_applicable      / not_applicable                / not_applicable      / dvc_as
                  adjacent_circuit / not_applicable      / not_applicable                / not_applicable      / dvc_b
                  adjacent_circuit / not_applicable      / not_applicable                / not_applicable      / dvc_c
```

## File Structure

Create:

- `src/insulation_coordination/rules/importer/axis_selectors.py` — the three selector models,
  the tagged union, the proposal and review models, and `ConfirmedAxes`. New module rather than
  more weight in `extract.py`, which is already ~1900 lines.
- `src/insulation_coordination/ui/axis_review.py` — the review model and dialog.
- `tests/rules/importer/test_axis_selectors.py`, `tests/rules/importer/test_axis_resolution.py`,
  `tests/ui/test_axis_review.py`.

Modify:

- `rules/importer/identify.py` — `AxisSelectorSpec` on `TableAuditSpec`; `GridProjector` gains a
  third parameter.
- `rules/importer/extract.py` — two draft fields, their digest coverage, proposal generation.
- `rules/importer/approval.py` — the blocker, and the re-projection call site.
- `rules/importer/review.py` — `review_axis_selector`, the resolver, and the projection call site.
- `rules/importer/recipes/iec62477_1_2022/tables.py` — axis specs on `TABLE_2` and `TABLE_3`.
- `rules/importer/recipes/iec62477_1_2022/projection.py` — both projections.
- `rules/importer/recipes/iec62477_1_2022/verification.py` — two projector signatures.
- `domain/rules.py` — `IEC_IMPORTER_VERSION`.
- `ui/rules_manager.py` — one button.

---

### Task 1: Selector models, proposal and review records

**Files:**
- Create: `src/insulation_coordination/rules/importer/axis_selectors.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py:512-527` (draft fields), and `_content_digest` plus its call sites so the new collections are covered by the draft digest
- Test: `tests/rules/importer/test_axis_selectors.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DvcDesignationSelector`, `Table2QuantitySelector`, `ProtectionTargetSelector`, the `AxisSelector` union, `AxisSelectorProposal`, `AxisSelectorReview`, `ConfirmedAxes`, and `ImportedRuleDraft.axis_selector_proposals` / `.axis_selector_reviews`.

- [ ] **Step 1: Write the failing tests**

Create `tests/rules/importer/test_axis_selectors.py`:

```python
"""Axis selector models: identity, totality, and hash stability."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from insulation_coordination.rules.importer.axis_selectors import (
    AxisSelectorProposal,
    ConfirmedAxes,
    DvcDesignationSelector,
    ProtectionTargetSelector,
    Table2QuantitySelector,
    selector_sha256,
)


def test_every_dimension_is_total_so_no_input_is_ever_omitted() -> None:
    """A structurally irrelevant dimension is not_applicable, never absent.

    evaluate_decision requires every declared input, so an optional field here would
    become an unanswerable runtime contract.
    """
    quantity = Table2QuantitySelector(
        operating_context="normal",
        quantity="impulse_withstand",
        basis="not_applicable",
    )
    target = ProtectionTargetSelector(
        target="adjacent_circuit",
        pe_relationship="not_applicable",
        access_context="not_applicable",
        person_scope="not_applicable",
        adjacent_dvc="dvc_b",
    )

    assert quantity.selector_kind == "table2_quantity"
    assert target.selector_kind == "protection_target"


def test_the_curve_basis_vocabulary_is_not_reused() -> None:
    """dc_mean is a Table 2 quantity; the curve's dc is a Figure 5 basis. #50 pinned that."""

    with pytest.raises(ValidationError):
        Table2QuantitySelector(
            operating_context="normal",
            quantity="working_voltage",
            basis="ac_unspecified",
        )


def test_the_union_round_trips_by_its_discriminator() -> None:
    designation = DvcDesignationSelector(designation="dvc_as", environment="dry")
    proposal = AxisSelectorProposal(
        grid_id="raw-iec62477_2022.dvc.voltage_limits",
        axis="row",
        index=3,
        selector=designation,
        proposal_sha256="a" * 64,
        grid_artifact_sha256="b" * 64,
    )

    restored = AxisSelectorProposal.model_validate(proposal.model_dump(mode="json"))

    assert restored.selector == designation
    assert restored == proposal


def test_an_unmatched_position_is_representable() -> None:
    """Table 3's columns have no grammar, so a proposal must be able to carry no selector."""

    proposal = AxisSelectorProposal(
        grid_id="raw-iec62477_2022.dvc.protection_matrix",
        axis="column",
        index=1,
        selector=None,
        proposal_sha256="c" * 64,
        grid_artifact_sha256="d" * 64,
    )

    assert proposal.selector is None


def test_selector_hash_is_stable_and_distinguishes_dimensions() -> None:
    first = DvcDesignationSelector(designation="dvc_as", environment="dry")
    same = DvcDesignationSelector(designation="dvc_as", environment="dry")
    other = DvcDesignationSelector(designation="dvc_as", environment="wet_and_saltwater_wet")

    assert selector_sha256(first) == selector_sha256(same)
    assert selector_sha256(first) != selector_sha256(other)


def test_confirmed_axes_reads_back_by_axis_and_index() -> None:
    axes = ConfirmedAxes(
        rows={3: DvcDesignationSelector(designation="dvc_b", environment="not_applicable")},
        columns={
            1: Table2QuantitySelector(
                operating_context="normal",
                quantity="working_voltage",
                basis="ac_rms",
            )
        },
    )

    assert axes.row(3).designation == "dvc_b"
    assert axes.column(1).basis == "ac_rms"
    with pytest.raises(KeyError):
        axes.row(4)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/test_axis_selectors.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named
'insulation_coordination.rules.importer.axis_selectors'`.

- [ ] **Step 3: Write the module**

Create `src/insulation_coordination/rules/importer/axis_selectors.py`:

```python
"""Reviewed semantic selectors for a grid's data rows and columns.

A physical row or column position is provenance. What a consumer resolves a rule by is the
selector a maintainer confirmed for that position, which is what these models carry. No
source wording, heading or value belongs here: only the neutral vocabulary the recipe and the
runtime contract share.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import Identifier, NotesText


class DvcDesignationSelector(FrozenModel):
    """A row axis position of either DVC table.

    ``environment`` is ``not_applicable`` where the source does not split the designation, so
    every declared decision input has an answer.
    """

    selector_kind: Literal["dvc_designation"] = "dvc_designation"
    designation: Literal["dvc_as", "dvc_b", "dvc_c"]
    environment: Literal["dry", "wet_and_saltwater_wet", "not_applicable"]


class Table2QuantitySelector(FrozenModel):
    """A column axis position of Table 2.

    ``basis`` deliberately does not reuse ``FaultTimeVoltageSelector.voltage_basis``: ``dc_mean``
    is a Table 2 working-voltage quantity and the curve's ``dc`` is a Figure 5 curve basis, so a
    consumer relating them must do so through an explicit mapping. #50 pinned that enum against
    widening.
    """

    selector_kind: Literal["table2_quantity"] = "table2_quantity"
    operating_context: Literal["normal", "single_fault_or_abnormal"]
    quantity: Literal["working_voltage", "impulse_withstand", "fault_voltage"]
    basis: Literal["ac_rms", "ac_peak", "dc_mean", "ac_peak_or_dc", "not_applicable"]


class ProtectionTargetSelector(FrozenModel):
    """A column axis position of Table 3."""

    selector_kind: Literal["protection_target"] = "protection_target"
    target: Literal["accessible_part", "adjacent_circuit"]
    pe_relationship: Literal["connected_to_pe", "not_connected_to_pe", "not_applicable"]
    access_context: Literal["general_access", "service_or_restricted_access", "not_applicable"]
    person_scope: Literal["ordinary_or_skilled", "skilled_only", "not_applicable"]
    adjacent_dvc: Literal["dvc_as", "dvc_b", "dvc_c", "not_applicable"]


AxisSelector: TypeAlias = Annotated[
    DvcDesignationSelector | Table2QuantitySelector | ProtectionTargetSelector,
    Field(discriminator="selector_kind"),
]


def selector_sha256(selector: AxisSelector) -> str:
    """Canonical hash of one selector, so a review can bind to the exact reading."""

    from insulation_coordination.rules.importer.extract import canonical_model_sha256

    return canonical_model_sha256(selector)


class AxisSelectorProposal(FrozenModel):
    """What the recipe's grammar read at one axis position, or nothing where it has none."""

    grid_id: Identifier
    axis: Literal["row", "column"]
    index: int = Field(ge=0)
    selector: AxisSelector | None
    proposal_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    grid_artifact_sha256: str = Field(pattern=r"[0-9a-f]{64}")


class AxisSelectorReview(FrozenModel):
    """Exact draft-only review of one axis position: confirmed, corrected or supplied.

    Bound to both the current proposal and the current raw-grid artifact, so a changed header
    reading, a changed grammar or a re-extracted grid drops the review and re-opens it.
    """

    grid_id: Identifier
    axis: Literal["row", "column"]
    index: int = Field(ge=0)
    proposal_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    grid_artifact_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    confirmed_selector: AxisSelector
    actor: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    notes: NotesText


class ConfirmedAxes(FrozenModel):
    """Resolved reviewed selectors handed to a projection. Empty for specs without axis specs."""

    rows: dict[int, AxisSelector] = {}
    columns: dict[int, AxisSelector] = {}

    def row(self, index: int) -> AxisSelector:
        return self.rows[index]

    def column(self, index: int) -> AxisSelector:
        return self.columns[index]
```

If `NotesText` or `Identifier` is not exported from `domain/rules.py`, import them from wherever
`CurveVariantReview` in `extract.py` imports them; do not redefine them.

- [ ] **Step 4: Add the draft fields**

In `src/insulation_coordination/rules/importer/extract.py`, add to `ImportedRuleDraft`
immediately after `manual_curve_traces`:

```python
    axis_selector_proposals: tuple[AxisSelectorProposal, ...] = ()
    axis_selector_reviews: tuple[AxisSelectorReview, ...] = ()
```

with the matching import from `insulation_coordination.rules.importer.axis_selectors`. Then
extend `_content_digest` with two keyword parameters of the same names and defaults, include them
in the digested payload exactly as `curve_variant_reviews` is included, and pass them at every
`_content_digest` call site that builds a draft. Search for `curve_variant_reviews` in that file
and mirror each occurrence — that is the complete list of places the two new collections belong.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/test_axis_selectors.py -q
```

Expected: 6 passed.

- [ ] **Step 6: Prove the draft digest covers the new fields**

Append to `tests/rules/importer/test_axis_selectors.py`:

```python
def test_the_draft_digest_covers_axis_reviews(synthetic_draft) -> None:
    """A review recorded without a digest change would be invisible to correction auditing."""

    from insulation_coordination.rules.importer.extract import canonical_model_sha256

    review = AxisSelectorReview(
        grid_id="raw-iec62477_2022.dvc.voltage_limits",
        axis="row",
        index=3,
        proposal_sha256="a" * 64,
        grid_artifact_sha256="b" * 64,
        confirmed_selector=DvcDesignationSelector(
            designation="dvc_b", environment="not_applicable"
        ),
        actor="tester",
        recorded_at=datetime(2026, 8, 11, tzinfo=UTC),
        notes="synthetic",
    )
    changed = synthetic_draft.model_copy(update={"axis_selector_reviews": (review,)})

    assert canonical_model_sha256(changed) != canonical_model_sha256(synthetic_draft)
```

Add `from datetime import UTC, datetime` to the imports. For `synthetic_draft`, reuse whichever
existing fixture or helper builds a minimal `ImportedRuleDraft` in
`tests/rules/importer/` — find it with
`grep -rn "ImportedRuleDraft(" tests/rules/importer | head` and use the smallest one; if the
nearest is a module-level helper rather than a fixture, import and call it directly instead of
taking a fixture parameter.

Run the file again; expected 7 passed.

- [ ] **Step 7: Gates and commit**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run ruff check .
```

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run mypy
```

Both must be clean. Commit message:

```text
feat(rules): add reviewed axis selector models (#53)

A physical row or column position is provenance; what a consumer resolves a
rule by should be the selector a maintainer confirmed for that position. Adds
the three selector models, their discriminated union, and the proposal and
review records that bind a confirmed selector to both the exact proposal and
the exact raw-grid artifact.

Every selector dimension is total, with an explicit not_applicable token,
because evaluate_decision requires every declared input. The Table 2 basis
vocabulary deliberately does not reuse FaultTimeVoltageSelector.voltage_basis.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 2: Recipe axis specs and proposal generation

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py:239-295` (`TableAuditSpec`)
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py` (`TABLE_2`, `TABLE_3`)
- Modify: `src/insulation_coordination/rules/importer/extract.py` (emit proposals)
- Test: `tests/rules/importer/iec62477_2022/test_axis_proposals.py`

**Interfaces:**
- Consumes: Task 1's `AxisSelectorProposal`, `AxisSelector`, `selector_sha256`, and `ImportedRuleDraft.axis_selector_proposals`.
- Produces: `AxisKeywordRule`, `AxisSelectorSpec`, `TableAuditSpec.axis_selectors: tuple[AxisSelectorSpec, ...]`, and `propose_axis_selectors(spec, grid) -> tuple[AxisSelectorProposal, ...]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/rules/importer/iec62477_2022/test_axis_proposals.py`:

```python
"""Axis proposals: keyword grammar for three axes, reviewer-supplied for Table 3's columns."""

from __future__ import annotations

from insulation_coordination.rules.importer.extract import propose_axis_selectors
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import (
    TABLE_2,
    TABLE_3,
)

EXPECTED_TABLE_2_ROWS = {
    ("dvc_as", "dry"),
    ("dvc_as", "wet_and_saltwater_wet"),
    ("dvc_b", "not_applicable"),
    ("dvc_c", "not_applicable"),
}
EXPECTED_TABLE_2_COLUMNS = {
    ("normal", "working_voltage", "ac_rms"),
    ("normal", "working_voltage", "ac_peak"),
    ("normal", "working_voltage", "dc_mean"),
    ("normal", "impulse_withstand", "not_applicable"),
    ("single_fault_or_abnormal", "fault_voltage", "ac_peak_or_dc"),
}


def test_table_2_declares_its_reviewed_row_and_column_inventories() -> None:
    """Stated independently of the recipe, as unordered sets: physical order is private."""

    rows = {
        (rule.selector.designation, rule.selector.environment)
        for spec in TABLE_2.axis_selectors
        if spec.axis == "row"
        for rule in spec.keyword_rules
    }
    columns = {
        (rule.selector.operating_context, rule.selector.quantity, rule.selector.basis)
        for spec in TABLE_2.axis_selectors
        if spec.axis == "column"
        for rule in spec.keyword_rules
    }

    assert rows == EXPECTED_TABLE_2_ROWS
    assert columns == EXPECTED_TABLE_2_COLUMNS


def test_table_3_columns_are_reviewer_supplied_with_no_keyword_rules() -> None:
    """A text grammar for that axis would need the header hierarchy's wording in public code."""

    column_spec = next(spec for spec in TABLE_3.axis_selectors if spec.axis == "column")

    assert column_spec.reviewer_supplied is True
    assert column_spec.keyword_rules == ()
    assert column_spec.expected_positions == 6


def test_no_keyword_is_a_phrase() -> None:
    """Short neutral keywords only. A multi-word keyword would be source wording."""

    for spec in (*TABLE_2.axis_selectors, *TABLE_3.axis_selectors):
        for rule in spec.keyword_rules:
            for keyword in rule.keywords:
                assert " " not in keyword
                assert keyword == keyword.lower()
                assert 0 < len(keyword) <= 12


def test_reviewer_supplied_axes_propose_nothing_but_still_enumerate_positions() -> None:
    grid = _protection_matrix_grid()

    proposals = propose_axis_selectors(TABLE_3, grid)
    columns = [item for item in proposals if item.axis == "column"]

    assert len(columns) == 6
    assert all(item.selector is None for item in columns)
    assert {item.index for item in columns} == set(range(1, 7))
```

`_protection_matrix_grid()` and the Table 2 equivalent used below must build a `RawGrid` whose
header cells carry synthetic neutral text. Reuse the existing synthetic grid builders: find them
with `grep -rn "def .*grid\b" tests/rules/importer/iec62477_2022/test_table3_projection.py
tests/rules/importer/iec62477_2022/test_table2_projection.py` and import or copy the smallest
one, then set each header cell's text to a synthetic string containing the keyword the recipe
declares for that position (for example `"as dry"` for the row you intend to be
`dvc_as / dry`). Synthetic text, never source text.

Add these two:

```python
def test_a_keyword_match_proposes_the_declared_selector() -> None:
    grid = _voltage_limits_grid()

    proposals = propose_axis_selectors(TABLE_2, grid)
    rows = {
        item.index: item.selector
        for item in proposals
        if item.axis == "row" and item.selector is not None
    }

    assert rows
    assert {
        (selector.designation, selector.environment) for selector in rows.values()
    } <= EXPECTED_TABLE_2_ROWS


def test_an_ambiguous_or_absent_match_proposes_nothing_rather_than_guessing() -> None:
    """Zero matches and two matches are both "no confirmed reading", never a positional guess."""

    grid = _voltage_limits_grid_with_header_text(row_index=3, text="nothing recognisable here")

    proposals = propose_axis_selectors(TABLE_2, grid)
    proposal = next(item for item in proposals if item.axis == "row" and item.index == 3)

    assert proposal.selector is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_axis_proposals.py -q
```

Expected: `ImportError: cannot import name 'propose_axis_selectors'`.

- [ ] **Step 3: Add the spec models**

In `src/insulation_coordination/rules/importer/identify.py`, above `TableAuditSpec`:

```python
class AxisKeywordRule(FrozenModel):
    """Short neutral keywords that together identify one axis position's selector.

    Every keyword must appear in the position's reviewed header text. Keywords are single
    generic words: a phrase would be source wording, which must not enter this repository.
    """

    keywords: tuple[str, ...] = Field(min_length=1)
    #: Keywords whose presence disqualifies this rule. One generic word can occur in more than
    #: one position's header text, and a rule that matched several positions would propose
    #: nothing at all: exactly one rule must match, or the position goes to the reviewer.
    excluded_keywords: tuple[str, ...] = ()
    selector: AxisSelector

    @model_validator(mode="after")
    def _keywords_are_single_words(self) -> AxisKeywordRule:
        for keyword in (*self.keywords, *self.excluded_keywords):
            if " " in keyword or keyword != keyword.lower() or not 0 < len(keyword) <= 12:
                raise ValueError("an axis keyword must be one short lowercase word")
        if set(self.keywords) & set(self.excluded_keywords):
            raise ValueError("a keyword cannot both be required and disqualify its own rule")
        return self


class AxisSelectorSpec(FrozenModel):
    """How one axis of a grid gets its reviewed semantic selectors."""

    axis: Literal["row", "column"]
    expected_positions: int = Field(ge=1)
    keyword_rules: tuple[AxisKeywordRule, ...] = ()
    #: This axis has no public grammar, so extraction proposes nothing and the reviewer
    #: supplies every selector. Used where a text grammar would require the source's header
    #: wording in public code.
    reviewer_supplied: bool = False

    @model_validator(mode="after")
    def _grammar_or_reviewer_but_not_both(self) -> AxisSelectorSpec:
        if self.reviewer_supplied and self.keyword_rules:
            raise ValueError("a reviewer-supplied axis declares no keyword rules")
        if not self.reviewer_supplied and not self.keyword_rules:
            raise ValueError("an axis needs keyword rules unless it is reviewer-supplied")
        return self
```

and add to `TableAuditSpec`, after `token_grammar`:

```python
    #: Axes whose data positions carry reviewed semantic selectors. A spec that declares any
    #: cannot be projected until every position of every declared axis has an exact review.
    axis_selectors: tuple[AxisSelectorSpec, ...] = ()
```

Import `AxisSelector` from `insulation_coordination.rules.importer.axis_selectors`.

- [ ] **Step 4: Declare the axes on both tables**

In `recipes/iec62477_1_2022/tables.py`, add to `TABLE_2`:

```python
axis_selectors = (
    (
        AxisSelectorSpec(
            axis="row",
            expected_positions=4,
            keyword_rules=(
                AxisKeywordRule(
                    keywords=("as", "dry"),
                    selector=DvcDesignationSelector(designation="dvc_as", environment="dry"),
                ),
                AxisKeywordRule(
                    keywords=("as", "wet"),
                    selector=DvcDesignationSelector(
                        designation="dvc_as", environment="wet_and_saltwater_wet"
                    ),
                ),
                AxisKeywordRule(
                    keywords=("b",),
                    selector=DvcDesignationSelector(
                        designation="dvc_b", environment="not_applicable"
                    ),
                ),
                AxisKeywordRule(
                    keywords=("c",),
                    selector=DvcDesignationSelector(
                        designation="dvc_c", environment="not_applicable"
                    ),
                ),
            ),
        ),
        AxisSelectorSpec(
            axis="column",
            expected_positions=5,
            keyword_rules=(
                AxisKeywordRule(
                    keywords=("rms",),
                    selector=Table2QuantitySelector(
                        operating_context="normal", quantity="working_voltage", basis="ac_rms"
                    ),
                ),
                # The bare peak keyword also occurs in two other columns' header text, so
                # without these exclusions three rules would match three positions each and
                # every one of them would propose nothing. Verified against the source.
                AxisKeywordRule(
                    keywords=("peak",),
                    excluded_keywords=("impulse", "fault"),
                    selector=Table2QuantitySelector(
                        operating_context="normal", quantity="working_voltage", basis="ac_peak"
                    ),
                ),
                AxisKeywordRule(
                    keywords=("mean",),
                    selector=Table2QuantitySelector(
                        operating_context="normal", quantity="working_voltage", basis="dc_mean"
                    ),
                ),
                AxisKeywordRule(
                    keywords=("impulse",),
                    selector=Table2QuantitySelector(
                        operating_context="normal",
                        quantity="impulse_withstand",
                        basis="not_applicable",
                    ),
                ),
                AxisKeywordRule(
                    keywords=("fault",),
                    selector=Table2QuantitySelector(
                        operating_context="single_fault_or_abnormal",
                        quantity="fault_voltage",
                        basis="ac_peak_or_dc",
                    ),
                ),
            ),
        ),
    ),
)
```

and to `TABLE_3`:

```python
axis_selectors = (
    (
        AxisSelectorSpec(
            axis="row",
            expected_positions=3,
            keyword_rules=(
                AxisKeywordRule(
                    keywords=("as",),
                    selector=DvcDesignationSelector(
                        designation="dvc_as", environment="not_applicable"
                    ),
                ),
                AxisKeywordRule(
                    keywords=("b",),
                    selector=DvcDesignationSelector(
                        designation="dvc_b", environment="not_applicable"
                    ),
                ),
                AxisKeywordRule(
                    keywords=("c",),
                    selector=DvcDesignationSelector(
                        designation="dvc_c", environment="not_applicable"
                    ),
                ),
            ),
        ),
        # No public grammar: a text grammar for this axis would require the source's header
        # hierarchy wording, which must not enter this repository. The reviewer supplies all
        # six protection-target selectors, and approval blocks until they do.
        AxisSelectorSpec(axis="column", expected_positions=6, reviewer_supplied=True),
    ),
)
```

Note that the `b` and `c` keyword rules must not also match the `as` positions. Implement
matching in the next step as whole-word matching over a normalized split, not substring
matching, so `as` does not match inside another word and `b` matches only a standalone `b`.

- [ ] **Step 5: Implement proposal generation**

In `src/insulation_coordination/rules/importer/extract.py`:

```python
def axis_positions(spec: TableAuditSpec, axis_spec: AxisSelectorSpec) -> tuple[int, ...]:
    """The physical positions one declared axis carries, read from the spec, never assumed.

    A row axis takes the data rows the spec's segments declare, because a table's data rows are
    not always contiguous — a note row can sit between two of them, and a contiguous range would
    then propose a note row and never propose the last real row at all. A column axis is
    contiguous from ``data_column_start``.
    """

    if axis_spec.axis == "row":
        declared = sorted({row for segment in spec.segments for row in segment.data_rows})
        positions = (
            tuple(declared)
            if declared
            else tuple(
                (spec.data_row_start or 0) + offset
                for offset in range(axis_spec.expected_positions)
            )
        )
    else:
        positions = tuple(
            (spec.data_column_start or 0) + offset for offset in range(axis_spec.expected_positions)
        )
    if len(positions) != axis_spec.expected_positions:
        raise ValueError(
            f"{spec.semantic_id} {axis_spec.axis} axis declares "
            f"{axis_spec.expected_positions} positions but the spec carries {len(positions)}"
        )
    return positions


def _axis_header_text(grid: RawGrid, spec: TableAuditSpec, axis: str, index: int) -> str:
    """The reviewed header cells a position's selector is read from.

    A row's header is the cells left of the data rectangle; a column's header is the cells
    above it. Both come from the reviewed grid, never from the recipe.
    """

    if axis == "row":
        limit = spec.data_column_start or 0
        cells = [cell for cell in grid.cells if cell.row == index and cell.column < limit]
    else:
        limit = spec.data_row_start or 0
        cells = [cell for cell in grid.cells if cell.column == index and cell.row < limit]
    return " ".join(cell.raw_text for cell in cells).lower()


def _matched_selector(axis_spec: AxisSelectorSpec, header_text: str) -> AxisSelector | None:
    """Exactly one keyword rule may match. Zero or several means no confirmed reading."""

    words = set(re.findall(r"[a-z]+", header_text))
    matched = [
        rule.selector
        for rule in axis_spec.keyword_rules
        if all(keyword in words for keyword in rule.keywords)
        and not any(keyword in words for keyword in rule.excluded_keywords)
    ]
    return matched[0] if len(matched) == 1 else None


def propose_axis_selectors(spec: TableAuditSpec, grid: RawGrid) -> tuple[AxisSelectorProposal, ...]:
    """One proposal per declared axis position, with no positional fallback anywhere."""

    proposals: list[AxisSelectorProposal] = []
    artifact = canonical_model_sha256(grid)
    for axis_spec in spec.axis_selectors:
        for index in axis_positions(spec, axis_spec, grid):
            selector = (
                None
                if axis_spec.reviewer_supplied
                else _matched_selector(
                    axis_spec, _axis_header_text(grid, spec, axis_spec.axis, index)
                )
            )
            proposals.append(
                AxisSelectorProposal(
                    grid_id=grid.id,
                    axis=axis_spec.axis,
                    index=index,
                    selector=selector,
                    proposal_sha256=_axis_proposal_sha256(grid.id, axis_spec.axis, index, selector),
                    grid_artifact_sha256=artifact,
                )
            )
    return tuple(proposals)


def _axis_proposal_sha256(
    grid_id: str, axis: str, index: int, selector: AxisSelector | None
) -> str:
    """Hash of the proposal's identity and its reading, so a review binds to both."""

    payload = f"{grid_id}|{axis}|{index}|{selector_sha256(selector) if selector else 'none'}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

Then call `propose_axis_selectors` where the draft's grids are assembled, and put the results in
`axis_selector_proposals`. Find the assembly point with
`grep -n "raw_grids=" src/insulation_coordination/rules/importer/extract.py` and add the
proposals for every table spec that declares `axis_selectors`, concatenated in spec order.
`re` and `hashlib` are already imported in that module; check before adding.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_axis_proposals.py -q
```

Expected: 6 passed. If a keyword rule matches two positions, the affected test fails with a
`None` selector where one was expected — fix the keywords, not the test.

- [ ] **Step 7: Gates and commit**

Run ruff and bare mypy; both clean. Then:

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer -q
```

Expected: no failures. Commit message:

```text
feat(rules): propose reviewed axis selectors from a keyword grammar (#53)

Both DVC tables declare which of their axes carry semantic selectors, and
extraction proposes one selector per declared position by matching short
neutral keywords in the reviewed header cells. Zero matches and several
matches both propose nothing: there is no positional fallback.

Table 3's column axis declares reviewer_supplied, so it proposes nothing by
construction. A text grammar for that axis would require the source's header
hierarchy wording, which must not enter this repository.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 3: The approval blocker and the review API

**Files:**
- Modify: `src/insulation_coordination/rules/importer/approval.py` (new blocker beside `CURVE_VARIANT_REVIEW_REQUIRED` at `:1305`)
- Modify: `src/insulation_coordination/rules/importer/review.py` (new `review_axis_selector`, modelled on `review_curve_variant` at `:2720`)
- Test: `tests/rules/importer/test_axis_review_api.py`

**Interfaces:**
- Consumes: Task 1's models, Task 2's `propose_axis_selectors` and `TableAuditSpec.axis_selectors`.
- Produces: `review_axis_selector(draft, *, grid_id, axis, index, selector, actor, notes) -> ImportedRuleDraft` and the `AXIS_SELECTOR_REVIEW_REQUIRED` blocker code.

- [ ] **Step 1: Write the failing tests**

Create `tests/rules/importer/test_axis_review_api.py`:

```python
"""Recording axis reviews, and the gate that requires them."""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.approval import ApprovalError, approval_blockers
from insulation_coordination.rules.importer.axis_selectors import DvcDesignationSelector
from insulation_coordination.rules.importer.review import review_axis_selector


def test_an_unreviewed_axis_position_blocks_approval(draft_with_axis_proposals) -> None:
    codes = {item.code for item in approval_blockers(draft_with_axis_proposals)}

    assert "AXIS_SELECTOR_REVIEW_REQUIRED" in codes


def test_confirming_every_position_clears_the_blocker(draft_with_axis_proposals) -> None:
    draft = draft_with_axis_proposals
    for proposal in draft.axis_selector_proposals:
        assert proposal.selector is not None, "this fixture proposes a reading for every position"
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=proposal.selector,
            actor="tester",
            notes="confirmed",
        )

    codes = {item.code for item in approval_blockers(draft)}

    assert "AXIS_SELECTOR_REVIEW_REQUIRED" not in codes


def test_a_review_records_the_reviewers_correction_not_the_proposal(
    draft_with_axis_proposals,
) -> None:
    """The reviewer is the authority; a hash-only record could not express this."""

    proposal = draft_with_axis_proposals.axis_selector_proposals[0]
    corrected = DvcDesignationSelector(designation="dvc_c", environment="not_applicable")

    draft = review_axis_selector(
        draft_with_axis_proposals,
        grid_id=proposal.grid_id,
        axis=proposal.axis,
        index=proposal.index,
        selector=corrected,
        actor="tester",
        notes="corrected",
    )

    review = next(
        item
        for item in draft.axis_selector_reviews
        if item.axis == proposal.axis and item.index == proposal.index
    )
    assert review.confirmed_selector == corrected
    assert review.proposal_sha256 == proposal.proposal_sha256


def test_a_second_review_of_one_position_replaces_the_first(draft_with_axis_proposals) -> None:
    proposal = draft_with_axis_proposals.axis_selector_proposals[0]
    draft = review_axis_selector(
        draft_with_axis_proposals,
        grid_id=proposal.grid_id,
        axis=proposal.axis,
        index=proposal.index,
        selector=DvcDesignationSelector(designation="dvc_b", environment="not_applicable"),
        actor="tester",
        notes="first",
    )
    draft = review_axis_selector(
        draft,
        grid_id=proposal.grid_id,
        axis=proposal.axis,
        index=proposal.index,
        selector=DvcDesignationSelector(designation="dvc_c", environment="not_applicable"),
        actor="tester",
        notes="second",
    )

    matching = [
        item
        for item in draft.axis_selector_reviews
        if item.axis == proposal.axis and item.index == proposal.index
    ]

    assert len(matching) == 1
    assert matching[0].confirmed_selector.designation == "dvc_c"


def test_actor_and_notes_are_required(draft_with_axis_proposals) -> None:
    proposal = draft_with_axis_proposals.axis_selector_proposals[0]

    with pytest.raises(ApprovalError):
        review_axis_selector(
            draft_with_axis_proposals,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=DvcDesignationSelector(designation="dvc_b", environment="not_applicable"),
            actor="  ",
            notes="",
        )


def test_reviewing_an_unknown_position_is_refused(draft_with_axis_proposals) -> None:
    with pytest.raises(ValueError):
        review_axis_selector(
            draft_with_axis_proposals,
            grid_id="raw-iec62477_2022.dvc.voltage_limits",
            axis="row",
            index=99,
            selector=DvcDesignationSelector(designation="dvc_b", environment="not_applicable"),
            actor="tester",
            notes="no such position",
        )
```

Add a `draft_with_axis_proposals` fixture in the same file: build the synthetic Table 2 grid from
Task 2's tests, run `propose_axis_selectors(TABLE_2, grid)`, and attach both the grid and the
proposals to the minimal `ImportedRuleDraft` helper Task 1 Step 6 located. Give every position a
matching header text so the fixture's own assertion about proposed readings holds.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/test_axis_review_api.py -q
```

Expected: `ImportError: cannot import name 'review_axis_selector'`.

- [ ] **Step 3: Implement the review API**

In `src/insulation_coordination/rules/importer/review.py`:

```python
def review_axis_selector(
    draft: ImportedRuleDraft,
    *,
    grid_id: str,
    axis: str,
    index: int,
    selector: AxisSelector,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Record one exact axis review: confirm, correct, or supply where nothing was proposed.

    The review binds the current proposal hash and the current grid artifact hash, so any
    change to either drops it and re-opens review.
    """

    if not actor.strip() or not notes.strip():
        raise ApprovalError("axis review actor and notes are required")
    proposal = next(
        (
            item
            for item in draft.axis_selector_proposals
            if item.grid_id == grid_id and item.axis == axis and item.index == index
        ),
        None,
    )
    if proposal is None:
        raise ValueError(f"unknown axis position: {grid_id} {axis} {index}")
    review = AxisSelectorReview(
        grid_id=grid_id,
        axis=proposal.axis,
        index=index,
        proposal_sha256=proposal.proposal_sha256,
        grid_artifact_sha256=proposal.grid_artifact_sha256,
        confirmed_selector=selector,
        actor=actor.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    kept = tuple(
        item
        for item in draft.axis_selector_reviews
        if not (item.grid_id == grid_id and item.axis == axis and item.index == index)
    )
    changed = draft.model_copy(update={"axis_selector_reviews": (*kept, review)})
    return record_correction(
        draft,
        changed,
        actor=actor,
        notes=f"record exact axis selector review: {notes}",
    )
```

Match `record_correction`'s real signature — read `review_curve_variant`'s call at
`review.py:2795` and pass the same shape of arguments.

- [ ] **Step 4: Implement the blocker**

In `src/insulation_coordination/rules/importer/approval.py`, inside the function that appends
`CURVE_VARIANT_REVIEW_REQUIRED` (around `:1286`), add a loop over every recipe table spec that
declares `axis_selectors`, over every declared position:

```python
for spec in (spec for recipe in RECIPES for spec in recipe.tables if spec.axis_selectors):
    grid_id = f"raw-{spec.semantic_id}"
    for proposal in (item for item in draft.axis_selector_proposals if item.grid_id == grid_id):
        exact = tuple(
            review
            for review in draft.axis_selector_reviews
            if review.grid_id == grid_id
            and review.axis == proposal.axis
            and review.index == proposal.index
            and review.proposal_sha256 == proposal.proposal_sha256
            and review.grid_artifact_sha256 == proposal.grid_artifact_sha256
        )
        if len(exact) != 1:
            blockers.append(
                _semantic_blocker(
                    draft,
                    code="AXIS_SELECTOR_REVIEW_REQUIRED",
                    semantic_id=spec.semantic_id,
                    message=(
                        f"{spec.semantic_id} {proposal.axis} position "
                        f"{proposal.index} lacks one exact axis selector review"
                    ),
                )
            )
```

One code covers both the unmatched and the merely unreviewed case: both mean "this position has
no confirmed selector", and the reviewer's action is identical.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/test_axis_review_api.py -q
```

Expected: 6 passed.

- [ ] **Step 6: Gates and commit**

Run ruff, bare mypy, then `uv run pytest tests/rules -q`. Commit message:

```text
feat(rules): require an exact review for every axis selector position (#53)

review_axis_selector records the reviewer's outcome — confirmed, corrected, or
supplied where the grammar proposed nothing — bound to the exact proposal and
the exact grid artifact, so either changing re-opens review. A position without
exactly one matching review blocks approval under
AXIS_SELECTOR_REVIEW_REQUIRED.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 4: The resolver and the projector interface

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py:551` (`GridProjector`)
- Modify: `src/insulation_coordination/rules/importer/review.py:1216` and `approval.py:791` (both call sites)
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/verification.py` (two projectors) and `projection.py` (two projectors — signature only in this task)
- Test: `tests/rules/importer/test_axis_resolution.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: `resolve_confirmed_axis_selectors(spec, grid, draft) -> ConfirmedAxes`, `AxisResolutionError`, and the three-parameter `GridProjector` contract `projector(grid, identity, confirmed_axes)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/rules/importer/test_axis_resolution.py` with one test per case. Use the
`draft_with_axis_proposals` fixture pattern from Task 3 (copy it into this file's own fixture, or
into `tests/rules/importer/conftest.py` if one exists there).

```python
"""Resolution refuses anything that is not an exact, current, unique review."""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.axis_selectors import DvcDesignationSelector
from insulation_coordination.rules.importer.review import (
    AxisResolutionError,
    resolve_confirmed_axis_selectors,
    review_axis_selector,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLE_2


def test_a_fully_reviewed_grid_resolves(fully_reviewed_draft, voltage_limits_grid) -> None:
    axes = resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, fully_reviewed_draft)

    assert len(axes.rows) == 4
    assert len(axes.columns) == 5


def test_a_missing_review_refuses(draft_with_axis_proposals, voltage_limits_grid) -> None:
    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft_with_axis_proposals)


def test_a_stale_proposal_hash_refuses(fully_reviewed_draft, voltage_limits_grid) -> None:
    stale = tuple(
        review.model_copy(update={"proposal_sha256": "0" * 64})
        for review in fully_reviewed_draft.axis_selector_reviews
    )
    draft = fully_reviewed_draft.model_copy(update={"axis_selector_reviews": stale})

    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft)


def test_a_stale_grid_artifact_hash_refuses(fully_reviewed_draft, voltage_limits_grid) -> None:
    stale = tuple(
        review.model_copy(update={"grid_artifact_sha256": "0" * 64})
        for review in fully_reviewed_draft.axis_selector_reviews
    )
    draft = fully_reviewed_draft.model_copy(update={"axis_selector_reviews": stale})

    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft)


def test_duplicate_reviews_for_one_position_refuse(
    fully_reviewed_draft, voltage_limits_grid
) -> None:
    first = fully_reviewed_draft.axis_selector_reviews[0]
    draft = fully_reviewed_draft.model_copy(
        update={"axis_selector_reviews": (*fully_reviewed_draft.axis_selector_reviews, first)}
    )

    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft)


def test_an_unmatched_position_resolves_once_a_review_supplies_it(
    draft_with_unmatched_row, voltage_limits_grid
) -> None:
    """The reviewer may supply a selector outright. Refusing this would forbid a designed path."""

    draft = draft_with_unmatched_row
    for proposal in draft.axis_selector_proposals:
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=proposal.selector
            or DvcDesignationSelector(designation="dvc_c", environment="not_applicable"),
            actor="tester",
            notes="supplied",
        )

    axes = resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft)

    assert len(axes.rows) == 4


def test_a_spec_without_axis_selectors_resolves_empty(draft_with_axis_proposals) -> None:
    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLES

    spec = next(item for item in TABLES if not item.axis_selectors)
    grid = _grid_for(spec)

    axes = resolve_confirmed_axis_selectors(spec, grid, draft_with_axis_proposals)

    assert axes.rows == {}
    assert axes.columns == {}
```

`draft_with_unmatched_row` is the Task 3 fixture with one row's header text replaced by
unrecognisable synthetic text, so its proposal carries `selector=None`. `_grid_for(spec)` builds a
minimal `RawGrid` with that spec's id; the resolver must not read its cells when no axis specs
are declared.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/test_axis_resolution.py -q
```

Expected: `ImportError: cannot import name 'AxisResolutionError'`.

- [ ] **Step 3: Implement the resolver**

In `src/insulation_coordination/rules/importer/review.py`:

```python
class AxisResolutionError(RulePackageError):
    """A grid's reviewed axis selectors are missing, duplicated or stale."""


def resolve_confirmed_axis_selectors(
    spec: TableAuditSpec,
    grid: RawGrid,
    draft: ImportedRuleDraft,
) -> ConfirmedAxes:
    """Reviewed axis facts for one grid, or an empty result for a spec that declares none.

    Resolution owns every refusal, so a projector receives either a complete context or an
    exception. A projector never inspects review state itself.
    """

    if not spec.axis_selectors:
        return ConfirmedAxes()
    artifact = canonical_model_sha256(grid)
    rows: dict[int, AxisSelector] = {}
    columns: dict[int, AxisSelector] = {}
    for axis_spec in spec.axis_selectors:
        for index in axis_positions(spec, axis_spec, grid):
            proposal = next(
                (
                    item
                    for item in draft.axis_selector_proposals
                    if item.grid_id == grid.id
                    and item.axis == axis_spec.axis
                    and item.index == index
                ),
                None,
            )
            if proposal is None:
                raise AxisResolutionError(
                    f"{grid.id} {axis_spec.axis} position {index} has no axis proposal"
                )
            exact = [
                review
                for review in draft.axis_selector_reviews
                if review.grid_id == grid.id
                and review.axis == axis_spec.axis
                and review.index == index
                and review.proposal_sha256 == proposal.proposal_sha256
                and review.grid_artifact_sha256 == artifact
            ]
            if len(exact) != 1:
                raise AxisResolutionError(
                    f"{grid.id} {axis_spec.axis} position {index} needs exactly one current "
                    f"review, found {len(exact)}"
                )
            target = rows if axis_spec.axis == "row" else columns
            target[index] = exact[0].confirmed_selector
    return ConfirmedAxes(rows=rows, columns=columns)
```

- [ ] **Step 4: Widen the projector interface**

In `identify.py`, change the alias:

```python
type GridProjector = Callable[[Any, StandardIdentity, Any], tuple[tuple[Any, ...], tuple[Any, ...]]]
```

Then update all four registered projectors to accept a third parameter named `confirmed_axes`.
The two in `verification.py` ignore it; add `# ponytail: unused here, the interface is uniform`
above each. The two in `projection.py` accept it now and use it in Tasks 5 and 6.

Update both call sites to resolve first:

`review.py:1216`

```python
            confirmed_axes = resolve_confirmed_axis_selectors(table_spec, grid, draft)
            projected, _proposals = grid_projector(grid, identity, confirmed_axes)
```

`approval.py:791`

```python
                from insulation_coordination.rules.importer.review import (
                    resolve_confirmed_axis_selectors,
                )

                expected, _proposals = projector(
                    grid, identity, resolve_confirmed_axis_selectors(spec, grid, draft)
                )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/test_axis_resolution.py -q
```

Expected: 7 passed.

- [ ] **Step 6: Prove the migration did not break the other projectors**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules -q
```

Expected: failures only in `test_table2_projection.py` and `test_table3_projection.py`, which
Tasks 5 and 6 rewrite. Every verification-projector test must pass. If one fails, the uniform
signature change is wrong — fix it here, not in a later task.

- [ ] **Step 7: Gates and commit**

Run ruff and bare mypy. Commit message:

```text
feat(rules): resolve reviewed axis facts before projecting a grid (#53)

Resolution turns exact current axis reviews into ConfirmedAxes and owns every
refusal: a position missing a review, carrying two, or bound to a stale
proposal or grid artifact stops the projection. A spec declaring no axis
selectors resolves empty.

GridProjector takes ConfirmedAxes as a third parameter, uniformly across all
four registered projectors, rather than adding a second registry: this is one
projection operation with reviewed facts optionally available, not two kinds of
projector.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 5: Table 2 projects semantic selectors

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/projection.py:103-278`
- Test: `tests/rules/importer/iec62477_2022/test_table2_projection.py`

**Interfaces:**
- Consumes: `ConfirmedAxes`, `resolve_confirmed_axis_selectors`, the selector models.
- Produces: `project_dvc_voltage_limits(grid, identity, confirmed_axes)` emitting inputs `dvc, environment, operating_context, quantity, basis, unit`.

- [ ] **Step 1: Write the failing tests**

In `tests/rules/importer/iec62477_2022/test_table2_projection.py`, replace the positional
expectations (the dict at `:171` asserting `"dvc": "dvc-1"` and
`"voltage_quantity": "voltage-quantity-1"`) and add:

```python
EXPECTED_ROW_SELECTORS = {
    ("dvc_as", "dry"),
    ("dvc_as", "wet_and_saltwater_wet"),
    ("dvc_b", "not_applicable"),
    ("dvc_c", "not_applicable"),
}
EXPECTED_COLUMN_SELECTORS = {
    ("normal", "working_voltage", "ac_rms"),
    ("normal", "working_voltage", "ac_peak"),
    ("normal", "working_voltage", "dc_mean"),
    ("normal", "impulse_withstand", "not_applicable"),
    ("single_fault_or_abnormal", "fault_voltage", "ac_peak_or_dc"),
}


def test_no_positional_identifier_reaches_the_runtime_contract() -> None:
    rules, _ = _project()

    for rule in rules:
        for declared in rule.inputs:
            for value in declared.allowed_values:
                assert not re.fullmatch(r"dvc-\d+|voltage-quantity-\d+", value)
        for row in rule.rows:
            for matcher in row.matchers:
                for value in matcher.values:
                    assert not re.fullmatch(r"dvc-\d+|voltage-quantity-\d+", str(value))


def test_the_declared_inputs_are_the_semantic_dimensions() -> None:
    rules, _ = _project()

    for rule in rules:
        assert {item.name for item in rule.inputs} == {
            "dvc",
            "environment",
            "operating_context",
            "quantity",
            "basis",
            "unit",
        }


def test_allowed_values_come_from_the_confirmed_selectors() -> None:
    rules, _ = _project()
    rule = rules[0]
    allowed = {item.name: set(item.allowed_values) for item in rule.inputs}

    assert allowed["dvc"] == {"dvc_as", "dvc_b", "dvc_c"}
    assert allowed["environment"] == {"dry", "wet_and_saltwater_wet", "not_applicable"}
    assert allowed["quantity"] == {"working_voltage", "impulse_withstand", "fault_voltage"}


def test_a_reordered_grid_projects_the_same_semantics() -> None:
    """Coordinates are provenance. Reordering physical rows must not change any matcher."""

    straight, _ = _project()
    reordered, _ = _project(reorder_rows=True)

    def semantics(rules):
        return {
            (
                rule.id,
                tuple(sorted((m.input, tuple(map(str, m.values))) for m in row.matchers)),
                tuple(
                    str(value.numeric or value.reference or value.boolean) for value in row.values
                ),
            )
            for rule in rules
            for row in rule.rows
        }

    assert semantics(reordered) == semantics(straight)


def test_the_impulse_column_evaluates_with_its_not_applicable_sentinel() -> None:
    rules, _ = _project()
    rule = next(item for item in rules if item.id.endswith(".impulse_reference"))

    result = evaluate_decision(
        rule,
        {
            "dvc": "dvc_b",
            "environment": "not_applicable",
            "operating_context": "normal",
            "quantity": "impulse_withstand",
            "basis": "not_applicable",
            "unit": "V",
        },
    )

    assert result.status in {"matched", "no_match"}


def test_omitting_a_dimension_is_input_required_not_a_guess() -> None:
    rules, _ = _project()

    result = evaluate_decision(rules[0], {"dvc": "dvc_b"})

    assert result.status == "input_required"
    assert "basis" in result.missing_inputs
```

Two more tests, which the two constants above exist for. Without them the design's requirement
that the inventories are stated independently of the recipe is untested for this table:

```python
def test_the_confirmed_selector_inventories_match_the_expected_sets() -> None:
    """Unordered sets, so the recipe and the expectation can disagree.

    Which physical position produced which selector is provenance and deliberately not
    asserted: the contract is the set of selectors, not their order.
    """
    _rules, axes = _project()

    rows = {(item.designation, item.environment) for item in axes.rows.values()}
    columns = {
        (item.operating_context, item.quantity, item.basis) for item in axes.columns.values()
    }

    assert rows == EXPECTED_ROW_SELECTORS
    assert columns == EXPECTED_COLUMN_SELECTORS


def test_every_projected_rule_arrives_as_a_proposal_awaiting_review() -> None:
    """A projected rule must not reach an approved package without a review of its own."""

    rules, proposals = _project_with_proposals()

    assert {proposal.semantic_id for proposal in proposals} == {rule.id for rule in rules}
    assert all(proposal.state == "proposed" for proposal in proposals)
```

`test_allowed_values_come_from_the_confirmed_selectors` must assert all five semantic inputs,
including `operating_context == {"normal", "single_fault_or_abnormal"}` and the full `basis`
vocabulary — not only the three shown above.

`_project(reorder_rows=False)` builds the synthetic grid, proposes axes, records a review per
position with `review_axis_selector`, resolves, calls
`project_dvc_voltage_limits(grid, identity, confirmed_axes)` and returns
`(rules, confirmed_axes)`. `_project_with_proposals()` does the same and returns
`(rules, proposals)`. With `reorder_rows=True` it swaps two data rows' header text **and** their
cell values together, so the same semantics live at different positions. Import `re` and
`evaluate_decision`.

- [ ] **Step 2: Run to verify failure**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_table2_projection.py -q
```

Expected: failures showing `dvc-1` still in `allowed_values`, and a `TypeError` about the
projector's third argument if the helper passes one before the signature changes.

- [ ] **Step 3: Rewrite the projection's selectors**

In `projection.py`, delete `_dvc` and `_quantity` (`:103-115`) and replace `_table_2_inputs` and
`_matchers` with confirmed-selector versions:

```python
def _table_2_inputs(grid: RawGrid, axes: ConfirmedAxes) -> tuple[DecisionInput, ...]:
    """Runtime inputs from the reviewed selectors, never from a physical coordinate."""

    rows = tuple(cast(DvcDesignationSelector, item) for item in axes.rows.values())
    columns = tuple(cast(Table2QuantitySelector, item) for item in axes.columns.values())
    return (
        DecisionInput(
            name="dvc",
            kind="categorical",
            allowed_values=tuple(sorted({item.designation for item in rows})),
        ),
        DecisionInput(
            name="environment",
            kind="categorical",
            allowed_values=tuple(sorted({item.environment for item in rows})),
        ),
        DecisionInput(
            name="operating_context",
            kind="categorical",
            allowed_values=tuple(sorted({item.operating_context for item in columns})),
        ),
        DecisionInput(
            name="quantity",
            kind="categorical",
            allowed_values=tuple(sorted({item.quantity for item in columns})),
        ),
        DecisionInput(
            name="basis",
            kind="categorical",
            allowed_values=tuple(sorted({item.basis for item in columns})),
        ),
        DecisionInput(name="unit", kind="categorical", allowed_values=(grid.target_unit,)),
    )


def _matchers(outcome: _Outcome, unit: str, axes: ConfirmedAxes) -> tuple[Matcher, ...]:
    row = cast(DvcDesignationSelector, axes.row(outcome.row))
    column = cast(Table2QuantitySelector, axes.column(outcome.column))
    return (
        Matcher(input="dvc", op="equals", values=(row.designation,)),
        Matcher(input="environment", op="equals", values=(row.environment,)),
        Matcher(input="operating_context", op="equals", values=(column.operating_context,)),
        Matcher(input="quantity", op="equals", values=(column.quantity,)),
        Matcher(input="basis", op="equals", values=(column.basis,)),
        Matcher(input="unit", op="equals", values=(unit,)),
    )
```

Thread `axes` through the four rule builders (`_numeric_rule`, `_curve_reference_rule`,
`_impulse_reference_rule`, `_not_applicable_rule`) — each takes it as a parameter and passes it to
`_table_2_inputs` and `_matchers`. Then:

```python
def project_dvc_voltage_limits(
    grid: RawGrid,
    identity: StandardIdentity,
    confirmed_axes: ConfirmedAxes,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project a complete reviewed Table 2 grid into proposed typed decisions."""

    if grid.id != f"raw-{ids.DVC_VOLTAGE_LIMITS}":
        raise ValueError("Table 2 projection requires the DVC voltage-limit grid")
    if grid.source.standard != identity.standard or grid.source.edition != identity.edition:
        raise ValueError("Table 2 grid does not match its identified source")
    if (
        len(confirmed_axes.rows) != TABLE_2.expected_data_rows
        or len(confirmed_axes.columns) != TABLE_2.expected_data_columns
    ):
        raise ValueError("Table 2 projection needs every reviewed axis selector")
```

keeping the rest of the body and passing `confirmed_axes` to each builder. The inventory check is
a defensive invariant only: resolution has already refused anything incomplete, and this
projection must not inspect review state itself.

- [ ] **Step 4: Run to verify passing**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_table2_projection.py -q
```

Expected: all pass.

- [ ] **Step 5: Gates and commit**

Run ruff, bare mypy, and `uv run pytest tests/rules -q` (Table 3's tests still fail; that is
Task 6). Commit message:

```text
feat(rules): Table 2 projects reviewed semantic selectors (#53)

dvc-N and voltage-quantity-N no longer reach a consumer. The rule's inputs are
the reviewed dimensions — designation, environment, operating context, quantity
and basis — and every allowed value comes from the confirmed axis selectors.
Route ids and outputs are unchanged, so the curve and Table 7 references still
resolve rather than duplicating values.

A test proves a reordered grid projects identical semantics: the physical
position is provenance.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 6: Table 3 projects semantic selectors

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/projection.py:340-420`
- Test: `tests/rules/importer/iec62477_2022/test_table3_projection.py`

**Interfaces:**
- Consumes: Task 4's resolver and Task 5's threading pattern.
- Produces: `project_dvc_protection_matrix(grid, identity, confirmed_axes)` emitting inputs `dvc, target, pe_relationship, access_context, person_scope, adjacent_dvc`.

- [ ] **Step 1: Write the failing tests**

In `tests/rules/importer/iec62477_2022/test_table3_projection.py`, replace the positional
expectation at `:130` and add:

```python
EXPECTED_PROTECTION_TARGET_SELECTORS = {
    ("accessible_part", "connected_to_pe", "not_applicable", "not_applicable", "not_applicable"),
    (
        "accessible_part",
        "not_connected_to_pe",
        "general_access",
        "ordinary_or_skilled",
        "not_applicable",
    ),
    (
        "accessible_part",
        "not_connected_to_pe",
        "service_or_restricted_access",
        "skilled_only",
        "not_applicable",
    ),
    ("adjacent_circuit", "not_applicable", "not_applicable", "not_applicable", "dvc_as"),
    ("adjacent_circuit", "not_applicable", "not_applicable", "not_applicable", "dvc_b"),
    ("adjacent_circuit", "not_applicable", "not_applicable", "not_applicable", "dvc_c"),
}


def test_the_six_reviewed_protection_targets_are_the_contract() -> None:
    """An unordered set: which physical column produced which selector stays private."""

    _rules, confirmed = _project()
    selectors = {
        (
            item.target,
            item.pe_relationship,
            item.access_context,
            item.person_scope,
            item.adjacent_dvc,
        )
        for item in confirmed.columns.values()
    }

    assert selectors == EXPECTED_PROTECTION_TARGET_SELECTORS


def test_no_positional_identifier_reaches_the_runtime_contract() -> None:
    rules, _ = _project()

    for rule in rules:
        for declared in rule.inputs:
            for value in declared.allowed_values:
                assert not re.fullmatch(r"dvc-\d+|protection-context-\d+", value)
        for row in rule.rows:
            for matcher in row.matchers:
                for value in matcher.values:
                    assert not re.fullmatch(r"dvc-\d+|protection-context-\d+", str(value))


def test_the_declared_inputs_are_the_semantic_dimensions() -> None:
    rules, _ = _project()

    assert {item.name for item in rules[0].inputs} == {
        "dvc",
        "target",
        "pe_relationship",
        "access_context",
        "person_scope",
        "adjacent_dvc",
    }


def test_an_adjacent_circuit_column_evaluates_with_its_not_applicable_dimensions() -> None:
    rules, _ = _project()

    result = evaluate_decision(
        rules[0],
        {
            "dvc": "dvc_b",
            "target": "adjacent_circuit",
            "pe_relationship": "not_applicable",
            "access_context": "not_applicable",
            "person_scope": "not_applicable",
            "adjacent_dvc": "dvc_c",
        },
    )

    assert result.status in {"matched", "no_match"}


def test_a_reordered_grid_projects_the_same_semantics() -> None:
    straight, _ = _project()
    reordered, _ = _project(reorder_columns=True)

    def semantics(rules):
        return {
            (
                rule.id,
                tuple(sorted((m.input, tuple(map(str, m.values))) for m in row.matchers)),
                tuple(value.categorical for value in row.values),
            )
            for rule in rules
            for row in rule.rows
        }

    assert semantics(reordered) == semantics(straight)
```

`_project()` returns `(rules, confirmed_axes)`. Because Table 3's column axis is
reviewer-supplied, the helper must record a review for each of the six columns from
`EXPECTED_PROTECTION_TARGET_SELECTORS` in a fixed order of its own choosing, and for the three
rows from the row proposals. `reorder_columns=True` assigns those same six selectors to different
physical columns while moving each column's cell values with it.

- [ ] **Step 2: Run to verify failure**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_table3_projection.py -q
```

Expected: failures naming `protection-context-1` in `allowed_values`.

- [ ] **Step 3: Rewrite the projection**

In `projection.py`'s `_protection_rule`, delete the `dvcs` and `contexts` derivations
(`:351-352`) and build inputs and matchers from `ConfirmedAxes`:

```python
def _protection_rule(
    grid: RawGrid,
    cells: tuple[_ProtectionCell, ...],
    axes: ConfirmedAxes,
) -> DecisionRule:
    rows = tuple(cast(DvcDesignationSelector, item) for item in axes.rows.values())
    columns = tuple(cast(ProtectionTargetSelector, item) for item in axes.columns.values())
    return DecisionRule(
        id=ids.DVC_PROTECTION_MATRIX,
        inputs=(
            DecisionInput(
                name="dvc",
                kind="categorical",
                allowed_values=tuple(sorted({item.designation for item in rows})),
            ),
            DecisionInput(
                name="target",
                kind="categorical",
                allowed_values=tuple(sorted({item.target for item in columns})),
            ),
            DecisionInput(
                name="pe_relationship",
                kind="categorical",
                allowed_values=tuple(sorted({item.pe_relationship for item in columns})),
            ),
            DecisionInput(
                name="access_context",
                kind="categorical",
                allowed_values=tuple(sorted({item.access_context for item in columns})),
            ),
            DecisionInput(
                name="person_scope",
                kind="categorical",
                allowed_values=tuple(sorted({item.person_scope for item in columns})),
            ),
            DecisionInput(
                name="adjacent_dvc",
                kind="categorical",
                allowed_values=tuple(sorted({item.adjacent_dvc for item in columns})),
            ),
        ),
        outputs=(
            DecisionOutput(
                name="protection_requirement",
                kind="categorical",
                allowed_values=_PROTECTION_REQUIREMENTS,
            ),
        ),
        rows=tuple(
            DecisionRow(
                matchers=_protection_matchers(cell, axes),
                values=(
                    DecisionValue(name="protection_requirement", categorical=cell.requirement),
                ),
                source=cell.source,
            )
            for cell in cells
        ),
        exhaustive=False,
        source=grid.source,
    )


def _protection_matchers(cell: _ProtectionCell, axes: ConfirmedAxes) -> tuple[Matcher, ...]:
    row = cast(DvcDesignationSelector, axes.row(cell.physical_row))
    column = cast(ProtectionTargetSelector, axes.column(cell.physical_column))
    return (
        Matcher(input="dvc", op="equals", values=(row.designation,)),
        Matcher(input="target", op="equals", values=(column.target,)),
        Matcher(input="pe_relationship", op="equals", values=(column.pe_relationship,)),
        Matcher(input="access_context", op="equals", values=(column.access_context,)),
        Matcher(input="person_scope", op="equals", values=(column.person_scope,)),
        Matcher(input="adjacent_dvc", op="equals", values=(column.adjacent_dvc,)),
    )
```

`_ProtectionCell` currently carries `logical_row` / `logical_column`. Read its definition and use
whichever attributes hold the **physical** grid indices, because `ConfirmedAxes` is keyed by
physical index; if only logical indices are carried, add the physical ones to that model in this
task and set them where the cell is built. Keep `ProtectionOutcome` if other code uses it;
otherwise delete it rather than leaving a model nothing constructs.

Update `project_dvc_protection_matrix` to take `confirmed_axes`, assert the inventory is complete
(3 rows, 6 columns) as a defensive invariant, and pass it down.

- [ ] **Step 4: Run to verify passing, then the whole rules suite**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_table3_projection.py -q
```

Expected: all pass. Then:

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules -q
```

Expected: no failures anywhere. Any remaining failure is a real integration break — fix it here.

- [ ] **Step 5: Gates and commit**

Run ruff and bare mypy. Commit message:

```text
feat(rules): Table 3 projects reviewed protection targets (#53)

protection-context-N and dvc-N no longer reach a consumer. The protection
matrix's inputs are the reviewed structured dimensions, and its six column
selectors are supplied by the reviewer because a public text grammar for that
axis would need the source's header hierarchy wording.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 7: The Rules Manager review surface

**Files:**
- Create: `src/insulation_coordination/ui/axis_review.py`
- Modify: `src/insulation_coordination/ui/rules_manager.py` (one button, beside `_review_curves_button` at `:146`)
- Test: `tests/ui/test_axis_review.py`

**Interfaces:**
- Consumes: `review_axis_selector`, `draft.axis_selector_proposals`, `draft.axis_selector_reviews`, the three selector models.
- Produces: `AxisReviewModel` with `.rows() -> tuple[AxisReviewRow, ...]` and `.confirm(grid_id, axis, index, selector, *, actor, notes)`, and `AxisReviewDialog`.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_axis_review.py`:

```python
"""The axis review surface: proposals in, decisions out. No review logic in Qt."""

from __future__ import annotations

from insulation_coordination.rules.importer.axis_selectors import DvcDesignationSelector
from insulation_coordination.ui.axis_review import AxisReviewDialog, AxisReviewModel


def test_the_model_lists_every_position_with_its_status(draft_with_axis_proposals) -> None:
    model = AxisReviewModel(draft_with_axis_proposals)

    rows = model.rows()

    assert len(rows) == len(draft_with_axis_proposals.axis_selector_proposals)
    assert all(row.status == "needs_review" for row in rows)


def test_a_reviewer_supplied_position_reports_no_proposal(draft_with_unmatched_row) -> None:
    model = AxisReviewModel(draft_with_unmatched_row)

    unmatched = [row for row in model.rows() if row.proposed is None]

    assert unmatched
    assert all(row.status == "needs_review" for row in unmatched)


def test_confirming_updates_the_status_and_the_draft(draft_with_axis_proposals) -> None:
    model = AxisReviewModel(draft_with_axis_proposals)
    first = model.rows()[0]

    model.confirm(
        first.grid_id,
        first.axis,
        first.index,
        DvcDesignationSelector(designation="dvc_b", environment="not_applicable"),
        actor="tester",
        notes="confirmed",
    )

    updated = next(
        row
        for row in model.rows()
        if (row.grid_id, row.axis, row.index) == (first.grid_id, first.axis, first.index)
    )
    assert updated.status == "reviewed"
    assert model.draft.axis_selector_reviews


def test_the_dialog_shows_one_row_per_position(qtbot, draft_with_axis_proposals) -> None:
    dialog = AxisReviewDialog(AxisReviewModel(draft_with_axis_proposals))
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == len(draft_with_axis_proposals.axis_selector_proposals)
    assert dialog.table.columnCount() == 5
```

Reuse the Task 3 fixtures; if `tests/ui/conftest.py` has no access to them, move the two fixtures
into `tests/conftest.py` in this task rather than duplicating their construction.

- [ ] **Step 2: Run to verify failure**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; $env:QT_QPA_PLATFORM = "offscreen"; uv run pytest tests/ui/test_axis_review.py -q
```

Expected: `ModuleNotFoundError: No module named 'insulation_coordination.ui.axis_review'`.

- [ ] **Step 3: Write the model and dialog**

Create `src/insulation_coordination/ui/axis_review.py`. Keep the split `curve_review.py` uses:
the model delegates every mutation to the importer's review function, and Qt only displays and
gathers.

```python
"""Axis selector review: confirm, correct or supply one selector per axis position.

Qt holds no review logic. Every decision goes through review_axis_selector, which records an
audited correction and binds the review to the exact proposal and grid artifact.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.rules.importer.axis_selectors import AxisSelector
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.review import review_axis_selector

_HEADINGS = ("table", "axis", "position", "proposed", "status")


class AxisReviewRow(FrozenModel):
    """One axis position as the reviewer sees it."""

    grid_id: str
    axis: Literal["row", "column"]
    index: int
    proposed: AxisSelector | None
    confirmed: AxisSelector | None
    status: Literal["needs_review", "reviewed"]


class AxisReviewModel:
    """Review actions over one draft's axis selector proposals."""

    def __init__(self, draft: ImportedRuleDraft) -> None:
        self._draft = draft

    @property
    def draft(self) -> ImportedRuleDraft:
        return self._draft

    def rows(self) -> tuple[AxisReviewRow, ...]:
        rows: list[AxisReviewRow] = []
        for proposal in self._draft.axis_selector_proposals:
            exact = next(
                (
                    review
                    for review in self._draft.axis_selector_reviews
                    if review.grid_id == proposal.grid_id
                    and review.axis == proposal.axis
                    and review.index == proposal.index
                    and review.proposal_sha256 == proposal.proposal_sha256
                    and review.grid_artifact_sha256 == proposal.grid_artifact_sha256
                ),
                None,
            )
            rows.append(
                AxisReviewRow(
                    grid_id=proposal.grid_id,
                    axis=proposal.axis,
                    index=proposal.index,
                    proposed=proposal.selector,
                    confirmed=exact.confirmed_selector if exact else None,
                    status="reviewed" if exact else "needs_review",
                )
            )
        return tuple(rows)

    def confirm(
        self,
        grid_id: str,
        axis: str,
        index: int,
        selector: AxisSelector,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = review_axis_selector(
            self._draft,
            grid_id=grid_id,
            axis=axis,
            index=index,
            selector=selector,
            actor=actor,
            notes=notes,
        )
        return self._draft


class AxisReviewDialog(QDialog):
    """One table of axis positions. No wizard: a reviewer sees every position at once."""

    def __init__(self, model: AxisReviewModel, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("Review axis selectors")
        self._model = model
        self.table = QTableWidget(0, len(_HEADINGS), self)
        self.table.setHorizontalHeaderLabels([heading for heading in _HEADINGS])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        rows = self._model.rows()
        self.table.setRowCount(len(rows))
        for position, row in enumerate(rows):
            proposed = "" if row.proposed is None else row.proposed.selector_kind
            for column, text in enumerate(
                (row.grid_id, row.axis, str(row.index), proposed, row.status)
            ):
                self.table.setItem(position, column, QTableWidgetItem(text))
```

Editing a selector's fields in place is the next increment; for this task the dialog displays
every position and its status, and `AxisReviewModel.confirm` is the seam the editing UI will
call. Do not add an editing widget that is not tested.

- [ ] **Step 4: Wire the Rules Manager button**

In `src/insulation_coordination/ui/rules_manager.py`, beside `_review_curves_button`, add a
`"Review axis selectors…"` button whose handler opens `AxisReviewDialog(AxisReviewModel(draft))`
for the currently selected draft and, on close, stores the model's draft back exactly as the
curve-review handler does. Follow `_on_review_curves_clicked`'s structure; enable the button
under the same condition that enables the curve-review button.

- [ ] **Step 5: Run to verify passing**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; $env:QT_QPA_PLATFORM = "offscreen"; uv run pytest tests/ui/test_axis_review.py -q
```

Expected: 4 passed.

- [ ] **Step 6: Gates and commit**

Run ruff, bare mypy, then the UI suite:

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; $env:QT_QPA_PLATFORM = "offscreen"; uv run pytest tests/ui -q
```

Commit message:

```text
feat(ui): review axis selectors from the Rules Manager (#53)

Axis review is an approval gate, so the surface for recording it ships with the
gate. One dialog lists every axis position with its proposal and status; the
model delegates each decision to review_axis_selector, so Qt holds no review
logic.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 8: Importer version, private tests, gates and the PR

**Files:**
- Modify: `src/insulation_coordination/domain/rules.py:17`
- Modify: `tests/private/test_iec62477_dvc_tables.py`
- Test: whichever private module already covers the DVC tables; add the targeted chain there

**Interfaces:**
- Consumes: every earlier task.
- Produces: `IEC_IMPORTER_VERSION = "iec-pdf-5"`, the private targeted tests, and PR.

- [ ] **Step 1: Bump the importer version**

In `src/insulation_coordination/domain/rules.py:17`:

```python
IEC_IMPORTER_VERSION = "iec-pdf-5"
```

Rule identifiers do not change in this slice, so without the bump `validation.py:463` would keep
accepting a package built against the positional contract and serving it as current. The bump
makes the package advertise which importer contract it belongs to.

- [ ] **Step 2: Run the suite and fix whatever pinned the old version**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; $env:QT_QPA_PLATFORM = "offscreen"; uv run pytest -n auto -q
```

Expected: failures only where a test hard-codes `iec-pdf-4`. Update each to the constant or to
`iec-pdf-5`, whichever the surrounding test does for other version-sensitive values. Do not
weaken an assertion that a stale importer version is rejected — that behaviour is the point.

- [ ] **Step 3: Add the private targeted tests**

In `tests/private/test_iec62477_dvc_tables.py`, add tests that prove the whole chain on the
licensed documents, structurally only:

```python
def test_the_licensed_tables_propose_every_axis_position(extracted_draft) -> None:
    """Real extraction must enumerate all eighteen positions across both DVC tables."""

    proposals = extracted_draft.axis_selector_proposals
    by_grid: dict[str, int] = {}
    for item in proposals:
        by_grid[item.grid_id] = by_grid.get(item.grid_id, 0) + 1

    assert by_grid[f"raw-{ids.DVC_VOLTAGE_LIMITS}"] == 9
    assert by_grid[f"raw-{ids.DVC_PROTECTION_MATRIX}"] == 9


def test_the_protection_matrix_columns_await_the_reviewer(extracted_draft) -> None:
    """That axis has no public grammar, so the licensed run proposes nothing for it."""

    columns = [
        item
        for item in extracted_draft.axis_selector_proposals
        if item.grid_id == f"raw-{ids.DVC_PROTECTION_MATRIX}" and item.axis == "column"
    ]

    assert len(columns) == 6
    assert all(item.selector is None for item in columns)


def test_an_unreviewed_axis_blocks_approval_of_the_licensed_draft(extracted_draft) -> None:
    codes = {item.code for item in approval_blockers(extracted_draft)}

    assert "AXIS_SELECTOR_REVIEW_REQUIRED" in codes


def test_reviewed_licensed_tables_project_semantic_selectors_only(extracted_draft) -> None:
    """The full chain: licensed extraction, reviewed axes, semantic projection."""

    draft = extracted_draft
    for proposal in draft.axis_selector_proposals:
        selector = proposal.selector or _reviewer_supplied_selector(proposal)
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=selector,
            actor="private test",
            notes="structural review for the targeted chain",
        )
    projected = project_reviewed_rules(draft)

    for rule in projected.decisions:
        if rule.id.startswith(ids.DVC_VOLTAGE_LIMITS) or rule.id == ids.DVC_PROTECTION_MATRIX:
            for declared in rule.inputs:
                for value in declared.allowed_values:
                    assert not re.fullmatch(
                        r"dvc-\d+|voltage-quantity-\d+|protection-context-\d+", value
                    )
```

`_reviewer_supplied_selector(proposal)` returns the appropriate member of the published
inventories for a proposal with no reading; for the protection-matrix columns it hands out the
six selectors in a fixed order. `project_reviewed_rules` is whatever the module already calls to
project a reviewed draft — read the file's existing imports rather than guessing the name. Keep
every assertion structural: no numeric value, no heading, no source wording.

- [ ] **Step 4: Run the private suite**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest -m private_standard -q
```

Expected on a machine without the PDFs: all skipped, zero collection errors. Record the count.
Do not describe this as the private suite passing.

- [ ] **Step 5: Full gates**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run ruff check .
```

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run mypy
```

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; $env:QT_QPA_PLATFORM = "offscreen"; uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing -q
```

Expected: ruff clean, mypy clean, 0 failed, and a "Required test coverage of 80.0% reached" line.
Record the passed and skipped counts and the total coverage.

- [ ] **Step 6: Audit the whole diff for licensed content**

```bash
git diff origin/main --unified=0
```

Read every added line. Confirm it carries only semantic identifiers, neutral tokens, structural
indexes, locators, issue numbers and counts. Confirm no source wording, no heading, no numeric
source content, no physical row or column ordering, and no pairing of a physical position to a
selector appears anywhere — including in the synthetic test fixtures, which must use invented
header text. A public push is not reversible; fix anything questionable before pushing.

- [ ] **Step 7: Commit, push and open the PR**

Commit the version bump and private tests:

```text
feat(rules): reject packages built against the positional DVC contract (#53)

Rule identifiers do not change in this slice, so a package built before it
would otherwise stay valid and keep serving dvc-N and protection-context-N as
though current. Bumping IEC_IMPORTER_VERSION makes the package advertise which
importer contract it belongs to; a stale package is rebuilt, its eighteen axis
selectors confirmed, and its changed Table 2 and Table 3 proposals reviewed.

Adds the targeted private tests for the licensed chain: real extraction
proposes every axis position, the protection-matrix columns await the reviewer,
an unreviewed axis blocks approval, and a reviewed draft projects semantic
selectors only.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

Then push and open the PR with `gh pr create --base main --body-file <path>`, whose body must
carry, in order: `Refs #53` (not `Closes`, because #53 also covers #53B and #53C); what changed;
the contract impact including the importer bump and the rebuild-and-reconfirm lifecycle; the
review-state consequence; the gate results with real numbers; a clearly headed section stating
that the private suite has **not** run and that the PR must not merge until it has, with the
command
`$env:ICC_PRIVATE_STANDARDS_DIR = "<directory holding the licensed PDFs>"; uv run pytest -m private_standard -q`
and the note that the maintainer has previously reduced this gate to the tests covering the
change; the PR #55 handoff; and what is out of scope.

---

## Self-Review

**Spec coverage.** Vocabularies → Task 1. Grammar and the reviewer-supplied asymmetry → Task 2.
Proposal/review authority and the blocker → Task 3. Resolver, refusals and the projector
interface → Task 4. Table 2's emitted contract → Task 5. Table 3's → Task 6. The review surface →
Task 7. Importer version, private chain and the audit → Task 8. Item 2 needs no task, as the spec
records. The non-contractual-identifier rule is enforced by tests in Tasks 5, 6 and 8. The
reordering guard is in Tasks 5 and 6. The evaluator-contract tests are in Task 5, with Table 3's
`not_applicable` case in Task 6.

**Placeholders.** Every code step carries real code. Four steps deliberately send the implementer
to read an existing definition rather than quoting it — `record_correction`'s argument shape,
`_ProtectionCell`'s index attributes, the minimal draft helper in `tests/rules/importer`, and
`project_reviewed_rules`'s real name — because quoting a signature I have not verified would be
worse than naming exactly what to look at.

**Type consistency.** `ConfirmedAxes.row()` / `.column()`, `selector_sha256`,
`propose_axis_selectors(spec, grid)`, `resolve_confirmed_axis_selectors(spec, grid, draft)`,
`review_axis_selector(draft, *, grid_id, axis, index, selector, actor, notes)` and
`projector(grid, identity, confirmed_axes)` are spelled identically in every task. Selector field
names match the models in Task 1 throughout Tasks 5 and 6.
