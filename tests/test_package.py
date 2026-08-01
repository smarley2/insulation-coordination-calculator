from pathlib import Path

from insulation_coordination import __version__
from insulation_coordination.cli import main


def test_package_exposes_version(capsys):
    assert __version__ == "0.1.0"
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_readme_documents_pcb_annex_gh_workflow() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    for required in (
        "PCB-only product boundary",
        "Rules Manager review workflow",
        "Annex G clearance workflow",
        "Pair-specific critical-frequency flow",
        "Annex H creepage workflow",
        "Unsupported PCB conditions",
        "Implementation map",
        "iec60664-1-f2",
        "iec60664-1-f5",
        "iec60664-1-f8",
        "iec60664-1-f9",
        "iec60664-1-a2",
        "iec60664-4-table-1",
        "iec60664-4-table-2",
        "calculate_clearance_candidates",
        "calculate_critical_frequency",
        "assess_part4_clearance",
        "apply_a2_altitude_correction",
        "calculate_creepage_candidates",
        "select_f5_pcb_creepage",
        "select_part4_table2_creepage",
        "calculate_pair",
        "computed independently for every pair",
    ):
        assert required in readme
