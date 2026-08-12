# Annex E Semantic ID Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give IEC 62477-1:2022 Annex E's two tables one semantic identifier each, so no
identifier in the approved-package contract claims a clearance-dimensioning factor is a
test-voltage correction.

**Architecture:** `iec62477_2022.altitude.clearance_correction` is added beside the existing
`iec62477_2022.altitude.test_voltage_correction`; the recipe's two Annex E specs stop building
suffixed ids (`.e1` / `.e2`) and name the two bare constants directly, sharpening `clause` from
`"Annex E"` to `"E.1"` and `"E.2"`; the required inventory registers each table as its own item
with its own consumer issue. Two regression guards that fail for independent reasons: the
recipe guard pins identifier + `source_table` + `clause` together and refuses any suffixed
member, and the inventory guard states both tables' requirement independently of the recipe.

**Tech Stack:** Python 3.13, Pydantic 2 frozen models, pytest (+ pytest-xdist), mypy strict,
ruff, uv.

**Spec:** `docs/superpowers/specs/2026-08-11-issue-52-annex-e-semantic-id-split-design.md`

## Global Constraints

- Public repository. No value, table heading, note or clause wording from an IEC document may
  enter any committed file. Permitted: page, figure and clause numbers, row and column
  indexes, bounding boxes, table identifiers, and the document's own identity strings.
- Neutral semantic descriptions such as "clearance correction" and "test-voltage correction"
  are permitted; nothing beyond what Issue #52's public text already states.
- `uv` is not on PATH. Prefix every command with:
  `$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"`
- Qt tests need `$env:QT_QPA_PLATFORM = "offscreen"` (set it for full-suite runs).
- Private licensed-document tests skip without the PDFs. Never report a private-suite result
  that was not actually produced by a run. The maintainer runs them.
- Coverage floor is 80%.
- Do not touch the two footnote-marker allowlists (out of scope, see spec).
- Do not implement anything from #53, #36 or #37. Do not wire a runtime consumer.
- Do not rename the `table-e1` / `table-e2` segment ids.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## Why Task 1 is one task

The contract change is atomic: the suite cannot be green in between its halves. Adding
`ALTITUDE_CLEARANCE_CORRECTION` to `REQUIRED_SEMANTIC_IDS` without the matching inventory item
fails `test_inventory_covers_every_required_id_exactly_once`, and splitting the inventory
without re-pointing the recipe fails `test_every_item_this_build_does_not_defer_has_a_recipe`.
So Task 1 carries the identifier, the recipe, the inventory, the guards and the counts
together, and its test cycle is run once at the end of the task rather than per file.

## File Structure

Source, all under `src/insulation_coordination/rules/importer/`:

- `iec62477_2022/semantic_ids.py` — add one constant, add it to `REQUIRED_SEMANTIC_IDS`.
- `iec62477_2022/inventory.py` — one required item becomes two.
- `recipes/iec62477_1_2022/tables.py` — two `semantic_id` and two `clause` values.
- `recipes/iec62477_1_2022/procedures.py` — one stale count in a comment (Task 2).

Tests:

- `tests/rules/importer/iec62477_2022/test_recipe_shape.py` — replace the family test, fix an
  E.2 lookup.
- `tests/rules/importer/iec62477_2022/test_inventory.py` — new inventory guard (Task 1),
  stale count in a docstring (Task 2).
- `tests/rules/importer/iec62477_2022/test_semantic_ids.py` — count and test name.
- `tests/rules/importer/iec62477_2022/test_slice_e2_integration.py` — count (Task 1), two
  stale counts in docstrings (Task 2).
- `tests/private/test_iec62477_numeric_tables.py` — two grid ids.
- `tests/private/test_iec62477_end_to_end.py` — count (Task 1), stale count in the module
  docstring (Task 2).

---

### Task 1: The identifier split, its guards and its counts

**Files:**
- Modify: `src/insulation_coordination/rules/importer/iec62477_2022/semantic_ids.py:23-26`, `:54`
- Modify: `src/insulation_coordination/rules/importer/iec62477_2022/inventory.py:75-77`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py:376`, `:380`, `:418`, `:422`
- Test: `tests/rules/importer/iec62477_2022/test_recipe_shape.py:100-106`, `:127-131`
- Test: `tests/rules/importer/iec62477_2022/test_inventory.py` (imports + new test at end)
- Test: `tests/rules/importer/iec62477_2022/test_semantic_ids.py:4-5`
- Test: `tests/rules/importer/iec62477_2022/test_slice_e2_integration.py:36`
- Test: `tests/private/test_iec62477_numeric_tables.py:45-46`
- Test: `tests/private/test_iec62477_end_to_end.py:109`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `insulation_coordination.rules.importer.iec62477_2022.semantic_ids.ALTITUDE_CLEARANCE_CORRECTION: str`, value `"iec62477_2022.altitude.clearance_correction"`, and a member of `REQUIRED_SEMANTIC_IDS`. The existing `ALTITUDE_TEST_VOLTAGE_CORRECTION` keeps its value and is now the identifier of Table E.2 alone. Both are emitted bare — no `.e1` / `.e2` suffix exists after this task.

- [ ] **Step 1: Write the failing recipe guard**

In `tests/rules/importer/iec62477_2022/test_recipe_shape.py`, replace
`test_altitude_tables_share_one_semantic_family` (lines 100-106) entirely with:

```python
def test_each_annex_e_table_owns_its_own_semantic_id() -> None:
    """Annex E's two tables do two different jobs, so each owns an identifier.

    E.1 gives an altitude correction factor for dimensioning clearances; E.2 gives test
    voltages corrected for the altitude of the testing laboratory. Pinning each identifier
    together with the table and subclause it reads is what stops a future edit from
    re-nesting one table under the other's family, which is the defect #52 removed.
    """
    e1 = next(
        spec for spec in RECIPE.tables if spec.semantic_id == ids.ALTITUDE_CLEARANCE_CORRECTION
    )
    e2 = next(
        spec for spec in RECIPE.tables if spec.semantic_id == ids.ALTITUDE_TEST_VOLTAGE_CORRECTION
    )

    assert e1.source_table == "E.1"
    assert e1.clause == "E.1"

    assert e2.source_table == "E.2"
    assert e2.clause == "E.2"

    altitude = [
        spec for spec in RECIPE.tables if spec.semantic_id.startswith("iec62477_2022.altitude.")
    ]
    assert [spec.semantic_id for spec in altitude] == [
        ids.ALTITUDE_CLEARANCE_CORRECTION,
        ids.ALTITUDE_TEST_VOLTAGE_CORRECTION,
    ]
```

The last assertion is the guard: it pins the emitted identifier set and the document order,
so both a suffixed member and a third altitude spec fail it.

- [ ] **Step 2: Fix the E.2 lookup in the same file**

In `test_no_column_hardcodes_a_licensed_axis_value`, lines 127-131 currently read:

```python
    altitude_e2 = next(
        spec
        for spec in RECIPE.tables
        if spec.semantic_id == f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e2"
    )
```

Replace with:

```python
altitude_e2 = next(
    spec for spec in RECIPE.tables if spec.semantic_id == ids.ALTITUDE_TEST_VOLTAGE_CORRECTION
)
```

- [ ] **Step 3: Write the failing inventory guard**

In `tests/rules/importer/iec62477_2022/test_inventory.py`, extend the second import block
(lines 5-8) to:

```python
from insulation_coordination.rules.importer.iec62477_2022.semantic_ids import (
    ALTITUDE_CLEARANCE_CORRECTION,
    ALTITUDE_TEST_VOLTAGE_CORRECTION,
    DVC_FAULT_TIME_VOLTAGE,
    REQUIRED_SEMANTIC_IDS,
)
```

and append this test at the end of the file:

```python
def test_annex_e_tables_are_two_required_items_with_their_own_consumers() -> None:
    """Each Annex E table is required in its own right, independently of the recipe.

    E.1 feeds clearance dimensioning in #36; E.2 feeds verification in #37. Stated here
    rather than derived from the specs, because that is the hole the single parent item left:
    had one table's recipe been removed, ``_covers`` would have matched the parent through
    the surviving route and the checklist could still have reported complete.
    """
    items = {
        item.semantic_id: item
        for item in REQUIRED_SOURCE_ITEMS
        if item.semantic_id.startswith("iec62477_2022.altitude.")
    }

    assert set(items) == {ALTITUDE_CLEARANCE_CORRECTION, ALTITUDE_TEST_VOLTAGE_CORRECTION}
    assert items[ALTITUDE_CLEARANCE_CORRECTION].expected_table == "Table E.1"
    assert items[ALTITUDE_CLEARANCE_CORRECTION].consumer_issue_ids == (36,)
    assert items[ALTITUDE_TEST_VOLTAGE_CORRECTION].expected_table == "Table E.2"
    assert items[ALTITUDE_TEST_VOLTAGE_CORRECTION].consumer_issue_ids == (37,)
```

- [ ] **Step 4: Update the three numeric counts**

`tests/rules/importer/iec62477_2022/test_semantic_ids.py`, lines 4-5 — rename the test with
its count, since the name states the number:

```python
def test_catalog_has_twenty_six_unique_ids() -> None:
    assert len(semantic_ids.REQUIRED_SEMANTIC_IDS) == 26
```

`tests/rules/importer/iec62477_2022/test_slice_e2_integration.py`, line 36:

```python
    assert len(REQUIRED_SOURCE_ITEMS) == 26
```

`tests/private/test_iec62477_end_to_end.py`, line 109:

```python
    assert len(REQUIRED_SOURCE_ITEMS) == 26
```

- [ ] **Step 5: Run the public tests to verify they fail**

Run:

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_recipe_shape.py tests/rules/importer/iec62477_2022/test_inventory.py tests/rules/importer/iec62477_2022/test_semantic_ids.py -q
```

Expected: FAIL. `test_recipe_shape.py` and `test_inventory.py` raise
`AttributeError: module 'insulation_coordination.rules.importer.iec62477_2022.semantic_ids' has
no attribute 'ALTITUDE_CLEARANCE_CORRECTION'` (an ImportError at collection for
`test_inventory.py`), and `test_catalog_has_twenty_six_unique_ids` fails
`assert 25 == 26`.

- [ ] **Step 6: Add the identifier**

In `src/insulation_coordination/rules/importer/iec62477_2022/semantic_ids.py`, lines 23-26
currently read:

```python
CLEARANCE_REQUIREMENTS = "iec62477_2022.clearance.requirements"
CREEPAGE_REQUIREMENTS = "iec62477_2022.creepage.requirements"
ALTITUDE_TEST_VOLTAGE_CORRECTION = "iec62477_2022.altitude.test_voltage_correction"
HIGH_FREQUENCY_APPLICABILITY = "iec62477_2022.high_frequency.applicability"
```

Replace with:

```python
CLEARANCE_REQUIREMENTS = "iec62477_2022.clearance.requirements"
CREEPAGE_REQUIREMENTS = "iec62477_2022.creepage.requirements"
#: Annex E's two tables do two different jobs and get one identifier each (#52): E.1's factor
#: corrects clearances for dimensioning, E.2's values correct test voltages for the altitude
#: of the testing laboratory. Neither is a route of the other, so neither carries a suffix.
ALTITUDE_CLEARANCE_CORRECTION = "iec62477_2022.altitude.clearance_correction"
ALTITUDE_TEST_VOLTAGE_CORRECTION = "iec62477_2022.altitude.test_voltage_correction"
HIGH_FREQUENCY_APPLICABILITY = "iec62477_2022.high_frequency.applicability"
```

Then, in `REQUIRED_SEMANTIC_IDS`, insert the new member immediately above the existing one
(line 54 becomes two lines):

```python
(ALTITUDE_CLEARANCE_CORRECTION,)
(ALTITUDE_TEST_VOLTAGE_CORRECTION,)
```

- [ ] **Step 7: Split the inventory item**

In `src/insulation_coordination/rules/importer/iec62477_2022/inventory.py`, lines 75-77
currently read:

```python
(_item(ids.ALTITUDE_TEST_VOLTAGE_CORRECTION, "table", (36, 37), table="Table E.1"),)
```

Replace with:

```python
(_item(ids.ALTITUDE_CLEARANCE_CORRECTION, "table", (36,), table="Table E.1"),)
(_item(ids.ALTITUDE_TEST_VOLTAGE_CORRECTION, "table", (37,), table="Table E.2"),)
```

Neither item gets `clause=`: table-backed items name their table, and the subclause lives in
the recipe spec where extraction reads it.

- [ ] **Step 8: Re-point the two recipe specs**

In `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py`, the first
Annex E spec (line 376 and line 380) currently reads:

```python
semantic_id = (f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e1",)
source_table = ("E.1",)
title_anchor = ("Table E.1",)
page_number = (193,)
clause = ("Annex E",)
```

Replace those with:

```python
semantic_id = (ids.ALTITUDE_CLEARANCE_CORRECTION,)
source_table = ("E.1",)
title_anchor = ("Table E.1",)
page_number = (193,)
clause = ("E.1",)
```

The second Annex E spec (line 418 and line 422) currently reads:

```python
semantic_id = (f"{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e2",)
source_table = ("E.2",)
title_anchor = ("Table E.2",)
page_number = (194,)
clause = ("Annex E",)
```

Replace those with:

```python
semantic_id = (ids.ALTITUDE_TEST_VOLTAGE_CORRECTION,)
source_table = ("E.2",)
title_anchor = ("Table E.2",)
page_number = (194,)
clause = ("E.2",)
```

Change nothing else in either spec: the bboxes, segments, row and column axes, data columns,
assertions and `_altitude_band_columns()` all stay exactly as they are. `spec.clause` is only
ever copied into provenance (`clause=spec.clause` in `extract.py`), never branched on, so
sharpening it cannot change what is extracted.

- [ ] **Step 9: Update the two private grid ids**

In `tests/private/test_iec62477_numeric_tables.py`, lines 45-46 currently read:

```python
    assert f"raw-{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e1" in grid_ids
    assert f"raw-{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}.e2" in grid_ids
```

Replace with:

```python
    assert f"raw-{ids.ALTITUDE_CLEARANCE_CORRECTION}" in grid_ids
    assert f"raw-{ids.ALTITUDE_TEST_VOLTAGE_CORRECTION}" in grid_ids
```

- [ ] **Step 10: Run the public tests to verify they pass**

Run:

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/ -q
```

Expected: PASS, no failures. This directory covers the recipe guard, the inventory guard, the
counts, the slice-closure tests and the recipe shape tests.

- [ ] **Step 11: Confirm the private suite still collects**

Run:

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest -m private_standard -q
```

Expected: all tests skipped (no licensed standards directory on this machine), zero collection
errors. A collection error here means a name in a private test does not exist; skips mean the
edits are syntactically and referentially sound. Record the skip count. Do not describe this
as the private suite passing.

- [ ] **Step 12: Run ruff and mypy**

Run:

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run ruff check .
```

Expected: `All checks passed!`

Run:

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run mypy
```

Expected: `Success: no issues found in 80 source files`. Run `mypy` with no arguments:
`pyproject.toml` scopes strict checking to the `insulation_coordination` package, and naming
`tests` explicitly instead surfaces hundreds of pre-existing untyped-test errors that have
nothing to do with this change. CI runs `uv run mypy`.

- [ ] **Step 13: Commit**

```bash
git add src/insulation_coordination/rules/importer/iec62477_2022/semantic_ids.py src/insulation_coordination/rules/importer/iec62477_2022/inventory.py src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py tests/rules/importer/iec62477_2022/test_recipe_shape.py tests/rules/importer/iec62477_2022/test_inventory.py tests/rules/importer/iec62477_2022/test_semantic_ids.py tests/rules/importer/iec62477_2022/test_slice_e2_integration.py tests/private/test_iec62477_numeric_tables.py tests/private/test_iec62477_end_to_end.py
```

Commit with this message:

```text
fix(rules): give each Annex E table its own semantic id (#52)

Both Annex E grids hung off iec62477_2022.altitude.test_voltage_correction,
as .e1 and .e2. Table E.1 does not correct test voltages: it gives an
altitude correction factor for dimensioning clearances. A consumer resolving
that identifier on the strength of its name would apply a clearance factor to
a test voltage.

E.1 now has iec62477_2022.altitude.clearance_correction and E.2 keeps the
test-voltage identifier. Both are emitted bare: after the split neither is a
route of the other, so a suffix would describe a family of one. The required
inventory registers each table separately, with E.1 on #36 and E.2 on #37, so
each table's requirement is a statement of the checklist rather than a
consequence of the recipe still declaring both routes.

Two guards fail for independent reasons: the recipe guard pins each identifier
with its source table and subclause and refuses any suffixed member, and the
inventory guard states both requirements without reading the recipe.

The identifiers, and therefore the raw grid ids, change: an approved package
carrying the suffixed ids no longer loads, and stored review resolutions for
both grids no longer match. Rebuild, re-review, re-approve. No source region,
bbox, segment or extraction strategy moves.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 2: Retire the stale "twenty-five"

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/procedures.py:53`
- Modify: `tests/rules/importer/iec62477_2022/test_inventory.py:68`
- Modify: `tests/rules/importer/iec62477_2022/test_slice_e2_integration.py:2`, `:33`
- Modify: `tests/private/test_iec62477_end_to_end.py:4`

**Interfaces:**
- Consumes: Task 1's `ALTITUDE_CLEARANCE_CORRECTION`, which made the required inventory
  twenty-six items.
- Produces: nothing. Documentation only; no behaviour changes.

The count is stated in prose in five more places. Left alone, each one tells the next reader
the checklist has twenty-five items.

- [ ] **Step 1: Enumerate what is left**

Search the tree:

```bash
grep -rni "twenty-five\|twenty_five" --include=*.py src tests
```

Expected: exactly five hits — `procedures.py:53`, `test_inventory.py:68`,
`test_slice_e2_integration.py:2` and `:33`, `test_iec62477_end_to_end.py:4`. (Task 1 already
renamed the sixth, `test_catalog_has_twenty_five_unique_ids`.) If a hit appears that is not in
this list, fix it too and note it in the task report.

- [ ] **Step 2: Update the source comment**

`src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/procedures.py:53` currently
reads:

```python
#: The matrix is evidence for the procedures, not one of the twenty-five required source
```

Replace that line with:

```python
#: The matrix is evidence for the procedures, not one of the twenty-six required source
```

- [ ] **Step 3: Update the four test docstrings**

`tests/rules/importer/iec62477_2022/test_inventory.py:68`, inside
`test_every_item_this_build_does_not_defer_has_a_recipe`:

```python
    this covers all twenty-six.
```

`tests/rules/importer/iec62477_2022/test_slice_e2_integration.py:2`, in the module docstring:

```python
Rules Manager reports all twenty-six of them.
```

`tests/rules/importer/iec62477_2022/test_slice_e2_integration.py:33`, in
`test_the_deferred_set_is_empty_and_every_item_has_a_recipe`:

```python
    twenty-six items is declared by a spec, under its own identifier or one of its routes.
```

`tests/private/test_iec62477_end_to_end.py:4`, in the module docstring:

```python
export a ``.icrules`` archive, re-import it, query all twenty-six required semantic IDs,
```

- [ ] **Step 4: Verify nothing stale survives**

```bash
grep -rni "twenty-five\|twenty_five" --include=*.py src tests
```

Expected: no output.

- [ ] **Step 5: Run ruff and the affected tests**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run ruff check .
```

Expected: `All checks passed!` (`procedures.py` is source, so a malformed comment would show
here.)

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/ -q
```

Expected: PASS, no failures.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/procedures.py tests/rules/importer/iec62477_2022/test_inventory.py tests/rules/importer/iec62477_2022/test_slice_e2_integration.py tests/private/test_iec62477_end_to_end.py
```

Commit with this message:

```text
docs: the required inventory is twenty-six items (#52)

Five comments and docstrings still spelled the count as twenty-five, in one
source comment and four test docstrings. Documentation only.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

### Task 3: Gates, licensed-content audit, and the pull request

**Files:** none modified. This task verifies and publishes.

**Interfaces:**
- Consumes: Tasks 1 and 2, committed.
- Produces: a pull request against `main` closing #52.

- [ ] **Step 1: Run the full suite with coverage**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; $env:QT_QPA_PLATFORM = "offscreen"; uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing -q
```

Expected: 0 failed, and a "Required test coverage of 80.0% reached" line. Record the passed
and skipped counts and the total coverage. Coverage flags are not in addopts, so they must be
passed explicitly, exactly as CI does. If anything fails, stop and report; do not open a PR on
a red suite.

- [ ] **Step 2: Re-run ruff and mypy at the final head**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run ruff check .
```

Expected: `All checks passed!`

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run mypy
```

Expected: `Success: no issues found in 80 source files`. Run `mypy` with no arguments:
`pyproject.toml` scopes strict checking to the `insulation_coordination` package, and naming
`tests` explicitly instead surfaces hundreds of pre-existing untyped-test errors that have
nothing to do with this change. CI runs `uv run mypy`.

- [ ] **Step 3: Audit the whole diff for licensed content**

```bash
git diff origin/main --unified=0
```

Read every added line. Confirm the diff contains only identifiers, table and subclause
locators (`E.1`, `E.2`, `Table E.1`, `Table E.2`), issue numbers, counts, and neutral semantic
descriptions. Confirm no numeric table value, column heading, note or clause wording from the
document appears anywhere, including in commit messages and the plan and spec documents. If
anything fails this audit, remove it before pushing — a public push is not reversible.

- [ ] **Step 4: Record the private-suite skip result**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest -m private_standard -q
```

Expected: all skipped, zero collection errors. Record the number. This is evidence that the
private edits reference real names, and nothing more. The PR body must say the private suite
has not run.

- [ ] **Step 5: Push the branch**

```bash
git push -u origin worktree-issue-52-annex-e-ids
```

- [ ] **Step 6: Open the pull request**

Write the body to a file first (it is long, and heredocs are refused in this worktree), then:

```bash
gh pr create --base main --title "fix(rules): give each Annex E table its own semantic id (#52)" --body-file <path to the body file>
```

The body must contain, in this order:

1. `Closes #52.`
2. What changes: the two bare identifiers, the recipe re-point and clause sharpening, the two
   inventory items with `(36,)` and `(37,)`, and the two independent regression guards.
3. Contract impact: an approved package carrying the suffixed ids no longer loads, because
   trusted-package validation requires the package's table-id set to equal the set derived
   from the current recipes. Rebuild, re-review, re-approve. No alias, no migration.
4. Review-state impact, both mechanisms: `ImportReviewItem.sha256` covers `semantic_id`, so
   the review item itself differs; and `_review_resolution_exists` matches a `kind="table"`
   item only against a rebuilt grid whose id is exactly `raw-{semantic_id}`. This includes
   E.2, whose engineering meaning did not change. No source-region re-selection: bboxes,
   segments and extraction strategy are untouched.
5. Verification: the gate results from Steps 1 and 2, with real numbers.
6. A section headed so it cannot be missed, stating that the private licensed-document suite
   has **not** run, that this PR must not merge until it has, and giving the command:
   `$env:ICC_PRIVATE_STANDARDS_DIR = "<directory holding the licensed PDFs>"; uv run pytest -m private_standard -q`
   Name the two private tests the run exercises: the altitude grid ids in
   `test_iec62477_numeric_tables.py` and the twenty-six-item count in
   `test_iec62477_end_to_end.py`.
7. That #52's footnote-marker allowlists are deliberately out of scope, and that nothing from
   #53, #36 or #37 is implemented here.

- [ ] **Step 7: Confirm the PR head**

```bash
gh pr view --json number,headRefOid,mergeable,url
```

Expected: `headRefOid` equal to the local `HEAD`, and `mergeable` not `CONFLICTING`. Report the
PR number and URL.

---

## Self-Review

**Spec coverage.** The contract section maps to Task 1 Steps 6-7; the recipe section to Step 8;
the inventory section to Step 7; both regression guards to Steps 1 and 3; the numeric counts to
Step 4 and the prose counts to Task 2; the private guards to Step 9; the package and review
consequences to Task 3 Step 6 items 3 and 4, since they are statements the PR must carry rather
than code; verification to Task 3 Steps 1, 2 and 4; the public-record limit to Task 3 Step 3;
and out of scope to Task 3 Step 6 item 7 and the Global Constraints.

**Placeholders.** Every code step carries the exact replacement text. The one deliberate
placeholder is `<path to the body file>` in Task 3 Step 6, which is a local scratch path the
implementer chooses, with the body's required contents enumerated immediately below it.

**Type consistency.** `ALTITUDE_CLEARANCE_CORRECTION` and `ALTITUDE_TEST_VOLTAGE_CORRECTION`
are spelled identically in every task. Task 1 refers to them as `ids.*` inside recipe and
inventory modules, which import `semantic_ids as ids`, and as bare names inside
`test_inventory.py`, which imports the names directly — matching each file's existing import
style. `expected_table` and `consumer_issue_ids` are the real `RequiredSourceItem` field names;
`source_table` and `clause` are the real `TableAuditSpec` field names.
