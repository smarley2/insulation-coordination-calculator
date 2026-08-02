# A.2 Altitude Range Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Ensure imported A.2 altitude tables declare their canonical row-axis range so calculations above 2,000 m work with checksum-valid rules packages.

**Architecture:** Keep the calculation-side A.2 contract strict. Populate each imported table's supported range at the projection boundary from its typed row axis, then regenerate the pinned local rules archive and update the project pin. Add importer and 5,000 m regression coverage.

**Tech Stack:** Python 3.12, Pydantic rule models, pytest, deterministic `.icrules` archives.

## Global Constraints

- Do not weaken `_validate_a2_altitude_rule`.
- Derive ranges from parsed axis values; do not hard-code A.2 values in the calculator.
- Preserve archive checksums and project/package identity consistency.
- Use the existing package writer for archive regeneration.

---

### Task 1: Make imported tables declare row-axis ranges

**Files:**
- Modify: `src/insulation_coordination/rules/importer/projection.py`
- Test: `tests/rules/test_importer.py`

- [x] Add a failing assertion that reviewed imported tables expose one row-axis `SupportedRange` matching the first and last row values.
- [x] Run the focused importer test and confirm it fails because ranges are empty.
- [x] Add the shared `SupportedRange` projection to both normal and legacy table paths.
- [x] Run the focused importer test and confirm it passes.

### Task 2: Add the 5,000 m calculation regression

**Files:**
- Test: `tests/calculation/test_high_frequency.py`

- [x] Extend the synthetic A.2 table through `5000 m` and add the altitude regression.
- [x] Assert the synthetic A.2 factor is applied at `5000 m`; the real package is separately verified with factor `1.48`.
- [x] Run the focused calculation test.

### Task 3: Regenerate the local pinned rules package

**Files:**
- Modify: `rules/RulesTest1.icrules`
- Modify: `projects/test1.icproj`

- [x] Add the row-axis range to the existing A.2 table through the typed package model.
- [x] Write the archive with `write_rule_package` and verify it reloads and validates.
- [x] Update the project SHA-256 pin to the regenerated archive digest.
- [x] Verify the application package performs the 5,000 m calculation.

### Task 4: Run the complete verification suite

- [x] Run importer and calculation tests.
- [x] Run the full pytest suite.
- [x] Confirm only the intended source, test, plan, project, and rules-package changes are present.
