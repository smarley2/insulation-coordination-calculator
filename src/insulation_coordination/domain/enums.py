from enum import StrEnum


class InsulationType(StrEnum):
    FUNCTIONAL = "functional"
    BASIC = "basic"
    SUPPLEMENTARY = "supplementary"
    REINFORCED = "reinforced"


class Provenance(StrEnum):
    PROJECT_DEFAULT = "project_default"
    PAIR_OVERRIDE = "pair_override"
    #: Derived from the project's supply configurations rather than entered by anyone. Kept
    #: apart from the two entered provenances so a reviewer reading an effective input can
    #: tell a value the application worked out from one a user took responsibility for.
    DERIVED_SUPPLY = "derived_supply"


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


class NetClassType(StrEnum):
    CIRCUIT = "circuit"
    PE_BONDED_CONDUCTIVE_PART = "pe_bonded_conductive_part"
    ACCESSIBLE_CONDUCTIVE_PART = "accessible_conductive_part"
    ACCESSIBLE_INSULATING_SURFACE = "accessible_insulating_surface"


class CircuitSourceRelationship(StrEnum):
    MAINS_CONNECTED = "mains_connected"
    NON_MAINS_EXTERNAL = "non_mains_external"
    INTERNALLY_GENERATED = "internally_generated"


class ConnectionExposure(StrEnum):
    INTERNAL_ONLY = "internal_only"
    EXTERNAL_LOCAL_PORT_OR_CABLE = "external_local_port_or_cable"
    LONG_OUTDOOR_LINE = "long_outdoor_line"


class DecisiveVoltageClass(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    DVC_AS = "dvc_as"
    DVC_B = "dvc_b"
    DVC_C = "dvc_c"


class ReviewState(StrEnum):
    NEEDS_REVIEW = "needs_review"
    USER_CONFIRMED = "user_confirmed"


class BarrierVerificationStatus(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    NO_GALVANIC_ISOLATION = "no_galvanic_isolation"
    VERIFIED_GALVANIC_ISOLATION = "verified_galvanic_isolation"


class VerificationMethod(StrEnum):
    TEST = "test"
    CALCULATION = "calculation"
    SIMULATION = "simulation"
    DOCUMENT_REVIEW = "document_review"
