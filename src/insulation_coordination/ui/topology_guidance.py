"""Explanations behind the net-classification and barrier-status dropdowns.

Classifying a net or a barrier is a sequence of closed choices - which of a few
IEC 62477-1 categories this net or this barrier falls into - and every choice has a
consequence somewhere else in the project: which rules apply to it, what a rule
package still needs from the user, or nothing at all. This module writes that
consequence down once per option, in the same registry the voltage-stress guidance
already uses (:mod:`insulation_coordination.ui.voltage_guidance`), so a dropdown
option and its explanation can never drift apart.

The text is this application's own engineering guidance. It paraphrases nothing
from a standard and quotes no clause of one. Where an option's consequence is a
matter the active rule package decides, this module names the semantic rule that
decides it instead of stating a number.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from insulation_coordination.domain.enums import (
    BarrierVerificationStatus,
    CircuitSourceRelationship,
    ConnectionExposure,
    DecisiveVoltageClass,
    NetClassType,
)
from insulation_coordination.ui.voltage_guidance import VoltageGuidance, register_guidance

#: This application's own statement of scope for the on-board-charger (OBC) worked
#: example: IEC 62477-1:2022 does not cover
#: EV/OBC equipment, so the OBC example is a topology illustration only, never a claim of
#: compliance. Kept as one constant so every place the OBC example appears - a guidance
#: example below, or the example project's own domain descriptions - carries the identical
#: wording rather than a paraphrase that could drift from it.
OBC_APPLICABILITY_WARNING = (
    "OBC is a topology example only. IEC 62477-1:2022 excludes electric-vehicle "
    "electrical equipment/systems; the applicable EV/OBC product standard takes "
    "precedence."
)


class TopologyGuidanceId(StrEnum):
    NET_TYPE_CIRCUIT = "net_type_circuit"
    NET_TYPE_PE_BONDED_CONDUCTIVE_PART = "net_type_pe_bonded_conductive_part"
    NET_TYPE_ACCESSIBLE_CONDUCTIVE_PART = "net_type_accessible_conductive_part"
    NET_TYPE_ACCESSIBLE_INSULATING_SURFACE = "net_type_accessible_insulating_surface"

    SOURCE_MAINS_CONNECTED = "source_mains_connected"
    SOURCE_NON_MAINS_EXTERNAL = "source_non_mains_external"
    SOURCE_INTERNALLY_GENERATED = "source_internally_generated"

    EXPOSURE_INTERNAL_ONLY = "exposure_internal_only"
    EXPOSURE_EXTERNAL_LOCAL_PORT_OR_CABLE = "exposure_external_local_port_or_cable"
    EXPOSURE_LONG_OUTDOOR_LINE = "exposure_long_outdoor_line"

    DVC_NOT_EVALUATED = "dvc_not_evaluated"
    # The "_topology" suffix is load-bearing, not decorative: DecisiveVoltageClass's own
    # raw values are "dvc_as" / "dvc_b" / "dvc_c" (domain.enums), and register_guidance
    # rejects a repeated string key across every registered id enum. An unsuffixed
    # member here would collide the moment another registry chose the same bare value.
    DVC_AS = "dvc_as_topology"
    DVC_B = "dvc_b_topology"
    DVC_C = "dvc_c_topology"

    GALVANIC_DOMAIN_ASSIGNMENT = "galvanic_domain_assignment"

    BARRIER_NOT_EVALUATED = "barrier_not_evaluated"
    BARRIER_NO_GALVANIC_ISOLATION = "barrier_no_galvanic_isolation"
    BARRIER_VERIFIED_GALVANIC_ISOLATION = "barrier_verified_galvanic_isolation"

    CLASSIFICATION_OVERVIEW = "classification_overview"


#: Which option of each classification enum maps to which guidance entry above.
#: Kept as one small mapping per enum rather than one combined mapping: several of
#: the underlying domain enums reuse the same raw value (both ``DecisiveVoltageClass``
#: and ``BarrierVerificationStatus`` have a ``not_evaluated`` member), and a single
#: mapping keyed across enum types would let one silently overwrite the other.
_NET_TYPE_GUIDANCE_IDS: Mapping[NetClassType, TopologyGuidanceId] = {
    NetClassType.CIRCUIT: TopologyGuidanceId.NET_TYPE_CIRCUIT,
    NetClassType.PE_BONDED_CONDUCTIVE_PART: TopologyGuidanceId.NET_TYPE_PE_BONDED_CONDUCTIVE_PART,
    NetClassType.ACCESSIBLE_CONDUCTIVE_PART: (
        TopologyGuidanceId.NET_TYPE_ACCESSIBLE_CONDUCTIVE_PART
    ),
    NetClassType.ACCESSIBLE_INSULATING_SURFACE: (
        TopologyGuidanceId.NET_TYPE_ACCESSIBLE_INSULATING_SURFACE
    ),
}
_SOURCE_GUIDANCE_IDS: Mapping[CircuitSourceRelationship, TopologyGuidanceId] = {
    CircuitSourceRelationship.MAINS_CONNECTED: TopologyGuidanceId.SOURCE_MAINS_CONNECTED,
    CircuitSourceRelationship.NON_MAINS_EXTERNAL: TopologyGuidanceId.SOURCE_NON_MAINS_EXTERNAL,
    CircuitSourceRelationship.INTERNALLY_GENERATED: (
        TopologyGuidanceId.SOURCE_INTERNALLY_GENERATED
    ),
}
_EXPOSURE_GUIDANCE_IDS: Mapping[ConnectionExposure, TopologyGuidanceId] = {
    ConnectionExposure.INTERNAL_ONLY: TopologyGuidanceId.EXPOSURE_INTERNAL_ONLY,
    ConnectionExposure.EXTERNAL_LOCAL_PORT_OR_CABLE: (
        TopologyGuidanceId.EXPOSURE_EXTERNAL_LOCAL_PORT_OR_CABLE
    ),
    ConnectionExposure.LONG_OUTDOOR_LINE: TopologyGuidanceId.EXPOSURE_LONG_OUTDOOR_LINE,
}
_DVC_GUIDANCE_IDS: Mapping[DecisiveVoltageClass, TopologyGuidanceId] = {
    DecisiveVoltageClass.NOT_EVALUATED: TopologyGuidanceId.DVC_NOT_EVALUATED,
    DecisiveVoltageClass.DVC_AS: TopologyGuidanceId.DVC_AS,
    DecisiveVoltageClass.DVC_B: TopologyGuidanceId.DVC_B,
    DecisiveVoltageClass.DVC_C: TopologyGuidanceId.DVC_C,
}
_BARRIER_GUIDANCE_IDS: Mapping[BarrierVerificationStatus, TopologyGuidanceId] = {
    BarrierVerificationStatus.NOT_EVALUATED: TopologyGuidanceId.BARRIER_NOT_EVALUATED,
    BarrierVerificationStatus.NO_GALVANIC_ISOLATION: (
        TopologyGuidanceId.BARRIER_NO_GALVANIC_ISOLATION
    ),
    BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION: (
        TopologyGuidanceId.BARRIER_VERIFIED_GALVANIC_ISOLATION
    ),
}


def guidance_id_for_net_type(value: NetClassType) -> TopologyGuidanceId:
    return _NET_TYPE_GUIDANCE_IDS[value]


def guidance_id_for_source_relationship(value: CircuitSourceRelationship) -> TopologyGuidanceId:
    return _SOURCE_GUIDANCE_IDS[value]


def guidance_id_for_connection_exposure(value: ConnectionExposure) -> TopologyGuidanceId:
    return _EXPOSURE_GUIDANCE_IDS[value]


def guidance_id_for_dvc(value: DecisiveVoltageClass) -> TopologyGuidanceId:
    return _DVC_GUIDANCE_IDS[value]


def guidance_id_for_barrier_status(value: BarrierVerificationStatus) -> TopologyGuidanceId:
    return _BARRIER_GUIDANCE_IDS[value]


register_guidance(
    VoltageGuidance(
        id=TopologyGuidanceId.NET_TYPE_CIRCUIT,
        title="circuit net class",
        short_text="A conductor set that carries an operating voltage of its own.",
        detailed_text=(
            "A circuit is a set of conductors that share a common voltage relative to "
            "the rest of the project and carry an operating voltage stress between "
            "themselves and every other net. Select it for windings, rails, buses, "
            "control signals, and any conductor pair a working voltage exists across.\n\n"
            "Do not select it for a conductive part that has no source of its own "
            "voltage - a chassis panel, a heatsink, or an insulating enclosure surface "
            "belongs in one of the other three classes, even when it is connected to "
            "protective earth.\n\n"
            "Marking a net as a circuit is what makes the source relationship, "
            "connection exposure, decisive voltage class, and galvanic domain fields "
            "apply to it; a rule package such as iec62477_2022.clearance.requirements "
            "and iec62477_2022.creepage.requirements only evaluates pairs that involve "
            "a circuit. It does not by itself set any of those four fields to a "
            "particular value - each is still answered on its own."
        ),
        examples=(
            "A DC bus rail.",
            "A PWM-switched motor phase output.",
            (
                "A wireless-power receiver coil and rectifier circuit, in its own galvanic "
                "domain from the primary side."
            ),
            (
                "A variable-speed drive's U/V/W motor-phase output, exposed through the "
                "external motor cable."
            ),
        ),
        common_mistakes=(
            "Classifying a heatsink or chassis panel as a circuit because it is conductive.",
            (
                "Leaving a genuine circuit net at its class default without visiting the "
                "other four fields."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.NET_TYPE_PE_BONDED_CONDUCTIVE_PART,
        title="PE-bonded conductive part",
        short_text="A conductive part bonded to protective earth, with no source of its own.",
        detailed_text=(
            "A conductive part - a frame, a bracket, a shield - that is bonded to "
            "protective earth and therefore held at earth potential rather than "
            "carrying a working voltage of its own. Select it for any accessible or "
            "internal metalwork whose potential is fixed by the bond rather than by a "
            "circuit.\n\n"
            "Do not select it for a part that is left floating, or for a part that "
            "itself carries a working voltage - those are a circuit, or an unbonded "
            "accessible conductive part.\n\n"
            "This class lets a rule package evaluate the pair between this part and "
            "every circuit net without asking for a source relationship, connection "
            "exposure, decisive voltage class, or galvanic domain - a bonded part "
            "answers none of them, since it has no source and joins no domain of its "
            "own. It does not decide how any other net is classified."
        ),
        examples=(
            "A metal enclosure bonded to the protective-earth terminal.",
            "A shield braid tied to chassis ground.",
        ),
        common_mistakes=(
            "Bonding a part to earth in the drawing but leaving its net class as circuit.",
            (
                "Assuming a PE-bonded part needs no further attention - the pairs it forms "
                "with every circuit still need clearance and creepage evaluated."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.NET_TYPE_ACCESSIBLE_CONDUCTIVE_PART,
        title="accessible conductive part",
        short_text="A touchable conductive part that is not bonded to protective earth.",
        detailed_text=(
            "A conductive part that a person can touch in normal use but that is not "
            "bonded to protective earth - an isolated metal knob, an ungrounded "
            "enclosure panel, a floating shield. Select it when the part is reachable "
            "and conductive, and its potential is not fixed by a PE bond.\n\n"
            "Do not select it for a part that is bonded to protective earth (use the "
            "PE-bonded class instead), or for a part nobody can touch in normal use.\n\n"
            "The distinction from a PE-bonded part matters because an unbonded "
            "accessible conductive part can float to a stressed potential that a "
            "bonded one cannot; the pairs it forms with a circuit are evaluated "
            "accordingly. It does not carry a source relationship, connection "
            "exposure, decisive voltage class, or galvanic domain of its own."
        ),
        examples=(
            "An isolated metal bezel on a front panel.",
            "A floating heatsink not tied to chassis.",
        ),
        common_mistakes=(
            ("Treating every touchable metal part as PE-bonded without checking the actual bond."),
            (
                "Leaving an accessible conductive part classified as a circuit because it "
                "was copied from one."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.NET_TYPE_ACCESSIBLE_INSULATING_SURFACE,
        title="accessible insulating surface",
        short_text="A touchable, non-conductive surface, evaluated for what is behind it.",
        detailed_text=(
            "A surface a person can touch in normal use that is not itself conductive "
            "- a plastic enclosure wall, a coated panel. Select it when what needs "
            "evaluating is the insulation between an internal circuit and the outside "
            "world, seen from the touchable surface rather than from a piece of "
            "metal.\n\n"
            "Do not select it for anything conductive; a conductive touchable part "
            "belongs in the accessible-conductive-part class instead.\n\n"
            "This class lets a rule package evaluate the pair between this surface and "
            "an internal circuit for clearance and creepage across the enclosure wall. "
            "It does not carry a source relationship, connection exposure, decisive "
            "voltage class, or galvanic domain of its own."
        ),
        examples=("The outer wall of a plastic enclosure.",),
        common_mistakes=(
            (
                "Classifying a coated metal part as insulating without checking whether "
                "the coating is relied on for insulation coordination."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.SOURCE_MAINS_CONNECTED,
        title="mains-connected source relationship",
        short_text="Connected to the AC or DC mains supply, directly or through passive parts.",
        detailed_text=(
            "Select this when the circuit's operating voltage derives from the mains "
            "supply the product is fed from - directly, or through fuses, filters, or "
            "other passive components that do not interrupt the galvanic connection to "
            "it. The circuit shares the mains supply's transient and temporary "
            "overvoltage exposure.\n\n"
            "Do not select it for a circuit that is separated from the mains by a "
            "transformer, an isolated converter stage, or any element that breaks the "
            "galvanic connection; that circuit is internally generated instead, even "
            "though the mains ultimately powers it.\n\n"
            "This answer feeds the rules that resolve a system voltage and overvoltage "
            "category from the supply (iec62477_2022.supply.system_voltage_resolution) "
            "and that size an impulse level from it "
            "(iec62477_2022.supply.impulse_by_system_voltage_ovc). It does not by "
            "itself set the decisive voltage class or the connection exposure - both "
            "are still answered separately."
        ),
        examples=(
            ("The primary side of an offline AC/DC converter, ahead of the isolation transformer."),
            "A DC bus fed straight from a rectified mains input.",
        ),
        common_mistakes=(
            (
                "Marking a circuit mains-connected because the product plugs into the "
                "wall, even though this particular circuit sits behind an isolating "
                "transformer."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.SOURCE_NON_MAINS_EXTERNAL,
        title="non-mains, externally sourced relationship",
        short_text="Sourced from outside the product, but not from the mains supply.",
        detailed_text=(
            "Select this when the circuit's operating voltage comes from outside the "
            "product's own enclosure, but from a source other than the mains supply - "
            "a vehicle battery bus, another cabinet's DC link, a field instrument "
            "loop. The circuit inherits whatever transient and temporary overvoltage "
            "that external source can deliver, which is not the same exposure a mains "
            "supply presents.\n\n"
            "Do not select it for a circuit generated entirely inside the product "
            "(internally generated) or for one fed from the mains (mains-connected).\n\n"
            "This answer feeds the same supply-resolution rules as the mains case "
            "(iec62477_2022.supply.system_voltage_resolution, "
            "iec62477_2022.supply.tov_by_system_voltage), resolved against the "
            "external source's own declared voltage rather than the mains. It does not "
            "set the connection exposure field, which is answered separately even for "
            "an externally sourced circuit."
        ),
        examples=(
            "A DC bus fed from an external battery pack through a cable.",
            "A field sensor loop powered from another cabinet.",
        ),
        common_mistakes=(
            (
                "Recording a battery-fed circuit as internally generated because the "
                "battery sits inside the same cabinet, when the battery is a separate "
                "external source."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.SOURCE_INTERNALLY_GENERATED,
        title="internally generated source relationship",
        short_text="Derived inside the product by a converter stage, transformer, or regulator.",
        detailed_text=(
            "Select this when the circuit's operating voltage is produced inside the "
            "product itself, by a converter stage, a transformer winding, or a "
            "regulator - and is not a direct, unbroken galvanic path back to the mains "
            "or to an external source. This is the default for a newly added net, on "
            "the assumption that most nets in a converter design are generated "
            "internally.\n\n"
            "Do not select it for a circuit whose voltage is the mains or an external "
            "source passed through with no isolating element in between.\n\n"
            "An internally generated circuit's exposure to the mains or an external "
            "source's transient and temporary overvoltage depends on what stands "
            "between it and that source - a transformer's attenuation "
            "(iec62477_2022.supply.hf_transformer_attenuation) or a verified barrier's "
            "transfer behaviour (iec62477_2022.supply.verified_barrier_transfer), not "
            "on this field alone. Recording the relationship correctly is what lets "
            "that later evaluation happen; it does not perform the evaluation itself."
        ),
        examples=(
            "The secondary side of an isolated DC/DC converter.",
            "A gate-drive supply generated by an auxiliary winding.",
        ),
        common_mistakes=(
            (
                "Leaving a mains-connected circuit at this default because nobody visited "
                "the field after adding the net."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.EXPOSURE_INTERNAL_ONLY,
        title="internal-only connection exposure",
        short_text="Reaches no connector, port, or cable leaving the enclosure.",
        detailed_text=(
            "Select this when the circuit is wired entirely inside the enclosure and "
            "never reaches a connector, terminal, or cable that a person or another "
            "piece of equipment could touch or connect to from outside. It sees no "
            "exposure beyond what the enclosure itself experiences.\n\n"
            "Do not select it for a circuit that terminates at any external connector "
            "or terminal block, even a short one - that is a local port or cable "
            "instead.\n\n"
            "This is the least exposed of the three options; it does not add any "
            "external-cable exposure ahead of what "
            "iec62477_2022.supply.impulse_by_system_voltage_ovc already resolves for "
            "the circuit's source. It does not decide the source relationship or the "
            "decisive voltage class."
        ),
        examples=(
            "A gate-drive signal routed only between two internal boards.",
            "An internal bus bar with no external terminal.",
        ),
        common_mistakes=(
            (
                "Marking a circuit internal-only because its connector is small, when the "
                "connector still exits the enclosure."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.EXPOSURE_EXTERNAL_LOCAL_PORT_OR_CABLE,
        title="external local port or cable exposure",
        short_text="Terminates at a connector or short cable leaving the enclosure, locally.",
        detailed_text=(
            "Select this when the circuit terminates at a connector, terminal, or "
            "cable that leaves the enclosure but stays within one installation - a "
            "short interconnect to an adjacent panel, a local sensor cable, a "
            "communication port on the same machine. It is more exposed than a purely "
            "internal net, but does not run the length of an outdoor line.\n\n"
            "Do not select it for a circuit with no external termination at all "
            "(internal only), or for one that runs a long outdoor or inter-building "
            "line, which carries materially more transient exposure.\n\n"
            "This answer contributes to the overvoltage-category resolution the active "
            "rule package performs on the circuit's supply "
            "(iec62477_2022.supply.impulse_by_system_voltage_ovc); it does not itself "
            "state which overvoltage category or impulse level results."
        ),
        examples=(
            "A CAN bus connector between two panels of the same machine.",
            "A local temperature-sensor cable a few metres long.",
            "A variable-speed drive's control/fieldbus connector, local to the same installation.",
        ),
        common_mistakes=(
            (
                "Treating every connector that exits the enclosure as a long outdoor line "
                "regardless of its actual run and environment."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.EXPOSURE_LONG_OUTDOOR_LINE,
        title="long outdoor line exposure",
        short_text="Runs a long outdoor, overhead, or inter-building line.",
        detailed_text=(
            "Select this when the circuit's external connection runs a long outdoor, "
            "overhead, or inter-building line - the kind of run that collects "
            "lightning-induced and switching transients well beyond what a short "
            "local cable sees.\n\n"
            "Do not select it for a cable that stays within one building or "
            "installation, even if it is long; use the local port or cable option for "
            "those.\n\n"
            "This is the most exposed of the three options and feeds the same "
            "overvoltage-category resolution as the other two "
            "(iec62477_2022.supply.impulse_by_system_voltage_ovc), pushing it toward a "
            "higher result rather than stating one directly. It does not by itself "
            "change the source relationship."
        ),
        examples=(
            "An outdoor sensor line running between two separate buildings.",
            "An overhead interconnect exposed to the weather.",
        ),
        common_mistakes=(
            (
                "Under-selecting a genuinely long outdoor run as a local port or cable "
                "because the connector itself looks ordinary."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.DVC_NOT_EVALUATED,
        title="DVC not evaluated",
        short_text="No decisive voltage class has been assigned yet; the answer is open.",
        detailed_text=(
            "The default state before anyone has assigned a decisive voltage class to "
            "this circuit. It means the classification is still open, not that the "
            "circuit has been examined and found to need no class.\n\n"
            "Do not leave it here once the circuit's classification review is "
            "otherwise complete - a rule package that evaluates DVC-dependent limits "
            "(iec62477_2022.dvc.voltage_limits, iec62477_2022.dvc.protection_matrix) "
            "has nothing to work from while this stands.\n\n"
            "It affects nothing on its own; it is a placeholder that other rules will "
            "refuse to proceed past, rather than a decision this application makes "
            "for you."
        ),
        examples=("A newly added circuit net, before anyone has reviewed its classification.",),
        common_mistakes=(
            (
                "Saving a project with every circuit still at 'not evaluated', expecting "
                "the class to be filled in automatically."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.DVC_AS,
        title="DVC A-s",
        short_text="The circuit belongs to decisive voltage class A-s.",
        detailed_text=(
            "Assign this class when the circuit meets the conditions the active rule "
            "package associates with decisive voltage class A-s. Which conditions "
            "those are, and what limits and protection requirements follow, is "
            "entirely the rule package's determination "
            "(iec62477_2022.dvc.voltage_limits, iec62477_2022.dvc.protection_matrix, "
            "iec62477_2022.dvc.fault_time_voltage); this field only records the "
            "choice, it does not compute it.\n\n"
            "Do not assign it from habit or by copying a sibling net's value - each "
            "circuit's DVC is answered for that circuit's own voltage and fault "
            "behaviour.\n\n"
            "Changing it changes which DVC-keyed limits the rule package applies to "
            "this circuit's pairs; it does not change the circuit's source "
            "relationship, connection exposure, or galvanic domain, which are "
            "independent answers."
        ),
        examples=(
            (
                "A circuit a reviewer has checked against the rule package's own DVC "
                "A-s criteria and confirmed to qualify."
            ),
        ),
        common_mistakes=(
            (
                "Assigning DVC A-s to every circuit in a project as a default rather than "
                "evaluating each one."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.DVC_B,
        title="DVC B",
        short_text="The circuit belongs to decisive voltage class B.",
        detailed_text=(
            "Assign this class when the circuit meets the conditions the active rule "
            "package associates with decisive voltage class B. As with every DVC "
            "option, the qualifying conditions and the limits that follow are the "
            "rule package's determination (iec62477_2022.dvc.voltage_limits, "
            "iec62477_2022.dvc.fault_applicability), not a value this field derives.\n\n"
            "Do not assign it without checking the circuit's own fault-time voltage "
            "behaviour against the rule package's criteria; a value copied from "
            "another circuit may not hold here.\n\n"
            "Changing it changes which DVC-keyed limits apply to this circuit's pairs "
            "and nothing about the circuit's other classification fields."
        ),
        examples=(
            (
                "A circuit a reviewer has checked against the rule package's own DVC B "
                "criteria and confirmed to qualify."
            ),
        ),
        common_mistakes=(
            (
                "Choosing DVC B by elimination between A-s and C without confirming it "
                "against the rule package's own criteria."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.DVC_C,
        title="DVC C",
        short_text="The circuit belongs to decisive voltage class C.",
        detailed_text=(
            "Assign this class when the circuit meets the conditions the active rule "
            "package associates with decisive voltage class C. As with the other two "
            "classes, the rule package decides the qualifying condition and the "
            "protection requirements that follow "
            "(iec62477_2022.dvc.voltage_limits, iec62477_2022.dvc.protection_matrix), "
            "not this field.\n\n"
            "Do not assign it merely because a circuit's voltage is high; the "
            "qualifying condition is the rule package's, and must be checked against "
            "it.\n\n"
            "Changing it changes which DVC-keyed limits apply to this circuit's pairs "
            "and nothing about the circuit's other classification fields."
        ),
        examples=(
            (
                "A circuit a reviewer has checked against the rule package's own DVC C "
                "criteria and confirmed to qualify."
            ),
        ),
        common_mistakes=(
            (
                "Assuming DVC C is always the safe choice for a high-voltage circuit "
                "without checking the rule package's actual criteria."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.GALVANIC_DOMAIN_ASSIGNMENT,
        title="galvanic domain assignment",
        short_text="Which isolated potential region this circuit belongs to; unset means undecided.",
        detailed_text=(
            "A galvanic domain groups every circuit that shares the same isolated "
            "reference potential - conductively connected to each other, and "
            "separated from every other domain only by a barrier. Assign this circuit "
            "to the domain it is conductively part of.\n\n"
            "Leave it unset while the circuit's domain has not been decided yet, or "
            "while the project has not defined any domain at all; unset is an "
            "incomplete state, not a claim that the circuit belongs to none. Domains "
            "themselves are created in the domain editor - this field only assigns an "
            "existing one.\n\n"
            "The assignment is what lets the topology check find which pairs of "
            "domains still need a barrier recorded between them, and lets a verified "
            "barrier's isolation apply to every circuit on each side of it, rather "
            "than to one pair at a time. It does not evaluate the barrier itself, and "
            "it does not change the circuit's source relationship, connection "
            "exposure, or decisive voltage class."
        ),
        examples=(
            (
                "Two converter stages joined by a common DC bus: both their circuits "
                "belong to the same domain."
            ),
            (
                "A primary-side and a secondary-side circuit separated by an isolating "
                "transformer: two different domains."
            ),
            (
                "A wireless charger's primary-side coil driver and its receiver-side coil "
                "and rectifier: two domains, joined only by the coreless coupling."
            ),
            (
                "An on-board charger's isolation-transformer primary and its HV battery "
                f"output, recorded as two domains. {OBC_APPLICABILITY_WARNING}"
            ),
        ),
        common_mistakes=(
            (
                "Assigning every circuit to the same domain without checking whether an "
                "isolating element actually separates them."
            ),
            (
                "Leaving a circuit unassigned indefinitely instead of creating the domain "
                "it belongs to."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.BARRIER_NOT_EVALUATED,
        title="barrier status not evaluated",
        short_text="No verification decision has been recorded for this domain pair yet.",
        detailed_text=(
            "The default state for a barrier record before anyone has decided whether "
            "the element between two domains provides verified galvanic isolation. It "
            "means the question is open, not that isolation has been checked and "
            "found absent.\n\n"
            "Do not leave a barrier at this status once its domains' pairs need "
            "evaluating - iec62477_2022.supply.multiple_source_propagation applies "
            "the unreduced, non-isolated assumption to every pair between the two "
            "domains until a verified status replaces it.\n\n"
            "It affects nothing on its own; it withholds the isolation credit rather "
            "than granting or denying it."
        ),
        examples=("A newly recorded domain pair, before its isolating element has been reviewed.",),
        common_mistakes=(
            (
                "Treating 'not evaluated' as equivalent to 'no isolation' when reporting "
                "a project's topology completeness."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.BARRIER_NO_GALVANIC_ISOLATION,
        title="no galvanic isolation",
        short_text="The two domains are not isolated; stress transfers between them unreduced.",
        detailed_text=(
            "Record this when the element between two domains does not provide "
            "galvanic isolation - a direct conductive connection, an unverified "
            "coupling, or an isolating component that has not been confirmed to "
            "hold. Every pair spanning the two domains is then evaluated as if the "
            "domains were one, under "
            "iec62477_2022.supply.multiple_source_propagation.\n\n"
            "Do not record this for an element that does provide verified isolation "
            "just because the verification has not been documented yet; use 'not "
            "evaluated' for that instead, since 'no isolation' is itself a decided "
            "answer, not a placeholder.\n\n"
            "It affects how stress propagates between the two domains for every "
            "circuit on both sides; it does not by itself change any single circuit's "
            "source relationship or connection exposure."
        ),
        examples=(
            (
                "Two DC buses joined by a shared PE conductor, with no transformer or "
                "opto-isolator between them."
            ),
            (
                "A non-isolated on-board charger's mains-referenced and battery-referenced "
                f"sides, sharing a common return. {OBC_APPLICABILITY_WARNING}"
            ),
        ),
        common_mistakes=(
            (
                "Recording 'no isolation' out of caution for an element that is actually "
                "isolating, instead of verifying and recording it properly."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.BARRIER_VERIFIED_GALVANIC_ISOLATION,
        title="verified galvanic isolation",
        short_text="A documented, verified isolating element separates the two domains.",
        detailed_text=(
            "Record this when the element between two domains - a transformer, an "
            "opto-isolator, an isolation amplifier - has been verified to provide "
            "galvanic isolation, with the verification method and evidence reference "
            "recorded alongside it. Only this status may carry that evidence; the "
            "other two must leave it blank.\n\n"
            "Do not record it without a verification method and an evidence "
            "reference - the domain model refuses a verified status that lacks them "
            "- and do not record it for an element that has not actually been "
            "checked, however isolating it looks on the schematic.\n\n"
            "A verified barrier lets a rule package apply the isolating element's "
            "transfer behaviour between the two domains "
            "(iec62477_2022.supply.verified_barrier_transfer) instead of the "
            "unreduced propagation a non-isolated pair sees. It does not change the "
            "classification of the circuits on either side, and the evidence must "
            "remain valid for the credit to stand."
        ),
        examples=(
            (
                "A mains-isolation transformer verified by routine test, with the test "
                "report referenced."
            ),
            (
                "The coreless coupling between a wireless charger's primary and receiver "
                "coils, verified by test."
            ),
            (
                "An isolated on-board charger's transformer and isolated control supply, "
                f"verified by test. {OBC_APPLICABILITY_WARNING}"
            ),
        ),
        common_mistakes=(
            (
                "Marking isolation verified from a datasheet claim alone, without a "
                "recorded verification method and evidence reference."
            ),
        ),
    ),
    VoltageGuidance(
        id=TopologyGuidanceId.CLASSIFICATION_OVERVIEW,
        title="how to classify a net",
        short_text="The order to answer the five classification questions in.",
        detailed_text=(
            "Start with the net class type: is this a circuit that carries its own "
            "operating voltage, or a conductive or insulating part with no source of "
            "its own? Only a circuit needs the next four answers.\n\n"
            "For a circuit, decide the source relationship first - mains-connected, "
            "non-mains external, or internally generated - since it is what "
            "determines which supply the circuit's transient and temporary "
            "overvoltage exposure traces back to. Decide the connection exposure "
            "next: how far the circuit's external connections reach, from purely "
            "internal wiring out to a long outdoor line. The decisive voltage class "
            "and the galvanic domain can be answered in either order once the first "
            "two are settled, but both stay open (DVC 'not evaluated', domain unset) "
            "until someone deliberately closes them - an open field is a status to "
            "track, not an error to silence.\n\n"
            "A non-circuit net (PE-bonded, accessible conductive, or accessible "
            "insulating) leaves all four of those fields unset; there is nothing to "
            "decide for them beyond the net class type itself.\n\n"
            "Every option's own help explains what it affects and what it does not; "
            "this overview only orders the decisions. None of the five fields "
            "derives another - each is a separate, deliberate answer, and changing "
            "one never silently changes another."
        ),
        examples=(),
        common_mistakes=(
            (
                "Picking a decisive voltage class before deciding the source relationship "
                "and connection exposure that its evaluation depends on."
            ),
            (
                "Assuming a circuit's default values need no attention just because they "
                "satisfy the model's validation."
            ),
        ),
    ),
)
