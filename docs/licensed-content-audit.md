# Licensed-content audit inventory

Issue #40, Task 9. Full-repository audit of the public tree for licensed IEC
content, produced from a run of `scripts/scan_licensed_content.py` (109
scanner findings) plus a manual review pass. This inventory lists paths,
line references, detection classes, and neutral descriptions only. It never
restates a licensed value, heading, note, or clause wording; classification
of any entry against the licensed source happens in private sessions only.

- Date: 2026-08-13
- Command: `uv run python scripts/scan_licensed_content.py .`
- Scanner totals: inline-factor=2, inline-threshold=7, numeric-series=41,
  source-like-text=28, synthetic-iec-source=2, text-numeric-series=3,
  value-near-table-id=26
- Tracked private artifacts (`.pdf`, `.icrules`, `.icproj`,
  `audit-inventory.json`): none, in the current tree and in the full history.

## Assessment vocabulary

| Assessment | Meaning |
| --- | --- |
| confirmed | Matches an issue #40 finding; migration to `.icrules` or a rewrite is pending. |
| allowed-structural | Permitted locator data: page numbers, bounding boxes, row/column indexes and counts, table/clause identifiers, shape expectations. |
| synthetic-ok | Reviewed; values are project-invented and do not reproduce source content. |
| verify-private | Cannot be classified from the public side; must be checked against the licensed source in a private session. |
| false-positive | Scanner heuristic artifact; no licensed-content risk. |

## Runtime source code

| Location | Class | Description | Assessment |
| --- | --- | --- | --- |
| `src/insulation_coordination/ui/value_options.py:14` | numeric-series | Complete constrained option series with unit labels, offered by the UI | confirmed (finding A) |
| `src/insulation_coordination/calculation/clearance.py:132` | numeric-series | Preferred-level series used by the reinforced treatment | confirmed (finding B) |
| `src/insulation_coordination/calculation/clearance.py:155` | inline-factor | Reinforced stress multiplier in calculation code | confirmed (finding B) |
| `src/insulation_coordination/calculation/clearance.py:146-166` | manual | Treatment trace wording and symbolic text mirror the source procedure rather than neutral application text | confirmed (finding B) |
| `src/insulation_coordination/calculation/creepage.py:144` | inline-factor | Reinforced creepage multiplier in calculation code | confirmed (finding B class) |
| `src/insulation_coordination/calculation/engine.py:180` | inline-threshold | High-frequency routing boundary as a literal | confirmed (finding B class) |
| `src/insulation_coordination/calculation/engine.py:387` | inline-threshold | Partial-discharge advisory trigger as a literal | confirmed (finding B class) |
| `src/insulation_coordination/calculation/high_frequency.py:104` | inline-threshold | High-frequency applicability boundary as a literal | confirmed (finding B class) |
| `src/insulation_coordination/calculation/high_frequency.py:257` | inline-threshold | High-frequency applicability boundary as a literal | confirmed (finding B class) |
| `src/insulation_coordination/calculation/high_frequency.py:462` | inline-threshold | Altitude-correction base boundary as a literal | confirmed (finding B class) |
| `src/insulation_coordination/calculation/high_frequency.py:601` | inline-threshold | Altitude table boundary validation constant | confirmed (finding B class) |
| `src/insulation_coordination/calculation/high_frequency.py:649` | inline-threshold | High-frequency applicability boundary as a literal | confirmed (finding B class) |

The `inline-threshold` entries extend finding B: they are comparison
constants rather than multiplicative factors, but the same migration rule
applies (semantic rule in `.icrules`, blocking behavior when absent).

## Importer recipes

Do not edit these under this slice; the importer tree is owned by the
in-flight #53 workstream.

| Location | Class | Description | Assessment |
| --- | --- | --- | --- |
| `src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py:145,150-155,207-216,255,297,300,342` | source-like-text | Sentence-case column headings instead of neutral lowercase descriptions | confirmed (finding F); wording match to the source must be checked privately |
| `src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py:104,347` | numeric-series | Page numbers, bounding boxes, row/column geometry, expected counts | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py:43,128,169,272` | source-like-text | Sentence-case column headings instead of neutral lowercase descriptions | confirmed (finding F) |
| `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py:131,211` | numeric-series | Structural extraction geometry | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/clauses.py:30` | numeric-series | Structural extraction geometry | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/clauses.py:63,65` | source-like-text | Error-message strings, not source text | false-positive |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/high_frequency.py:54` | numeric-series | Structural extraction geometry | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/procedures.py:72,280` | numeric-series | Grid row indexes and segment geometry | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/spacing.py:175,468` | numeric-series | Grid row indexes and segment geometry | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py:47` | numeric-series | Clause bounding boxes and page numbers | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py:332` | source-like-text | Project-authored guidance title/summary describing that source notes exist | verify-private (confirm the summary stays descriptive and copies nothing) |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py:408,491` | numeric-series | Structural extraction geometry | allowed-structural |

## Public tests and fixtures

| Location | Class | Description | Assessment |
| --- | --- | --- | --- |
| `tests/calculation/conftest.py:97,111,196,197,391,393` | numeric-series | Fixture axis series and cell values attached to real annex-table locators | confirmed (finding C); exact-match extent is a private check |
| `tests/calculation/conftest.py:115-154` | manual | Altitude axis rows and factors attached to a real annex-table locator (below series threshold) | confirmed (finding C) |
| `tests/calculation/conftest.py:155-194` | manual | Advisory-table axis and cells attached to a real annex-table locator | confirmed (finding C) |
| `tests/calculation/conftest.py:474-537` | manual | Formula constants attached to IEC 60664-4 equation semantics | verify-private |
| `tests/calculation/test_high_frequency.py:138,159,326,444` | numeric-series | Parametrized expectations bound to IEC 60664-4 semantic behavior | verify-private (moves with the conftest fixtures) |
| `tests/calculation/test_part1.py:183` | numeric-series | Expected outputs derived from the synthetic cell scheme | synthetic-ok; re-check during Task 5 |
| `tests/domain/test_display.py:67` | numeric-series | Display expectations that include formula constants near Part 4 semantics | verify-private |
| `tests/fixtures/synthetic_rules.py:89,252,409,634,1082` | numeric-series | Project-invented axes, cells, and curve points | synthetic-ok |
| `tests/fixtures/synthetic_rules.py:1029,1246` | synthetic-iec-source | Synthetic package claims a real IEC standard identity as its source reference | confirmed (scanner class 5); resolve with Task 5 fixture policy |
| `tests/fixtures/topology_examples.py:69` | numeric-series | Synthetic project input triples | synthetic-ok |
| `tests/rules/importer/iec62477_2022/test_annex_f_recipes.py:107-109` | numeric-series | Page numbers and expected grid shapes | allowed-structural |
| `tests/rules/test_evaluator.py:616` | numeric-series | Synthetic trace-formatting expectations | synthetic-ok |
| `tests/rules/test_importer.py:205,811` | numeric-series | Synthetic PDF recipe and compound-cell fixtures | synthetic-ok |
| `tests/test_end_to_end.py:83` | numeric-series | Synthetic project pair inputs | synthetic-ok |
| `tests/ui/test_pair_workflow.py:777` | numeric-series | Override cases using labels from the UI option series | confirmed (tied to finding A; update with Task 3) |

## Documents

| Location | Class | Description | Assessment |
| --- | --- | --- | --- |
| `README.md:93` | manual | Altitude boundary value inside a workflow diagram | resolved (this slice; value neutralized) |
| `README.md:99-104` | value-near-table-id | Advisory threshold and treatment behavior stated with table identifiers | resolved (this slice; values neutralized) |
| `README.md:139,148-152` | value-near-table-id | Frequency boundary and reinforced treatment behavior stated directly | resolved (this slice; values and treatment wording neutralized) |
| `diff-readable.tex:49-84` (12 flagged lines) | value-near-table-id | Generated report diff pairing real calculated results with source table locators | resolved (this slice; file deleted, finding E) |
| `docs/superpowers/plans/2026-08-02-project-defaults-netclass-ui.md:14,38-64` | text-numeric-series, value-near-table-id | Complete normative option series reproduced inline and as a list | resolved (this slice; series replaced by pointers to the approved package, finding D) |
| `docs/superpowers/specs/2026-08-02-project-defaults-netclass-ui-design.md:13,28` | manual | References the normative option series and one option label | resolved (this slice; finding D) |
| `docs/superpowers/plans/2026-08-01-pcb-iec-workflow-correction.md:529,588` | value-near-table-id | Normative boundary statements next to table identifiers | resolved (this slice; boundaries neutralized, table identifiers retained) |
| `docs/superpowers/specs/2026-08-01-pcb-iec-workflow-correction-design.md:66,72,200,251` | value-near-table-id | Normative boundary statements next to table identifiers | resolved (this slice; boundaries neutralized, table identifiers retained) |
| `docs/superpowers/plans/2026-08-02-a2-altitude-range-fix.md:5,7,36,37` | value-near-table-id | Boundary statements; line 37 additionally stated a verified real-package factor value | resolved (this slice; the factor value formerly stated at line 37 now referenced only as package-defined) |
| `docs/superpowers/plans/2026-08-10-iec62477-slice-d.md:680` | text-numeric-series | Source column index tuple | allowed-structural |
| `docs/superpowers/specs/2026-08-07-iec62477-foundation-design.md:29` | text-numeric-series | Table identifier list | allowed-structural |
| `docs/report-and-pairs-improvements-spec.md:80-81` | manual | Example report line with distances | synthetic-ok (reviewed this slice: round invented example labels, no source locators, and they do not match any real generated output) |

Resolved rows above were fixed by the issue #40 Task 6 documentation slice:
stated boundaries, thresholds, factors, and the option series were replaced by
neutral references to the approved `.icrules` package and its semantic rules;
permitted structural locators (table/annex identifiers) were kept. Line
references in resolved rows are historical and point at the neutralized text.

## Boundary properties not yet true

These belong to issue #40 tasks that are still open; they are inventoried
here instead of being asserted by `tests/test_content_boundaries.py`:

- UI option lists supplied entirely by a rules package (Task 3; blocked on
  #34 slice D content).
- Reinforced policy values supplied entirely by a rules package (Task 4).
- Public fixtures free of real table axes/cells (Task 5).
- Public docs/README free of normative statements (Task 6; the confirmed
  Documents-section entries above are resolved, README restructuring stays
  with issue #41).
- Neutralized importer recipe labels (Task 7; collides with in-flight #53).
- The scanner running with `--strict` in CI (Task 8 remainder/Task 11; only
  after the migrations above land).

## Input to the git-history decision (Task 10)

Confirmed content has lived in the history of these paths since their
introduction (~387 commits; no private binary artifact was ever committed):

- `src/insulation_coordination/ui/value_options.py`
- `src/insulation_coordination/calculation/clearance.py`
- `tests/calculation/conftest.py`
- `docs/superpowers/plans/2026-08-02-project-defaults-netclass-ui.md` and its spec
- `diff-readable.tex`
- `src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py`,
  `iec60664_4_2005.py`

See `docs/git-history-treatment.md` for options and recommendation.
