# Licensed-content audit inventory

Issue #40, Task 9. Full-repository audit of the public tree for licensed IEC
content, produced from a run of `scripts/scan_licensed_content.py` (109
scanner findings) plus a manual review pass. This inventory lists paths,
line references, detection classes, and neutral descriptions only. It never
restates a licensed value, heading, note, or clause wording; classification
of any entry against the licensed source happens in private sessions only.

- First audited: 2026-08-13. Reconciled: 2026-08-18, after issue #110, issue #40's
  Task 4, and issue #37's Tasks 9, 10, 11, 14 and 15.
- Command: `uv run python scripts/scan_licensed_content.py .`
- Scanner totals when first audited: inline-factor=2, inline-threshold=7,
  numeric-series=41, source-like-text=28, synthetic-iec-source=2,
  text-numeric-series=3, value-near-table-id=26 (109 findings).
- Scanner totals now: inline-threshold=3, numeric-series=43,
  source-like-text=5, synthetic-iec-source=7, text-numeric-series=2
  (60 findings). Every `value-near-table-id` finding is resolved; the
  `numeric-series` count rose because the fixture rewrite in Task 5 split some
  containers, not because new content was added. The `synthetic-iec-source`
  count rose by two when issue #36's supply fixture joined the DVC fixture in
  the identity exception below, and by two again when issue #37's verification
  fixture joined them for the same reason; the `numeric-series` count rose by
  one with that fixture's invented curve points. No new content came with
  either. It rose by one again with issue #110's reinforced treatment recipe,
  whose clause specs are one more container of page numbers and bounding
  boxes -- the same `allowed-structural` shape the four sibling recipe clause
  spec containers already have, and the only new finding that slice added.
- The `inline-threshold` count **fell by four** in issue #37's Task 9. The
  Part 4 frequency boundary had been written out as a literal in four
  comparisons across `calculation/high_frequency.py` and
  `calculation/engine.py`; it is now the single named constant
  `PART4_FREQUENCY_THRESHOLD_HZ`, which those four comparisons and the new
  partial-discharge review warning all read. Nothing was removed from the
  tree and nothing was neutralized - the same figure is stated once instead of
  four times, so the heuristic that fires on a literal in a comparison no
  longer has one to find. No new finding was introduced by that task or by
  Tasks 10 and 11, and **no fifth identity exception was added**: the three
  new calculation modules and their three new test modules read the existing
  verification fixture rather than declaring a source of their own.
- The `inline-factor` class **is gone entirely** and the total fell from 63 to
  60 in issue #40's Task 4. The two reinforced multipliers that were literals in
  `calculation/clearance.py` and `calculation/creepage.py` are now read from the
  approved package through `calculation/reinforced_rules.py`, and the
  `numeric-series` container beside one of them went with them. This is a
  removal, not a rewording: the figures are no longer in the tree at all.
- Issue #37's Task 14 removed **two manual-review findings the scanner cannot
  see**, both in `report/human_view.py`'s trace-sentence builder. Neither is a
  scanner class, so the total is unchanged at 60 across that task, and Task 15's
  five new topology fixtures and their tests added no finding of any class and
  **no fifth identity exception**: they read the existing verification fixture's
  identity rather than declaring a source of their own.
- Tracked private artifacts (`.pdf`, `.icrules`, `.icproj`, `.icdraft`,
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
| `src/insulation_coordination/calculation/engine.py:386`, `high_frequency.py:104,257,649` | inline-threshold | The Part 4 frequency boundary, stated as a literal in four comparisons | resolved (issue #37 Task 9; the four comparisons now read one named `PART4_FREQUENCY_THRESHOLD_HZ` in `high_frequency.py`, and the value is stated once. Still a finding-B-class boundary in a single place rather than four, and it remains a candidate for a package-supplied figure) |
| `src/insulation_coordination/calculation/high_frequency.py:462` | inline-threshold | Altitude-correction base boundary as a literal | confirmed (finding B class) |
| `src/insulation_coordination/report/human_view.py` (altitude branch of the trace-sentence builder) | manual | Report sentence stated the A.2 altitude boundary as a numeral; no table identifier sits nearby, so no scanner class fires | resolved (issue #37 Task 14; the sentence now says the boundary the named rule states was checked and not exceeded, and states no figure) |
| `src/insulation_coordination/report/human_view.py` (reinforced-creepage branch of the trace-sentence builder) | manual | Report sentence spelled the reinforced creepage factor out as a word, which the numeral heuristics do not see | resolved (issue #37 Task 14; the branch is deleted, and the step's own reason - built by `calculation/reinforced_rules.py` from the resolved rule - is rendered by the fallback instead) |
| `src/insulation_coordination/calculation/high_frequency.py:601` | inline-threshold | Altitude table boundary validation constant | confirmed (finding B class) |

The `inline-threshold` entries extend finding B: they are comparison
constants rather than multiplicative factors, but the same migration rule
applies (semantic rule in `.icrules`, blocking behavior when absent).

## Importer recipes

Do not edit these under this slice; the importer tree is owned by the
in-flight #53 workstream.

| Location | Class | Description | Assessment |
| --- | --- | --- | --- |
| `src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py:145,150-155,207-216,255,297,300,342` | source-like-text | Sentence-case column headings instead of neutral lowercase descriptions | resolved (Task 7; all 25 headings rewritten, private check confirmed every removed label occurred verbatim in the source and no replacement does) |
| `src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py:104,347` | numeric-series | Page numbers, bounding boxes, row/column geometry, expected counts | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py:43,169` | source-like-text | Sentence-case column headings instead of neutral lowercase descriptions | resolved (Task 7; all 10 headings rewritten) |
| `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py:128` | source-like-text | An `identity_anchors` entry, substring-matched against the document's own cover text at `identify.py:745` | allowed-structural (reclassified in Task 7: the document's identity string is permitted, and rewording it breaks identity verification — same class as the `Edition` prefix the scanner already exempts) |
| `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py:272` | source-like-text | A `figure=` locator, confirmed absent from the source and therefore author-invented | false-positive (reclassified in Task 7; left unchanged on purpose — `figure=` flows into `SourceReference` and the rule digest, so relabelling it would force a re-extraction for a cosmetic gain) |
| `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py:131,211` | numeric-series | Structural extraction geometry | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/clauses.py:30` | numeric-series | Structural extraction geometry | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/clauses.py:63,65` | source-like-text | Error-message strings, not source text | false-positive |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/high_frequency.py:54` | numeric-series | Structural extraction geometry | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/procedures.py:72,280` | numeric-series | Grid row indexes and segment geometry | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/reinforced.py:55` | numeric-series | Clause bounding boxes and page numbers (issue #110) | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/spacing.py:175,468` | numeric-series | Grid row indexes and segment geometry | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py:47` | numeric-series | Clause bounding boxes and page numbers | allowed-structural |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py:332` | source-like-text | Project-authored guidance title/summary describing that source notes exist | verify-private (confirm the summary stays descriptive and copies nothing) |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py:408,491` | numeric-series | Structural extraction geometry | allowed-structural |

## Public tests and fixtures

| Location | Class | Description | Assessment |
| --- | --- | --- | --- |
| `tests/calculation/conftest.py` (axis series, cells, altitude and advisory tables, equation constants) | numeric-series, manual | Fixture data formerly taken from real annex tables | resolved (Task 5; data invented, expectations re-derived from the algorithm rather than from output). Remaining `numeric-series` hits are `synthetic-ok`: the heuristic fires on any large numeric container in a file naming an IEC identifier, and these files must keep those identifiers because the engine looks rules up by exactly those strings |
| `tests/calculation/conftest.py` (A.2 first row and first factor) | manual | Structure the engine's own A.2 validator enforces, not free fixture data | allowed-structural (Task 5; marked as structure in the fixture module and in a comment — inventing it would fail validation) |
| `tests/calculation/test_high_frequency.py` | numeric-series | Parametrized expectations bound to the conftest fixtures | resolved (Task 5; moved with the fixtures, re-derived) |
| `tests/calculation/test_part1.py:183` | numeric-series | Expected outputs derived from the synthetic cell scheme | synthetic-ok (re-checked in Task 5: reads the part 1 package's already-invented cells) |
| `tests/domain/test_display.py:67` | numeric-series | Display expectations that included formula constants near Part 4 semantics | resolved (Task 5; the file no longer carries an IEC identifier and clears the scanner outright) |
| `tests/fixtures/synthetic_rules.py:89,252,409,634,1082` | numeric-series | Project-invented axes, cells, and curve points | synthetic-ok |
| `tests/fixtures/synthetic_rules.py:1047,1264` | synthetic-iec-source | The DVC fixture package claims a real IEC standard identity as its source reference | open, deliberately not forced (Task 5). `DvcGuidanceService` refuses any package whose rules lack the expected standard **and** edition, so the fixture must carry that identity for the accept path to exist; dropping it would delete about twenty tests including the refusal case that proves the gate. The fixture references the production constant rather than a literal and marks itself synthetic. Needs either an audit policy decision (assess `synthetic-ok`, naming the gate) or an injectable identity in `src/`. The exception is written into `tests/test_content_boundaries.py`'s docstring so it cannot rot |
| `tests/fixtures/synthetic_rules.py:1311,1644` | synthetic-iec-source | The supply fixture package claims a real IEC standard identity as its source reference | open, deliberately not forced (issue #36 slice 1). Exactly the DVC case, for a second gate: `read_supply_rules` refuses any rule whose source is not the expected standard **and** edition, so the fixture must carry that identity for the accept path — and the wrong-edition refusal — to be testable at all. Values, axes and the frequency are project-invented and the fixture says so. Resolves with the same policy decision or injectable identity the DVC entry needs |
| `tests/fixtures/synthetic_rules.py:1806,2044` | synthetic-iec-source | The verification fixture package claims a real IEC standard identity as its source reference | open, deliberately not forced (issue #37 slice 1). The DVC and supply case again, for a third gate: `read_verification_rules` refuses any rule whose source is not the expected standard **and** edition, so the fixture must carry that identity for the accept path — and the wrong-edition refusal, which needs a package that is right about everything else — to be testable at all. Every value, step and condition is project-invented and the fixture says so. Resolves with the same policy decision or injectable identity the DVC and supply entries need |
| `tests/fixtures/synthetic_rules.py:2008` | numeric-series | The verification fixture's invented curve points and axis bounds | synthetic-ok (issue #37 slice 1; the heuristic fires on any numeric container in a file naming an IEC identifier, and the file must keep those identifiers because the adapter resolves rules by exactly those strings) |
| `tests/fixtures/verification_topologies.py:271` | synthetic-iec-source | The verification topology fixture's dielectric package claims a real IEC standard identity as its source reference | open, deliberately not forced (issue #37 slice 3). The same gate a fourth time: the package it builds is read through `read_verification_rules`, which refuses any rule whose source is not the expected standard **and** edition, so a fixture that omitted the identity could not reach the accept path at all. Its document id is `synthetic-verification-source` and its note says it carries no IEC numeric values. Resolves with the same policy decision or injectable identity the three entries above need |
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
- The scanner running with `--strict` in CI (Task 8 remainder/Task 11; only
  after the migrations above land).

Done since the first audit:

- Public fixtures free of real table axes/cells (Task 5), except the one
  documented DVC identity exception above.
- Public docs/README free of normative statements (Task 6; README
  restructuring stays with issue #41).
- Neutralized importer recipe labels (Task 7). Package identity is unchanged:
  `TableColumnSpec.heading` has exactly one consumer, the review dialog, and
  never reaches an extracted rule or a canonical hash — so no importer version
  bump and no re-extraction were required.

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
