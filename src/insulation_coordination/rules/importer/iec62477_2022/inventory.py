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


#: Required items whose extraction recipes are not written yet, so completeness reports them
#: as deferred instead of missing and approval does not block a package on work that has not
#: started. Empty since Slice E closed: every required item now has a recipe, so completeness
#: reports a missing item as missing. The mechanism stays because it is how the next standard
#: is landed a slice at a time, and a test asserts every member is a required inventory item
#: so it cannot hide an identifier that does not exist.
DEFERRED_SEMANTIC_IDS: frozenset[str] = frozenset()

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
    _item(ids.CLEARANCE_REINFORCED_TREATMENT, "decision", (36,), clause="4.4.7.4.2"),
    _item(ids.CREEPAGE_REINFORCED_TREATMENT, "decision", (36,), clause="4.4.7.5.2"),
    _item(ids.ALTITUDE_CLEARANCE_CORRECTION, "table", (36,), table="Table E.1"),
    _item(ids.ALTITUDE_TEST_VOLTAGE_CORRECTION, "table", (37,), table="Table E.2"),
    _item(ids.HIGH_FREQUENCY_APPLICABILITY, "decision", (36, 37), clause="Annex F"),
    _item(ids.HIGH_FREQUENCY_BAND_FACTOR, "decision", (36,), table="Table F.2", clause="F.2.3"),
    _item(ids.TEST_IMPULSE_PROCEDURE, "procedure", (37,), table="Table 26"),
    _item(ids.TEST_IMPULSE_SELECTION, "table", (37,), table="Table 27"),
    _item(ids.TEST_IMPULSE_ALTERNATIVE, "procedure", (37,), clause="5.2.3.3"),
    _item(ids.TEST_MAINS_DIELECTRIC_VALUES, "table", (37,), table="Table 28"),
    _item(ids.TEST_NON_MAINS_DIELECTRIC_VALUES, "table", (37,), table="Table 29"),
    #: The AC or DC voltage test's own subclauses. Tables 28 and 29 above carry only its
    #: values; without these four the package states no duration, no electrode topology, no
    #: column-selection rule, no disconnection obligation and no acceptance criterion, which
    #: is why every planned dielectric application recorded a missing duration.
    _item(ids.TEST_DIELECTRIC_DISCONNECTION, "procedure", (37,), clause="5.2.3.4.3"),
    _item(ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION, "decision", (37,), clause="5.2.3.4.4"),
    _item(ids.TEST_DIELECTRIC_APPLICATION_DURATION, "procedure", (37,), clause="5.2.3.4.5"),
    _item(ids.TEST_DIELECTRIC_ACCEPTANCE, "decision", (37,), clause="5.2.3.4.6"),
    _item(
        ids.TEST_PARTIAL_DISCHARGE,
        "procedure",
        (37,),
        table="Table 30",
        clause="4.4.7.10.3",
    ),
    #: Table 30 above is the procedure. This is the subclause that decides whether a solid
    #: insulation owes that procedure at all, and how the test is classified once it does --
    #: two conditions on quantities of the pair, which no table states.
    _item(
        ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE,
        "decision",
        (37,),
        clause="4.4.7.10.3",
    ),
    _item(ids.TEST_WORKING_VOLTAGE_DETERMINATION, "procedure", (37,)),
    _item(ids.TEST_INTERNAL_SPD_MONITORING, "procedure", (37,)),
    _item(ids.TEST_PRECONDITIONING, "procedure", (37,)),
    _item(ids.TEST_ACCESSIBLE_SURFACE_FOIL, "procedure", (37,)),
    _item(ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION, "decision", (37,)),
)
