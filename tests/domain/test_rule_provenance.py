"""Resolving guidance's named rules to package sources, and saying so when it cannot.

No IEC value or wording appears here: the fixture package's source references are invented
locators.
"""

from __future__ import annotations

from insulation_coordination.domain.rule_provenance import (
    citation,
    referenced_rule_ids,
    rule_provenance,
)
from insulation_coordination.domain.rules import SourceReference
from tests.fixtures.synthetic_rules import synthetic_dvc_rule_package, synthetic_rule_package


def test_referenced_rule_ids_finds_each_id_once_in_the_order_it_is_named() -> None:
    text = (
        "This feeds iec62477_2022.supply.system_voltage_resolution and then "
        "iec62477_2022.dvc.voltage_limits, and later "
        "iec62477_2022.supply.system_voltage_resolution again."
    )
    assert referenced_rule_ids(text) == (
        "iec62477_2022.supply.system_voltage_resolution",
        "iec62477_2022.dvc.voltage_limits",
    )


def test_a_sentence_ending_id_does_not_swallow_the_full_stop() -> None:
    assert referenced_rule_ids("evaluated by iec62477_2022.dvc.voltage_limits.") == (
        "iec62477_2022.dvc.voltage_limits",
    )


def test_prose_naming_no_rule_resolves_to_nothing() -> None:
    assert referenced_rule_ids("A chassis panel carries no voltage of its own.") == ()
    assert rule_provenance(synthetic_dvc_rule_package(), "No rule named here.") == ()


def test_a_named_rule_the_package_carries_resolves_to_its_source() -> None:
    text = "decided by iec62477_2022.dvc.voltage_limits"

    (entry,) = rule_provenance(synthetic_dvc_rule_package(), text)

    assert entry.rule_id == "iec62477_2022.dvc.voltage_limits"
    assert entry.available is True
    assert entry.source is not None
    assert entry.source.standard == "IEC 62477-1"


def test_a_named_rule_the_package_lacks_resolves_to_no_source_rather_than_a_guess() -> None:
    text = "decided by iec62477_2022.dvc.voltage_limits"

    (entry,) = rule_provenance(synthetic_rule_package(), text)

    assert entry.available is False
    assert entry.source is None


def test_no_package_resolves_every_named_rule_to_no_source() -> None:
    text = "iec62477_2022.dvc.voltage_limits and iec62477_2022.supply.tov_by_system_voltage"

    entries = rule_provenance(None, text)

    assert [entry.rule_id for entry in entries] == list(referenced_rule_ids(text))
    assert all(entry.source is None for entry in entries)


def test_citation_names_only_the_locating_fields_it_has() -> None:
    source = SourceReference(
        document_id="synthetic",
        standard="IEC 62477-1",
        edition="2022",
        clause="synthetic-clause",
        table="synthetic-table",
        page=7,
    )

    assert citation(source) == "IEC 62477-1 2022, Table synthetic-table, clause synthetic-clause, p.7"


def test_citation_of_nothing_is_empty() -> None:
    assert citation(None) == ""
