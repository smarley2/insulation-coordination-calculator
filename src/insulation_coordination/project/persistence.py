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
    InsulationType,
    NetClassType,
    ReviewState,
)
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.verification import ProtectionImplementation

PROJECT_SCHEMA_VERSION = 8

# The solid-insulation key the version 7 -> 8 migration drops. It recorded whether a declared
# construction's layers could be tested one at a time, and no clause of the standard this
# application implements asks that: the applicability clause of the partial-discharge test asks
# only how many layers there are. Unlike every other step in the chain this one removes a field
# rather than introducing one, so it carries no guard - a version-7 document is *expected* to
# hold this key, and the whole point of the step is to drop it.
SEPARABLE_LAYERS_KEY = "separately_testable_layers"

# The project-level key the version 6 -> 7 migration introduces. Guarded like every other
# introduced key: a version-6 document already carrying it was migrated once or hand-edited,
# and a second pass must not touch a method someone actually chose.
IMPULSE_VERIFICATION_KEY = "impulse_verification_method"

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

# Pair-level keys the version 5 -> 6 migration introduces. Same guard as above: a version-5
# document carrying any of them was already migrated or hand-edited, and overwriting a real
# protective-means selection with a mapped guess is exactly what must not happen silently.
PAIR_VERIFICATION_KEYS = frozenset(
    {
        "protection_implementation",
        "protection_review_state",
        "solid_insulation",
        "routine_exemption",
    }
)

# How an existing pair-level insulation selection reads as a protective means.
#
# Only the three the selection names unambiguously. ``SUPPLEMENTARY`` is deliberately absent:
# supplementary insulation is one half of a double-insulation construction as often as it is a
# protective means in its own right, and nothing on the pair says which, so the migration
# records no selection rather than one that merely shares a name. Everything a pair did not
# select for itself is left unset the same way - a project default is not a selection, and
# copying it into every pair would both invent a decision and de-link the pair from the
# default it was following.
MIGRATED_PROTECTION: dict[InsulationType, ProtectionImplementation] = {
    InsulationType.FUNCTIONAL: ProtectionImplementation.FUNCTIONAL_INSULATION,
    InsulationType.BASIC: ProtectionImplementation.BASIC_INSULATION,
    InsulationType.REINFORCED: ProtectionImplementation.REINFORCED_INSULATION,
}

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
    if version == 5:
        if "voltage_evidence" in document:
            raise ProjectVersionError(
                f"Project schema {declared} must not contain voltage_evidence"
            )
        # Same defensive shape as the version 3 step: a corrupt ``pairs`` is left for
        # ``Project.model_validate`` to reject with a proper load error.
        pairs_field = document.get("pairs", [])
        pairs: list[object] = pairs_field if isinstance(pairs_field, list) else []
        dict_pairs = [pair for pair in pairs if isinstance(pair, dict)]
        present = sorted(
            {key for pair in dict_pairs for key in PAIR_VERIFICATION_KEYS & pair.keys()}
        )
        if present:
            raise ProjectVersionError(
                f"Project schema {declared} pairs must not contain {', '.join(present)}"
            )
        # An existing project has recorded no voltage evidence, so the library starts empty.
        # Solid-insulation and routine-exemption records are left absent rather than written
        # as nulls, exactly as the pair-level impulse override is: the fields default to none,
        # and writing into every pair could only ever overwrite something.
        document["voltage_evidence"] = []
        for pair in dict_pairs:
            pair["protection_implementation"] = _migrated_protection(pair)
            pair["protection_review_state"] = ReviewState.NEEDS_REVIEW.value
        version = 6
    if version == 6:
        if IMPULSE_VERIFICATION_KEY in document:
            raise ProjectVersionError(
                f"Project schema {declared} must not contain {IMPULSE_VERIFICATION_KEY}"
            )
        # Nothing is written. An existing project chose no impulse verification method, and the
        # field defaults to none, so the key is left absent exactly as the pair-level impulse
        # override and the solid-insulation record are: writing a null would record a decision
        # as having been made and not made at the same time, and there is no conservative value
        # to migrate to - the impulse test is the source's own default, but a project that
        # never saw the choice has not selected it.
        version = 7
    if version == 7:
        # Same defensive shape as the version 3 and 5 steps: a ``pairs`` that is not a list,
        # or a ``solid_insulation`` that is not an object, is left exactly as it is for
        # ``Project.model_validate`` to reject with a proper load error.
        declared_field = document.get("pairs", [])
        declaring_pairs: list[object] = declared_field if isinstance(declared_field, list) else []
        for entry in declaring_pairs:
            if not isinstance(entry, dict):
                continue
            solid = entry.get("solid_insulation")
            if isinstance(solid, dict):
                # Dropped, not folded into ``notes``: the answer was recorded against a
                # question nothing asks, and moving it into free text would put it back in
                # front of a reviewer as though something still depended on it.
                solid.pop(SEPARABLE_LAYERS_KEY, None)
        version = 8
    if version != PROJECT_SCHEMA_VERSION:
        raise ProjectVersionError(f"Project schema {declared} is unsupported")
    document["schema_version"] = PROJECT_SCHEMA_VERSION
    return document


def _migrated_protection(pair: dict[str, object]) -> str | None:
    """The protective means ``pair``'s own insulation selection reads as, if any.

    Conservative on every axis: a pair that inherited the project default made no selection,
    an unrecognised or ambiguous value maps to nothing, and a mapped value still arrives
    needing review. The answer is always either the pair's own unambiguous selection or
    nothing at all.
    """

    selection = pair.get("insulation_type")
    if not isinstance(selection, dict) or not selection.get("is_override"):
        return None
    value = selection.get("value")
    if not isinstance(value, str):
        return None
    try:
        insulation = InsulationType(value)
    except ValueError:
        return None
    mapped = MIGRATED_PROTECTION.get(insulation)
    return None if mapped is None else mapped.value


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
