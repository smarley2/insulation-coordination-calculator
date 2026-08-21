import pytest

from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    _require_complete_inventory,
)
from insulation_coordination.rules.importer.iec62477_2022.inventory import (
    DEFERRED_SEMANTIC_IDS,
    REQUIRED_SOURCE_ITEMS,
)
from insulation_coordination.rules.importer.iec62477_2022.semantic_ids import (
    ALTITUDE_CLEARANCE_CORRECTION,
    ALTITUDE_TEST_VOLTAGE_CORRECTION,
    DVC_FAULT_TIME_VOLTAGE,
    REQUIRED_SEMANTIC_IDS,
    TEST_DIELECTRIC_ACCEPTANCE,
    TEST_DIELECTRIC_APPLICATION_DURATION,
    TEST_DIELECTRIC_DISCONNECTION,
    TEST_DIELECTRIC_TOPOLOGY_SELECTION,
    TEST_IMPULSE_SELECTION,
    TEST_PARTIAL_DISCHARGE,
    TEST_PROTECTIVE_IMPEDANCE,
    TEST_SOLID_INSULATION_PARTIAL_DISCHARGE,
)
from insulation_coordination.rules.importer.recipes import RECIPES
from insulation_coordination.rules.importer.review import (
    inventory_report,
    missing_inventory_items,
)
from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft


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


def test_impulse_selection_is_declared_a_table() -> None:
    """The recipe projects Table 27 as four table specs, not a decision.

    A conformance review (issue #37, 2026-08-18) flagged this row: the declared kind must
    match what the recipe actually projects, or completeness checks are comparing the wrong
    shape.
    """
    item = next(
        item for item in REQUIRED_SOURCE_ITEMS if item.semantic_id == TEST_IMPULSE_SELECTION
    )
    assert item.expected_output_kind == "table"
    assert item.expected_table == "Table 27"


def test_partial_discharge_applicability_locator_is_the_clause_not_the_table() -> None:
    """Table 30 is the procedure; 4.4.7.10.3 is the applicability and classification rule.

    Same conformance review, finding A6: the inventory row named only Table 30, with no
    clause locator for the rule that actually decides when the test applies.
    """
    item = next(
        item for item in REQUIRED_SOURCE_ITEMS if item.semantic_id == TEST_PARTIAL_DISCHARGE
    )
    assert item.expected_table == "Table 30"
    assert item.expected_clause == "4.4.7.10.3"


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
    this covers all twenty-six.
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
    """Each Annex E table is required in its own right, with its own consumer.

    E.1 feeds clearance dimensioning in #36; E.2 feeds verification in #37. Stated here
    rather than derived from the specs: the split itself is what closes the hole the single
    parent item left, and this guard is what stops the two items being re-merged or their
    tables and consumers swapped.
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


def test_the_voltage_test_body_is_four_required_items_with_their_own_clauses() -> None:
    """Finding B3: Tables 28 and 29 carried the values and nothing carried the procedure.

    Each row names the subclause it comes from, because a required item without a locator is
    the same class of gap as the partial-discharge row above: completeness can report the item
    missing but nobody can tell where to go and get it.
    """
    expected = {
        TEST_DIELECTRIC_DISCONNECTION: ("5.2.3.4.3", "procedure"),
        TEST_DIELECTRIC_TOPOLOGY_SELECTION: ("5.2.3.4.4", "decision"),
        TEST_DIELECTRIC_APPLICATION_DURATION: ("5.2.3.4.5", "procedure"),
        TEST_DIELECTRIC_ACCEPTANCE: ("5.2.3.4.6", "decision"),
    }
    items = {item.semantic_id: item for item in REQUIRED_SOURCE_ITEMS}

    for semantic_id, (clause, kind) in expected.items():
        item = items[semantic_id]
        assert (item.expected_clause, item.expected_output_kind) == (clause, kind)
        assert item.expected_table is None
        assert item.consumer_issue_ids == (37,)


def test_a_package_predating_the_voltage_test_body_is_blocked_by_name() -> None:
    """Growing the required set makes the approved package incomplete, and that must be said.

    Not a crash and not a silent pass: the four identifiers are declared by the recipe, so
    completeness counts them, reports each as unapproved, and the approval path refuses with
    them named. A maintainer re-extracts and re-reviews rather than wondering why nothing
    changed.
    """
    draft = _draft()
    statuses = {status.semantic_id: status for status in inventory_report(draft)}
    body = (
        TEST_DIELECTRIC_DISCONNECTION,
        TEST_DIELECTRIC_TOPOLOGY_SELECTION,
        TEST_DIELECTRIC_APPLICATION_DURATION,
        TEST_DIELECTRIC_ACCEPTANCE,
    )

    for semantic_id in body:
        status = statuses[semantic_id]
        # Located, so it counts against completeness rather than being skipped as deferred.
        assert status.located
        assert not status.deferred
        assert not (status.extracted or status.typed or status.approved)

    assert set(body) <= {status.semantic_id for status in missing_inventory_items(draft)}
    with pytest.raises(ApprovalError, match="required inventory item"):
        _require_complete_inventory(draft)


def test_the_solid_insulation_partial_discharge_rule_is_its_own_required_item() -> None:
    """Finding A6's remaining half: Table 30 is the procedure, 4.4.7.10.3 is the rule.

    A sibling row rather than a second locator on the procedure's row, because the two answer
    different questions and a consumer asks for exactly one of them. Stated here rather than
    derived from the specs, so the two cannot be re-merged.
    """
    items = {item.semantic_id: item for item in REQUIRED_SOURCE_ITEMS}
    item = items[TEST_SOLID_INSULATION_PARTIAL_DISCHARGE]

    assert (item.expected_clause, item.expected_output_kind) == ("4.4.7.10.3", "decision")
    assert item.expected_table is None
    assert item.consumer_issue_ids == (37,)
    assert items[TEST_PARTIAL_DISCHARGE].expected_output_kind == "procedure"


def test_a_package_predating_the_partial_discharge_rule_is_blocked_by_name() -> None:
    """Growing the required set makes the approved package incomplete, and that must be said.

    Not a crash and not a silent pass: the identifier is declared by the recipe, so completeness
    counts it, reports it unextracted and unapproved, and the approval path refuses with it named.
    """
    draft = _draft()
    status = {status.semantic_id: status for status in inventory_report(draft)}[
        TEST_SOLID_INSULATION_PARTIAL_DISCHARGE
    ]

    assert status.located
    assert not status.deferred
    assert not (status.extracted or status.typed or status.approved)
    assert TEST_SOLID_INSULATION_PARTIAL_DISCHARGE in {
        item.semantic_id for item in missing_inventory_items(draft)
    }
    with pytest.raises(ApprovalError, match="required inventory item"):
        _require_complete_inventory(draft)


def test_the_protective_impedance_test_is_its_own_required_item() -> None:
    """Finding A9.4: the two tests are in 5.2.3.6, and its requirement subclause only points.

    A procedure item rather than a decision, because the subclause states obligations and a
    method rather than a choice keyed on an input. Stated here rather than derived from the
    specs, so it cannot be quietly folded into a dielectric route.
    """
    items = {item.semantic_id: item for item in REQUIRED_SOURCE_ITEMS}
    item = items[TEST_PROTECTIVE_IMPEDANCE]

    assert (item.expected_clause, item.expected_output_kind) == ("5.2.3.6", "procedure")
    assert item.expected_table is None
    assert item.consumer_issue_ids == (37,)


def test_a_package_predating_the_protective_impedance_test_is_blocked_by_name() -> None:
    """The required set grows, so an approved package built before it is incomplete."""
    draft = _draft()
    status = {status.semantic_id: status for status in inventory_report(draft)}[
        TEST_PROTECTIVE_IMPEDANCE
    ]

    assert status.located
    assert not status.deferred
    assert not (status.extracted or status.typed or status.approved)
    assert TEST_PROTECTIVE_IMPEDANCE in {
        item.semantic_id for item in missing_inventory_items(draft)
    }
    with pytest.raises(ApprovalError, match="required inventory item"):
        _require_complete_inventory(draft)
