"""Toolbar with viewer-specific actions for the lineage graph viewer."""

from __future__ import annotations


def _get_base_class():
    """Return QToolBar at runtime, object for static analysis."""
    try:
        from qgis.PyQt.QtWidgets import QToolBar

        return QToolBar
    except ImportError:
        return object


class ViewerToolbar(_get_base_class()):
    """Toolbar for the lineage graph viewer.

    Inherits from QToolBar at runtime.
    """

    def __init__(self, parent=None) -> None:
        from qgis.PyQt.QtWidgets import QAction, QLineEdit

        super().__init__("Lineage Viewer", parent)

        self._on_fit_requested = None
        self._on_zoom_in_requested = None
        self._on_zoom_out_requested = None
        self._on_reload_requested = None
        self._on_search_changed = None
        self._on_export_requested = None

        # Fit to view
        self._fit_action = QAction("Fit to View", self)
        self._fit_action.setToolTip("Fit graph to view")
        self._fit_action.triggered.connect(lambda: self._emit_fit())
        self.addAction(self._fit_action)

        # Zoom in
        self._zoom_in_action = QAction("Zoom In", self)
        self._zoom_in_action.setToolTip("Zoom in")
        self._zoom_in_action.triggered.connect(lambda: self._emit_zoom_in())
        self.addAction(self._zoom_in_action)

        # Zoom out
        self._zoom_out_action = QAction("Zoom Out", self)
        self._zoom_out_action.setToolTip("Zoom out")
        self._zoom_out_action.triggered.connect(lambda: self._emit_zoom_out())
        self.addAction(self._zoom_out_action)

        # Reload
        self._reload_action = QAction("Reload", self)
        self._reload_action.setToolTip("Reload lineage graph")
        self._reload_action.triggered.connect(lambda: self._emit_reload())
        self.addAction(self._reload_action)

        self.addSeparator()

        # Search
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search by filename...")
        self._search_input.setMaximumWidth(200)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self.addWidget(self._search_input)

        self.addSeparator()

        # Export actions
        self._export_dot_action = QAction("Export DOT", self)
        self._export_dot_action.triggered.connect(lambda: self._emit_export("dot"))
        self.addAction(self._export_dot_action)

        self._export_svg_action = QAction("Export SVG", self)
        self._export_svg_action.triggered.connect(lambda: self._emit_export("svg"))
        self.addAction(self._export_svg_action)

        self._export_png_action = QAction("Export PNG", self)
        self._export_png_action.triggered.connect(lambda: self._emit_export("png"))
        self.addAction(self._export_png_action)

    def set_callbacks(
        self,
        on_fit=None,
        on_zoom_in=None,
        on_zoom_out=None,
        on_reload=None,
        on_search_changed=None,
        on_export=None,
    ) -> None:
        """Set callback functions for toolbar events."""
        self._on_fit_requested = on_fit
        self._on_zoom_in_requested = on_zoom_in
        self._on_zoom_out_requested = on_zoom_out
        self._on_reload_requested = on_reload
        self._on_search_changed = on_search_changed
        self._on_export_requested = on_export

    def search_text(self) -> str:
        """Return current search text."""
        return self._search_input.text()

    def _on_search_text_changed(self, text: str) -> None:
        if self._on_search_changed:
            self._on_search_changed(text)

    def _emit_fit(self) -> None:
        if self._on_fit_requested:
            self._on_fit_requested()

    def _emit_zoom_in(self) -> None:
        if self._on_zoom_in_requested:
            self._on_zoom_in_requested()

    def _emit_zoom_out(self) -> None:
        if self._on_zoom_out_requested:
            self._on_zoom_out_requested()

    def _emit_reload(self) -> None:
        if self._on_reload_requested:
            self._on_reload_requested()

    def _emit_export(self, fmt: str) -> None:
        if self._on_export_requested:
            self._on_export_requested(fmt)
