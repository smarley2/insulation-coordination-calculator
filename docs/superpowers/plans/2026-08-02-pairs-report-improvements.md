# Pairs Page and Human-Readable Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the loaded-project Pairs workflow stable and explicit, expose calculated values in the matrix, and generate a compact human-readable report without internal identifiers or overflowing tables.

**Architecture:** Keep the calculation engine and authoritative report validation intact, then add one shared pair-label helper and a human-facing report view derived from the validated snapshot. The Pairs page will validate all effective cases before publishing any result, while the LaTeX template will render comparison matrices and concise grouped explanations from display-oriented fields.

**Tech Stack:** Python 3.12, PySide6, Pydantic models, pytest/pytest-qt, Jinja2, LaTeX/Tectonic, Poppler rendering for PDF QA.

## Global Constraints

- Pair-specific values remain pair overrides; project defaults remain inherited until overridden.
- Recalculation is all-or-nothing and must identify every invalid human-readable pair and field.
- UUIDs, result hashes, raw semantic IDs, and low-level trace steps are not rendered in the human report or primary calculation lists.
- Explicit `printed_wiring` in project defaults or a pair override counts as confirmation and emits no PCB construction advisory.
- Calculated matrix cells show an em dash before a successful calculation and millimetres afterward.
- The main window must preserve maximized state and outer geometry while navigating between pages.
- Preserve the existing rules package and Python dependency floors; do not modify unrelated `audit/` or user project artifacts.

---

## File map

| File | Responsibility in this change |
| --- | --- |
| `src/insulation_coordination/domain/display.py` | Shared human-readable pair labels and display names. |
| `src/insulation_coordination/ui/pair_models.py` | Calculated matrix parameters and result display. |
| `src/insulation_coordination/ui/pair_editor.py` | Layout containment, all-or-nothing recalculation, and user-facing validation dialog. |
| `src/insulation_coordination/ui/calculation_review.py` | Human-readable group membership and result rows. |
| `src/insulation_coordination/ui/main_window.py` | Navigation geometry preservation. |
| `src/insulation_coordination/calculation/engine.py` | Suppression of confirmed printed-wiring advisory and advisory deduplication helper if required. |
| `src/insulation_coordination/report/model.py` | Display-oriented pair/group fields and comparison-matrix snapshot. |
| `src/insulation_coordination/report/latex.py` | Readable source-reference formatting and safe wrapping helpers. |
| `src/insulation_coordination/report/templates/report.tex.j2` | Table of contents and the revised Chapters 4–7. |
| `tests/ui/test_pair_workflow.py` | Pairs layout, validation, matrix, and result-label regressions. |
| `tests/ui/test_calculation_review.py` | Human-readable review labels. |
| `tests/report/test_latex.py` | Human report model/template behavior. |
| `tests/calculation/test_part1.py` | Printed-wiring advisory behavior. |
| `tests/test_end_to_end.py` | Complete report generation and PDF smoke coverage. |

---

### Task 1: Add one shared human pair-label function

**Files:**
- Create: `src/insulation_coordination/domain/display.py`
- Test: `tests/domain/test_display.py`
- Modify: `src/insulation_coordination/ui/pair_models.py`

**Interfaces:**
- Produces `pair_label(project: Project, pair: PairCase) -> str`, formatted as `name_a ↔ name_b` using project net-class order.
- `PairListModel` and later report/UI tasks consume this function instead of duplicating net-ID lookup logic.

- [ ] **Step 1: Write the failing test**

```python
def test_pair_label_uses_net_class_names(project):
    assert pair_label(project, project.pairs[0]) == "HV+ ↔ HV-"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/domain/test_display.py::test_pair_label_uses_net_class_names -q`

Expected: FAIL because `insulation_coordination.domain.display` does not yet provide `pair_label`.

- [ ] **Step 3: Write minimal implementation**

Implement a mapping from `project.net_classes` IDs to names, preserve the pair's `net_a`/`net_b` order, and use `?` only for an invalid reference.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/domain/test_display.py -q`

Expected: PASS.

- [ ] **Step 5: Replace duplicated UI formatting**

Update `PairListModel.load_project` and `CalculationReviewPage` callers to use the helper while keeping UUIDs available only as internal lookup keys.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/domain/display.py src/insulation_coordination/ui/pair_models.py tests/domain/test_display.py
git commit -m "feat: centralize human pair labels"
```

### Task 2: Make recalculation all-or-nothing with visible errors

**Files:**
- Modify: `src/insulation_coordination/ui/pair_editor.py:911-928`
- Modify: `src/insulation_coordination/ui/calculation_review.py:73-95`
- Test: `tests/ui/test_pair_workflow.py`
- Test: `tests/ui/test_calculation_review.py`

**Interfaces:**
- `PairPage.recalculate()` remains the button slot and publishes either all `PairResult` values or none.
- Add a small formatter in `pair_editor.py`, `format_calculation_error(pair_label: str, error: Exception) -> str`, that turns engine messages such as `frequency_hz is required` into `Frequency is required`.

- [ ] **Step 1: Write the failing missing-frequency test**

Create a pair-page fixture with `defaults.frequency_hz=None`, invoke `page.recalculate()`, and assert the review lists are empty and the captured critical message contains `HV+ ↔ HV-` and `Frequency is required`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ui/test_pair_workflow.py -k missing_frequency -q`

Expected: FAIL because the current code catches the exception and silently continues.

- [ ] **Step 3: Implement preflight and atomic publication**

Resolve every pair first, call `calculate_pair` into a temporary list, collect `(pair_label, exception)` on failure, and return without calling `update_results` when the error list is non-empty. Clear `_results` and the review page before showing a `QMessageBox.critical` containing all formatted errors.

- [ ] **Step 4: Run the focused tests**

Run: `pytest tests/ui/test_pair_workflow.py -k 'missing_frequency or grouping' tests/ui/test_calculation_review.py -q`

Expected: PASS, with no stale group or result rows after the blocked calculation.

- [ ] **Step 5: Add a multi-error test**

Use two pairs with different missing fields and assert one dialog message contains both human pair labels, proving no pair is silently skipped.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/ui/pair_editor.py src/insulation_coordination/ui/calculation_review.py tests/ui/test_pair_workflow.py tests/ui/test_calculation_review.py
git commit -m "fix: report blocked pair recalculations"
```

### Task 3: Show calculated clearance and creepage in the Pairs page

**Files:**
- Modify: `src/insulation_coordination/ui/pair_models.py:13-146`
- Modify: `src/insulation_coordination/ui/pair_editor.py:751-909`
- Test: `tests/ui/test_pair_workflow.py`

**Interfaces:**
- `CoverageMatrixModel.set_results(results: Mapping[str, PairResult]) -> None` stores results by pair UUID and emits a model reset.
- `CoverageMatrixModel.load_project` clears result values; `PairPage.recalculate` passes the complete result mapping after success.

- [ ] **Step 1: Write failing matrix tests**

Assert the selector contains `Required clearance` and `Required creepage`, cells show `—` before calculation, and after a valid calculation show the result in `mm` in both mirrored cells.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ui/test_pair_workflow.py -k 'calculated_matrix or required_clearance or required_creepage' -q`

Expected: FAIL because the selector and model have no calculated-result parameters.

- [ ] **Step 3: Implement result-backed parameters**

Add the two matrix keys, return `—` when no result exists, and format `result.clearance_mm`/`result.creepage_mm` with `_format_value`. Keep coverage and input parameter behavior unchanged.

- [ ] **Step 4: Connect the page lifecycle**

Clear results from `load_project`, pair edits, and blocked recalculation. Publish results to the matrix only after every pair succeeds.

- [ ] **Step 5: Run focused UI tests**

Run: `pytest tests/ui/test_pair_workflow.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/ui/pair_models.py src/insulation_coordination/ui/pair_editor.py tests/ui/test_pair_workflow.py
git commit -m "feat: display calculated distances in pair matrix"
```

### Task 4: Stabilize navigation and the Pairs page geometry

**Files:**
- Modify: `src/insulation_coordination/ui/main_window.py:41-69,163-167`
- Modify: `src/insulation_coordination/ui/pair_editor.py:805-855`
- Test: `tests/ui/test_pair_workflow.py`
- Test: `tests/ui/test_main_window.py`

**Interfaces:**
- `_show_page(index: int)` preserves `windowState()` and `frameGeometry()` while changing the stacked page.
- `PairPage` keeps all child minimum sizes at zero except the matrix's useful minimum height and reapplies internal splitter sizes after the page receives its real viewport size.

- [ ] **Step 1: Write the failing navigation regression test**

Show a `MainWindow`, maximize it, load `projects/test1.icproj`, switch to Pairs and back, and assert `isMaximized()` and the outer geometry remain unchanged. Use `QApplication.processEvents()` after each navigation.

- [ ] **Step 2: Run test to verify it fails or captures the regression**

Run: `pytest tests/ui/test_main_window.py -k project_load_pairs_geometry -q`

Expected: the test either reproduces the size change or establishes the current invariant on the platform; it must fail if a page causes the window to leave maximized state or alter its frame geometry.

- [ ] **Step 3: Implement geometry preservation**

Capture the current state and frame geometry around `setCurrentIndex`, restore maximized state when it was maximized, and avoid calling `resize` on the outer window. In `PairPage`, use zero minimum widths on scroll/panel children, set splitter sizes only from the actual viewport, and schedule the size pass on every first show after a project load without changing the outer window.

- [ ] **Step 4: Add layout assertions**

Assert matrix and pair-list rectangles do not intersect, the editor scroll area has a vertical scrollbar range at laptop-height, and the N/A controls are descendants of the voltage rows.

- [ ] **Step 5: Run UI tests**

Run: `pytest tests/ui/test_main_window.py tests/ui/test_pair_workflow.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/ui/main_window.py src/insulation_coordination/ui/pair_editor.py tests/ui/test_main_window.py tests/ui/test_pair_workflow.py
git commit -m "fix: preserve pairs page window geometry"
```

### Task 5: Add human-facing report comparison data

**Files:**
- Modify: `src/insulation_coordination/report/model.py:93-180,251-297`
- Create: `src/insulation_coordination/report/human_view.py`
- Test: `tests/report/test_human_view.py`
- Modify: `tests/report/test_latex.py`

**Interfaces:**
- `HumanMatrix(name: str, unit: str, values: tuple[tuple[str, ...], ...])` stores one square matrix with net-class headers represented by the existing project order.
- `HumanPairCalculation(pair_label: str, ... )` stores the readable subset needed by the template: effective conditions, stresses, candidate summaries, governing explanation, final distances, and readable source references.
- `build_human_report_view(model: ReportModel) -> HumanReportView` derives common characteristics, differing matrices, display-numbered groups, and human pair calculations without changing authoritative validation.

- [ ] **Step 1: Write failing comparison tests**

Build a report model with one shared default and one pair override. Assert the shared characteristic appears in `common_values`, the overridden characteristic creates exactly one square matrix, diagonal cells are `—`, and pair cells use net-class labels.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/report/test_human_view.py -q`

Expected: FAIL because no human report view exists.

- [ ] **Step 3: Implement human-view dataclasses/models**

Create frozen validated models with display-safe strings and decimal values. Use the report model's `matrix_rows` and `groups`; never expose UUIDs or hashes as rendered fields.

- [ ] **Step 4: Implement generic common/different comparison**

For each effective field, voltage stress, required clearance, and required creepage, compare normalized display values across all pair rows. Emit one `HumanMatrix` only when more than one value exists.

- [ ] **Step 5: Implement readable calculation explanations**

Convert candidate IDs and governing reasons to labels such as `Impulse withstand`, `Steady-state peak`, `Altitude correction`, and `Selected creepage floor`; keep the associated source reference as a readable sentence.

- [ ] **Step 6: Run report tests and commit**

Run: `pytest tests/report/test_human_view.py tests/report/test_latex.py -q`

Expected: the new view tests pass; existing audit-snapshot tests continue to validate trace retention.

```bash
git add src/insulation_coordination/report/model.py src/insulation_coordination/report/human_view.py tests/report/test_human_view.py tests/report/test_latex.py
git commit -m "feat: derive human report comparison data"
```

### Task 6: Replace the report template with readable chapters

**Files:**
- Modify: `src/insulation_coordination/report/latex.py:28-45,63-82`
- Modify: `src/insulation_coordination/report/templates/report.tex.j2:38-372`
- Modify: `tests/report/test_latex.py`

**Interfaces:**
- `render_latex` adds the human report view to the Jinja context while retaining strict undefined behavior.
- The template renders `HumanReportView.common_values`, `.comparison_matrices`, `.groups`, `.advisories`, and `.rules`.

- [ ] **Step 1: Write failing template assertions**

Assert generated TeX contains `\\tableofcontents`, a `Pair Comparison Matrices` section, a common-values paragraph, and a square matrix for a differing field. Assert it does not contain `Authoritative Pair Matrix`, `Pair ID`, `Result SHA-256`, `Signature:`, `Transformations, corrections, and selections.`, or `Approval Records`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/report/test_latex.py -k human -q`

Expected: FAIL because the current template renders the audit table and raw trace.

- [ ] **Step 3: Add table-of-contents and matrix macros**

Insert `\\tableofcontents` after the title page and define a compact `tabularx`/`longtable` layout with bounded paragraph columns. Render each human comparison matrix with net-class headers and em-dash diagonals.

- [ ] **Step 4: Render Chapters 4 and 5 from human view**

Replace the landscape authoritative table with common values and only differing matrices. Replace group hashes, pair UUIDs, raw paths, formula traces, and per-step output with human pair labels, candidate summaries, concise prose, and readable source references.

- [ ] **Step 5: Render advisory and provenance chapters**

Deduplicate advisory codes before rendering, omit Chapter 6 when empty, render one advisory list when non-empty, retain source documents, and remove the Approval Records subsection entirely.

- [ ] **Step 6: Add wrapping regression assertions**

Use long synthetic reasons and source references and assert the TeX contains `\\allowbreak` or paragraph-cell output rather than one unbreakable machine string. Keep trusted formulas out of the human template.

- [ ] **Step 7: Run focused report tests and commit**

Run: `pytest tests/report/test_latex.py -q`

Expected: PASS with the updated human-report assertions and all unchanged model-integrity assertions.

```bash
git add src/insulation_coordination/report/latex.py src/insulation_coordination/report/templates/report.tex.j2 tests/report/test_latex.py
git commit -m "feat: render concise human-readable report"
```

### Task 7: Suppress confirmed printed-wiring notices and update advisory tests

**Files:**
- Modify: `src/insulation_coordination/calculation/engine.py:377-400`
- Test: `tests/calculation/test_part1.py`
- Modify: `tests/report/test_latex.py`

**Interfaces:**
- `calculate_pair` returns no `PCB_CONSTRUCTION_CONFIRMATION` warning or verification requirement when the effective construction is explicit `printed_wiring` from defaults or an override.
- Distinct advisory codes remain available and are rendered once per code.

- [ ] **Step 1: Write failing advisory tests**

Assert an effective printed-wiring case has empty warning and verification tuples, while a distinct synthetic warning still appears once after report-level deduplication.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/calculation/test_part1.py -k printed_wiring tests/report/test_latex.py -k advisory -q`

Expected: FAIL because the engine currently emits the same confirmation twice.

- [ ] **Step 3: Implement confirmation semantics**

Remove the printed-wiring warning/requirement branch when the effective value is explicit. Do not alter the construction calculation path or other warning conditions.

- [ ] **Step 4: Run advisory tests**

Run: `pytest tests/calculation/test_part1.py tests/report/test_latex.py -k 'printed_wiring or advisory' -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/insulation_coordination/calculation/engine.py tests/calculation/test_part1.py tests/report/test_latex.py
git commit -m "fix: treat explicit printed wiring as confirmed"
```

### Task 8: Verify end-to-end PDF output and finish integration

**Files:**
- Modify: `tests/test_end_to_end.py`
- Modify: `docs/release-checklist.md` only if the existing checklist needs a report-layout verification item.

- [ ] **Step 1: Add end-to-end human-report assertions**

Generate the synthetic report and assert the output contains the table of contents and human pair names, excludes UUID/hash/raw-trace markers, and has no Chapter 7.2 heading.

- [ ] **Step 2: Run the complete Python test suite**

Run: `.venv/bin/pytest -q`

Expected: PASS with zero failures.

- [ ] **Step 3: Compile a representative report**

Run the existing report-generation path against the complete workspace and compile the resulting `.tex` with the configured Tectonic command. Confirm the compiler exits successfully and the PDF exists.

- [ ] **Step 4: Render and inspect PDF pages**

Render the title/contents page, Chapter 4, the first Chapter 5 pair, advisories, and final provenance pages with the bundled Poppler `pdftoppm`. Check that matrix cells, source references, candidate names, and paragraph text remain inside page margins with no overlap.

- [ ] **Step 5: Run formatting/static checks**

Run: `.venv/bin/ruff check src tests`

Expected: exit 0.

- [ ] **Step 6: Review the implementation against the specification**

Confirm every requirement in `docs/report-and-pairs-improvements-spec.md` has a passing test or visual inspection result, and verify `git status --short` shows no generated report or temporary QA files staged.

- [ ] **Step 7: Commit final integration changes**

```bash
git add tests/test_end_to_end.py docs/release-checklist.md
git commit -m "test: verify human-readable report output"
```

## Plan self-review

- Spec coverage: Tasks 1–4 cover pair labels, validation, calculated matrix values, N/A placement, scrolling, non-overlap, and navigation geometry. Tasks 5–7 cover common/different matrices, readable grouped calculations, wrapping, table of contents, advisory semantics, Chapter 6 omission, and removal of Chapter 7.2. Task 8 covers compilation and rendered-PDF inspection.
- Placeholder scan: no step relies on an unfinished-task marker or an unspecified helper; all new interfaces and test commands are named.
- Type consistency: `pair_label` is shared by UI/report consumers; `set_results` accepts pair-ID keyed results; `build_human_report_view` is the only template-facing transformation; `render_latex` receives the validated report model and derives the view.
- Scope: no changes are planned for unrelated `audit/` or user-generated `projects/` files.
