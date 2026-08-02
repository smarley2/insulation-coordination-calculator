# Pairs Page Matrix Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Pairs page responsive and allow each Coverage Matrix cell to display and edit pair-specific voltages and defaultable parameter overrides.

**Architecture:** Keep `Project`, `PairCase`, `ProjectDefaults`, persistence, and calculation behavior unchanged. Extend `CoverageMatrixModel` with a selected display parameter and effective-value formatting, pass project defaults into `PairEditor`, and rearrange `PairPage` into a splitter-based layout with a scrollable editor. Use existing `resolve_effective_case()` for all default/override display and provenance.

**Tech Stack:** Python 3.12+, PySide6, Pydantic models already in the repository, pytest-qt, Ruff, mypy.

## Global Constraints

- Do not change the `.icproj` schema or domain model.
- Do not add dependencies.
- Voltages remain explicit per-pair `PairVoltages` values; only existing defaultable PairEditor fields use overrides.
- The conventional-construction-assumptions field remains out of scope because it is not exposed in the desktop editor.
- Preserve canonical mirrored-pair behavior: both matrix halves resolve to the same `PairCase`.
- Write the failing test before each production-code behavior change and run it to confirm the expected failure.
- Keep existing tests and public helper methods working unless the plan explicitly extends them.

---

## File map

- Modify: `src/insulation_coordination/ui/pair_models.py` — selected matrix parameter, effective-value rendering, and display labels.
- Modify: `src/insulation_coordination/ui/pair_editor.py` — inherited-default loading, all exposed default/override controls, and responsive Pairs page layout.
- Modify: `tests/ui/test_pair_workflow.py` — matrix parameter, cell selection, default/override, and layout regression tests.
- Modify: `tests/ui/test_pair_editor_fields.py` — inherited-value and reset behavior tests.

## Task 1: Add failing regression tests for matrix values and inherited overrides

**Files:**
- Modify: `tests/ui/test_pair_workflow.py`
- Modify: `tests/ui/test_pair_editor_fields.py`

**Interfaces:**
- Consumes: current `PairPage`, `CoverageMatrixModel`, and `PairEditor` behavior.
- Produces: tests that define the new public behavior before implementation.

- [ ] **Step 1: Add a project fixture default impulse and a matrix parameter test**

Extend `_make_project()` in `tests/ui/test_pair_workflow.py` with `impulse_v=Decimal(1200)` and add:

```python
def test_matrix_parameter_displays_pair_voltage(qtbot, pair_page):
    pair = pair_page.project.pairs[0]
    pair_page.select_pair_by_id(str(pair.id))
    pair_page.editor.set_long_term_rms("500 V")
    pair_page._matrix_parameter_combo.setCurrentText("Long-term RMS voltage")

    index = pair_page.matrix_model.index(0, 1)
    assert pair_page.matrix_model.data(index) == "500 V"
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(1, 0)) == "500 V"
```

- [ ] **Step 2: Add default/override matrix rendering tests**

Add:

```python
def test_matrix_parameter_displays_default_and_pair_override(qtbot, pair_page):
    pair = pair_page.project.pairs[0]
    pair_page._matrix_parameter_combo.setCurrentText("Frequency")
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == "50 Hz (D)"

    pair_page.select_pair_by_id(str(pair.id))
    pair_page.editor.set_frequency_override("100 kHz")
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == "100000 Hz (O)"

    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 2)) == "50 Hz (D)"
```

- [ ] **Step 3: Add the cell-selection and inherited-editor tests**

Add:

```python
def test_clicking_matrix_cell_loads_pair_editor(qtbot, pair_page):
    pair_page._on_matrix_clicked(pair_page.matrix_model.index(1, 0))
    assert pair_page.editor.pair is pair_page.project.pairs[0]


def test_pair_editor_shows_inherited_default_values(qtbot, pair_page):
    pair_page.select_pair_by_id(str(pair_page.project.pairs[0].id))
    assert pair_page.editor._freq_edit.text() == "50"
    assert pair_page.editor._freq_source_label.text() == "Default"
    assert pair_page.editor._impulse_edit.text() == "1200"
    assert pair_page.editor._impulse_source_label.text() == "Default"
```

- [ ] **Step 4: Add pair-local reset coverage for representative and enum fields**

In `tests/ui/test_pair_editor_fields.py`, load the editor with `editor.load_pair(project.pairs[0], project.defaults)`, set a frequency and insulation override, clear both, and assert the stored `OverrideValue` objects inherit and the displayed values return to the project defaults:

```python
def test_clear_defaultable_overrides_returns_to_project_defaults(qtbot):
    from insulation_coordination.ui.pair_editor import PairEditor

    project = _make_project().model_copy(
        update={"defaults": ProjectDefaults(frequency_hz=Decimal(50), insulation_type="basic")}
    )
    editor = PairEditor()
    editor.load_pair(project.pairs[0], project.defaults)
    qtbot.addWidget(editor)

    editor.set_frequency_override("100 kHz")
    editor.set_insulation_override(InsulationType.REINFORCED)
    editor.clear_frequency_override()
    editor.clear_insulation_override()

    assert editor.pair is not None
    assert not editor.pair.frequency_hz.is_override
    assert not editor.pair.insulation_type.is_override
    assert editor._freq_edit.text() == "50"
    assert editor._insulation_combo.currentText() == "basic"
```

Import `InsulationType` in the test module if it is not already imported.

- [ ] **Step 5: Run the new tests and verify they fail for the missing feature**

Run:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui/test_pair_workflow.py tests/ui/test_pair_editor_fields.py -k 'matrix_parameter or matrix_displays or clicking_matrix or inherited_default or clear_defaultable'
```

Expected: FAIL with missing `_matrix_parameter_combo`, missing parameter display behavior, and/or the current `load_pair()` signature not accepting defaults. Do not change production code until the failure is attributable to the requested behavior.

- [ ] **Step 6: Commit the failing tests**

```bash
git add tests/ui/test_pair_workflow.py tests/ui/test_pair_editor_fields.py
git commit -m "test: specify pair matrix parameter editing"
```

## Task 2: Implement parameter-aware CoverageMatrixModel

**Files:**
- Modify: `src/insulation_coordination/ui/pair_models.py`

**Interfaces:**
- Consumes: `Project`, `PairCase`, `resolve_effective_case()`, and existing canonical pair lookup.
- Produces: `MATRIX_PARAMETERS`, `set_parameter(parameter: str)`, and display text for the selected parameter.

- [ ] **Step 1: Define the parameter options and field mapping**

Add a UI-owned tuple with the exact labels used by the test and a field mapping for defaultable values:

```python
MATRIX_PARAMETERS = (
    ("coverage", "Coverage"),
    ("long_term_rms_v", "Long-term RMS voltage"),
    ("steady_state_peak_v", "Steady-state peak voltage"),
    ("recurring_peak_v", "Recurring peak voltage"),
    ("temporary_overvoltage_peak_v", "Temporary overvoltage peak"),
    ("impulse_v", "Impulse withstand voltage"),
    ("frequency_hz", "Frequency"),
    ("insulation_type", "Insulation type"),
    ("field_condition", "Field condition"),
    ("electrode_radius_mm", "Electrode radius"),
    ("altitude_m", "Altitude"),
    ("pollution_degree", "Pollution degree"),
    ("construction_type", "Construction"),
    ("cti_or_material_group", "CTI/material group"),
)
```

Keep voltage field names separate from `EffectiveCase` field names so voltage display reads `pair.voltages.<field>`. For defaultable display, assign `effective = resolve_effective_case(self._project.defaults, pair)` and read `getattr(effective, field)`.

- [ ] **Step 2: Add a resettable selected parameter and emit model refreshes**

Initialize the model to `"coverage"`, add:

```python
def set_parameter(self, parameter: str) -> None:
    if parameter not in {key for key, _label in MATRIX_PARAMETERS}:
        raise ValueError(f"Unknown matrix parameter: {parameter}")
    self.beginResetModel()
    self._parameter = parameter
    self.endResetModel()
```

Initialize `_parameter` in `__init__`; do not add a second pair storage structure.

- [ ] **Step 3: Implement value formatting and provenance rendering**

Add small module-local helpers that format `Decimal` values without scientific notation, append the unit (`V`, `Hz`, `mm`, or `m`) where applicable, return `—` for missing values, return `N/A` for `Applicability.NOT_APPLICABLE`, and append ` (D)` or ` (O)` only when an effective defaultable value exists. Use `resolve_effective_case(self._project.defaults, pair)` for defaultable fields.

For `DisplayRole`, keep diagonal cells as net names. For off-diagonal cells, return `✓` for `coverage`, the pair voltage display for voltage parameters, and the effective default/override display for all other parameters. A missing value is `—`; a blank coverage cell remains empty only when `pair_at()` returns `None`.

- [ ] **Step 4: Run the focused model/UI tests and verify green**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui/test_pair_workflow.py -k 'matrix_parameter or matrix_displays'
```

Expected: the matrix display tests pass; editor and layout tests may remain failing until Tasks 3 and 4.

- [ ] **Step 5: Commit the model implementation**

```bash
git add src/insulation_coordination/ui/pair_models.py
git commit -m "feat: show selected pair parameters in matrix"
```

## Task 3: Implement inherited values and pair-local reset controls in PairEditor

**Files:**
- Modify: `src/insulation_coordination/ui/pair_editor.py`

**Interfaces:**
- Consumes: `ProjectDefaults`, `resolve_effective_case()`, existing `OverrideValue` setters, and `PairCase` voltage fields.
- Produces: `load_pair(pair, defaults=None)`, `set_insulation_override()`, clear methods for every exposed defaultable field, and visible default/override provenance controls.

- [ ] **Step 1: Add failing coverage for all reset slots before extending the controls**

Extend the field test with direct assertions that the editor exposes reset buttons named `_freq_default_button`, `_insulation_default_button`, `_impulse_default_button`, `_field_default_button`, `_radius_default_button`, `_altitude_default_button`, `_pollution_default_button`, `_construction_default_button`, and `_cti_default_button`. A missing named control must fail clearly before implementation.

- [ ] **Step 2: Pass defaults into the editor and resolve effective values on load**

Import `ProjectDefaults` and `resolve_effective_case`. Store `_defaults: ProjectDefaults | None`. Change the signature to:

```python
def load_pair(self, pair: PairCase, defaults: ProjectDefaults | None = None) -> None:
```

When defaults are supplied, resolve the pair once and load effective values into every visible control. Set each provenance label from the corresponding `EffectiveValue.provenance`; when no default or override exists, leave the control blank and label it `Default`. Preserve the current pair-only behavior for tests/callers that omit `defaults`.

- [ ] **Step 3: Add provenance and “Use default” controls to every exposed defaultable field**

Extend `_override_row()` to accept a reset callback and add a compact button labeled `Default` with a tooltip `Use project default`. Add the missing insulation provenance label and wrap the insulation combo in the same row. Add a blank insulation item so an unset value can remain blank.

Keep the four voltage editors as direct pair-owned controls without provenance labels. Do not add a default path for voltages.

- [ ] **Step 4: Add the minimal setter/clearer methods**

Keep existing setters and add:

```python
def _clear_override(self, field: str, source_label: QLabel) -> None:
    if self._pair is None:
        return
    current = getattr(self._pair, field)
    self._update_pair(**{field: type(current).inherit()})
    source_label.setText("Default")
    if self._pair is not None:
        self.load_pair(self._pair, self._defaults)


def set_insulation_override(self, value: InsulationType) -> None:
    if self._pair is None:
        return
    self._update_pair(insulation_type=OverrideValue[InsulationType].override(value))
    self._insulation_source_label.setText("Override")


def clear_frequency_override(self) -> None:
    self._clear_override("frequency_hz", self._freq_source_label)


def clear_insulation_override(self) -> None:
    self._clear_override("insulation_type", self._insulation_source_label)


def clear_radius_override(self) -> None:
    self._clear_override("electrode_radius_mm", self._radius_source_label)


def clear_altitude_override(self) -> None:
    self._clear_override("altitude_m", self._altitude_source_label)


def clear_pollution_override(self) -> None:
    self._clear_override("pollution_degree", self._pollution_source_label)


def clear_construction_override(self) -> None:
    self._clear_override("construction_type", self._construction_source_label)


def clear_cti_override(self) -> None:
    self._clear_override("cti_or_material_group", self._cti_source_label)
```

Each clearer writes `OverrideValue[T].inherit()`, updates its provenance label to `Default`, and reloads the effective value from `_defaults` without emitting an accidental override. Keep `clear_impulse_override()` and `clear_field_override()` consistent with the same behavior. Add `clear_frequency_override()` because frequency currently has only a setter.

- [ ] **Step 5: Run the editor tests and verify green**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui/test_pair_editor_fields.py tests/ui/test_pair_workflow.py -k 'inherited_default or clear_defaultable or frequency_override or set_impulse or set_field'
```

Expected: inherited values, reset behavior, and existing override tests pass.

- [ ] **Step 6: Commit the editor implementation**

```bash
git add src/insulation_coordination/ui/pair_editor.py tests/ui/test_pair_editor_fields.py
git commit -m "feat: show pair defaults and reset overrides"
```

## Task 4: Implement the responsive PairPage layout and matrix wiring

**Files:**
- Modify: `src/insulation_coordination/ui/pair_editor.py`
- Modify: `tests/ui/test_pair_workflow.py`

**Interfaces:**
- Consumes: `MATRIX_PARAMETERS`, `CoverageMatrixModel.set_parameter()`, `PairEditor.load_pair(pair, defaults)`, and existing project signals.
- Produces: `_matrix_parameter_combo`, splitter-based responsive layout, matrix refresh after pair edits, and preserved selected-pair editing.

- [ ] **Step 1: Add failing layout and refresh tests**

Add:

```python
def test_pairs_page_uses_splitters_and_expanding_matrix(qtbot, pair_page):
    from PySide6.QtWidgets import QSplitter

    assert isinstance(pair_page._main_splitter, QSplitter)
    assert isinstance(pair_page._top_splitter, QSplitter)
    assert pair_page._matrix_view.minimumHeight() >= 160
    assert pair_page._matrix_view.sizePolicy().verticalPolicy().name == "Expanding"


def test_pair_edit_refreshes_selected_matrix_parameter(qtbot, pair_page):
    pair_page._matrix_parameter_combo.setCurrentText("Long-term RMS voltage")
    pair = pair_page.project.pairs[0]
    pair_page.select_pair_by_id(str(pair.id))
    pair_page.editor.set_long_term_rms("750 V")
    assert pair_page.matrix_model.data(pair_page.matrix_model.index(0, 1)) == "750 V"
```

- [ ] **Step 2: Run the new layout tests and verify they fail**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui/test_pair_workflow.py -k 'splitters or refreshes_selected'
```

Expected: FAIL because the current page has no splitters, no parameter combo, and does not reload the matrix model after an editor update.

- [ ] **Step 3: Build the split layout and add the parameter selector**

Import `QAbstractItemView`, `QHeaderView`, `QScrollArea`, `QSizePolicy`, and `QSplitter`. Create:

```python
self._main_splitter = QSplitter(Qt.Orientation.Vertical)
self._top_splitter = QSplitter(Qt.Orientation.Horizontal)
self._matrix_parameter_combo = QComboBox()
for key, label in MATRIX_PARAMETERS:
    self._matrix_parameter_combo.addItem(label, key)
self._matrix_parameter_combo.currentIndexChanged.connect(self._on_matrix_parameter_changed)
```

Put the combo, matrix view, and pair list in the expanding left pane. Put `PairEditor` inside a `QScrollArea` with `setWidgetResizable(True)` in the right pane. Put the Recalculate button and calculation review in the lower main splitter pane. Set stretch factors so the upper pane receives most of the page height, and set the matrix minimum height to at least 160 pixels. Configure matrix headers for interactive/stretch sizing while preserving horizontal scrolling for long net-class names.

- [ ] **Step 4: Wire parameter selection and pair loading**

Add:

```python
def _on_matrix_parameter_changed(self, index: int) -> None:
    parameter = self._matrix_parameter_combo.itemData(index)
    if isinstance(parameter, str):
        self.matrix_model.set_parameter(parameter)
```

Call `self.editor.load_pair(pair, self._project.defaults)` from `select_pair_by_id()`. Keep `select_pair_by_id()` as the single path used by both matrix and list clicks.

- [ ] **Step 5: Refresh the matrix without losing selection after editor changes**

In `_on_pair_changed()`, replace the project pair, then reload `matrix_model`, `pair_list_model`, and `calculation_review` from the updated project. Save the current parameter key before reload and restore it afterward if `load_project()` resets model state. Keep `_selected_pair_id` unchanged and do not reload the editor recursively.

- [ ] **Step 6: Run the focused workflow tests and verify green**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/ui/test_pair_workflow.py tests/ui/test_pair_editor_fields.py
```

Expected: all focused Pairs/editor tests pass, including existing recalculation, mirrored-pair, and grouping tests.

- [ ] **Step 7: Commit the responsive page implementation**

```bash
git add src/insulation_coordination/ui/pair_editor.py tests/ui/test_pair_workflow.py
git commit -m "fix: make pairs matrix responsive and editable"
```

## Task 5: Full verification and diff review

**Files:**
- Modify: none unless a verification command identifies a defect.

**Interfaces:**
- Consumes: completed model, editor, page layout, and focused tests.
- Produces: fresh evidence for the requested behavior and no regressions.

- [ ] **Step 1: Run the complete test suite**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Expected: zero failures; repository-configured private-standard skips are acceptable.

- [ ] **Step 2: Run lint and type checks**

```bash
uv run ruff check .
uv run mypy
```

Expected: both commands exit with status 0.

- [ ] **Step 3: Check whitespace and inspect the final diff**

```bash
git diff --check
git status --short
git diff -- src/insulation_coordination/ui/pair_models.py src/insulation_coordination/ui/pair_editor.py tests/ui/test_pair_workflow.py tests/ui/test_pair_editor_fields.py
```

Confirm that only the requested Pairs-page/UI tests changed; leave unrelated existing `audit/` worktree files untouched.

- [ ] **Step 4: Perform desktop acceptance**

Launch the GUI in a display-capable environment, maximize the window, open Pairs, and verify:

1. The matrix remains visible and is not collapsed.
2. Changing the dropdown to RMS, Frequency, or Impulse changes cell text.
3. A cell click loads the corresponding pair editor.
4. A project default is visible with `Default`/`D` provenance.
5. Editing one pair shows `Override`/`O` only for that pair.
6. Resetting a field returns it to the project default.
7. Numeric and N/A voltage entries display correctly and remain pair-local.

- [ ] **Step 5: Commit any final verification-only fixes**

If the checks identify a real implementation defect, add a focused failing test, fix it, rerun the relevant command, and commit the minimal correction:

```bash
git add src/insulation_coordination/ui/pair_models.py src/insulation_coordination/ui/pair_editor.py tests/ui/test_pair_workflow.py tests/ui/test_pair_editor_fields.py
git commit -m "fix: address pairs page verification findings"
```
