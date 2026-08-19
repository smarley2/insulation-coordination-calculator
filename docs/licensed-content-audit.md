# Licensed-content audit inventory

Issue #40, Task 9. Full-repository audit of the public tree for licensed IEC
content, produced from a run of `scripts/scan_licensed_content.py` (109
scanner findings) plus a manual review pass. This inventory lists paths,
line references, detection classes, and neutral descriptions only. It never
restates a licensed value, heading, note, or clause wording; classification
of any entry against the licensed source happens in private sessions only.

- First audited: 2026-08-13. Reconciled: 2026-08-19, after issue #110, issue #40's
  Tasks 4 (#117, #119), 11 and 12, and issue #37's Tasks 9, 10, 11, 14 and 15.
- Command: `uv run python scripts/scan_licensed_content.py .`
- Scanner totals when first audited: inline-factor=2, inline-threshold=7,
  numeric-series=41, source-like-text=28, synthetic-iec-source=2,
  text-numeric-series=3, value-near-table-id=26 (109 findings).
- Scanner totals now: inline-threshold=1, numeric-series=43,
  source-like-text=5, synthetic-iec-source=7, text-numeric-series=2
  (58 findings). Every `value-near-table-id` finding is resolved; the
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
  Issue #40's Task 4 then took **`inline-factor` to zero**: both findings were
  the reinforced treatment factors, and both are now resolved from the approved
  package. The same task dropped `numeric-series` by one, by removing the
  preferred-level series from `calculation/clearance.py`.
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
- Issue #37's Task 14 removed **one manual-review finding the scanner cannot
  see**, in the altitude branch of `report/human_view.py`'s trace-sentence
  builder. It is not a scanner class, so the total is unchanged at 60 across that
  task, and Task 15's five new topology fixtures and their tests added no finding
  of any class and **no fifth identity exception**: they read the existing
  verification fixture's identity rather than declaring a source of their own.
- Tracked private artifacts (`.pdf`, `.icrules`, `.icproj`, `.icdraft`,
  `audit-inventory.json`): none, in the current tree and in the full history.
- Issue #40's Task 12 took `inline-threshold` from three to **one**, and the
  total from 60 to 58. Both resolved entries were the A.2 altitude boundary: the
  altitude a clearance is corrected above, and the constant the shape gate
  compared the table's first row against. Neither figure is in the tree any more.
  The boundary is now the first coordinate of the approved A.2 table's own row
  axis -- the row whose factor the gate proves is unity -- so it is the package's
  statement, and a package carrying no A.2 route blocks the calculation with
  `ALTITUDE_RULE_UNAVAILABLE` rather than quietly returning an uncorrected
  distance. The same task removed a licensed figure from
  `tests/calculation/conftest.py`, whose A.2 fixture had to start at the real
  boundary while the validator demanded it and now invents its own, and added a
  conforming A.2 rule to the shared Part 1 fixture, because every real Part 1
  package states one and the engine now refuses a package that does not.
- Issue #40's Task 11 added no finding. It found three that had never been
  inventoried -- one each in `test_dvc_clause_projection.py`,
  `test_raw_grid_review.py` and `test_semantic_review.py` -- and classified them
  in the table below. The reviewed-finding baseline at the foot of this document
  is now the complete machine-readable list, and CI fails if the tree stops
  matching it; the tables' line references are indicative and go stale.

- **Maintainer rulings, 2026-08-18.** Two long-open items are settled. (1) The four
  `synthetic-iec-source` findings are **not exceptions**: this issue's own content boundary permits
  standard names, edition numbers and source provenance references, so a synthetic fixture naming
  the identity its service gates on is permitted content and the scanner class is an over-broad
  heuristic. Their rows are reclassified below; the formal decision record is below. (2) The
  Git-history treatment is **cleanup-only**, recorded in `docs/git-history-treatment.md`. (3) Two
  rows carrying `confirmed (finding A)` were stale — Task 3 removed that series in #92 — and are
  corrected below.

## Decision record: DVC/synthetic-iec-source identity exception

A public fixture must claim a real IEC standard identity (name and edition) wherever the
runtime it exercises gates on that identity — `DvcGuidanceService` and its siblings check both
standard *and* edition, so a fixture with no identity could not exercise the accept path or the
wrong-edition refusal at all, and removing the identity would delete the tests that prove the
gate exists. Four `synthetic-iec-source` fixtures now carry one for exactly this reason (the DVC,
supply, verification, and verification-topology fixtures inventoried below).

- [x] Maintainer decision: **bless the exception**
- Decided by: Fabio Posser
- Date: 2026-08-19
- Notes: a standard name and edition number are explicitly on this issue's own permitted list, and
  none of the four fixtures reproduce a licensed value, heading, note, or clause phrase — only the
  identity two typed fields need to gate on. The alternative, an identity injectable from outside
  `src/` purely so a fixture could avoid stating a real standard name, would add production
  indirection whose only purpose is satisfying a scanner heuristic, which is a worse trade than
  keeping the identity and reviewing what sits beside it. Standing condition, to keep the exception
  narrow: it covers the standard identity only — name and edition — and any fixture that claims an
  IEC standard identity must still carry no licensed value, heading, note, or prose beside it. A
  fixture that pairs the identity with a real cell, series, or heading is a new finding, not covered
  by this decision.

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
| `src/insulation_coordination/ui/value_options.py:14` | numeric-series | Complete constrained option series with unit labels, offered by the UI | resolved (issue #40 Task 3, #92; the series is gone from the module, which now names only the row-axis identifier an approved package publishes the levels under. This row was left stale and is corrected 2026-08-18) |
| `src/insulation_coordination/ui/value_options.py:24-30` | manual | `POLLUTION_OPTIONS` and `MATERIAL_OPTIONS` tuples, the two option lists that remain in the module now that the impulse levels come from the package | resolved (issue #40 Task 3, private-session review concluded 2026-08-19; both tuples are category labels — pollution-degree numbers 1-2 and material-group letters I/II/IIIa/IIIb — not normative values. This issue's own ownership boundary already permits "units and generic concepts such as voltage, RMS, peak, DVC, OVC, pollution degree" in public source, and a material-group identifier is the same class of generic vocabulary. Neither tuple pairs a value with a table or clause identifier, and which subset of degrees this product offers is a product-scope choice, not licensed content) |
| `src/insulation_coordination/calculation/clearance.py:132` | numeric-series | Preferred-level series used by the reinforced treatment | resolved (issue #40 Task 4, #117; the series is read off the row axis of the requirement the treatment rule refers to, and no series remains in the module) |
| `src/insulation_coordination/calculation/clearance.py:155` | inline-factor | Reinforced stress multiplier in calculation code | resolved (issue #40 Task 4, #117; the factor comes from the approved package, and an absent, unapproved or incompatible package blocks instead of falling back) |
| `src/insulation_coordination/calculation/clearance.py:146-166` | manual | Treatment trace wording and symbolic text mirror the source procedure rather than neutral application text | resolved (issue #40 Task 4, #117; the step now states what this application did and names the rule that decided it) |
| `src/insulation_coordination/calculation/creepage.py:144` | inline-factor | Reinforced creepage multiplier in calculation code | resolved (issue #40 Task 4, #117; same route, resolved from the same package) |
| `src/insulation_coordination/report/human_view.py:1054` | manual | Report projection restated the creepage treatment in a sentence written into public source | resolved (issue #40 Task 4, #119; both treatment operations now render the trace step's own rule-backed reason. Found while closing Task 4, so it was never inventoried as a finding) |
| `src/insulation_coordination/calculation/engine.py:180` | inline-threshold | High-frequency routing boundary as a literal | confirmed (finding B class; investigated in issue #40 Task 12 and deliberately left. The approved package *does* state a frequency boundary, in the row matchers of `iec62477_2022.high_frequency.applicability`, but that rule is IEC 62477-1 Annex F's own applicability statement while this constant gates the IEC 60664-4 routines; it includes its lower bound where the constant excludes it; and it answers a three-input question whose answer differs from a frequency-only gate for impulse and temporary-overvoltage stresses and above the annex's upper bound. Reading only the part of it that agrees would be a migration in name. What is missing is an IEC 60664-4 scope rule: `recipes/iec60664_4_2005.py` extracts the annex's equations but no clause stating the frequency below which Part 4 says nothing, so this needs an extraction step under `rules/importer/`, now tracked in issue #133) |
| `src/insulation_coordination/calculation/engine.py:387` | inline-threshold | Partial-discharge advisory trigger as a literal | confirmed (finding B class; investigated in issue #40 Task 12 and deliberately left. No resolved rule states this trigger. The advisory's own `semantic_rule_id` names a rule no package carries, the F.9 table it cites is keyed by the same row axis as F.8 so no axis edge supplies the figure, and `iec62477_2022.test.partial_discharge.applicability` answers whether a partial-discharge *test* is required, which is a different question. What is missing is an extracted IEC 60664-1 Annex F clause rule and a semantic identifier for it -- again an extraction step under `rules/importer/`, now tracked in issue #133. The warning's wording states the trigger in words as well as the comparison stating it as a numeral; both go together when the rule arrives) |
| `src/insulation_coordination/calculation/engine.py:386`, `high_frequency.py:104,257,649` | inline-threshold | The Part 4 frequency boundary, stated as a literal in four comparisons | resolved (issue #37 Task 9; the four comparisons now read one named `PART4_FREQUENCY_THRESHOLD_HZ` in `high_frequency.py`, and the value is stated once. Still a finding-B-class boundary in a single place rather than four, and it remains a candidate for a package-supplied figure) |
| `src/insulation_coordination/calculation/high_frequency.py:462` | inline-threshold | Altitude-correction base boundary as a literal | resolved (issue #40 Task 12; the altitude a clearance is corrected above is read off the row axis of the A.2 table the approved mapping already resolves, and a package that states no A.2 route blocks the calculation instead of skipping the correction in silence) |
| `src/insulation_coordination/report/human_view.py` (altitude branch of the trace-sentence builder) | manual | Report sentence stated the A.2 altitude boundary as a numeral; no table identifier sits nearby, so no scanner class fires | resolved (issue #37 Task 14; the sentence now says the boundary the named rule states was checked and not exceeded, and states no figure) |
| `src/insulation_coordination/report/human_view.py` (reinforced-creepage branch of the trace-sentence builder) | manual | Report sentence spells the reinforced creepage factor out as a word, which the numeral heuristics do not see | confirmed (finding B class; owned by a separate workstream and deliberately untouched by issue #37 Task 14 to avoid two sessions editing one function) |
| `src/insulation_coordination/calculation/high_frequency.py:601` | inline-threshold | Altitude table boundary validation constant | resolved (issue #40 Task 12; the shape gate no longer compares the first row against a figure. It still requires a unity factor on that row, which is what makes the row readable as the boundary the correction is referred to -- a structural expectation, not a value) |

The `inline-threshold` entries extend finding B: they are comparison
constants rather than multiplicative factors, but the same migration rule
applies (semantic rule in `.icrules`, blocking behavior when absent). Issue
#40's Task 12 resolved the two altitude entries and left the other two where
they were, for the reasons written into their rows: both of the remaining ones
need a value the importer does not extract yet, and neither is a constant a
consumer can simply stop writing down.

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
| `tests/fixtures/synthetic_rules.py:1047,1264` | synthetic-iec-source | The DVC fixture package claims a real IEC standard identity as its source reference resolved (2026-08-18, maintainer ruling). Not an exception after all: this issue's own content boundary permits **standard names and edition numbers** and **source provenance references**, which is exactly what the fixture carries. The `synthetic-iec-source` class is an over-broad heuristic — cheap to raise and cheap to review — not a finding. The fixture must carry the identity because the service gates on standard *and* edition, so without it neither the accept path nor the wrong-edition refusal is testable; its document id and note say it is synthetic, and every value in it is invented |
| `tests/fixtures/synthetic_rules.py:1311,1644` | synthetic-iec-source | The supply fixture package claims a real IEC standard identity as its source reference resolved (2026-08-18, maintainer ruling). Not an exception after all: this issue's own content boundary permits **standard names and edition numbers** and **source provenance references**, which is exactly what the fixture carries. The `synthetic-iec-source` class is an over-broad heuristic — cheap to raise and cheap to review — not a finding. The fixture must carry the identity because the service gates on standard *and* edition, so without it neither the accept path nor the wrong-edition refusal is testable; its document id and note say it is synthetic, and every value in it is invented |
| `tests/fixtures/synthetic_rules.py:1806,2044` | synthetic-iec-source | The verification fixture package claims a real IEC standard identity as its source reference resolved (2026-08-18, maintainer ruling). Not an exception after all: this issue's own content boundary permits **standard names and edition numbers** and **source provenance references**, which is exactly what the fixture carries. The `synthetic-iec-source` class is an over-broad heuristic — cheap to raise and cheap to review — not a finding. The fixture must carry the identity because the service gates on standard *and* edition, so without it neither the accept path nor the wrong-edition refusal is testable; its document id and note say it is synthetic, and every value in it is invented |
| `tests/fixtures/synthetic_rules.py:2008` | numeric-series | The verification fixture's invented curve points and axis bounds | synthetic-ok (issue #37 slice 1; the heuristic fires on any numeric container in a file naming an IEC identifier, and the file must keep those identifiers because the adapter resolves rules by exactly those strings) |
| `tests/fixtures/verification_topologies.py:271` | synthetic-iec-source | The verification topology fixture's dielectric package claims a real IEC standard identity as its source reference resolved (2026-08-18, maintainer ruling). Not an exception after all: this issue's own content boundary permits **standard names and edition numbers** and **source provenance references**, which is exactly what the fixture carries. The `synthetic-iec-source` class is an over-broad heuristic — cheap to raise and cheap to review — not a finding. The fixture must carry the identity because the service gates on standard *and* edition, so without it neither the accept path nor the wrong-edition refusal is testable; its document id and note say it is synthetic, and every value in it is invented |
| `tests/fixtures/topology_examples.py:69` | numeric-series | Synthetic project input triples | synthetic-ok |
| `tests/rules/importer/iec62477_2022/test_annex_f_recipes.py:107-109` | numeric-series | Page numbers and expected grid shapes | allowed-structural |
| `tests/rules/importer/iec62477_2022/test_dvc_clause_projection.py` | numeric-series | A synthetic clause spec's page number and bounding box | allowed-structural (added in Task 11; the same shape as the recipe clause spec containers, with an invented clause identifier) |
| `tests/ui/test_raw_grid_review.py` | numeric-series | Invented axis-selector proposal indexes and digest placeholders | synthetic-ok (added in Task 11) |
| `tests/ui/test_semantic_review.py` | numeric-series | A synthetic clause spec's page number and bounding box | allowed-structural (added in Task 11; the `test_dvc_clause_projection.py` row again) |
| `tests/rules/test_evaluator.py:616` | numeric-series | Synthetic trace-formatting expectations | synthetic-ok |
| `tests/rules/test_importer.py:205,811` | numeric-series | Synthetic PDF recipe and compound-cell fixtures | synthetic-ok |
| `tests/test_end_to_end.py:83` | numeric-series | Synthetic project pair inputs | synthetic-ok |
| `tests/ui/test_pair_workflow.py:777` | numeric-series | Override cases using labels from the UI option series | resolved (issue #40 Task 3, #92; the labels now come from the fixture package's axis, not from a constant in public source. Row left stale and corrected 2026-08-18) |

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

This section inventories issue #40 tasks still open, instead of asserting
them in `tests/test_content_boundaries.py`. None remain open as of
2026-08-19; the last one is listed under "Done since the first audit" below.

Done since the first audit:

- UI option lists supplied entirely by a rules package (Task 3). The impulse
  levels come from the approved package, since #92. What was left in
  `ui/value_options.py` — the pollution-degree and material-group label
  tuples — was reviewed in a private session on 2026-08-19 and found to be
  generic vocabulary, not licensed content; see the corresponding
  `value_options.py:24-30` row above.

- The scanner running with `--strict` in CI (Task 11). See the baseline section
  at the foot of this document.

- Public fixtures free of real table axes/cells (Task 5), except the one
  documented DVC identity exception above.
- Public docs/README free of normative statements (Task 6; README
  restructuring stays with issue #41).
- Reinforced policy values supplied entirely by a rules package (Task 4).
  `calculation/reinforced_rules.py` resolves both treatment routes from the
  approved package and raises a typed block naming every reason a package
  cannot answer; nothing falls back to a constant, and the report renders the
  resulting step's own reason (#117, #119).
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

## Reviewed-finding baseline (Task 11)

`.github/workflows/ci.yml` runs
`uv run python scripts/scan_licensed_content.py . --strict` on every push and
pull request. `--strict` does **not** fail on findings -- every finding below is
classified in the tables above, and a gate that fires on known-good input gets
switched off within a week. It fails when the tree stops agreeing with the block
below, in either direction:

- a **new** finding fails the build, because nobody has classified it yet;
- a **gone** finding fails the build too, because a reviewed finding that was
  resolved leaves a row in the tables above saying something untrue. Making that
  a warning would be quieter and would let the record rot, which is the failure
  mode this document exists to prevent. It costs the person who fixed the leak
  one run of `--update-baseline` and one row of prose, at the moment they are the
  only person who knows what changed.

The key is path plus category, never line number: findings move down a file
whenever anything above them is edited, and several line references in the tables
above are already stale for exactly that reason. A count per path and category is
stable under those moves and still changes the instant a finding appears or
disappears.

The baseline lives here rather than in a file of its own so that the counts and
the prose classifying them cannot disagree. Only the fenced block is machine-read,
one `path category count` per line; the scanner never parses the prose or the
tables.

**What a green gate does not mean.** The scanner reads `git ls-files`, so an
untracked or unstaged file is never scanned -- a copy staged into `docs/`
reported clean until it was committed. It matches numerals, so a licensed value
written as a word evades it; that is how the reinforced creepage factor sat in
`report/human_view.py` as a word. And `value-near-table-id` needs a table or
clause identifier beside the value, so a bare figure in a trace sentence evades
it; that is how the altitude boundary sat in the same module. All three were
found by reading, not by the tool, and are deliberately not fixed here: a
word-detector would be a research project and a false-positive machine. A passing
build means no new *structural* finding, not a clean tree. The scanner prints the
same warning on every run, CI included.

<!-- scanner-baseline: regenerate with `uv run python scripts/scan_licensed_content.py . --update-baseline` -->

```text
docs/superpowers/plans/2026-08-10-iec62477-slice-d.md text-numeric-series 1
docs/superpowers/specs/2026-08-07-iec62477-foundation-design.md text-numeric-series 1
src/insulation_coordination/calculation/engine.py inline-threshold 1
src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py numeric-series 2
src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py numeric-series 2
src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py source-like-text 2
src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/clauses.py numeric-series 1
src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/clauses.py source-like-text 2
src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/high_frequency.py numeric-series 1
src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/procedures.py numeric-series 2
src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/reinforced.py numeric-series 1
src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/spacing.py numeric-series 2
src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py numeric-series 1
src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/supply.py source-like-text 1
src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py numeric-series 2
tests/calculation/conftest.py numeric-series 6
tests/calculation/test_high_frequency.py numeric-series 4
tests/calculation/test_part1.py numeric-series 1
tests/fixtures/synthetic_rules.py numeric-series 6
tests/fixtures/synthetic_rules.py synthetic-iec-source 6
tests/fixtures/topology_examples.py numeric-series 1
tests/fixtures/verification_topologies.py synthetic-iec-source 1
tests/rules/importer/iec62477_2022/test_annex_f_recipes.py numeric-series 3
tests/rules/importer/iec62477_2022/test_dvc_clause_projection.py numeric-series 1
tests/rules/test_evaluator.py numeric-series 1
tests/rules/test_importer.py numeric-series 2
tests/test_end_to_end.py numeric-series 1
tests/ui/test_pair_workflow.py numeric-series 1
tests/ui/test_raw_grid_review.py numeric-series 1
tests/ui/test_semantic_review.py numeric-series 1
```
