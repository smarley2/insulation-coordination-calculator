# Raw PDF Grid Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require visible, explicit review of extracted IEC table cells before Rules Manager builds and approves typed rule content.

**Architecture:** Add one domain operation that safely corrects or accepts flagged cells in an immutable raw grid and records their resolutions. Add a focused Qt grid-review dialog, then wire it into Rules Manager so raw review, typed-content construction, formula confirmation, and approval are distinct gated stages.

**Tech Stack:** Python 3.12, Pydantic frozen models, PySide6 widgets, pytest, pytest-qt.

## Global Constraints

- Keep licensed PDFs, extracted values, `.icrules`, and `.icproj` files local and uncommitted.
- Preserve extracted `raw_text`, coordinates, and `SourceReference` during corrections.
- No new dependency and no embedded PDF viewer.
- No raw review resolution without explicit `Accept table` action.
- Use immutable model copies and preserve the correction digest chain.

---

### Task 1: Audited Raw-Grid Acceptance

**Files:**
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Modify: `src/insulation_coordination/rules/importer/review.py`
- Modify: `src/insulation_coordination/rules/importer/__init__.py`
- Test: `tests/rules/test_importer.py`

**Interfaces:**
- Consumes: `ImportedRuleDraft`, `RawGrid`, `RawGridCell`, `record_correction(...)`.
- Produces: `unresolved_raw_review_items(draft) -> tuple[ImportReviewItem, ...]` and `accept_raw_grid(draft, *, grid_id: str, corrections: Mapping[tuple[int, int], Decimal], actor: str, notes: str) -> ImportedRuleDraft`.

- [ ] **Step 1: Write failing tests for scoped raw-grid acceptance**

```python
def test_accept_raw_grid_resolves_only_selected_grid_and_preserves_raw_text(
    supported_pdfs, injected_recipes
) -> None:
    draft = extract_draft(supported_pdfs)
    grid = draft.raw_grids[0]
    flagged = tuple(
        item for item in draft.review_items
        if item.kind == "raw_cell" and item.semantic_id.startswith(f"{grid.id}:")
    )

    accepted = accept_raw_grid(
        draft,
        grid_id=grid.id,
        corrections={},
        actor="Maintainer",
        notes="Compared against PDF",
    )

    resolved = {item.review_item_sha256 for item in accepted.review_resolutions}
    assert resolved == {item.sha256 for item in flagged}
    assert tuple(cell.raw_text for cell in accepted.raw_grids[0].cells) == tuple(
        cell.raw_text for cell in grid.cells
    )
    assert all(
        cell.parse_status == "numeric"
        for cell in accepted.raw_grids[0].cells
        if f"{grid.id}:{cell.row}:{cell.column}" in {item.semantic_id for item in flagged}
    )
```

Add separate tests proving one supplied correction changes only `value`, rejects
unknown coordinates, rejects `Decimal("NaN")`, and rejects accepting an already
resolved grid.

- [ ] **Step 2: Run the new domain tests and verify RED**

Run: `uv run pytest -q tests/rules/test_importer.py -k 'accept_raw_grid or unresolved_raw'`

Expected: collection/import failure because `accept_raw_grid` and
`unresolved_raw_review_items` do not exist.

- [ ] **Step 3: Permit only safe audited raw-grid corrections**

In `approval.py`, replace the blanket raw-grid inequality rejection with a
validator that requires identical grid IDs, shapes, units, grid sources, cell
coordinates, cell sources, and `raw_text`. Permit changes only to `value`,
`qualifier`, `suffix`, and `parse_status`. Extend `_changed_tokens` with one
`raw-grid:<id>` token for each changed grid. Require a resolved raw cell to have
`value is not None` and `parse_status == "numeric"`.

- [ ] **Step 4: Implement the minimum domain operation**

In `review.py`, locate unresolved `raw_cell` items for `grid_id`. For each
flagged coordinate, use the supplied correction or its existing parsed value;
require a finite decimal, then copy the cell with `parse_status="numeric"` and
cleared qualifier/suffix. Copy the grid and draft, then call `record_correction`
with only those items. Export both helpers from the importer package.

- [ ] **Step 5: Run domain tests and verify GREEN**

Run: `uv run pytest -q tests/rules/test_importer.py -k 'accept_raw_grid or unresolved_raw or correction'`

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/insulation_coordination/rules/importer tests/rules/test_importer.py
git commit -m "feat: add audited raw grid acceptance"
```

---

### Task 2: Gate Typed-Content Construction on Raw Review

**Files:**
- Modify: `src/insulation_coordination/rules/importer/review.py`
- Modify: `tests/rules/test_importer.py`
- Modify: `tests/ui/test_rules_manager_review.py`

**Interfaces:**
- Consumes: `unresolved_raw_review_items(...)`, `accept_raw_grid(...)`.
- Produces: `build_reviewed_draft(...)` that rejects pending raw reviews and resolves definition items only.

- [ ] **Step 1: Replace obsolete auto-resolution test with failing gate test**

```python
def test_build_reviewed_draft_requires_raw_grid_acceptance(
    supported_pdfs, injected_recipes
) -> None:
    draft = extract_draft(supported_pdfs)
    with pytest.raises(ValueError, match="review extracted table cells first"):
        build_reviewed_draft(draft, actor="Maintainer", notes="Build rules")
```

Add a happy-path test that accepts every grid, builds content, asserts all
required content is present, and asserts only placeholder-formula items remain
unresolved.

- [ ] **Step 2: Run gate tests and verify RED**

Run: `uv run pytest -q tests/rules/test_importer.py -k 'build_reviewed_draft'`

Expected: the new rejection assertion fails because build currently resolves
raw items automatically.

- [ ] **Step 3: Implement the build gate and narrower resolution set**

At function entry, raise `ValueError("Review extracted table cells first.")`
when `unresolved_raw_review_items(draft)` is non-empty. Build typed content as
today. Resolve table/formula/mapping definition items except placeholder
formulas; never include `raw_cell` items in this resolution tuple.

- [ ] **Step 4: Update existing synthetic workflow tests**

Add a test helper that calls `accept_raw_grid` once per grid before
`build_reviewed_draft`. Keep assertions based on visible outcomes: required
content, unresolved placeholder formulas, and approval gating.

- [ ] **Step 5: Run importer and Rules Manager tests and verify GREEN**

Run: `uv run pytest -q tests/rules/test_importer.py tests/ui/test_rules_manager_review.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/insulation_coordination/rules/importer/review.py tests/rules/test_importer.py tests/ui/test_rules_manager_review.py
git commit -m "fix: require raw cell review before rule build"
```

---

### Task 3: Extracted-Table Review Dialog

**Files:**
- Create: `src/insulation_coordination/ui/raw_grid_review.py`
- Create: `tests/ui/test_raw_grid_review.py`

**Interfaces:**
- Consumes: `ImportedRuleDraft`, `accept_raw_grid(...)`, `unresolved_raw_review_items(...)`.
- Produces: `RawGridReviewDialog(draft, *, actor: str, notes: str)`, `reviewed_draft` property, and `draft_changed = Signal(object)`.

- [ ] **Step 1: Write failing Qt test for visible full grid**

```python
def test_dialog_shows_complete_grid_and_flags_review_cells(qtbot, draft) -> None:
    dialog = RawGridReviewDialog(
        draft, actor="Maintainer", notes="Compared against PDF"
    )
    qtbot.addWidget(dialog)
    grid = draft.raw_grids[0]

    assert dialog.grid_count == len(draft.raw_grids)
    assert dialog.row_count == grid.rows
    assert dialog.column_count == grid.columns
    assert dialog.pending_cell_count > 0
```

Add tests that select a flagged cell, apply a literal decimal correction,
accept the table, and assert `reviewed_draft` changed; add invalid/empty input
tests asserting acceptance stays blocked.

- [ ] **Step 2: Run dialog tests and verify RED**

Run: `uv run pytest -q tests/ui/test_raw_grid_review.py`

Expected: collection failure because the dialog module does not exist.

- [ ] **Step 3: Implement minimal dialog layout**

Use `QComboBox`, `QTableWidget`, `QLabel`, `QLineEdit`, and three buttons.
Populate every grid cell with `raw_text`; store `(row, column)` in item data.
Use a warning background and tooltip for unresolved flagged cells. Non-flagged
cells are read-only. Selection updates source/status details and editor state.

- [ ] **Step 4: Implement edit and accept actions**

Keep pending edits in a `dict[(row, column), Decimal]`. `Apply value` validates
one finite decimal and updates display without resolving anything. `Accept
table` calls `accept_raw_grid`, updates `reviewed_draft`, emits `draft_changed`,
refreshes progress, and disables itself for an already accepted table.

- [ ] **Step 5: Run dialog tests and verify GREEN**

Run: `uv run pytest -q tests/ui/test_raw_grid_review.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/insulation_coordination/ui/raw_grid_review.py tests/ui/test_raw_grid_review.py
git commit -m "feat: add extracted IEC grid review dialog"
```

---

### Task 4: Rules Manager Wiring and Safe Formula Entry

**Files:**
- Modify: `src/insulation_coordination/ui/rules_manager.py`
- Modify: `tests/ui/test_rules_manager_review.py`

**Interfaces:**
- Consumes: `RawGridReviewDialog`, unresolved raw-review count, placeholder literal counts.
- Produces: staged button enablement and formula fields with no placeholder defaults.

- [ ] **Step 1: Write failing Rules Manager workflow tests**

Add tests proving:

```python
assert rules_manager.review_tables_enabled is True
assert rules_manager.build_review_enabled is False
```

for a fresh draft; after all grids are accepted, reverse those states. After
build, assert `57/57` equivalent required-content state and only placeholder
formulas remain. Assert `FormulaConstantDialog` fields are empty and reject the
wrong literal count.

- [ ] **Step 2: Run Rules Manager tests and verify RED**

Run: `uv run pytest -q tests/ui/test_rules_manager_review.py`

Expected: missing properties/button and prefilled formula fields fail.

- [ ] **Step 3: Wire the grid-review action**

Add `Review extracted tables…` above `Build reviewed content…`. Require notes
before opening. On each `draft_changed`, call `set_draft`. Enable review while
raw items remain; enable build only when no raw items remain and typed required
content is missing. Keep formula review and approval gated by existing domain
state.

- [ ] **Step 4: Fix progress copy and formula validation**

Replace `Reviewed {self.review_count} items` with actual resolved/remaining
counts. Initialize formula edits with `""`, show expected literal count in the
label/placeholder, reject empty tokens, non-finite decimals, and counts unequal
to the current expression's literal count.

- [ ] **Step 5: Run focused UI tests and verify GREEN**

Run: `uv run pytest -q tests/ui/test_raw_grid_review.py tests/ui/test_rules_manager_review.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/insulation_coordination/ui/rules_manager.py tests/ui
git commit -m "fix: expose safe staged IEC review workflow"
```

---

### Task 5: Full Verification and Manual GUI Check

**Files:**
- Modify only if verification reveals a defect covered by a new failing test.

**Interfaces:**
- Consumes: completed workflow.
- Produces: fresh automated and manual evidence.

- [ ] **Step 1: Run formatting and static checks**

Run: `uv run ruff check . && uv run ruff format --check .`

Expected: exit 0 with no violations.

- [ ] **Step 2: Run full automated suite**

Run: `uv run pytest -q`

Expected: zero failures; private-standard tests may skip when their explicit
opt-in condition is absent.

- [ ] **Step 3: Launch and inspect real-PDF workflow**

Run: `uv run icc --gui`. Import both files in `standards/`. Verify six grids are
selectable, all 57 ambiguous cells require explicit table acceptance, build is
blocked before acceptance, formula fields start empty, and approval remains
blocked until all four formula definitions are entered.

- [ ] **Step 4: Check repository state**

Run: `git status --short && git log -5 --oneline`

Expected: only intentional commits and no licensed/generated artifacts staged.
