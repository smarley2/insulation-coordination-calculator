from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.enums import (
    BarrierVerificationStatus,
    DecisiveVoltageClass,
    NetClassType,
    ReviewState,
    VerificationMethod,
)
from insulation_coordination.domain.project import (
    NetClass,
    Project,
    ProjectDefaults,
    ProjectMetadata,
)
from insulation_coordination.domain.topology import (
    GalvanicBarrier,
    GalvanicDomain,
    barrier_between,
    circuit_nets,
    domain_for_net,
    topology_completion,
)
from insulation_coordination.project.pairs import reconcile_pairs


def _project(**overrides: object) -> Project:
    fields: dict[str, object] = {
        "id": UUID(int=1000),
        "metadata": ProjectMetadata(title="Synthetic"),
        "application_version": "test",
        "defaults": ProjectDefaults(),
        "net_classes": (),
        "pairs": (),
    }
    fields.update(overrides)
    return Project(**fields)


def _domain(**overrides: object) -> GalvanicDomain:
    fields: dict[str, object] = {"id": UUID(int=1), "name": "Domain A"}
    fields.update(overrides)
    return GalvanicDomain(**fields)


def _barrier(**overrides: object) -> GalvanicBarrier:
    fields: dict[str, object] = {
        "id": UUID(int=100),
        "domain_a_id": UUID(int=1),
        "domain_b_id": UUID(int=2),
        "status": BarrierVerificationStatus.NOT_EVALUATED,
        "description": "Synthetic barrier",
    }
    fields.update(overrides)
    return GalvanicBarrier(**fields)


def test_net_class_with_only_id_and_name_lands_on_documented_defaults() -> None:
    net = NetClass(id=UUID(int=1), name="N1")

    assert net.net_type is NetClassType.CIRCUIT
    assert net.source_relationship is not None
    assert net.connection_exposure is not None
    assert net.decisive_voltage_class is DecisiveVoltageClass.NOT_EVALUATED
    assert net.galvanic_domain_id is None
    assert net.classification_review_state is ReviewState.NEEDS_REVIEW


def test_circuit_net_may_have_a_null_domain() -> None:
    net = NetClass(id=UUID(int=1), name="N1", galvanic_domain_id=None)
    assert net.galvanic_domain_id is None


def test_circuit_net_requires_its_enum_fields_set() -> None:
    with pytest.raises(ValidationError, match="circuit net requires"):
        NetClass(id=UUID(int=1), name="N1", source_relationship=None)


def test_non_circuit_net_rejects_a_dvc() -> None:
    with pytest.raises(ValidationError, match="non-circuit net"):
        NetClass(
            id=UUID(int=1),
            name="N1",
            net_type=NetClassType.ACCESSIBLE_CONDUCTIVE_PART,
            source_relationship=None,
            connection_exposure=None,
            decisive_voltage_class=DecisiveVoltageClass.DVC_B,
            galvanic_domain_id=None,
        )


def test_non_circuit_net_requires_circuit_only_fields_unset() -> None:
    with pytest.raises(ValidationError, match="non-circuit net"):
        NetClass(id=UUID(int=1), name="N1", net_type=NetClassType.ACCESSIBLE_CONDUCTIVE_PART)


def test_non_circuit_net_accepts_unset_circuit_only_fields() -> None:
    net = NetClass(
        id=UUID(int=1),
        name="N1",
        net_type=NetClassType.PE_BONDED_CONDUCTIVE_PART,
        source_relationship=None,
        connection_exposure=None,
        decisive_voltage_class=None,
        galvanic_domain_id=None,
    )
    assert net.net_type is NetClassType.PE_BONDED_CONDUCTIVE_PART


def test_barrier_rejects_the_same_domain_twice() -> None:
    with pytest.raises(ValidationError, match="two different domains"):
        _barrier(domain_a_id=UUID(int=1), domain_b_id=UUID(int=1))


def test_verified_isolation_requires_method_and_evidence() -> None:
    with pytest.raises(ValidationError, match="Verified isolation requires"):
        _barrier(status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION)


def test_verified_isolation_rejects_blank_evidence() -> None:
    with pytest.raises(ValidationError, match="Verified isolation requires"):
        _barrier(
            status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
            verification_method=VerificationMethod.TEST,
            evidence_reference="   ",
        )


def test_verified_isolation_accepts_method_and_evidence() -> None:
    barrier = _barrier(
        status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
        verification_method=VerificationMethod.TEST,
        evidence_reference="Report 42",
    )
    assert barrier.verification_method is VerificationMethod.TEST


def test_unverified_status_rejects_a_lingering_verification_method() -> None:
    with pytest.raises(ValidationError, match="Only verified isolation"):
        _barrier(
            status=BarrierVerificationStatus.NOT_EVALUATED,
            verification_method=VerificationMethod.TEST,
        )


def test_unverified_status_rejects_a_lingering_evidence_reference() -> None:
    with pytest.raises(ValidationError, match="Only verified isolation"):
        _barrier(
            status=BarrierVerificationStatus.NO_GALVANIC_ISOLATION,
            evidence_reference="stale",
        )


def test_barrier_domain_key_is_unordered() -> None:
    forward = _barrier(domain_a_id=UUID(int=1), domain_b_id=UUID(int=2))
    reverse = _barrier(domain_a_id=UUID(int=2), domain_b_id=UUID(int=1))
    assert forward.domain_key == reverse.domain_key


def test_project_with_no_domains_is_valid() -> None:
    project = _project()
    assert project.galvanic_domains == ()
    assert project.galvanic_barriers == ()


def test_project_rejects_duplicate_domain_ids() -> None:
    domain = _domain()
    with pytest.raises(ValidationError, match="Galvanic domain IDs must be unique"):
        _project(galvanic_domains=(domain, domain.model_copy(update={"name": "Domain B"})))


def test_project_rejects_duplicate_domain_names_after_normalisation() -> None:
    domains = (
        _domain(id=UUID(int=1), name="Domain A"),
        _domain(id=UUID(int=2), name="  domain a "),
    )
    with pytest.raises(ValidationError, match="Galvanic domain names must be unique"):
        _project(galvanic_domains=domains)


def test_project_requires_exactly_one_direct_source_domain_when_any_domain_exists() -> None:
    with pytest.raises(ValidationError, match="Exactly one galvanic domain"):
        _project(galvanic_domains=(_domain(is_direct_source_domain=False),))


def test_project_rejects_two_direct_source_domains() -> None:
    domains = (
        _domain(id=UUID(int=1), name="A", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="B", is_direct_source_domain=True),
    )
    with pytest.raises(ValidationError, match="Exactly one galvanic domain"):
        _project(galvanic_domains=domains)


def test_project_accepts_exactly_one_direct_source_domain() -> None:
    project = _project(galvanic_domains=(_domain(is_direct_source_domain=True),))
    assert len(project.galvanic_domains) == 1


def test_project_rejects_a_net_class_domain_id_that_does_not_resolve() -> None:
    net = NetClass(id=UUID(int=1), name="N1", galvanic_domain_id=UUID(int=999))
    with pytest.raises(ValidationError, match="net class's galvanic domain"):
        _project(
            net_classes=(net,),
            galvanic_domains=(_domain(is_direct_source_domain=True),),
        )


def test_project_accepts_a_net_class_with_no_domain() -> None:
    net = NetClass(id=UUID(int=1), name="N1", galvanic_domain_id=None)
    project = _project(
        net_classes=(net,), galvanic_domains=(_domain(is_direct_source_domain=True),)
    )
    assert project.net_classes[0].galvanic_domain_id is None


def test_project_rejects_a_barrier_whose_domain_does_not_resolve() -> None:
    with pytest.raises(ValidationError, match="galvanic barrier's domains"):
        _project(
            galvanic_domains=(_domain(id=UUID(int=1), is_direct_source_domain=True),),
            galvanic_barriers=(_barrier(domain_a_id=UUID(int=1), domain_b_id=UUID(int=2)),),
        )


def test_project_rejects_two_barriers_sharing_an_unordered_domain_pair() -> None:
    domains = (
        _domain(id=UUID(int=1), name="A", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="B"),
    )
    barriers = (
        _barrier(id=UUID(int=100), domain_a_id=UUID(int=1), domain_b_id=UUID(int=2)),
        _barrier(id=UUID(int=101), domain_a_id=UUID(int=2), domain_b_id=UUID(int=1)),
    )
    with pytest.raises(ValidationError, match="must not duplicate a domain pair"):
        _project(galvanic_domains=domains, galvanic_barriers=barriers)


def test_circuit_nets_filters_out_non_circuit_nets() -> None:
    circuit = NetClass(id=UUID(int=1), name="Circuit")
    non_circuit = NetClass(
        id=UUID(int=2),
        name="Chassis",
        net_type=NetClassType.ACCESSIBLE_CONDUCTIVE_PART,
        source_relationship=None,
        connection_exposure=None,
        decisive_voltage_class=None,
        galvanic_domain_id=None,
    )
    classes = (circuit, non_circuit)
    project = _project(net_classes=classes, pairs=reconcile_pairs(classes, ()))

    assert circuit_nets(project) == (circuit,)


def test_domain_for_net_resolves_the_declared_domain() -> None:
    domain = _domain(is_direct_source_domain=True)
    net = NetClass(id=UUID(int=10), name="N1", galvanic_domain_id=domain.id)
    project = _project(net_classes=(net,), galvanic_domains=(domain,))

    assert domain_for_net(project, net.id) == domain


def test_domain_for_net_is_none_without_a_domain() -> None:
    net = NetClass(id=UUID(int=10), name="N1", galvanic_domain_id=None)
    project = _project(net_classes=(net,))

    assert domain_for_net(project, net.id) is None


def test_barrier_between_matches_a_and_b_in_either_order() -> None:
    domains = (
        _domain(id=UUID(int=1), name="A", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="B"),
    )
    barrier = _barrier(domain_a_id=UUID(int=1), domain_b_id=UUID(int=2))
    project = _project(galvanic_domains=domains, galvanic_barriers=(barrier,))

    assert barrier_between(project, UUID(int=1), UUID(int=2)) == barrier
    assert barrier_between(project, UUID(int=2), UUID(int=1)) == barrier


def test_barrier_between_is_none_when_no_barrier_exists() -> None:
    domains = (
        _domain(id=UUID(int=1), name="A", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="B"),
    )
    project = _project(galvanic_domains=domains)

    assert barrier_between(project, UUID(int=1), UUID(int=2)) is None


def test_topology_completion_on_empty_topology_reports_incomplete_without_raising() -> None:
    net = NetClass(id=UUID(int=1), name="N1")
    project = _project(net_classes=(net,))

    completion = topology_completion(project)

    assert completion.is_complete is False
    assert net.id in completion.nets_needing_review
    assert net.id in completion.circuit_nets_without_domain
    assert net.id in completion.circuit_nets_with_unevaluated_dvc
    assert completion.domain_pairs_without_barrier == ()
    assert completion.unevaluated_barriers == ()


def test_topology_completion_reports_domain_pairs_without_a_barrier() -> None:
    domains = (
        _domain(id=UUID(int=1), name="A", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="B"),
    )
    project = _project(galvanic_domains=domains)

    completion = topology_completion(project)

    assert completion.domain_pairs_without_barrier == ((UUID(int=1), UUID(int=2)),)
    assert completion.is_complete is False


def test_topology_completion_reports_unevaluated_barriers() -> None:
    domains = (
        _domain(id=UUID(int=1), name="A", is_direct_source_domain=True),
        _domain(id=UUID(int=2), name="B"),
    )
    barrier = _barrier(domain_a_id=UUID(int=1), domain_b_id=UUID(int=2))
    project = _project(galvanic_domains=domains, galvanic_barriers=(barrier,))

    completion = topology_completion(project)

    assert completion.unevaluated_barriers == (barrier.id,)
    assert completion.domain_pairs_without_barrier == ()


def test_topology_completion_is_complete_when_nothing_is_outstanding() -> None:
    domain = _domain(is_direct_source_domain=True)
    net = NetClass(
        id=UUID(int=1),
        name="N1",
        galvanic_domain_id=domain.id,
        decisive_voltage_class=DecisiveVoltageClass.DVC_B,
        classification_review_state=ReviewState.USER_CONFIRMED,
    )
    project = _project(net_classes=(net,), galvanic_domains=(domain,))

    completion = topology_completion(project)

    assert completion.is_complete is True
