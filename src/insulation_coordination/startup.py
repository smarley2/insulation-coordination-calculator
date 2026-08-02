from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


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
    if not resolved.is_file():
        raise ValueError(f"startup document is not a file: {resolved}")
    kind = {".icproj": StartupKind.PROJECT, ".icrules": StartupKind.RULES}.get(
        resolved.suffix.lower()
    )
    if kind is None:
        raise ValueError("startup document must have extension .icproj or .icrules")
    return StartupRequest(kind, resolved)
