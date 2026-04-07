"""T1 tests for Phase 6 UI enhancements.

Tests _get_created_by(), column registry consistency, detail panel
created_by display logic, and inspect dialog structure — all without
QGIS runtime dependency where possible.
"""

from __future__ import annotations

import ast
import pathlib
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Paths to modules under test
# ---------------------------------------------------------------------------

_HOOKS_PATH = pathlib.Path(__file__).parent.parent / "lineage_core" / "hooks.py"
_DETAIL_PANEL_PATH = pathlib.Path(__file__).parent.parent / "lineage_viewer" / "detail_panel.py"
_INSPECT_DIALOG_PATH = pathlib.Path(__file__).parent.parent / "lineage_manager" / "inspect_dialog.py"
_GRAPH_NODE_ITEM_PATH = pathlib.Path(__file__).parent.parent / "lineage_viewer" / "graph_node_item.py"


# ===========================================================================
# _get_created_by() tests
# ===========================================================================


class TestGetCreatedBy:
    """Unit tests for _get_created_by helper in hooks.py."""

    def _make_mock_settings(self, value: str):
        """Create a mock QgsSettings that returns value for SETTING_USERNAME."""
        mock_settings = MagicMock()
        mock_settings.return_value.value.return_value = value
        return mock_settings

    def _make_qgis_mocks(self, username: str):
        """Build a linked qgis/qgis.core mock hierarchy with QgsSettings configured."""
        mock_qgs_settings = MagicMock()
        mock_qgs_settings.return_value.value.return_value = username
        mock_qgis_core = MagicMock()
        mock_qgis_core.QgsSettings = mock_qgs_settings
        mock_qgis = MagicMock()
        mock_qgis.core = mock_qgis_core
        return mock_qgis, mock_qgis_core

    def test_returns_none_when_empty(self):
        mock_qgis, mock_qgis_core = self._make_qgis_mocks("")
        with patch.dict("sys.modules", {"qgis": mock_qgis, "qgis.core": mock_qgis_core}):
            from GeoLineage.lineage_core.hooks import _get_created_by

            result = _get_created_by()
            assert result is None

    def test_returns_none_when_unset(self):
        mock_qgis, mock_qgis_core = self._make_qgis_mocks("")
        with patch.dict("sys.modules", {"qgis": mock_qgis, "qgis.core": mock_qgis_core}):
            from GeoLineage.lineage_core.hooks import _get_created_by

            result = _get_created_by()
            assert result is None

    def test_returns_username_when_set(self):
        mock_qgis, mock_qgis_core = self._make_qgis_mocks("alice")
        with patch.dict("sys.modules", {"qgis": mock_qgis, "qgis.core": mock_qgis_core}):
            from GeoLineage.lineage_core.hooks import _get_created_by

            result = _get_created_by()
            assert result == "alice"

    def test_no_getpass_import_in_hooks(self):
        """Verify hooks.py does not import or call getpass.getuser()."""
        source = _HOOKS_PATH.read_text()
        assert "getpass" not in source, "_get_created_by must not use getpass"

    def test_source_reads_setting_username(self):
        """Verify _get_created_by reads SETTING_USERNAME from settings."""
        source = _HOOKS_PATH.read_text()
        assert "SETTING_USERNAME" in source


# ===========================================================================
# Column registry consistency tests
# ===========================================================================


class TestColumnRegistry:
    """Verify InspectDialog column registry is self-consistent."""

    def _get_inspect_source(self) -> str:
        return _INSPECT_DIALOG_PATH.read_text()

    def test_columns_list_exists(self):
        source = self._get_inspect_source()
        assert "_COLUMNS" in source

    def test_column_count_matches_constants(self):
        """Verify len(_COLUMNS) matches the number of _COL_* class attributes."""
        source = self._get_inspect_source()
        tree = ast.parse(source)

        columns_list = None
        col_constants = set()

        for node in ast.walk(tree):
            # Find _COLUMNS assignment
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_COLUMNS" and isinstance(node.value, ast.List):
                        columns_list = node.value.elts

            # Find _COL_* names in Tuple unpacking
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Tuple):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name) and elt.id.startswith("_COL_"):
                                col_constants.add(elt.id)

        assert columns_list is not None, "_COLUMNS list not found"
        assert len(columns_list) == len(col_constants), (
            f"_COLUMNS has {len(columns_list)} entries but found {len(col_constants)} _COL_* constants"
        )

    def test_editable_cols_use_symbolic_names(self):
        """Verify _EDITABLE_COLS keys are not raw integer literals."""
        source = self._get_inspect_source()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "_EDITABLE_COLS"
                        and isinstance(node.value, ast.Dict)
                    ):
                        for key in node.value.keys:
                            assert not isinstance(key, ast.Constant), (
                                f"_EDITABLE_COLS uses raw literal {key.value} instead of symbolic _COL_* name"
                            )

    def test_columns_include_file_user_params(self):
        """Verify new columns File, User, Params are in the registry."""
        source = self._get_inspect_source()
        assert '"File"' in source or "'File'" in source
        assert '"User"' in source or "'User'" in source
        assert '"Params"' in source or "'Params'" in source


# ===========================================================================
# Detail panel created_by display tests
# ===========================================================================


class TestDetailPanelCreatedBy:
    """Verify detail_panel.py reads created_by from entry dict."""

    def test_source_reads_created_by(self):
        source = _DETAIL_PANEL_PATH.read_text()
        assert 'entry.get("created_by"' in source or "entry.get('created_by'" in source

    def test_user_label_format(self):
        """Verify the User label uses 'User: {created_by}' format."""
        source = _DETAIL_PANEL_PATH.read_text()
        assert 'f"User: {created_by}"' in source or "f'User: {created_by}'" in source


# ===========================================================================
# Detail panel collapsible params tests
# ===========================================================================


class TestDetailPanelCollapsibleParams:
    """Verify params section has expand/collapse toggle."""

    def test_toggle_button_exists(self):
        source = _DETAIL_PANEL_PATH.read_text()
        assert "Show Parameters" in source
        assert "Hide Parameters" in source

    def test_params_default_hidden(self):
        """Verify params_label starts hidden."""
        source = _DETAIL_PANEL_PATH.read_text()
        assert "setVisible(False)" in source

    def test_params_text_selectable(self):
        """Verify params text has TextSelectableByMouse flag."""
        source = _DETAIL_PANEL_PATH.read_text()
        assert "TextSelectableByMouse" in source


# ===========================================================================
# Search highlight color test
# ===========================================================================


class TestSearchHighlight:
    """Verify search highlight uses bright yellow color."""

    def test_highlight_color_is_yellow(self):
        source = _GRAPH_NODE_ITEM_PATH.read_text()
        assert '_HIGHLIGHT_COLOR = "#FFEB3B"' in source


# ===========================================================================
# Toolbar export PNG ordering test
# ===========================================================================


class TestToolbarExportPng:
    """Verify Export PNG is placed before search in toolbar."""

    def test_export_png_before_search(self):
        toolbar_path = pathlib.Path(__file__).parent.parent / "lineage_viewer" / "toolbar.py"
        source = toolbar_path.read_text()
        png_pos = source.index("Export PNG")
        search_pos = source.index("Search by filename")
        assert png_pos < search_pos, "Export PNG should appear before search widget"


# ===========================================================================
# Multi-gpkg InspectDialog structure tests
# ===========================================================================


class TestMultiGpkgInspectDialog:
    """Verify InspectDialog no longer takes gpkg_path in constructor."""

    def test_constructor_no_gpkg_path_param(self):
        """Verify __init__ signature is (project_dir, dock_widget, parent)."""
        source = _INSPECT_DIALOG_PATH.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                arg_names = [a.arg for a in node.args.args]
                if "project_dir" in arg_names:
                    assert "gpkg_path" not in arg_names, "InspectDialog.__init__ should not have gpkg_path parameter"
                    return
        # If we didn't find it by walking, do a simple text check
        assert "gpkg_path" not in source.split("def __init__")[1].split(")")[0]

    def test_no_self_gpkg_path(self):
        """Verify self._gpkg_path is fully removed."""
        source = _INSPECT_DIALOG_PATH.read_text()
        assert "self._gpkg_path" not in source

    def test_uses_pathlib_glob_non_recursive(self):
        """Verify non-recursive glob('*.gpkg') is used."""
        source = _INSPECT_DIALOG_PATH.read_text()
        assert '.glob("*.gpkg")' in source or ".glob('*.gpkg')" in source

    def test_uses_userrole_for_gpkg_path(self):
        """Verify UserRole is used to store per-row gpkg_path."""
        source = _INSPECT_DIALOG_PATH.read_text()
        assert "Qt.UserRole" in source


# ===========================================================================
# Context menu tests
# ===========================================================================


class TestContextMenu:
    """Verify right-click context menu structure in InspectDialog."""

    def test_context_menu_policy_set(self):
        source = _INSPECT_DIALOG_PATH.read_text()
        assert "CustomContextMenu" in source

    def test_context_menu_signal_connected(self):
        source = _INSPECT_DIALOG_PATH.read_text()
        assert "customContextMenuRequested" in source

    def test_context_menu_has_actions(self):
        source = _INSPECT_DIALOG_PATH.read_text()
        assert '"Delete"' in source or "'Delete'" in source
        assert '"Relink..."' in source or "'Relink...'" in source
        assert '"View in Graph"' in source or "'View in Graph'" in source

    def test_context_menu_guards_empty_row(self):
        """Verify _on_context_menu returns early when row < 0."""
        source = _INSPECT_DIALOG_PATH.read_text()
        # Find the _on_context_menu method and verify it checks row < 0
        assert "row < 0" in source


# ===========================================================================
# Plugin.py caller update tests
# ===========================================================================


class TestPluginManageDialog:
    """Verify plugin.py no longer requires active layer for Manage dialog."""

    def test_no_active_layer_requirement(self):
        plugin_path = pathlib.Path(__file__).parent.parent / "plugin.py"
        source = plugin_path.read_text()
        # Find _show_manage_dialog method
        method_start = source.index("def _show_manage_dialog")
        method_end = source.index("\n    def ", method_start + 1)
        method_source = source[method_start:method_end]
        assert "activeLayer" not in method_source
        assert "extract_gpkg_path" not in method_source

    def test_uses_project_dir_only(self):
        plugin_path = pathlib.Path(__file__).parent.parent / "plugin.py"
        source = plugin_path.read_text()
        method_start = source.index("def _show_manage_dialog")
        method_end = source.index("\n    def ", method_start + 1)
        method_source = source[method_start:method_end]
        assert "homePath" in method_source
        assert "InspectDialog(project_dir" in method_source
