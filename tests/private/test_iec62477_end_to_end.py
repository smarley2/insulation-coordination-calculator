"""Issue #34's Definition of Done, demonstrated on the licensed documents.

Extract all three PDFs, resolve every review item, review every curve variant, approve,
export a ``.icrules`` archive, re-import it, query every required semantic ID, and execute
one representative request per consumer issue.

This is the first test to round-trip a package carrying procedures and comparison-only
grids. Assertions stay on identifiers, counts, and evaluation status: no value, heading, or
wording from a source table or clause is named here. A request's inputs are read from the
reviewed rule itself rather than written down, which is also the only way a request in this
file can be a question the source actually settles.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import (
    DecisionRule,
    Matcher,
    RulePackage,
)
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.iec62477_2022.inventory import (
    REQUIRED_SOURCE_ITEMS,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.procedures import (
    PRECONDITIONING_APPLICABILITY_ID,
    PRECONDITIONING_ELECTRICAL_ID,
    PRECONDITIONING_MATERIAL_ID,
)

pytestmark = pytest.mark.private_standard


def _rule_ids(package: RulePackage) -> frozenset[str]:
    return frozenset(
        rule.id
        for rule in (
            *package.tables,
            *package.formulas,
            *package.decisions,
            *package.procedures,
            *package.guidance,
            *package.curves,
        )
    )


def _covers(candidate: str, semantic_id: str) -> bool:
    return candidate == semantic_id or candidate.startswith(f"{semantic_id}.")


def _request_settled_by(rule: DecisionRule, row_index: int = 0) -> dict[str, Decimal | str | bool]:
    """A request the reviewed rule's own row answers, built from that row's matchers.

    Writing the inputs out would either copy source conditions into this file or invent a
    combination the source never settles. Reading them off the row does neither.
    """
    matched: dict[str, Matcher] = {
        matcher.input: matcher for matcher in rule.rows[row_index].matchers
    }
    request: dict[str, Decimal | str | bool] = {}
    for declared in rule.inputs:
        matcher = matched.get(declared.name)
        if matcher is not None and matcher.boolean is not None:
            request[declared.name] = matcher.boolean
        elif matcher is not None and matcher.values:
            request[declared.name] = matcher.values[0]
        elif matcher is not None and matcher.minimum is not None:
            request[declared.name] = matcher.minimum
        elif declared.kind == "categorical":
            request[declared.name] = declared.allowed_values[0]
        elif declared.kind == "boolean":
            request[declared.name] = True
        else:
            request[declared.name] = Decimal(1)
    return request


def test_every_required_semantic_id_is_queryable_after_a_round_trip(
    licensed_package: RulePackage,
) -> None:
    """The whole checklist survives export and re-import, by identifier.

    A required item is queryable when the reloaded package carries a rule under its
    identifier or one of its routes. Nothing here reads a value: what Issue #34 promises its
    consumers is that they can ask for these by stable ID.
    """
    package = licensed_package
    available = _rule_ids(package)

    assert len(REQUIRED_SOURCE_ITEMS) == 29
    for item in REQUIRED_SOURCE_ITEMS:
        assert any(_covers(candidate, item.semantic_id) for candidate in available), (
            item.semantic_id
        )


def test_the_band_factor_answers_a_frequency_and_refuses_one_it_does_not_cover(
    licensed_package: RulePackage,
) -> None:
    """Issue #72's promise on the licensed document: a frequency in, a factor or nothing out.

    Every quantity is read off the reviewed rule, so this file states neither a boundary nor
    a factor. The frequency that must answer nothing is one hertz, far below any band the
    annex declares and not a boundary of one.
    """
    package = licensed_package
    rule = next(item for item in package.decisions if item.id == ids.HIGH_FREQUENCY_BAND_FACTOR)

    assert rule.exhaustive is False
    bands = [matcher for row in rule.rows for matcher in row.matchers if matcher.op == "range"]
    assert len(bands) == len(rule.rows)
    assert all(matcher.minimum is not None and matcher.maximum is not None for matcher in bands)

    for index, band in enumerate(bands):
        assert band.minimum is not None and band.maximum is not None
        inside = (band.minimum + band.maximum) / 2
        result = evaluate_decision(rule, {"working_voltage_frequency_hz": inside})
        assert result.status == "matched"
        assert result.matched_row == index
        assert [value.numeric for value in result.values] == [
            value.numeric for value in rule.rows[index].values
        ]

    outside = evaluate_decision(rule, {"working_voltage_frequency_hz": Decimal(1)})
    assert outside.status == "no_match"
    assert outside.values == ()


def test_the_archive_carries_the_procedures_and_the_preconditioning_routes(
    licensed_package: RulePackage,
) -> None:
    """Procedures had never been through the archive layer before this slice.

    Both preconditioning routes must arrive, with their steps and their gate, because the
    package now answers "which preconditioning applies" with a rule identifier.
    """
    package = licensed_package
    procedures = {rule.id: rule for rule in package.procedures}

    assert {PRECONDITIONING_ELECTRICAL_ID, PRECONDITIONING_MATERIAL_ID} <= set(procedures)
    for route in (PRECONDITIONING_ELECTRICAL_ID, PRECONDITIONING_MATERIAL_ID):
        assert procedures[route].procedure_steps
        assert procedures[route].applicability_rule_id == PRECONDITIONING_APPLICABILITY_ID
    assert PRECONDITIONING_APPLICABILITY_ID in {rule.id for rule in package.decisions}


def test_one_representative_request_per_consumer_issue(
    licensed_package: RulePackage,
) -> None:
    """#35 DVC guidance, #36 an impulse and TOV derivation, #37 a test-procedure lookup."""

    package = licensed_package
    decisions = {rule.id: rule for rule in package.decisions}
    tables = {rule.id: rule for rule in package.tables}
    procedures = {rule.id: rule for rule in package.procedures}

    # #35: which decisive voltage class a supply falls in, and what protection it calls for.
    for semantic_id in (ids.DVC_VOLTAGE_LIMITS, ids.DVC_PROTECTION_MATRIX):
        rule = decisions[semantic_id]
        result = evaluate_decision(rule, _request_settled_by(rule))
        assert result.status == "matched", semantic_id
        assert result.values

    # #36: the impulse withstand voltage and the temporary overvoltage for one system
    # voltage, read at the coordinate the reviewed table's own axes declare.
    # Both items are split into an AC and a DC route, so the request names the route.
    impulse = tables[f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac"]
    tov = tables[f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac"]
    for table in (impulse, tov):
        assert table.row_axis.values and table.column_axis.values
        cell = next(item for item in table.cells if (item.row, item.column) == (0, 0))
        assert cell.unit == table.unit
        assert cell.value > 0

    # #37: which preconditioning a routine electrical test performs, and the steps it names.
    gate = decisions[PRECONDITIONING_APPLICABILITY_ID]
    answer = evaluate_decision(
        gate, {"test_context": "electrical_test", "test_purpose": "type_test"}
    )
    assert answer.status == "matched"
    selected = {value.name: value for value in answer.values}
    assert selected["preconditioning_required"].boolean is True
    route = selected["preconditioning_procedure_rule_id"].categorical
    assert route == PRECONDITIONING_ELECTRICAL_ID
    assert procedures[route].procedure_steps
    # And the procedure a Table 26 impulse test performs, looked up by identifier.
    impulse_procedures = tuple(
        rule for rule in package.procedures if _covers(rule.id, ids.TEST_IMPULSE_PROCEDURE)
    )
    assert impulse_procedures
    assert all(rule.procedure_steps for rule in impulse_procedures)
