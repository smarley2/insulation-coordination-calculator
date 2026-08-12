"""Interactive harness: open the manual curve review dialog on synthetic data.

Not collected by the suite (no ``test_`` filename prefix). Run it by path:

    uv run pytest tests/ui/preview_curve_review.py -s -p no:randomly

The dialog blocks until closed. Untracked scratch file — delete when done.
"""

from __future__ import annotations

from insulation_coordination.ui.curve_review import CurveReviewDialog
from tests.ui.test_curve_review import local_manual_draft, manual_draft  # noqa: F401


def test_preview(qtbot, local_manual_draft) -> None:  # noqa: F811
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(draft, actor="Reviewer", pdf_paths={"SYNTHETIC": path})
    qtbot.addWidget(dialog)
    dialog.exec()
