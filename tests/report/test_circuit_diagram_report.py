from __future__ import annotations

from pathlib import Path

import pytest

from insulation_coordination.project import image_attachments
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import ReportBuildError, build_report_model
from tests.fixtures.images import attachment_from, png_bytes


@pytest.fixture
def diagram_inputs(report_inputs, tmp_path: Path):
    """The shared report inputs, with a captioned diagram attached."""
    project, results, groups, rules = report_inputs
    attachment = attachment_from(
        png_bytes(),
        caption=r"Topology \input{unsafe} & 100%",
        source_note="Exported from the EDA tool",
    )
    return project.model_copy(update={"circuit_diagram": attachment}), results, groups, rules


def test_report_without_a_diagram_has_no_diagram_section(report_inputs, tmp_path: Path) -> None:
    build_directory = tmp_path / "build"

    model = build_report_model(*report_inputs, image_directory=build_directory)

    assert model.circuit_diagram is None
    assert "Circuit Diagram" not in render_latex(model)
    assert not build_directory.exists()


def test_diagram_is_staged_next_to_the_document_under_a_deterministic_name(
    diagram_inputs, tmp_path: Path
) -> None:
    project = diagram_inputs[0]
    assert project.circuit_diagram is not None

    model = build_report_model(*diagram_inputs, image_directory=tmp_path)

    assert model.circuit_diagram is not None
    staged = tmp_path / model.circuit_diagram.staged_filename
    assert model.circuit_diagram.staged_filename == project.circuit_diagram.staged_filename
    assert staged.read_bytes() == project.circuit_diagram.decoded_bytes()
    assert model.circuit_diagram.sha256 == project.circuit_diagram.sha256


def test_report_model_carries_no_source_path(diagram_inputs, tmp_path: Path) -> None:
    model = build_report_model(*diagram_inputs, image_directory=tmp_path)

    assert model.circuit_diagram is not None
    assert str(tmp_path) not in model.model_dump_json()
    assert model.circuit_diagram.staged_filename == Path(
        model.circuit_diagram.staged_filename
    ).name


def test_a_diagram_without_a_directory_blocks_the_report(diagram_inputs) -> None:
    with pytest.raises(ReportBuildError, match="directory to stage into"):
        build_report_model(*diagram_inputs)


def test_a_staging_failure_blocks_the_report(
    diagram_inputs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise image_attachments.ImageAttachmentError("disk full")

    monkeypatch.setattr("insulation_coordination.report.model.stage_report_image", fail)

    with pytest.raises(ReportBuildError, match="could not be staged: disk full"):
        build_report_model(*diagram_inputs, image_directory=tmp_path)


def test_latex_includes_the_staged_file_with_escaped_text(diagram_inputs, tmp_path: Path) -> None:
    model = build_report_model(*diagram_inputs, image_directory=tmp_path)

    tex = render_latex(model)

    assert model.circuit_diagram is not None
    assert r"\usepackage{graphicx}" in tex
    assert (
        r"\includegraphics[width=\linewidth,height=0.68\textheight,keepaspectratio]"
        f"{{{model.circuit_diagram.staged_filename}}}" in tex
    )
    assert r"Topology \textbackslash{}input\{unsafe\} \& 100\%" in tex
    assert r"\input{unsafe}" not in tex
    assert "Source: Exported from the EDA tool" in tex
    assert str(tmp_path) not in tex


def test_diagram_section_precedes_the_calculations(diagram_inputs, tmp_path: Path) -> None:
    tex = render_latex(build_report_model(*diagram_inputs, image_directory=tmp_path))

    assert tex.index(r"\section{Net Classes}") < tex.index(r"\section{Circuit Diagram}")
    assert tex.index(r"\section{Circuit Diagram}") < tex.index(r"\section{Grouped Calculations}")


def test_diagram_without_caption_or_note_renders_only_the_image(
    report_inputs, tmp_path: Path
) -> None:
    project, results, groups, rules = report_inputs
    project = project.model_copy(update={"circuit_diagram": attachment_from(png_bytes())})

    tex = render_latex(build_report_model(project, results, groups, rules, image_directory=tmp_path))
    section = tex[tex.index(r"\section{Circuit Diagram}") :]
    section = section[: section.index(r"\clearpage")]

    assert r"\includegraphics" in section
    assert "Source:" not in section
