from itertools import combinations
from uuid import UUID

from insulation_coordination.domain.project import NetClass, PairCase


def canonical_pair_key(left: UUID, right: UUID) -> str:
    if left == right:
        raise ValueError("A pair requires two different net classes")
    first, second = sorted((str(left), str(right)))
    return f"{first}::{second}"


def reconcile_pairs(
    net_classes: tuple[NetClass, ...], existing: tuple[PairCase, ...]
) -> tuple[PairCase, ...]:
    ids = [net_class.id for net_class in net_classes]
    if len(set(ids)) != len(ids):
        raise ValueError("Net-class IDs must be unique")

    existing_by_key = {canonical_pair_key(pair.net_a, pair.net_b): pair for pair in existing}
    if len(existing_by_key) != len(existing):
        raise ValueError("Only one case may exist for an unordered net-class pair")

    pairs: list[PairCase] = []
    for left, right in combinations(ids, 2):
        key = canonical_pair_key(left, right)
        current = existing_by_key.get(key)
        if current is None:
            pairs.append(PairCase(key=key, net_a=left, net_b=right))
        else:
            pairs.append(current.model_copy(update={"key": key, "net_a": left, "net_b": right}))
    return tuple(pairs)
