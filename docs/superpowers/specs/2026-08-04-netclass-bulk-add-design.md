# Bulk Net-Class Add Design

## Goal

Let the engineer mint a numbered run of net classes on the Project page in one action —
base name plus a count, producing `DIV_HV_1` … `DIV_HV_4` — instead of typing each name
into the Add dialog.

Reference case (issue #1): an HV divider of five 330 kΩ resistors between `HVP` and `HVN`
needs four intermediate net classes, and the engineer needs those names to write the
Altium net-class rules.

## Scope

One public method on `ProjectPage` and one button. Nothing else changes: no new domain
entity, no schema version, no change to `reconcile_pairs`, the pair list, the coverage
matrix, or the report.

Deliberately absent, and each one is a decision rather than an oversight:

- **No voltage derivation.** The working voltages of every spacing inside the divider are
  typed by hand, pair by pair, exactly as for any other pair today.
- **No pair-set relaxation.** Generated net classes are ordinary net classes, so they pair
  with every other net class. A project of six plain nets plus six four-node dividers holds
  30 net classes, 435 pairs and a 30×30 coverage matrix. Accepted knowingly: the simple
  version ships first and the matrix gets judged against real data.
- **No auto description.** A generated net class carries a blank description, like a manual
  add. A canned string would render into the report, where a wrong-looking one is worse
  than none.

A fuller treatment — a persistent chain entity that derives each span's worst-case voltage
and owns its own pair subset — was designed and built on the local branch
`feat/resistor-measurement-chain` and rejected as too heavy before this spec. Issue #1
therefore stays open after this work lands.

## Interface

```python
def add_net_classes(self, base: str, amount: int) -> None:
    """Append `amount` net classes named base_1 … base_amount."""
```

Names are `f"{base}_{position}"` for `position` in `1..amount`: index starts at one, no zero
padding. `base` is stripped of surrounding whitespace and of one trailing underscore, so
`"DIV_HV_"` and `"DIV_HV"` produce the same run.

Validation, all raising `ValueError` with a readable message and mutating nothing:

- empty base after stripping
- `amount` below 1 or above 64
- any generated name already present in `Project.net_class_names`, reported by name

Name comparison is exact, matching the case-sensitive check `add_net_class` already
performs — `div_hv_1` and `DIV_HV_1` can coexist today and this method does not change that.

Collision checking happens before any mutation, so a batch is all-or-nothing: no half-built
divider is left behind for the engineer to clean up.

The whole batch is one project update — every new `NetClass` appended in index order, a
single `reconcile_pairs` call, a single `_update_project`. That emits one `project_changed`
signal instead of `amount` of them, and marks the project dirty once.

`add_net_class` is left untouched. It takes a literal name plus a description, so merging the
two would buy an argument to explain and nothing else.

## User-facing behaviour

The net-class group box gains a fourth button, "Add Many…", beside Add, Rename and Delete.
Its handler asks for the base name (`QInputDialog.getText`), then the amount
(`QInputDialog.getInt`, default 4, minimum 1, maximum 64), calls `add_net_classes`, and shows
the `ValueError` message in a `QMessageBox.warning` on rejection.

The handler holds no logic beyond that sequence. Both dialogs are modal, and an offscreen
modal reached from a test hangs the entire CI job, so tests drive `add_net_classes`
directly and never press the button.

## Testing

In `tests/ui/test_project_pages.py`, against the public method:

1. `add_net_classes("DIV_HV", 4)` appends exactly `DIV_HV_1` … `DIV_HV_4` after the existing
   net classes, in order.
2. Pairs reconcile to `C(n, 2)` for the new net-class count, and data already entered on an
   unrelated pair survives.
3. A collision with an existing `DIV_HV_2` raises `ValueError`, and both the net-class count
   and the pair count are unchanged afterwards.
4. `"DIV_HV_"` yields the same names as `"DIV_HV"`.
5. `amount=0` and `amount=65` each raise `ValueError`.

## Verification

Focused tests, then the full suite, Ruff, mypy strict, `git diff --check`, and the 80%
coverage gate that `pyproject` enforces locally. Then a pull request whose body says
`Refs #1` — the issue is not closed by name minting alone.
