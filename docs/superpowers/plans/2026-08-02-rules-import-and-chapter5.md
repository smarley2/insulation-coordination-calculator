# Rules Import and Chapter 5 Group Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let maintainers load the supplied IEC PDFs safely, including PDFs unlockable by an empty or user-entered password, and make Chapter 5 explain every calculation group, its pairs, and its applied rules.

**Architecture:** Keep password handling at the importer/UI boundary: `identify_standard` accepts an optional password, tries the empty password automatically, and raises a non-sensitive password-required error when unlocking fails. `RulesManagerWindow` retries with a masked in-memory prompt. Extend the existing human report projection with deduplicated rule descriptions and render a Chapter 5 index plus per-group rules list; keep the validated calculation model and trace unchanged.

**Tech Stack:** Python 3, pypdf, PySide6, dataclasses, Jinja2 LaTeX templates, pytest, Ruff, Tectonic.

## Global Constraints

- Do not bypass non-empty PDF passwords or weaken standard identity checks.
- Keep PDF source bytes and user passwords out of saved rule packages and logs.
- Preserve existing report validation and internal calculation traces.
- Do not modify user-generated `audit/`, `projects/`, or `tmp/` contents.

---

### Task 1: Safe encrypted-PDF identification and UI retry

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/importer/__init__.py`
- Modify: `src/insulation_coordination/ui/rules_manager.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py`
- Test: `tests/rules/test_importer.py`
- Test: `tests/ui/test_project_pages.py`

**Interfaces:**
- `identify_standard(path: Path, password: str | None = None) -> StandardIdentity` attempts `password or ""` only when the reader is encrypted and raises `PasswordRequiredError(path, supplied=bool(password))` when decryption fails.
- `extract_draft(paths: tuple[Path, ...], passwords: Mapping[Path, str] | None = None) -> ImportedRuleDraft` passes each path's transient password to identification.
- `PasswordRequiredError` exposes only the PDF path and a password-state message; it never stores or prints the password.

- [x] **Step 1: Write failing importer tests** for an encrypted synthetic PDF that opens with an empty password, a PDF that rejects an empty password, and a PDF that succeeds with the supplied password; assert error messages contain no password.
- [x] **Step 2: Run the focused importer tests** with `pytest tests/rules/test_importer.py -k 'password or encrypted' -q`; confirm the new cases fail before implementation.
- [x] **Step 3: Implement password-aware pypdf loading** using `PdfReader.decrypt(password or "")`, keeping the existing size, PDF-header, page-count, and identity checks intact; add the `PasswordRequiredError` export.
- [x] **Step 4: Add transient password mapping to extraction** and implement the Rules Manager retry loop with `QInputDialog` masked input, cancel handling, and a clear critical error for wrong/cancelled passwords.
- [x] **Step 5: Correct the supplied recipe fingerprints** to 172 pages for IEC 60664-1 Edition 3.0 2020-05 and 138 pages plus `Second edition` for IEC 60664-4 2005-09.
- [x] **Step 6: Run the focused importer and UI tests** and verify that the existing unsupported-PDF dialog behavior remains unchanged.
- [x] **Step 7: Commit** with `feat: support password-protected standard PDFs`.

### Task 2: Chapter 5 group index, pair membership, and rule descriptions

**Files:**
- Modify: `src/insulation_coordination/report/human_view.py`
- Modify: `src/insulation_coordination/report/templates/report.tex.j2`
- Test: `tests/report/test_human_view.py`
- Test: `tests/report/test_latex.py`

**Interfaces:**
- Add `HumanRule(description: str, source_reference: SourceReference | None)`.
- Extend `HumanGroup` with `rules: tuple[HumanRule, ...]`.
- Build one deduplicated `HumanRule` per semantic calculation rule/operation, using readable descriptions and retaining the first source reference.

- [x] **Step 1: Write failing report tests** asserting each human group has rules, the rendered Chapter 5 starts with a group index containing every pair, and the rendered group contains a `Rules applied` list with source text.
- [x] **Step 2: Run the focused report tests** with `pytest tests/report/test_human_view.py tests/report/test_latex.py -q`; confirm the new assertions fail.
- [x] **Step 3: Implement `HumanRule` projection** with readable mappings for the IEC clearance, creepage, altitude, and calculation-selection rule IDs plus a sentence fallback for other trace steps.
- [x] **Step 4: Render the Chapter 5 index and per-group rule list** before the shared calculation block, preserving human pair labels and omitting internal Pair IDs.
- [x] **Step 5: Change candidate tables** to natural-width candidate, voltage, and distance columns (`lrrX`) for both clearance and creepage candidates.
- [x] **Step 6: Run focused report tests** and inspect generated LaTeX for escaped user text and stable output.
- [x] **Step 7: Commit** with `feat: explain calculation groups in reports`.

### Task 3: Full verification and supplied-standard smoke check

**Files:**
- No source changes expected; generated verification outputs remain under `tmp/` and are not committed.

- [x] **Step 1: Run `pytest -q`** and resolve any regression from the new importer signature or report dataclasses.
- [x] **Step 2: Run `ruff check .`** and fix only source/test lint issues introduced by this work.
- [x] **Step 3: Identify both files in `standards/brusa`** using the new importer path; verify the encrypted Part 1 succeeds through empty-password decryption and the Part 4 edition/page fingerprint is accepted.
- [x] **Step 4: Compile and render a representative report** with Tectonic/Poppler, check for compilation errors, overfull boxes, and readable Chapter 5 group/rule tables.
- [x] **Step 5: Review the diff** to confirm no user-generated `audit/`, `projects/`, `tmp/`, passwords, or PDF bytes are staged.
- [x] **Step 6: Commit any final verification-only source fixes** if needed and report exact test/compile evidence.
