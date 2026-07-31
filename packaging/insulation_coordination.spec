# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH).resolve().parent.parent

datas = [
    (str(root / "src" / "insulation_coordination" / "report" / "templates"),
     "insulation_coordination/report/templates"),
]

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
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="icc",
)
