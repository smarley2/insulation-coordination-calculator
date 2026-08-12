from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError

from insulation_coordination.domain.project import Project

PROJECT_SCHEMA_VERSION = 3


class ProjectSaveError(OSError):
    """A project file could not be safely replaced."""


class ProjectVersionError(ValueError):
    """A project document uses an unsupported schema version."""


class ProjectLoadError(ValueError):
    """A project file could not be read or validated."""


def migrate_project_document(raw: dict[str, object]) -> dict[str, object]:
    version = raw.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ProjectVersionError("Project schema_version must be an integer")
    if version > PROJECT_SCHEMA_VERSION:
        raise ProjectVersionError(
            f"Project schema {version} is newer than supported version {PROJECT_SCHEMA_VERSION}"
        )
    document = deepcopy(raw)
    declared = version
    if version == 1:
        if "group_splits" in document:
            raise ProjectVersionError("Project schema 1 must not contain group_splits")
        document["group_splits"] = []
        version = 2
    if version == 2:
        if "circuit_diagram" in document:
            raise ProjectVersionError(f"Project schema {declared} must not contain circuit_diagram")
        document["circuit_diagram"] = None
        version = 3
    if version != PROJECT_SCHEMA_VERSION:
        raise ProjectVersionError(f"Project schema {declared} is unsupported")
    document["schema_version"] = PROJECT_SCHEMA_VERSION
    return document


def load_project(path: Path) -> Project:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("Project document root must be an object")
        document = migrate_project_document(raw)
        document.pop("schema_version")
        return Project.model_validate(document)
    except ProjectVersionError:
        raise
    except (OSError, TypeError, ValidationError, json.JSONDecodeError) as error:
        raise ProjectLoadError(f"Could not load project {path}: {error}") from error


def save_project_atomic(path: Path, project: Project) -> None:
    document = {"schema_version": PROJECT_SCHEMA_VERSION, **project.model_dump(mode="json")}
    content = json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except Exception as error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ProjectSaveError(str(error)) from error
