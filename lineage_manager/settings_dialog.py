"""Settings dialog — configure username for lineage recording."""

from __future__ import annotations

import getpass
import logging

from ..lineage_core.settings import LOGGER_NAME, SETTING_USERNAME

logger = logging.getLogger(f"{LOGGER_NAME}.settings_dialog")


def _get_base_class():
    """Return QDialog at runtime, object for static analysis."""
    try:
        from qgis.PyQt.QtWidgets import QDialog

        return QDialog
    except ImportError:
        return object


class SettingsDialog(_get_base_class()):
    """Configure username recording for lineage entries.

    Inherits from QDialog at runtime.
    """

    def __init__(self, parent=None) -> None:
        from qgis.core import QgsSettings
        from qgis.PyQt.QtWidgets import (
            QCheckBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
        )

        super().__init__(parent)
        self.setWindowTitle("GeoLineage Settings")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        # Username checkbox
        self._checkbox = QCheckBox("Record username in lineage entries")
        layout.addWidget(self._checkbox)

        # Username input
        user_layout = QHBoxLayout()
        user_layout.addWidget(QLabel("Username:"))
        self._username_edit = QLineEdit()
        self._username_edit.setPlaceholderText(f"Default: {getpass.getuser()}")
        user_layout.addWidget(self._username_edit)
        layout.addLayout(user_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(ok_btn)
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        # Load current settings
        settings = QgsSettings()
        current_username = settings.value(SETTING_USERNAME, "", str)
        if current_username:
            self._checkbox.setChecked(True)
            self._username_edit.setText(current_username)
        else:
            self._checkbox.setChecked(False)

    def _on_accept(self) -> None:
        from qgis.core import QgsSettings

        settings = QgsSettings()
        if self._checkbox.isChecked():
            username = self._username_edit.text().strip()
            if not username:
                username = getpass.getuser()
            settings.setValue(SETTING_USERNAME, username)
        else:
            settings.setValue(SETTING_USERNAME, "")
        self.accept()
