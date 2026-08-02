# Pairs and Report Readability Follow-up Design

## Goal

Make recalculation failures explicit when no rules package is loaded, and make the generated report distinguish project/default comparison data from pair-input voltage data while removing duplicated group detail.

## Approved behavior

1. The Pairs page must show a blocking error when Recalculate is pressed without an approved rules package. The message must tell the user to load the rules package before retrying.
2. Chapter 4 must always render square matrices for the four pair-input voltage stresses: long-term RMS, steady-state peak, recurring peak, and temporary overvoltage peak. These values remain matrices even when every pair has the same value because they are pair inputs, not project defaults.
3. Project/default-derived characteristics continue to use the existing human-readable behavior: one common-value list when equal, otherwise one comparison matrix.
4. Chapter transitions use page breaks before Chapters 4 and 5. Each group subsection in Chapter 5 (`5.x`) starts on a new page.
5. Calculation groups are formed from the complete identity-free calculation signature. All pairs in a group therefore share the calculation conditions, voltage stresses, candidate distances, and final distances. Chapter 5 will list the pair names once under each group and render one shared calculation block; redundant `5.x.x` pair subsections are removed.
6. Candidate tables use flexible text columns and compact natural-width stress/distance columns. The report wording must say “altitude correction was not needed” when no correction was applied.

## Boundaries

- Preserve authoritative report validation and internal calculation traces.
- Keep human-facing pair/group labels; do not expose pair IDs, signatures, or package UUIDs in the PDF.
- Keep UI and report changes covered by focused regression tests.
- Do not modify user-generated `audit/`, `projects/`, or `tmp/` contents.

## Verification

- Add a UI regression test for missing rules on Recalculate.
- Add human-view/template tests proving all four voltage matrices are present and group calculations are rendered once.
- Run the full pytest suite and Ruff.
- Compile and visually inspect a representative multi-pair PDF for page breaks, matrix presence, compact columns, and absence of overfull boxes.
