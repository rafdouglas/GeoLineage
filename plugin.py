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
            "Toggle GeoLineage Recording",
            self.iface.mainWindow(),
        )
        self.toggle_action.setCheckable(True)
        self.toggle_action.setChecked(False)
        self.toggle_action.toggled.connect(self._on_toggle)
        self.toolbar.addAction(self.toggle_action)

        # Add to Plugins menu
        self.iface.addPluginToMenu("&GeoLineage", self.toggle_action)

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

    def _update_icon(self, enabled: bool) -> None:
        """Update toggle action icon based on state."""
        from qgis.PyQt.QtGui import QIcon

        icon_path = os.path.join(os.path.dirname(__file__), "resources")
        icon_file = "icon_on.png" if enabled else "icon_off.png"
        if self.toggle_action:
            self.toggle_action.setIcon(QIcon(os.path.join(icon_path, icon_file)))
