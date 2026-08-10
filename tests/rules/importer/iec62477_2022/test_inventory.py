from insulation_coordination.rules.importer.iec62477_2022.inventory import (
    REQUIRED_SOURCE_ITEMS,
)
from insulation_coordination.rules.importer.iec62477_2022.semantic_ids import (
    DVC_FAULT_TIME_VOLTAGE,
    REQUIRED_SEMANTIC_IDS,
)


def test_inventory_covers_every_required_id_exactly_once() -> None:
    ids = [item.semantic_id for item in REQUIRED_SOURCE_ITEMS]
    assert len(ids) == len(set(ids))
    assert set(ids) == REQUIRED_SEMANTIC_IDS


def test_every_item_names_at_least_one_consumer_issue() -> None:
    assert all(item.consumer_issue_ids for item in REQUIRED_SOURCE_ITEMS)


def test_every_consumer_issue_has_at_least_one_item() -> None:
    consumers = {issue for item in REQUIRED_SOURCE_ITEMS for issue in item.consumer_issue_ids}
    assert consumers == {35, 36, 37}


def test_every_table_item_declares_its_table() -> None:
    for item in REQUIRED_SOURCE_ITEMS:
        if item.expected_output_kind == "table":
            assert item.expected_table is not None


def test_every_item_targets_the_supported_edition() -> None:
    for item in REQUIRED_SOURCE_ITEMS:
        assert item.standard == "IEC 62477-1"
        assert item.edition == "2022"


def test_fault_time_voltage_is_a_curve() -> None:
    item = next(
        item for item in REQUIRED_SOURCE_ITEMS if item.semantic_id == DVC_FAULT_TIME_VOLTAGE
    )
    assert item.expected_output_kind == "curve"
