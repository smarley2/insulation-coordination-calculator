"""The preview a reviewer reads, and warns them, before copying an advisory prompt out.

Its own module rather than another few hundred lines of ``clause_fact_review``: nothing here
knows what a route or a fact is, it shows one string and copies that same string.
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

#: Shown above the prompt, before any copy is possible. The generated text carries licensed
#: clause wording verbatim -- that is what makes the prompt useful and what makes pasting it into
#: a third-party service a disclosure. Stated as the boundary it is rather than as a footnote:
#: the application contacts nobody, so the whole decision is the reviewer's and they have to be
#: told what they are deciding about.
LICENCE_WARNING = (
    "This prompt quotes licensed clause text verbatim. Generating it is local and offline: no "
    "provider is contacted, nothing is sent anywhere, and the text is not written to any file, "
    "log or audit record -- it exists here and, if you press Copy prompt, on your clipboard. "
    "Pasting it into an external AI service discloses licensed material to that service. Copy "
    "it only if your IEC licence and your company policy allow that."
)

#: Restated beside the copy button, because the prompt itself is the only other place it is said
#: and the reviewer reading this dialog is the person the rule is about.
_ADVISORY_NOTE = (
    "Whatever the model answers is advice. You still read the clause and press Author fact, "
    "Record: states nothing this route models, and Record completion yourself."
)


class ClauseFactAiPromptDialog(QDialog):
    """A read-only preview of one generated prompt, with an explicit copy action.

    Nothing reaches the clipboard until the reviewer presses Copy prompt: copying on open would
    put licensed text on the clipboard of anyone who merely looked at the preview.
    """

    def __init__(self, prompt: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI review prompt for this route")

        self.warning = QLabel(LICENCE_WARNING, self)
        self.warning.setWordWrap(True)
        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setPlainText(prompt)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        advisory = QLabel(_ADVISORY_NOTE, self)
        advisory.setWordWrap(True)
        self._status = QLabel("", self)
        self._status.setWordWrap(True)

        self.copy_button = QPushButton("Copy prompt", self)
        self.copy_button.clicked.connect(self.copy_prompt)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        actions = QHBoxLayout()
        actions.addWidget(self.copy_button)
        actions.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self.warning)
        layout.addWidget(self.preview, 1)
        layout.addWidget(advisory)
        layout.addWidget(self._status)
        layout.addLayout(actions)
        self.resize(900, 720)

    @property
    def prompt(self) -> str:
        """Exactly what the preview shows, which is exactly what Copy prompt writes out."""

        return self.preview.toPlainText()

    @property
    def status_text(self) -> str:
        return self._status.text()

    def copy_prompt(self) -> None:
        QGuiApplication.clipboard().setText(self.prompt)
        self._status.setText(
            "Copied to the clipboard. It is not stored anywhere else; close this and it is gone."
        )


__all__ = ["LICENCE_WARNING", "ClauseFactAiPromptDialog"]
