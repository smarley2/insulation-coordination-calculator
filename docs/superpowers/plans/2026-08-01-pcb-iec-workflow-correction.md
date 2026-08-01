# PCB IEC Workflow Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic PDF-number workflow with reviewed semantic IEC rules and calculate PCB clearance and creepage per net-class pair using IEC 60664-1 Annex G/H plus the applicable IEC 60664-4 high-frequency branches.

**Architecture:** Keep the existing manual per-pair stress boundary. Extract only the approved source inventory into semantic raw tables/equations, review those artifacts before projection, then build typed sparse tables and explicit route mappings. The calculation engine evaluates Part 1 candidates first, performs a pair-specific critical-frequency check above 30 kHz, applies the bounded Part 4 second pass when required, and emits a complete trace.

**Tech Stack:** Python 3.12, Pydantic frozen models, Decimal arithmetic, pdfplumber, PySide6, pytest, pytest-qt.

**Approved specification:** [`docs/superpowers/specs/2026-08-01-pcb-iec-workflow-correction-design.md`](../specs/2026-08-01-pcb-iec-workflow-correction-design.md)

## Global Constraints

- Work on `main`, as requested. Make one focused commit after each task.
- Use test-driven development: add one failing behavior test, run it and observe RED, implement the minimum change, then run the focused suite and observe GREEN.
- Do not commit licensed PDFs, extracted IEC values, generated `.icrules`, or `.icproj` files.
- Retain manual pair inputs for required impulse, long-term RMS, steady-state peak, temporary-overvoltage peak, and recurring peak voltage.
- Import only IEC 60664-1 F.2, F.5 (both pages), F.8, F.9, A.2 and IEC 60664-4 Tables 1/2 plus Equations (1)/(2), the minimum-frequency statement, and radius criterion.
- Do not import F.1, F.3, F.4, or Part 4 Table 5 as calculation assets.
- Never infer a lookup from display text. Use stable semantic row/column IDs and reviewed selection policies.
- Never collapse multiline alternatives, ranges, blanks, notes, or footnotes into a first-number scalar.
- Never interpolate unless the reviewed source contract explicitly permits it.
- Block unsupported PCB conditions and missing table combinations; do not substitute a neighboring cell or material branch.
- Recalculate critical frequency per pair and per clearance pass. There are at most the initial pass and the source-described second pass; no tolerance or iteration-limit constants.
- Bump rule schema and importer versions. Reject packages built by the superseded `raw_sequence` importer.
- Every result must be traceable to table/equation, logical row/column, source page, and calculation function.

---

### Task 1: Add Semantic Sparse Table Selection

**Files:**
- Modify: `src/insulation_coordination/domain/rules.py`
- Modify: `src/insulation_coordination/rules/evaluator.py`
- Modify: `src/insulation_coordination/rules/validation.py`
- Modify: `src/insulation_coordination/rules/audit.py`
- Modify: `tests/rules/test_evaluator.py`
- Modify: `tests/rules/test_archive.py`
- Modify: `tests/rules/test_audit.py`
- Modify: `tests/fixtures/synthetic_rules.py`

**Interfaces:**
- Add `AxisSelectionMode = Literal["exact", "ceiling", "linear"]`.
- Extend `TableAxis` with `labels: tuple[Identifier, ...]`; require one unique label per numeric coordinate.
- Add discriminated expression `TableSelect(op="table_select", table_id, row, column, row_mode, column_mode)`.
- Permit sparse `Table.cells`; require unique, in-bounds coordinates instead of a complete rectangle.
- Preserve `Lookup` and `LinearInterpolate` only for parsing old schema data; corrected packages and builders must emit `TableSelect`.

- [ ] **Step 1: Write failing evaluator tests**

Add small synthetic tables proving exact selection, conservative ceiling selection, row-only interpolation, column-only interpolation, and two-axis selection. Assert missing sparse coordinates and out-of-range values raise `EvaluationError`.

```python
expression = TableSelect(
    table_id="example",
    row=Variable(name="stress_v"),
    column=Variable(name="pollution_code"),
    row_mode="ceiling",
    column_mode="exact",
)
evaluated = evaluate_expression(expression, variables, {table.id: table})
assert evaluated.value == Decimal("1.5")
assert evaluated.steps[-1].source_reference == expected_cell.source
```

Also assert a linear selection trace names both bracketing cells and their source references.

- [ ] **Step 2: Run the evaluator tests and verify RED**

Run: `uv run pytest -q tests/rules/test_evaluator.py -k 'table_select or sparse or axis_labels'`

Expected: collection/model failure because semantic labels and `TableSelect` do not exist.

- [ ] **Step 3: Implement the minimum table model and evaluator**

Validate strictly increasing numeric axis values, equal label/value lengths, unique labels, unique cell coordinates, and in-bounds cells. In the evaluator, resolve each axis independently by its declared mode, form the one/two/four contributing coordinates, reject any missing contributing coordinate, compute Decimal interpolation, apply declared rounding, and emit trace steps containing semantic axis labels and every contributing `SourceReference`.

- [ ] **Step 4: Update validation, audit traversal, and fixtures**

Teach expression traversal and referenced-table validation about `TableSelect`. Replace complete-rectangle validation with sparse-coordinate validation. Update synthetic rule builders to supply labels and use `TableSelect`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `uv run pytest -q tests/rules/test_evaluator.py tests/rules/test_archive.py tests/rules/test_audit.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/insulation_coordination/domain/rules.py src/insulation_coordination/rules/evaluator.py src/insulation_coordination/rules/validation.py src/insulation_coordination/rules/audit.py tests/rules tests/fixtures/synthetic_rules.py
git commit -m "feat: add semantic sparse table selection"
```

---

### Task 2: Model Semantic Raw Tables and Equations

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Modify: `src/insulation_coordination/rules/importer/__init__.py`
- Modify: `tests/rules/test_importer.py`

**Interfaces:**
- Replace the one-page scalar assumptions with `TableSegmentSpec`, `TableColumnSpec`, and `EquationAuditSpec`.
- Add `RawGridSegment(page_number, row_start, row_count, source)`.
- Extend `RawGridCell` with `role`, `logical_row`, `logical_column`, `footnotes`, and an optional scalar `value` only for semantic data cells.
- Add `ExtractedEquation(id, rendered, variables, literals, unit, applicability, source, parse_status)` to `ImportedRuleDraft`.
- Include segments, roles, logical coordinates, footnotes, and equations in content digests and immutable correction checks.

- [ ] **Step 1: Write failing raw-model/parser tests**

Use synthetic PDF cell text to prove:

```python
assert parse_data_cell("1 000 d").value == Decimal("1000")
assert parse_data_cell("1 000 d").footnotes == ("d",)
assert parse_data_cell("110\n120\n127").parse_status == "non_scalar"
assert parse_data_cell("30 to 60").parse_status == "range"
```

Assert header, blank, note, and footnote cells are preserved verbatim and are never manual numeric-review items. Assert changing extracted source text, role, logical coordinate, segment, or equation source is rejected by `record_correction`.

- [ ] **Step 2: Run importer model tests and verify RED**

Run: `uv run pytest -q tests/rules/test_importer.py -k 'semantic_cell or grouped_thousands or raw_segment or extracted_equation'`

Expected: missing models/fields and incorrect generic scalar parsing.

- [ ] **Step 3: Implement role-aware extraction models**

Separate exact `raw_text` from normalized scalar data. Normalize decimal comma and grouped thousands only for recipe-declared data cells. Split only recipe-approved trailing footnote markers. Represent multiline alternatives and ranges as non-scalar values unless a source-specific projection contract handles them. Preserve every visible cell for review.

- [ ] **Step 4: Extend draft digest and safe corrections**

Corrections may change only the normalized scalar value/parse status/footnote metadata of a flagged data cell or the reviewed parsed representation of a flagged equation. They may not change source identity, raw text, semantic role, logical coordinate, page segment, or recipe contract.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `uv run pytest -q tests/rules/test_importer.py -k 'semantic_cell or grouped_thousands or raw_segment or extracted_equation or correction'`

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/insulation_coordination/rules/importer tests/rules/test_importer.py
git commit -m "feat: preserve semantic IEC extraction artifacts"
```

---

### Task 3: Correct the IEC 60664-1 Recipe Inventory

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py`
- Modify: `tests/rules/test_importer.py`
- Modify: `tests/private/test_supplied_standards.py`

**Interfaces:**
- Recipe tables: `iec60664-1-f2`, `iec60664-1-f5`, `iec60664-1-f8`, `iec60664-1-f9`, `iec60664-1-a2`.
- F.5 has two physical `TableSegmentSpec` entries and one logical semantic table.
- F.2 declares merged-cell `fill_down` only for the precise recipe columns/rows where the PDF visually spans rows.
- F.5 exposes all source columns during raw review but marks only PCB columns as calculation projection inputs.
- F.8 and F.9 share a physical page region but project to distinct logical tables.

- [ ] **Step 1: Replace obsolete recipe assertions with failing inventory tests**

Assert the recipe omits F.1/F.3/F.4, includes all five required logical tables, contains both F.5 page segments, contains stable semantic column IDs/headings/units, and has structural contracts for monotonic axes, blanks, notes, and footnotes.

In the private real-PDF test, assert F.5 joins both pages, the last row comes from the continuation page, F.8/F.9 are separated correctly, A.2 is present, and `1 000` plus footnote markers normalize without data loss. Do not assert licensed numeric values in public tests.

- [ ] **Step 2: Run recipe tests and verify RED**

Run: `uv run pytest -q tests/rules/test_importer.py tests/private/test_supplied_standards.py -k 'part1 or f5 or source_inventory'`

Expected: the current F.2/F.3/F.4 inventory and one-page model fail.

- [ ] **Step 3: Implement the Part 1 recipes**

Encode the already-audited PDF anchors and regions as edition-specific layout facts:

- A.2: page 53, one segment, 3 columns;
- F.2: page 70, one segment, 7 columns;
- F.5: pages 73 and 74, 10 columns with compatible headings;
- F.8/F.9: page 76, separate logical projections from the combined region.

Declare page-number conventions in one helper so displayed PDF page and internal pdfplumber index cannot drift. Add structural checks for continuation headings, ordered/non-overlapping voltage axes, required PCB branches, and expected unavailable combinations.

- [ ] **Step 4: Delete F.3/F.4 calculation contracts**

Remove their table/formula/mapping specs rather than retaining dead aliases. Keep no fallback mapping from F.3 to altitude or F.4 to creepage.

- [ ] **Step 5: Run focused and private tests and verify GREEN**

Run: `uv run pytest -q tests/rules/test_importer.py tests/private/test_supplied_standards.py -k 'part1 or f5 or source_inventory'`

Expected: PASS when the local licensed PDFs are available; public importer tests pass independently.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py tests/rules/test_importer.py tests/private/test_supplied_standards.py
git commit -m "fix: import required IEC 60664-1 PCB sources"
```

---

### Task 4: Correct the IEC 60664-4 Recipe and Extract Real Equations

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `tests/rules/test_importer.py`
- Modify: `tests/private/test_supplied_standards.py`

**Interfaces:**
- Recipe tables: `iec60664-4-table-1`, `iec60664-4-table-2`.
- Equation artifacts: `iec60664-4-equation-1-critical-frequency`, `iec60664-4-equation-2-frequency-factor`, `iec60664-4-minimum-frequency`, `iec60664-4-radius-criterion`.
- No Part 4 Table 5 recipe, typed table, formula, or mapping.

- [ ] **Step 1: Write failing Part 4 inventory and equation tests**

Assert only Tables 1/2 are calculation tables. Assert every equation artifact has variables, canonical units, applicability, exact clause/equation/page source, and no placeholder constant. Add private tests that locate Equation (1) from the anchored English text beginning on page 21 and Equation (2) from its continuation on page 23.

- [ ] **Step 2: Run Part 4 tests and verify RED**

Run: `uv run pytest -q tests/rules/test_importer.py tests/private/test_supplied_standards.py -k 'part4 or equation or table_5'`

Expected: current Table 5 use and four fabricated constants fail.

- [ ] **Step 3: Implement Table 1 and Table 2 contracts**

Declare semantic voltage rows, frequency columns, pollution branches/multipliers, sparse unavailable combinations, and source-permitted interpolation directions. Extraction must retain all headings and source coordinates and must fail if the table shape or required semantic branch changes.

- [ ] **Step 4: Implement anchored equation extraction**

Extract the real equation display/text region and normalize variables and units into a canonical parsed representation. Keep source literals in the private draft, not recipe constants. Treat functional applicability as a mapping artifact and the radius test as a reviewed criterion. Delete iteration tolerance/max-iteration formula specs.

- [ ] **Step 5: Run focused and private tests and verify GREEN**

Run: `uv run pytest -q tests/rules/test_importer.py tests/private/test_supplied_standards.py -k 'part4 or equation or table_5'`

Expected: PASS when local standards are present; public tests remain portable.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py src/insulation_coordination/rules/importer/extract.py tests/rules/test_importer.py tests/private/test_supplied_standards.py
git commit -m "fix: import IEC 60664-4 tables and equations"
```

---

### Task 5: Project Accepted Artifacts into Typed Rules

**Files:**
- Create: `src/insulation_coordination/rules/importer/projection.py`
- Modify: `src/insulation_coordination/rules/importer/review.py`
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Modify: `src/insulation_coordination/rules/importer/__init__.py`
- Modify: `tests/rules/test_importer.py`

**Interfaces:**
- Add `unresolved_table_items`, `unresolved_equation_items`, and `unresolved_mapping_items`.
- Add `accept_raw_table(...)` and `accept_equation_mapping(...)`; each requires actor and notes only when acceptance is committed.
- `build_reviewed_draft(...)` performs deterministic projection only after all source artifacts and mappings are explicitly accepted.
- Projection emits labeled sparse `Table`, real `Formula`, and approved-target `CompatibilityMapping` models; it never synthesizes `raw_sequence`.

- [ ] **Step 1: Write failing staged-projection tests**

Assert a fresh draft contains no usable typed rules. Viewing/canceling review changes no digest. Table acceptance resolves only that logical table. Equation/mapping acceptance resolves only the selected artifacts. Build fails while any artifact is pending. After all acceptances, build produces exactly the corrected inventory and every typed cell points to its original raw source cell.

```python
with pytest.raises(ValueError, match="Review equations and mappings first"):
    build_reviewed_draft(tables_accepted, actor="Maintainer", notes="Build")
assert all(not formula_uses_variable(f, "raw_sequence") for f in built.formulas)
```

- [ ] **Step 2: Run projection tests and verify RED**

Run: `uv run pytest -q tests/rules/test_importer.py -k 'projection or staged_review or raw_sequence'`

Expected: current builder auto-generates flattened axes/formulas before semantic review.

- [ ] **Step 3: Implement deterministic table projection**

Join logical segments, apply only declared fill-down behavior, strip reviewed footnote metadata from numeric coordinates, assign stable axis labels, preserve sparse blanks, and enforce monotonicity/coverage/source assertions. F.5 must become one typed table sourced from both pages.

- [ ] **Step 4: Implement equation and mapping projection**

Build the expression tree from the reviewed canonical equation artifact and typed variables/units. Build route mappings from reviewed semantic contracts. Do not use literal placeholders or infer table IDs from strings.

- [ ] **Step 5: Run importer and validation tests and verify GREEN**

Run: `uv run pytest -q tests/rules/test_importer.py tests/rules/test_archive.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/insulation_coordination/rules/importer tests/rules/test_importer.py tests/rules/test_archive.py
git commit -m "feat: project reviewed IEC artifacts into typed rules"
```

---

### Task 6: Fix the Extracted-Table Review UI

**Files:**
- Modify: `src/insulation_coordination/ui/raw_grid_review.py`
- Modify: `src/insulation_coordination/ui/rules_manager.py`
- Modify: `tests/ui/test_raw_grid_review.py`
- Modify: `tests/ui/test_rules_manager_review.py`

**Interfaces:**
- `RawGridReviewDialog` receives the draft and actor, but not mandatory notes at construction.
- It renders one logical table at a time with real headings, segment/page markers, raw text, normalized values, footnotes, roles, and source details.
- Notes are requested and validated only by `Accept table`.
- Progress reports logical tables accepted/pending, not raw-cell plus definition totals.

- [ ] **Step 1: Write failing Qt workflow tests**

Add tests proving `Review extracted tables` opens with an empty notes field; closing/canceling does not change the draft; accepting with empty notes is blocked; accepting with notes records one resolution. Assert headers use recipe headings instead of `Column 1`, multipage F.5 exposes both segments, raw `1 000 d` is visible beside normalized `1000` and marker `d`, and no F.3/F.4/Table 5 appears.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `uv run pytest -q tests/ui/test_raw_grid_review.py tests/ui/test_rules_manager_review.py -k 'notes or headings or multipage or progress'`

Expected: Rules Manager currently blocks opening without notes and the grid uses generic headings.

- [ ] **Step 3: Implement the semantic table view**

Use the logical recipe contract for column headers and fixed row-header labels. Add a compact segment/page indicator and a details panel for raw text, normalized value, footnotes, parse state, and `SourceReference`. Color pending data corrections separately from contextual header/note/footnote cells. Keep contextual cells read-only.

- [ ] **Step 4: Move the notes gate to acceptance**

Remove the pre-open notes check from Rules Manager. On `Accept table`, require nonblank notes, call `accept_raw_table`, refresh the draft and stage counts, and leave the dialog open on the next pending logical table. Merely inspecting or closing must produce no audit record.

- [ ] **Step 5: Run UI tests and verify GREEN**

Run: `uv run pytest -q tests/ui/test_raw_grid_review.py tests/ui/test_rules_manager_review.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add src/insulation_coordination/ui/raw_grid_review.py src/insulation_coordination/ui/rules_manager.py tests/ui/test_raw_grid_review.py tests/ui/test_rules_manager_review.py
git commit -m "fix: review semantic IEC tables before acceptance"
```

---

### Task 7: Add Equation and Mapping Review Before Build

**Files:**
- Create: `src/insulation_coordination/ui/equation_review.py`
- Modify: `src/insulation_coordination/ui/rules_manager.py`
- Modify: `tests/ui/test_rules_manager_review.py`
- Create: `tests/ui/test_equation_review.py`

**Interfaces:**
- Add `EquationReviewDialog(draft, *, actor: str)` with immutable `reviewed_draft` and `draft_changed` signal.
- Show formula ID, rendered equation/criterion, variables, units, applicability, supported range, source, and dependent semantic mappings.
- Replace `Review formula constants...` with `Review equations and mappings...`.
- Stage enablement: tables → equations/mappings → build → approve.

- [ ] **Step 1: Write failing dialog and stage-order tests**

Assert the equation dialog lists the four real Part 4 artifacts, exposes no unexplained comma-separated constant fields, shows their source clauses/pages, requires notes on acceptance, and cannot accept an equation with an unresolved parse status. Assert `Build reviewed content` stays disabled until both equations and mappings are accepted.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `uv run pytest -q tests/ui/test_equation_review.py tests/ui/test_rules_manager_review.py -k 'equation or mapping or build_order'`

Expected: missing dialog and current build-before-formula order.

- [ ] **Step 3: Implement the review dialog**

Use read-only labels/text areas for canonical equation data and source context. Permit editing only flagged parsed fields through typed controls. `Accept equation and mappings` requires notes and calls the domain acceptance operation; canceling records nothing.

- [ ] **Step 4: Rewire Rules Manager stages**

Delete `FormulaConstantDialog` and placeholder-count code. Derive independent table/equation/mapping/package counts from review items. Enable build only after all three source stages are resolved. Enable approval only after typed validation succeeds.

- [ ] **Step 5: Run Rules Manager and dialog tests and verify GREEN**

Run: `uv run pytest -q tests/ui/test_equation_review.py tests/ui/test_rules_manager.py tests/ui/test_rules_manager_review.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

```bash
git add src/insulation_coordination/ui/equation_review.py src/insulation_coordination/ui/rules_manager.py tests/ui/test_equation_review.py tests/ui/test_rules_manager_review.py
git commit -m "feat: review IEC equations before rule build"
```

---

### Task 8: Implement the Annex G Part 1 Clearance Candidates

**Files:**
- Modify: `src/insulation_coordination/calculation/clearance.py`
- Modify: `src/insulation_coordination/calculation/engine.py`
- Modify: `src/insulation_coordination/domain/trace.py`
- Modify: `tests/calculation/test_part1.py`
- Modify: `tests/calculation/conftest.py`
- Modify: `tests/fixtures/synthetic_rules.py`

**Interfaces:**
- `calculate_clearance_candidates(effective, rules)` evaluates impulse from F.2 and applicable steady-state/temporary/recurring peak stresses from F.8.
- Add explicit helpers `select_f2_impulse_clearance(...)`, `select_f8_periodic_clearance(...)`, and `apply_reinforced_stress_treatment(...)`.
- `DistanceCandidate`/trace retain input stress, treated stress, insulation route, field/pollution branch, selection mode, source cells, and omission justification.

- [ ] **Step 1: Write failing Annex G tests**

Cover functional, basic, supplementary, and reinforced insulation; Case A/Case B field routes; required pollution branches; each manual periodic stress; explicitly not-applicable stress with justification; unsupported missing inputs; and maximum candidate selection. Assert reinforced treatment changes the lookup stress before table selection and functional insulation does not receive basic/reinforced scaling.

```python
candidates = calculate_clearance_candidates(effective, rules)
assert {item.candidate_id for item in candidates} == {
    "impulse",
    "steady_state_peak",
    "temporary_overvoltage_peak",
    "recurring_peak",
}
assert trace_step(candidates, "impulse").semantic_rule_id == "iec60664-1:f2"
```

- [ ] **Step 2: Run Part 1 tests and verify RED**

Run: `uv run pytest -q tests/calculation/test_part1.py -k 'f2 or f8 or reinforced or clearance_candidate'`

Expected: existing route formulas are backed by wrong flattened sources and lack reviewed branch traces.

- [ ] **Step 3: Implement explicit F.2/F.8 selection**

Replace dynamically composed route strings that hide source meaning with a small set of validated semantic mappings. Perform stress treatment first, select with the table's declared exact/ceiling policy, and attach source-backed trace steps. Reject missing sparse branches and out-of-range stress as `CalculationRangeError`.

- [ ] **Step 4: Preserve manual stress boundary and omissions**

Keep all `PairVoltages` inputs. Continue requiring explicit `NOT_APPLICABLE` plus justification for omitted periodic stresses. Include each omission in the final trace without inventing a zero-voltage candidate.

- [ ] **Step 5: Run Part 1 and engine tests and verify GREEN**

Run: `uv run pytest -q tests/calculation/test_part1.py tests/test_end_to_end.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 8**

```bash
git add src/insulation_coordination/calculation/clearance.py src/insulation_coordination/calculation/engine.py src/insulation_coordination/domain/trace.py tests/calculation/test_part1.py tests/calculation/conftest.py tests/fixtures/synthetic_rules.py
git commit -m "feat: calculate Annex G Part 1 clearance"
```

---

### Task 9: Implement Pair-Specific Critical Frequency and Part 4 Clearance

**Files:**
- Modify: `src/insulation_coordination/calculation/high_frequency.py`
- Modify: `src/insulation_coordination/calculation/engine.py`
- Modify: `src/insulation_coordination/domain/trace.py`
- Modify: `tests/calculation/test_high_frequency.py`
- Modify: `tests/calculation/test_part1.py`

**Interfaces:**
- Add `calculate_critical_frequency(clearance_mm, rules) -> EvaluatedValue` using reviewed Equation (1) with explicit units.
- Add `select_frequency_factor(frequency_hz, critical_frequency_hz, rules)` for 100%, Equation (2), or 125% treatment.
- Replace tolerance-based looping with `assess_part4_clearance(effective, part1_periodic_candidate, rules)` that records initial and optional second pass.
- Add trace records for `critical_frequency_hz`, actual frequency, selected branch/factor, radius ratio, recalculated distance, and stability.

- [ ] **Step 1: Write failing critical-frequency boundary tests**

For two pairs with different Part 1 clearances but the same frequency, assert different computed critical frequencies and possibly different selected branches. Cover exactly 30 kHz (Part 4 inactive), above 30 kHz but below `fcritical`, between `fcritical` and reviewed minimum frequency, and at/above minimum frequency.

- [ ] **Step 2: Write failing field and second-pass tests**

Cover homogeneous, approximately homogeneous, and inhomogeneous fields; radius criterion pass/fail; Table 1 activation only at/above critical frequency for inhomogeneous fields; stable first pass; stable second pass; and a branch/field/distance that remains unstable after the second pass and raises `HighFrequencyCalculationError(code="HF_SECOND_PASS_UNSTABLE")`.

- [ ] **Step 3: Run high-frequency tests and verify RED**

Run: `uv run pytest -q tests/calculation/test_high_frequency.py -k 'critical or frequency_factor or second_pass or radius'`

Expected: current implementation uses fabricated tolerance and iteration-limit rules and does not model the approved branch sequence.

- [ ] **Step 4: Implement the bounded Part 4 algorithm**

Start from the relevant Part 1 periodic-voltage clearance, evaluate Equation (1), compare the actual pair frequency, evaluate the field route and Equation (2)/125% factor where applicable, calculate a new clearance, recompute critical frequency, and perform at most the described second pass. Stability means identical semantic branch, field classification, and source-rounded distance—not an arbitrary numeric tolerance.

- [ ] **Step 5: Remove fake convergence settings**

Delete `_iteration_setting`, tolerance/max-iteration routes, related fields from `HfCandidates`/`CalculationTrace`, and every UI/import mapping that supplied those pseudo-IEC values.

- [ ] **Step 6: Run high-frequency and engine tests and verify GREEN**

Run: `uv run pytest -q tests/calculation/test_high_frequency.py tests/calculation/test_part1.py tests/test_end_to_end.py`

Expected: PASS.

- [ ] **Step 7: Commit Task 9**

```bash
git add src/insulation_coordination/calculation/high_frequency.py src/insulation_coordination/calculation/engine.py src/insulation_coordination/domain/trace.py tests/calculation/test_high_frequency.py tests/calculation/test_part1.py
git commit -m "fix: apply pair specific IEC critical frequency"
```

---

### Task 10: Apply A.2 Altitude and F.9 Advisories

**Files:**
- Modify: `src/insulation_coordination/calculation/high_frequency.py`
- Modify: `src/insulation_coordination/calculation/engine.py`
- Modify: `src/insulation_coordination/domain/trace.py`
- Modify: `tests/calculation/test_part1.py`
- Modify: `tests/calculation/test_high_frequency.py`

**Interfaces:**
- Move altitude logic to `apply_a2_altitude_correction(effective, governing_clearance, rules)`.
- At/below 2,000 m, return the base clearance and a trace explaining no factor applies.
- Above 2,000 m, interpolate the reviewed A.2 factor only inside its supported range and apply it after the maximum clearance candidate is chosen.
- Add source-backed F.9 partial-discharge and withstand-test advisories without altering the numeric result.

- [ ] **Step 1: Write failing altitude/advisory tests**

Cover below, exactly at, between, and outside A.2 supported altitudes. Assert interpolation contributes both source cells, the factor is applied after Part 1/Part 4 maximum selection, and out-of-range altitude blocks. Assert F.9 advice appears for applicable PCB cases and never changes `clearance_mm` or `creepage_mm`.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest -q tests/calculation/test_part1.py tests/calculation/test_high_frequency.py -k 'altitude or a2 or partial_discharge or f9'`

Expected: current altitude mapping points to the wrong source and F.9 is absent.

- [ ] **Step 3: Implement A.2 and advisories**

Use a labeled A.2 table selection with linear altitude interpolation and exact source trace. Keep Part 4 assessment on the pre-altitude base clearance. Emit structured `CalculationWarning`/`VerificationRequirement` records with semantic rule IDs and source references.

- [ ] **Step 4: Run focused and engine tests and verify GREEN**

Run: `uv run pytest -q tests/calculation/test_part1.py tests/calculation/test_high_frequency.py tests/test_end_to_end.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 10**

```bash
git add src/insulation_coordination/calculation/high_frequency.py src/insulation_coordination/calculation/engine.py src/insulation_coordination/domain/trace.py tests/calculation/test_part1.py tests/calculation/test_high_frequency.py
git commit -m "feat: apply IEC altitude and discharge guidance"
```

---

### Task 11: Implement Annex H PCB Creepage and Part 4 Table 2

**Files:**
- Modify: `src/insulation_coordination/calculation/creepage.py`
- Modify: `src/insulation_coordination/calculation/high_frequency.py`
- Modify: `src/insulation_coordination/calculation/engine.py`
- Modify: `src/insulation_coordination/domain/trace.py`
- Modify: `tests/calculation/test_part1.py`
- Modify: `tests/calculation/test_high_frequency.py`
- Modify: `tests/calculation/conftest.py`

**Interfaces:**
- Add `select_f5_pcb_creepage(effective, rules)` over the joined F.5 table.
- Add `select_part4_table2_creepage(effective, rules)` with reviewed voltage-row and frequency-column policies plus the applicable pollution multiplier.
- Final creepage is `max(part1_f5, optional_part4_table2, final_clearance)`.
- Reinforced insulation doubles the selected F.5 distance; functional/basic/supplementary use it directly.

- [ ] **Step 1: Write failing F.5 tests**

Cover PCB pollution degree 1 and 2, exact voltage rows, permitted interpolation across the F.5 page boundary, functional/basic/supplementary, reinforced doubling, and the final-clearance floor. Assert values above/below the joined table range and PCB pollution degree 3/4 block rather than selecting non-PCB columns.

- [ ] **Step 2: Write failing unsupported-condition tests**

Assert explicit errors for coating/potting, rib reduction, split materials/pollution degrees, floating conductive parts, short-duration reduction, unsupported CTI/material classification, and other declared Annex H special cases represented in `conventional_construction_assumptions`.

- [ ] **Step 3: Write failing Table 2 tests**

Cover frequency at/below 30 kHz (no Part 4 creepage candidate), exact frequency columns, permitted between-column interpolation, conservative/non-interpolated voltage-row behavior, pollution multiplier, sparse missing combinations, and supported-range failures. Assert Part 4 Table 2 can govern over both F.5 and the clearance floor.

- [ ] **Step 4: Run creepage tests and verify RED**

Run: `uv run pytest -q tests/calculation/test_part1.py tests/calculation/test_high_frequency.py -k 'creepage or f5 or table2 or unsupported_pcb'`

Expected: current creepage routes are backed by F.4/Table 5 and lack joined-table semantics.

- [ ] **Step 5: Implement Annex H selection and validation**

Validate PCB scope before lookup. Select only the reviewed printed-wiring branches, use only source-permitted interpolation, apply reinforced doubling after the F.5 selection, and add a source-backed trace for every transformation. At high frequency, evaluate Table 2 independently and then take the maximum with final clearance.

- [ ] **Step 6: Run creepage, engine, and grouping tests and verify GREEN**

Run: `uv run pytest -q tests/calculation/test_part1.py tests/calculation/test_high_frequency.py tests/calculation/test_grouping.py tests/test_end_to_end.py`

Expected: PASS.

- [ ] **Step 7: Commit Task 11**

```bash
git add src/insulation_coordination/calculation/creepage.py src/insulation_coordination/calculation/high_frequency.py src/insulation_coordination/calculation/engine.py src/insulation_coordination/domain/trace.py tests/calculation
git commit -m "feat: calculate Annex H PCB creepage"
```

---

### Task 12: Bump Trust Versions and Reject Obsolete Packages

**Files:**
- Modify: `src/insulation_coordination/domain/rules.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/archive.py`
- Modify: `src/insulation_coordination/rules/validation.py`
- Modify: `src/insulation_coordination/project/resolver.py`
- Modify: `src/insulation_coordination/ui/main_window.py`
- Modify: `tests/rules/test_archive.py`
- Modify: `tests/project/test_resolver.py`
- Modify: `tests/ui/test_rules_manager.py`

**Interfaces:**
- Increment `RULE_SCHEMA_VERSION` and `IMPORTER_VERSION` together.
- Validation requires semantic axis labels, `TableSelect`, corrected source inventory, real equation IDs, and absence of `raw_sequence`/obsolete source IDs.
- Archive/project loading reports a clear regeneration error for superseded packages.

- [ ] **Step 1: Write failing migration/trust-gate tests**

Build legacy fixtures containing `raw_sequence`, F.3 altitude, F.4 creepage, Part 4 Table 5, or the four placeholder formulas. Assert archive import and project resolution reject them with an error that tells the maintainer to re-import the licensed PDFs. Assert no partially loaded package becomes active.

- [ ] **Step 2: Run migration tests and verify RED**

Run: `uv run pytest -q tests/rules/test_archive.py tests/project/test_resolver.py tests/ui/test_rules_manager.py -k 'legacy or schema or regenerate or raw_sequence'`

Expected: old schema packages are currently structurally accepted or fail without useful guidance.

- [ ] **Step 3: Implement version and semantic trust gates**

Reject any schema other than the current version at calculation/archive trust boundaries. Add explicit validation issue codes for obsolete importer, missing semantic axis labels, obsolete source table, placeholder formula, and forbidden `raw_sequence`. Surface one concise user-facing regeneration message in Rules Manager/main window.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest -q tests/rules/test_archive.py tests/project/test_resolver.py tests/ui/test_rules_manager.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 12**

```bash
git add src/insulation_coordination/domain/rules.py src/insulation_coordination/rules/importer/extract.py src/insulation_coordination/rules/archive.py src/insulation_coordination/rules/validation.py src/insulation_coordination/project/resolver.py src/insulation_coordination/ui/main_window.py tests/rules/test_archive.py tests/project/test_resolver.py tests/ui/test_rules_manager.py
git commit -m "fix: reject obsolete IEC rule packages"
```

---

### Task 13: Add Real-PDF Import-to-Calculation Acceptance Coverage

**Files:**
- Modify: `tests/private/test_supplied_standards.py`
- Modify: `tests/test_end_to_end.py`
- Modify: `tests/ui/test_rules_manager_review.py`
- Modify: `docs/release-checklist.md`

**Interfaces:**
- One private helper performs: identify → extract → accept tables → accept equations/mappings → build → approve.
- The approved package passes semantic validation and can calculate representative PCB pairs below and above 30 kHz.
- Private assertions may inspect licensed values at runtime, but no extracted value snapshots are committed.

- [ ] **Step 1: Write the failing end-to-end acceptance test**

With the supplied PDFs, assert:

1. corrected source inventory and one joined F.5 table;
2. no unresolved review items after explicit acceptance;
3. package approval/round-trip archive validation;
4. one Part 1 PCB pair with Annex G/H traces;
5. two above-30-kHz pairs with different clearances produce their own `fcritical` decisions;
6. one Part 4 Table 1 path and one Table 2 path;
7. final trace source references resolve to the expected standard/table/equation pages.

- [ ] **Step 2: Run acceptance tests and verify RED**

Run: `uv run pytest -q tests/private/test_supplied_standards.py tests/test_end_to_end.py`

Expected: failures expose any remaining importer/projection/calculation seam.

- [ ] **Step 3: Fix only integration defects**

Make no new architecture in this task. Correct identifiers, units, source propagation, stage transitions, or fixture setup revealed by the end-to-end test. If a semantic assumption is wrong, stop and amend the approved design before changing behavior.

- [ ] **Step 4: Run acceptance tests and verify GREEN**

Run: `uv run pytest -q tests/private/test_supplied_standards.py tests/test_end_to_end.py`

Expected: PASS with local PDFs.

- [ ] **Step 5: Add release-checklist scenarios**

Add manual checks for empty-note dialog opening, table headings/footnotes, F.5 continuation, equation-review order, pair-specific `fcritical`, unsupported PCB cases, schema rejection, and trace source links.

- [ ] **Step 6: Commit Task 13**

```bash
git add tests/private/test_supplied_standards.py tests/test_end_to_end.py tests/ui/test_rules_manager_review.py docs/release-checklist.md
git commit -m "test: cover reviewed IEC PCB workflow end to end"
```

---

### Task 14: Document Annex G/H and Code Traceability

**Files:**
- Modify: `README.md`
- Modify: `docs/release-checklist.md`
- Test: `tests/test_package.py`

**Interfaces:**
- README sections: product boundary, required source inventory, Rules Manager review workflow, Annex G flow, Part 4 critical-frequency flow, Annex H flow, supported/blocked PCB cases, trace interpretation, and implementation map.
- Mermaid diagrams show branch order and maximum/floor selection.
- Implementation map links every numbered workflow step to the exact public/private function and focused test module.

- [ ] **Step 1: Add failing documentation contract tests**

In `tests/test_package.py`, assert README contains the corrected table IDs, Annex G/H headings, `fcritical` per-pair statement, unsupported-condition section, and paths/names for the entry-point functions. This guards against the old F.3/F.4/Table 5 documentation returning.

- [ ] **Step 2: Run documentation tests and verify RED**

Run: `uv run pytest -q tests/test_package.py -k 'readme or workflow_documentation'`

Expected: missing corrected workflow documentation.

- [ ] **Step 3: Write the source and review workflow documentation**

Explain why required-content and manual-review counts differ, how contextual cells differ from pending semantic artifacts, why review opens without notes but acceptance requires them, how multipage F.5 is joined, and why raw display text/footnotes do not become lookup keys.

- [ ] **Step 4: Write the calculation workflow documentation**

Add concise Mermaid flows for Annex G, the pair-specific Part 4 `fcritical` branch, and Annex H. State the manual stress boundary and list F.2/F.5/F.8/F.9/A.2/Tables 1/2/Equations 1/2. Document supported PCB cases and every blocked condition.

- [ ] **Step 5: Add step-to-code and step-to-test links**

Use repository-relative links with function anchors or function names, for example:

| Workflow step | Implementation | Verification |
| --- | --- | --- |
| Annex G candidates | `calculation/clearance.py::calculate_clearance_candidates` | `tests/calculation/test_part1.py` |
| Pair `fcritical` | `calculation/high_frequency.py::calculate_critical_frequency` | `tests/calculation/test_high_frequency.py` |
| Annex H maximum | `calculation/creepage.py::calculate_creepage_candidates` | `tests/calculation/test_part1.py` |

- [ ] **Step 6: Run documentation tests and verify GREEN**

Run: `uv run pytest -q tests/test_package.py -k 'readme or workflow_documentation'`

Expected: PASS.

- [ ] **Step 7: Commit Task 14**

```bash
git add README.md docs/release-checklist.md tests/test_package.py
git commit -m "docs: map IEC PCB workflows to implementation"
```

---

### Task 15: Full Verification and Manual GUI Check

**Files:**
- Modify only if verification reveals a defect; add a regression test before each fix.

- [ ] **Step 1: Run formatting and static checks**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
```

Expected: all commands exit 0.

- [ ] **Step 2: Run the complete automated suite**

Run: `uv run pytest -q`

Expected: PASS, with private supplied-standard tests passing when their local PDF fixture is available.

- [ ] **Step 3: Verify package/install entry points**

Run:

```bash
uv sync --locked --all-groups
uv run icc --help
```

Expected: dependencies remain locked and the CLI entry point starts successfully.

- [ ] **Step 4: Perform the manual Rules Manager workflow**

Run: `uv run icc --gui`

Using local IEC PDFs, verify:

1. table review opens with no notes;
2. real headings, source pages, normalized values, and footnotes are visible;
3. F.5 continues across both pages as one logical table;
4. acceptance, not viewing, requires notes;
5. equations/mappings are reviewed before build;
6. the obsolete constant dialog is gone;
7. stage counts are understandable and reach zero pending;
8. build and approval enable in order;
9. an approved package calculates representative PCB pairs;
10. above 30 kHz, each pair trace shows its own clearance, `fcritical`, comparison, branch, and second-pass state.

- [ ] **Step 5: Inspect repository hygiene**

Run:

```bash
git status --short
git diff --check
git log --oneline -15
```

Expected: no PDFs, generated rules/projects, caches, or unrelated files are tracked; no whitespace errors; one focused commit per task.

- [ ] **Step 6: Request code review**

Use `superpowers:requesting-code-review` against the approved design and this plan. Resolve every correctness/safety finding with a regression test, then rerun Steps 1–5.

- [ ] **Step 7: Finish the branch**

Because work is intentionally on `main`, do not merge another branch. Report the commits, verification evidence, any intentionally unsupported PCB cases, and the exact manual test sequence to the user.
