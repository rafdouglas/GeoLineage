"""Cleanup dialog — drop _lineage + _lineage_meta tables from GeoPackages."""

from __future__ import annotations

import logging

from ..lineage_core.settings import LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.cleanup_dialog")


def _get_base_class():
    """Return QDialog at runtime, object for static analysis."""
    try:
        from qgis.PyQt.QtWidgets import QDialog

        return QDialog
    except ImportError:
        return object


class CleanupDialog(_get_base_class()):
    """Drop lineage tables from one or many GeoPackages.

    Inherits from QDialog at runtime.
    """

    def __init__(self, parent=None) -> None:
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import (
            QButtonGroup,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QRadioButton,
            QVBoxLayout,
        )

        super().__init__(parent)
        self.setWindowTitle("Cleanup Lineage Tables")
        self.setMinimumWidth(500)
        self.setAttribute(Qt.WA_DeleteOnClose)

        layout = QVBoxLayout(self)

        # Mode selection
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Mode:"))
        self._single_radio = QRadioButton("Single File")
        self._batch_radio = QRadioButton("Batch (directory)")
        self._single_radio.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._single_radio)
        self._mode_group.addButton(self._batch_radio)
        mode_layout.addWidget(self._single_radio)
        mode_layout.addWidget(self._batch_radio)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        # Path input
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Path:"))
        self._path_edit = QLineEdit()
        path_layout.addWidget(self._path_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        # Action buttons
        btn_layout = QHBoxLayout()
        cleanup_btn = QPushButton("Clean Up")
        cleanup_btn.clicked.connect(self._on_cleanup)
        btn_layout.addWidget(cleanup_btn)
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_browse(self) -> None:
        from qgis.PyQt.QtWidgets import QFileDialog

        if self._single_radio.isChecked():
            path, _ = QFileDialog.getOpenFileName(self, "Select GeoPackage", "", "GeoPackage (*.gpkg)")
        else:
            path = QFileDialog.getExistingDirectory(self, "Select Directory")

        if path:
            self._path_edit.setText(path)

    def _on_cleanup(self) -> None:
        from qgis.PyQt.QtWidgets import QMessageBox

        path = self._path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "No Path", "Please select a file or directory.")
            return

        if self._single_radio.isChecked():
            self._cleanup_single(path)
        else:
            self._cleanup_batch(path)

    def _cleanup_single(self, path: str) -> None:
        from qgis.PyQt.QtWidgets import QMessageBox

        from ..lineage_manager.data_ops import drop_lineage_tables

        reply = QMessageBox.question(
            self,
            "Confirm Cleanup",
            f"Drop lineage tables from:\n{path}\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            drop_lineage_tables(path)
            QMessageBox.information(self, "Done", "Lineage tables dropped successfully.")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to drop tables:\n{exc}")

    def _cleanup_batch(self, directory: str) -> None:
        import os

        from qgis.PyQt.QtWidgets import QMessageBox

        from ..lineage_manager.data_ops import batch_drop_lineage

        gpkg_count = sum(1 for f in os.listdir(directory) if f.endswith(".gpkg"))
        if gpkg_count == 0:
            QMessageBox.information(self, "No Files", "No .gpkg files found in directory.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Batch Cleanup",
            f"Drop lineage tables from {gpkg_count} GeoPackage file(s) in:\n{directory}\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        results = batch_drop_lineage(directory)
        successes = sum(1 for r in results if r["success"])
        failures = sum(1 for r in results if not r["success"])

        summary = f"Processed {len(results)} file(s):\n  Successes: {successes}\n  Failures: {failures}"
        if failures:
            failed_files = "\n".join(f"  - {r['path']}: {r['error']}" for r in results if not r["success"])
            summary += f"\n\nFailed files:\n{failed_files}"

        QMessageBox.information(self, "Batch Cleanup Results", summary)
