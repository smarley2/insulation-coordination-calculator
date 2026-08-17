from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from insulation_coordination.domain.enums import (
    CircuitSourceRelationship,
    ConnectionExposure,
    DecisiveVoltageClass,
    NetClassType,
    ReviewState,
)
from insulation_coordination.domain.project import Project

PROJECT_SCHEMA_VERSION = 5

# Net-level keys the version 3 -> 4 migration adds. A version-3 document must not carry any of
# these yet - their presence means the document was already migrated (or hand-edited), and the
# migration must refuse it rather than silently overwrite a real classification.
NET_TOPOLOGY_KEYS = frozenset(
    {
        "net_type",
        "source_relationship",
        "connection_exposure",
        "decisive_voltage_class",
        "galvanic_domain_id",
        "classification_review_state",
    }
)

_DIRECT_DOMAIN_NAME = "Direct / source-side domain"


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
    if version == 3:
        if "galvanic_domains" in document:
            raise ProjectVersionError(
                f"Project schema {declared} must not contain galvanic_domains"
            )
        if "galvanic_barriers" in document:
            raise ProjectVersionError(
                f"Project schema {declared} must not contain galvanic_barriers"
            )
        nets_field = document.get("net_classes", [])
        # A hand-edited or corrupt document may carry a ``net_classes`` that is not a
        # list at all, or a list with an entry that is not an object. Neither shape can
        # ever be a valid schema-3 document, so the migration leaves it untouched rather
        # than calling ``.keys()`` on it - that lets ``Project.model_validate`` reject it
        # below with a proper ``ProjectLoadError`` instead of an ``AttributeError``.
        nets: list[object] = nets_field if isinstance(nets_field, list) else []
        dict_nets = [net for net in nets if isinstance(net, dict)]
        if any(NET_TOPOLOGY_KEYS & net.keys() for net in dict_nets):
            raise ProjectVersionError(
                f"Project schema {declared} net classes must not contain topology keys"
            )
        domain_id = str(uuid4())
        document["galvanic_domains"] = [
            {
                "id": domain_id,
                "name": _DIRECT_DOMAIN_NAME,
                "description": "",
                "is_direct_source_domain": True,
                "review_state": ReviewState.NEEDS_REVIEW.value,
            }
        ]
        document["galvanic_barriers"] = []
        for net in dict_nets:
            net["net_type"] = NetClassType.CIRCUIT.value
            net["source_relationship"] = CircuitSourceRelationship.INTERNALLY_GENERATED.value
            net["connection_exposure"] = ConnectionExposure.INTERNAL_ONLY.value
            net["decisive_voltage_class"] = DecisiveVoltageClass.NOT_EVALUATED.value
            net["galvanic_domain_id"] = domain_id
            net["classification_review_state"] = ReviewState.NEEDS_REVIEW.value
        version = 4
    if version == 4:
        if "supply_configurations" in document:
            raise ProjectVersionError(
                f"Project schema {declared} must not contain supply_configurations"
            )
        # An existing project declares no supply arrangement, so it derives nothing and keeps
        # every stress it was saved with. Pair-level impulse overrides are left absent rather
        # than written as nulls: the field defaults to none, and a migration that writes into
        # every pair could only ever overwrite something.
        document["supply_configurations"] = []
        version = 5
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
