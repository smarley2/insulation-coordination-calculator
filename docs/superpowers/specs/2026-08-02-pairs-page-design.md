# Pairs Page Matrix Editing Design

## Goal

Make the Pairs page usable at normal and maximized window sizes while making every unique net-class pair easy to inspect and edit from the Coverage Matrix.

## Scope

This change is limited to the desktop Pairs page and its existing Qt models/widgets. It does not add a new project-file field, change the calculation domain model, or derive voltages from individual net classes.

## User-facing behavior

The Coverage Matrix represents one canonical `PairCase` for each unordered combination of two net classes. The diagonal has no pair. The two mirrored cells refer to the same stored pair.

The page uses a parameter selector above the matrix. The selector includes:

- Coverage status
- Long-term RMS voltage
- Steady-state peak voltage
- Recurring peak voltage
- Temporary overvoltage peak
- Impulse withstand voltage
- Frequency
- Insulation type
- Field condition
- Electrode radius
- Altitude
- Pollution degree
- Construction
- CTI/material group

Coverage status displays the existing complete/incomplete state. The other options display the selected pair’s effective value. Voltage values are pair-owned and show their numeric value, `N/A`, or `—` for blank. Defaultable parameters resolve through the existing project-default/pair-override mechanism and show a `D` marker for a project default or an `O` marker for an individual pair override. Missing values show `—`.

Clicking an off-diagonal matrix cell selects that pair and loads it into the editor. Editing any field updates only that pair, refreshes the project and matrix, and keeps the selected pair active. Every defaultable field currently exposed in the PairEditor supports an individual pair override. Clearing an override returns the field to the project default. The four stress voltages are always pair-owned inputs and are edited directly; they do not use default/override provenance. The model’s conventional-construction-assumptions field remains out of scope because it is not currently exposed in the desktop editor.

## Layout

The Pairs page replaces its unbounded vertical stack with a vertical splitter:

1. The upper pane contains a horizontal splitter.
   - The left pane contains the parameter selector, Coverage Matrix, and pair list.
   - The right pane contains a scrollable selected-pair editor.
2. The lower pane contains the Recalculate button and calculation review.

The matrix and editor use expanding size policies. The matrix has a useful minimum height, stretchable rows and columns, and horizontal scrolling only when net-class labels require it. The editor scrolls independently. Switching pages does not alter the main window geometry.

## Data flow

`PairPage` owns the current immutable `Project`. `CoverageMatrixModel` retains the canonical unordered-pair lookup and exposes a selected display parameter. For defaultable fields it uses `resolve_effective_case(project.defaults, pair)` to render the effective value and provenance. `PairEditor` receives the current `ProjectDefaults` when loading a pair so inherited values are visible rather than blank; its existing setters continue to write `OverrideValue.override(...)` for pair-local edits, and each exposed defaultable row provides a way to return to inheritance.

After an editor change:

1. `PairEditor` emits the updated `PairCase`.
2. `PairPage` replaces that pair in the immutable `Project`.
3. The matrix model and calculation review reload from the updated project.
4. The selected pair remains selected and the visible parameter cell updates.

## Validation and error handling

Existing parsing and domain validation remain authoritative. Invalid text does not replace the current valid pair value. Blank and not-applicable voltage states remain distinct; not-applicable continues to require a justification. Matrix rendering must tolerate missing effective values without raising and display `—`.

## Testing

Add focused Qt tests for:

- matrix parameter selection and display for a pair-owned voltage;
- matrix display of a project default and an individual pair override;
- mirrored cells resolving to the same pair and same displayed value;
- clicking a matrix cell loading the correct pair editor;
- inherited defaults appearing as values in the editor;
- changing an editor field affecting only the selected pair;
- layout splitter and expanding size policies preventing a collapsed matrix;
- existing recalculation and save/reload behavior remaining intact.

Run the focused UI tests, the complete test suite, Ruff, mypy, and `git diff --check` before claiming completion.
