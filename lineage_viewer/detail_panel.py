"""Side panel showing lineage entry details for the selected node."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..lineage_retrieval.graph_builder import LineageNode

from .graph_node_item import STATUS_COLORS


def _get_base_class():
    """Return QWidget at runtime, object for static analysis."""
    try:
        from qgis.PyQt.QtWidgets import QWidget

        return QWidget
    except ImportError:
        return object


class DetailPanel(_get_base_class()):
    """Panel displaying lineage entry details for a selected node.

    Inherits from QWidget at runtime.
    """

    def __init__(self, parent=None) -> None:
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

        super().__init__(parent)

        self._on_parent_clicked = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header area
        self._header_label = QLabel("Select a node")
        self._header_label.setWordWrap(True)
        self._header_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self._header_label)

        self._path_label = QLabel("")
        self._path_label.setWordWrap(True)
        self._path_label.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(self._path_label)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._status_label)

        # Scrollable entries area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll)

        self.setMinimumWidth(250)

    def set_on_parent_clicked(self, callback) -> None:
        """Set callback for when a parent link is clicked."""
        self._on_parent_clicked = callback

    def set_node(self, node: LineageNode) -> None:
        """Populate panel with this node's entries."""
        from qgis.PyQt.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

        self._header_label.setText(node.filename)
        self._path_label.setText(node.path)

        color = STATUS_COLORS.get(node.status, "#9E9E9E")
        self._status_label.setText(f"Status: {node.status}")
        self._status_label.setStyleSheet(
            f"font-size: 11px; color: white; background-color: {color}; padding: 2px 6px; border-radius: 3px;"
        )

        # Clear previous entries
        self._clear_scroll()

        if not node.entries:
            no_entries = QLabel("No lineage entries")
            no_entries.setStyleSheet("color: #999; font-style: italic; padding: 16px;")
            self._scroll_layout.addWidget(no_entries)
            return

        for entry in node.entries:
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setStyleSheet("QFrame { border: 1px solid #ddd; border-radius: 4px; padding: 8px; margin: 2px; }")
            entry_layout = QVBoxLayout(frame)

            # Entry type
            entry_type = entry.get("entry_type", "unknown")
            type_label = QLabel(f"Type: {entry_type}")
            type_label.setStyleSheet("font-weight: bold;")
            entry_layout.addWidget(type_label)

            # Operation tool
            op_tool = entry.get("operation_tool", "")
            if op_tool:
                entry_layout.addWidget(QLabel(f"Tool: {op_tool}"))

            # Timestamp
            created_at = entry.get("created_at", "")
            if created_at:
                entry_layout.addWidget(QLabel(f"Time: {created_at}"))

            # Parent files
            raw_parents = entry.get("parent_files", "")
            if raw_parents:
                try:
                    parents = json.loads(raw_parents) if isinstance(raw_parents, str) else raw_parents
                except (json.JSONDecodeError, TypeError):
                    parents = []

                if parents:
                    entry_layout.addWidget(QLabel("Parents:"))
                    for parent_path in parents:
                        btn = QPushButton(parent_path)
                        btn.setFlat(True)
                        btn.setStyleSheet("text-align: left; color: #1565C0; text-decoration: underline;")
                        btn.clicked.connect(lambda checked, p=parent_path: self._handle_parent_click(p))
                        entry_layout.addWidget(btn)

            # Parameters
            raw_params = entry.get("parameters", "")
            if raw_params:
                try:
                    params = json.loads(raw_params) if isinstance(raw_params, str) else raw_params
                    params_text = json.dumps(params, indent=2)
                except (json.JSONDecodeError, TypeError):
                    params_text = str(raw_params)
                params_label = QLabel(f"Parameters:\n{params_text}")
                params_label.setWordWrap(True)
                params_label.setStyleSheet(
                    "font-size: 10px; font-family: monospace; background: #f5f5f5; padding: 4px;"
                )
                entry_layout.addWidget(params_label)

            self._scroll_layout.addWidget(frame)

    def clear(self) -> None:
        """Reset panel to empty state."""
        self._header_label.setText("Select a node")
        self._path_label.setText("")
        self._status_label.setText("")
        self._status_label.setStyleSheet("font-size: 11px;")
        self._clear_scroll()

    def _clear_scroll(self) -> None:
        """Remove all widgets from scroll area."""
        while self._scroll_layout.count():
            child = self._scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _handle_parent_click(self, parent_path: str) -> None:
        """Handle click on a parent file link."""
        if self._on_parent_clicked:
            self._on_parent_clicked(parent_path)
