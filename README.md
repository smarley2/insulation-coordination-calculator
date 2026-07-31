# Insulation Coordination Calculator

Offline desktop application that calculates auditable functional, basic, and reinforced
clearance and creepage requirements from approved private IEC rule packages and generates
LaTeX/PDF insulation-coordination reports.

## Highlights

- Python 3.12 + PySide6 desktop shell with a UI-independent domain engine.
- Versioned `.icproj` projects and deterministic `.icrules` rule archives.
- `Decimal`-only engineering arithmetic; every lookup, formula, substitution,
  interpolation, correction, and rounding step is traced and referenced.
- Full audit browser in the Rules Manager: tables, formulas, mappings, checksums,
  validation, and CSV/JSON inventory export.
- Offline LaTeX/PDF compilation through a pinned Tectonic executable.
- Blocked final report generation while any pair has a blocking error.
- Never executes code from rule packages; only whitelisted declarative operators.

## Development

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run mypy
uv run pytest
```

## Desktop

```bash
uv run icc --gui
```

## Packaging

- Windows: `packaging/insulation_coordination.spec` (PyInstaller) +
  `installer/insulation-coordination.iss` (Inno Setup).
- macOS: same spec with `--windowed`; bundle as `.app` with document types.
- CI: `.github/workflows/windows-package.yml` and `.github/workflows/macos-package.yml`.
- See `docs/release-checklist.md` for the acceptance matrix.

Private licensed IEC PDFs, `.icrules`, `.icproj`, audits, and derived values stay local
and are never committed (`/.gitignore`).
