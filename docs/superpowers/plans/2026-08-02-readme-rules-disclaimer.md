# README rules, disclaimer, and contribution guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `README.md` so its rules-data boundary, Rules Manager workflow, user responsibility, private-artifact handling, Tectonic behavior, and contribution paths are accurate and easy to find.

**Architecture:** This is a documentation-only change. Keep the existing technical calculation sections and update the README at the documentation boundaries identified in the approved design: a prominent notice near the introduction, a workflow aligned with the Rules Manager UI, responsibility/contribution sections near the end, and two narrowly scoped wording corrections.

**Tech Stack:** Markdown, repository source/tests as the behavioral reference, Git.

## Global Constraints

- The software contains no IEC rules or licensed standard content.
- Calculations require an approved `.icrules` package.
- Users must create or obtain their organization's approved package through the Rules Manager.
- Internal sharing must follow the organization's standards licence and procedures.
- The user is responsible for checking inputs, rule packages, calculations, and results against applicable standards and project requirements.
- Private artifacts are ignored by default but must not be committed.
- No application behavior, rule package format, UI, or legal licensing terms will be changed.

---

### Task 1: Update the README

**Files:**
- Modify: `README.md`
- Reference: `src/insulation_coordination/ui/rules_manager.py`
- Reference: `tests/ui/test_rules_manager.py`
- Reference: `tests/ui/test_rules_manager_review.py`

**Interfaces:**
- Consumes: Existing README structure and the current Rules Manager labels/behavior.
- Produces: A self-contained README that accurately explains how users obtain and share rule packages and how they are responsible for validating results.

- [ ] **Step 1: Add the prominent rule-data notice**

Insert an Important block immediately after the opening paragraph and before `## Highlights`. It must say, in concise wording, that the application does not include IEC rules, tables, or licensed standard PDFs; a calculation requires an approved `.icrules` package; users must create or obtain one through Rules Manager; and internal sharing must comply with the organization's licence and procedures.

Use wording equivalent to:

```markdown
> [!IMPORTANT]
> This software does not include IEC rules, tables, or licensed standard PDFs. To calculate results, you must create or obtain an approved `.icrules` package through the Rules Manager. The package is the rule set used by the application and may be shared within your company team only in accordance with your organization's standards licence and procedures.
```

- [ ] **Step 2: Correct the Rules Manager sequence**

Replace the existing six-step list under `## Rules Manager review workflow` with the exact operational sequence below:

```markdown
1. Select both licensed PDFs together: IEC 60664-1 and IEC 60664-4. The importer identifies the supported editions and extracts raw grids, semantic headings, equations, mappings, footnotes, and source cells.
2. Review the extracted tables and raw cells. Review is read-only until a reviewer records identity and notes for an acceptance or correction.
3. Review the extracted equations and semantic mappings.
4. Click `Build reviewed content` after table/raw-cell review is complete. Resolve every remaining review item and provide the required notes.
5. Click `Approve reviewed draft` and provide approver identity and approval notes. Approval is blocked until the draft is fully resolved and passes validation.
6. Click `Export approved package` to write the deterministic `.icrules` archive.
7. Share the approved `.icrules` file internally where permitted, and use `Import approved .icrules` on other team installations. The receiving installation does not need the source PDFs.
```

Clarify immediately after the list that approval switches the Rules Manager to the approved package, export writes the shareable archive, and later import installs/activates that archive. Do not describe export itself as a separate activation step.

- [ ] **Step 3: Add responsibility and disclaimer guidance**

Insert a `## Responsibility and disclaimer` section before `## Development` or, if that would interrupt the technical flow, immediately before `## Implementation map`. The section must state that results are decision-support output, not certification or a substitute for engineering review; the user must verify inputs, rules, calculations, and results against applicable standards and project requirements; and the project authors are not responsible for loss, damage, non-compliance, or other consequences arising from use of the software or its results.

Use concise, plain-language wording and avoid claiming that a README disclaimer changes rights under applicable law.

- [ ] **Step 4: Add contribution guidance**

Insert a `## Contributing` section after the responsibility section or near the end of the README. Invite users to open issues for input, bug, and improvement reports, including reproducible context where possible. Invite pull requests from people who want to collaborate and ask contributors to describe the change and verification performed.

- [ ] **Step 5: Correct nearby repository and packaging claims**

Change the Tectonic bullet under `## Highlights` to distinguish packaged builds from development environments. State that packaged builds use a bundled/pinned offline Tectonic executable and that development runs can use an executable on `PATH` or an explicitly supplied path.

Change the final private-artifact paragraph from an absolute “never committed” claim to explicit repository guidance: private IEC PDFs, `.icrules`, `.icproj`, audits, and derived values are ignored by default and must not be committed or published.

- [ ] **Step 6: Preserve and inspect the remaining README**

Do not rewrite the calculation workflows unless verification finds a contradiction. Check that the existing sections still describe the current PCB-only boundary, Annex G/H behavior, unsupported conditions, trace interpretation, development commands, desktop launch, packaging files, and implementation-map links.

- [ ] **Step 7: Run documentation verification**

Run:

```bash
git diff --check
rg -n -i "does not include|\.icrules|Rules Manager|responsibility|disclaimer|issues|pull requests|never committed|ignored by default|Tectonic" README.md
```

Expected: no whitespace errors; the README contains the new rule-data notice, corrected workflow, responsibility/disclaimer, contribution guidance, qualified Tectonic wording, and no contradictory “never committed” statement.

Then compare the final workflow against `src/insulation_coordination/ui/rules_manager.py` and the Rules Manager tests. Since this task changes documentation only, no new automated test is required; run the normal test suite only if the implementation workflow or reviewer requests a broader regression check.

- [ ] **Step 8: Review the final diff**

Run:

```bash
git diff -- README.md
git status --short
```

Confirm that only the intended README changes are unstaged/uncommitted in the implementation, and that unrelated existing workspace artifacts remain untouched.

- [ ] **Step 9: Commit the README update**

```bash
git add README.md
git commit -m "docs: clarify rules ownership and user responsibility"
```

