"""Immutable, auditable report generation."""

from insulation_coordination.report.compiler import CompileResult, compile_pdf
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import ReportBuildError, ReportModel, build_report_model

__all__ = [
    "CompileResult",
    "ReportBuildError",
    "ReportModel",
    "build_report_model",
    "compile_pdf",
    "render_latex",
]
