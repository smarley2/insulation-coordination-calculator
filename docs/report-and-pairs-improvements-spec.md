# Pairs Page and Human-Readable Report Specification

## Purpose

Improve the Pairs workflow and generated report after a project is loaded. The
Pairs page must remain usable at the current window size, calculation failures
must be visible to the user, and the report must explain the results in terms
of net-class pairs rather than internal identifiers.

## Decisions

- Pair-specific values continue to be stored as pair overrides. Project
  defaults remain inherited until a pair override is entered.
- Recalculation is all-or-nothing. A missing required input blocks the whole
  recalculation and reports every affected human-readable pair and field.
- Calculation groups and results use `net-class ↔ net-class` labels. UUIDs and
  result hashes are implementation details and are not shown in the human
  report or primary calculation lists.
- The matrix parameter selector includes required clearance and required
  creepage. Their cells show an em dash until a successful calculation exists.
- An explicit project default of `printed_wiring` confirms the construction
  classification. It must not create the PCB construction warning or its
  duplicate verification requirement.
- The report is human-first. Raw semantic IDs, result hashes, symbolic
  formula traces, and low-level transformation steps remain available to the
  calculation model but are not rendered in the PDF.

## Pairs page behavior

### Window and layout

Loading a project and navigating Project → Pairs, Pairs → Project, and back
must preserve the main window's maximized state and outer geometry. The page's
splitters may redistribute space inside the available page, but child size
hints must not enlarge the main window or force a horizontal layout outside the
viewport.

The page keeps three independent regions:

1. a coverage matrix and pair list;
2. a vertically scrollable selected-pair editor;
3. calculation groups and results.

The coverage matrix and pair list must not overlap. The editor's vertical
scrollbar must expose all voltage and parameter controls at laptop-height
windows. N/A controls remain in the voltage rows, aligned to the right of the
corresponding voltage input.

### Recalculation validation

Before calling the calculation engine, the page resolves every pair against
project defaults and validates every required input. Validation errors are
collected and shown in one user-facing error dialog. Each error includes the
human pair label and the missing or invalid field, for example:

`HVP ↔ PE — Frequency is required.`

No partial results, groups, or matrix result values are published when any
pair fails validation. Existing results are cleared or marked stale when a
calculation is blocked.

### Groups and results

The calculation review uses labels such as:

- `Group 1 — 2 pairs`
- `HVP ↔ HVN`
- `HVP ↔ PE: clearance 3.0 mm, creepage 5.0 mm`

Group membership is visible to a human without opening a tooltip or decoding
a hash. Internal IDs may remain in tooltips or diagnostic logs only if needed
for troubleshooting.

### Matrix values

The selector contains the existing coverage, voltage, and effective-parameter
options plus:

- `Required clearance`
- `Required creepage`

After calculation, each applicable pair cell displays the calculated value in
millimetres. Before calculation or when no result is available, it displays
`—`. Selecting a matrix cell still loads that pair into the editor.

## Report structure

The report receives a clickable table of contents after the title page.

### Chapter 4: Pair Comparison Matrices

The large authoritative pair table is removed. Chapter 4 begins with a short
summary of characteristics common to every pair. A characteristic is listed
there only when its effective value is identical for all pairs.

For each characteristic whose value differs, the report renders a square
net-class × net-class matrix. Diagonal cells contain an em dash; pair cells
contain the value for that net-class pair. The generated matrices cover the
effective inputs, voltage stresses, required clearance, and required creepage.
Only matrices with a real difference are rendered.

The matrix layout uses bounded, wrapping columns and ordinary portrait pages
where possible. It must not contain unbreakable UUIDs, hashes, or raw semantic
paths that can run past the page edge.

### Chapter 5: Grouped Calculations

Groups are named in display order (`Group 1`, `Group 2`, …) and include their
human-readable pair members. Each pair section contains:

- the pair name;
- concise effective conditions and voltage stresses;
- candidate distances with readable labels;
- the selected clearance and creepage values;
- short paragraphs explaining the rule selection, corrections, and governing
  result;
- standards and table references where they support the decision.

The report does not render pair UUIDs, result hashes, raw semantic paths, raw
symbolic/substituted formulas, or every internal trace step. Explanations must
use ordinary prose. When a source or rule reference is shown, it is formatted
as a readable reference rather than a colon-delimited machine path.

### Chapter 6: Advisories

Warnings and verification requirements with the same code are deduplicated.
The printed-wiring confirmation is not emitted when `printed_wiring` is an
explicit project default or pair setting. If no genuine advisories remain,
Chapter 6 is omitted. If advisories remain, each is written once with a short
human explanation and its supporting standard reference.

### Chapter 7: Rules Package Provenance

The chapter retains the rules package identity and source-document information
needed to identify the calculation basis. The Approval Records subsection is
removed; there is no Chapter 7.2.

## Data and rendering boundaries

The report model continues to validate the complete calculation snapshot and
retain the full engine trace for correctness checks. A separate human-facing
view is derived for rendering. This keeps authoritative recalculation and
staleness checks intact while preventing internal IDs and audit serialization
from controlling the document layout.

Pair labels are derived from the project net-class names in one place and are
used consistently by the Pairs page, report matrices, groups, results, and
error messages.

## Verification

Automated tests cover:

- outer-window maximized state and geometry across project load and navigation;
- non-overlapping matrix/pair regions and editor scrolling;
- all-or-nothing missing-frequency validation;
- human group and result labels;
- calculated clearance and creepage matrix values;
- common-versus-different Chapter 4 matrix generation;
- readable Chapter 5 output with no UUIDs, hashes, or raw paths;
- suppression and deduplication of printed-wiring advisories;
- removal of Chapter 7.2;
- LaTeX compilation and rendered PDF visual inspection for overflow.
