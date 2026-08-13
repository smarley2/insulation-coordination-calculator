# Project Defaults and Net-Class UI Design

## Goal

Make the three constrained project defaults selectable from explicit dropdowns and
make the visible Add button reliably add a net class through its dialog path.

## Scope

- Replace the project-default impulse voltage, pollution degree, and CTI/material
  group line edits with non-editable `QComboBox` controls.
- Keep an empty first option for an unset default.
- Populate impulse voltage with the option series carried by the approved rules
  package (source locator IEC 60664-1 Table F.2; the values are not restated in
  this public record), displayed in kV and stored as volts.
- Populate pollution degree with `1` and `2`.
- Populate material group with `I`, `II`, `IIIa`, and `IIIb`.
- Preserve existing project serialization and `ProjectDefaults` types.
- Add a Qt test that clicks Add, enters a name in the dialog, accepts it, and
  verifies the project and list are updated.
- Fix only the Add-path behavior exposed by that test; keep the public
  `add_net_class()` method unchanged unless the failing UI test proves it needs a
  supporting adjustment.

## Choices and data flow

`ProjectPage` owns the widgets and converts combo-box user data directly into the
existing domain values. The impulse combo stores `Decimal` volts as item data while
displaying the package-supplied kV labels; pollution stores integers; material stores
the group string. Selecting the blank item writes `None` through the same immutable
`ProjectDefaults.model_validate()` update path used today.

The Add button continues to open the existing `QInputDialog`. The regression test
will exercise the dialog as a user would, so any signal/event-order issue is fixed at
the UI boundary rather than weakening the existing domain-level tests.

## Error handling and compatibility

Existing invalid-input handling for free-text numeric defaults is removed only for
these constrained fields because the combo boxes cannot emit unsupported values.
Loading a project whose legacy/default value is outside the new choices must not
silently change it; the load path will retain the displayed value by adding it as a
temporary item when necessary, while new selections remain constrained to the
approved list.

## Verification

- Qt unit tests assert exact combo contents, blank selection behavior, and storage
  types/values.
- The Add-button test drives the dialog and verifies one net class plus the
  reconciled pair state.
- Run the focused UI tests, then the full test suite and lint/type checks.
- Launch the desktop UI and manually exercise the three dropdowns and Add flow.
