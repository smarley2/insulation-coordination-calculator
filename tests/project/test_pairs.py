from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from insulation_coordination.domain.project import (
    NetClass,
    PairCase,
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.project.pairs import canonical_pair_key, reconcile_pairs


def test_three_net_classes_create_three_canonical_pairs() -> None:
    classes = tuple(NetClass(id=UUID(int=index), name=f"N{index}") for index in (1, 2, 3))

    pairs = reconcile_pairs(classes, ())

    assert [pair.key for pair in pairs] == [
        f"{UUID(int=1)}::{UUID(int=2)}",
        f"{UUID(int=1)}::{UUID(int=3)}",
        f"{UUID(int=2)}::{UUID(int=3)}",
    ]


def test_reconciliation_preserves_existing_case_for_reversed_net_order() -> None:
    first, second = UUID(int=1), UUID(int=2)
    existing = PairCase(key="legacy", net_a=second, net_b=first, notes="keep this")

    pairs = reconcile_pairs(
        (NetClass(id=first, name="A"), NetClass(id=second, name="B")), (existing,)
    )

    assert pairs[0].key == f"{first}::{second}"
    assert pairs[0].net_a == first
    assert pairs[0].net_b == second
    assert pairs[0].notes == "keep this"


def test_pair_rejects_the_same_net_twice() -> None:
    with pytest.raises(ValidationError, match="two different"):
        PairCase(key="invalid", net_a=UUID(int=1), net_b=UUID(int=1))


def test_canonical_pair_key_rejects_diagonal_pair() -> None:
    with pytest.raises(ValueError, match="two different"):
        canonical_pair_key(UUID(int=1), UUID(int=1))


@given(st.lists(st.uuids(), unique=True, max_size=12))
def test_pair_reconciliation_has_one_unique_pair_per_unordered_combination(ids: list[UUID]) -> None:
    pairs = reconcile_pairs(tuple(NetClass(id=value, name=str(value)) for value in ids), ())

    assert len(pairs) == len(ids) * (len(ids) - 1) // 2
    assert len({pair.key for pair in pairs}) == len(pairs)
    for pair in pairs:
        assert canonical_pair_key(pair.net_a, pair.net_b) == pair.key
        assert canonical_pair_key(pair.net_b, pair.net_a) == pair.key


def test_project_rejects_duplicate_pair_ids_even_for_distinct_net_pairs() -> None:
    classes = tuple(NetClass(id=UUID(int=index), name=f"N{index}") for index in (1, 2, 3))
    pairs = list(reconcile_pairs(classes, ()))
    pairs[1] = pairs[1].model_copy(update={"id": pairs[0].id})

    with pytest.raises(ValidationError, match="Pair IDs must be unique"):
        Project(
            id=UUID(int=10),
            metadata=ProjectMetadata(title="Synthetic"),
            application_version="test",
            required_rules=RulePackageReference(
                package_id="synthetic",
                version="1",
                sha256="a" * 64,
            ),
            defaults=ProjectDefaults(),
            net_classes=classes,
            pairs=tuple(pairs),
        )
