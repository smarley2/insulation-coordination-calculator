# Cross-Platform Free Release Design

**Date:** 2026-08-02
**Status:** Approved

## Goal

Complete the original V1 release work by producing installable Windows, macOS,
and Linux artifacts that run and generate reports offline without requiring the
maintainer to buy code-signing certificates or an Apple Developer membership.

The free release is explicit about its trust level: Windows and macOS artifacts
are usable but are not publicly trusted or notarized, while Linux artifacts use
free GPG-based integrity signing when a release key is configured. Paid signing
and Apple notarization remain optional CI stages that can be enabled later
without changing the application or package formats.

## Scope

V1 produces one supported architecture per operating system:

- Windows x86_64: an Inno Setup per-user installer.
- macOS arm64: an ad-hoc-signed application in a DMG.
- Linux x86_64: an AppImage and a portable tar archive.

All artifacts include the same Python application, report templates, pinned
Tectonic 0.16.9 executable, and offline Tectonic resource cache. Version 0.16.9
is required because it contains the macOS arm64 `fontspec` crash fix needed by
the report template. Runtime code is
identical across platforms except for startup integration, compiler location,
and package metadata.

Additional CPU architectures, app stores, package repositories, commercial
certificates, Developer ID signing, and Apple notarization are outside the free
V1 release gate. The build workflows retain optional signing stages for future
credentials.

## Design Principles

- Runtime calculations and report compilation remain completely offline.
- Private IEC PDFs, `.icrules`, `.icproj`, audits, and derived IEC values never
  enter public source, build contexts, CI caches, or release artifacts.
- Unsigned, ad-hoc-signed, trusted-signed, and notarized are distinct statuses;
  release metadata never describes one as another.
- A packaging failure cannot weaken calculation validation or rule-package
  trust boundaries.
- Local source development may use a system Tectonic installation; frozen
  applications must use and verify their bundled compiler and resource cache.
- User projects and installed private rules survive application uninstall.
- Existing source workflows and `icc --gui` remain compatible.

## Artifact Architecture

The existing quality workflow remains the shared source gate. Three native
packaging jobs consume the same tested revision:

```text
Application source
       |
       +-- Ruff, mypy, pytest, synthetic end-to-end report
       |
       +-- Windows runner -> PyInstaller -> Inno Setup installer
       +-- macOS runner   -> PyInstaller -> ad-hoc signature -> DMG
       +-- Linux runner   -> PyInstaller -> AppImage + tar archive
                                      |
                                      +-> release metadata + SHA256SUMS
```

Each native job builds rather than cross-compiles. PyInstaller produces the
platform application tree. A platform packaging step then adds launch metadata,
file associations, the pinned compiler bundle, and the platform container.

The release workflow downloads Tectonic build inputs only during packaging,
verifies them against repository-pinned hashes, and packages the executable and
resource cache. Packaged smoke tests run with cached-only compiler flags and an
isolated user-data directory so they cannot succeed by using a developer's
existing Tectonic cache.

## Application Startup and File Opening

The CLI becomes the single launch router for terminal use, desktop shortcuts,
and file associations:

- `icc` opens the desktop GUI.
- `icc --gui` opens the desktop GUI for backward compatibility.
- `icc --version` prints the version and exits successfully.
- `icc PROJECT.icproj` opens the validated project in the desktop GUI.
- `icc PACKAGE.icrules` validates, installs, activates, and displays the rules
  package in the desktop GUI.
- Unsupported extensions, missing files, or mutually incompatible arguments
  exit nonzero and display an actionable error.

The launch router parses the requested file before creating the main window,
then passes the resolved startup action to the UI. The main window reuses its
existing project and rule-loading paths; startup does not introduce a second
validation or persistence implementation.

Platform integration points call this same interface:

- Windows registry commands invoke `icc.exe "%1"` for `.icproj` and
  `.icrules`.
- macOS `CFBundleDocumentTypes` forwards opened documents to the application.
- Linux installs a `.desktop` entry and MIME definitions for both extensions.

## Bundled Offline Tectonic

The repository contains a machine-readable manifest for Tectonic 0.16.9. For
each supported platform it records:

- platform and architecture;
- upstream artifact identity;
- executable relative path and SHA-256;
- resource-cache relative path and canonical SHA-256;
- licence and attribution;
- the required cached-only command-line flag.

Packaging fails if a downloaded executable or resource cache does not match the
manifest. The validated files are copied into the frozen application tree.

At runtime, frozen applications resolve only the bundled compiler. Before every
PDF compile, the application verifies the executable and resource-cache hashes.
It then invokes Tectonic with its bundled cache location and cached-only flag.
No fallback to `PATH`, a home-directory cache, or network retrieval is allowed
for frozen applications.

Source runs continue to locate a system Tectonic after checking an explicitly
provided compiler command. This preserves the current Linux development
workflow without weakening packaged releases.

If the compiler bundle is missing or altered, the report page explains the
failed integrity check. Project editing, calculations, saves, and LaTeX export
remain available; PDF generation is blocked.

## Platform Packages

### Windows

PyInstaller produces the `icc` application directory. Inno Setup installs it
per user, creates Start Menu and optional desktop shortcuts, and registers
`.icproj` and `.icrules` associations. Uninstall removes application files and
associations but does not delete user projects or the platformdirs rules
directory.

The normal free artifact is unsigned and release notes explain the expected
Windows warning. If Authenticode credentials later become available, the
workflow signs packaged PE files before installer creation and signs the final
installer afterward. Signature verification is mandatory whenever that stage
runs.

### macOS

PyInstaller produces a windowed arm64 `.app`. The package step provides document
types, icons, and bundle metadata, signs nested executables and the outer bundle
ad hoc, verifies bundle consistency, and places the application in a DMG.

Ad-hoc signing is described only as bundle-integrity signing. The release notes
state that the application is not Apple-notarized and give the standard Finder
right-click, Open procedure. If Developer ID credentials later become
available, the optional stage replaces the ad-hoc signature, enables hardened
runtime, submits the DMG with `notarytool`, staples the ticket, and verifies it.

### Linux

PyInstaller produces an x86_64 application directory. The package step creates
an AppImage, a portable tar archive, an application icon, a `.desktop` entry,
and MIME definitions for `.icproj` and `.icrules`.

The AppImage and archive are usable without a signing service. When the release
GPG key is configured, CI signs the checksum manifest and embeds or attaches an
artifact signature. The public key fingerprint and verification commands are
documented with the release.

## Release Metadata and Optional Signing

Every packaging job emits machine-readable metadata containing:

- application version and source commit;
- operating system and architecture;
- artifact filename, size, and SHA-256;
- Tectonic version and verified bundle hashes;
- package smoke-test result;
- signing status: `unsigned`, `ad-hoc`, `trusted`, or `notarized`;
- signing identity when a trusted signature exists.

The release assembly job combines this metadata and writes `SHA256SUMS` for all
public artifacts. Signing stages are conditional on the presence of credentials,
but the resulting status is derived from verification rather than from the
condition that attempted signing.

## Packaged Diagnostic Flow

The executable provides a release-diagnostic command that accepts synthetic
`.icproj` and `.icrules` fixtures plus an output directory. It performs the same
trusted operations as the GUI:

1. load and validate the project;
2. load, validate, and hash-check the approved rules package;
3. resolve and calculate every pair;
4. group results and build the report model;
5. render `.tex`;
6. verify and invoke bundled Tectonic offline;
7. validate the generated PDF;
8. write a concise machine-readable result.

The diagnostic command does not generate or embed IEC-derived fixtures. CI
creates only synthetic public fixtures before packaging and supplies them to the
installed application.

## Error Handling

- Startup file errors identify the path, expected extension, and validation
  reason without exposing private rule content.
- File-association failures leave the application open on a new project and show
  the error rather than terminating without explanation.
- Compiler integrity failures block PDF generation and identify which bundled
  component failed verification.
- Package smoke tests treat any system-compiler fallback, home-cache access, or
  missing output as a failure.
- Optional signing failures fail the signing job; they never silently publish an
  artifact labelled as trusted.
- Release assembly rejects duplicate filenames, missing metadata, mismatched
  checksums, or any forbidden private artifact.

## Automated Verification

Unit and integration tests cover CLI routing, startup actions, compiler-manifest
parsing, executable and cache hashing, tamper detection, developer-mode fallback,
and platform association metadata.

Each native package job runs the packaged diagnostic flow with synthetic public
fixtures and an isolated user-data directory. Platform checks then verify:

- Windows: installer execution, registry associations, installed launch,
  offline PDF generation, uninstall, and preservation of seeded user data.
- macOS: DMG mount, bundle structure, ad-hoc signature consistency, launch,
  document routing, and offline PDF generation.
- Linux: AppImage execution, tar archive execution, desktop/MIME validation,
  document routing, and offline PDF generation.

The repository quality gate remains:

```bash
uv run ruff check .
uv run mypy
QT_QPA_PLATFORM=offscreen uv run pytest
```

## Release Acceptance

A free V1 release is publishable only when:

1. all repository quality gates pass;
2. all three native package jobs pass for the same source commit;
3. the locally supplied IEC standards pass extraction, approval, calculation,
   and comparison with the separately human-reviewed private digest;
4. every public artifact matches `SHA256SUMS`;
5. artifact scans find no private standards, rules, projects, audits, derived IEC
   values, or development caches;
6. packaged reports compile using only the verified bundled Tectonic resources;
7. installation documentation accurately explains Windows warnings, macOS
   Gatekeeper opening, Linux permissions, and checksum/signature verification;
8. one final clean-machine installation check succeeds on Windows, macOS, and
   Linux before the V1 release is published.

## Documentation

The README gains a download matrix and platform-specific installation sections.
The release checklist records automated evidence separately from manual
acceptance. Documentation never tells users that unsigned or ad-hoc-signed
artifacts are trusted-signed or notarized.

The existing implementation plans remain historical records. Their unchecked
boxes are not used as release status; the updated release checklist and native
workflow results are authoritative.
