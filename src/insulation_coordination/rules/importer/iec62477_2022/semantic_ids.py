"""Stable semantic identifiers for IEC 62477-1:2022 rules.

These identifiers are the contract between the importer and the runtime consumers in
issues #35, #36 and #37. They are immutable once released in an approved package: a
changed interpretation creates a new identifier, never a redefinition of an old one.

This module holds identifiers only. No source value, heading, or wording belongs here.
"""

DVC_VOLTAGE_LIMITS = "iec62477_2022.dvc.voltage_limits"
DVC_PROTECTION_MATRIX = "iec62477_2022.dvc.protection_matrix"
DVC_FAULT_TIME_VOLTAGE = "iec62477_2022.dvc.fault_time_voltage"
DVC_FAULT_APPLICABILITY = "iec62477_2022.dvc.fault_applicability"

SUPPLY_SYSTEM_VOLTAGE_RESOLUTION = "iec62477_2022.supply.system_voltage_resolution"
SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC = "iec62477_2022.supply.impulse_by_system_voltage_ovc"
SUPPLY_TOV_BY_SYSTEM_VOLTAGE = "iec62477_2022.supply.tov_by_system_voltage"
SUPPLY_MULTIPLE_SOURCE_PROPAGATION = "iec62477_2022.supply.multiple_source_propagation"
SUPPLY_VERIFIED_BARRIER_TRANSFER = "iec62477_2022.supply.verified_barrier_transfer"
SUPPLY_SPD_REDUCTION_REQUIREMENTS = "iec62477_2022.supply.spd_reduction_requirements"
SUPPLY_HF_TRANSFORMER_ATTENUATION = "iec62477_2022.supply.hf_transformer_attenuation"

CLEARANCE_REQUIREMENTS = "iec62477_2022.clearance.requirements"
CREEPAGE_REQUIREMENTS = "iec62477_2022.creepage.requirements"
#: How a spacing for the stronger insulation is dimensioned from the weaker one's. One
#: identifier per spacing kind, and siblings rather than routes of the requirement tables
#: above for the reason the two Annex E identifiers are siblings: a treatment is a separate
#: normative statement about a requirement, not a route of resolving one. Each names a
#: treatment rather than its whole subclause, the way two routes already split 4.4.7.2.5.
CLEARANCE_REINFORCED_TREATMENT = "iec62477_2022.clearance.reinforced_treatment"
CREEPAGE_REINFORCED_TREATMENT = "iec62477_2022.creepage.reinforced_treatment"
#: Annex E's two tables do two different jobs and get one identifier each (#52): E.1's factor
#: corrects clearances for dimensioning, E.2's values correct test voltages for the altitude
#: of the testing laboratory. Neither is a route of the other, so neither carries a suffix.
ALTITUDE_CLEARANCE_CORRECTION = "iec62477_2022.altitude.clearance_correction"
ALTITUDE_TEST_VOLTAGE_CORRECTION = "iec62477_2022.altitude.test_voltage_correction"
HIGH_FREQUENCY_APPLICABILITY = "iec62477_2022.high_frequency.applicability"
#: The annex's own band grid resolves a factor from a frequency (#72), which is a different
#: question from whether the annex applies at all, so it gets its own identifier rather than a
#: route under the applicability one. A sibling for the same reason the two Annex E identifiers
#: are siblings: neither is a route of the other.
HIGH_FREQUENCY_BAND_FACTOR = "iec62477_2022.high_frequency.band_factor"

TEST_IMPULSE_PROCEDURE = "iec62477_2022.test.impulse_procedure"
TEST_IMPULSE_SELECTION = "iec62477_2022.test.impulse_selection"
#: The test a source permits *instead of* the impulse withstand test. Its own identifier rather
#: than a route of the procedure above, for the reason the two reinforced treatments are siblings
#: of their requirement tables: an alternative is a separate normative statement about a test, not
#: a route of performing it -- and the engineer's choice between them has to name one of the two.
TEST_IMPULSE_ALTERNATIVE = "iec62477_2022.test.impulse_alternative"
TEST_MAINS_DIELECTRIC_VALUES = "iec62477_2022.test.mains_dielectric_values"
TEST_NON_MAINS_DIELECTRIC_VALUES = "iec62477_2022.test.non_mains_dielectric_values"
#: The body of the AC or DC voltage test, which its two value tables above do not state. Four
#: identifiers rather than one, because the source states four separately consumable things and
#: a consumer asks for exactly one of them: what is disconnected and restored before the voltage
#: is applied, which electrodes an application uses and which column of the value tables it
#: reads, how long the voltage is held, and what counts as a pass. Siblings of the two value
#: tables for the reason the reinforced treatments are siblings of their requirement tables:
#: none of the four is a route of resolving a tabulated value. Each names its role rather than
#: its subclause, so a renumbered edition does not rename the contract.
TEST_DIELECTRIC_DISCONNECTION = "iec62477_2022.test.dielectric_disconnection"
TEST_DIELECTRIC_TOPOLOGY_SELECTION = "iec62477_2022.test.dielectric_topology_selection"
TEST_DIELECTRIC_APPLICATION_DURATION = "iec62477_2022.test.dielectric_application_duration"
TEST_DIELECTRIC_ACCEPTANCE = "iec62477_2022.test.dielectric_acceptance"
TEST_PARTIAL_DISCHARGE = "iec62477_2022.test.partial_discharge"
#: When a solid insulation owes the partial-discharge test in addition to the two tests its
#: subclause asks for, and how that test is then classified. A sibling of the procedure above
#: rather than a route of it, for the reason the permitted impulse alternative is a sibling: a
#: statement about when a test is owed is not a way of performing it. Named for the insulation
#: the obligation attaches to rather than for its subclause, so a renumbered edition does not
#: rename the contract -- and deliberately not under the ``partial_discharge`` stem, which
#: already carries the procedure's own applicability route and whose raw artifact id this one
#: would otherwise be a prefix of.
TEST_SOLID_INSULATION_PARTIAL_DISCHARGE = "iec62477_2022.test.solid_insulation_partial_discharge"
TEST_WORKING_VOLTAGE_DETERMINATION = "iec62477_2022.test.working_voltage_determination"
TEST_INTERNAL_SPD_MONITORING = "iec62477_2022.test.internal_spd_monitoring"
TEST_PRECONDITIONING = "iec62477_2022.test.preconditioning"
TEST_ACCESSIBLE_SURFACE_FOIL = "iec62477_2022.test.accessible_surface_foil"
TEST_ASSEMBLED_ROUTINE_EXEMPTION = "iec62477_2022.test.assembled_routine_exemption"

REQUIRED_SEMANTIC_IDS: frozenset[str] = frozenset(
    {
        DVC_VOLTAGE_LIMITS,
        DVC_PROTECTION_MATRIX,
        DVC_FAULT_TIME_VOLTAGE,
        DVC_FAULT_APPLICABILITY,
        SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
        SUPPLY_TOV_BY_SYSTEM_VOLTAGE,
        SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        SUPPLY_VERIFIED_BARRIER_TRANSFER,
        SUPPLY_SPD_REDUCTION_REQUIREMENTS,
        SUPPLY_HF_TRANSFORMER_ATTENUATION,
        CLEARANCE_REQUIREMENTS,
        CREEPAGE_REQUIREMENTS,
        CLEARANCE_REINFORCED_TREATMENT,
        CREEPAGE_REINFORCED_TREATMENT,
        ALTITUDE_CLEARANCE_CORRECTION,
        ALTITUDE_TEST_VOLTAGE_CORRECTION,
        HIGH_FREQUENCY_APPLICABILITY,
        HIGH_FREQUENCY_BAND_FACTOR,
        TEST_IMPULSE_PROCEDURE,
        TEST_IMPULSE_SELECTION,
        TEST_IMPULSE_ALTERNATIVE,
        TEST_MAINS_DIELECTRIC_VALUES,
        TEST_NON_MAINS_DIELECTRIC_VALUES,
        TEST_DIELECTRIC_DISCONNECTION,
        TEST_DIELECTRIC_TOPOLOGY_SELECTION,
        TEST_DIELECTRIC_APPLICATION_DURATION,
        TEST_DIELECTRIC_ACCEPTANCE,
        TEST_PARTIAL_DISCHARGE,
        TEST_SOLID_INSULATION_PARTIAL_DISCHARGE,
        TEST_WORKING_VOLTAGE_DETERMINATION,
        TEST_INTERNAL_SPD_MONITORING,
        TEST_PRECONDITIONING,
        TEST_ACCESSIBLE_SURFACE_FOIL,
        TEST_ASSEMBLED_ROUTINE_EXEMPTION,
    }
)
