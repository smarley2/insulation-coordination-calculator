"""Report disclosure of net classification, galvanic domains, and barriers.

Topology never feeds a calculation in this issue (see the domain layer's own tests for
that boundary), so every assertion here is about what a reviewer can *see*, never about
a distance changing.
"""

from uuid import UUID

from insulation_coordination.domain.enums import (
    BarrierVerificationStatus,
    DecisiveVoltageClass,
    ReviewState,
    VerificationMethod,
)
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.topology import GalvanicBarrier, GalvanicDomain
from insulation_coordination.report.human_view import build_human_report_view
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import build_report_model

_PRIMARY_ID = UUID(int=10)
_SECONDARY_ID = UUID(int=11)
_TERTIARY_ID = UUID(int=12)
_BARRIER_ID = UUID(int=20)


def _with_topology(
    project: Project,
    *,
    domain_review: ReviewState = ReviewState.USER_CONFIRMED,
    barrier_status: BarrierVerificationStatus = BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
) -> Project:
    """Classify both synthetic nets and record one barrier between two domains."""
    high, low = project.net_classes[0], project.net_classes[1]
    primary = GalvanicDomain(
        id=_PRIMARY_ID,
        name="Primary side",
        description="Directly connected to the mains input.",
        is_direct_source_domain=True,
        review_state=domain_review,
    )
    secondary = GalvanicDomain(id=_SECONDARY_ID, name="Secondary side", review_state=domain_review)
    if barrier_status is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION:
        barrier = GalvanicBarrier(
            id=_BARRIER_ID,
            domain_a_id=_PRIMARY_ID,
            domain_b_id=_SECONDARY_ID,
            status=barrier_status,
            description="Isolation transformer barrier",
            verification_method=VerificationMethod.TEST,
            evidence_reference="EVID-0042 & report",
        )
    else:
        barrier = GalvanicBarrier(
            id=_BARRIER_ID,
            domain_a_id=_PRIMARY_ID,
            domain_b_id=_SECONDARY_ID,
            status=barrier_status,
            description="Isolation transformer barrier",
        )
    net_classes = (
        high.model_copy(
            update={
                "galvanic_domain_id": _PRIMARY_ID,
                "decisive_voltage_class": DecisiveVoltageClass.DVC_B,
                "classification_review_state": ReviewState.USER_CONFIRMED,
            }
        ),
        low.model_copy(
            update={
                "galvanic_domain_id": _SECONDARY_ID,
                "decisive_voltage_class": DecisiveVoltageClass.DVC_AS,
                "classification_review_state": ReviewState.USER_CONFIRMED,
            }
        ),
    )
    return project.model_copy(
        update={
            "net_classes": net_classes,
            "galvanic_domains": (primary, secondary),
            "galvanic_barriers": (barrier,),
        }
    )


def test_report_model_carries_domain_and_barrier_inventory_in_project_order(report_inputs) -> None:
    project, results, groups, rules = report_inputs
    project = _with_topology(project)

    model = build_report_model(project, results, groups, rules)

    assert [domain.name for domain in model.galvanic_domains] == ["Primary side", "Secondary side"]
    assert model.galvanic_barriers[0].evidence_reference == "EVID-0042 & report"
    assert model.topology.is_complete is True


def test_report_model_lists_domains_needing_review_independently_of_topology_completion(
    report_inputs,
) -> None:
    """``topology_completion`` never reads ``GalvanicDomain.review_state`` (see topology.py);

    the report is the first consumer that discloses it, so it must be read directly here.
    """
    project, results, groups, rules = report_inputs
    project = _with_topology(project, domain_review=ReviewState.NEEDS_REVIEW)

    model = build_report_model(project, results, groups, rules)

    assert model.topology.is_complete is True
    assert set(model.domains_needing_review) == {_PRIMARY_ID, _SECONDARY_ID}


def test_report_model_builds_for_legacy_project_with_no_topology(report_inputs) -> None:
    """A project with no domains and only ``NOT_EVALUATED``/``NEEDS_REVIEW`` nets still builds."""
    project, results, groups, rules = report_inputs

    model = build_report_model(project, results, groups, rules)

    assert model.galvanic_domains == ()
    assert model.galvanic_barriers == ()
    assert model.domains_needing_review == ()
    assert model.topology.is_complete is False


def test_human_view_resolves_net_classification_and_domain_and_barrier_names(
    report_inputs,
) -> None:
    project, results, groups, rules = report_inputs
    project = _with_topology(project)
    model = build_report_model(project, results, groups, rules)

    view = build_human_report_view(model)

    hv = next(item for item in view.net_classifications if item.name == "HV_1")
    assert hv.galvanic_domain == "Primary side"
    assert hv.decisive_voltage_class == "dvc b"
    assert hv.review_state == "user confirmed"

    domain = next(item for item in view.galvanic_domains if item.name == "Primary side")
    assert domain.is_direct_source_domain is True
    assert domain.review_state == "user confirmed"

    barrier = view.galvanic_barriers[0]
    assert barrier.domain_a == "Primary side"
    assert barrier.domain_b == "Secondary side"
    assert barrier.status == "verified galvanic isolation"
    assert barrier.evidence_reference == "EVID-0042 & report"


def test_human_view_states_unresolved_topology_by_name_for_legacy_project(report_inputs) -> None:
    project, results, groups, rules = report_inputs
    model = build_report_model(project, results, groups, rules)

    view = build_human_report_view(model)

    status = view.topology_status
    assert status.is_complete is False
    assert set(status.nets_needing_review) == {"HV_1", "LV%2"}
    assert set(status.circuit_nets_without_domain) == {"HV_1", "LV%2"}
    assert set(status.circuit_nets_with_unevaluated_dvc) == {"HV_1", "LV%2"}
    assert status.domain_pairs_without_barrier == ()
    assert status.unevaluated_barriers == ()
    assert status.domains_needing_review == ()
    assert status.fully_resolved is False


def test_human_view_names_domain_pairs_without_barrier_and_unevaluated_barriers(
    report_inputs,
) -> None:
    project, results, groups, rules = report_inputs
    project = _with_topology(project, barrier_status=BarrierVerificationStatus.NOT_EVALUATED)
    third = GalvanicDomain(id=_TERTIARY_ID, name="Tertiary side", review_state=ReviewState.USER_CONFIRMED)
    project = project.model_copy(update={"galvanic_domains": (*project.galvanic_domains, third)})
    model = build_report_model(project, results, groups, rules)

    view = build_human_report_view(model)

    status = view.topology_status
    assert status.is_complete is False
    assert status.unevaluated_barriers == ("Primary side \u2194 Secondary side",)
    assert any("Tertiary side" in pair for pair in status.domain_pairs_without_barrier)


def test_human_view_topology_status_is_not_fully_resolved_while_a_domain_awaits_review(
    report_inputs,
) -> None:
    """``is_complete`` alone would miss this - it never inspects ``GalvanicDomain.review_state``."""
    project, results, groups, rules = report_inputs
    project = _with_topology(project, domain_review=ReviewState.NEEDS_REVIEW)
    model = build_report_model(project, results, groups, rules)

    view = build_human_report_view(model)

    assert view.topology_status.is_complete is True
    assert view.topology_status.fully_resolved is False
    assert set(view.topology_status.domains_needing_review) == {"Primary side", "Secondary side"}


def _topology_section(tex: str) -> str:
    """The Project Topology section's own text, bounded before the next ``\\section``."""
    return tex.split(r"\section{Project Topology}", 1)[1].split(r"\section{", 1)[0]


def test_latex_project_topology_section_discloses_inventory_and_evidence(report_inputs) -> None:
    project, results, groups, rules = report_inputs
    project = _with_topology(project)
    model = build_report_model(project, results, groups, rules)

    tex = render_latex(model)
    topology_tex = _topology_section(tex)

    assert "Project Topology" in tex
    assert "Primary side" in topology_tex
    assert "Secondary side" in topology_tex
    assert "EVID-0042" in topology_tex
    assert r"EVID-0042 \& report" in topology_tex  # the evidence reference's "&" is escaped
    assert "EVID-0042 & report" not in topology_tex  # never passed through raw
    # A barrier states a recorded fact, never a protection/attenuation claim (decision 5);
    # the disclaimer itself is the only place those words may appear - scoped to this
    # section so an unrelated advisory or net name elsewhere can't inflate the count.
    assert "protection or attenuation claim" in topology_tex
    assert topology_tex.lower().count("protect") == 1
    assert topology_tex.lower().count("attenuat") == 1


def test_latex_topology_disclaimer_count_ignores_mentions_outside_the_section(
    report_inputs,
) -> None:
    """A net description elsewhere in the report may legitimately reuse these words;
    the topology section's own disclaimer count must not be thrown off by them."""
    project, results, groups, rules = report_inputs
    project = _with_topology(project)
    noisy_net = project.net_classes[0].model_copy(
        update={"description": "Bonded for protective earth, with no attenuation stage."}
    )
    project = project.model_copy(update={"net_classes": (noisy_net, project.net_classes[1])})
    model = build_report_model(project, results, groups, rules)

    tex = render_latex(model)
    topology_tex = _topology_section(tex)

    assert tex.lower().count("protect") > 1
    assert tex.lower().count("attenuat") > 1
    assert topology_tex.lower().count("protect") == 1
    assert topology_tex.lower().count("attenuat") == 1


def test_latex_states_no_domains_or_barriers_for_legacy_project(report_inputs) -> None:
    project, results, groups, rules = report_inputs
    model = build_report_model(project, results, groups, rules)

    tex = render_latex(model)

    topology_tex = _topology_section(tex)
    assert "No galvanic domains are recorded" in topology_tex
    assert "No galvanic barriers are recorded" in topology_tex
    assert "HV\\_1" in topology_tex
    assert "not yet" in topology_tex.lower() or "awaiting" in topology_tex.lower()
