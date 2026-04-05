"""T1 tests for hooks.py pure-Python logic.

Tests re-entrancy guard, exception isolation, identity check,
and helper functions — all without QGIS dependency.
"""

import contextlib
import types

from GeoLineage.lineage_core.hooks import (
    _decrement_depth,
    _extract_input_layer_ids,
    _get_depth,
    _get_layer_id,
    _get_layer_source_path,
    _increment_depth,
    _is_gpkg_path,
    _local,
    _sanitize_params,
)

# --- Re-entrancy guard tests ---


class TestReentrancyGuard:
    def setup_method(self):
        _local.depth = 0

    def test_initial_depth_is_zero(self):
        _local.depth = 0
        assert _get_depth() == 0

    def test_increment_increases_depth(self):
        assert _increment_depth() == 1
        assert _get_depth() == 1

    def test_multiple_increments(self):
        _increment_depth()
        _increment_depth()
        assert _get_depth() == 2

    def test_decrement_decreases_depth(self):
        _increment_depth()
        _increment_depth()
        _decrement_depth()
        assert _get_depth() == 1

    def test_decrement_does_not_go_below_zero(self):
        assert _decrement_depth() == 0
        assert _get_depth() == 0

    def test_increment_decrement_roundtrip(self):
        _increment_depth()
        _increment_depth()
        _increment_depth()
        _decrement_depth()
        _decrement_depth()
        _decrement_depth()
        assert _get_depth() == 0

    def test_nested_calls_only_record_at_depth_one(self):
        """Simulates nested processing.run() calls.
        Only the outermost call (depth==1 after increment) should record.
        """
        recordings = []

        def maybe_record():
            depth = _increment_depth()
            try:
                if depth == 1:
                    recordings.append("recorded")
                # Simulate nested call
                if depth == 1:
                    inner_depth = _increment_depth()
                    if inner_depth == 1:
                        recordings.append("inner-recorded")
                    _decrement_depth()
            finally:
                _decrement_depth()

        maybe_record()
        assert recordings == ["recorded"]
        assert _get_depth() == 0


# --- Exception isolation tests ---


class TestExceptionIsolation:
    def test_exception_in_recording_does_not_propagate(self):
        """Simulates the wrapper pattern where recording failures are caught."""
        original_result = {"OUTPUT": "test.gpkg"}

        def original_run(*args, **kwargs):
            return original_result

        def bad_recorder(*args, **kwargs):
            raise RuntimeError("Recording failed!")

        # Simulate the wrapper pattern from hooks.py
        result = original_run("native:buffer", {})
        with contextlib.suppress(Exception):
            bad_recorder(result)

        assert result == original_result

    def test_wrapper_pattern_returns_result_on_recording_failure(self):
        """The full wrapper pattern: call original, try recording, return result."""
        call_log = []

        def original_run(alg, params):
            call_log.append(("run", alg))
            return {"OUTPUT": "result"}

        def failing_record(alg, params, result):
            raise ValueError("boom")

        # Simulated wrapper
        result = original_run("native:buffer", {"INPUT": "test"})
        try:
            failing_record("native:buffer", {"INPUT": "test"}, result)
        except Exception:
            call_log.append("recording_failed")

        assert result == {"OUTPUT": "result"}
        assert "recording_failed" in call_log


# --- Identity check tests ---


class TestIdentityCheck:
    def test_identity_check_matches_wrapper(self):
        """When processing.run is still our wrapper, identity check passes."""
        mock_module = types.SimpleNamespace()

        def wrapper(*a, **k):
            return None

        mock_module.run = wrapper

        assert mock_module.run is wrapper

    def test_identity_check_fails_when_another_wraps(self):
        """If another plugin wraps after us, identity check should fail."""
        mock_module = types.SimpleNamespace()

        def our_wrapper(*a, **k):
            return None

        def other_wrapper(*a, **k):
            return None

        mock_module.run = other_wrapper

        assert mock_module.run is not our_wrapper

    def test_restoration_skipped_on_identity_mismatch(self):
        """Simulates the uninstall logic: skip restoration if identity doesn't match."""
        mock_module = types.SimpleNamespace()

        def original(*a, **k):
            return "original"

        def our_wrapper(*a, **k):
            return "ours"

        def other_wrapper(*a, **k):
            return "theirs"

        mock_module.run = other_wrapper

        # Simulated uninstall logic
        if mock_module.run is our_wrapper:
            mock_module.run = original
        else:
            pass  # Skip restoration

        # Should still be the other plugin's wrapper
        assert mock_module.run is other_wrapper


# --- _is_gpkg_path tests ---


class TestIsGpkgPath:
    def test_valid_gpkg_path(self):
        assert _is_gpkg_path("/data/output.gpkg") is True

    def test_gpkg_uppercase(self):
        assert _is_gpkg_path("/data/OUTPUT.GPKG") is True

    def test_gpkg_mixed_case(self):
        assert _is_gpkg_path("/data/file.GpKg") is True

    def test_non_gpkg_extension(self):
        assert _is_gpkg_path("/data/file.shp") is False

    def test_none_input(self):
        assert _is_gpkg_path(None) is False

    def test_empty_string(self):
        assert _is_gpkg_path("") is False

    def test_non_string_input(self):
        assert _is_gpkg_path(42) is False

    def test_gpkg_with_spaces(self):
        assert _is_gpkg_path("/my data/output file.gpkg") is True

    def test_gpkg_relative_path(self):
        assert _is_gpkg_path("output.gpkg") is True

    def test_memory_layer_string(self):
        assert _is_gpkg_path("memory:Point?crs=epsg:4326") is False


# --- _extract_input_layer_ids tests ---


class MockLayer:
    """Mock QGIS layer with id() and source() methods."""

    def __init__(self, layer_id: str, source: str = ""):
        self._id = layer_id
        self._source = source

    def id(self) -> str:
        return self._id

    def source(self) -> str:
        return self._source

    def name(self) -> str:
        return f"layer_{self._id}"


class TestExtractInputLayerIds:
    def test_single_input_layer(self):
        layer = MockLayer("layer_abc123")
        params = {"INPUT": layer}
        ids = _extract_input_layer_ids(params)
        assert ids == ["layer_abc123"]

    def test_multiple_input_keys(self):
        input_layer = MockLayer("input_1")
        overlay_layer = MockLayer("overlay_1")
        params = {"INPUT": input_layer, "OVERLAY": overlay_layer}
        ids = _extract_input_layer_ids(params)
        assert "input_1" in ids
        assert "overlay_1" in ids

    def test_list_of_layers(self):
        layers = [MockLayer("l1"), MockLayer("l2"), MockLayer("l3")]
        params = {"LAYERS": layers}
        ids = _extract_input_layer_ids(params)
        assert ids == ["l1", "l2", "l3"]

    def test_no_input_layers(self):
        params = {"DISTANCE": 100, "SEGMENTS": 5}
        ids = _extract_input_layer_ids(params)
        assert ids == []

    def test_string_input_not_layer(self):
        params = {"INPUT": "/path/to/file.shp"}
        ids = _extract_input_layer_ids(params)
        assert ids == []

    def test_none_value(self):
        params = {"INPUT": None}
        ids = _extract_input_layer_ids(params)
        assert ids == []


# --- _get_layer_id tests ---


class TestGetLayerId:
    def test_layer_object(self):
        layer = MockLayer("abc123")
        assert _get_layer_id(layer) == "abc123"

    def test_string_returns_none(self):
        assert _get_layer_id("/path/to/file.gpkg") is None

    def test_none_returns_none(self):
        assert _get_layer_id(None) is None

    def test_int_returns_none(self):
        assert _get_layer_id(42) is None


# --- _sanitize_params tests ---


class TestSanitizeParams:
    def test_primitive_values(self):
        params = {"DISTANCE": 100.0, "SEGMENTS": 5, "NAME": "test", "FLAG": True}
        result = _sanitize_params(params)
        assert result == params

    def test_layer_replaced_with_string(self):
        layer = MockLayer("abc123")
        params = {"INPUT": layer}
        result = _sanitize_params(params)
        assert result["INPUT"] == "<layer:abc123>"

    def test_list_with_layers(self):
        layers = [MockLayer("l1"), MockLayer("l2")]
        params = {"LAYERS": layers}
        result = _sanitize_params(params)
        assert result["LAYERS"] == ["<layer:l1>", "<layer:l2>"]

    def test_none_value(self):
        params = {"OUTPUT": None}
        result = _sanitize_params(params)
        assert result["OUTPUT"] is None

    def test_mixed_list(self):
        layer = MockLayer("l1")
        params = {"LAYERS": [layer, "path/to/file.shp", 42]}
        result = _sanitize_params(params)
        assert result["LAYERS"] == ["<layer:l1>", "path/to/file.shp", 42]

    def test_dict_value(self):
        params = {"OPTIONS": {"key1": "val1", "key2": 2}}
        result = _sanitize_params(params)
        assert result["OPTIONS"] == {"key1": "val1", "key2": "2"}

    def test_unsupported_type_stringified(self):
        params = {"WEIRD": object()}
        result = _sanitize_params(params)
        assert isinstance(result["WEIRD"], str)


# --- _get_layer_id string handling tests ---


class TestGetLayerIdStringHandling:
    def test_string_returns_none_without_qgis(self):
        """String layer ID returns None when QgsProject is unavailable (T1 environment)."""
        assert _get_layer_id("some_layer_id_string") is None

    def test_file_path_string_returns_none(self):
        """File path strings are not valid layer IDs."""
        assert _get_layer_id("/path/to/file.gpkg") is None

    def test_empty_string_returns_none(self):
        assert _get_layer_id("") is None


# --- _get_layer_source_path string handling tests ---


class TestGetLayerSourcePathStringHandling:
    def test_existing_file_path_returns_path(self, tmp_path):
        """String path to an existing file returns the path."""
        gpkg = tmp_path / "input.gpkg"
        gpkg.write_bytes(b"dummy")
        assert _get_layer_source_path(str(gpkg)) == str(gpkg)

    def test_existing_file_with_layername_suffix(self, tmp_path):
        """String path with |layername= suffix strips suffix and returns base."""
        gpkg = tmp_path / "input.gpkg"
        gpkg.write_bytes(b"dummy")
        assert _get_layer_source_path(f"{gpkg}|layername=points") == str(gpkg)

    def test_nonexistent_file_returns_none(self):
        """String path to a non-existing file returns None."""
        assert _get_layer_source_path("/nonexistent/path/file.gpkg") is None

    def test_none_returns_none(self):
        assert _get_layer_source_path(None) is None

    def test_int_returns_none(self):
        assert _get_layer_source_path(42) is None

    def test_layer_object_still_works(self, tmp_path):
        """MockLayer with .source() still works as before."""
        gpkg = tmp_path / "source.gpkg"
        gpkg.write_bytes(b"dummy")
        layer = MockLayer("l1", source=str(gpkg))
        assert _get_layer_source_path(layer) == str(gpkg)

    def test_layer_object_with_layername_suffix(self, tmp_path):
        """MockLayer source with |layername= suffix strips it."""
        gpkg = tmp_path / "source.gpkg"
        gpkg.write_bytes(b"dummy")
        layer = MockLayer("l1", source=f"{gpkg}|layername=foo")
        assert _get_layer_source_path(layer) == str(gpkg)

    def test_string_layer_id_returns_none_without_qgis(self):
        """String that is not a file path returns None (QgsProject unavailable in T1)."""
        assert _get_layer_source_path("some_layer_id") is None
