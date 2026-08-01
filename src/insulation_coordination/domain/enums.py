from enum import StrEnum


class InsulationType(StrEnum):
    FUNCTIONAL = "functional"
    BASIC = "basic"
    SUPPLEMENTARY = "supplementary"
    REINFORCED = "reinforced"


class Provenance(StrEnum):
    PROJECT_DEFAULT = "project_default"
    PAIR_OVERRIDE = "pair_override"


class FieldCondition(StrEnum):
    INHOMOGENEOUS = "inhomogeneous"
    HOMOGENEOUS = "homogeneous"
    APPROXIMATELY_HOMOGENEOUS = "approximately_homogeneous"


class ConstructionType(StrEnum):
    PRINTED_WIRING = "printed_wiring"
    OTHER = "other"


class Applicability(StrEnum):
    BLANK = "blank"
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
