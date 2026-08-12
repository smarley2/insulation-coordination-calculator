"""Trust and execution model for bundled or source-run Tectonic."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from pydantic import Field, field_validator

from insulation_coordination.domain.project import FrozenModel

_SHA256 = re.compile(r"[0-9a-f]{64}")


class TectonicIntegrityError(ValueError):
    """A bundled Tectonic executable or cache failed its trust checks."""


type CompilerCommand = str | os.PathLike[str] | Sequence[str | os.PathLike[str]]


class TectonicPlatform(FrozenModel):
    archive_url: str
    archive_sha256: str
    archive_member: str
    executable_path: str
    cache_path: str
    lock_path: str
    offline_flag: str

    @field_validator("archive_sha256")
    @classmethod
    def _valid_archive_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("archive SHA-256 must be 64 lowercase hexadecimal characters")
        return value


class TectonicManifest(FrozenModel):
    schema_version: int = Field(strict=True)
    tectonic_version: str
    licence: str
    default_bundle_url: str
    default_bundle_sha256: str
    platforms: dict[str, TectonicPlatform]

    @field_validator("default_bundle_sha256")
    @classmethod
    def _valid_bundle_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("bundle SHA-256 must be 64 lowercase hexadecimal characters")
        return value


class TectonicLock(FrozenModel):
    platform_key: str
    tectonic_version: str
    executable_sha256: str
    cache_sha256: str

    @field_validator("executable_sha256", "cache_sha256")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("SHA-256 must be 64 lowercase hexadecimal characters")
        return value


class TectonicRuntime(FrozenModel):
    command: tuple[str, ...]
    offline_flag: str
    cache_dir: Path | None
    status: str


def canonical_tree_sha256(root: Path) -> str:
    """Hash a directory deterministically from POSIX names and file bytes."""
    root = Path(root)
    if root.is_symlink():
        raise TectonicIntegrityError("cache root must not be a symlink")
    if not root.is_dir():
        raise TectonicIntegrityError("cache root must be a directory")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise TectonicIntegrityError(f"cache contains symlink: {path}")
        if not path.is_file():
            if not path.is_dir():
                raise TectonicIntegrityError(f"cache contains unsupported entry: {path}")
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_tectonic_manifest(path: Path) -> TectonicManifest:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        manifest = TectonicManifest.model_validate(document)
    except TectonicIntegrityError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise TectonicIntegrityError(f"could not load Tectonic manifest: {error}") from error
    if manifest.schema_version != 1:
        raise TectonicIntegrityError(
            f"unsupported Tectonic manifest schema {manifest.schema_version}"
        )
    return manifest


def verify_bundled_tectonic(
    base_dir: Path,
    platform_key: str,
    manifest_path: Path | None = None,
) -> TectonicRuntime:
    base = Path(base_dir).resolve(strict=True)
    manifest = load_tectonic_manifest(manifest_path or base / "tectonic-manifest.json")
    platform_record = manifest.platforms.get(platform_key)
    if platform_record is None:
        raise TectonicIntegrityError(f"unsupported platform in Tectonic manifest: {platform_key}")
    if manifest.tectonic_version != "0.16.9":
        raise TectonicIntegrityError(f"unsupported Tectonic version: {manifest.tectonic_version}")

    executable_path = _safe_bundle_path(base, platform_record.executable_path, "executable")
    cache_path = _safe_bundle_path(base, platform_record.cache_path, "cache")
    lock_path = _safe_bundle_path(base, platform_record.lock_path, "lock")
    if executable_path.is_symlink():
        raise TectonicIntegrityError("Tectonic executable must not be a symlink")
    if not executable_path.is_file():
        raise TectonicIntegrityError(f"Tectonic executable is missing: {executable_path}")
    if not os.access(executable_path, os.X_OK) and os.name != "nt":
        raise TectonicIntegrityError("Tectonic executable is not executable")
    if not cache_path.is_dir():
        raise TectonicIntegrityError(f"Tectonic cache is missing: {cache_path}")
    try:
        lock = TectonicLock.model_validate(json.loads(lock_path.read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError) as error:
        raise TectonicIntegrityError(f"could not load Tectonic lock: {error}") from error
    if lock.platform_key != platform_key or lock.tectonic_version != manifest.tectonic_version:
        raise TectonicIntegrityError("Tectonic lock identity does not match the manifest")
    if _sha256_file(executable_path) != lock.executable_sha256:
        raise TectonicIntegrityError("Tectonic executable SHA-256 does not match its lock")
    if canonical_tree_sha256(cache_path) != lock.cache_sha256:
        raise TectonicIntegrityError("Tectonic cache SHA-256 does not match its lock")
    _verify_version(executable_path, manifest.tectonic_version)
    return TectonicRuntime(
        command=(str(executable_path),),
        offline_flag=platform_record.offline_flag,
        cache_dir=cache_path,
        status="verified-bundled",
    )


def resolve_tectonic_runtime(command: CompilerCommand | None = None) -> TectonicRuntime:
    """Resolve explicit source commands or the verified executable in a frozen app."""
    if command is not None:
        normalized = _normalize_command(command)
        return TectonicRuntime(
            command=tuple(normalized),
            offline_flag=_probe_offline_flag(normalized),
            cache_dir=None,
            status="source-explicit",
        )
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return verify_bundled_tectonic(base, _platform_key())
    found = shutil.which("tectonic")
    if found is None:
        raise TectonicIntegrityError("No Tectonic executable found on PATH")
    return TectonicRuntime(
        command=(found,),
        offline_flag=_probe_offline_flag([found]),
        cache_dir=None,
        status="source-path",
    )


def _safe_bundle_path(base: Path, value: str, label: str) -> Path:
    if not value or "\\" in value:
        raise TectonicIntegrityError(f"unsafe path in Tectonic {label}: {value!r}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise TectonicIntegrityError(f"unsafe path in Tectonic {label}: {value!r}")
    candidate = (base / Path(*relative.parts)).resolve(strict=False)
    try:
        candidate.relative_to(base)
    except ValueError as error:
        raise TectonicIntegrityError(f"unsafe path in Tectonic {label}: {value!r}") from error
    return candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_version(executable: Path, version: str) -> None:
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            shell=False,
            timeout=10,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TectonicIntegrityError(f"could not verify Tectonic version: {error}") from error
    if completed.returncode != 0 or f"Tectonic {version}" not in completed.stdout:
        raise TectonicIntegrityError("Tectonic executable version does not match the manifest")


def _normalize_command(command: CompilerCommand) -> list[str]:
    if isinstance(command, (str, os.PathLike)):
        return [os.fspath(command)]
    return [os.fspath(part) for part in command]


def _probe_offline_flag(command: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            [*command, "--help"],
            shell=False,
            timeout=10,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "--only-cached"
    help_text = completed.stdout + completed.stderr
    return "--only-cached" if "--only-cached" in help_text else "--offline"


def _platform_key() -> str:
    machine = platform.machine().lower()
    if sys.platform.startswith("win") and machine in {"amd64", "x86_64"}:
        return "windows-x86_64"
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if sys.platform.startswith("linux") and machine in {"amd64", "x86_64"}:
        return "linux-x86_64"
    raise TectonicIntegrityError(f"unsupported packaged platform: {sys.platform}/{machine}")
