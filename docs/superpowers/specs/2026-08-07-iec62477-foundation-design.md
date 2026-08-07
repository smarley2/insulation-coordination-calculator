# IEC 62477-1:2022 rule foundation (Slice A)

Issue: [#34](https://github.com/smarley2/insulation-coordination-calculator/issues/34), slice A of five.
Date: 2026-08-07.

## Purpose

Issue #34 asks for an end-to-end Rule Manager workflow that extracts IEC 62477-1:2022
into an approved private `.icrules` package. That is far too large for one change. This
slice builds the foundation the other four slices stand on, and touches no PDF:

1. A frozen catalog of stable semantic IDs.
2. A machine-readable inventory of required source items.
3. Rule-schema version 3, adding decisions, procedures, and guidance as first-class
   auditable rule kinds.
4. One new expression node, so RMS-to-peak conversion is a reviewed formula rather than
   a precomputed constant.
5. Decision evaluation that returns provenance, and returns "input required" instead of
   guessing.

Nothing in this slice reads a licensed PDF. Every test uses synthetic values.

## Slice map

| Slice | Content | Depends on |
| --- | --- | --- |
| A (this spec) | Semantic IDs, inventory, schema v3, decision evaluation | — |
| B | 62477 document identity, numeric table recipes (7, E.1, E.2) | A |
| C | Blank-cell semantics, categorical and decision tables (2, 3, 8, 9, 27, 28, 29) | B |
| D | Prose clause rules, procedures (26, 30), review and authoring UI | C |
| E | Inventory-driven completeness gates, package composition, private end-to-end | D |

## Semantic ID catalog

New module `src/insulation_coordination/rules/importer/iec62477_2022/semantic_ids.py`.

It declares the 24 IDs listed in issue #34 as module-level constants and exposes
`REQUIRED_SEMANTIC_IDS: frozenset[str]`. The IDs are immutable once released in an
approved package. A changed interpretation creates a new versioned ID, never a silent
redefinition of an existing one.

The module holds identifiers only. No clause text, no numeric values, no source wording.

## Required source inventory

New module `src/insulation_coordination/rules/importer/iec62477_2022/inventory.py`.

```python
class RequiredSourceItem(FrozenModel):
    semantic_id: Identifier
    standard: Identifier
    edition: Identifier
    expected_clause: ReferenceText | None = None
    expected_table: ReferenceText | None = None
    expected_figure: ReferenceText | None = None
    expected_output_kind: RuleKind
    required: bool = True
    consumer_issue_ids: tuple[int, ...]
```

`RuleKind`, declared in the same module, is
`Literal["table", "formula", "decision", "procedure", "guidance"]`.

`REQUIRED_SOURCE_ITEMS: tuple[RequiredSourceItem, ...]` covers every ID in the catalog.
This inventory is the single authoritative checklist. Slices B through E derive
extraction targets, review status, completeness counts, and private test expectations
from it. Package completeness is never computed by counting tables or matching titles.

Table and clause identifiers such as `"Table 7"` are structural locators, not source
wording, and may live in public code. Column headings, cell values, notes, and clause
prose may not.

## Schema version 3

All changes land in `src/insulation_coordination/domain/rules.py`.

### Constants

- `RULE_SCHEMA_VERSION` goes from 2 to 3.
- `IEC_IMPORTER_VERSION` goes from `"iec-pdf-2"` to `"iec-pdf-3"`.

### Decision rules

```python
DecisionValueKind = Literal["categorical", "numeric", "boolean"]

class DecisionInput(FrozenModel):
    name: Identifier
    kind: DecisionValueKind
    unit: Identifier | None = None
    allowed_values: tuple[Identifier, ...] = ()

class DecisionOutput(FrozenModel):
    name: Identifier
    kind: DecisionValueKind | Literal["reference"]
    unit: Identifier | None = None
    allowed_values: tuple[Identifier, ...] = ()

class Matcher(FrozenModel):
    input: Identifier
    op: Literal["any", "equals", "in", "range"]
    values: tuple[Identifier, ...] = ()
    minimum: DecimalValue | None = None
    maximum: DecimalValue | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True

class DecisionValue(FrozenModel):
    name: Identifier
    categorical: Identifier | None = None
    numeric: DecimalValue | None = None
    boolean: bool | None = None
    reference: Identifier | None = None
    unit: Identifier | None = None

class DecisionRow(FrozenModel):
    matchers: tuple[Matcher, ...]
    values: tuple[DecisionValue, ...]
    source: SourceReference
    notes: NotesText = ""

class DecisionRule(FrozenModel):
    id: Identifier
    inputs: tuple[DecisionInput, ...] = Field(min_length=1)
    outputs: tuple[DecisionOutput, ...] = Field(min_length=1)
    rows: tuple[DecisionRow, ...] = Field(min_length=1)
    exhaustive: bool
    applicability: ApplicabilityText = ""
    source: SourceReference
```

Rows are ordered and the first match wins. That ordering is data, not an implementation
detail: a reviewer reads the rows in the order the standard states its exceptions.

Model validation rejects a rule when:

- a matcher names an input the rule does not declare;
- a categorical matcher uses a value outside the input's `allowed_values`;
- a `range` matcher targets a non-numeric input, or a numeric input has no unit;
- a row does not produce exactly the declared outputs, once each;
- a `DecisionValue` sets a field that contradicts its declared output kind, or sets more
  than one of the four value fields;
- a categorical output value falls outside its declared `allowed_values`;
- `exhaustive` is true and the cross-product of categorical input domains is not covered.

`reference` outputs carry another rule's identifier. That is how "according to Table 7"
stays a rule reference instead of degrading into a text value.

### Procedure and guidance rules

```python
class ProcedureStep(FrozenModel):
    order: int = Field(ge=1)
    text: ReferenceText
    source: SourceReference

class ProcedureRule(FrozenModel):
    id: Identifier
    test_kind: Identifier
    classifications: tuple[Identifier, ...] = ()
    waveform: ReferenceText | None = None
    polarity: ReferenceText | None = None
    duration: ReferenceText | None = None
    repetitions: ReferenceText | None = None
    preparation_steps: tuple[ProcedureStep, ...] = ()
    procedure_steps: tuple[ProcedureStep, ...] = ()
    acceptance_reference: SourceReference | None = None
    applicability_rule_id: Identifier | None = None
    applicability: ApplicabilityText = ""
    source: SourceReference

class GuidanceRule(FrozenModel):
    id: Identifier
    title: ReferenceText
    summary: NotesText
    warnings: tuple[NotesText, ...] = ()
    examples: tuple[NotesText, ...] = ()
    source: SourceReference
```

`applicability_rule_id` keeps applicability separate from procedure, so a missing
engineering input yields `ENGINEERING_INPUT_REQUIRED` rather than `NOT_REQUIRED`.

### Package

`RulePackage` gains three fields, each defaulting to empty so existing construction sites
keep working:

```python
decisions: tuple[DecisionRule, ...] = ()
procedures: tuple[ProcedureRule, ...] = ()
guidance: tuple[GuidanceRule, ...] = ()
```

`CompatibilityMapping` stays exactly as it is. It is not a container for IEC decision
logic, and no new decision content is expressed through it.

### Migration

None. `load_rule_package` already rejects a schema mismatch and already names the
required action, at `src/insulation_coordination/rules/archive.py:225`. Bumping the
constant makes every version 2 package fail to load with that message. This slice adds a
test proving it and nothing else. Writing an upgrade path for a one-time maintainer-only
event is not worth its own test surface.

The archive format is a fixed member list, `CORE_MEMBERS` at
`src/insulation_coordination/rules/archive.py:19`. The three new package fields need
three new members, `decisions.json`, `procedures.json` and `guidance.json`, each
checksummed like the existing ones. Without that, decisions written into a package would
vanish on the next load without any error.

## Expression node: Power

Issue #34 requires deterministic Decimal square-root behaviour for RMS-to-peak
conversion, and forbids precomputing undocumented constants.

```python
class Power(FrozenModel):
    op: Literal["power"] = "power"
    base: Expression
    numerator: int = Field(strict=True)
    denominator: Literal[1, 2] = 1
```

`denominator` is restricted to 1 and 2, which covers integer powers and square roots.
That is everything the reviewed rules need today. A third root value gets added when a
reviewed rule requires one, not before.

Evaluation rules in `src/insulation_coordination/rules/evaluator.py`:

- `denominator == 1`: exact integer power. A negative exponent on a zero base is an
  `EvaluationError`.
- `denominator == 2`: `Decimal.sqrt` under the formula's declared precision context,
  applied to `base ** numerator`. A negative operand is an `EvaluationError`, never a
  complex or NaN result.
- The rendered trace shows the operation and its operands, like every other node.

`Power` joins the `Expression` union, the discriminator, the `model_rebuild` list, the
`_expression_shape` and `_expression_variables` walkers in
`src/insulation_coordination/rules/importer/approval.py`, and the audit inventory in
`src/insulation_coordination/rules/audit.py`.

## Decision evaluation

New function in `src/insulation_coordination/rules/evaluator.py`:

```python
class DecisionResult(FrozenModel):
    rule_id: Identifier
    status: Literal["matched", "no_match", "input_required"]
    matched_row: int | None = None
    values: tuple[DecisionValue, ...] = ()
    missing_inputs: tuple[Identifier, ...] = ()
    source: SourceReference | None = None

def evaluate_decision(
    rule: DecisionRule,
    inputs: Mapping[str, Decimal | str | bool],
) -> DecisionResult: ...
```

Behaviour:

- A declared input absent from `inputs` produces `input_required` and names every missing
  input. Consumers map that to `ENGINEERING_INPUT_REQUIRED`. It never falls through to a
  default row.
- An input value outside a categorical input's `allowed_values` is an `EvaluationError`.
  Silently treating it as no-match would hide a caller bug.
- The first matching row wins. `source` carries that row's `SourceReference`, so a
  caller can render exactly which table row or clause produced the outcome.
- No match on a non-exhaustive rule produces `no_match`. No match on a rule declared
  exhaustive is an `EvaluationError`, because construction validation should have made
  it impossible.

Runtime UI consumes `DecisionResult`. It never re-implements the lookup.

## Audit and report surfaces

- `src/insulation_coordination/rules/audit.py` gains decision, procedure, and guidance
  counts plus their source references, so the existing audit inventory and export stay
  complete.
- `src/insulation_coordination/ui/rules_manager.py` gains Decisions, Procedures, and
  Guidance sections in the audit tree, populated from the inventory. No parsing logic
  enters this module.
- `src/insulation_coordination/report/model.py` records the new counts alongside the
  existing schema version, so a generated report states what kind of rules it used.

Report template changes beyond those counts are out of scope for this slice.

## Tests

All public, all synthetic.

`tests/rules/importer/iec62477_2022/test_semantic_ids.py`

- Every catalog ID is unique.
- `REQUIRED_SEMANTIC_IDS` matches the declared constants exactly.
- Every ID matches the documented naming shape.

`tests/rules/importer/iec62477_2022/test_inventory.py`

- Every required semantic ID appears in the inventory exactly once.
- Every inventory item names at least one consumer issue.
- Every consumer issue in 35, 36, 37 has at least one item.
- Every item of kind `table` declares `expected_table`.

Prose-derived items carry no locator in this slice. Issue #34 names them by description
rather than clause number, and confirming a clause number requires the document. Their
locator lands with their extraction recipe in slice D, where it can be verified against
the source rather than guessed.

`tests/rules/test_decision_rules.py`

- Round-trip serialization preserves every field.
- Each validation rejection listed above has a failing case.
- An exhaustive rule with an uncovered categorical combination is rejected.
- A reference output pointing at another rule survives round-trip.

`tests/rules/test_decision_evaluation.py`

- Matched, no-match, and input-required paths.
- First-match-wins ordering with overlapping rows.
- Out-of-domain categorical input raises.
- No-match on an exhaustive rule raises.
- The result carries the matching row's source reference.

`tests/rules/test_power_expression.py`

- `denominator=1` integer powers, including negative exponents.
- `denominator=2` square root reproducibility across repeated evaluation.
- Negative operand under a square root raises `EvaluationError`.
- Precision honoured at the formula's declared precision.
- Round-trip serialization and rendered trace.

`tests/rules/test_archive.py` gains a case proving a schema-version-2 package fails to
load with a message naming the rebuild requirement.

Existing suites in `tests/rules/` and `tests/ui/` are updated for the schema bump.
`tests/fixtures/synthetic_rules.py` gains a synthetic decision rule, procedure, and
guidance entry so downstream tests have something to exercise.

## Out of scope for this slice

- Any PDF reading, identity validation, or extraction recipe.
- Any change to `_REQUIRED_RECIPES`. The package still requires exactly IEC 60664-1:2020
  and IEC 60664-4:2005 until slice B.
- Prose clause handling and the authoring UI.
- The completeness dashboard.
- Private tests against licensed PDFs.

## Definition of done

- `uv run ruff check .` passes.
- `uv run mypy` passes.
- `uv run pytest` passes, coverage still at or above the configured floor.
- No licensed value, heading, note, or clause text appears in any file added by this
  slice.
