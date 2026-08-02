"""Validate public release artifacts and write reproducible checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ("windows-x86_64", "macos-arm64", "linux-x86_64")
SIGNING_STATUSES = {"unsigned", "ad-hoc", "trusted", "notarized"}
FORBIDDEN_NAMES = {"audit-inventory.json"}
FORBIDDEN_SUFFIXES = {".pdf", ".icrules", ".icproj", ".pyc"}


class ReleaseArtifactError(ValueError):
    """Release metadata or public-content validation failed."""


def scan_forbidden(root: Path) -> tuple[str, ...]:
    root = Path(root)
    findings: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.add(relative)
        if "__pycache__" in PurePosixPath(relative).parts:
            findings.add(relative)
        if path.is_file() and (zipfile.is_zipfile(path) or tarfile.is_tarfile(path)):
            findings.update(f"{relative}!{member}" for member in _archive_members(path))
    return tuple(sorted(findings))


def build_release_index(artifact_dir: Path) -> dict[str, object]:
    artifact_dir = Path(artifact_dir).resolve()
    findings = scan_forbidden(artifact_dir)
    if findings:
        raise ReleaseArtifactError(f"forbidden release content: {', '.join(findings)}")
    metadata_files = sorted(artifact_dir.glob("*.metadata.json"))
    platforms: dict[str, dict[str, object]] = {}
    all_artifacts: list[str] = []
    for metadata_path in metadata_files:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as error:
            raise ReleaseArtifactError(f"invalid metadata: {metadata_path.name}") from error
        if metadata.get("schema_version") != 1:
            raise ReleaseArtifactError(f"unsupported metadata schema: {metadata_path.name}")
        platform = metadata.get("platform")
        status = metadata.get("signing_status")
        if platform not in PLATFORMS:
            raise ReleaseArtifactError(f"unsupported platform: {platform}")
        if platform in platforms:
            raise ReleaseArtifactError(f"duplicate platform metadata: {platform}")
        if status not in SIGNING_STATUSES:
            raise ReleaseArtifactError(f"unsupported signing status: {status}")
        declared = metadata.get("artifacts")
        if not isinstance(declared, list) or not declared:
            raise ReleaseArtifactError(f"metadata has no artifacts: {metadata_path.name}")
        checked: list[dict[str, object]] = []
        for item in declared:
            if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
                raise ReleaseArtifactError(f"invalid artifact entry: {metadata_path.name}")
            filename = item["filename"]
            candidate = _safe_leaf(artifact_dir, filename)
            if not candidate.is_file():
                raise ReleaseArtifactError(f"declared artifact is missing: {filename}")
            size = item.get("size")
            digest = item.get("sha256")
            actual_digest = _sha256(candidate)
            if size != candidate.stat().st_size:
                raise ReleaseArtifactError(f"size mismatch for {filename}")
            if digest != actual_digest:
                raise ReleaseArtifactError(f"hash mismatch for {filename}")
            if filename in all_artifacts:
                raise ReleaseArtifactError(f"duplicate artifact filename: {filename}")
            all_artifacts.append(filename)
            checked.append({"filename": filename, "size": size, "sha256": digest})
        platforms[platform] = {
            "metadata": metadata_path.name,
            "signing_status": status,
            "artifacts": checked,
        }
    missing = sorted(set(PLATFORMS) - set(platforms))
    if missing:
        raise ReleaseArtifactError(f"missing platform metadata: {', '.join(missing)}")
    return {
        "schema_version": 1,
        "platforms": {key: platforms[key] for key in PLATFORMS},
        "artifacts": sorted(all_artifacts),
    }


def write_sha256sums(artifact_dir: Path, artifacts: Sequence[Path]) -> Path:
    artifact_dir = Path(artifact_dir)
    rows = []
    for artifact in sorted((Path(item) for item in artifacts), key=lambda item: item.name):
        relative = artifact.resolve().relative_to(artifact_dir.resolve()).as_posix()
        rows.append(f"{_sha256(artifact)}  {relative}")
    destination = artifact_dir / "SHA256SUMS"
    _atomic_write(destination, "\n".join(rows) + "\n")
    return destination


def write_platform_metadata(
    artifact_dir: Path,
    platform: str,
    signing_status: str,
    artifacts: Sequence[Path],
) -> Path:
    if platform not in PLATFORMS:
        raise ReleaseArtifactError(f"unsupported platform: {platform}")
    if signing_status not in SIGNING_STATUSES:
        raise ReleaseArtifactError(f"unsupported signing status: {signing_status}")
    entries = []
    for artifact in sorted((Path(item) for item in artifacts), key=lambda item: item.name):
        entries.append(
            {
                "filename": artifact.name,
                "size": artifact.stat().st_size,
                "sha256": _sha256(artifact),
            }
        )
    destination = Path(artifact_dir) / f"{platform}.metadata.json"
    _atomic_write(
        destination,
        json.dumps(
            {
                "schema_version": 1,
                "platform": platform,
                "signing_status": signing_status,
                "artifacts": entries,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return destination


def _safe_leaf(root: Path, filename: str) -> Path:
    relative = PurePosixPath(filename)
    if not filename or relative.is_absolute() or len(relative.parts) != 1 or relative.parts[0] in {".", ".."}:
        raise ReleaseArtifactError(f"artifact filename must be a leaf: {filename!r}")
    candidate = (root / relative.parts[0]).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ReleaseArtifactError(f"artifact escapes release directory: {filename!r}") from error
    return candidate


def _archive_members(path: Path) -> tuple[str, ...]:
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                return tuple(info.filename for info in archive.infolist())
        with tarfile.open(path, "r:*") as archive:
            return tuple(member.name for member in archive.getmembers())
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        return ()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(destination: Path, content: str) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    args = parser.parse_args()
    artifact_dir = args.artifact_dir
    index = build_release_index(artifact_dir)
    index_path = artifact_dir / "release-index.json"
    _atomic_write(index_path, json.dumps(index, indent=2, sort_keys=True) + "\n")
    artifacts = [artifact_dir / name for name in index["artifacts"]]
    write_sha256sums(artifact_dir, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
