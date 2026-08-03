# Release Acceptance Checklist

Record evidence for the exact commit and workflow run before publishing. Do not place
licensed PDFs, private `.icrules`/`.icproj` files, extracted values, or audit exports in
the release workspace.

## Version bump

Bumping the release version touches these, and CI fails if any is missed:

- [ ] `version` in `pyproject.toml`
- [ ] `__version__` in `src/insulation_coordination/__init__.py`
- [ ] `env.VERSION` in `.github/workflows/release.yml` (must equal the `v*` tag)
- [ ] `uv lock` re-run and `uv.lock` committed — it records the project's own
      version, and CI installs with `uv sync --locked`. Verify with
      `uv sync --locked --all-groups`, not `uv run --frozen`, which skips the check.

## Automated evidence

| Gate | Result | Evidence URL / SHA |
| --- | --- | --- |
| Ruff and mypy | [ ] | |
| Public pytest suite | [ ] | |
| Native Tectonic locks refreshed and verified | [ ] | |
| Windows installer smoke test | [ ] | |
| macOS DMG signature and offline diagnostic | [ ] | |
| Linux AppImage/tar diagnostic | [ ] | |
| Forbidden-content scan | [ ] | |
| `release-index.json` and `SHA256SUMS` | [ ] | |

## Manual clean-machine evidence

For each row record tester, date, OS version, clean account/machine, result, and the
artifact SHA-256.

| Platform | File association | Offline PDF | Warning observed | User data survives uninstall | Evidence |
| --- | --- | --- | --- | --- | --- |
| Windows x86_64 | [ ] | [ ] | unsigned SmartScreen | [ ] | |
| macOS arm64 | [ ] | [ ] | ad-hoc/not notarized | [ ] | |
| Linux x86_64 | [ ] | [ ] | none / desktop policy | [ ] | |

## Rules and calculation acceptance

- [ ] Approved `.icrules` imports without source PDFs; identity and hash are visible.
- [ ] F.2, F.5, F.8, F.9, A.2, IEC 60664-4 Tables 1/2 and equations have visible provenance.
- [ ] Functional, basic, reinforced, and greater-than-30-kHz PCB cases calculate correctly.
- [ ] Unsupported construction, pollution, material, geometry, and sparse-cell cases block.
- [ ] Incomplete pairs block report generation with a per-pair explanation.
- [ ] Save/reopen preserves project and rules hashes.
- [ ] Generated PDF has no clipping and includes formulas, substitutions, and sources.

## Final sign-off

- Commit SHA: ____________________
- Workflow run: __________________
- Release version: _______________
- Reviewer: ______________________
- Date: __________________________
