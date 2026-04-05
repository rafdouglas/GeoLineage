"""T1 unit tests for lineage_viewer.detail_panel — regression guard and data contract.

These tests do NOT instantiate DetailPanel (requires QGIS/QWidget at runtime).
Instead they verify:
  1. The source code uses the correct dict key "operation_params" (not "parameters").
  2. A pure-Python helper that mirrors the field-extraction logic in set_node().
"""

from __future__ import annotations

import ast
import pathlib

# ---------------------------------------------------------------------------
# Path to the module under test
# ---------------------------------------------------------------------------

_DETAIL_PANEL_PATH = pathlib.Path(__file__).parent.parent / "lineage_viewer" / "detail_panel.py"


# ---------------------------------------------------------------------------
# Pure-Python helper mirroring detail_panel.py lines 100–145
# ---------------------------------------------------------------------------


def extract_detail_fields(entry: dict) -> dict:
    """Extract the fields that DetailPanel.set_node() reads from an entry dict.

    Returns a dict with the same keys and values that the panel would display,
    without touching any Qt widgets.
    """
    return {
        "entry_type": entry.get("entry_type", "unknown"),
        "operation_tool": entry.get("operation_tool", ""),
        "created_at": entry.get("created_at", ""),
        "parent_files": entry.get("parent_files", ""),
        "operation_params": entry.get("operation_params", ""),
    }


# ---------------------------------------------------------------------------
# AST-based regression guard
# ---------------------------------------------------------------------------


def _collect_get_string_keys(source: str) -> set[str]:
    """Walk the AST and collect every string literal used as the first argument
    to a .get() call (i.e. ``some_dict.get("<key>", ...)``).
    """
    tree = ast.parse(source)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
    return keys


class TestDetailPanelSourceContract:
    """Verify the source file uses the correct dict key."""

    def test_detail_panel_uses_operation_params_key(self):
        """detail_panel.py must call entry.get('operation_params', ...).

        Regression guard: a previous bug used 'parameters' instead.
        """
        source = _DETAIL_PANEL_PATH.read_text(encoding="utf-8")
        get_keys = _collect_get_string_keys(source)

        assert "operation_params" in get_keys, (
            "detail_panel.py must use entry.get('operation_params', ...) "
            "to read operation parameters from the lineage entry dict. "
            "The key must match the database column name defined in schema.py."
        )

    def test_detail_panel_does_not_use_bare_parameters_key(self):
        """detail_panel.py must NOT call entry.get('parameters', ...).

        'parameters' was the wrong key used in a previous bug.
        """
        source = _DETAIL_PANEL_PATH.read_text(encoding="utf-8")
        get_keys = _collect_get_string_keys(source)

        assert "parameters" not in get_keys, (
            "detail_panel.py must not use entry.get('parameters', ...). "
            "The correct key is 'operation_params' (matches the DB column)."
        )


# ---------------------------------------------------------------------------
# Data-contract tests using the pure-Python extract helper
# ---------------------------------------------------------------------------


class TestExtractDetailFields:
    """Test the extract_detail_fields() helper that mirrors panel field logic."""

    def test_entry_with_operation_params_extracts_correctly(self):
        """An entry dict with 'operation_params' populates the field."""
        params_json = '{"buffer_distance": 100}'
        entry = {
            "entry_type": "processing",
            "operation_tool": "buffer",
            "created_at": "2024-01-15T10:30:00",
            "parent_files": '["input.gpkg"]',
            "operation_params": params_json,
        }
        result = extract_detail_fields(entry)

        assert result["operation_params"] == params_json

    def test_entry_with_wrong_key_parameters_returns_empty(self):
        """An entry dict using the old wrong key 'parameters' yields empty string."""
        entry = {
            "entry_type": "processing",
            "operation_tool": "buffer",
            "parameters": '{"buffer_distance": 100}',  # wrong key — old bug
        }
        result = extract_detail_fields(entry)

        assert result["operation_params"] == "", (
            "When the entry dict has 'parameters' but not 'operation_params', "
            "the extracted value must be empty (the panel would show nothing)."
        )

    def test_entry_all_fields_extracted(self):
        """A fully-populated entry dict extracts all fields correctly."""
        entry = {
            "entry_type": "export",
            "operation_tool": "native:dissolve",
            "created_at": "2024-03-20T08:00:00",
            "parent_files": '["roads.gpkg", "admin.gpkg"]',
            "operation_params": '{"dissolve_field": "region"}',
        }
        result = extract_detail_fields(entry)

        assert result["entry_type"] == "export"
        assert result["operation_tool"] == "native:dissolve"
        assert result["created_at"] == "2024-03-20T08:00:00"
        assert result["parent_files"] == '["roads.gpkg", "admin.gpkg"]'
        assert result["operation_params"] == '{"dissolve_field": "region"}'

    def test_entry_missing_optional_fields_uses_defaults(self):
        """Missing optional fields fall back to their default values."""
        entry = {"entry_type": "import"}
        result = extract_detail_fields(entry)

        assert result["entry_type"] == "import"
        assert result["operation_tool"] == ""
        assert result["created_at"] == ""
        assert result["parent_files"] == ""
        assert result["operation_params"] == ""

    def test_entry_missing_entry_type_defaults_to_unknown(self):
        """An entry dict with no 'entry_type' defaults to 'unknown'."""
        result = extract_detail_fields({})

        assert result["entry_type"] == "unknown"

    def test_entry_empty_dict_all_defaults(self):
        """An empty entry dict produces all-default values."""
        result = extract_detail_fields({})

        assert result == {
            "entry_type": "unknown",
            "operation_tool": "",
            "created_at": "",
            "parent_files": "",
            "operation_params": "",
        }
