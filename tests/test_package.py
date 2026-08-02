from pathlib import Path

from insulation_coordination import __version__, cli
from insulation_coordination.startup import StartupKind


def test_package_exposes_version(capsys):
    assert __version__ == "0.1.0"
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_normal_invocations_route_to_gui(monkeypatch, tmp_path: Path) -> None:
    project_path = tmp_path / "design.icproj"
    project_path.write_bytes(b"fixture")
    requests = []

    monkeypatch.setattr(cli, "_run_gui", lambda request: requests.append(request) or 17)

    assert cli.main([]) == 17
    assert cli.main(["--gui"]) == 17
    assert cli.main([str(project_path)]) == 17
    assert [request.kind for request in requests] == [
        StartupKind.NEW,
        StartupKind.NEW,
        StartupKind.PROJECT,
    ]
    assert requests[2].path == project_path.resolve()


def test_release_diagnostic_invocation_routes_without_starting_gui(monkeypatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setattr(
        cli,
        "_run_release_diagnostic",
        lambda paths: calls.append(paths) or 23,
    )
    paths = (tmp_path / "project.icproj", tmp_path / "rules.icrules", tmp_path / "output")

    assert cli.main(["--release-diagnostic", *(str(path) for path in paths)]) == 23
    assert calls == [paths]


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
