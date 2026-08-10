from __future__ import annotations

import json
import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Self
from unittest.mock import Mock
from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.enums import ReviewState
from insulation_coordination.domain.project import (
    GroupSplit,
    NetClass,
    OverrideValue,
    PairCase,
    PairVoltage,
    PairVoltages,
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.project.persistence import (
    NET_TOPOLOGY_KEYS,
    ProjectLoadError,
    ProjectSaveError,
    ProjectVersionError,
    load_project,
    migrate_project_document,
    save_project_atomic,
)


@pytest.fixture
def sample_project() -> Project:
    high = UUID(int=1)
    low = UUID(int=2)
    return Project(
        id=UUID(int=3),
        metadata=ProjectMetadata(title="Drive insulation"),
        application_version="0.1.0",
        required_rules=RulePackageReference(
            package_id="iec-60664",
            version="2020.1",
            sha256="a" * 64,
        ),
        defaults=ProjectDefaults(frequency_hz=Decimal("50000.00")),
        net_classes=(NetClass(id=high, name="HV"), NetClass(id=low, name="LV")),
        pairs=(
            PairCase(
                key=f"{high}::{low}",
                net_a=high,
                net_b=low,
                voltages=PairVoltages(long_term_rms_v=PairVoltage.applicable(Decimal("560.00"))),
            ),
        ),
    )


@pytest.fixture
def topology_migration_project() -> Project:
    """Three nets and three pairs exercising stresses, an override, an exclusion, and a note."""
    net_a = UUID(int=10)
    net_b = UUID(int=11)
    net_c = UUID(int=12)
    return Project(
        id=UUID(int=13),
        metadata=ProjectMetadata(title="Legacy fixture"),
        application_version="0.1.0",
        defaults=ProjectDefaults(frequency_hz=Decimal("50000.00")),
        net_classes=(
            NetClass(id=net_a, name="Net A"),
            NetClass(id=net_b, name="Net B"),
            NetClass(id=net_c, name="Net C"),
        ),
        pairs=(
            PairCase(
                key=f"{net_a}::{net_b}",
                net_a=net_a,
                net_b=net_b,
                voltages=PairVoltages(long_term_rms_v=PairVoltage.applicable(Decimal("400.00"))),
                frequency_hz=OverrideValue.override(Decimal("60000.00")),
                notes="check clearance again",
            ),
            PairCase(
                key=f"{net_a}::{net_c}",
                net_a=net_a,
                net_b=net_c,
                voltages=PairVoltages(
                    long_term_rms_v=PairVoltage.not_applicable("never adjacent"),
                    steady_state_peak_v=PairVoltage.not_applicable("never adjacent"),
                    recurring_peak_v=PairVoltage.not_applicable("never adjacent"),
                    temporary_overvoltage_peak_v=PairVoltage.not_applicable("never adjacent"),
                ),
            ),
            PairCase(key=f"{net_b}::{net_c}", net_a=net_b, net_b=net_c),
        ),
    )


def _as_schema_v2_document(project: Project) -> dict[str, object]:
    document: dict[str, object] = {"schema_version": 2, **project.model_dump(mode="json")}
    document.pop("galvanic_domains", None)
    document.pop("galvanic_barriers", None)
    for net in document["net_classes"]:  # type: ignore[union-attr]
        for key in NET_TOPOLOGY_KEYS:
            net.pop(key, None)
    return document


def test_migration_v2_to_v3_adds_direct_domain_and_classifies_every_net(
    topology_migration_project: Project,
) -> None:
    raw = _as_schema_v2_document(topology_migration_project)
    original_pairs = deepcopy(raw["pairs"])
    original_nets = deepcopy(raw["net_classes"])

    migrated = migrate_project_document(raw)

    assert migrated["schema_version"] == 3
    assert migrated["pairs"] == original_pairs
    assert migrated["galvanic_barriers"] == []

    domains = migrated["galvanic_domains"]
    assert isinstance(domains, list)
    assert len(domains) == 1
    domain = domains[0]
    assert domain["is_direct_source_domain"] is True
    assert domain["review_state"] == "needs_review"
    assert isinstance(domain["name"], str) and domain["name"]
    assert UUID(domain["id"])  # generated id must parse as a UUID
    domain_id = domain["id"]

    nets = migrated["net_classes"]
    assert isinstance(nets, list)
    assert len(nets) == len(original_nets)
    for migrated_net, original_net in zip(nets, original_nets, strict=True):
        assert migrated_net["net_type"] == "circuit"
        assert migrated_net["source_relationship"] == "internally_generated"
        assert migrated_net["connection_exposure"] == "internal_only"
        assert migrated_net["decisive_voltage_class"] == "not_evaluated"
        assert migrated_net["galvanic_domain_id"] == domain_id
        assert migrated_net["classification_review_state"] == "needs_review"
        untouched = {k: v for k, v in migrated_net.items() if k not in NET_TOPOLOGY_KEYS}
        assert untouched == original_net


def test_migrated_classification_state_is_needs_review_not_confirmed(
    topology_migration_project: Project,
) -> None:
    raw = _as_schema_v2_document(topology_migration_project)

    migrated = migrate_project_document(raw)

    assert migrated["galvanic_domains"][0]["review_state"] == "needs_review"  # type: ignore[index]
    assert all(
        net["classification_review_state"] == "needs_review"  # type: ignore[union-attr]
        for net in migrated["net_classes"]  # type: ignore[union-attr]
    )


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda raw: raw.__setitem__("galvanic_domains", []), "galvanic_domains"),
        (lambda raw: raw.__setitem__("galvanic_barriers", []), "galvanic_barriers"),
        (lambda raw: raw["net_classes"][0].__setitem__("net_type", "circuit"), "topology"),
    ],
)
def test_migration_rejects_v2_document_already_carrying_topology_keys(
    topology_migration_project: Project, mutate: object, match: str
) -> None:
    raw = _as_schema_v2_document(topology_migration_project)
    mutate(raw)  # type: ignore[operator]

    with pytest.raises(ProjectVersionError, match=match):
        migrate_project_document(raw)


def test_migrated_project_round_trips_without_creating_a_second_domain(
    topology_migration_project: Project, tmp_path: Path
) -> None:
    raw = _as_schema_v2_document(topology_migration_project)
    path = tmp_path / "legacy.icproj"
    path.write_text(json.dumps(raw), encoding="utf-8")

    first_load = load_project(path)
    save_project_atomic(path, first_load)
    second_load = load_project(path)

    assert second_load == first_load
    assert len(second_load.galvanic_domains) == 1
    assert second_load.galvanic_domains[0].id == first_load.galvanic_domains[0].id
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 3
    assert len(saved["galvanic_domains"]) == 1


def test_schema_v1_document_loads_through_both_migration_steps(
    topology_migration_project: Project, tmp_path: Path
) -> None:
    document = _as_schema_v2_document(topology_migration_project)
    document.pop("group_splits", None)
    document["schema_version"] = 1
    path = tmp_path / "legacy-v1.icproj"
    path.write_text(json.dumps(document), encoding="utf-8")

    loaded = load_project(path)

    assert loaded.group_splits == ()
    assert len(loaded.galvanic_domains) == 1
    assert loaded.galvanic_domains[0].is_direct_source_domain is True
    assert all(
        net.classification_review_state is ReviewState.NEEDS_REVIEW for net in loaded.net_classes
    )


def test_project_round_trip_preserves_decimal_text(sample_project: Project, tmp_path: Path) -> None:
    path = tmp_path / "drive.icproj"

    save_project_atomic(path, sample_project)

    assert '"560.00"' in path.read_text(encoding="utf-8")
    assert load_project(path) == sample_project


def test_round_trip_preserves_exact_ruleset_pin(sample_project: Project, tmp_path: Path) -> None:
    path = tmp_path / "drive.icproj"
    save_project_atomic(path, sample_project)

    loaded = load_project(path)

    assert loaded.required_rules == RulePackageReference(
        package_id="iec-60664", version="2020.1", sha256="a" * 64
    )


def test_failed_replace_preserves_previous_file(
    sample_project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "drive.icproj"
    unrelated = tmp_path / "unrelated.tmp"
    path.write_text('{"schema_version":1,"sentinel":true}', encoding="utf-8")
    unrelated.write_text("do not remove", encoding="utf-8")
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("disk error")))

    with pytest.raises(ProjectSaveError, match="disk error"):
        save_project_atomic(path, sample_project)

    assert '"sentinel":true' in path.read_text(encoding="utf-8")
    assert unrelated.read_text(encoding="utf-8") == "do not remove"
    assert list(tmp_path.glob("*.tmp")) == [unrelated]


def test_migration_chains_v1_through_v2_to_v3_without_mutating_source() -> None:
    raw: dict[str, object] = {"schema_version": 1, "sentinel": True}
    original = deepcopy(raw)

    migrated = migrate_project_document(raw)

    domain = migrated["galvanic_domains"][0]  # type: ignore[index]
    assert migrated == {
        "schema_version": 3,
        "sentinel": True,
        "group_splits": [],
        "galvanic_domains": [domain],
        "galvanic_barriers": [],
    }
    assert domain["is_direct_source_domain"] is True  # type: ignore[index]
    assert domain["review_state"] == "needs_review"  # type: ignore[index]
    assert UUID(domain["id"])  # type: ignore[index]
    assert raw == original
    assert migrated is not raw


def test_future_schema_is_rejected() -> None:
    with pytest.raises(ProjectVersionError, match="newer"):
        migrate_project_document({"schema_version": 4})


def test_unsupported_older_schema_is_rejected() -> None:
    with pytest.raises(ProjectVersionError, match="unsupported"):
        migrate_project_document({"schema_version": 0})


def test_load_rejects_future_schema_without_changing_file(tmp_path: Path) -> None:
    path = tmp_path / "future.icproj"
    original = json.dumps({"schema_version": 4})
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectVersionError, match="newer"):
        load_project(path)

    assert path.read_text(encoding="utf-8") == original


def test_schema_v1_loads_with_empty_group_splits_and_save_writes_current_schema(
    sample_project: Project, tmp_path: Path
) -> None:
    old_document = {"schema_version": 1, **sample_project.model_dump(mode="json")}
    old_document.pop("group_splits", None)
    old_document.pop("galvanic_domains", None)
    old_document.pop("galvanic_barriers", None)
    for net in old_document["net_classes"]:
        for key in NET_TOPOLOGY_KEYS:
            net.pop(key, None)
    path = tmp_path / "old.icproj"
    path.write_text(json.dumps(old_document), encoding="utf-8")

    loaded = load_project(path)
    save_project_atomic(path, loaded)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert loaded.group_splits == ()
    assert len(loaded.galvanic_domains) == 1
    assert loaded.galvanic_domains[0].is_direct_source_domain is True
    assert saved["schema_version"] == 3
    assert saved["group_splits"] == []


def test_schema_v1_with_mislabeled_group_splits_is_rejected_without_rewriting_source(
    sample_project: Project, tmp_path: Path
) -> None:
    document = {"schema_version": 1, **sample_project.model_dump(mode="json")}
    document["group_splits"] = []
    original = json.dumps(document)
    path = tmp_path / "mislabeled-v1.icproj"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectVersionError, match="group_splits"):
        load_project(path)

    assert path.read_text(encoding="utf-8") == original


def test_project_persists_group_split_metadata(sample_project: Project, tmp_path: Path) -> None:
    split = GroupSplit(signature="a" * 64, pair_ids=(str(sample_project.pairs[0].id),))
    project = sample_project.model_copy(update={"group_splits": (split,)})
    path = tmp_path / "splits.icproj"

    save_project_atomic(path, project)

    assert load_project(path).group_splits == (split,)


@pytest.mark.parametrize("location", ["top_level", "pair"])
def test_load_rejects_unknown_persisted_fields(
    sample_project: Project, tmp_path: Path, location: str
) -> None:
    path = tmp_path / "unknown.icproj"
    save_project_atomic(path, sample_project)
    document = json.loads(path.read_text(encoding="utf-8"))
    target = document if location == "top_level" else document["pairs"][0]
    target["misspelled_input"] = "must not be discarded"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProjectLoadError, match="misspelled_input") as error:
        load_project(path)

    assert "extra_forbidden" in str(error.value.__cause__)


@pytest.mark.parametrize("field", ["package_id", "version"])
def test_rules_reference_strips_and_rejects_blank_identifiers(field: str) -> None:
    values = {"package_id": " rules ", "version": " 1 ", "sha256": "a" * 64}
    assert RulePackageReference(**values).model_dump()[field] == values[field].strip()
    values[field] = " \t "

    with pytest.raises(ValidationError, match="at least 1 character"):
        RulePackageReference(**values)


def test_temp_creation_failure_preserves_previous_file(
    sample_project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "drive.icproj"
    path.write_text("previous", encoding="utf-8")
    monkeypatch.setattr("tempfile.NamedTemporaryFile", Mock(side_effect=OSError("create error")))

    with pytest.raises(ProjectSaveError, match="create error"):
        save_project_atomic(path, sample_project)

    assert path.read_text(encoding="utf-8") == "previous"


@pytest.mark.parametrize("operation", ["write", "flush"])
def test_temp_write_or_flush_failure_preserves_previous_file(
    sample_project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    path = tmp_path / "drive.icproj"
    path.write_text("previous", encoding="utf-8")

    class FailingTemporaryFile:
        name = str(tmp_path / "known.tmp")

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def write(self, _: str) -> int:
            if operation == "write":
                raise OSError("write error")
            return 0

        def flush(self) -> None:
            if operation == "flush":
                raise OSError("flush error")

        def fileno(self) -> int:
            return 0

    monkeypatch.setattr("tempfile.NamedTemporaryFile", Mock(return_value=FailingTemporaryFile()))

    with pytest.raises(ProjectSaveError, match=f"{operation} error"):
        save_project_atomic(path, sample_project)

    assert path.read_text(encoding="utf-8") == "previous"


def test_fsync_failure_removes_only_known_temp_and_preserves_previous_file(
    sample_project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "drive.icproj"
    unrelated = tmp_path / "unrelated.tmp"
    path.write_text("previous", encoding="utf-8")
    unrelated.write_text("do not remove", encoding="utf-8")
    monkeypatch.setattr(os, "fsync", Mock(side_effect=OSError("sync error")))

    with pytest.raises(ProjectSaveError, match="sync error"):
        save_project_atomic(path, sample_project)

    assert path.read_text(encoding="utf-8") == "previous"
    assert unrelated.read_text(encoding="utf-8") == "do not remove"
    assert list(tmp_path.glob("*.tmp")) == [unrelated]


def test_cleanup_failure_does_not_mask_replace_failure(
    sample_project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "drive.icproj"
    path.write_text("previous", encoding="utf-8")
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("replace error")))
    monkeypatch.setattr(Path, "unlink", Mock(side_effect=OSError("cleanup error")))

    with pytest.raises(ProjectSaveError, match="replace error"):
        save_project_atomic(path, sample_project)

    assert path.read_text(encoding="utf-8") == "previous"


def test_project_requires_unique_net_names_and_consistent_pairs(sample_project: Project) -> None:
    first, second = sample_project.net_classes
    with pytest.raises(ValidationError, match="unique"):
        Project(
            **sample_project.model_dump(exclude={"net_classes"}),
            net_classes=(first, second.model_copy(update={"name": "HV"})),
        )
    with pytest.raises(ValidationError, match="canonical"):
        Project(
            **sample_project.model_dump(exclude={"pairs"}),
            pairs=(sample_project.pairs[0].model_copy(update={"key": "wrong"}),),
        )


def test_rules_reference_rejects_invalid_sha256() -> None:
    with pytest.raises(ValidationError, match="64"):
        RulePackageReference(package_id="rules", version="1", sha256="not-a-hash")
