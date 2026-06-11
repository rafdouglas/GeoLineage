"""Tests for GeoLineagePlugin._restore_toggle_state reconcile (issue 1.4).

The reconcile must run unconditionally on project load so recording does not
leak across a project switch: a project with the flag off (or unset) must turn
recording OFF, and the reconcile must never persist state (which would dirty a
freshly loaded project).

QGIS is mocked via patch.dict(sys.modules, ...) in the established style of
test_ui_enhancements.py. The recording/icon helper methods are replaced with
mocks so the test exercises only the reconcile orchestration, QGIS-free.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_plugin(flag_value: bool, flag_ok: bool = True):
    """Build a GeoLineagePlugin with a mocked QgsProject returning the flag.

    Returns (plugin, project_mock). The four helpers touched by the reconcile
    (_enable_recording / _disable_recording / _update_icon / _save_toggle_state)
    are replaced with MagicMocks so we observe orchestration without QGIS.
    """
    project = MagicMock()
    project.readBoolEntry.return_value = (flag_value, flag_ok)
    qgis_core = MagicMock()
    qgis_core.QgsProject.instance.return_value = project
    qgis = MagicMock()
    qgis.core = qgis_core

    with patch.dict("sys.modules", {"qgis": qgis, "qgis.core": qgis_core}):
        from GeoLineage.plugin import GeoLineagePlugin

        plugin = GeoLineagePlugin(iface=MagicMock())
        plugin.toggle_action = MagicMock()
        plugin._enable_recording = MagicMock()
        plugin._disable_recording = MagicMock()
        plugin._update_icon = MagicMock()
        plugin._save_toggle_state = MagicMock()
        plugin._restore_toggle_state()
    return plugin


def test_restore_disables_when_flag_false():
    """The bug: switching to a project with the flag off must stop recording."""
    plugin = _make_plugin(flag_value=False)

    plugin._disable_recording.assert_called_once()
    plugin._enable_recording.assert_not_called()
    plugin.toggle_action.setChecked.assert_called_once_with(False)
    plugin._update_icon.assert_called_once_with(False)


def test_restore_disables_when_flag_unset():
    """Flag absent (ok=False) defaults to off → recording disabled."""
    plugin = _make_plugin(flag_value=False, flag_ok=False)

    plugin._disable_recording.assert_called_once()
    plugin._enable_recording.assert_not_called()
    plugin.toggle_action.setChecked.assert_called_once_with(False)


def test_restore_enables_when_flag_true():
    plugin = _make_plugin(flag_value=True)

    plugin._enable_recording.assert_called_once()
    plugin._disable_recording.assert_not_called()
    plugin.toggle_action.setChecked.assert_called_once_with(True)
    plugin._update_icon.assert_called_once_with(True)


def test_restore_never_saves_state():
    """Reconcile must not persist state in either direction."""
    plugin_off = _make_plugin(flag_value=False)
    plugin_off._save_toggle_state.assert_not_called()

    plugin_on = _make_plugin(flag_value=True)
    plugin_on._save_toggle_state.assert_not_called()


def test_restore_blocks_signals_during_setchecked():
    """setChecked must be wrapped in blockSignals so _on_toggle does not fire."""
    plugin = _make_plugin(flag_value=True)

    plugin.toggle_action.blockSignals.assert_any_call(True)
    plugin.toggle_action.blockSignals.assert_any_call(False)


def test_restore_noop_without_toggle_action():
    """With no toggle action, reconcile returns without touching recording."""
    project = MagicMock()
    project.readBoolEntry.return_value = (True, True)
    qgis_core = MagicMock()
    qgis_core.QgsProject.instance.return_value = project
    qgis = MagicMock()
    qgis.core = qgis_core

    with patch.dict("sys.modules", {"qgis": qgis, "qgis.core": qgis_core}):
        from GeoLineage.plugin import GeoLineagePlugin

        plugin = GeoLineagePlugin(iface=MagicMock())
        plugin.toggle_action = None
        plugin._enable_recording = MagicMock()
        plugin._disable_recording = MagicMock()
        plugin._restore_toggle_state()

    plugin._enable_recording.assert_not_called()
    plugin._disable_recording.assert_not_called()
