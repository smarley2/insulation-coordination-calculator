## Summary

Describe the problem and the solution. Keep the pull request focused.

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Calculation or rule-handling change
- [ ] UI or report change
- [ ] Packaging, release, or CI change
- [ ] Documentation only

## Verification

List the commands and workflows used to verify the change.

- [ ] `uv run ruff check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest --cov=insulation_coordination --cov-branch --cov-report=term-missing --cov-fail-under=80`
- [ ] Relevant packaging or smoke test, when applicable

## Engineering impact

For calculation, rule-package, trace, or report changes, describe:

- affected branches, formulas, mappings, or candidate selection;
- boundary and failure cases covered by tests;
- compatibility impact on `.icproj` or `.icrules` files;
- how deterministic output and audit traceability were preserved.

Write `Not applicable` when this section does not apply.

## User-visible changes

Add screenshots or example output for UI/report changes. Remove confidential or licensed content first.

## Safety and content confirmation

- [ ] No licensed IEC PDF, table, excerpt, or reconstructed standard content is included.
- [ ] No real customer/company `.icproj`, private `.icrules`, audit export, credentials, or proprietary data is included.
- [ ] New fixtures and examples are synthetic.
- [ ] Security-sensitive details were reported privately according to `SECURITY.md`.

## Checklist

- [ ] The change is documented where necessary.
- [ ] Tests were added or updated for changed behavior.
- [ ] Total branch-aware coverage remains at least 80%.
- [ ] Existing project and rule-package compatibility was considered.
- [ ] Review conversations can be resolved before merge.
