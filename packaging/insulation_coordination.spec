import platform
import plistlib
import os
import sys
from pathlib import Path

root = Path(SPECPATH).resolve().parent.parent
machine = platform.machine().lower()
if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
    platform_key = "windows-x86_64"
elif sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
    platform_key = "macos-arm64"
elif sys.platform.startswith("linux") and machine in {"amd64", "x86_64"}:
    platform_key = "linux-x86_64"
else:
    raise SystemExit(f"unsupported release platform: {sys.platform}/{machine}")

# Native inputs are staged outside PyInstaller's --clean work tree.
tectonic_root = Path(os.environ.get("TECTONIC_STAGE_ROOT", root / ".release-tectonic"))
tectonic_stage = tectonic_root / platform_key
tectonic_manifest = root / "packaging" / "tectonic-manifest.json"
tectonic_lock = root / "packaging" / "tectonic-locks" / f"{platform_key}.json"
tectonic_executable = tectonic_stage / "tectonic" / (
    "tectonic.exe" if platform_key == "windows-x86_64" else "tectonic"
)
tectonic_cache = tectonic_stage / "tectonic" / "cache"
for required in (tectonic_executable, tectonic_cache, tectonic_lock):
    if not required.exists():
        raise SystemExit(f"missing native release input: {required}")

datas = [
    (str(root / "src" / "insulation_coordination" / "report" / "templates"),
     "insulation_coordination/report/templates"),
    (str(tectonic_manifest), "."),
    (str(tectonic_stage / "tectonic"), "tectonic"),
    (str(tectonic_lock), "tectonic-locks"),
    (str(root / "packaging" / "assets" / "icc.svg"), "assets"),
]

# The macOS Info.plist contains CFBundleDocumentTypes for .icproj and .icrules.

hiddenimports = [
    "insulation_coordination.report.templates",
    "pypdf",
    "pdfplumber",
    "platformdirs",
    "jinja2",
]

a = Analysis(
    [str(root / "src" / "insulation_coordination" / "cli.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "pytest",
        "tests",
        "hypothesis",
        "mypy",
        "ruff",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

icon_path = root / "build" / "icons" / ("icc.ico" if sys.platform == "win32" else "icc.icns")

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="icc",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        icon=str(icon_path),
        console=False,
    )
    app = BUNDLE(
        exe,
        name="Insulation Coordination Calculator.app",
        icon=str(icon_path),
        info_plist=plistlib.loads(
            (root / "packaging" / "macos" / "Info.plist").read_bytes()
        ),
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="icc",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        icon=str(icon_path),
        console=sys.platform.startswith("linux"),
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="icc",
    )
