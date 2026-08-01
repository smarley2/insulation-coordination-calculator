# Release Acceptance Checklist

Run on a clean machine with no Python or LaTeX preinstalled, offline.

1. Installer (Windows `insulation-coordination-setup.exe` or macOS `.app`/zip) installs per-user.
2. `.icproj` and `.icrules` file associations open the application.
3. Approved `.icrules` imports without any PDFs; identity/hash shown in Rules Manager.
4. Every rules table cell, formula node, mapping, and source reference is visible in the audit tree; CSV/JSON inventory export works.
5. Functional, basic, and reinforced insulation plus a >30 kHz case calculate; clearance ≤ creepage.
6. Save/reopen reproduces identical results (project SHA-256 and rules SHA-256 match).
7. An incomplete pair blocks final report generation with a per-pair message.
8. `.tex` and PDF contain formulas, substitutions, and exact source references; no network access required.
9. Generated PDF has no clipping and landscape matrix tables render correctly.
10. Public source/archive contains no private standards, `.icrules`, `.icproj`, audits, or derived IEC values.

## IEC PCB Rules Manager and calculation

- [ ] `Review extracted tables` opens when resolution notes are empty; viewing alone creates no resolution.
- [ ] Table review shows semantic headings, raw text, normalized numeric value, qualifiers, footnotes, and exact PDF page/cell source.
- [ ] IEC 60664-1 Table F.5 appears once and continues from PDF page 73 to page 74 without losing its PCB columns.
- [ ] Accepting a table or equations/mappings requires actor and notes.
- [ ] Equations and mappings must be reviewed before `Build reviewed content` becomes available; obsolete formula-constant dialog is absent.
- [ ] Required-content and manual-review counts are labelled separately and both reach their completed state before approval.
- [ ] Two PCB pairs above 30 kHz show separate starting clearances, `fcritical` values, frequency comparisons, selected branches, and second-pass status.
- [ ] Unsupported PCB cases (non-printed wiring, pollution degree other than 1/2, unknown material group, conventional-construction assumptions, or unavailable sparse source cells) stop with a specific message.
- [ ] A schema-1 or `iec-pdf-1` package is rejected with instructions to re-import licensed IEC PDFs; no partial package becomes active.
- [ ] Trace entries link back to IEC 60664-1 F.2/F.5/F.8/F.9/A.2 and IEC 60664-4 Tables 1/2 and Equations (1)/(2), as applicable.

## Offline Tectonic verification

- `packaging/tectonic-manifest.json` records the pinned Tectonic version, licence, bundle SHA-256, executable SHA-256, and `offline: true`.
- Startup verifies the bundled Tectonic executable hash before compiling; the compiler always runs with `--offline`.

## Cross-platform

- Windows: PyInstaller `icc.exe` + Inno Setup installer (`.icproj`/`.icrules` registry).
- macOS: PyInstaller `--windowed` bundle + `.app` Info.plist document types; zip for distribution.
- Runtime code is identical; `platformdirs` selects the per-OS user data directory for installed rules.
