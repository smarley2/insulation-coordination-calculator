from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.release_artifacts import (
    ReleaseArtifactError,
    build_release_index,
    scan_forbidden,
    write_sha256sums,
)


def _write_metadata(path: Path, *, platform: str, artifact: str = "package.bin") -> None:
    payload = (path.parent / artifact).resolve()
    payload.write_bytes(b"public artifact")
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "platform": platform,
                "signing_status": "unsigned",
                "artifacts": [
                    {
                        "filename": artifact,
                        "size": payload.stat().st_size,
                        "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_release_index_rejects_duplicate_platform_metadata(tmp_path: Path) -> None:
    _write_metadata(tmp_path / "a.metadata.json", platform="linux-x86_64")
    _write_metadata(tmp_path / "b.metadata.json", platform="linux-x86_64")
    with pytest.raises(ReleaseArtifactError, match="duplicate platform"):
        build_release_index(tmp_path)


@pytest.mark.parametrize(
    "name",
    (
        "standard.pdf",
        "private.icrules",
        "customer.icproj",
        "audit-inventory.json",
        "__pycache__/module.pyc",
    ),
)
def test_forbidden_release_member_is_reported(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"private")
    assert scan_forbidden(tmp_path)


def test_release_index_requires_all_v1_platforms_and_checks_artifacts(tmp_path: Path) -> None:
    for platform in ("windows-x86_64", "macos-arm64", "linux-x86_64"):
        _write_metadata(
            tmp_path / f"{platform}.metadata.json",
            platform=platform,
            artifact=f"{platform}.bin",
        )
    index = build_release_index(tmp_path)
    assert set(index["platforms"]) == {"windows-x86_64", "macos-arm64", "linux-x86_64"}

    (tmp_path / "linux-x86_64.bin").write_bytes(b"tampered")
    with pytest.raises(ReleaseArtifactError, match="size|hash"):
        build_release_index(tmp_path)


def test_sha256sums_is_sorted_and_uses_relative_names(tmp_path: Path) -> None:
    first = tmp_path / "z.bin"
    second = tmp_path / "a.bin"
    first.write_bytes(b"z")
    second.write_bytes(b"a")
    checksum = write_sha256sums(tmp_path, (first, second))
    lines = checksum.read_text(encoding="utf-8").splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["a.bin", "z.bin"]
