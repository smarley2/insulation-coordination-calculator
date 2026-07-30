"""Deterministic calculation groups and presentation-only partitions."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import Field

from insulation_coordination.calculation.engine import PairResult
from insulation_coordination.domain.project import FrozenModel, GroupSplit

__all__ = [
    "CalculationGroup",
    "GroupingError",
    "calculation_signature",
    "group_results",
    "merge_groups",
    "split_group",
]


class GroupingError(ValueError):
    """Saved presentation grouping cannot be applied safely."""


class CalculationGroup(FrozenModel):
    group_id: str = Field(min_length=1)
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    pair_ids: tuple[str, ...] = Field(min_length=1)
    pair_display_order: tuple[int, ...] = ()


def calculation_signature(result: PairResult) -> str:
    """SHA-256 of every calculation-relevant, identity-free result value."""
    payload = result.model_dump(mode="python", exclude={"pair_id", "pair_key"})
    canonical_json = json.dumps(
        _canonical_json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def group_results(
    results: tuple[PairResult, ...], splits: tuple[GroupSplit, ...]
) -> tuple[CalculationGroup, ...]:
    """Rebuild groups from results; stale saved split references are rejected."""
    automatic: dict[str, list[str]] = {}
    display_index: dict[str, int] = {}
    for index, result in enumerate(results):
        pair_id = str(result.pair_id)
        if pair_id in display_index:
            raise GroupingError(f"duplicate pair ID in results: {pair_id}")
        display_index[pair_id] = index
        automatic.setdefault(calculation_signature(result), []).append(pair_id)

    split_ids: dict[str, list[tuple[str, ...]]] = {signature: [] for signature in automatic}
    for split in splits:
        members = automatic.get(split.signature)
        if members is None or not set(split.pair_ids) <= set(members):
            raise GroupingError("stale group split references a missing result or signature")
        if len(split.pair_ids) == len(members):
            raise GroupingError("saved group split must leave at least one pair in its source group")
        if set(split.pair_ids) & {
            pair_id for existing in split_ids[split.signature] for pair_id in existing
        }:
            raise GroupingError("saved group splits overlap")
        split_ids[split.signature].append(split.pair_ids)

    groups: list[CalculationGroup] = []
    for signature, members in automatic.items():
        selected = [pair_id for partition in split_ids[signature] for pair_id in partition]
        if not selected:
            groups.append(
                _group(
                    signature,
                    tuple(members),
                    pair_display_order=tuple(display_index[pair_id] for pair_id in members),
                    automatic=True,
                )
            )
            continue
        for partition in split_ids[signature]:
            groups.append(
                _group(
                    signature,
                    tuple(pair_id for pair_id in members if pair_id in partition),
                    pair_display_order=tuple(
                        display_index[pair_id] for pair_id in members if pair_id in partition
                    ),
                )
            )
        remainder = tuple(pair_id for pair_id in members if pair_id not in set(selected))
        if remainder:
            groups.append(
                _group(
                    signature,
                    remainder,
                    pair_display_order=tuple(display_index[pair_id] for pair_id in remainder),
                )
            )
    return tuple(sorted(groups, key=lambda group: min(display_index[pair] for pair in group.pair_ids)))


def split_group(
    groups: tuple[CalculationGroup, ...], group_id: str, pair_ids: tuple[str, ...]
) -> tuple[CalculationGroup, ...]:
    """Split one presentation group without changing its calculation signature."""
    _validate_groups(groups)
    target = next((group for group in groups if group.group_id == group_id), None)
    if target is None:
        raise GroupingError(f"unknown group ID: {group_id}")
    selected = _ordered_subset(target.pair_ids, pair_ids)
    if len(selected) == len(target.pair_ids):
        raise GroupingError("group split must leave at least one pair in its source group")
    remaining = tuple(pair_id for pair_id in target.pair_ids if pair_id not in set(selected))
    positions = _pair_positions(groups)
    replacement = (
        _group(
            target.signature,
            remaining,
            pair_display_order=tuple(positions[pair_id] for pair_id in remaining),
        ),
        _group(
            target.signature,
            selected,
            pair_display_order=tuple(positions[pair_id] for pair_id in selected),
        ),
    )
    return _sort_by_existing_display_order(groups, target.group_id, replacement)


def merge_groups(
    groups: tuple[CalculationGroup, ...], pair_ids: tuple[str, ...]
) -> tuple[CalculationGroup, ...]:
    """Merge selected groups only when all selected pairs share a signature."""
    _validate_groups(groups)
    positions = _pair_positions(groups)
    if len(pair_ids) != len(set(pair_ids)) or not pair_ids:
        raise GroupingError("pair IDs to merge must be non-empty and unique")
    if not set(pair_ids) <= set(positions):
        raise GroupingError("unknown pair ID in merge")
    selected_groups = [group for group in groups if set(group.pair_ids) & set(pair_ids)]
    signatures = {group.signature for group in selected_groups}
    if len(signatures) != 1:
        raise GroupingError("cannot merge pairs with different calculation signatures")
    signature = signatures.pop()
    selected = tuple(sorted(pair_ids, key=positions.__getitem__))
    retained: list[CalculationGroup] = []
    for group in groups:
        remainder = tuple(pair_id for pair_id in group.pair_ids if pair_id not in set(selected))
        if remainder == group.pair_ids:
            retained.append(group)
        elif remainder:
            retained.append(
                _group(
                    group.signature,
                    remainder,
                    pair_display_order=tuple(positions[pair_id] for pair_id in remainder),
                )
            )
    retained.append(
        _group(
            signature,
            selected,
            pair_display_order=tuple(positions[pair_id] for pair_id in selected),
        )
    )
    return tuple(sorted(retained, key=lambda group: min(positions[pair] for pair in group.pair_ids)))


def _group(
    signature: str,
    pair_ids: tuple[str, ...],
    *,
    pair_display_order: tuple[int, ...],
    automatic: bool = False,
) -> CalculationGroup:
    group_id = signature if automatic else _presentation_group_id(signature, pair_ids)
    return CalculationGroup(
        group_id=group_id,
        signature=signature,
        pair_ids=pair_ids,
        pair_display_order=pair_display_order,
    )


def _presentation_group_id(signature: str, pair_ids: tuple[str, ...]) -> str:
    payload = json.dumps([signature, *pair_ids], separators=(",", ":"))
    return "split-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ordered_subset(source: tuple[str, ...], requested: tuple[str, ...]) -> tuple[str, ...]:
    if len(requested) != len(set(requested)) or not requested:
        raise GroupingError("group split pair IDs must be non-empty and unique")
    if not set(requested) <= set(source):
        raise GroupingError("group split contains a pair outside its source group")
    return tuple(pair_id for pair_id in source if pair_id in set(requested))


def _validate_groups(groups: tuple[CalculationGroup, ...]) -> None:
    if len({group.group_id for group in groups}) != len(groups):
        raise GroupingError("group IDs must be unique")
    positions = _pair_positions(groups)
    if len(positions) != sum(len(group.pair_ids) for group in groups):
        raise GroupingError("a pair may belong to only one group")


def _pair_positions(groups: tuple[CalculationGroup, ...]) -> dict[str, int]:
    has_display_order = any(group.pair_display_order for group in groups)
    if has_display_order:
        if any(len(group.pair_display_order) != len(group.pair_ids) for group in groups):
            raise GroupingError("group display order must cover every pair")
        positions = {
            pair_id: display_order
            for group in groups
            for pair_id, display_order in zip(group.pair_ids, group.pair_display_order, strict=True)
        }
        if len(set(positions.values())) != len(positions):
            raise GroupingError("pair display order must be unique")
        return positions
    result_positions: dict[str, int] = {}
    for index, pair_id in enumerate(pair_id for group in groups for pair_id in group.pair_ids):
        result_positions[pair_id] = index
    return result_positions


def _sort_by_existing_display_order(
    groups: tuple[CalculationGroup, ...],
    replaced_group_id: str,
    replacement: tuple[CalculationGroup, ...],
) -> tuple[CalculationGroup, ...]:
    positions = _pair_positions(groups)
    updated = [group for group in groups if group.group_id != replaced_group_id] + list(replacement)
    return tuple(sorted(updated, key=lambda group: min(positions[pair] for pair in group.pair_ids)))


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported calculation signature value: {type(value).__name__}")


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("calculation signatures require finite Decimal values")
    if value.is_zero():
        return "0"
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    text = "".join(str(digit) for digit in digits).rstrip("0")
    exponent += len(digits) - len(text)
    prefix = "-" if sign else ""
    if exponent >= 0:
        return prefix + text + "0" * exponent
    decimal_point = len(text) + exponent
    if decimal_point > 0:
        return prefix + text[:decimal_point] + "." + text[decimal_point:]
    return prefix + "0." + "0" * -decimal_point + text
