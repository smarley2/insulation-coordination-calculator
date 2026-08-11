from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMessageBox

from insulation_coordination.project.image_attachments import ImageAttachmentError
from insulation_coordination.ui.circuit_diagram import CircuitDiagramBox
from tests.fixtures.images import gif_bytes, jpeg_bytes, png_bytes


@pytest.fixture
def diagram_box(qtbot) -> CircuitDiagramBox:
    box = CircuitDiagramBox()
    qtbot.addWidget(box)
    box.resize(QSize(400, 300))
    return box


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_empty_state_offers_only_add(diagram_box: CircuitDiagramBox) -> None:
    assert diagram_box.attachment is None
    assert diagram_box._add_button.isEnabled()
    assert not diagram_box._replace_button.isEnabled()
    assert not diagram_box._remove_button.isEnabled()
    assert diagram_box.summary == "No image attached."


def test_attaching_an_image_publishes_it_and_shows_a_preview(
    qtbot, diagram_box: CircuitDiagramBox, tmp_path: Path
) -> None:
    path = write(tmp_path, "topology.png", png_bytes(60, 40))

    with qtbot.waitSignal(diagram_box.attachment_changed) as blocker:
        diagram_box.attach_path(path)

    attachment = diagram_box.attachment
    assert attachment is not None
    assert blocker.args == [attachment]
    assert attachment.original_filename == "topology.png"
    assert not diagram_box._add_button.isEnabled()
    assert diagram_box._replace_button.isEnabled()
    assert diagram_box._remove_button.isEnabled()
    assert "60×40 px" in diagram_box.summary
    assert not diagram_box._preview.pixmap().isNull()


def test_preview_fits_the_widget_without_distorting_or_upscaling(
    diagram_box: CircuitDiagramBox, tmp_path: Path
) -> None:
    diagram_box.attach_path(write(tmp_path, "tall.png", png_bytes(200, 800)))

    pixmap = diagram_box._preview.pixmap()

    assert pixmap.width() <= diagram_box._preview.width()
    assert pixmap.height() <= diagram_box._preview.height()
    assert pixmap.height() == pytest.approx(pixmap.width() * 4, abs=1)


def test_resizing_rescales_from_the_cached_decode(
    diagram_box: CircuitDiagramBox, tmp_path: Path
) -> None:
    diagram_box.attach_path(write(tmp_path, "tall.png", png_bytes(200, 800)))
    cache_key = diagram_box._preview_source.cacheKey()

    diagram_box._preview.resize(QSize(60, 400))
    diagram_box._render_preview()

    assert diagram_box._preview_source.cacheKey() == cache_key
    assert diagram_box._preview.pixmap().width() <= 60


def test_a_rejected_file_leaves_the_current_attachment_untouched(
    diagram_box: CircuitDiagramBox, tmp_path: Path
) -> None:
    diagram_box.attach_path(write(tmp_path, "good.png", png_bytes()))
    attached = diagram_box.attachment
    received: list[object] = []
    diagram_box.attachment_changed.connect(received.append)

    with pytest.raises(ImageAttachmentError):
        diagram_box.attach_path(write(tmp_path, "bad.png", gif_bytes()))

    assert diagram_box.attachment == attached
    assert received == []


def test_replacing_swaps_the_image_and_keeps_the_typed_caption(
    diagram_box: CircuitDiagramBox, tmp_path: Path
) -> None:
    diagram_box.attach_path(write(tmp_path, "first.png", png_bytes()))
    diagram_box._caption_edit.setText("Main topology")
    diagram_box._on_text_edited()

    diagram_box.attach_path(write(tmp_path, "second.jpg", jpeg_bytes()))

    attachment = diagram_box.attachment
    assert attachment is not None
    assert attachment.original_filename == "second.jpg"
    assert attachment.caption == "Main topology"


def test_caption_and_note_edits_keep_the_image_bytes(
    diagram_box: CircuitDiagramBox, tmp_path: Path
) -> None:
    diagram_box.attach_path(write(tmp_path, "diagram.png", png_bytes()))
    original = diagram_box.attachment
    assert original is not None

    diagram_box._caption_edit.setText("Figure 1")
    diagram_box._source_edit.setText("Drawn in the EDA tool")
    diagram_box._on_text_edited()

    updated = diagram_box.attachment
    assert updated is not None
    assert (updated.caption, updated.source_note) == ("Figure 1", "Drawn in the EDA tool")
    assert updated.sha256 == original.sha256
    assert updated.data_base64 == original.data_base64


def test_editing_text_without_an_attachment_publishes_nothing(
    diagram_box: CircuitDiagramBox,
) -> None:
    received: list[object] = []
    diagram_box.attachment_changed.connect(received.append)

    diagram_box._caption_edit.setText("Orphan caption")
    diagram_box._on_text_edited()

    assert received == []


def test_remove_asks_first_and_clears_the_preview(
    diagram_box: CircuitDiagramBox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    diagram_box.attach_path(write(tmp_path, "diagram.png", png_bytes()))
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )

    diagram_box._on_remove_clicked()

    assert diagram_box.attachment is not None

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    diagram_box._on_remove_clicked()

    assert diagram_box.attachment is None
    assert diagram_box._preview.pixmap().isNull()
    assert diagram_box._add_button.isEnabled()


def test_controls_are_keyboard_reachable_and_named(diagram_box: CircuitDiagramBox) -> None:
    from PySide6.QtCore import Qt

    for widget in (
        diagram_box._add_button,
        diagram_box._replace_button,
        diagram_box._remove_button,
        diagram_box._caption_edit,
        diagram_box._source_edit,
    ):
        assert widget.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert diagram_box._preview.accessibleName() == "Circuit diagram preview"
    assert diagram_box._caption_edit.accessibleName() == "Circuit diagram caption"
    assert diagram_box._source_edit.accessibleName() == "Circuit diagram source or note"
