"""T1 unit tests for lineage_manager.inspect_dialog.

These tests do NOT instantiate InspectDialog (requires QGIS/QWidget at runtime).
Instead they verify:
  1. A pure-Python helper that collects absolute GeoPackage paths from a list of
     QGIS layer source strings, mirroring the scope logic in _load_entries().
  2. AST-based regression guards for the three Qt-bound fixes:
     - setSortingEnabled(False) wraps the populate loop (Phase 1)
     - the folder *.gpkg glob is gone; extract_gpkg_path is used (Phase 2)
     - the window title says "Manage Lineage" not "Inspect Lineage" (Phase 3)
"""

from __future__ import annotations

import ast
import os
import pathlib

_INSPECT_DIALOG_PATH = pathlib.Path(__file__).parent.parent / "lineage_manager" / "inspect_dialog.py"


# ---------------------------------------------------------------------------
# Pure-Python helper mirroring the scope logic in _load_entries()
# ---------------------------------------------------------------------------


def collect_loaded_gpkg_paths(layer_sources: list[str]) -> list[str]:
    """Collect deduped absolute GeoPackage paths from a list of layer source URIs.

    This mirrors the logic that replaces the folder *.gpkg glob in _load_entries().
    Pure Python — no QGIS dependency so it can be unit-tested.
    """
    from GeoLineage.lineage_retrieval.path_resolver import extract_gpkg_path

    gpkg_paths: list[str] = []
    seen: set[str] = set()
    for source in layer_sources:
        if not isinstance(source, str):
            continue
        path = extract_gpkg_path(source)
        if not path:
            continue
        abs_path = os.path.abspath(path)
        if abs_path in seen:
            continue
        seen.add(abs_path)
        gpkg_paths.append(abs_path)
    return gpkg_paths


# ---------------------------------------------------------------------------
# Scope regression tests (Phase 2)
# ---------------------------------------------------------------------------


class TestCollectLoadedGpkgPaths:
    def test_extracts_gpkg_path_from_source_uri(self):
        result = collect_loaded_gpkg_paths(["/data/foo.gpkg|layername=points"])
        assert result == [os.path.abspath("/data/foo.gpkg")]

    def test_dedupes_same_file_loaded_multiple_times(self):
        """Phase 2 regression: same gpkg loaded as two layers appears once."""
        result = collect_loaded_gpkg_paths(
            [
                "/data/foo.gpkg|layername=points",
                "/data/foo.gpkg|layername=lines",
            ]
        )
        assert result == [os.path.abspath("/data/foo.gpkg")]

    def test_includes_gpkg_outside_project_dir(self):
        """Phase 2 regression: paths outside project_dir must be included."""
        result = collect_loaded_gpkg_paths(["/other/place/elsewhere.gpkg|layername=x"])
        assert result == [os.path.abspath("/other/place/elsewhere.gpkg")]

    def test_skips_non_gpkg_sources(self):
        result = collect_loaded_gpkg_paths(
            [
                "/data/foo.shp",
                "postgres://host/db",
                "",
            ]
        )
        assert result == []

    def test_skips_non_string_sources(self):
        result = collect_loaded_gpkg_paths([None, 42, "/data/foo.gpkg|layername=x"])  # type: ignore[list-item]
        assert result == [os.path.abspath("/data/foo.gpkg")]

    def test_preserves_first_seen_order(self):
        result = collect_loaded_gpkg_paths(
            [
                "/data/b.gpkg|layername=x",
                "/data/a.gpkg|layername=y",
                "/data/b.gpkg|layername=z",
            ]
        )
        assert result == [os.path.abspath("/data/b.gpkg"), os.path.abspath("/data/a.gpkg")]


# ---------------------------------------------------------------------------
# AST-based regression guards
# ---------------------------------------------------------------------------


def _source() -> str:
    return _INSPECT_DIALOG_PATH.read_text(encoding="utf-8")


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _find_setSortingEnabled_calls(func: ast.AST) -> list[ast.Call]:
    calls = []
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setSortingEnabled"
        ):
            calls.append(node)
    return calls


class TestSortingEnabledPopulateGuard:
    """Phase 1 regression: populate loop must run with sorting disabled."""

    def test_load_entries_disables_sorting_before_populate(self):
        tree = ast.parse(_source())
        load_entries = _find_function(tree, "_load_entries")
        assert load_entries is not None, "_load_entries method must exist"

        calls = _find_setSortingEnabled_calls(load_entries)
        false_calls = [c for c in calls if c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value is False]
        assert false_calls, (
            "_load_entries must call self._table.setSortingEnabled(False) before populating rows. "
            "Without this, Qt resorts after every setItem() and columns land on wrong rows "
            "(the empty-cells bug). See .claude/plans/fix-manage-lineage-dialog.md Phase 1."
        )

    def test_load_entries_reenables_sorting_after_populate(self):
        tree = ast.parse(_source())
        load_entries = _find_function(tree, "_load_entries")
        assert load_entries is not None

        calls = _find_setSortingEnabled_calls(load_entries)
        true_calls = [c for c in calls if c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value is True]
        assert true_calls, "_load_entries must re-enable sorting after populating rows"

    def test_load_entries_wraps_populate_in_try_finally(self):
        """Re-enable must be in a finally block so exceptions don't leave sorting off."""
        tree = ast.parse(_source())
        load_entries = _find_function(tree, "_load_entries")
        assert load_entries is not None

        try_nodes = [n for n in ast.walk(load_entries) if isinstance(n, ast.Try)]
        assert try_nodes, "_load_entries must use try/finally to guarantee sort re-enable"

        reenables_in_finally = False
        for try_node in try_nodes:
            for finally_stmt in try_node.finalbody:
                for call in ast.walk(finally_stmt):
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "setSortingEnabled"
                        and call.args
                        and isinstance(call.args[0], ast.Constant)
                        and call.args[0].value is True
                    ):
                        reenables_in_finally = True
        assert reenables_in_finally, "setSortingEnabled(True) must be called inside a finally block in _load_entries"


class TestScopeRegressionGuard:
    """Phase 2 regression: no folder glob; use extract_gpkg_path on loaded layers."""

    def test_load_entries_does_not_glob_project_dir(self):
        source = _source()
        assert ".glob(" not in source, (
            "inspect_dialog.py must not glob the project directory for *.gpkg. "
            "It should enumerate layers loaded in the QGIS project instead. "
            "See .claude/plans/fix-manage-lineage-dialog.md Phase 2."
        )

    def test_inspect_dialog_imports_extract_gpkg_path(self):
        source = _source()
        assert "extract_gpkg_path" in source, (
            "inspect_dialog.py must use extract_gpkg_path() from lineage_retrieval.path_resolver "
            "to identify GeoPackage-backed layers, matching the 'Show Lineage Graph' path."
        )

    def test_inspect_dialog_enumerates_map_layers(self):
        source = _source()
        assert "mapLayers" in source, (
            "inspect_dialog.py must enumerate QgsProject.instance().mapLayers() to scope "
            "the dialog to loaded layers (Phase 2)."
        )


class TestWindowTitleGuard:
    """Phase 3 regression: title says 'Manage Lineage', not 'Inspect Lineage'."""

    def test_window_title_uses_manage_lineage(self):
        source = _source()
        assert "Manage Lineage" in source, (
            "inspect_dialog.py window title must say 'Manage Lineage' to match the menu caption."
        )

    def test_window_title_does_not_use_inspect_lineage(self):
        source = _source()
        assert "Inspect Lineage" not in source, (
            "inspect_dialog.py must not use the old 'Inspect Lineage' title — it disagreed with "
            "the 'Manage Lineage...' menu caption."
        )


class TestInitSignature:
    """Phase 2 regression: InspectDialog.__init__ accepts iface."""

    def test_init_accepts_iface_parameter(self):
        tree = ast.parse(_source())
        class_node = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "InspectDialog"),
            None,
        )
        assert class_node is not None
        init = next((n for n in class_node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
        assert init is not None
        arg_names = [a.arg for a in init.args.args]
        assert "iface" in arg_names, (
            "InspectDialog.__init__ must accept an 'iface' parameter so _load_entries can "
            "enumerate layers loaded in the current QGIS project (Phase 2)."
        )
