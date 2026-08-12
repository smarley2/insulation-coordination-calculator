# Cross-Platform Free Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce tested Windows, macOS, and Linux V1 packages that open associated project/rules files and generate reports fully offline without requiring paid signing credentials.

**Architecture:** A shared startup router and rules-installation service feed the existing Qt main window. Frozen builds resolve a repository-locked Tectonic executable and warmed offline cache through a new verifier, while source runs retain the current system-compiler fallback. Native GitHub Actions jobs build and smoke-test an Inno Setup installer, an ad-hoc-signed macOS DMG, and Linux AppImage/tar artifacts; a final job verifies metadata, checksums, and absence of private files.

**Tech Stack:** Python 3.12, PySide6 6.x, Pydantic 2.x, PyInstaller 6.x, Tectonic 0.16.9, Inno Setup 6, AppImageTool, GitHub Actions, pytest, Ruff, mypy.

## Global Constraints

- V1 package architectures are Windows x86_64, macOS arm64, and Linux x86_64.
- Runtime calculations and report compilation must make no network requests.
- Frozen applications must use and verify the bundled Tectonic 0.16.9 executable and warmed cache; they must never fall back to `PATH` or a home-directory cache.
- Source runs may use an explicitly supplied compiler or a system `tectonic` executable.
- Private IEC PDFs, `.icrules`, `.icproj`, audits, extracted values, and private tests must not enter build staging, CI caches, or release artifacts.
- Windows and macOS artifacts are publishable without paid trust credentials, but release metadata must identify them as `unsigned` and `ad-hoc`, respectively.
- Linux GPG signing, Windows Authenticode, and Apple Developer ID/notarization are conditional stages; an absent credential must not fail an unsigned free build.
- User projects and installed private rules must survive uninstall on every platform.
- Existing `icc --gui` and `icc --version` behavior must remain compatible; invoking `icc` without arguments must open the GUI.
- `.icproj` opens a project; `.icrules` validates, installs, activates, and displays a rules package.
- Every task uses red-green-refactor, runs focused tests, and ends with a focused commit.

## File Map

| Path | Responsibility |
| --- | --- |
| `src/insulation_coordination/rules/installation.py` | UI-independent approved-rules installation and canonical installed path |
| `src/insulation_coordination/startup.py` | CLI/startup request parsing and document classification |
| `src/insulation_coordination/ui/app.py` | Qt application creation and macOS `QFileOpenEvent` forwarding |
| `src/insulation_coordination/ui/main_window.py` | Apply startup requests through existing project/rules UI paths |
| `src/insulation_coordination/report/tectonic.py` | Manifest models, tree hashing, platform selection, frozen compiler verification |
| `src/insulation_coordination/report/compiler.py` | Compile with explicit cached-only flag and isolated cache environment |
| `src/insulation_coordination/release_diagnostic.py` | Packaged end-to-end project/rules/calculation/report diagnostic |
| `scripts/create_release_fixtures.py` | Generate ignored synthetic `.icproj` and `.icrules` smoke fixtures |
| `scripts/prepare_tectonic.py` | Download, verify, extract, warm, and lock native Tectonic staging |
| `scripts/render_icons.py` | Render the reviewed SVG into native PNG, ICO, and ICNS files using PySide6 |
| `scripts/release_artifacts.py` | Release metadata, checksums, and forbidden-content scanning |
| `packaging/tectonic-manifest.json` | Upstream archive URLs, archive hashes, bundle identity, and native lock paths |
| `packaging/tectonic-locks/*.json` | Native executable/cache hashes produced by clean native lock-refresh jobs |
| `packaging/insulation_coordination.spec` | Shared platform-aware PyInstaller application build |
| `packaging/assets/icc.svg` | Single source application icon |
| `packaging/windows/smoke.ps1` | Installed Windows release acceptance |
| `packaging/macos/Info.plist` | macOS bundle and document-type metadata |
| `packaging/macos/package.sh` | Ad-hoc signing, DMG creation, and smoke checks |
| `packaging/linux/AppRun` | AppImage entry point |
| `packaging/linux/icc.desktop` | Linux desktop entry and MIME declarations |
| `packaging/linux/application-x-icc.xml` | Shared MIME definitions for `.icproj` and `.icrules` |
| `.github/workflows/tectonic-locks.yml` | Manual native cache-lock refresh workflow |
| `.github/workflows/release.yml` | Three native package jobs plus release assembly |

---

### Task 1: Extract Approved Rules Installation from the Rules Manager

**Files:**
- Create: `src/insulation_coordination/rules/installation.py`
- Modify: `src/insulation_coordination/ui/rules_manager.py:203-232,460-477`
- Create: `tests/rules/test_installation.py`
- Modify: `tests/ui/test_rules_manager.py:42-82`

**Interfaces:**
- Consumes: `load_rule_package(path: Path) -> RulePackage`, `write_rule_package(path: Path, package: RulePackage) -> str`
- Produces: `InstalledRulePackage(path: Path, package: RulePackage)`
- Produces: `default_rules_dir() -> Path`
- Produces: `install_rule_package(source: Path, rules_dir: Path | None = None) -> InstalledRulePackage`

- [ ] **Step 1: Write failing service tests**

```python
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.installation import install_rule_package
from tests.fixtures.synthetic_rules import synthetic_rule_package


def test_install_rule_package_validates_and_reloads_canonical_archive(tmp_path: Path) -> None:
    source = tmp_path / "source.icrules"
    write_rule_package(source, synthetic_rule_package())

    installed = install_rule_package(source, tmp_path / "installed")

    assert installed.path.parent == tmp_path / "installed"
    assert installed.path.name == (
        f"{installed.package.manifest.package_id}-{installed.package.manifest.version}.icrules"
    )
    assert load_rule_package(installed.path).package_sha256 == installed.package.package_sha256


def test_install_rule_package_never_replaces_valid_install_with_bad_input(tmp_path: Path) -> None:
    source = tmp_path / "source.icrules"
    write_rule_package(source, synthetic_rule_package())
    installed = install_rule_package(source, tmp_path / "installed")
    before = installed.path.read_bytes()
    source.write_bytes(b"not a rule archive")

    with pytest.raises(RulePackageError):
        install_rule_package(source, tmp_path / "installed")

    assert installed.path.read_bytes() == before
```

- [ ] **Step 2: Run the service tests and verify the missing module failure**

Run: `uv run pytest -q tests/rules/test_installation.py`

Expected: FAIL while importing `insulation_coordination.rules.installation`.

- [ ] **Step 3: Implement the installation service**

```python
from dataclasses import dataclass
from pathlib import Path

import platformdirs

from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.rules.archive import load_rule_package, write_rule_package


@dataclass(frozen=True)
class InstalledRulePackage:
    path: Path
    package: RulePackage


def default_rules_dir() -> Path:
    return platformdirs.user_data_path("icc") / "rules"


def install_rule_package(source: Path, rules_dir: Path | None = None) -> InstalledRulePackage:
    package = load_rule_package(Path(source))
    destination_dir = Path(rules_dir) if rules_dir is not None else default_rules_dir()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / (
        f"{package.manifest.package_id}-{package.manifest.version}.icrules"
    )
    write_rule_package(destination, package)
    return InstalledRulePackage(destination, load_rule_package(destination))
```

Replace `RulesManagerWindow._install_path()` and its import/write/reload sequence with `install_rule_package(path, self._rules_dir)`. Keep `ImportResult` as the UI compatibility wrapper around the service result.

- [ ] **Step 4: Verify the service and Rules Manager paths**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -q tests/rules/test_installation.py tests/ui/test_rules_manager.py`

Expected: PASS; altered archives remain rejected and imported packages still emit `package_activated`.

- [ ] **Step 5: Commit the installation boundary**

```bash
git add src/insulation_coordination/rules/installation.py \
  src/insulation_coordination/ui/rules_manager.py \
  tests/rules/test_installation.py tests/ui/test_rules_manager.py
git commit -m "refactor: centralize approved rules installation"
```

---

### Task 2: Route Terminal, File-Association, and macOS Open Events

**Files:**
- Create: `src/insulation_coordination/startup.py`
- Modify: `src/insulation_coordination/cli.py`
- Modify: `src/insulation_coordination/ui/app.py`
- Modify: `src/insulation_coordination/ui/main_window.py`
- Create: `tests/test_startup.py`
- Modify: `tests/test_package.py`
- Modify: `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `install_rule_package(source: Path, rules_dir: Path | None = None) -> InstalledRulePackage`
- Produces: `StartupKind(StrEnum)` with `NEW`, `PROJECT`, and `RULES`
- Produces: `StartupRequest(kind: StartupKind, path: Path | None)`
- Produces: `classify_startup_path(path: Path) -> StartupRequest`
- Produces: `parse_cli(argv: Sequence[str] | None) -> argparse.Namespace`
- Produces: `MainWindow.open_document(path: Path) -> bool`
- Produces: `DesktopApplication.file_open_requested: Signal(Path)`

- [ ] **Step 1: Write failing startup classification and CLI tests**

```python
from pathlib import Path

import pytest

from insulation_coordination.startup import StartupKind, classify_startup_path


@pytest.mark.parametrize(
    ("name", "kind"),
    (("design.icproj", StartupKind.PROJECT), ("iec.icrules", StartupKind.RULES)),
)
def test_classify_startup_path_requires_existing_supported_file(
    tmp_path: Path, name: str, kind: StartupKind
) -> None:
    path = tmp_path / name
    path.write_bytes(b"fixture")
    request = classify_startup_path(path)
    assert request.kind is kind
    assert request.path == path.resolve()


def test_classify_startup_path_rejects_unknown_extension(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("notes", encoding="utf-8")
    with pytest.raises(ValueError, match=".icproj or .icrules"):
        classify_startup_path(path)
```

Extend `tests/test_package.py` by monkeypatching `insulation_coordination.cli._run_gui` and asserting that `main([])`, `main(["--gui"])`, and `main([str(project_path)])` all call it exactly once, while `main(["--version"])` does not.

- [ ] **Step 2: Run focused tests and confirm current no-argument behavior fails**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -q tests/test_startup.py tests/test_package.py tests/ui/test_main_window.py`

Expected: FAIL because the startup module, document positional argument, and main-window dispatcher do not exist.

- [ ] **Step 3: Implement the startup request model and CLI router**

```python
class StartupKind(StrEnum):
    NEW = "new"
    PROJECT = "project"
    RULES = "rules"


@dataclass(frozen=True)
class StartupRequest:
    kind: StartupKind
    path: Path | None = None


def classify_startup_path(path: Path) -> StartupRequest:
    resolved = Path(path).expanduser().resolve(strict=True)
    kind = {".icproj": StartupKind.PROJECT, ".icrules": StartupKind.RULES}.get(
        resolved.suffix.lower()
    )
    if kind is None:
        raise ValueError("startup document must have extension .icproj or .icrules")
    return StartupRequest(kind, resolved)
```

The CLI parser adds `document` with `nargs="?"`. `main()` handles `--version` first; every other normal invocation calls `_run_gui(StartupRequest(...))`. Keep `--gui`, but reject `--gui` combined with a positional document through `parser.error()`.

- [ ] **Step 4: Forward startup and `QFileOpenEvent` paths into MainWindow**

Subclass `QApplication` as `DesktopApplication`, override `event()` for `QEvent.Type.FileOpen`, and queue paths received before the window connects. Add `take_pending_open_paths() -> tuple[Path, ...]`.

Add `MainWindow.open_document(path)`:

```python
def open_document(self, path: Path) -> bool:
    try:
        request = classify_startup_path(path)
        if request.kind is StartupKind.PROJECT:
            project = load_project(request.path)
            self.open_project_from_project(project)
        else:
            installed = install_rule_package(request.path)
            self.load_rules(installed.package)
    except (OSError, ValueError, ProjectLoadError, RulePackageError) as error:
        QMessageBox.critical(self, "Open Document", str(error))
        return False
    return True
```

Connect `file_open_requested` to `open_document`, process queued paths after constructing the window, and apply the initial `StartupRequest` before entering `app.exec()`.

- [ ] **Step 5: Verify all startup paths**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -q tests/test_startup.py tests/test_package.py tests/ui/test_main_window.py tests/ui/test_rules_manager.py`

Expected: PASS; no-argument invocation routes to the GUI, and project/rules documents use their existing trusted loaders.

- [ ] **Step 6: Commit startup integration**

```bash
git add src/insulation_coordination/startup.py src/insulation_coordination/cli.py \
  src/insulation_coordination/ui/app.py src/insulation_coordination/ui/main_window.py \
  tests/test_startup.py tests/test_package.py tests/ui/test_main_window.py
git commit -m "feat: open project and rules files from desktop launch"
```

---

### Task 3: Model and Verify the Bundled Tectonic Runtime

**Files:**
- Create: `src/insulation_coordination/report/tectonic.py`
- Replace: `packaging/tectonic-manifest.json`
- Create: `tests/report/test_tectonic.py`

**Interfaces:**
- Produces: `TectonicPlatform` Pydantic model
- Produces: `TectonicManifest` Pydantic model
- Produces: `TectonicRuntime(command: tuple[str, ...], offline_flag: str, cache_dir: Path | None, status: str)`
- Produces: `canonical_tree_sha256(root: Path) -> str`
- Produces: `load_tectonic_manifest(path: Path) -> TectonicManifest`
- Produces: `verify_bundled_tectonic(base_dir: Path, platform_key: str, manifest_path: Path | None = None) -> TectonicRuntime`
- Produces: `resolve_tectonic_runtime(command: CompilerCommand | None = None) -> TectonicRuntime`

- [ ] **Step 1: Write failing manifest, hash, and tamper tests**

```python
import hashlib
import json
from pathlib import Path

import pytest

from insulation_coordination.report.tectonic import (
    TectonicIntegrityError,
    canonical_tree_sha256,
    verify_bundled_tectonic,
)


def test_canonical_tree_hash_includes_relative_names_and_bytes(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    (root / "a.txt").write_bytes(b"A")
    (root / "b.txt").write_bytes(b"B")
    expected = hashlib.sha256(b"a.txt\0A\0b.txt\0B\0").hexdigest()
    assert canonical_tree_sha256(root) == expected


def test_verify_bundled_tectonic_rejects_changed_executable(tmp_path: Path) -> None:
    base, manifest_path = _write_fake_bundle(tmp_path)
    runtime = verify_bundled_tectonic(base, "linux-x86_64", manifest_path)
    assert runtime.status == "verified-bundled"
    (base / "tectonic" / "tectonic").write_bytes(b"changed")
    with pytest.raises(TectonicIntegrityError, match="executable SHA-256"):
        verify_bundled_tectonic(base, "linux-x86_64", manifest_path)
```

The helper writes a fake executable, cache tree, and manifest with computed hashes. Add separate tests for a changed cache file, a symlink in the cache tree, an unsupported platform key, malformed SHA-256 text, and paths containing `..`.

- [ ] **Step 2: Run tests and verify the missing verifier failure**

Run: `uv run pytest -q tests/report/test_tectonic.py`

Expected: FAIL while importing `insulation_coordination.report.tectonic`.

- [ ] **Step 3: Implement strict manifest models and canonical hashing**

Use Pydantic with `extra="forbid"`. Hash trees by sorted POSIX relative path followed by NUL, file bytes, and NUL. Reject symlinks and any manifest path that is absolute or contains `..`.

`TectonicRuntime` contains only verified execution inputs:

```python
@dataclass(frozen=True)
class TectonicRuntime:
    command: tuple[str, ...]
    offline_flag: str
    cache_dir: Path | None
    status: str
```

`verify_bundled_tectonic()` verifies the executable SHA-256, executable bit on POSIX, cache canonical SHA-256, and Tectonic version from `tectonic --version` before returning a runtime.

- [ ] **Step 4: Replace the manifest with locked upstream archive inputs**

Use schema version 1 and these GitHub-published Tectonic 0.16.9 archive records. This version is the first selected release containing the required macOS arm64 `fontspec` crash fix:

```json
{
  "schema_version": 1,
  "tectonic_version": "0.16.9",
  "licence": "MIT",
  "default_bundle_url": "https://relay.fullyjustified.net/default_bundle_v33.tar",
  "default_bundle_sha256": "6ffe055852f8faf66c0acbe1a7fb27f87b869a90bad1204f3bf4d9683f597c7c",
  "platforms": {
    "windows-x86_64": {
      "archive_url": "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.16.9/tectonic-0.16.9-x86_64-pc-windows-msvc.zip",
      "archive_sha256": "131a24604785a9600989a3d91225f597df52ac06f00aeffe86fd529f99ee5cdd",
      "archive_member": "tectonic.exe",
      "executable_path": "tectonic/tectonic.exe",
      "cache_path": "tectonic/cache",
      "lock_path": "tectonic-locks/windows-x86_64.json",
      "offline_flag": "--only-cached"
    },
    "macos-arm64": {
      "archive_url": "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.16.9/tectonic-0.16.9-aarch64-apple-darwin.tar.gz",
      "archive_sha256": "edb67c61aba768289f6da441c9e6f523cfaff4f8b2a5708523ef29c543f8e88e",
      "archive_member": "tectonic",
      "executable_path": "tectonic/tectonic",
      "cache_path": "tectonic/cache",
      "lock_path": "tectonic-locks/macos-arm64.json",
      "offline_flag": "--only-cached"
    },
    "linux-x86_64": {
      "archive_url": "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.16.9/tectonic-0.16.9-x86_64-unknown-linux-gnu.tar.gz",
      "archive_sha256": "f3c825128095dc3399ea11c08c18035b33050a216930c295c79e8eb11bd21de4",
      "archive_member": "tectonic",
      "executable_path": "tectonic/tectonic",
      "cache_path": "tectonic/cache",
      "lock_path": "tectonic-locks/linux-x86_64.json",
      "offline_flag": "--only-cached"
    }
  }
}
```

The native lock file supplies `executable_sha256` and `cache_sha256`; loading fails when the lock file is absent.

- [ ] **Step 5: Verify manifest and integrity behavior**

Run: `uv run pytest -q tests/report/test_tectonic.py`

Expected: PASS for valid fake bundles and deterministic failures for every tamper/path case.

- [ ] **Step 6: Commit the runtime trust model**

```bash
git add src/insulation_coordination/report/tectonic.py \
  packaging/tectonic-manifest.json tests/report/test_tectonic.py
git commit -m "feat: verify bundled tectonic runtime"
```

---

### Task 4: Compile with an Explicit Offline Cache

**Files:**
- Modify: `src/insulation_coordination/report/compiler.py`
- Modify: `src/insulation_coordination/ui/report_page.py`
- Modify: `scripts/demo_report.py`
- Modify: `tests/report/test_compiler.py`
- Modify: `tests/ui/test_report_page.py`

**Interfaces:**
- Consumes: `TectonicRuntime`
- Modifies: `compile_pdf(tex_path, output_path, tectonic, *, offline_flag=None, cache_dir=None) -> CompileResult`
- Produces: subprocess environment with `TECTONIC_CACHE_DIR` set only when `cache_dir` is supplied

- [ ] **Step 1: Add failing explicit-flag and isolated-cache assertions**

Extend the fake compiler to print its `TECTONIC_CACHE_DIR` and the contents of
`seed.txt` from that directory. Add:

```python
def test_compile_pdf_uses_declared_flag_and_cache(tmp_path: Path) -> None:
    tex = _tex(tmp_path)
    command = _fake_tectonic(tmp_path / "tectonic")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "seed.txt").write_text("seed", encoding="utf-8")

    result = compile_pdf(
        tex,
        tmp_path / "report.pdf",
        command,
        offline_flag="--only-cached",
        cache_dir=cache,
    )

    assert result.success
    assert "--only-cached" in result.stdout
    assert "SEED=seed" in result.stdout
    assert str(cache.resolve()) not in result.stdout
    assert (cache / "seed.txt").read_text(encoding="utf-8") == "seed"
```

Add tests rejecting a missing/non-directory cache and ensuring the subprocess inherits the normal environment except for the resolved `TECTONIC_CACHE_DIR` override.

- [ ] **Step 2: Run focused tests and confirm the new keyword arguments fail**

Run: `uv run pytest -q tests/report/test_compiler.py tests/ui/test_report_page.py`

Expected: FAIL because `compile_pdf()` does not accept `offline_flag` or `cache_dir`.

- [ ] **Step 3: Implement explicit runtime execution**

Pass `offline_flag or _offline_flag(command)` into `_run_tectonic()`. When `cache_dir` is supplied, resolve it strictly, require a directory, copy it to an isolated `tectonic-cache` directory inside the compilation temporary directory, copy `os.environ`, set `TECTONIC_CACHE_DIR` to the private copy, and pass `env=environment` to `subprocess.run()`. This keeps the verified packaged cache immutable and makes concurrent compiles independent.

Do not mutate `os.environ`. Preserve direct fake-compiler tests by keeping the existing command parameter and automatic flag detection when no explicit flag is provided.

- [ ] **Step 4: Resolve Tectonic outside the report widget**

Remove `find_tectonic()` and `_bundled_tectonic()` from `report_page.py`. Resolve a `TectonicRuntime` through `resolve_tectonic_runtime(self._tectonic)` and call:

```python
result = compile_pdf(
    tex,
    destination / f"{self._basename()}.pdf",
    runtime.command,
    offline_flag=runtime.offline_flag,
    cache_dir=runtime.cache_dir,
)
```

Update `scripts/demo_report.py` to use the same source-runtime resolver. Convert `TectonicIntegrityError` and `CompileError` to the report page's existing actionable `RuntimeError` path.

- [ ] **Step 5: Verify compiler and report integration**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -q tests/report/test_compiler.py tests/ui/test_report_page.py tests/test_end_to_end.py`

Expected: PASS; fake commands remain supported and cache/flag inputs are explicit.

- [ ] **Step 6: Commit offline compiler integration**

```bash
git add src/insulation_coordination/report/compiler.py \
  src/insulation_coordination/ui/report_page.py scripts/demo_report.py \
  tests/report/test_compiler.py tests/ui/test_report_page.py
git commit -m "feat: compile reports with verified offline cache"
```

---

### Task 5: Add the Packaged Release Diagnostic

**Files:**
- Create: `src/insulation_coordination/release_diagnostic.py`
- Modify: `src/insulation_coordination/cli.py`
- Create: `scripts/create_release_fixtures.py`
- Create: `tests/test_release_diagnostic.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: project/rules persistence, `calculate_pair`, `group_results`, report model/render/compiler, `TectonicRuntime`
- Produces: `ReleaseReportSource(project_sha256: str, rules_sha256: str, tex_path: Path)`
- Produces: `render_release_tex(project_path: Path, rules_path: Path, output_dir: Path) -> ReleaseReportSource`
- Produces: `ReleaseDiagnosticResult(success: bool, project_sha256: str, rules_sha256: str, tex_path: Path, pdf_path: Path, log_path: Path)`
- Produces: `run_release_diagnostic(project_path: Path, rules_path: Path, output_dir: Path, runtime: TectonicRuntime | None = None) -> ReleaseDiagnosticResult`
- Produces CLI: `icc --release-diagnostic PROJECT.icproj PACKAGE.icrules OUTPUT_DIR`

- [ ] **Step 1: Write a failing diagnostic end-to-end test**

```python
def test_release_diagnostic_loads_calculates_and_compiles(
    tmp_path: Path, release_fixture: tuple[Path, Path]
) -> None:
    project_path, rules_path = release_fixture
    runtime = TectonicRuntime(
        command=_fake_tectonic(tmp_path / "tectonic"),
        offline_flag="--only-cached",
        cache_dir=None,
        status="test",
    )

    result = run_release_diagnostic(project_path, rules_path, tmp_path / "output", runtime)

    assert result.success
    assert result.tex_path.exists()
    assert result.pdf_path.exists()
    assert result.rules_sha256 == load_rule_package(rules_path).package_sha256
```

Add failure tests for project/rules hash mismatch, an incomplete pair, compiler failure, and a destination containing a pre-existing symlink leaf.

- [ ] **Step 2: Run the diagnostic test and verify the missing module failure**

Run: `uv run pytest -q tests/test_release_diagnostic.py`

Expected: FAIL while importing `insulation_coordination.release_diagnostic`.

- [ ] **Step 3: Implement the diagnostic using production boundaries**

Implement `render_release_tex()` by loading both files through production loaders, asserting the project's required rules ID, version, and SHA-256 match, calculating all pairs, building groups/model, and writing `.tex`. `run_release_diagnostic()` calls that function, compiles with the supplied or resolved runtime, requires `CompileResult.success`, and returns the frozen result model.

The CLI diagnostic writes `release-diagnostic.json` with `model_dump(mode="json")`, prints only its path, and returns 1 on a caught diagnostic error.

- [ ] **Step 4: Add deterministic synthetic fixture generation**

Refactor the reusable synthetic project builder from `scripts/demo_report.py` into `scripts/create_release_fixtures.py`. Its command writes only:

```text
release-smoke/project.icproj
release-smoke/rules.icrules
```

Use `save_project_atomic()` and `write_rule_package()`. Add `/build/`, `/dist/`, `/Output/`, and `/release-smoke/` to `.gitignore` while preserving the existing ignored private locations.

- [ ] **Step 5: Verify the diagnostic and CLI parser**

Run: `uv run pytest -q tests/test_release_diagnostic.py tests/test_package.py tests/test_end_to_end.py`

Expected: PASS; the diagnostic JSON contains no rule table values or project input matrix.

- [ ] **Step 6: Commit the diagnostic**

```bash
git add .gitignore src/insulation_coordination/release_diagnostic.py \
  src/insulation_coordination/cli.py scripts/create_release_fixtures.py \
  scripts/demo_report.py tests/test_release_diagnostic.py tests/test_package.py
git commit -m "feat: add packaged release diagnostic"
```

---

### Task 6: Prepare and Lock Native Tectonic Staging

**Files:**
- Create: `scripts/prepare_tectonic.py`
- Create: `tests/packaging/__init__.py`
- Create: `tests/packaging/test_prepare_tectonic.py`
- Create: `.github/workflows/tectonic-locks.yml`
- Create through native lock workflow: `packaging/tectonic-locks/windows-x86_64.json`
- Create through native lock workflow: `packaging/tectonic-locks/macos-arm64.json`
- Create through native lock workflow: `packaging/tectonic-locks/linux-x86_64.json`

**Interfaces:**
- Consumes: `packaging/tectonic-manifest.json`, generated release fixtures, `render_release_tex()`, `canonical_tree_sha256()`
- Produces: `prepare_tectonic(platform_key: str, destination: Path, *, refresh_lock: bool = False, manifest_path: Path | None = None) -> Path`
- Produces native lock JSON: `{"platform_key", "tectonic_version", "executable_sha256", "cache_sha256"}`

- [ ] **Step 1: Write failing safe-download/extraction tests with local archives**

```python
def test_prepare_tectonic_rejects_archive_hash_mismatch(tmp_path: Path) -> None:
    manifest = _fake_manifest(tmp_path, archive_bytes=b"archive", claimed_sha="0" * 64)
    with pytest.raises(TectonicPreparationError, match="archive SHA-256"):
        prepare_tectonic("linux-x86_64", tmp_path / "stage", manifest_path=manifest)


def test_safe_extract_rejects_parent_member(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    _write_tar(archive, {"../tectonic": b"binary"})
    with pytest.raises(TectonicPreparationError, match="archive member"):
        extract_declared_member(archive, "../tectonic", tmp_path / "out")
```

Add a fake compiler script that writes a valid PDF on the online warm pass, records `TECTONIC_CACHE_DIR`, and requires the declared offline flag on the second pass. Assert staging contains only the executable, cache, copied manifest, and copied native lock.

- [ ] **Step 2: Run preparation tests and confirm the missing script failure**

Run: `uv run pytest -q tests/packaging/test_prepare_tectonic.py`

Expected: FAIL because `scripts.prepare_tectonic` is absent.

- [ ] **Step 3: Implement verified download, safe extraction, and cache warming**

Use only the standard library (`urllib.request`, `hashlib`, `tarfile`, `zipfile`, `tempfile`, `subprocess`). Download to a temporary file, verify `archive_sha256`, extract only `archive_member`, and reject absolute/parent paths.

Call `render_release_tex()` to create the representative `.tex`. Warm an isolated `TECTONIC_CACHE_DIR` by running the staged executable against that file once without the cached-only flag. Immediately rerun with `offline_flag`, `HOME` set to an empty temporary directory, and proxy variables set to `http://127.0.0.1:9`. Require a valid PDF from the offline pass.

- [ ] **Step 4: Implement native lock refresh and normal verification modes**

On macOS, ad-hoc sign the extracted Tectonic executable before hashing it; the same signed bytes are later copied as PyInstaller data without re-signing. `--refresh-lock` writes a complete lock JSON from the final staged executable/cache. Normal mode loads the committed lock and rejects either hash mismatch. Both modes run `tectonic --version` and require `Tectonic 0.16.9`.

The command interface is:

```bash
uv run python scripts/prepare_tectonic.py \
  --platform linux-x86_64 \
  --destination build/tectonic/linux-x86_64 \
  --fixtures release-smoke
```

- [ ] **Step 5: Add the native lock-refresh workflow and collect all three locks**

Create a manual workflow with a native matrix. Each job checks out the same commit, generates synthetic fixtures, runs `prepare_tectonic.py --refresh-lock`, reruns normal verification, and uploads exactly one lock JSON.

Run the workflow, download the three lock artifacts, and place them under `packaging/tectonic-locks/`. Validate locally:

Run: `uv run pytest -q tests/report/test_tectonic.py tests/packaging/test_prepare_tectonic.py`

Expected: PASS and every manifest `lock_path` resolves to a committed strict JSON file.

- [ ] **Step 6: Commit preparation and native locks**

```bash
git add scripts/prepare_tectonic.py tests/packaging \
  .github/workflows/tectonic-locks.yml packaging/tectonic-locks
git commit -m "build: lock native offline tectonic bundles"
```

---

### Task 7: Build One Shared Platform-Aware PyInstaller Application

**Files:**
- Modify: `packaging/insulation_coordination.spec`
- Create: `packaging/assets/icc.svg`
- Create: `scripts/render_icons.py`
- Create: `packaging/macos/Info.plist`
- Create: `tests/packaging/test_package_metadata.py`

**Interfaces:**
- Consumes: staged `build/tectonic/<platform-key>/tectonic/`
- Produces: Windows/Linux `dist/icc/` and macOS `dist/Insulation Coordination Calculator.app`

- [ ] **Step 1: Write failing static metadata tests**

```python
def test_pyinstaller_spec_bundles_templates_manifest_and_tectonic() -> None:
    spec = (ROOT / "packaging/insulation_coordination.spec").read_text(encoding="utf-8")
    for required in (
        "report/templates",
        "tectonic-manifest.json",
        "tectonic-locks",
        "build/tectonic",
        "CFBundleDocumentTypes",
    ):
        assert required in spec


def test_macos_document_types_route_both_extensions() -> None:
    plist = plistlib.loads((ROOT / "packaging/macos/Info.plist").read_bytes())
    extensions = {
        extension
        for item in plist["CFBundleDocumentTypes"]
        for extension in item["CFBundleTypeExtensions"]
    }
    assert extensions == {"icproj", "icrules"}


def test_native_icons_are_rendered_from_one_svg(tmp_path: Path) -> None:
    outputs = render_icons(ROOT / "packaging/assets/icc.svg", tmp_path)
    assert {path.suffix for path in outputs} == {".png", ".ico", ".icns"}
    assert all(path.stat().st_size > 0 for path in outputs)
```

- [ ] **Step 2: Run the metadata tests and confirm missing package inputs**

Run: `uv run pytest -q tests/packaging/test_package_metadata.py`

Expected: FAIL because the staged Tectonic data, external plist, and icon are not wired into the spec.

- [ ] **Step 3: Add the vector icon source**

Create this deterministic SVG without external assets:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="#17324d"/>
  <path d="M128 112v288M384 112v288" stroke="#f3b61f" stroke-width="34"/>
  <path d="M176 256h160m-28-28 28 28-28 28m-104 0-28-28 28-28"
        fill="none" stroke="#ffffff" stroke-width="24" stroke-linecap="round"
        stroke-linejoin="round"/>
</svg>
```

- [ ] **Step 4: Make the spec platform-aware**

Implement `render_icons(source: Path, destination: Path) -> tuple[Path, ...]` with `QSvgRenderer`, a transparent 512×512 `QImage`, and `QPainter`; save the same rendered image as PNG, ICO, and ICNS through Qt's native image writers. The packaging workflows run this script before PyInstaller.

Derive `platform_key` from `sys.platform` and `platform.machine()`, require the matching staged Tectonic directory, and add it plus the manifest/locks/templates as `datas` or `binaries` with stable relative paths.

Set `console=False` for Windows and macOS and `console=True` for Linux. Use the generated ICO on Windows, ICNS in the macOS `BUNDLE`, and PNG/SVG in Linux staging. Add the already ad-hoc-signed macOS Tectonic executable as data so PyInstaller does not rewrite its locked bytes. Use `BUNDLE` on macOS with the committed Info.plist fields; use `COLLECT` on Windows/Linux. Keep private/test paths excluded.

- [ ] **Step 5: Build and inspect the host-native artifact**

Run:

```bash
uv run python scripts/create_release_fixtures.py release-smoke
uv run python scripts/render_icons.py packaging/assets/icc.svg build/icons
uv run python scripts/prepare_tectonic.py \
  --platform macos-arm64 --destination build/tectonic/macos-arm64 \
  --fixtures release-smoke
uv run pyinstaller --noconfirm packaging/insulation_coordination.spec
```

Use the platform key matching the host. Verify the frozen tree contains templates, manifest, lock, Tectonic executable, and cache, then execute its `--release-diagnostic` command.

- [ ] **Step 6: Run package metadata and Python quality checks**

Run: `uv run pytest -q tests/packaging/test_package_metadata.py tests/test_release_diagnostic.py && uv run ruff check . && uv run mypy`

Expected: PASS.

- [ ] **Step 7: Commit the shared package build**

```bash
git add packaging/insulation_coordination.spec packaging/assets/icc.svg \
  scripts/render_icons.py \
  packaging/macos/Info.plist tests/packaging/test_package_metadata.py
git commit -m "build: create shared native application bundle"
```

---

### Task 8: Complete and Smoke-Test the Windows Installer

**Files:**
- Modify: `installer/insulation-coordination.iss`
- Create: `packaging/windows/smoke.ps1`
- Create: `.github/workflows/release.yml`
- Modify: `tests/packaging/test_package_metadata.py`
- Delete: `.github/workflows/windows-package.yml`

**Interfaces:**
- Consumes: `dist/icc/`, release fixtures, Windows native Tectonic staging
- Produces: `dist/release/insulation-coordination-<version>-windows-x86_64-setup.exe`
- Produces: `dist/release/windows-x86_64.metadata.json`

- [ ] **Step 1: Add failing installer-contract assertions**

```python
def test_windows_installer_preserves_user_rules_and_routes_documents() -> None:
    script = (ROOT / "installer/insulation-coordination.iss").read_text(encoding="utf-8")
    assert "[UninstallDelete]" not in script
    assert '""%1""' in script
    assert ".icproj" in script and ".icrules" in script
    assert "desktopicon" in script
    assert "AppVersion" in script
```

- [ ] **Step 2: Run the contract test and confirm current uninstall behavior fails**

Run: `uv run pytest -q tests/packaging/test_package_metadata.py -k windows`

Expected: FAIL because `[UninstallDelete]` removes installed private rules and versioning is fixed.

- [ ] **Step 3: Correct the Inno Setup definition**

Use AppId `{9A3B7D2E-4C21-4F0A-9D2C-1C0C0A1D0001}`, accept `/DAppVersion=<version>`, add an optional desktop icon task, retain per-user installation and both registry associations, and remove all user-data deletion directives. Output the versioned installer filename.

- [ ] **Step 4: Implement installed Windows smoke acceptance**

The PowerShell script must:

1. seed `$env:LOCALAPPDATA\icc\rules\preserve-me.txt`;
2. install with `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`;
3. assert `icc.exe` and both HKCU association commands exist;
4. run `icc.exe --release-diagnostic ...` and require a valid PDF/result JSON;
5. run the generated uninstaller silently;
6. assert the seeded rules file remains.

Any failed native command terminates through `$ErrorActionPreference = "Stop"`.

- [ ] **Step 5: Add the Windows release job**

The job uses `windows-latest`, Python 3.12, uv, the fixture/preparation scripts, PyInstaller, Inno Setup, and `packaging/windows/smoke.ps1`. It scans `dist/icc` before installer creation and uploads the installer plus metadata.

Add optional Authenticode steps guarded by non-empty `WINDOWS_PFX_BASE64`, `WINDOWS_PFX_PASSWORD`, and `WINDOWS_TIMESTAMP_URL` secrets. Sign application PE files before Inno Setup but exclude `tectonic/tectonic.exe` so its repository lock remains valid. Sign the installer afterward with SHA-256/RFC3161, run `signtool verify /pa /v`, and set metadata to `trusted` only after verification. Without secrets, metadata is `unsigned`.

- [ ] **Step 6: Run local static checks and dispatch the Windows job**

Run: `uv run pytest -q tests/packaging/test_package_metadata.py`

Then dispatch `release.yml` for the current branch and verify `packaging/windows/smoke.ps1` passes on the hosted runner.

- [ ] **Step 7: Commit Windows packaging**

```bash
git add installer/insulation-coordination.iss packaging/windows/smoke.ps1 \
  .github/workflows/release.yml tests/packaging/test_package_metadata.py
git rm .github/workflows/windows-package.yml
git commit -m "build: package and smoke test windows release"
```

---

### Task 9: Build, Ad-Hoc Sign, and Smoke-Test the macOS DMG

**Files:**
- Create: `packaging/macos/package.sh`
- Create: `packaging/macos/sign-and-notarize.sh`
- Modify: `.github/workflows/release.yml`
- Modify: `tests/packaging/test_package_metadata.py`
- Delete: `.github/workflows/macos-package.yml`

**Interfaces:**
- Consumes: `dist/Insulation Coordination Calculator.app`, release fixtures, macOS native Tectonic staging
- Produces: `dist/release/insulation-coordination-<version>-macos-arm64.dmg`
- Produces: `dist/release/macos-arm64.metadata.json`

- [ ] **Step 1: Add failing macOS package-script assertions**

```python
def test_macos_package_verifies_ad_hoc_signature_and_dmg() -> None:
    script = (ROOT / "packaging/macos/package.sh").read_text(encoding="utf-8")
    for required in (
        "codesign --force --sign -",
        "codesign --verify --deep --strict",
        "hdiutil create",
        "--release-diagnostic",
    ):
        assert required in script
```

- [ ] **Step 2: Run the assertion and confirm the script is absent**

Run: `uv run pytest -q tests/packaging/test_package_metadata.py -k macos`

Expected: FAIL because `packaging/macos/package.sh` does not exist.

- [ ] **Step 3: Implement ad-hoc signing, DMG creation, and smoke acceptance**

Use `set -euo pipefail`. Verify the staged Tectonic executable still matches its native lock and is already ad-hoc signed. Sign other unsigned nested executable files, then the outer app with identity `-`; do not force-resign the locked Tectonic executable. Verify with `codesign --verify --deep --strict --verbose=2`. Run the app's MacOS executable directly with `--release-diagnostic`, validate the PDF, create a compressed DMG using `hdiutil create -format UDZO`, mount it read-only, rerun `codesign --verify`, and detach it.

- [ ] **Step 4: Add the optional Developer ID/notarization script**

The script runs only when all four environment variables exist: `MACOS_CERTIFICATE_P12`, `MACOS_CERTIFICATE_PASSWORD`, `APPLE_NOTARY_KEY_ID`, and `APPLE_NOTARY_ISSUER_ID`, with the private API key supplied as `APPLE_NOTARY_KEY_P8`.

Import the P12 into a temporary keychain, sign nested code with hardened runtime, recompute the copied Tectonic executable hash in the app's embedded native lock, then sign the outer app so its Developer ID signature seals that updated lock. Recreate the DMG, submit using `xcrun notarytool submit --wait`, staple with `xcrun stapler staple`, and verify with `spctl --assess` and `xcrun stapler validate`. Delete the temporary keychain through a shell trap.

- [ ] **Step 5: Add the macOS release job**

Use an arm64 GitHub-hosted macOS runner, Python 3.12, uv, fixture/preparation scripts, PyInstaller, and `package.sh`. Upload the DMG and metadata. Metadata is `ad-hoc` after free-path verification or `notarized` only after the optional script verifies the stapled ticket.

- [ ] **Step 6: Run static checks and dispatch the macOS job**

Run: `uv run pytest -q tests/packaging/test_package_metadata.py`

Dispatch `release.yml`, download the DMG, mount it on a clean macOS account, and confirm Finder right-click → Open launches the app without modifying the package.

- [ ] **Step 7: Commit macOS packaging**

```bash
git add packaging/macos/package.sh packaging/macos/sign-and-notarize.sh \
  .github/workflows/release.yml tests/packaging/test_package_metadata.py
git rm .github/workflows/macos-package.yml
git commit -m "build: package and smoke test macos release"
```

---

### Task 10: Build, Integrate, and Smoke-Test Linux Artifacts

**Files:**
- Create: `packaging/linux/AppRun`
- Create: `packaging/linux/icc.desktop`
- Create: `packaging/linux/application-x-icc.xml`
- Create: `packaging/linux/package.sh`
- Modify: `.github/workflows/release.yml`
- Modify: `tests/packaging/test_package_metadata.py`

**Interfaces:**
- Consumes: `dist/icc/`, release fixtures, Linux native Tectonic staging
- Produces: `dist/release/insulation-coordination-<version>-linux-x86_64.AppImage`
- Produces: `dist/release/insulation-coordination-<version>-linux-x86_64.tar.gz`
- Produces: `dist/release/linux-x86_64.metadata.json`

- [ ] **Step 1: Add failing Linux desktop/MIME assertions**

```python
def test_linux_metadata_routes_both_document_types() -> None:
    desktop = (ROOT / "packaging/linux/icc.desktop").read_text(encoding="utf-8")
    mime = ET.parse(ROOT / "packaging/linux/application-x-icc.xml")
    assert "application/x-icc-project" in desktop
    assert "application/x-icc-rules" in desktop
    patterns = {node.attrib["pattern"] for node in mime.findall(".//{*}glob")}
    assert patterns == {"*.icproj", "*.icrules"}
```

- [ ] **Step 2: Run the assertion and confirm Linux package files are absent**

Run: `uv run pytest -q tests/packaging/test_package_metadata.py -k linux`

Expected: FAIL while reading the missing metadata files.

- [ ] **Step 3: Implement AppDir and portable archive construction**

`AppRun` resolves its own directory and executes `usr/bin/icc "$@"`. The desktop entry uses `Exec=icc %f`, declares both MIME types, and points to the SVG icon.

`package.sh` copies `dist/icc` to `AppDir/usr/lib/icc`, creates `AppDir/usr/bin/icc` as a relative launcher, installs desktop/MIME/icon files, and builds both deterministic tar.gz and AppImage outputs. Use `SOURCE_DATE_EPOCH` from the source commit and sorted tar members.

- [ ] **Step 4: Pin and verify AppImageTool**

Download:

```text
https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
```

Require SHA-256:

```text
a6d71e2b6cd66f8e8d16c37ad164658985e0cf5fcaa950c90a482890cb9d13e0
```

Fail before execution on mismatch. Run AppImageTool with `ARCH=x86_64` and `--no-appstream`.

- [ ] **Step 5: Add Linux smoke and optional GPG signing**

Run the portable executable and AppImage with `--release-diagnostic`; set `APPIMAGE_EXTRACT_AND_RUN=1` for CI environments without FUSE. Validate the desktop file with `desktop-file-validate` and install MIME XML into an isolated `XDG_DATA_HOME` with `xdg-mime`.

If `GPG_PRIVATE_KEY` and `GPG_PASSPHRASE` are non-empty, import the key into a temporary `GNUPGHOME`, create detached armored signatures for both artifacts and the checksum file, verify them, and set metadata signing status to `trusted`. Otherwise set it to `unsigned`.

- [ ] **Step 6: Add and dispatch the Linux release job**

Use `ubuntu-latest`, install only Qt runtime libraries plus `desktop-file-utils` and `shared-mime-info`, then run the shared fixture/preparation/PyInstaller/package flow. Upload AppImage, tar.gz, metadata, and optional `.asc` files.

Run: `uv run pytest -q tests/packaging/test_package_metadata.py`

Dispatch `release.yml` and verify both artifacts complete the diagnostic.

- [ ] **Step 7: Commit Linux packaging**

```bash
git add packaging/linux .github/workflows/release.yml \
  tests/packaging/test_package_metadata.py
git commit -m "build: package and smoke test linux release"
```

---

### Task 11: Assemble Checksums, Metadata, and Private-Content Gates

**Files:**
- Create: `scripts/release_artifacts.py`
- Create: `tests/packaging/test_release_artifacts.py`
- Modify: `.github/workflows/release.yml`

**Interfaces:**
- Produces: `scan_forbidden(root: Path) -> tuple[str, ...]`
- Produces: `build_release_index(artifact_dir: Path) -> dict[str, object]`
- Produces: `write_sha256sums(artifact_dir: Path, artifacts: Sequence[Path]) -> Path`
- Produces: `dist/release/release-index.json`
- Produces: `dist/release/SHA256SUMS`

- [ ] **Step 1: Write failing release-index and forbidden-content tests**

```python
def test_release_index_rejects_duplicate_platform_metadata(tmp_path: Path) -> None:
    _write_metadata(tmp_path / "a.json", platform="linux-x86_64")
    _write_metadata(tmp_path / "b.json", platform="linux-x86_64")
    with pytest.raises(ReleaseArtifactError, match="duplicate platform"):
        build_release_index(tmp_path)


@pytest.mark.parametrize(
    "name",
    (
        "standard.pdf",
        "private.icrules",
        "customer.icproj",
        "audit-inventory.json",
        "table-iec60664-1-f5.csv",
        "__pycache__/module.pyc",
    ),
)
def test_forbidden_release_member_is_reported(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"private")
    assert scan_forbidden(tmp_path)
```

Add tests requiring exactly `windows-x86_64`, `macos-arm64`, and `linux-x86_64`, verifying every declared artifact hash/size, sorting `SHA256SUMS`, and rejecting signing status outside `unsigned`, `ad-hoc`, `trusted`, `notarized`.

- [ ] **Step 2: Run focused tests and confirm the script is absent**

Run: `uv run pytest -q tests/packaging/test_release_artifacts.py`

Expected: FAIL while importing `scripts.release_artifacts`.

- [ ] **Step 3: Implement strict artifact assembly**

Use JSON schema version 1 with exact fields from the design. Resolve only leaf filenames inside the artifact directory. Hash files in chunks, compare metadata size/hash, reject duplicate names/platforms, and atomically write `release-index.json` and `SHA256SUMS`.

Scan directories and archive member names for forbidden extensions/names before container creation in native jobs and again over downloaded release files in assembly. Do not print file contents.

- [ ] **Step 4: Add the release assembly job**

The job depends on all three native jobs, downloads their artifacts into separate directories, flattens only declared public files, runs `release_artifacts.py`, verifies `sha256sum --check`, and uploads the complete release bundle.

On `v*` tags, use `gh release create "$GITHUB_REF_NAME" --generate-notes` followed by `gh release upload` for files listed by `release-index.json`. On manual dispatch, upload only the Actions artifact.

- [ ] **Step 5: Verify release assembly tests and workflow syntax**

Run: `uv run pytest -q tests/packaging/test_release_artifacts.py tests/packaging/test_package_metadata.py`

Run: `git diff --check`

Dispatch the full workflow and require one assembly artifact containing three platform metadata files, the release index, checksum file, Windows installer, macOS DMG, Linux AppImage, and Linux tar.gz.

- [ ] **Step 6: Commit release assembly**

```bash
git add scripts/release_artifacts.py tests/packaging/test_release_artifacts.py \
  .github/workflows/release.yml
git commit -m "build: assemble verified cross-platform release"
```

---

### Task 12: Document Free Installation and Close Release Acceptance

**Files:**
- Modify: `README.md`
- Replace: `docs/release-checklist.md`
- Create: `scripts/record_private_review_digest.py`
- Modify: `tests/private/test_supplied_standards.py`
- Modify: `tests/test_package.py`

**Interfaces:**
- Produces: `record_private_review_digest(paths: tuple[Path, Path], destination: Path) -> str`
- Produces: platform download/install/warning/checksum instructions
- Produces: an evidence-oriented release checklist separating automated and manual gates

- [ ] **Step 1: Add failing documentation assertions**

```python
def test_readme_documents_free_cross_platform_release() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for required in (
        "Windows x86_64",
        "macOS arm64",
        "Linux x86_64",
        "SHA256SUMS",
        "right-click",
        "unsigned",
        "AppImage",
        ".icproj",
        ".icrules",
    ):
        assert required in readme
```

Add a private test that writes a reviewed-digest file to a temporary path and asserts its exact 64-lowercase-hex format without printing extracted values.

- [ ] **Step 2: Run documentation/private tests and confirm missing guidance**

Run: `uv run pytest -q tests/test_package.py tests/private/test_supplied_standards.py`

Expected: FAIL on README assertions; the existing private digest comparison may remain skipped until the local reviewed digest is recorded.

- [ ] **Step 3: Implement explicit human-reviewed digest recording**

The script accepts the two licensed PDF paths plus `--destination`. It extracts the draft, prints only standard identities, raw-grid dimensions, review-item count, and the digest, then requires the operator to type `I reviewed these extracted sources` before atomically writing the digest. Reuse the stable digest function from the private test by moving it to `rules/importer/review.py` as `draft_review_digest(draft) -> str`.

Never auto-accept raw cells or equations in this script. The confirmation records human responsibility; calculation approval remains in the Rules Manager.

- [ ] **Step 4: Replace the release checklist with evidence fields**

For each automated gate, record the workflow run URL, commit SHA, artifact SHA-256, and pass/fail result. For manual Windows/macOS/Linux checks, record tester, date, OS version, clean account/machine, file-association result, offline PDF result, warning observed, and user-data preservation result.

Keep the corrected IEC PCB review/calculation checks and mark them complete only from the private-standard test and Rules Manager acceptance.

- [ ] **Step 5: Add README download and free-install instructions**

Explain:

- Windows: installer is unsigned, expected warning, exact association behavior, and checksum verification with `Get-FileHash`.
- macOS: DMG is ad-hoc signed but not notarized, Finder right-click → Open, and verification with `shasum -a 256`.
- Linux: `chmod +x`, AppImage launch, tar fallback, optional GPG verification, and desktop/MIME integration.
- All platforms: bundled Tectonic is verified and report compilation is offline.

- [ ] **Step 6: Run the complete repository verification**

Run:

```bash
uv run ruff check .
uv run mypy
QT_QPA_PLATFORM=offscreen uv run pytest -v
git diff --check
```

Expected: all public tests pass; the private digest test passes when the ignored reviewed digest is present and otherwise skips with its existing explicit reason.

- [ ] **Step 7: Run the full native release and manual acceptance**

Dispatch `release.yml` for the final commit. Verify the assembly checksums locally, then execute every manual checklist row once on clean Windows, macOS, and Linux environments. Do not publish V1 until all required rows contain evidence.

- [ ] **Step 8: Commit release documentation and acceptance tooling**

```bash
git add README.md docs/release-checklist.md \
  scripts/record_private_review_digest.py \
  src/insulation_coordination/rules/importer/review.py \
  tests/private/test_supplied_standards.py tests/test_package.py
git commit -m "docs: complete free cross-platform release acceptance"
```

---

## Design Coverage

| Approved design area | Implemented and verified by |
| --- | --- |
| Artifact architecture and platform scope | Tasks 7–10 |
| Application startup and file opening | Tasks 1–2 |
| Bundled offline Tectonic | Tasks 3–6 |
| Windows, macOS, and Linux packages | Tasks 7–10 |
| Release metadata and optional signing | Tasks 8–11 |
| Packaged diagnostic flow | Task 5 and native smoke steps in Tasks 8–10 |
| Error handling and tamper rejection | Tasks 1–6 and Task 11 |
| Automated verification and release acceptance | Tasks 8–12 |
| User-facing installation documentation | Task 12 |

## Plan Completion Criteria

The implementation is complete only when all twelve focused commits exist, the
full Python quality gate passes, the three native package jobs pass for one
commit, release assembly verifies every checksum, the private-standard reviewed
digest gate is satisfied, and the clean-machine acceptance checklist is signed
off for Windows, macOS, and Linux.
