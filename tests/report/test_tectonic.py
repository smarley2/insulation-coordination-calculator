from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from insulation_coordination.report.tectonic import (
    TectonicIntegrityError,
    canonical_tree_sha256,
    verify_bundled_tectonic,
)


def _tree_hash(root: Path) -> str:
    return canonical_tree_sha256(root)


def _write_fake_bundle(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "bundle"
    executable = base / "tectonic" / "tectonic"
    cache = base / "tectonic" / "cache"
    executable.parent.mkdir(parents=True)
    cache.mkdir()
    executable.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then\n"
        "  echo 'Tectonic 0.16.9'\n"
        "fi\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    (cache / "seed.txt").write_text("seed", encoding="utf-8")

    lock_path = base / "lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "platform_key": "linux-x86_64",
                "tectonic_version": "0.16.9",
                "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "cache_sha256": _tree_hash(cache),
            }
        ),
        encoding="utf-8",
    )
    manifest_path = base / "tectonic-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tectonic_version": "0.16.9",
                "licence": "MIT",
                "default_bundle_url": "https://example.test/bundle.tar",
                "default_bundle_sha256": "0" * 64,
                "platforms": {
                    "linux-x86_64": {
                        "archive_url": "https://example.test/tectonic.tar.gz",
                        "archive_sha256": "0" * 64,
                        "archive_member": "tectonic",
                        "executable_path": "tectonic/tectonic",
                        "cache_path": "tectonic/cache",
                        "lock_path": "lock.json",
                        "offline_flag": "--only-cached",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return base, manifest_path


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


def test_verify_bundled_tectonic_rejects_changed_cache(tmp_path: Path) -> None:
    base, manifest_path = _write_fake_bundle(tmp_path)
    verify_bundled_tectonic(base, "linux-x86_64", manifest_path)
    (base / "tectonic" / "cache" / "seed.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(TectonicIntegrityError, match="cache SHA-256"):
        verify_bundled_tectonic(base, "linux-x86_64", manifest_path)


def test_canonical_tree_hash_rejects_symlink(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    target = tmp_path / "target"
    target.write_text("target", encoding="utf-8")
    (root / "link").symlink_to(target)

    with pytest.raises(TectonicIntegrityError, match="symlink"):
        canonical_tree_sha256(root)


def test_verify_bundled_tectonic_rejects_unsupported_platform(tmp_path: Path) -> None:
    base, manifest_path = _write_fake_bundle(tmp_path)

    with pytest.raises(TectonicIntegrityError, match="unsupported platform"):
        verify_bundled_tectonic(base, "windows-x86_64", manifest_path)


def test_verify_bundled_tectonic_rejects_malformed_lock_digest(tmp_path: Path) -> None:
    base, manifest_path = _write_fake_bundle(tmp_path)
    lock = base / "lock.json"
    document = json.loads(lock.read_text(encoding="utf-8"))
    document["cache_sha256"] = "not-a-digest"
    lock.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        verify_bundled_tectonic(base, "linux-x86_64", manifest_path)


def test_verify_bundled_tectonic_rejects_parent_manifest_path(tmp_path: Path) -> None:
    base, manifest_path = _write_fake_bundle(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["platforms"]["linux-x86_64"]["cache_path"] = "../cache"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe path"):
        verify_bundled_tectonic(base, "linux-x86_64", manifest_path)
