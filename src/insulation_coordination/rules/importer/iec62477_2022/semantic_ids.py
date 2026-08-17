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
TEST_MAINS_DIELECTRIC_VALUES = "iec62477_2022.test.mains_dielectric_values"
TEST_NON_MAINS_DIELECTRIC_VALUES = "iec62477_2022.test.non_mains_dielectric_values"
TEST_PARTIAL_DISCHARGE = "iec62477_2022.test.partial_discharge"
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
        ALTITUDE_CLEARANCE_CORRECTION,
        ALTITUDE_TEST_VOLTAGE_CORRECTION,
        HIGH_FREQUENCY_APPLICABILITY,
        HIGH_FREQUENCY_BAND_FACTOR,
        TEST_IMPULSE_PROCEDURE,
        TEST_IMPULSE_SELECTION,
        TEST_MAINS_DIELECTRIC_VALUES,
        TEST_NON_MAINS_DIELECTRIC_VALUES,
        TEST_PARTIAL_DISCHARGE,
        TEST_WORKING_VOLTAGE_DETERMINATION,
        TEST_INTERNAL_SPD_MONITORING,
        TEST_PRECONDITIONING,
        TEST_ACCESSIBLE_SURFACE_FOIL,
        TEST_ASSEMBLED_ROUTINE_EXEMPTION,
    }
)
