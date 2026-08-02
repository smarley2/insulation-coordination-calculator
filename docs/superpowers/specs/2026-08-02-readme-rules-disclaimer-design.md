# README rules, responsibility, and contribution guidance

## Goal

Bring `README.md` into alignment with the current Rules Manager workflow and make
the software's rule-data boundary, user responsibility, and contribution paths
unambiguous.

## Current context

The application does not ship with an active IEC rule package or licensed IEC
standard PDFs. The Rules Manager can extract a draft from the user's licensed
IEC 60664-1 and IEC 60664-4 PDFs, review and validate the extracted content,
approve it, and export a deterministic `.icrules` archive. An approved archive
can later be imported and used without the source PDFs. The current README
describes most of this workflow but does not clearly state the rule-data
boundary or the user's responsibility for checking results.

The repository also ignores private standards, `.icrules`, `.icproj`, and audit
artifacts by default. Documentation should describe this as a repository safety
measure, not as an absolute technical guarantee that files can never be
committed.

## Documentation design

### Prominent notice

Add an Important notice immediately after the opening description. It will state
that:

- the software contains no IEC rules or licensed standard content;
- calculations require an approved `.icrules` package;
- users must create or obtain their organization's approved package through the
  Rules Manager;
- the resulting package may be shared internally only in accordance with the
  organization's standards licence and procedures.

### Rules Manager workflow

Rewrite the existing numbered workflow to mirror the UI and tested behavior:

1. Select both licensed PDFs together: IEC 60664-1 and IEC 60664-4.
2. Review extracted tables and raw cells, recording reviewer identity and notes
   for corrections or acceptance.
3. Review extracted equations and semantic mappings.
4. Build reviewed content after table/raw-cell review and resolve all remaining
   review items.
5. Approve the fully resolved draft with approver identity and approval notes.
6. Export the approved deterministic `.icrules` package.
7. Share the approved package internally as permitted and import it on other
   team installations; source PDFs are not required on receiving machines.

Avoid describing export as a separate activation operation. Approval switches
the Rules Manager to the approved package, while export writes the archive and
later import installs and activates a shared archive.

### Responsibility and disclaimer

Add a dedicated section near the end explaining that the software and its
results are decision-support output, not certification or a substitute for
engineering review. State that the user is solely responsible for checking
inputs, rule packages, calculations, and results against the applicable
standards and project requirements. State that the project authors are not
responsible for loss, damage, non-compliance, or other consequences resulting
from use of the software or its results.

### Contributions

Add a short section inviting users to open GitHub issues for input, bug, and
improvement reports, and to submit pull requests when they want to collaborate.
Ask contributors to include enough context to reproduce or assess a change.

### Other README corrections

Keep the existing calculation and implementation details unless repository
evidence shows they are inaccurate. Correct only the following nearby wording:

- Explain that packaged builds use a bundled/pinned offline Tectonic executable,
  while development can use an executable supplied on `PATH`.
- Replace the absolute claim that private artifacts are “never committed” with
  guidance that they are ignored by default and must not be committed.

## Scope

Only `README.md` and this design specification are in scope. No application
behavior, rule package format, UI, or legal licensing terms will be changed.

## Acceptance criteria

- A new reader sees near the top that IEC rules are not included and that an
  approved `.icrules` package is required.
- The documented Rules Manager sequence matches the current UI and tests.
- The README clearly assigns standards verification and use decisions to the
  user and includes a concise limitation-of-liability statement.
- The README explains how to report inputs, bugs, and improvements and how to
  collaborate through pull requests.
- No existing technical workflow is weakened or contradicted.
- Private-artifact and Tectonic wording is accurate and appropriately qualified.

## Verification

- Read the final README against `src/insulation_coordination/ui/rules_manager.py`
  and the Rules Manager tests.
- Search the README for contradictory claims about bundled rules, activation,
  private artifacts, and report compilation.
- Run `git diff --check` and the repository's relevant documentation-independent
  verification commands as appropriate; no code behavior is expected to change.
