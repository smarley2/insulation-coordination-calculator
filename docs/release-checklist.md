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

## Offline Tectonic verification

- `packaging/tectonic-manifest.json` records the pinned Tectonic version, licence, bundle SHA-256, executable SHA-256, and `offline: true`.
- Startup verifies the bundled Tectonic executable hash before compiling; the compiler always runs with `--offline`.

## Cross-platform

- Windows: PyInstaller `icc.exe` + Inno Setup installer (`.icproj`/`.icrules` registry).
- macOS: PyInstaller `--windowed` bundle + `.app` Info.plist document types; zip for distribution.
- Runtime code is identical; `platformdirs` selects the per-OS user data directory for installed rules.
