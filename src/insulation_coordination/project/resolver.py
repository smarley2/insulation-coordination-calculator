from insulation_coordination.domain.enums import Provenance
from insulation_coordination.domain.project import (
    EffectiveCase,
    EffectiveValue,
    OverrideValue,
    PairCase,
    ProjectDefaults,
)


def _resolve[T](default: T | None, override: OverrideValue[T]) -> EffectiveValue[T | None]:
    if override.is_override:
        assert override.value is not None
        return EffectiveValue(value=override.value, provenance=Provenance.PAIR_OVERRIDE)
    return EffectiveValue(value=default, provenance=Provenance.PROJECT_DEFAULT)


def resolve_effective_case(defaults: ProjectDefaults, pair: PairCase) -> EffectiveCase:
    return EffectiveCase(
        id=pair.id,
        key=pair.key,
        net_a=pair.net_a,
        net_b=pair.net_b,
        voltages=pair.voltages,
        frequency_hz=_resolve(defaults.frequency_hz, pair.frequency_hz),
        impulse_v=_resolve(defaults.impulse_v, pair.impulse_v),
        insulation_type=_resolve(defaults.insulation_type, pair.insulation_type),
        field_condition=_resolve(defaults.field_condition, pair.field_condition),
        electrode_radius_mm=_resolve(defaults.electrode_radius_mm, pair.electrode_radius_mm),
        altitude_m=_resolve(defaults.altitude_m, pair.altitude_m),
        pollution_degree=_resolve(defaults.pollution_degree, pair.pollution_degree),
        construction_type=_resolve(defaults.construction_type, pair.construction_type),
        cti_or_material_group=_resolve(defaults.cti_or_material_group, pair.cti_or_material_group),
        conventional_construction_assumptions=_resolve(
            defaults.conventional_construction_assumptions,
            pair.conventional_construction_assumptions,
        ),
    )
