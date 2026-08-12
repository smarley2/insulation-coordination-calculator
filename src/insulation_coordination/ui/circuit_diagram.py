"""Project-page editor for the one circuit diagram a project can carry."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from insulation_coordination.domain.attachments import ProjectImageAttachment
from insulation_coordination.project.image_attachments import (
    ImageAttachmentError,
    load_project_image,
)

#: Only formats the report can embed are offered.
IMAGE_FILE_FILTER = "Images (*.png *.jpg *.jpeg)"

_PREVIEW_MINIMUM_HEIGHT = 180


class CircuitDiagramBox(QGroupBox):
    """Add, replace, remove, and annotate the project circuit diagram.

    The widget owns no project state: every accepted edit is published as one
    immutable attachment, and a rejected file leaves the current one in place.
    """

    attachment_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__("Circuit diagram")
        self._attachment: ProjectImageAttachment | None = None
        # Decoded once per attachment: scaling for a repaint must not decode again.
        self._preview_source = QPixmap()

        layout = QHBoxLayout(self)

        self._preview = QLabel()
        self._preview.setMinimumHeight(_PREVIEW_MINIMUM_HEIGHT)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setAccessibleName("Circuit diagram preview")
        # A neutral field behind the image so a transparent PNG stays visible.
        self._preview.setStyleSheet("background-color: #f2f2f2; border: 1px solid #c8c8c8;")
        layout.addWidget(self._preview, 1)

        controls = QVBoxLayout()
        form = QFormLayout()
        self._caption_edit = QLineEdit()
        self._caption_edit.setAccessibleName("Circuit diagram caption")
        self._caption_edit.editingFinished.connect(self._on_text_edited)
        form.addRow("Caption:", self._caption_edit)
        self._source_edit = QLineEdit()
        self._source_edit.setAccessibleName("Circuit diagram source or note")
        self._source_edit.editingFinished.connect(self._on_text_edited)
        form.addRow("Source / note:", self._source_edit)
        controls.addLayout(form)

        buttons = QHBoxLayout()
        self._add_button = QPushButton("Add circuit diagram…")
        self._add_button.clicked.connect(self._on_choose_clicked)
        buttons.addWidget(self._add_button)
        self._replace_button = QPushButton("Replace…")
        self._replace_button.clicked.connect(self._on_choose_clicked)
        buttons.addWidget(self._replace_button)
        self._remove_button = QPushButton("Remove")
        self._remove_button.clicked.connect(self._on_remove_clicked)
        buttons.addWidget(self._remove_button)
        controls.addLayout(buttons)

        self._summary_label = QLabel()
        self._summary_label.setAccessibleName("Circuit diagram summary")
        self._summary_label.setWordWrap(True)
        controls.addWidget(self._summary_label)
        controls.addStretch(1)
        layout.addLayout(controls, 1)

        self.set_attachment(None)

    @property
    def attachment(self) -> ProjectImageAttachment | None:
        return self._attachment

    @property
    def summary(self) -> str:
        return self._summary_label.text()

    def set_attachment(self, attachment: ProjectImageAttachment | None) -> None:
        """Show a project's attachment without reporting it back as an edit."""
        self._attachment = attachment
        self._preview_source = QPixmap()
        if attachment is not None:
            self._preview_source.loadFromData(attachment.decoded_bytes())
        for edit, text in (
            (self._caption_edit, "" if attachment is None else attachment.caption),
            (self._source_edit, "" if attachment is None else attachment.source_note),
        ):
            edit.blockSignals(True)
            edit.setText(text)
            edit.blockSignals(False)
        self._add_button.setEnabled(attachment is None)
        self._replace_button.setEnabled(attachment is not None)
        self._remove_button.setEnabled(attachment is not None)
        self._summary_label.setText(_summary_of(attachment))
        self._render_preview()

    def attach_path(self, path: Path) -> None:
        """Attach one image file, keeping the caption and note already typed.

        Raises ``ImageAttachmentError`` and changes nothing when the file is not
        a usable image.
        """
        attachment = load_project_image(
            Path(path),
            caption=self._caption_edit.text().strip(),
            source_note=self._source_edit.text().strip(),
        )
        self._publish(attachment)

    def remove(self) -> None:
        if self._attachment is None:
            return
        self._publish(None)

    def _publish(self, attachment: ProjectImageAttachment | None) -> None:
        self.set_attachment(attachment)
        self.attachment_changed.emit(attachment)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render_preview()

    def _render_preview(self) -> None:
        if self._preview_source.isNull():
            self._preview.setPixmap(QPixmap())
            self._preview.setText("No circuit diagram attached")
            return
        self._preview.setText("")
        # Bounded by the source as well as the widget: a small diagram is shown
        # at its own size rather than blown up into a blur.
        self._preview.setPixmap(
            self._preview_source.scaled(
                self._preview.size().boundedTo(self._preview_source.size()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _on_text_edited(self) -> None:
        """Caption and note are metadata: the image bytes and hash never change."""
        if self._attachment is None:
            return
        updated = self._attachment.model_copy(
            update={
                "caption": self._caption_edit.text().strip(),
                "source_note": self._source_edit.text().strip(),
            }
        )
        if updated == self._attachment:
            return
        self._publish(updated)

    def _on_choose_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Circuit Diagram", "", IMAGE_FILE_FILTER)
        if not path:
            return
        try:
            self.attach_path(Path(path))
        except ImageAttachmentError as error:
            QMessageBox.warning(self, "Circuit Diagram", str(error))

    def _on_remove_clicked(self) -> None:
        if self._attachment is None:
            return
        reply = QMessageBox.question(
            self,
            "Remove Circuit Diagram",
            "Remove the circuit diagram from this project?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.remove()


def _summary_of(attachment: ProjectImageAttachment | None) -> str:
    if attachment is None:
        return "No image attached."
    kilobytes = attachment.byte_size / 1024
    return (
        f"{attachment.original_filename} — {attachment.format.upper()}, "
        f"{attachment.width_px}×{attachment.height_px} px, {kilobytes:.0f} kB"
    )
