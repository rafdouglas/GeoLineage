"""Inspect dialog — table view of all _lineage entries for a GeoPackage."""

from __future__ import annotations

import logging
import os

from ..lineage_core.settings import LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.inspect_dialog")


def _get_base_class():
    """Return QDialog at runtime, object for static analysis."""
    try:
        from qgis.PyQt.QtWidgets import QDialog

        return QDialog
    except ImportError:
        return object


class InspectDialog(_get_base_class()):
    """Table view of all lineage entries for a selected GeoPackage.

    Inherits from QDialog at runtime.
    """

    # Column indices
    _COL_ID = 0
    _COL_LAYER = 1
    _COL_TYPE = 2
    _COL_TOOL = 3
    _COL_SUMMARY = 4
    _COL_EDIT_SUMMARY = 5
    _COL_TIME = 6
    _COL_PARENTS = 7
    _EDITABLE_COLS = {4: "operation_summary", 5: "edit_summary"}

    def __init__(self, gpkg_path: str, project_dir: str, dock_widget=None, parent=None) -> None:
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout

        super().__init__(parent)
        self._gpkg_path = gpkg_path
        self._project_dir = project_dir
        self._dock_widget = dock_widget
        self._updating = False

        self.setWindowTitle(f"Inspect Lineage: {os.path.basename(gpkg_path)}")
        self.setMinimumSize(800, 400)
        self.setAttribute(Qt.WA_DeleteOnClose)

        layout = QVBoxLayout(self)

        # Table
        self._build_table(layout)

        # Button row 1
        btn_row1 = QHBoxLayout()
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self._on_delete)
        btn_row1.addWidget(delete_btn)

        cleanup_btn = QPushButton("Cleanup...")
        cleanup_btn.clicked.connect(self._on_cleanup)
        btn_row1.addWidget(cleanup_btn)

        relink_btn = QPushButton("Relink...")
        relink_btn.clicked.connect(self._on_relink)
        btn_row1.addWidget(relink_btn)

        btn_row1.addStretch()
        layout.addLayout(btn_row1)

        # Button row 2
        btn_row2 = QHBoxLayout()
        if dock_widget is not None:
            graph_btn = QPushButton("View in Graph")
            graph_btn.clicked.connect(self._on_view_in_graph)
            btn_row2.addWidget(graph_btn)

        btn_row2.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row2.addWidget(close_btn)
        layout.addLayout(btn_row2)

        self._load_entries()

    def _build_table(self, parent_layout) -> None:
        from qgis.PyQt.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget

        headers = ["ID", "Layer", "Type", "Tool", "Summary", "Edit Summary", "Time", "Parents"]
        self._table = QTableWidget(0, len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSortingEnabled(True)
        self._table.cellChanged.connect(self._on_cell_changed)
        parent_layout.addWidget(self._table)

    def _load_entries(self) -> None:
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import QTableWidgetItem

        from ..lineage_manager.data_ops import read_all_entries

        self._updating = True
        self._table.setRowCount(0)

        entries = read_all_entries(self._gpkg_path)
        self._table.setRowCount(len(entries))

        for row, entry in enumerate(entries):
            items = [
                (self._COL_ID, str(entry.get("id", ""))),
                (self._COL_LAYER, entry.get("layer_name", "")),
                (self._COL_TYPE, entry.get("entry_type", "")),
                (self._COL_TOOL, entry.get("operation_tool", "") or ""),
                (self._COL_SUMMARY, entry.get("operation_summary", "")),
                (self._COL_EDIT_SUMMARY, entry.get("edit_summary", "") or ""),
                (self._COL_TIME, entry.get("created_at", "")),
                (self._COL_PARENTS, entry.get("parent_files", "") or ""),
            ]
            for col, text in items:
                item = QTableWidgetItem(str(text))
                if col not in self._EDITABLE_COLS:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self._table.setItem(row, col, item)

        self._updating = False

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._updating:
            return
        field = self._EDITABLE_COLS.get(col)
        if field is None:
            return

        from ..lineage_manager.data_ops import update_entry_field

        id_item = self._table.item(row, self._COL_ID)
        if id_item is None:
            return
        entry_id = int(id_item.text())
        new_value = self._table.item(row, col).text()
        try:
            update_entry_field(self._gpkg_path, entry_id, field, new_value)
        except Exception:
            logger.exception("Failed to update field %s for entry %d", field, entry_id)

    def _on_delete(self) -> None:
        from qgis.PyQt.QtWidgets import QMessageBox

        from ..lineage_manager.data_ops import delete_entry

        row = self._table.currentRow()
        if row < 0:
            return
        id_item = self._table.item(row, self._COL_ID)
        if id_item is None:
            return
        entry_id = int(id_item.text())

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete lineage entry {entry_id}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        delete_entry(self._gpkg_path, entry_id)
        self._load_entries()

    def _on_cleanup(self) -> None:
        from .cleanup_dialog import CleanupDialog

        dlg = CleanupDialog(self)
        dlg.exec_()
        self._load_entries()

    def _on_relink(self) -> None:
        from .relink_dialog import RelinkDialog

        dlg = RelinkDialog(self._gpkg_path, self._project_dir, self)
        dlg.exec_()
        self._load_entries()

    def _on_view_in_graph(self) -> None:
        if self._dock_widget is not None:
            self._dock_widget.show_lineage(self._gpkg_path, self._project_dir)
            self.close()
