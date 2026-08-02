# Rules Import and Chapter 5 Group Descriptions Design

## Goal

Allow supported IEC PDFs that are encrypted but unlockable with an empty password or a user-supplied password, and make Chapter 5 explain group membership and the rules applied to each group.

## Approved behavior

1. The importer first attempts an empty password for encrypted PDFs. This supports the BRUSA IEC 60664-1 file, whose content is readable without a user password.
2. If the PDF requires a non-empty password, the UI displays an error and offers a password prompt. The password is held only in memory for the current extraction attempt. A wrong password produces a clear failure and recommends an unlocked copy.
3. The supported recipe fingerprints are corrected for the supplied BRUSA editions: IEC 60664-1 Edition 3.0 2020-05 (172 pages) and IEC 60664-4 Second edition 2005-09 (138 pages).
4. Chapter 5 begins with a group index listing every group and its human-readable pairs. Each group then includes a `Rules applied` list with human-readable descriptions and sources, followed by the shared calculation block.
5. Clearance and creepage candidate tables use natural-width candidate, voltage, and distance columns, leaving the remaining width for the explanation column.

## Boundaries

- Do not bypass non-empty PDF passwords or weaken standard identity checks.
- Keep PDF source bytes and user passwords out of saved rule packages and logs.
- Preserve existing report validation and internal calculation traces.
- Do not modify user-generated `audit/`, `projects/`, or `tmp/` contents.

## Verification

- Test empty-password encrypted identification, password-required failure, and supplied-password success using generated PDFs.
- Test the Chapter 5 group index, human rule descriptions, and candidate-table layout.
- Run the full pytest suite, Ruff, and a representative PDF compilation/render inspection.
