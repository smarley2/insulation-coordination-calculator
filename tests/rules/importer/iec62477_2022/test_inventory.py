from insulation_coordination.rules.importer.iec62477_2022.inventory import (
    DEFERRED_SEMANTIC_IDS,
    REQUIRED_SOURCE_ITEMS,
)
from insulation_coordination.rules.importer.iec62477_2022.semantic_ids import (
    ALTITUDE_CLEARANCE_CORRECTION,
    ALTITUDE_TEST_VOLTAGE_CORRECTION,
    DVC_FAULT_TIME_VOLTAGE,
    REQUIRED_SEMANTIC_IDS,
)
from insulation_coordination.rules.importer.recipes import RECIPES


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


def test_every_deferred_identifier_is_a_required_inventory_item() -> None:
    """The deferred set cannot hide an identifier that does not exist."""

    assert DEFERRED_SEMANTIC_IDS <= {item.semantic_id for item in REQUIRED_SOURCE_ITEMS}


def test_nothing_is_deferred_any_more() -> None:
    """Slice E closed the package: every required item has a recipe, so nothing is deferred.

    While anything was deferred, completeness reported it as deferred rather than missing.
    With the set empty, a required item without a recipe is reported as missing, which is
    what the inventory gate refuses.
    """
    assert DEFERRED_SEMANTIC_IDS == frozenset()


def test_every_item_this_build_does_not_defer_has_a_recipe() -> None:
    """The build-time half of completeness.

    Approval refuses a draft that skipped content the recipes declare; this asserts the
    other half, that the recipes really do declare everything the inventory requires apart
    from the items explicitly deferred. When Slice E lands and empties the deferred set,
    this covers all twenty-five.
    """
    declared = {
        spec.semantic_id
        for recipe in RECIPES
        for spec in (*recipe.tables, *recipe.clauses, *recipe.curves, *recipe.formulas)
    }
    for item in REQUIRED_SOURCE_ITEMS:
        if item.semantic_id in DEFERRED_SEMANTIC_IDS:
            continue
        covered = any(
            candidate == item.semantic_id or candidate.startswith(f"{item.semantic_id}.")
            for candidate in declared
        )
        assert covered, f"no recipe declares {item.semantic_id}"


def test_annex_e_tables_are_two_required_items_with_their_own_consumers() -> None:
    """Each Annex E table is required in its own right, independently of the recipe.

    E.1 feeds clearance dimensioning in #36; E.2 feeds verification in #37. Stated here
    rather than derived from the specs, because that is the hole the single parent item left:
    had one table's recipe been removed, ``_covers`` would have matched the parent through
    the surviving route and the checklist could still have reported complete.
    """
    items = {
        item.semantic_id: item
        for item in REQUIRED_SOURCE_ITEMS
        if item.semantic_id.startswith("iec62477_2022.altitude.")
    }

    assert set(items) == {ALTITUDE_CLEARANCE_CORRECTION, ALTITUDE_TEST_VOLTAGE_CORRECTION}
    assert items[ALTITUDE_CLEARANCE_CORRECTION].expected_table == "Table E.1"
    assert items[ALTITUDE_CLEARANCE_CORRECTION].consumer_issue_ids == (36,)
    assert items[ALTITUDE_TEST_VOLTAGE_CORRECTION].expected_table == "Table E.2"
    assert items[ALTITUDE_TEST_VOLTAGE_CORRECTION].consumer_issue_ids == (37,)
