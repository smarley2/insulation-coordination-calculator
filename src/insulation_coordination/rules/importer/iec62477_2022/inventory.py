"""The authoritative checklist of IEC 62477-1:2022 content the calculator requires.

Extraction targets, review status, package completeness, and the private end-to-end
tests all derive from this tuple. Completeness is never computed by counting tables or
matching human-readable titles.

Prose-derived items carry no locator here. Issue #34 names them by description rather
than clause number, and a clause number that has not been verified against the document
would be a guess. Their locator lands with their extraction recipe.
"""

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import Identifier, ReferenceText, RuleKind
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

STANDARD = "IEC 62477-1"
EDITION = "2022"
#: The recipe whose document this inventory describes.
RECIPE_ID = "iec62477-1-2022"


class RequiredSourceItem(FrozenModel):
    semantic_id: Identifier
    standard: Identifier
    edition: Identifier
    expected_clause: ReferenceText | None = None
    expected_table: ReferenceText | None = None
    expected_figure: ReferenceText | None = None
    expected_output_kind: RuleKind
    required: bool = True
    consumer_issue_ids: tuple[int, ...]


def _item(
    semantic_id: str,
    kind: RuleKind,
    consumers: tuple[int, ...],
    *,
    table: str | None = None,
    clause: str | None = None,
) -> RequiredSourceItem:
    return RequiredSourceItem(
        semantic_id=semantic_id,
        standard=STANDARD,
        edition=EDITION,
        expected_clause=clause,
        expected_table=table,
        expected_output_kind=kind,
        consumer_issue_ids=consumers,
    )


#: Required items whose extraction recipes are not written yet, so completeness reports
#: them as deferred instead of missing and approval does not block a package on work that
#: has not started. These are Issue #34's Slice E content -- Tables 26 to 30 and the
#: remaining verification procedures. The set is expected to be empty when Slice E closes,
#: and a test asserts every member is a required inventory item so it cannot hide a
#: identifier that does not exist.
DEFERRED_SEMANTIC_IDS: frozenset[str] = frozenset(
    {
        ids.TEST_IMPULSE_SELECTION,
        ids.TEST_MAINS_DIELECTRIC_VALUES,
        ids.TEST_NON_MAINS_DIELECTRIC_VALUES,
        ids.TEST_PARTIAL_DISCHARGE,
        ids.TEST_WORKING_VOLTAGE_DETERMINATION,
        ids.TEST_INTERNAL_SPD_MONITORING,
        ids.TEST_PRECONDITIONING,
        ids.TEST_ACCESSIBLE_SURFACE_FOIL,
        ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION,
    }
)

REQUIRED_SOURCE_ITEMS: tuple[RequiredSourceItem, ...] = (
    _item(ids.DVC_VOLTAGE_LIMITS, "decision", (35, 37), table="Table 2"),
    _item(ids.DVC_PROTECTION_MATRIX, "decision", (35, 37), table="Table 3"),
    _item(ids.DVC_FAULT_TIME_VOLTAGE, "curve", (35, 37)),
    _item(ids.DVC_FAULT_APPLICABILITY, "decision", (35, 37)),
    _item(ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, "decision", (36,)),
    _item(ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC, "table", (36,), table="Table 7"),
    _item(ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE, "table", (36, 37), table="Table 7"),
    _item(ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION, "decision", (36,)),
    _item(ids.SUPPLY_VERIFIED_BARRIER_TRANSFER, "decision", (36,)),
    _item(ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS, "decision", (36, 37)),
    _item(ids.SUPPLY_HF_TRANSFORMER_ATTENUATION, "decision", (36,)),
    _item(ids.CLEARANCE_REQUIREMENTS, "table", (36,), table="Table 8"),
    _item(ids.CREEPAGE_REQUIREMENTS, "table", (36,), table="Table 9"),
    _item(
        ids.ALTITUDE_TEST_VOLTAGE_CORRECTION, "table", (36, 37), table="Table E.1"
    ),
    _item(
        ids.HIGH_FREQUENCY_APPLICABILITY, "decision", (36, 37), clause="Annex F"
    ),
    _item(ids.TEST_IMPULSE_PROCEDURE, "procedure", (37,), table="Table 26"),
    _item(ids.TEST_IMPULSE_SELECTION, "decision", (37,), table="Table 27"),
    _item(ids.TEST_MAINS_DIELECTRIC_VALUES, "table", (37,), table="Table 28"),
    _item(ids.TEST_NON_MAINS_DIELECTRIC_VALUES, "table", (37,), table="Table 29"),
    _item(ids.TEST_PARTIAL_DISCHARGE, "procedure", (37,), table="Table 30"),
    _item(ids.TEST_WORKING_VOLTAGE_DETERMINATION, "procedure", (37,)),
    _item(ids.TEST_INTERNAL_SPD_MONITORING, "procedure", (37,)),
    _item(ids.TEST_PRECONDITIONING, "procedure", (37,)),
    _item(ids.TEST_ACCESSIBLE_SURFACE_FOIL, "procedure", (37,)),
    _item(ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION, "decision", (37,)),
)
