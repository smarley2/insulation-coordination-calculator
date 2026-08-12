# Issue #52 — Annex E gets two semantic identifiers

Both Annex E grids hang off one identifier, `iec62477_2022.altitude.test_voltage_correction`,
used as `f"{...}.e1"` and `f"{...}.e2"` by the recipe. E.1 does not correct test voltages: it
gives an altitude correction factor for dimensioning clearances. The name in the contract
asserts something the source does not, which is the defect class of #48 (invented DVC
designations) and #50 (an unstated Figure 7 basis).

Annex E separates E.1 and E.2. E.1's factor is consumed by the clearance-dimensioning path,
and the main clearance clause points at E.1; E.2's corrected voltages serve clearance
verification. These are maintainer-reviewed source facts, recorded here as the basis of the
split; no licensed value or wording enters this repository.

## The contract

Two identifiers, each owning exactly one table:

```text
iec62477_2022.altitude.clearance_correction
iec62477_2022.altitude.test_voltage_correction
```

`semantic_ids.py` gains `ALTITUDE_CLEARANCE_CORRECTION` directly above the existing constant,
and `REQUIRED_SEMANTIC_IDS` gains the same member: the required semantic inventory goes from
twenty-five identifiers to twenty-six.

No alias, and no `.e1` / `.e2` suffix on either. A suffix belongs to an identifier that
genuinely fans out into routes — `CREEPAGE_REQUIREMENTS`, `HIGH_FREQUENCY_APPLICABILITY`, the
Table 7 pairs. After the split each altitude identifier has one member, so it is named the way
`CLEARANCE_REQUIREMENTS` is: bare.

`semantic_ids.py` states that an identifier is immutable once released in an approved package
and that a changed interpretation creates a new identifier rather than redefining an old one.
E.1 gets a new identifier, which is exactly that rule. E.2's move from `.e2` to bare is an
intentional breaking identifier correction, made before a released approved contract depends
on it. It is not a precedent for removing a suffix from a released identifier: that would
still require a new identifier.

### What a rebuild has to do

Neither altitude spec registers a grid projector and neither is `comparison_only`, so
`package_expectations` files both under `table_rule_ids` with `typed_results[id] = {id}`: each
identifier emits one table rule, itself.

For a trusted approved IEC package, `validate_rule_package` derives the expected table ids
from the current recipes and requires the package's table-id set to equal it. An approved
package carrying the suffixed altitude ids therefore stops loading after this change. That is
the intended behaviour. Rebuild, re-review, re-approve; there is no shim and no migration.

## The recipe

In `recipes/iec62477_1_2022/tables.py`, the two f-strings become the two constants and the
provenance sharpens from the annex to the subclause:

```text
ALTITUDE_CLEARANCE_CORRECTION      source_table="E.1"   clause="E.1"
ALTITUDE_TEST_VOLTAGE_CORRECTION   source_table="E.2"   clause="E.2"
```

Nothing else in either spec moves. The semantics one level down were already right: E.1 keeps
`column_axis_id="clearance_correction_branch"` and its `clearance_factor` data column, E.2
keeps `altitude_band_m` and `_altitude_band_columns()`.

Segment ids stay `table-e1` and `table-e2`. A segment id is an extraction-segment identity
local to its spec, not part of the consumer-facing contract, so renaming it would buy no
semantic clarity and would churn artifacts and hashes for nothing.

## The inventory

`iec62477_2022/inventory.py` replaces one item with two, in document order:

```python
(_item(ids.ALTITUDE_CLEARANCE_CORRECTION, "table", (36,), table="Table E.1"),)
(_item(ids.ALTITUDE_TEST_VOLTAGE_CORRECTION, "table", (37,), table="Table E.2"),)
```

Clearance dimensioning feeds #36; corrected test voltages feed #37. The checklist then says
which consumer breaks if either table goes missing, which the single item could not.

Neither item carries `expected_clause`. Table-backed items name their table; `clause=` is for
items that are prose- or clause-oriented, such as `HIGH_FREQUENCY_APPLICABILITY`. The sharper
subclause lives in the recipe spec, where extraction reads it, and duplicating it onto the
checklist would create a second place to keep correct.

This closes the second defect #52 names, and the hole is at the declaration level rather than
the extraction level. With both `.e1` and `.e2` declared, `inventory_report` already requires
every matching declared route to be extracted and typed, so a failing E.2 extraction fails the
parent item today. What the old inventory lacked was an independent statement that E.2 is
required at all: had its spec been removed, `matching` would have shrunk to E.1 and the single
parent item could still have reported complete. Two items make each table's requirement a
statement of the checklist rather than a consequence of the recipe.

`_covers` is unchanged. Its prefix behaviour is intentional for identifier families that
really do fan out into routes, and it documents that purpose. #52 stops abusing that mechanism
for two rules that are separate engineering jobs.

## Regression guards

Two guards that fail for independent reasons, not two spellings of one assertion.

**The recipe guard** replaces `test_altitude_tables_share_one_semantic_family` in
`test_recipe_shape.py`, whose premise — two children under the one parent — is the defect being
removed. The replacement pins which physical table each identifier owns, together with its
subclause:

```python
e1 = next(spec for spec in RECIPE.tables if spec.semantic_id == ids.ALTITUDE_CLEARANCE_CORRECTION)
e2 = next(
    spec for spec in RECIPE.tables if spec.semantic_id == ids.ALTITUDE_TEST_VOLTAGE_CORRECTION
)

assert e1.source_table == "E.1"
assert e1.clause == "E.1"

assert e2.source_table == "E.2"
assert e2.clause == "E.2"
```

and asserts that the annex-E altitude specs are exactly two, under exactly those two bare
identifiers. Pinning the emitted identifier set is what makes re-nesting either table under
the other's family fail.

**The inventory guard** is new in `test_inventory.py`: two required items, each naming its own
table, E.1 on `(36,)` and E.2 on `(37,)`. It states both tables' requirement independently of
the recipe, which is the structural hole described above.

The existing behavioural tests in `test_inventory.py` need no change — they derive from the
tuple rather than hard-coding a count — but their documentation does.

### Counts and prose

Three numeric assertions move from twenty-five to twenty-six: `test_semantic_ids.py`,
`test_slice_e2_integration.py`, and private `test_iec62477_end_to_end.py`. The report line in
`test_slice_e2_integration.py` interpolates `len(...)` and follows on its own.

Six spelled-out references also move, so no stale documentation survives the change:
`test_catalog_has_twenty_five_unique_ids` (renamed), the `test_slice_e2_integration.py` module
and test docstrings, the closing docstring in `test_inventory.py`, the private
`test_iec62477_end_to_end.py` module docstring, and the source comment in
`recipes/iec62477_1_2022/procedures.py`.

### Private guards

`tests/private/test_iec62477_numeric_tables.py` asserts both suffixed `raw-` grid ids; both
become the bare ones. This test is the right home because it verifies that the real licensed
extraction produces both altitude grids under their corrected identifiers.

### Files touched

Source: `semantic_ids.py`, `inventory.py`, `recipes/iec62477_1_2022/tables.py`, and the comment
in `recipes/iec62477_1_2022/procedures.py`.

Tests: `test_recipe_shape.py`, `test_inventory.py`, `test_semantic_ids.py`,
`test_slice_e2_integration.py`, `tests/private/test_iec62477_numeric_tables.py`,
`tests/private/test_iec62477_end_to_end.py`.

## Package and review consequences

Both identifier changes invalidate the previous review identity, by two mechanisms:

- `ImportReviewItem.sha256` hashes the whole review item, `semantic_id` included, so the item
  itself is a different item after the rename.
- `_review_resolution_exists` resolves a `kind="table"` item by finding a rebuilt raw grid
  whose id is exactly `raw-{item.semantic_id}`. The old grid ids no longer exist, so a stored
  resolution matches nothing and the item is unresolved, which blocks approval.

This includes E.2, whose engineering meaning is unchanged. Its artifact and review identity
changed, so renewed review is correct rather than an inconvenience.

Cell-level review items are keyed `grid_id:row:column:index` and would be invalidated the same
way. Neither altitude spec declares compound components, so there are none to lose.

No source-region re-selection is involved. The PDF source regions, bounding boxes, segments,
row and column structure, and extraction strategy do not change. Both tables are re-extracted
under their corrected identifiers and must be re-reviewed; no source geometry is redesigned.

## Verification

Quality gates: ruff, mypy strict, the full suite, and the 80% coverage floor. The public half
of this change is fully covered by them.

Licensed-source verification requirement: the design rests on maintainer-reviewed source facts
establishing the E.1 / E.2 split, recorded in the opening section. Implementation proceeds
without embedding those licensed contents publicly. Execution verification is still
outstanding: the final PR must run the private licensed-document extraction suite, on the
machine holding the PDFs, before it merges. The two private tests above are what that run
exercises.

Public-record limit: identifiers, table and subclause locators, structural indexes, and
neutral semantic descriptions such as "clearance correction" and "test-voltage correction".
No numeric content and no source wording enters the public repository.

## Out of scope

The two footnote-marker allowlists #52 documents stay as they are. Tightening them is safe
against this edition and more brittle against the next, so it is a deliberate decision of its
own rather than a drive-by change here.

No runtime consumer is wired. The live altitude correction resolves IEC 60664-1's table
(`apply_a2_altitude_correction`); pointing any calculation at the 62477 factor belongs to #36.

Nothing from #53. The provisional DVC positional contract is untouched by this change.
