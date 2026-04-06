"""Relink dialog — fix broken parent paths in lineage entries."""

from __future__ import annotations

import logging
import os

from ..lineage_core.settings import LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.relink_dialog")


def _get_base_class():
    """Return QDialog at runtime, object for static analysis."""
    try:
        from qgis.PyQt.QtWidgets import QDialog

        return QDialog
    except ImportError:
        return object


class RelinkDialog(_get_base_class()):
    """Fix broken parent paths in lineage entries.

    Inherits from QDialog at runtime.
    """

    def __init__(self, gpkg_path: str, project_dir: str, parent=None) -> None:
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import (
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QPushButton,
            QVBoxLayout,
        )

        super().__init__(parent)
        self._gpkg_path = gpkg_path
        self._project_dir = project_dir
        self._broken_items: list[dict] = []

        self.setWindowTitle(f"Relink Broken Parents: {os.path.basename(gpkg_path)}")
        self.setMinimumSize(600, 400)
        self.setAttribute(Qt.WA_DeleteOnClose)

        layout = QVBoxLayout(self)

        # Broken paths list
        layout.addWidget(QLabel("Broken parent paths:"))
        self._list_widget = QListWidget()
        layout.addWidget(self._list_widget)

        # Single relink buttons
        single_layout = QHBoxLayout()
        browse_btn = QPushButton("Browse New Location")
        browse_btn.clicked.connect(self._on_browse_replacement)
        single_layout.addWidget(browse_btn)
        relink_btn = QPushButton("Relink Selected")
        relink_btn.clicked.connect(self._on_relink_selected)
        single_layout.addWidget(relink_btn)
        single_layout.addStretch()
        layout.addLayout(single_layout)

        # Batch relink group
        batch_group = QGroupBox("Batch Prefix Replacement")
        batch_layout = QVBoxLayout(batch_group)

        old_layout = QHBoxLayout()
        old_layout.addWidget(QLabel("Old prefix:"))
        self._old_prefix_edit = QLineEdit()
        old_layout.addWidget(self._old_prefix_edit)
        batch_layout.addLayout(old_layout)

        new_layout = QHBoxLayout()
        new_layout.addWidget(QLabel("New prefix:"))
        self._new_prefix_edit = QLineEdit()
        new_layout.addWidget(self._new_prefix_edit)
        batch_layout.addLayout(new_layout)

        batch_btn_layout = QHBoxLayout()
        batch_btn = QPushButton("Batch Relink")
        batch_btn.clicked.connect(self._on_batch_relink)
        batch_btn_layout.addWidget(batch_btn)
        batch_btn_layout.addStretch()
        batch_layout.addLayout(batch_btn_layout)

        layout.addWidget(batch_group)

        # Close button
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)

        # Replacement path storage
        self._replacement_path: str | None = None

        self._scan_broken_parents()

    def _scan_broken_parents(self) -> None:
        from ..lineage_manager.data_ops import find_broken_parents

        self._list_widget.clear()
        self._broken_items = find_broken_parents(self._gpkg_path, self._project_dir)
        for item in self._broken_items:
            self._list_widget.addItem(f"Entry {item['entry_id']}: {item['parent_path']}")

    def _on_browse_replacement(self) -> None:
        from qgis.PyQt.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "Select Replacement File", "", "GeoPackage (*.gpkg);;All Files (*)")
        if path:
            self._replacement_path = path

    def _on_relink_selected(self) -> None:
        from qgis.PyQt.QtWidgets import QMessageBox

        from ..lineage_manager.data_ops import relink_parent

        row = self._list_widget.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a broken path.")
            return

        if not self._replacement_path:
            QMessageBox.warning(self, "No Replacement", "Please browse for a replacement file first.")
            return

        item = self._broken_items[row]
        relink_parent(self._gpkg_path, item["entry_id"], item["parent_path"], self._replacement_path)
        self._replacement_path = None
        self._scan_broken_parents()

    def _on_batch_relink(self) -> None:
        from qgis.PyQt.QtWidgets import QMessageBox

        from ..lineage_manager.data_ops import batch_relink_prefix

        old_prefix = self._old_prefix_edit.text().strip()
        new_prefix = self._new_prefix_edit.text().strip()

        if not old_prefix:
            QMessageBox.warning(self, "Missing Prefix", "Please enter the old prefix.")
            return

        count = batch_relink_prefix(self._gpkg_path, old_prefix, new_prefix)
        QMessageBox.information(self, "Batch Relink Complete", f"Modified {count} entry(ies).")
        self._scan_broken_parents()
