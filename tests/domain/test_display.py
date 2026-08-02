from uuid import UUID

from insulation_coordination.domain.project import (
    NetClass,
    PairCase,
    Project,
    ProjectDefaults,
    ProjectMetadata,
)
from insulation_coordination.project.pairs import canonical_pair_key
from insulation_coordination.domain.display import pair_label


def test_pair_label_uses_net_class_names() -> None:
    nets = (
        NetClass(id=UUID(int=1), name="HV+"),
        NetClass(id=UUID(int=2), name="HV-"),
    )
    pair = PairCase(
        key=canonical_pair_key(nets[0].id, nets[1].id),
        net_a=nets[0].id,
        net_b=nets[1].id,
    )
    project = Project(
        id=UUID(int=100),
        metadata=ProjectMetadata(title="Test"),
        application_version="test",
        defaults=ProjectDefaults(),
        net_classes=nets,
        pairs=(pair,),
    )

    assert pair_label(project, pair) == "HV+ ↔ HV-"
