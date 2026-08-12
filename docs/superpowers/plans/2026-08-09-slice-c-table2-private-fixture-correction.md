# Slice C Table 2 Private-Fixture Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the IEC 62477-1:2022 Table 2 structural recipe and semantic projection so the licensed private fixture extracts without guessing and resolves its curve and Table 7 impulse references exactly.

**Architecture:** Keep the generic strict extraction boundary. Describe the verified 8×6 physical grid through recipe-declared headers, a 4×5 semantic body, merged data cells, and two neutral reference anchors. Project numeric, curve-reference, impulse-reference, and not-applicable outcomes into separate typed decisions so one merged Table 7 cell can expose exact AC/DC targets without assigning supply type to DVC rows.

**Tech Stack:** Python 3.12, Pydantic frozen models, `Decimal`, pytest, Ruff, mypy, private licensed-PDF tests.

## Global Constraints

- Never commit or print IEC text, extracted values, screenshots, PDFs, `.icrules`, or private audit output.
- Public tests use neutral synthetic cells only; private tests assert structural identities, hashes, and statuses.
- Unsupported or undeclared cells remain blocking; do not relax strict extraction validation.
- Preserve source document, page, table, physical row/column, and merged-anchor provenance.
- Run private tests with `ICC_PRIVATE_STANDARDS_DIR=/Users/fabiocposser/Documents/github/insulation-coordination-calculator/standards` from the feature worktree.
- Maintain branch-aware coverage at or above 80%.

---

### Task 1: Correct Table 2 structure and merged-data inheritance

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/importer/identify.py`
- Modify: `tests/rules/importer/iec62477_2022/test_table2_extraction.py`

**Interfaces:**
- Consumes: `TableAuditSpec`, `MergedCellSpec`, `BlankCellSpec`, `ReferenceSlotSpec`, `RawGrid`, `apply_table_structure(grid, spec)`.
- Produces: corrected `TABLE_2`; merged data cells whose logical coordinates remain distinct while values/reference tokens and source spans come from their declared anchor.

- [ ] **Step 1: Rewrite the synthetic Table 2 fixture and add failing structural assertions**

Build neutral cells with data rows `range(3, 7)` and columns `range(1, 6)`. Declare synthetic merged blanks at `(4, 4)`, `(4, 5)`, `(5, 5)`, and `(6, 4)`, not-applicable `(6, 5)`, and structural footnote continuations `(7, 1)` through `(7, 5)`. Assert:

```python
assert (TABLE_2.data_row_start, TABLE_2.data_column_start) == (3, 1)
assert (TABLE_2.expected_data_rows, TABLE_2.expected_data_columns) == (4, 5)
assert {(slot.row, slot.column) for slot in TABLE_2.reference_slots} == {(3, 5), (5, 4)}

structured = apply_table_structure(_grid(), TABLE_2)
cells = {(cell.row, cell.column): cell for cell in structured.cells}
assert cells[(4, 5)].reference_token == cells[(3, 5)].reference_token
assert cells[(5, 5)].reference_token == cells[(3, 5)].reference_token
assert cells[(6, 4)].reference_token == cells[(5, 4)].reference_token
assert cells[(4, 4)].value == cells[(3, 4)].value
assert (cells[(4, 4)].logical_row, cells[(4, 4)].logical_column) != (
    cells[(3, 4)].logical_row,
    cells[(3, 4)].logical_column,
)
```

- [ ] **Step 2: Run the structural tests and verify RED**

Run:

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_table2_extraction.py -q
```

Expected: failures show the old `(2, 2)` semantic origin, old reference coordinates, and rejection of declared blank data cells during merge expansion.

- [ ] **Step 3: Implement the verified structural recipe**

Set:

```python
data_row_start = 3
data_column_start = 1
expected_data_rows = 4
expected_data_columns = 5
```

Declare these merges:

```python
MergedCellSpec(row=0, column=0, row_span=3, inherit="down")
MergedCellSpec(row=0, column=1, column_span=5, inherit="right")
MergedCellSpec(row=1, column=1, column_span=4, inherit="right")
MergedCellSpec(row=3, column=4, row_span=2, inherit="down")
MergedCellSpec(row=3, column=5, row_span=3, inherit="down")
MergedCellSpec(row=5, column=4, row_span=2, inherit="down")
```

Declare every covered empty coordinate as `BlankCellSpec(..., semantics="inherit")`, and `(6, 5)` as `not_applicable`. Use one curve slot at `(3, 5)` targeting `DVC_FAULT_TIME_VOLTAGE`, and one Table 7 family slot at `(5, 4)` targeting `SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC`.

Extend `BlankCellSemantics` with `"structural"` and declare footnote-row continuation cells `(7, 1)` through `(7, 5)` with that meaning. They must remain physically empty and are never projected as outcomes.

In `apply_table_structure`, accept a covered cell when it is blank, marked `inherit`, and has role `blank` or `data`:

```python
if (
    cell.role not in {"blank", "data"}
    or cell.parse_status != "blank"
    or cell.blank_semantics != "inherit"
):
    raise ExtractionError(...)
```

Keep the covered cell's logical row and column, but copy the anchor's reviewed scalar/reference fields and anchor source.

- [ ] **Step 4: Run structural and neighboring extraction tests**

Run:

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_table2_extraction.py tests/rules/test_compound_cells.py tests/rules/test_importer.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/insulation_coordination/rules/importer/extract.py src/insulation_coordination/rules/importer/identify.py src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py tests/rules/importer/iec62477_2022/test_table2_extraction.py docs/superpowers/specs/2026-08-08-iec62477-slice-c-dvc-and-curves-design.md docs/superpowers/plans/2026-08-09-slice-c-table2-private-fixture-correction.md
git commit -m "fix(importer): match IEC Table 2 structure"
```

---

### Task 2: Project five quantities and exact curve/impulse references

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/projection.py`
- Modify: `tests/rules/importer/iec62477_2022/test_table2_projection.py`
- Modify: `tests/private/test_iec62477_slice_c_roundtrip.py`

**Interfaces:**
- Consumes: corrected structured `RawGrid`; `SemanticReferenceToken`; Table 7 `.ac`/`.dc` semantic table IDs.
- Produces: `project_dvc_voltage_limits(...)` returning numeric/not-applicable decisions plus `iec62477_2022.dvc.voltage_limits.fault_time_reference` and `.impulse_reference` decisions and proposals.

- [ ] **Step 1: Write failing projection tests for the corrected semantic shape**

Assert the numeric decision has only `dvc`, `voltage_quantity`, and `unit` inputs and exposes five distinct quantity selectors. Assert no matcher uses `conditional_alternative` or synthetic operating-condition rows.

Assert the curve-reference rule has one reference output whose rows all target:

```python
ids.DVC_FAULT_TIME_VOLTAGE
```

Assert the impulse-reference rule has two outputs and each row contains exactly:

```python
{
    f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac",
    f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc",
}
```

Assert every decision reference resolves to one synthetic final target by ID.

- [ ] **Step 2: Run the projection tests and verify RED**

Run:

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_table2_projection.py -q
```

Expected: failures show the old row/column loops, paired quantity mapping, boolean alternative input, combined reference rule, and TOV targets.

- [ ] **Step 3: Implement minimal corrected projection**

Iterate body coordinates with:

```python
for row in range(TABLE_2.data_row_start, TABLE_2.data_row_start + TABLE_2.expected_data_rows):
    for column in range(
        TABLE_2.data_column_start,
        TABLE_2.data_column_start + TABLE_2.expected_data_columns,
    ):
```

Map `dvc` directly from physical body row and `voltage_quantity` directly from physical body column. Remove `operating_condition` and `conditional_alternative` from Table 2 decision inputs and matchers.

Split reference outcomes by target family:

```python
curve_outcomes = tuple(item for item in outcomes if item.value == ids.DVC_FAULT_TIME_VOLTAGE)
impulse_outcomes = tuple(
    item for item in outcomes if item.value == ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC
)
```

Build the curve rule with one `DecisionOutput(name="fault_time_voltage", kind="reference")`. Build the impulse rule with `DecisionOutput(name="ac_reference", kind="reference")` and `DecisionOutput(name="dc_reference", kind="reference")`; each row emits the exact `.ac` and `.dc` table IDs. Preserve each outcome's source reference.

- [ ] **Step 4: Update private structural reference assertions**

In `test_iec62477_slice_c_roundtrip.py`, replace TOV targets with impulse targets and continue asserting each resolves exactly once across final tables, formulas, decisions, procedures, guidance, and curves. Compare only IDs and canonical hashes.

- [ ] **Step 5: Run public projection, integration, validation, and archive tests**

Run:

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_table2_projection.py tests/rules/importer/iec62477_2022/test_slice_c_integration.py tests/rules/test_audit.py tests/rules/test_archive.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/projection.py tests/rules/importer/iec62477_2022/test_table2_projection.py tests/private/test_iec62477_slice_c_roundtrip.py
git commit -m "fix(importer): project verified Table 2 references"
```

---

### Task 3: Prove licensed extraction and finish branch publication

**Files:**
- Modify only if a test exposes a root-cause defect in the files owned by Tasks 1-2.

**Interfaces:**
- Consumes: corrected recipe/projection and maintainer-supplied standards.
- Produces: green private/full gates, reviewed commits, local-main fast-forward, pushed feature branch, and draft PR with `Refs #34`.

- [ ] **Step 1: Run the focused licensed fixture tests**

Run:

```bash
ICC_PRIVATE_STANDARDS_DIR=/Users/fabiocposser/Documents/github/insulation-coordination-calculator/standards \
uv run pytest -m private_standard \
  tests/private/test_iec62477_numeric_tables.py \
  tests/private/test_iec62477_dvc_tables.py \
  tests/private/test_iec62477_curves.py \
  tests/private/test_iec62477_slice_c_roundtrip.py -q
```

Expected: PASS without printing extracted text, values, coordinates, crops, or package bytes.

- [ ] **Step 2: Run the complete gates**

```bash
uv run ruff check .
uv run mypy
QT_QPA_PLATFORM=offscreen ICC_PRIVATE_STANDARDS_DIR=/Users/fabiocposser/Documents/github/insulation-coordination-calculator/standards \
uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing --cov-fail-under=80
git diff --check origin/main...HEAD
! git diff --name-only origin/main...HEAD | rg '\.(pdf|png|jpg|jpeg|tif|tiff|icrules)$'
```

Expected: all checks exit 0 and total branch-aware coverage is at least 80%.

- [ ] **Step 3: Request independent spec, safety, and privacy reviews**

Reviewers inspect the corrected source structure, semantic target selection, approval/reference resolution, private-test output safety, and complete diff. Address every actionable finding and repeat Step 2.

- [ ] **Step 4: Fast-forward local main and verify the merged tree**

```bash
git -C /Users/fabiocposser/Documents/github/insulation-coordination-calculator merge --ff-only codex/issue-34-slice-c
```

Run the complete gates once more from the main checkout.

- [ ] **Step 5: Push and open the draft PR**

```bash
git push -u origin codex/issue-34-slice-c
```

Create a draft PR targeting `main`. The body summarizes the corrected Table 2 source model, all Slice C work, verification, private-fixture status, and explicitly says `Refs #34` rather than closing the issue.
