"""GeoLineage QGIS Plugin — main plugin class.

Provides toolbar toggle for enabling/disabling lineage recording.
Persists toggle state in project custom properties.
"""

import contextlib
import logging
import os

from .lineage_core.settings import LOGGER_NAME

logger = logging.getLogger(f"{LOGGER_NAME}.plugin")

# Project custom property key for toggle state
_PROJECT_PROPERTY_KEY = "geolineage_enabled"


class GeoLineagePlugin:
    """QGIS plugin for GeoPackage lineage tracking."""

    def __init__(self, iface) -> None:
        self.iface = iface
        self.toolbar = None
        self.toggle_action = None
        self._enabled = False
        self.dock_widget = None
        self.show_lineage_action = None
        self.manage_action = None
        self.settings_action = None
        self.layer_context_menu_action = None

    def initGui(self) -> None:
        """Called by QGIS when the plugin is loaded. Sets up toolbar and actions."""
        from qgis.core import QgsProject
        from qgis.PyQt.QtGui import QIcon
        from qgis.PyQt.QtWidgets import QAction

        # Create toolbar
        self.toolbar = self.iface.addToolBar("GeoLineage")
        self.toolbar.setObjectName("GeoLineageToolbar")

        # Create toggle action
        icon_path = os.path.join(os.path.dirname(__file__), "resources")
        self.toggle_action = QAction(
            QIcon(os.path.join(icon_path, "icon_off.png")),
            "GeoLineage is currently not recording. Click to start recording.",
            self.iface.mainWindow(),
        )
        self.toggle_action.setCheckable(True)
        self.toggle_action.setChecked(False)
        self.toggle_action.toggled.connect(self._on_toggle)
        self.toolbar.addAction(self.toggle_action)

        # Add to Plugins menu
        self.iface.addPluginToMenu("&GeoLineage", self.toggle_action)

        # Show Lineage Graph action
        self.show_lineage_action = QAction(
            "Show Lineage Graph",
            self.iface.mainWindow(),
        )
        self.show_lineage_action.triggered.connect(self._show_lineage_for_active_layer)
        self.iface.addPluginToMenu("&GeoLineage", self.show_lineage_action)

        # Manage Lineage action
        self.manage_action = QAction(
            "Manage Lineage...",
            self.iface.mainWindow(),
        )
        self.manage_action.triggered.connect(self._show_manage_dialog)
        self.iface.addPluginToMenu("&GeoLineage", self.manage_action)

        # Settings action
        self.settings_action = QAction(
            "Settings",
            self.iface.mainWindow(),
        )
        self.settings_action.triggered.connect(self._show_settings_dialog)
        self.iface.addPluginToMenu("&GeoLineage", self.settings_action)

        # Layer tree context menu entry
        from qgis.core import QgsMapLayer

        self.layer_context_menu_action = QAction("Show Lineage", self.iface.mainWindow())
        self.layer_context_menu_action.triggered.connect(self._show_lineage_from_context_menu)
        with contextlib.suppress(Exception):
            self.iface.addCustomActionForLayerType(self.layer_context_menu_action, "", QgsMapLayer.VectorLayer, True)

        # Restore state from project on load
        QgsProject.instance().readProject.connect(self._on_project_read)

        # Restore from current project if already open
        self._restore_toggle_state()

        logger.info("GeoLineage plugin initialized")

    def unload(self) -> None:
        """Called by QGIS when the plugin is unloaded. Cleans up everything."""
        from qgis.core import QgsProject

        # Uninstall hooks if active
        if self._enabled:
            self._disable_recording()

        # Disconnect project signal
        with contextlib.suppress(TypeError, RuntimeError):
            QgsProject.instance().readProject.disconnect(self._on_project_read)

        # Remove viewer dock widget
        if self.dock_widget:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None

        # Remove show lineage action
        if self.show_lineage_action:
            self.iface.removePluginMenu("&GeoLineage", self.show_lineage_action)
            self.show_lineage_action = None

        # Remove manage action
        if self.manage_action:
            self.iface.removePluginMenu("&GeoLineage", self.manage_action)
            self.manage_action = None

        # Remove settings action
        if self.settings_action:
            self.iface.removePluginMenu("&GeoLineage", self.settings_action)
            self.settings_action = None

        # Remove layer context menu action
        if self.layer_context_menu_action:
            with contextlib.suppress(Exception):
                self.iface.removeCustomActionForLayerType(self.layer_context_menu_action)
            self.layer_context_menu_action = None

        # Remove GUI elements
        if self.toggle_action:
            self.iface.removePluginMenu("&GeoLineage", self.toggle_action)
        if self.toolbar:
            del self.toolbar
            self.toolbar = None

        self.toggle_action = None
        logger.info("GeoLineage plugin unloaded")

    def _on_toggle(self, checked: bool) -> None:
        """Handle toggle action state change."""
        if checked:
            self._enable_recording()
        else:
            self._disable_recording()

        # Save state to project
        self._save_toggle_state(checked)

        # Update icon
        self._update_icon(checked)

    def _enable_recording(self) -> None:
        """Enable lineage recording by installing hooks."""
        from .lineage_core.hooks import install_hooks

        install_hooks()
        self._enabled = True
        logger.info("Lineage recording enabled")

    def _disable_recording(self) -> None:
        """Disable lineage recording by uninstalling hooks."""
        from .lineage_core.hooks import uninstall_hooks

        uninstall_hooks()
        self._enabled = False
        logger.info("Lineage recording disabled")

    def _save_toggle_state(self, enabled: bool) -> None:
        """Save toggle state to current project's custom properties."""
        from qgis.core import QgsProject

        project = QgsProject.instance()
        project.writeEntry("GeoLineage", _PROJECT_PROPERTY_KEY, enabled)

    def _restore_toggle_state(self) -> None:
        """Restore toggle state from current project's custom properties."""
        from qgis.core import QgsProject

        project = QgsProject.instance()
        enabled, ok = project.readBoolEntry("GeoLineage", _PROJECT_PROPERTY_KEY, False)
        if ok and enabled and self.toggle_action:
            # Set checked state — this will trigger _on_toggle
            self.toggle_action.setChecked(True)

    def _on_project_read(self) -> None:
        """Handle project load — restore toggle state."""
        self._restore_toggle_state()

    def _show_lineage_for_active_layer(self) -> None:
        """Show lineage graph for the currently active layer."""
        from .lineage_retrieval.path_resolver import extract_gpkg_path

        layer = self.iface.activeLayer()
        if layer is None:
            self.iface.messageBar().pushWarning("GeoLineage", "No active layer selected.")
            return

        gpkg_path = extract_gpkg_path(layer.source())
        if gpkg_path is None:
            self.iface.messageBar().pushWarning("GeoLineage", "Active layer is not backed by a GeoPackage file.")
            return

        self._show_lineage_dock(gpkg_path)

    def _show_lineage_from_context_menu(self) -> None:
        """Show lineage graph from layer tree context menu."""
        from .lineage_retrieval.path_resolver import extract_gpkg_path

        layer = self.iface.activeLayer()
        if layer is None:
            return

        gpkg_path = extract_gpkg_path(layer.source())
        if gpkg_path is None:
            self.iface.messageBar().pushInfo("GeoLineage", "Selected layer is not a GeoPackage.")
            return

        self._show_lineage_dock(gpkg_path)

    def _show_lineage_dock(self, gpkg_path: str) -> None:
        """Create or reuse dock widget and show lineage for the given path."""
        from qgis.core import QgsProject
        from qgis.PyQt.QtCore import Qt

        if self.dock_widget is None:
            from .lineage_viewer.dock_widget import LineageDockWidget

            self.dock_widget = LineageDockWidget(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)

        project_dir = QgsProject.instance().homePath() or os.path.dirname(gpkg_path)
        self.dock_widget.show_lineage(gpkg_path, project_dir)
        self.dock_widget.show()

    def _show_manage_dialog(self) -> None:
        """Open InspectDialog for the active layer's GeoPackage."""
        from qgis.core import QgsProject

        from .lineage_manager.inspect_dialog import InspectDialog
        from .lineage_retrieval.path_resolver import extract_gpkg_path

        layer = self.iface.activeLayer()
        if layer is None:
            self.iface.messageBar().pushWarning("GeoLineage", "No active layer selected.")
            return

        gpkg_path = extract_gpkg_path(layer.source())
        if gpkg_path is None:
            self.iface.messageBar().pushWarning("GeoLineage", "Active layer is not backed by a GeoPackage file.")
            return

        project_dir = QgsProject.instance().homePath() or os.path.dirname(gpkg_path)
        dlg = InspectDialog(gpkg_path, project_dir, dock_widget=self.dock_widget, parent=self.iface.mainWindow())
        dlg.exec_()

    def _show_settings_dialog(self) -> None:
        """Open SettingsDialog."""
        from .lineage_manager.settings_dialog import SettingsDialog

        dlg = SettingsDialog(parent=self.iface.mainWindow())
        dlg.exec_()

    def _update_icon(self, enabled: bool) -> None:
        """Update toggle action icon and tooltip based on state."""
        from qgis.PyQt.QtGui import QIcon

        icon_path = os.path.join(os.path.dirname(__file__), "resources")
        icon_file = "icon_on.png" if enabled else "icon_off.png"
        if self.toggle_action:
            self.toggle_action.setIcon(QIcon(os.path.join(icon_path, icon_file)))
            if enabled:
                self.toggle_action.setToolTip("GeoLineage is currently recording. Click to pause.")
            else:
                self.toggle_action.setToolTip("GeoLineage is currently not recording. Click to start recording.")
