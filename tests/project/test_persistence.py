from __future__ import annotations

import json
import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.project import (
    NetClass,
    PairCase,
    PairVoltage,
    PairVoltages,
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.project.persistence import (
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
                voltages=PairVoltages(
                    long_term_rms_v=PairVoltage.applicable(Decimal("560.00"))
                ),
            ),
        ),
    )


def test_project_round_trip_preserves_decimal_text(
    sample_project: Project, tmp_path: Path
) -> None:
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
    path.write_text('{"schema_version":1,"sentinel":true}', encoding="utf-8")
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("disk error")))

    with pytest.raises(ProjectSaveError, match="disk error"):
        save_project_atomic(path, sample_project)

    assert '"sentinel":true' in path.read_text(encoding="utf-8")
    assert list(tmp_path.glob("*.tmp")) == []


def test_migration_returns_new_document_without_overwriting_source() -> None:
    raw: dict[str, object] = {"schema_version": 1, "sentinel": True}
    original = deepcopy(raw)

    migrated = migrate_project_document(raw)

    assert migrated == original
    assert raw == original
    assert migrated is not raw


def test_future_schema_is_rejected() -> None:
    with pytest.raises(ProjectVersionError, match="newer"):
        migrate_project_document({"schema_version": 2})


def test_load_rejects_future_schema_without_changing_file(tmp_path: Path) -> None:
    path = tmp_path / "future.icproj"
    original = json.dumps({"schema_version": 2})
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectVersionError, match="newer"):
        load_project(path)

    assert path.read_text(encoding="utf-8") == original


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
