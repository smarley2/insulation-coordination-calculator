# Project Defaults and Net-Class UI Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make impulse voltage, pollution degree, and material group project defaults constrained dropdowns and verify that the visible Add button creates a net class through its dialog flow.

**Architecture:** Keep `ProjectDefaults` and persistence unchanged. Add UI-owned option tables and combo-box conversion helpers in `ProjectPage`; combo item data carries the existing stored types (`Decimal` volts, `int`, and `str`). Extend the existing Qt UI test module with direct selection assertions and an event-driven test of `_add_button` plus `QInputDialog`.

**Tech Stack:** Python 3.12, PySide6, pytest-qt, Pydantic models, uv.

## Global Constraints

- Keep the project PCB-only pollution choices to `1` and `2`.
- Use impulse options represented by IEC F.2: `0.33, 0.40, 0.50, 0.60, 0.80, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10, 12, 15, 20, 25, 30, 40, 50, 60, 80, 100 kV`.
- Keep an empty first option for unset defaults.
- Store impulse selections as volts (`Decimal`), not display strings.
- Preserve a loaded legacy value by adding it as a marked compatibility item instead of silently changing it.
- Do not add dependencies or change the domain schema.
- Use test-first red-green verification for every behavior change.

---

### Task 1: Add failing UI coverage for constrained defaults and Add button

**Files:**
- Modify: `tests/ui/test_project_pages.py`

**Interfaces:**
- Consumes: `ProjectPage._impulse_combo`, `ProjectPage._pollution_combo`, `ProjectPage._cti_combo`, and `_add_button` after the production implementation exposes them.
- Produces: Regression tests specifying combo contents, stored values, blank clearing, and the actual Add dialog path.

- [ ] **Step 1: Add a test for exact constrained combo contents**

```python
def test_project_default_dropdown_choices(qtbot, qtbot_project):
    page = qtbot_project
    assert [page._impulse_combo.itemText(i) for i in range(page._impulse_combo.count())] == [
        "",
        "0.33 kV",
        "0.40 kV",
        "0.50 kV",
        "0.60 kV",
        "0.80 kV",
        "1.0 kV",
        "1.2 kV",
        "1.5 kV",
        "2.0 kV",
        "2.5 kV",
        "3.0 kV",
        "4.0 kV",
        "5.0 kV",
        "6.0 kV",
        "8.0 kV",
        "10 kV",
        "12 kV",
        "15 kV",
        "20 kV",
        "25 kV",
        "30 kV",
        "40 kV",
        "50 kV",
        "60 kV",
        "80 kV",
        "100 kV",
    ]
    assert [page._pollution_combo.itemText(i) for i in range(page._pollution_combo.count())] == ["", "1", "2"]
    assert [page._cti_combo.itemText(i) for i in range(page._cti_combo.count())] == ["", "I", "II", "IIIa", "IIIb"]
```

- [ ] **Step 2: Add a test for selection storage and blank clearing**

```python
def test_project_default_dropdowns_update_existing_model(qtbot, qtbot_project):
    page = qtbot_project
    page._impulse_combo.setCurrentText("2.5 kV")
    page._pollution_combo.setCurrentText("2")
    page._cti_combo.setCurrentText("IIIa")
    assert page.project.defaults.impulse_v == Decimal("2500")
    assert page.project.defaults.pollution_degree == 2
    assert page.project.defaults.cti_or_material_group == "IIIa"
    page._impulse_combo.setCurrentIndex(0)
    page._pollution_combo.setCurrentIndex(0)
    page._cti_combo.setCurrentIndex(0)
    assert page.project.defaults.impulse_v is None
    assert page.project.defaults.pollution_degree is None
    assert page.project.defaults.cti_or_material_group is None
```

- [ ] **Step 3: Add a test for the actual Add button/dialog path**

```python
def test_add_button_adds_net_class_through_dialog(qtbot, qtbot_project):
    page = qtbot_project

    def accept_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert dialog is not None
        dialog.setTextValue("HV+")
        dialog.accept()

    QTimer.singleShot(0, accept_dialog)
    qtbot.mouseClick(page._add_button, Qt.MouseButton.LeftButton)
    assert page.project.net_class_names == ("HV+",)
    assert page._net_list.count() == 1
```

Add the `QTimer`, `Qt`, and `QApplication` imports required by the test. Keep the existing direct `add_net_class()` tests because they cover domain reconciliation separately from the button wiring.

- [ ] **Step 4: Run only the new tests and confirm they fail for missing combo widgets/behavior**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui/test_project_pages.py -k 'dropdown or add_button'`

Expected: FAIL because the current implementation exposes line edits rather than the requested combo boxes; the Add test must either pass (proving the reported bug is not reproducible in the Qt harness) or fail with a concrete dialog/event error to guide the fix.

### Task 2: Implement constrained ProjectPage defaults and compatibility loading

**Files:**
- Modify: `src/insulation_coordination/ui/project_pages.py`

**Interfaces:**
- Consumes: `ProjectDefaults` fields and the option values defined in the task constraints.
- Produces: `_impulse_combo`, `_pollution_combo`, and `_cti_combo` non-editable controls; combo selection updates that write the existing domain types; legacy-value preservation on load.

- [ ] **Step 1: Define the UI option data beside the ProjectPage class**

Use tuples of `(display_text, value)` where impulse values are `Decimal` volts:

```python
_IMPULSE_OPTIONS = (
    ("0.33 kV", Decimal("330")),
    ("0.40 kV", Decimal("400")),
    ("0.50 kV", Decimal("500")),
    ("0.60 kV", Decimal("600")),
    ("0.80 kV", Decimal("800")),
    ("1.0 kV", Decimal("1000")),
    ("1.2 kV", Decimal("1200")),
    ("1.5 kV", Decimal("1500")),
    ("2.0 kV", Decimal("2000")),
    ("2.5 kV", Decimal("2500")),
    ("3.0 kV", Decimal("3000")),
    ("4.0 kV", Decimal("4000")),
    ("5.0 kV", Decimal("5000")),
    ("6.0 kV", Decimal("6000")),
    ("8.0 kV", Decimal("8000")),
    ("10 kV", Decimal("10000")),
    ("12 kV", Decimal("12000")),
    ("15 kV", Decimal("15000")),
    ("20 kV", Decimal("20000")),
    ("25 kV", Decimal("25000")),
    ("30 kV", Decimal("30000")),
    ("40 kV", Decimal("40000")),
    ("50 kV", Decimal("50000")),
    ("60 kV", Decimal("60000")),
    ("80 kV", Decimal("80000")),
    ("100 kV", Decimal("100000")),
)
_POLLUTION_OPTIONS = (("1", 1), ("2", 2))
_MATERIAL_OPTIONS = (("I", "I"), ("II", "II"), ("IIIa", "IIIa"), ("IIIb", "IIIb"))
```

Import `Decimal` at module scope. Do not introduce a new domain enum solely for these UI values.

- [ ] **Step 2: Replace the three line edits with non-editable combo boxes**

Create each combo with `addItem("", None)`, then add its option text and typed data. Connect `currentIndexChanged` to a helper that reads `combo.itemData(index)` and writes `None` or the typed value through `ProjectDefaults.model_validate()`.

- [ ] **Step 3: Load and restore values without emitting changes**

Block signals while loading. Select by `findData(default_value)`. If a non-`None` loaded value is not in the approved options, append a compatibility item such as `"3 (legacy)"` or `"2.5 kV (legacy)"` with the original typed value, then select it. This preserves old projects while keeping all newly entered values constrained.

- [ ] **Step 4: Remove the obsolete handlers only for these fields**

Delete `_on_impulse_changed`, `_on_pollution_changed`, and `_on_cti_changed` plus their free-text conversion branches. Keep frequency and altitude line-edit parsing unchanged. Keep the existing enum combo handlers unchanged.

- [ ] **Step 5: Run the new tests and verify green**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui/test_project_pages.py -k 'dropdown or add_button'`

Expected: PASS, with the Add test outcome matching the actual dialog path. If the Add test failed in Task 1, make only the UI-boundary correction needed for that failure.

### Task 3: Verify the full project workflow and desktop UI

**Files:**
- Modify: none unless a test exposes an implementation defect.

**Interfaces:**
- Consumes: the completed `ProjectPage` implementation and test coverage.
- Produces: fresh automated and live UI evidence.

- [ ] **Step 1: Run the full project-page UI tests**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui/test_project_pages.py`

Expected: all tests pass.

- [ ] **Step 2: Run the full automated suite**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -q`

Expected: zero failures; private-standard tests may remain skipped according to repository configuration.

- [ ] **Step 3: Run lint and type checks**

Run: `uv run ruff check . && uv run mypy`

Expected: exit code 0 from both commands.

- [ ] **Step 4: Launch the desktop UI for manual acceptance**

Run: `QT_QPA_PLATFORM=offscreen uv run icc --gui` in an environment with a display if needed. Open/create a project, inspect all three dropdowns, select values and verify the project changes, then click Add, enter `HV+`, accept, and verify `HV+` appears in Net classes.

- [ ] **Step 5: Review the diff and commit the implementation**

Run: `git diff --check && git status --short && git diff -- src/insulation_coordination/ui/project_pages.py tests/ui/test_project_pages.py`

Then commit with:

```bash
git add src/insulation_coordination/ui/project_pages.py tests/ui/test_project_pages.py
git commit -m "fix: constrain project defaults and netclass add UI"
```
