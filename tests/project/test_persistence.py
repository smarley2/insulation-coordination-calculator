from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Self
from unittest.mock import Mock
from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.enums import InsulationType, ReviewState
from insulation_coordination.domain.project import (
    GroupSplit,
    ImpulseVerificationMethod,
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
from insulation_coordination.domain.supply import (
    DeclaredSystemVoltage,
    EarthingArrangement,
    ImpulseOverrideBasis,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    ReductionVerificationMethod,
    SupplyConfiguration,
    SupplyConfigurationProblemCode,
    SupplyKind,
    VerifiedImpulseOverride,
    validate_supply_configurations,
)
from insulation_coordination.domain.verification import (
    EvidenceApprovalState,
    ProtectionImplementation,
    RoutineTestExemptionEvidence,
    SolidInsulationTestData,
    VoltageEvidence,
    VoltageEvidenceMethod,
    VoltageQuantityKind,
)
from insulation_coordination.project.persistence import (
    IMPULSE_VERIFICATION_KEY,
    NET_TOPOLOGY_KEYS,
    PAIR_VERIFICATION_KEYS,
    PROJECT_SCHEMA_VERSION,
    ProjectLoadError,
    ProjectSaveError,
    ProjectVersionError,
    load_project,
    migrate_project_document,
    save_project_atomic,
)
from tests.fixtures.images import attachment_from, png_bytes


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


def _without_fields_added_since_v6(document: dict[str, object]) -> dict[str, object]:
    """Strip everything the version 6 -> 7 migration introduces, in place."""
    document.pop(IMPULSE_VERIFICATION_KEY, None)
    return document


def _without_fields_added_since_v5(document: dict[str, object]) -> dict[str, object]:
    """Strip everything the migrations after version 5 introduce, in place."""
    _without_fields_added_since_v6(document)
    document.pop("voltage_evidence", None)
    for pair in document["pairs"]:  # type: ignore[union-attr]
        for key in PAIR_VERIFICATION_KEYS:
            pair.pop(key, None)
    return document


def _without_fields_added_since_v3(document: dict[str, object]) -> dict[str, object]:
    """Strip everything the migrations after version 3 introduce, in place."""
    _without_fields_added_since_v5(document)
    document.pop("galvanic_domains", None)
    document.pop("galvanic_barriers", None)
    document.pop("supply_configurations", None)
    for net in document["net_classes"]:  # type: ignore[union-attr]
        for key in NET_TOPOLOGY_KEYS:
            net.pop(key, None)
    return document


def _as_schema_v3_document(project: Project) -> dict[str, object]:
    return _without_fields_added_since_v3({"schema_version": 3, **project.model_dump(mode="json")})


def _as_schema_v5_document(project: Project) -> dict[str, object]:
    return _without_fields_added_since_v5({"schema_version": 5, **project.model_dump(mode="json")})


def _as_schema_v6_document(project: Project) -> dict[str, object]:
    return _without_fields_added_since_v6({"schema_version": 6, **project.model_dump(mode="json")})


def _pairs_without_verification_keys(document: dict[str, object]) -> list[dict[str, object]]:
    return [
        {key: value for key, value in pair.items() if key not in PAIR_VERIFICATION_KEYS}
        for pair in document["pairs"]  # type: ignore[union-attr]
    ]


def test_migration_v3_to_v4_adds_direct_domain_and_classifies_every_net(
    topology_migration_project: Project,
) -> None:
    raw = _as_schema_v3_document(topology_migration_project)
    original_pairs = deepcopy(raw["pairs"])
    original_nets = deepcopy(raw["net_classes"])

    migrated = migrate_project_document(raw)

    assert migrated["schema_version"] == PROJECT_SCHEMA_VERSION
    assert _pairs_without_verification_keys(migrated) == original_pairs
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


def test_migration_v3_to_v4_changes_nothing_outside_the_topology_fields_it_introduces(
    topology_migration_project: Project,
) -> None:
    """Every top-level key the v3 document already had survives byte-identically.

    The per-net and per-pair checks above cover the two collections the migration walks;
    this covers the rest of the document, so a future migration step cannot quietly
    rewrite the metadata, defaults or required-rules reference of an existing project.
    """
    raw = _as_schema_v3_document(topology_migration_project)
    original = deepcopy(raw)

    migrated = migrate_project_document(raw)

    introduced = {
        "schema_version",
        "galvanic_domains",
        "galvanic_barriers",
        "supply_configurations",
        "voltage_evidence",
        "net_classes",
        "pairs",
    }
    assert set(migrated) - set(original) == introduced - {"schema_version", "net_classes", "pairs"}
    for key, value in original.items():
        if key in introduced:
            continue
        assert migrated[key] == value, f"migration changed the pre-existing key {key!r}"


def test_migrated_classification_state_is_needs_review_not_confirmed(
    topology_migration_project: Project,
) -> None:
    raw = _as_schema_v3_document(topology_migration_project)

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
    ],
)
def test_migration_rejects_v3_document_already_carrying_reserved_top_level_keys(
    topology_migration_project: Project, mutate: object, match: str
) -> None:
    raw = _as_schema_v3_document(topology_migration_project)
    mutate(raw)  # type: ignore[operator]

    with pytest.raises(ProjectVersionError, match=match):
        migrate_project_document(raw)


@pytest.mark.parametrize("key", sorted(NET_TOPOLOGY_KEYS))
def test_migration_rejects_v3_document_whose_net_already_carries_any_topology_key(
    topology_migration_project: Project, key: str
) -> None:
    """Parametrized over the whole frozenset, so a key added later is covered for free."""
    raw = _as_schema_v3_document(topology_migration_project)
    raw["net_classes"][0][key] = "already-set"  # type: ignore[index]

    with pytest.raises(ProjectVersionError, match="topology"):
        migrate_project_document(raw)


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": 2, "net_classes": ["oops"]},
        {"schema_version": 1, "net_classes": [None]},
    ],
)
def test_load_rejects_schema_document_with_a_non_dict_net_class_entry(
    tmp_path: Path, document: dict[str, object]
) -> None:
    """A hand-edited or corrupt document must fail as ``ProjectLoadError``, never crash.

    Before the fix, the migration called ``.keys()`` on each ``net_classes`` entry
    unconditionally, so a string or ``null`` entry raised a bare ``AttributeError`` out
    of ``load_project`` instead of the load error every other bad document produces.
    """
    path = tmp_path / "corrupt.icproj"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProjectLoadError):
        load_project(path)


def test_migrated_project_round_trips_without_creating_a_second_domain(
    topology_migration_project: Project, tmp_path: Path
) -> None:
    raw = _as_schema_v3_document(topology_migration_project)
    path = tmp_path / "legacy.icproj"
    path.write_text(json.dumps(raw), encoding="utf-8")

    first_load = load_project(path)
    save_project_atomic(path, first_load)
    second_load = load_project(path)

    assert second_load == first_load
    assert len(second_load.galvanic_domains) == 1
    assert second_load.galvanic_domains[0].id == first_load.galvanic_domains[0].id
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == PROJECT_SCHEMA_VERSION
    assert len(saved["galvanic_domains"]) == 1


def test_schema_v1_document_loads_through_every_migration_step(
    topology_migration_project: Project, tmp_path: Path
) -> None:
    document = _as_schema_v3_document(topology_migration_project)
    document.pop("group_splits", None)
    document.pop("circuit_diagram", None)
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


def test_migration_chains_every_step_from_v1_without_mutating_source() -> None:
    raw: dict[str, object] = {"schema_version": 1, "sentinel": True}
    original = deepcopy(raw)

    migrated = migrate_project_document(raw)

    domain = migrated["galvanic_domains"][0]  # type: ignore[index]
    assert migrated == {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "sentinel": True,
        "group_splits": [],
        "circuit_diagram": None,
        "galvanic_domains": [domain],
        "galvanic_barriers": [],
        "supply_configurations": [],
        "voltage_evidence": [],
    }
    assert domain["is_direct_source_domain"] is True  # type: ignore[index]
    assert domain["review_state"] == "needs_review"  # type: ignore[index]
    assert UUID(domain["id"])  # type: ignore[index]
    assert raw == original
    assert migrated is not raw


def test_future_schema_is_rejected() -> None:
    with pytest.raises(ProjectVersionError, match="newer"):
        migrate_project_document({"schema_version": PROJECT_SCHEMA_VERSION + 1})


def test_unsupported_older_schema_is_rejected() -> None:
    with pytest.raises(ProjectVersionError, match="unsupported"):
        migrate_project_document({"schema_version": 0})


def test_load_rejects_future_schema_without_changing_file(tmp_path: Path) -> None:
    path = tmp_path / "future.icproj"
    original = json.dumps({"schema_version": PROJECT_SCHEMA_VERSION + 1})
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectVersionError, match="newer"):
        load_project(path)

    assert path.read_text(encoding="utf-8") == original


def test_schema_v1_loads_with_empty_group_splits_and_save_writes_the_current_schema(
    sample_project: Project, tmp_path: Path
) -> None:
    old_document = _without_fields_added_since_v3(
        {"schema_version": 1, **sample_project.model_dump(mode="json")}
    )
    old_document.pop("group_splits", None)
    old_document.pop("circuit_diagram", None)
    path = tmp_path / "old.icproj"
    path.write_text(json.dumps(old_document), encoding="utf-8")

    loaded = load_project(path)
    save_project_atomic(path, loaded)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert loaded.group_splits == ()
    assert loaded.circuit_diagram is None
    assert len(loaded.galvanic_domains) == 1
    assert loaded.galvanic_domains[0].is_direct_source_domain is True
    assert saved["schema_version"] == PROJECT_SCHEMA_VERSION
    assert saved["group_splits"] == []
    assert saved["circuit_diagram"] is None


def test_schema_v2_loads_without_a_circuit_diagram(sample_project: Project, tmp_path: Path) -> None:
    document = _without_fields_added_since_v3(
        {"schema_version": 2, **sample_project.model_dump(mode="json")}
    )
    document.pop("circuit_diagram", None)
    path = tmp_path / "v2.icproj"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert load_project(path).circuit_diagram is None


def test_schema_v2_with_a_circuit_diagram_is_rejected(
    sample_project: Project, tmp_path: Path
) -> None:
    document = {"schema_version": 2, **sample_project.model_dump(mode="json")}
    document["circuit_diagram"] = None
    original = json.dumps(document)
    path = tmp_path / "mislabeled-v2.icproj"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectVersionError, match="circuit_diagram"):
        load_project(path)

    assert path.read_text(encoding="utf-8") == original


def test_circuit_diagram_survives_save_and_load_unchanged(
    sample_project: Project, tmp_path: Path
) -> None:
    attachment = attachment_from(png_bytes(), caption="Main topology", source_note="EDA export")
    project = sample_project.model_copy(update={"circuit_diagram": attachment})
    path = tmp_path / "diagram.icproj"

    save_project_atomic(path, project)
    loaded = load_project(path)

    assert loaded.circuit_diagram == attachment
    assert loaded.circuit_diagram is not None
    assert loaded.circuit_diagram.decoded_bytes() == attachment.decoded_bytes()
    assert loaded.circuit_diagram.sha256 == attachment.sha256


@pytest.mark.parametrize("field", ["sha256", "data_base64"])
def test_corrupted_attachment_payload_is_rejected_on_load(
    sample_project: Project, tmp_path: Path, field: str
) -> None:
    attachment = attachment_from(png_bytes())
    project = sample_project.model_copy(update={"circuit_diagram": attachment})
    path = tmp_path / "diagram.icproj"
    save_project_atomic(path, project)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["circuit_diagram"][field] = "f" * 64 if field == "sha256" else "!not base64!"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProjectLoadError, match="SHA-256|base64"):
        load_project(path)


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


# --- supply configurations and verified pair overrides (schema 4 -> 5) --------------------


def _supply_project(sample_project: Project) -> Project:
    """``sample_project`` with two supply rows - one disabled - and a verified pair override.

    Every value is this module's own. What a round-trip of it proves is that the arrangement
    a user entered survives, not that any of it is a reading of a standard.
    """
    return sample_project.model_copy(
        update={
            "supply_configurations": (
                SupplyConfiguration(
                    id=UUID(int=41),
                    enabled=True,
                    name="Site supply",
                    supply_kind=SupplyKind.AC_MAINS,
                    nominal_voltage_v=Decimal(15),
                    phase_system=PhaseSystem.THREE_PHASE,
                    earthing_arrangement=EarthingArrangement.TN_STAR_POINT_EARTHED,
                    overvoltage_category=OvervoltageCategory.III,
                    input_topology=InputTopology.DIRECT_INPUT,
                    declared_system_voltages=(
                        DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=Decimal(15)),
                    ),
                    notes="Primary arrangement",
                ),
                SupplyConfiguration(
                    id=UUID(int=42),
                    enabled=False,
                    name="Bench supply",
                    supply_kind=SupplyKind.NON_MAINS_DC,
                    nominal_voltage_v=Decimal(22),
                    phase_system=None,
                    earthing_arrangement=EarthingArrangement.NOT_APPLICABLE,
                    overvoltage_category=None,
                    input_topology=InputTopology.DIRECT_INPUT,
                ),
            ),
            "pairs": (
                sample_project.pairs[0].model_copy(
                    update={
                        "impulse_override": VerifiedImpulseOverride(
                            value_v=Decimal(111),
                            basis=ImpulseOverrideBasis.VERIFIED_CIRCUIT_CHARACTERISTIC,
                            verification_method=ReductionVerificationMethod.TEST,
                            justification="Measured at the terminals",
                            evidence_reference="LAB-7",
                            affected_location="HV to LV at the input filter",
                        )
                    }
                ),
            ),
        }
    )


def test_schema_v4_loads_with_no_supply_configurations_and_no_pair_overrides(
    topology_migration_project: Project, tmp_path: Path
) -> None:
    document = _without_fields_added_since_v5(
        {"schema_version": 4, **topology_migration_project.model_dump(mode="json")}
    )
    document.pop("supply_configurations", None)
    path = tmp_path / "v4.icproj"
    path.write_text(json.dumps(document), encoding="utf-8")

    loaded = load_project(path)

    assert loaded.supply_configurations == ()
    assert all(pair.impulse_override is None for pair in loaded.pairs)
    assert loaded == topology_migration_project


def test_schema_v4_carrying_supply_configurations_is_rejected(
    sample_project: Project, tmp_path: Path
) -> None:
    document = {"schema_version": 4, **sample_project.model_dump(mode="json")}
    document["supply_configurations"] = []
    original = json.dumps(document)
    path = tmp_path / "mislabeled-v4.icproj"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectVersionError, match="supply_configurations"):
        load_project(path)

    assert path.read_text(encoding="utf-8") == original


def test_a_legacy_project_keeps_its_stresses_and_gains_no_derived_values(
    topology_migration_project: Project, tmp_path: Path
) -> None:
    """Opening and saving an existing project adds an empty list and nothing else."""
    raw = _as_schema_v3_document(topology_migration_project)
    original_pairs = deepcopy(raw["pairs"])
    path = tmp_path / "legacy.icproj"
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_project(path)
    save_project_atomic(path, loaded)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["schema_version"] == PROJECT_SCHEMA_VERSION
    assert saved["supply_configurations"] == []
    for saved_pair, original_pair in zip(saved["pairs"], original_pairs, strict=True):  # type: ignore[arg-type]
        assert saved_pair["impulse_override"] is None
        assert saved_pair["voltages"] == original_pair["voltages"]
        assert saved_pair["impulse_v"] == original_pair["impulse_v"]
    assert load_project(path) == loaded


def test_supply_configurations_and_pair_overrides_round_trip_unchanged(
    sample_project: Project, tmp_path: Path
) -> None:
    project = _supply_project(sample_project)
    path = tmp_path / "supply.icproj"

    save_project_atomic(path, project)
    reloaded = load_project(path)

    assert reloaded == project
    save_project_atomic(path, reloaded)
    assert load_project(path) == project


def test_a_disabled_configuration_and_the_project_order_survive_a_round_trip(
    sample_project: Project, tmp_path: Path
) -> None:
    project = _supply_project(sample_project)
    path = tmp_path / "supply.icproj"

    save_project_atomic(path, project)
    reloaded = load_project(path)

    assert tuple(item.id for item in reloaded.supply_configurations) == (
        UUID(int=41),
        UUID(int=42),
    )
    assert [item.enabled for item in reloaded.supply_configurations] == [True, False]
    assert reloaded.supply_configurations[1].name == "Bench supply"


def test_only_entered_evidence_is_persisted_never_a_derived_result(
    sample_project: Project, tmp_path: Path
) -> None:
    """The saved document carries configurations and override evidence and nothing else.

    A derived impulse, a governing scenario or a propagated domain stress reaching the file
    would make a stale number authoritative on the next open. None of them has a key here.
    """
    path = tmp_path / "supply.icproj"
    save_project_atomic(path, _supply_project(sample_project))

    saved = json.loads(path.read_text(encoding="utf-8"))

    entered = {
        "id",
        "enabled",
        "name",
        "supply_kind",
        "nominal_voltage_v",
        "phase_system",
        "earthing_arrangement",
        "overvoltage_category",
        "input_topology",
        "rectifier_bridge_rms_v",
        "declared_system_voltages",
        "notes",
    }
    assert all(set(row) == entered for row in saved["supply_configurations"])
    override = saved["pairs"][0]["impulse_override"]
    assert override["value_v"] == "111"
    assert override["evidence_reference"] == "LAB-7"


def test_supply_configuration_ids_must_be_unique(sample_project: Project) -> None:
    project = _supply_project(sample_project)
    first = project.supply_configurations[0]
    with pytest.raises(ValidationError, match="unique"):
        Project(
            **project.model_dump(exclude={"supply_configurations"}),
            supply_configurations=(first, first.model_copy(update={"name": "Second"})),
        )


def test_two_configurations_sharing_a_name_are_reported_rather_than_refused(
    sample_project: Project,
) -> None:
    """Incompleteness is reportable data, not a save-blocking contradiction."""
    project = _supply_project(sample_project)
    first, second = project.supply_configurations

    renamed = project.model_copy(
        update={
            "supply_configurations": (
                first,
                second.model_copy(update={"name": first.name, "enabled": True}),
            )
        }
    )

    assert len(renamed.supply_configurations) == 2
    assert any(
        problem.code is SupplyConfigurationProblemCode.DUPLICATE_NAME
        for problem in validate_supply_configurations(renamed.supply_configurations)
    )


# --- verification state and protective means (schema 5 -> 6) ------------------------------


def _evidence(value: str, *, entry_id: int, pair_id: UUID) -> VoltageEvidence:
    """One approved entry. Every figure and string is this module's own."""
    return VoltageEvidence(
        id=UUID(int=entry_id),
        pair_id=pair_id,
        quantity_kind=VoltageQuantityKind.AC_RMS,
        value_v=Decimal(value),
        method=VoltageEvidenceMethod.SIMULATION,
        operating_condition="normal operation",
        source_reference="SIM-1",
        recorded_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        approval_state=EvidenceApprovalState.APPROVED_FOR_DESIGN,
    )


@pytest.fixture
def verification_project(sample_project: Project) -> Project:
    """``sample_project`` with one evidence entry and a fully declared pair."""
    pair = sample_project.pairs[0]
    return sample_project.model_copy(
        update={
            "voltage_evidence": (_evidence("41", entry_id=51, pair_id=pair.id),),
            "pairs": (
                pair.model_copy(
                    update={
                        "protection_implementation": (
                            ProtectionImplementation.PROTECTIVE_SCREEN_PLUS_BASIC
                        ),
                        "protection_review_state": ReviewState.USER_CONFIRMED,
                        "solid_insulation": SolidInsulationTestData(
                            present=True,
                            minimum_thickness_mm=Decimal("0.7"),
                            layer_count=3,
                            material_reference="MAT-9",
                        ),
                        "routine_exemption": RoutineTestExemptionEvidence(
                            subassemblies_routine_tested=True,
                            subassembly_evidence_reference="SUB-4",
                            reviewer="A. Reviewer",
                        ),
                    }
                ),
            ),
        }
    )


def test_schema_v5_with_supply_configurations_opens_and_keeps_everything(
    sample_project: Project, tmp_path: Path
) -> None:
    """#36's arrangements survive the bump, and nothing the project had is rewritten."""
    project = _supply_project(sample_project)
    document = _as_schema_v5_document(project)
    original = deepcopy(document)
    path = tmp_path / "v5.icproj"
    path.write_text(json.dumps(document), encoding="utf-8")

    loaded = load_project(path)

    assert loaded == project
    assert loaded.voltage_evidence == ()
    migrated = migrate_project_document(original)
    assert migrated["supply_configurations"] == original["supply_configurations"]
    for key, value in original.items():
        if key in {"schema_version", "voltage_evidence", "pairs"}:
            continue
        assert migrated[key] == value, f"migration changed the pre-existing key {key!r}"
    assert _pairs_without_verification_keys(migrated) == original["pairs"]


def test_schema_v5_carrying_voltage_evidence_is_rejected(
    sample_project: Project, tmp_path: Path
) -> None:
    document = _as_schema_v5_document(sample_project)
    document["voltage_evidence"] = []
    original = json.dumps(document)
    path = tmp_path / "mislabeled-v5.icproj"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectVersionError, match="voltage_evidence"):
        load_project(path)

    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("key", sorted(PAIR_VERIFICATION_KEYS))
def test_schema_v5_pair_already_carrying_a_verification_key_is_rejected(
    sample_project: Project, tmp_path: Path, key: str
) -> None:
    document = _as_schema_v5_document(sample_project)
    document["pairs"][0][key] = None  # type: ignore[index]
    original = json.dumps(document)
    path = tmp_path / "mislabeled-v5-pair.icproj"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectVersionError, match=key):
        load_project(path)

    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("insulation", "expected"),
    [
        (InsulationType.FUNCTIONAL, ProtectionImplementation.FUNCTIONAL_INSULATION),
        (InsulationType.BASIC, ProtectionImplementation.BASIC_INSULATION),
        (InsulationType.REINFORCED, ProtectionImplementation.REINFORCED_INSULATION),
    ],
)
def test_an_explicit_pair_insulation_selection_migrates_to_its_protective_means(
    sample_project: Project,
    insulation: InsulationType,
    expected: ProtectionImplementation,
) -> None:
    project = _with_insulation(sample_project, OverrideValue.override(insulation))

    migrated = migrate_project_document(_as_schema_v5_document(project))

    assert migrated["pairs"][0]["protection_implementation"] == expected.value  # type: ignore[index]


@pytest.mark.parametrize("insulation", [InsulationType.SUPPLEMENTARY, None])
def test_an_ambiguous_or_inherited_insulation_selection_migrates_to_nothing(
    sample_project: Project, insulation: InsulationType | None
) -> None:
    """Supplementary insulation may be one half of a double-insulation construction.

    Which it is cannot be read off the pair, and the protective means keep those two apart
    on purpose, so the migration records no selection at all rather than one that happens
    to share a name. A pair that inherited the project default never made a selection of
    its own either, and gets the same answer.
    """
    selection: OverrideValue[InsulationType] = (
        OverrideValue[InsulationType].inherit()
        if insulation is None
        else OverrideValue.override(insulation)
    )
    project = _with_insulation(sample_project, selection)

    migrated = migrate_project_document(_as_schema_v5_document(project))

    assert migrated["pairs"][0]["protection_implementation"] is None  # type: ignore[index]


@pytest.mark.parametrize(
    "selection",
    ["not an object", {"is_override": True, "value": "gold plated"}, {"is_override": True}],
)
def test_a_hand_edited_insulation_selection_migrates_to_nothing_rather_than_crashing(
    sample_project: Project, selection: object
) -> None:
    """The migration reads raw JSON, so it must survive a value no enum has."""
    document = _as_schema_v5_document(sample_project)
    document["pairs"][0]["insulation_type"] = selection  # type: ignore[index]

    migrated = migrate_project_document(document)

    assert migrated["pairs"][0]["protection_implementation"] is None  # type: ignore[index]


def test_every_migrated_protective_means_needs_review(
    sample_project: Project, tmp_path: Path
) -> None:
    project = _with_insulation(sample_project, OverrideValue.override(InsulationType.BASIC))
    path = tmp_path / "v5-review.icproj"
    path.write_text(json.dumps(_as_schema_v5_document(project)), encoding="utf-8")

    loaded = load_project(path)

    assert loaded.pairs[0].protection_implementation is ProtectionImplementation.BASIC_INSULATION
    assert loaded.pairs[0].protection_review_state is ReviewState.NEEDS_REVIEW


def _with_insulation(project: Project, selection: OverrideValue[InsulationType]) -> Project:
    return project.model_copy(
        update={
            "pairs": (project.pairs[0].model_copy(update={"insulation_type": selection}),),
        }
    )


def test_a_legacy_project_keeps_its_pair_ids_and_calculation_inputs(
    topology_migration_project: Project, tmp_path: Path
) -> None:
    """Every step from version 1 runs, and nothing a pair was dimensioned from moves."""
    raw = _as_schema_v3_document(topology_migration_project)
    raw["schema_version"] = 1
    raw.pop("group_splits", None)
    raw.pop("circuit_diagram", None)
    original_pairs = deepcopy(raw["pairs"])
    path = tmp_path / "legacy.icproj"
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_project(path)
    save_project_atomic(path, loaded)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["schema_version"] == PROJECT_SCHEMA_VERSION
    assert saved["voltage_evidence"] == []
    for saved_pair, original_pair in zip(saved["pairs"], original_pairs, strict=True):  # type: ignore[arg-type]
        assert saved_pair["id"] == original_pair["id"]
        assert saved_pair["key"] == original_pair["key"]
        assert saved_pair["voltages"] == original_pair["voltages"]
        assert saved_pair["frequency_hz"] == original_pair["frequency_hz"]
        assert saved_pair["notes"] == original_pair["notes"]
        assert saved_pair["solid_insulation"] is None
        assert saved_pair["routine_exemption"] is None
    assert load_project(path) == loaded


def test_verification_state_round_trips_unchanged(
    verification_project: Project, tmp_path: Path
) -> None:
    path = tmp_path / "verification.icproj"

    save_project_atomic(path, verification_project)
    reloaded = load_project(path)

    assert reloaded == verification_project
    save_project_atomic(path, reloaded)
    assert load_project(path) == verification_project


def test_schema_v6_opens_with_no_impulse_verification_method_chosen(
    verification_project: Project, tmp_path: Path
) -> None:
    """A project that never saw the choice has not made it, and nothing else is rewritten."""
    document = _as_schema_v6_document(verification_project)
    original = deepcopy(document)
    path = tmp_path / "v6.icproj"
    path.write_text(json.dumps(document), encoding="utf-8")

    loaded = load_project(path)

    assert loaded == verification_project
    assert loaded.impulse_verification_method is None
    migrated = migrate_project_document(original)
    assert set(migrated) - set(original) == set()
    for key, value in original.items():
        if key == "schema_version":
            continue
        assert migrated[key] == value, f"migration changed the pre-existing key {key!r}"


def test_the_migration_leaves_the_method_absent_rather_than_nulled(
    verification_project: Project,
) -> None:
    """The 4 -> 5 and 5 -> 6 steps left their optional records absent; so does this one.

    A written null would say a decision was recorded, and the value recorded was nothing.
    """
    migrated = migrate_project_document(_as_schema_v6_document(verification_project))

    assert IMPULSE_VERIFICATION_KEY not in migrated
    assert migrated["schema_version"] == PROJECT_SCHEMA_VERSION


def test_schema_v6_already_carrying_an_impulse_verification_method_is_rejected(
    verification_project: Project, tmp_path: Path
) -> None:
    document = _as_schema_v6_document(verification_project)
    document[IMPULSE_VERIFICATION_KEY] = ImpulseVerificationMethod.AC_VOLTAGE_TEST.value
    original = json.dumps(document)
    path = tmp_path / "mislabeled-v6.icproj"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectVersionError, match=IMPULSE_VERIFICATION_KEY):
        load_project(path)

    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("method", list(ImpulseVerificationMethod))
def test_a_chosen_impulse_verification_method_round_trips_unchanged(
    verification_project: Project, tmp_path: Path, method: ImpulseVerificationMethod
) -> None:
    project = verification_project.model_copy(update={"impulse_verification_method": method})
    path = tmp_path / "chosen.icproj"

    save_project_atomic(path, project)
    reloaded = load_project(path)

    assert reloaded.impulse_verification_method is method
    assert reloaded == project
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved[IMPULSE_VERIFICATION_KEY] == method.value


def test_voltage_evidence_ids_must_be_unique(verification_project: Project) -> None:
    entry = verification_project.voltage_evidence[0]
    with pytest.raises(ValidationError, match="unique"):
        Project(
            **verification_project.model_dump(exclude={"voltage_evidence"}),
            voltage_evidence=(entry, entry.model_copy(update={"notes": "a second entry"})),
        )
