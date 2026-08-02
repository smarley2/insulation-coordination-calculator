"""Download, warm, and integrity-lock one native Tectonic bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from insulation_coordination.release_diagnostic import render_release_tex
from insulation_coordination.report.tectonic import (
    canonical_tree_sha256,
    load_tectonic_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


class TectonicPreparationError(ValueError):
    """Native Tectonic staging failed a safety, download, or offline check."""


def prepare_tectonic(
    platform_key: str,
    destination: Path,
    *,
    refresh_lock: bool = False,
    manifest_path: Path | None = None,
    fixtures: Path | None = None,
) -> Path:
    manifest_file = Path(manifest_path or ROOT / "packaging" / "tectonic-manifest.json")
    manifest = load_tectonic_manifest(manifest_file)
    record = manifest.platforms.get(platform_key)
    if record is None:
        raise TectonicPreparationError(f"unsupported platform: {platform_key}")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    _copy_manifest(manifest_file, destination)

    with tempfile.TemporaryDirectory(prefix="icc-tectonic-download-") as temporary:
        archive = Path(temporary) / "tectonic.archive"
        _download(record.archive_url, archive)
        if _sha256_file(archive) != record.archive_sha256:
            raise TectonicPreparationError("archive SHA-256 does not match manifest")
        executable = _bundle_path(destination, record.executable_path, "executable")
        extract_declared_member(archive, record.archive_member, executable)
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    _verify_version(executable, manifest.tectonic_version)
    cache = _bundle_path(destination, record.cache_path, "cache")
    cache.mkdir(parents=True, exist_ok=True)

    if fixtures is None:
        raise TectonicPreparationError("release fixtures are required to warm the cache")
    with tempfile.TemporaryDirectory(prefix="icc-tectonic-fixture-") as temporary:
        source = render_release_tex(
            Path(fixtures) / "project.icproj",
            Path(fixtures) / "rules.icrules",
            Path(temporary),
        )
        _compile_once(executable, source.tex_path, cache, record.offline_flag, offline=False)
        _compile_once(executable, source.tex_path, cache, record.offline_flag, offline=True)

    lock_source = manifest_file.parent / record.lock_path
    lock_destination = _bundle_path(destination, record.lock_path, "lock")
    lock_destination.parent.mkdir(parents=True, exist_ok=True)
    if refresh_lock:
        if sys.platform == "darwin":
            _adhoc_sign(executable)
        lock_destination.write_text(
            json.dumps(
                {
                    "platform_key": platform_key,
                    "tectonic_version": manifest.tectonic_version,
                    "executable_sha256": _sha256_file(executable),
                    "cache_sha256": canonical_tree_sha256(cache),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    elif lock_destination.is_file():
        pass
    elif lock_source.is_file():
        shutil.copy2(lock_source, lock_destination)
    else:
        raise TectonicPreparationError(f"native lock is missing: {lock_source}")
    return destination


def extract_declared_member(archive: Path, member: str, output: Path) -> Path:
    _safe_archive_member(member)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as package:
                info = package.getinfo(member)
                if info.is_dir():
                    raise TectonicPreparationError("archive member is not a file")
                output.write_bytes(package.read(info))
        else:
            with tarfile.open(archive, "r:*") as package:
                info = package.getmember(member)
                if not info.isfile():
                    raise TectonicPreparationError("archive member is not a file")
                stream = package.extractfile(info)
                if stream is None:
                    raise TectonicPreparationError("archive member cannot be read")
                output.write_bytes(stream.read())
    except KeyError as error:
        raise TectonicPreparationError(f"archive member is missing: {member}") from error
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise TectonicPreparationError(f"could not extract archive member: {error}") from error
    return output


def _download(url: str, destination: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as stream:
            shutil.copyfileobj(response, stream)
    except OSError as error:
        raise TectonicPreparationError(f"could not download Tectonic archive: {error}") from error


def _copy_manifest(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination / "tectonic-manifest.json")


def _bundle_path(base: Path, value: str, label: str) -> Path:
    if not value or "\\" in value:
        raise TectonicPreparationError(f"unsafe {label} path in manifest: {value!r}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise TectonicPreparationError(f"unsafe {label} path in manifest: {value!r}")
    return base.joinpath(*relative.parts)


def _safe_archive_member(member: str) -> None:
    relative = PurePosixPath(member)
    if not member or "\\" in member or relative.is_absolute() or ".." in relative.parts:
        raise TectonicPreparationError(f"unsafe archive member: {member!r}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_version(executable: Path, version: str) -> None:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TectonicPreparationError(f"could not verify Tectonic version: {error}") from error
    if result.returncode != 0 or f"Tectonic {version}" not in result.stdout:
        raise TectonicPreparationError("Tectonic version does not match manifest")


def _compile_once(
    executable: Path,
    tex: Path,
    cache: Path,
    offline_flag: str,
    *,
    offline: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix="icc-tectonic-out-") as output:
        environment = os.environ.copy()
        environment["TECTONIC_CACHE_DIR"] = str(cache)
        if offline:
            with tempfile.TemporaryDirectory(prefix="icc-empty-home-") as empty_home:
                environment["HOME"] = empty_home
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
                    environment[key] = "http://127.0.0.1:9"
                result = _run_compile(executable, tex, Path(output), offline_flag, environment)
        else:
            result = _run_compile(executable, tex, Path(output), None, environment)
        pdf = Path(output) / f"{tex.stem}.pdf"
        if result.returncode != 0 or not pdf.is_file() or not pdf.read_bytes().startswith(b"%PDF-"):
            raise TectonicPreparationError(
                f"Tectonic {'offline ' if offline else ''}cache warm failed: {result.stderr[-500:]}"
            )


def _run_compile(
    executable: Path,
    tex: Path,
    output: Path,
    offline_flag: str | None,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    command = [str(executable)]
    if offline_flag is not None:
        command.append(offline_flag)
    command.extend(("--outdir", str(output), str(tex)))
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TectonicPreparationError(f"Tectonic compile failed: {error}") from error


def _adhoc_sign(executable: Path) -> None:
    try:
        result = subprocess.run(
            ["codesign", "--force", "--sign", "-", str(executable)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise TectonicPreparationError(f"could not ad-hoc sign Tectonic: {error}") from error
    if result.returncode != 0:
        raise TectonicPreparationError(f"could not ad-hoc sign Tectonic: {result.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--refresh-lock", action="store_true")
    args = parser.parse_args()
    prepare_tectonic(
        args.platform,
        args.destination,
        refresh_lock=args.refresh_lock,
        manifest_path=args.manifest,
        fixtures=args.fixtures,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
