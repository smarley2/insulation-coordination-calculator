# Contributing

Thank you for contributing to the Insulation Coordination Calculator.

This is engineering software. Changes that affect calculations, rule-package handling, traces, or reports must be reviewable, deterministic, and supported by focused tests.

## Before starting

- Search existing issues and discussions before opening a new item.
- Use the bug-report or feature-request form for new work.
- Keep each pull request focused on one problem or closely related group of changes.
- Do not commit licensed standards, private engineering data, or generated customer files.

For security-sensitive findings, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development setup

Requirements:

- Python 3.12
- `uv`
- platform dependencies required by PySide6/Qt

Install the project and all development dependencies:

```bash
uv sync --locked --all-groups
```

Run the application:

```bash
uv run icc --gui
```

## Required checks

Run these commands before submitting a pull request:

```bash
uv run ruff check .
uv run mypy
uv run pytest --cov=insulation_coordination --cov-branch --cov-report=term-missing --cov-fail-under=80
```

The test suite must maintain at least 80% total branch-aware coverage. New or changed behavior should be covered directly rather than relying only on the repository-wide percentage.

Packaging or release changes should also run the relevant platform packaging and smoke-test workflow.

## Calculation and rule changes

Changes affecting insulation-coordination results require additional care:

- use `Decimal`-based arithmetic consistently;
- preserve deterministic output and complete audit traces;
- add focused tests for boundary values, invalid inputs, interpolation, rounding, and governing-candidate selection;
- document the source identifier used by the rule package without copying licensed table or standard text into the repository;
- keep unsupported conditions explicit and blocking rather than silently guessing;
- verify that report output and trace references remain consistent with the calculated result.

Do not add IEC rules, tables, standard excerpts, licensed PDFs, or reconstructed copyrighted content to source code, tests, fixtures, issues, or pull requests.

## Private files and test data

Never commit or upload:

- IEC standard PDFs;
- `.icrules` files created from licensed content;
- real `.icproj` customer or company projects;
- audit exports containing licensed or proprietary data;
- credentials, secrets, personal information, or confidential engineering data.

Use synthetic fixtures containing no licensed or proprietary content. Check `git status` and the complete staged diff before committing.

## Pull requests

A pull request should include:

- a concise explanation of the problem and solution;
- the affected components and platforms;
- the commands or workflows used for verification;
- screenshots for visible UI changes;
- migration or compatibility notes when file formats change;
- confirmation that no licensed or sensitive material is included.

All required CI checks must pass. Resolve review conversations before merge. Maintainers may request smaller commits, additional tests, or separation of unrelated changes.

## Commit messages

Use short, descriptive messages with a conventional prefix when practical:

```text
fix: correct high-frequency branch selection
test: cover clearance boundary conditions
docs: clarify package review workflow
ci: pin release action dependencies
```

## Reporting ordinary defects

Include the application version, operating system, installation method, exact reproduction steps, expected behavior, actual behavior, and sanitized logs. Attach only synthetic project or rule data.