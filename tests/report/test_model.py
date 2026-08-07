from pathlib import Path

from insulation_coordination.calculation.engine import calculate_pair
from insulation_coordination.calculation.grouping import group_results
from insulation_coordination.domain.project import RulePackageReference
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.report.model import build_report_model
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from tests.fixtures.synthetic_rules import synthetic_rule_package


def test_rules_provenance_counts_decisions_procedures_and_guidance(
    report_inputs, tmp_path: Path
) -> None:
    project, _results, _groups, rules = report_inputs
    source = synthetic_rule_package()
    decision, procedure, guidance = source.decisions[0], source.procedures[0], source.guidance[0]
    # Distinct counts, so a count read from the wrong collection cannot pass.
    enriched = rules.model_copy(
        update={
            "decisions": (decision,),
            "procedures": (
                procedure,
                procedure.model_copy(update={"id": "synthetic-procedure-2"}),
            ),
            "guidance": tuple(
                guidance.model_copy(update={"id": f"synthetic-guidance-{index}"})
                for index in range(3)
            ),
            "package_sha256": None,
        }
    )
    path = tmp_path / "enriched.icrules"
    write_rule_package(path, enriched)
    loaded = load_rule_package(path)
    assert loaded.package_sha256 is not None
    project = project.model_copy(
        update={
            "required_rules": RulePackageReference(
                package_id=str(loaded.manifest.package_id),
                version=loaded.manifest.version,
                sha256=loaded.package_sha256,
            )
        }
    )
    results = tuple(
        calculate_pair(resolve_effective_case(project.defaults, pair), loaded)
        for pair in project.pairs
    )

    model = build_report_model(project, results, group_results(results, ()), loaded)

    assert model.rules.decision_count == 1
    assert model.rules.procedure_count == 2
    assert model.rules.guidance_count == 3
