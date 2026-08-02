from __future__ import annotations

import plistlib
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.render_icons import render_icons

ROOT = Path(__file__).parents[2]


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


def test_linux_metadata_routes_both_document_types() -> None:
    desktop = (ROOT / "packaging/linux/icc.desktop").read_text(encoding="utf-8")
    mime = ET.parse(ROOT / "packaging/linux/application-x-icc.xml")
    assert "application/x-icc-project" in desktop
    assert "application/x-icc-rules" in desktop
    patterns = {node.attrib["pattern"] for node in mime.findall(".//{*}glob")}
    assert patterns == {"*.icproj", "*.icrules"}


def test_windows_installer_preserves_user_rules_and_routes_documents() -> None:
    script = (ROOT / "installer/insulation-coordination.iss").read_text(encoding="utf-8")
    assert "[UninstallDelete]" not in script
    assert '""%1""' in script
    assert ".icproj" in script and ".icrules" in script
    assert "desktopicon" in script
    assert "AppVersion" in script


def test_macos_package_verifies_ad_hoc_signature_and_dmg() -> None:
    script = (ROOT / "packaging/macos/package.sh").read_text(encoding="utf-8")
    for required in (
        "codesign --force --sign -",
        "codesign --verify --deep --strict",
        "hdiutil create",
        "--release-diagnostic",
    ):
        assert required in script
