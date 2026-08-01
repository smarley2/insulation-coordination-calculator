# PCB IEC Workflow Correction Design

## Goal

Correct the rules importer and calculation package so the supported PCB workflow
follows IEC 60664-1:2020 Annex G and Annex H, with the applicable IEC 60664-4:2005
high-frequency additions. The review UI must expose faithful source tables and
equations before it permits a usable `.icrules` package to be built.

The correction replaces the current generic numeric flattening. A table is not
valid merely because every extracted token can be converted to a decimal. It is
valid only when its row axis, column branches, units, missing combinations,
footnotes, interpolation policy, and source references match an explicit
semantic contract.

## Confirmed Product Boundary

The software is for printed-circuit-board insulation coordination. Version 1
keeps the planned manual stress boundary: the user supplies the required impulse
withstand voltage and the actual RMS and peak stresses for each net-class pair.
The software does not derive those stresses from nominal mains voltage, supply
topology, or overvoltage category.

Consequently:

- IEC 60664-1 Tables F.1, F.3, and F.4 are not calculation inputs and are not
  imported into the rules package;
- multiline alternatives and ranges in F.3/F.4 cannot be mistaken for scalar
  calculation data;
- every calculation is performed per net-class pair, not once per net class;
  and
- the input boundary is documented in the UI, trace, and README.

## Current Defects Being Replaced

The existing importer and builder are unsafe for real calculations:

- opening the extracted-table dialog incorrectly requires resolution notes;
- one PDF cell is assumed to contain at most one scalar, so `110 / 120 / 127`,
  ranges, grouped thousands, and footnotes are misparsed;
- all numeric cells are flattened into a synthetic one-dimensional
  `raw_sequence`, losing their table meaning;
- headers and footnotes are retained only as untyped display cells;
- IEC 60664-1 F.5, F.8, and A.2 are missing;
- F.3 is incorrectly used as an altitude table and F.4 as a creepage table;
- IEC 60664-4 Table 5 test-circuit data is incorrectly used as a creepage
  table;
- four placeholder prompts are presented as IEC formula constants even though
  functional applicability is a mapping decision and the convergence settings
  are software policy; and
- formula definitions and mappings are constructed before the maintainer can
  inspect their actual semantics.

Existing drafts and approved packages produced by this importer version must
not be treated as valid inputs to the corrected engine.

## Required Source Inventory

### IEC 60664-1:2020

| Source | Imported role |
| --- | --- |
| Table F.2 | Impulse-clearance lookup with field and pollution branches |
| Table F.5, both pages | One joined PCB creepage table |
| Table F.8 | Clearance for steady-state peak, temporary overvoltage, and recurring peak voltage |
| Table A.2 | Clearance altitude correction above 2 000 m |
| Table F.9 | Partial-discharge advisory data |
| Annex G / Clause 5.2 | Clearance workflow and branching contract |
| Annex H / Clause 5.3 | PCB creepage workflow and branching contract |

Table F.10 is not substituted for A.2. Annex G explicitly sends the
above-2 000 m branch to A.2. Values at or below 2 000 m remain governed by the
base clearance tables under the supported workflow.

### IEC 60664-4:2005

| Source | Imported role |
| --- | --- |
| Table 1 | High-frequency inhomogeneous-field clearance |
| Table 2 | Frequency-dependent creepage |
| Equation (1) | Critical frequency derived from the current clearance |
| Equation (2) | Detailed high-frequency voltage factor between critical and minimum frequency |
| Clauses 3.1 and 4.3.1 | Radius-to-clearance field criterion |
| Clauses 4.3 and 4.4 | Homogeneous and inhomogeneous clearance routing |

IEC 60664-4 Table 5 contains test-circuit parameters and is excluded from the
calculation package.

## Source Extraction and Typed Projection

### Recipe contracts

Each supported source has an edition-specific recipe containing only stable
layout anchors, page regions, shape expectations, semantic row/column roles,
units, and validation rules. Licensed numeric data and source prose are still
extracted locally from the PDFs and remain in the private draft/package flow;
they are not committed as source assets.

A recipe declares:

- the logical table ID and every physical page segment;
- row-axis coordinates and unit;
- stable semantic column IDs and human-readable headings;
- header, data, blank, note, and footnote regions;
- expected numeric coverage and unavailable combinations;
- the source-declared interpolation or selection policy; and
- structural assertions such as monotonicity, page-continuation compatibility,
  and complete required branches.

### Raw review representation

Raw extraction preserves every visible cell exactly. Each cell also carries a
semantic role and a parsed representation where appropriate:

- `header`, `data`, `blank`, `note`, or `footnote` role;
- normalized finite decimal value for scalar data;
- separated footnote markers;
- source page, grid row, grid column, and logical table coordinates; and
- parse/review status.

Grouped thousands such as `1 000` normalize to `1000`. A trailing marker such
as `d` remains footnote metadata and never becomes part of a lookup key or
numeric value. Parenthesized rib-reduction alternatives in F.5 remain visible
metadata because rib reduction is outside the automated path.

The corrected calculation inventory no longer contains F.3/F.4, so their
multiline alternatives and ranges require no lossy scalar conversion.

### Multi-page tables

F.5 is one logical table with two physical page segments. Both page segments
are shown during review. The builder verifies identical column semantics and
strictly ordered, non-overlapping voltage rows before joining them. Missing,
duplicated, reordered, or incompatible continuation rows block acceptance.

### Typed table model

Typed tables keep numeric axis coordinates for evaluation and add stable axis
labels for auditability. Categorical branches use stable numeric codes plus
explicit labels; formulas never depend on visible heading text.

Every typed cell contains one numeric value, unit, and exact source reference.
Missing combinations remain missing and cause a range/combination error rather
than silently selecting a neighbor.

The expression model gains the minimum operation required for genuine
two-dimensional behavior. IEC 60664-4 Table 2 can interpolate between frequency
columns only where the source permits it. Voltage-row selection/interpolation
follows the reviewed source policy; the engine never invents interpolation.
The same rule applies to all sources: interpolate only where the standard
explicitly permits it, otherwise perform the declared exact or conservative
boundary selection.

## Equation and Mapping Review

Equation extraction is separate from table extraction. The importer locates
and parses the IEC 60664-4 critical-frequency and frequency-factor equations,
the minimum-frequency statement, and the radius criterion from their anchored
source regions. Their numeric literals are not hidden in public recipe code.

The review UI shows for every equation:

- semantic formula ID;
- rendered equation;
- variables and canonical units;
- applicability and supported range;
- exact standard, edition, clause/equation, and PDF page; and
- the semantic mappings that use it.

The maintainer accepts or rejects the extracted equation and mapping. There is
no dialog asking for unexplained constants.

Functional high-frequency applicability is represented as an approved semantic
mapping, not a fabricated `compare(literal, literal)` formula. Convergence is
algorithm behavior, not IEC source data, and therefore does not appear as an
IEC formula.

## Annex G Clearance Workflow

For each net-class pair:

1. Validate the manually entered impulse voltage, steady-state peak voltage,
   temporary-overvoltage peak, recurring peak, frequency, insulation type,
   field condition, pollution degree, electrode radius when required, and
   altitude.
2. Block coating, potting, or another declared construction condition requiring
   IEC 60664-3 or an unsupported branch.
3. Calculate the impulse candidate from F.2 using the applicable Case A/Case B
   and pollution branch.
4. Calculate each applicable steady-state, temporary, and recurring peak
   candidate from F.8 using the applicable field branch.
5. Apply the Clause 5.2.5 reinforced treatment to the stress before lookup:
   the next preferred impulse withstand level where specified, otherwise the
   prescribed percentage treatment; periodic stresses use the prescribed
   reinforced treatment. Functional insulation follows 5.2.4 without
   basic/reinforced scaling.
6. If frequency exceeds 30 kHz, run the IEC 60664-4 clearance assessment
   described below and add its result as another candidate.
7. Select the largest applicable clearance candidate.
8. When altitude exceeds 2 000 m, interpolate the A.2 factor within its supported
   range and apply it to the governing clearance.
9. Emit the required withstand-test and F.9 partial-discharge advisories without
   silently modifying the selected result.

The trace retains every candidate, omission, scaling decision, table branch,
interpolation, maximum selection, altitude factor, and advisory source.

## IEC 60664-4 Clearance Workflow

The Part 4 threshold and the critical frequency are different decisions.
Frequency above 30 kHz activates the assessment; it does not automatically
produce a larger distance.

For each applicable pair:

1. Start from the relevant Part 1 periodic-voltage clearance.
2. Compute critical frequency from Equation (1) using that pair's current
   clearance, with explicit unit conversion.
3. Compare the pair frequency with its computed critical frequency.
4. For homogeneous or approximately homogeneous fields:
   - below critical frequency, use the 100 % treatment;
   - between critical frequency and the source-defined minimum frequency, use
     Equation (2);
   - at or above the minimum frequency, use the 125 % treatment; and
   - enforce the radius-to-clearance criterion and applicable Case A/Case B
     route.
5. For an inhomogeneous field, retain the Part 1 treatment below critical
   frequency and evaluate Table 1 at or above critical frequency.
6. Recalculate the clearance, recompute critical frequency, and perform the
   possible second iteration described by the standard.
7. Accept the result only when the selected branch, field classification, and
   source-rounded distance are stable. Otherwise block for engineering review.

This removes arbitrary tolerance and iteration-limit prompts. The trace records
the initial clearance, critical frequency, actual frequency, selected branch,
factor, radius ratio, recalculated clearance, and second-iteration result.

## Annex H PCB Creepage Workflow

For each net-class pair:

1. Validate long-term RMS voltage, frequency, insulation type, printed-wiring
   construction, pollution degree, and material classification.
2. Block coating/potting, rib reduction, split materials or pollution degrees,
   floating conductive parts, short-duration reduction, and other unsupported
   Annex H special conditions.
3. Select the joined F.5 printed-wiring branch and its pollution column.
4. Apply only the source-permitted voltage interpolation.
5. Use the selected distance directly for functional, basic, or supplementary
   insulation. Apply twice the selected F.5 distance for reinforced insulation.
6. If frequency exceeds 30 kHz, evaluate IEC 60664-4 Table 2 with its declared
   frequency-column interpolation and pollution multiplier. Missing table
   combinations or values outside the supported range block calculation.
7. Select the largest of the Part 1 creepage, Part 4 creepage, and final
   clearance floor.

The printed-wiring columns in F.5 cover pollution degrees 1 and 2. A PCB case
using pollution degree 3 or 4 is blocked rather than routed through the
different-material columns. Material-group restrictions stated for the PCB
branch are validated explicitly.

## Maintainer UI Workflow

The Rules Manager uses explicit stages:

1. **Import PDFs** creates a private, unusable draft containing raw tables,
   equation candidates, semantic mapping contracts, and review items.
2. **Review extracted tables** opens without requiring notes. It displays
   logical source tables with real headings, semantic column labels, raw values,
   normalized numeric values, footnotes, page segments, and source coordinates.
3. **Accept table** requires resolution notes at the moment the maintainer
   accepts or corrects that table. Canceling or merely viewing records nothing.
4. **Review equations and mappings** is enabled only after every required table
   is accepted. It shows real equations and route contracts with their exact
   references. Acceptance requires notes.
5. **Build reviewed content** is enabled only after table, equation, and mapping
   review is complete. It deterministically projects the approved extraction
   into typed tables, formulas, and mappings; it does not auto-resolve review
   items.
6. **Approve reviewed draft** remains disabled until typed-package validation
   succeeds and every review item is explicitly resolved.

Progress is shown by stage (`tables`, `equations`, `mappings`, and `package`),
not as one confusing total that double-counts source cells and semantic content.
Counts are derived from the corrected recipe inventory and are not hard-coded to
the previous 57/114 values.

## Validation and Failure Behavior

Import/build/approval is blocked when any of the following occurs:

- expected table, continuation page, equation, heading, branch, or unit is
  missing or duplicated;
- a raw value cannot be parsed without losing meaning;
- a correction changes table shape, source identity, or an unflagged cell;
- a required typed combination is blank;
- axes are duplicated, unordered, incompatible across pages, or outside their
  declared range;
- an equation literal, variable, unit, or source reference does not match its
  reviewed contract;
- a semantic route has no single reviewed mapping;
- an unsupported PCB condition is selected;
- Part 4 iteration does not stabilize after the source-described second pass;
  or
- a package was created by the superseded importer/schema and lacks the new
  semantic guarantees.

Errors identify the standard, table/equation, page, logical coordinate, and
expected contract. No failure silently falls back to the first number in a
cell, a neighboring table value, a different material branch, or a placeholder
constant.

## Schema and Compatibility

The importer version and rule schema version are incremented. The archive
validator requires semantic axis labels and the new expression/selection
contracts. Packages from the generic `raw_sequence` importer are rejected by
the corrected calculation trust gate and must be regenerated from the licensed
PDFs.

Project files remain compatible because the manual electrical input boundary
does not change. A project pinned to an obsolete rules package reports a clear
rules-package migration error.

## README and Review Documentation

The README becomes the human entry point for reviewing the implemented
workflow. It includes:

- the manual-input boundary;
- a Mermaid diagram for Annex G clearance;
- a Mermaid diagram for Annex H PCB creepage;
- a Mermaid diagram for the IEC 60664-4 critical-frequency decision and second
  iteration;
- the required table/equation inventory;
- supported, advisory, and blocked cases;
- an explanation of every relevant calculation trace field; and
- a step-to-code matrix linking each documented step to its implementation
  function and focused tests.

The implementation uses stable, narrowly scoped function names so those links
remain reviewable. The intended boundaries are:

- `calculate_pair` for orchestration and final maximum/floor decisions;
- `calculate_annex_g_clearance` for Part 1 clearance candidates;
- `calculate_annex_h_creepage` for PCB creepage candidates;
- `calculate_part4_clearance` for the high-frequency clearance branch;
- `critical_frequency_hz` for Equation (1);
- `apply_altitude_correction` for A.2; and
- dedicated table/equation projection helpers in the importer.

If implementation discovers a better existing boundary, the README links to
the final equivalent function rather than preserving a misleading name.

## Testing

### Importer tests

- opening table review without notes;
- notes required only on acceptance;
- grouped thousands and separated footnote markers;
- F.5 two-page stitching and continuation failures;
- correct semantic axes, labels, units, and missing cells for every required
  source;
- source-permitted versus forbidden interpolation;
- equation and mapping review before build;
- rejection of F.3/F.4 and IEC 60664-4 Table 5 as calculation assets; and
- rejection of packages created by the superseded importer contract.

### Calculation tests

- Annex G impulse and each periodic-voltage candidate;
- Case A/Case B routing and verification advisories;
- functional, basic, and reinforced treatment;
- maximum candidate selection and A.2 boundary/interpolation;
- F.9 advisory conditions;
- critical frequency below, equal to, between, and above the Part 4 branch
  boundaries;
- radius criterion and the second recalculation pass;
- Part 4 inhomogeneous Table 1 route;
- F.5 PCB pollution-degree branches across both pages;
- reinforced creepage doubling and clearance floor;
- Part 4 Table 2 frequency behavior and pollution multipliers; and
- every declared unsupported PCB condition and out-of-range combination.

### Real-PDF verification

The private supplied-standard tests load the actual licensed PDFs and verify:

- the complete required source inventory;
- exact physical shapes and multi-page joins;
- typed axis/branch dimensions and units;
- zero unresolved parse ambiguity before semantic review;
- no orphan typed table, formula, or mapping;
- complete review/build/approve workflow; and
- representative Annex G, Annex H, and Part 4 calculations with trace source
  references.

Qt tests cover stage gating, source-table rendering, semantic headings,
footnotes, corrections, notes timing, equation review, and final approval.

## Success Criteria

- A reviewer can identify what every extracted row and column means before
  accepting it.
- No multiline choice, range, grouped thousands value, or footnote is silently
  converted to the wrong scalar.
- F.5 is complete across both pages.
- F.2, F.8, A.2, F.9, IEC 60664-4 Tables 1/2, and the required equations are
  present and connected only to their intended routes.
- Every supported PCB calculation follows the documented Annex G/H and Part 4
  decisions and produces a source-backed trace.
- Unsupported cases block explicitly.
- Formula review precedes typed-content build.
- The README links each calculation step to the function and tests that
  implement it.
- The complete automated suite and real-PDF workflow pass before the corrected
  package can be described as usable.
