# Pairs and Report Readability Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make missing-rules recalculation errors explicit and make Chapters 4–5 of the human report show pair voltage inputs and shared group calculations without duplication.

**Architecture:** Keep calculation and report-model validation unchanged. Add the missing-rules guard at the Pairs page boundary, derive voltage matrices separately from default/effective comparison data in `human_view.py`, and render one representative calculation per calculation group because grouping already guarantees identical identity-free results. Use the existing Jinja LaTeX template and focused pytest fixtures.

**Tech Stack:** Python 3, PySide6, Pydantic models, pytest/pytest-qt, Jinja2, LaTeX/Tectonic, Ruff.

## Global Constraints

- Preserve authoritative report validation and internal calculation traces.
- Keep human-facing pair/group labels; do not expose pair IDs, signatures, or package UUIDs in the PDF.
- Always render matrices for long-term RMS, steady-state peak, recurring peak, and temporary overvoltage pair inputs.
- Render one shared calculation block per group and omit redundant `5.x.x` pair subsections.
- Do not modify user-generated `audit/`, `projects/`, or `tmp/` contents.

---

### Task 1: Make missing rules explicit on the Pairs page

**Files:**
- Modify: `tests/ui/test_pair_workflow.py`
- Modify: `src/insulation_coordination/ui/pair_editor.py:919-949`

**Interfaces:** `PairPage.recalculate()` remains a no-argument UI slot; `format_calculation_error()` continues formatting pair-specific failures.

- [ ] **Step 1: Write the failing test**

Add `test_recalculate_reports_missing_rules` with a loaded project and no rules package. Monkeypatch `QMessageBox.critical`, call `page.recalculate()`, and assert the captured message contains `Load an approved rules package` and no result exists.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/ui/test_pair_workflow.py::test_recalculate_reports_missing_rules -q`

Expected: FAIL because `recalculate()` currently returns silently.

- [ ] **Step 3: Write the minimal implementation**

Replace the silent guard with:

```python
if self._project is None:
    return
if self._rules is None:
    QMessageBox.critical(
        self,
        "Cannot recalculate",
        "Load an approved rules package before recalculating.",
    )
    return
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/ui/test_pair_workflow.py::test_recalculate_reports_missing_rules -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/ui/test_pair_workflow.py src/insulation_coordination/ui/pair_editor.py
git commit -m "fix: explain missing rules on recalculation"
```

### Task 2: Keep all pair-input voltage matrices in Chapter 4

**Files:**
- Modify: `tests/report/test_human_view.py`
- Modify: `tests/report/test_latex.py`
- Modify: `src/insulation_coordination/report/human_view.py:82-143`

**Interfaces:** `build_human_report_view(model: ReportModel) -> HumanReportView` remains the projection entry point; `HumanMatrix` remains square with `name`, `unit`, `headers`, and `values`.

- [ ] **Step 1: Write the failing tests**

Assert the human view contains these matrix names even when all pair stresses are equal:

```python
names = {item.name for item in view.comparison_matrices}
assert {
    "Long-term RMS voltage",
    "Steady-state peak voltage",
    "Recurring peak voltage",
    "Temporary overvoltage peak voltage",
} <= names
```

Add a LaTeX assertion for the same four names and ensure they are not common-value bullets.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/report/test_human_view.py tests/report/test_latex.py -q`

Expected: FAIL because equal voltage stresses currently move to `common_values`.

- [ ] **Step 3: Write the minimal implementation**

Separate the existing default/effective specifications from voltage specifications. Always append `_matrix_for(...)` for:

```python
(
    ("Long-term RMS voltage", "V", lambda row: _stress_text(row, "long-term RMS")),
    ("Steady-state peak voltage", "V", lambda row: _stress_text(row, "steady-state peak")),
    ("Recurring peak voltage", "V", lambda row: _stress_text(row, "recurring peak")),
    ("Temporary overvoltage peak voltage", "V", lambda row: _stress_text(row, "temporary overvoltage peak")),
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/report/test_human_view.py tests/report/test_latex.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/report/test_human_view.py tests/report/test_latex.py src/insulation_coordination/report/human_view.py
git commit -m "feat: show pair voltage matrices in reports"
```

### Task 3: Render one shared calculation block per group

**Files:**
- Modify: `tests/report/test_latex.py`
- Modify: `src/insulation_coordination/report/templates/report.tex.j2:122-203`

**Interfaces:** `HumanGroup.pair_labels` remains the displayed membership; `HumanGroup.calculations[0]` is the representative calculation because the group signature guarantees identical results.

- [ ] **Step 1: Write the failing test**

Add `test_grouped_report_renders_one_shared_block_per_group` asserting the rendered report contains no `\\subsubsection`, contains `Included pairs:`, and contains exactly one `Effective conditions.` block per human group.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/report/test_latex.py::test_grouped_report_renders_one_shared_block_per_group -q`

Expected: FAIL because the template currently emits one pair subsection per calculation.

- [ ] **Step 3: Write the minimal implementation**

Inside each group loop, add `\\clearpage`, keep the group subsection and included pair labels, assign `{% set calculation = group.calculations[0] %}`, and render the existing shared tables once. Remove the pair loop and `\\subsubsection` heading.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/report/test_latex.py::test_grouped_report_renders_one_shared_block_per_group -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/report/test_latex.py src/insulation_coordination/report/templates/report.tex.j2
git commit -m "refactor: summarize shared calculations by group"
```

### Task 4: Apply page breaks, wording, and compact candidate columns

**Files:**
- Modify: `tests/report/test_latex.py`
- Modify: `src/insulation_coordination/report/templates/report.tex.j2:90-205`

**Interfaces:** The template remains rendered through `render_latex()`; existing template filters remain available.

- [ ] **Step 1: Write the failing tests**

Assert `\\clearpage` precedes Chapters 4 and 5, each group has a preceding page break, candidate tables use `@{}XrrX@{}`, and a no-correction report contains `altitude correction was not needed`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/report/test_latex.py -q`

Expected: FAIL because the current template lacks all requested breaks, uses equal-width candidate columns, and renders `no`.

- [ ] **Step 3: Write the minimal implementation**

Add `\\clearpage` before Chapters 4 and 5 and at the start of every group loop. Change candidate table preambles to `@{}XrrX@{}`. Replace boolean interpolation with an explicit conditional that renders `altitude correction was applied` or `altitude correction was not needed`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/report/test_latex.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/report/test_latex.py src/insulation_coordination/report/templates/report.tex.j2
git commit -m "fix: improve report pagination and table layout"
```

### Task 5: Full verification and representative PDF QA

**Files:** Verify `src/insulation_coordination/ui/pair_editor.py`, `src/insulation_coordination/report/human_view.py`, and `src/insulation_coordination/report/templates/report.tex.j2`.

**Interfaces:** No new production interfaces; this task validates the completed changes end-to-end.

- [ ] **Step 1: Run focused tests**

Run: `.venv/bin/pytest tests/ui/test_pair_workflow.py tests/report/test_human_view.py tests/report/test_latex.py -q`

Expected: all focused tests pass.

- [ ] **Step 2: Run Ruff**

Run: `.venv/bin/ruff check src tests`

Expected: `All checks passed!`.

- [ ] **Step 3: Generate and compile the representative multi-pair report**

Regenerate `tmp/pdfs/test1-report/test1-human.tex` from `projects/test1.icproj` and `rules/RulesTest1.icrules`, then run:

```bash
/opt/homebrew/bin/tectonic --outdir tmp/pdfs/test1-report tmp/pdfs/test1-report/test1-human.tex
```

Expected: exit code 0 and no `Overfull` warnings.

- [ ] **Step 4: Render and inspect representative pages**

Render with bundled `pdftoppm` and inspect the contents page, Chapter 4 voltage matrices, first Chapter 5 group, and final page. Confirm page breaks, all four voltage matrices, one shared block per group, compact numeric columns, readable wording, and no clipped or overlapping text.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`

Expected: zero failures.

- [ ] **Step 6: Review status**

Run `git diff --check`, `git status --short`, and `git log --oneline -6`. Leave user-generated `audit/`, `projects/`, and `tmp/` uncommitted.
