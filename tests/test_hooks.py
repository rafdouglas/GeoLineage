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
    _resolve_output_layer_definition,
    _sanitize_params,
    _strip_layername,
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


# --- _resolve_output_layer_definition tests ---


class MockQgsProperty:
    """Mock QgsProperty with staticValue()."""

    def __init__(self, value: str):
        self._value = value

    def staticValue(self) -> str:
        return self._value


class MockOutputLayerDefinition:
    """Mock QgsProcessingOutputLayerDefinition with .sink attribute."""

    def __init__(self, sink):
        self.sink = sink


class TestResolveOutputLayerDefinition:
    def test_plain_string_passes_through(self):
        assert _resolve_output_layer_definition("/path/to/file.gpkg") == "/path/to/file.gpkg"

    def test_none_passes_through(self):
        assert _resolve_output_layer_definition(None) is None

    def test_layer_object_passes_through(self):
        layer = MockLayer("abc")
        result = _resolve_output_layer_definition(layer)
        assert result is layer

    def test_definition_with_qgs_property_sink(self):
        prop = MockQgsProperty("/data/output.gpkg")
        defn = MockOutputLayerDefinition(sink=prop)
        assert _resolve_output_layer_definition(defn) == "/data/output.gpkg"

    def test_definition_with_string_sink(self):
        defn = MockOutputLayerDefinition(sink="/data/output.gpkg")
        assert _resolve_output_layer_definition(defn) == "/data/output.gpkg"

    def test_definition_with_unknown_sink_type(self):
        """When sink exists but is neither string nor has staticValue, return obj unchanged."""
        defn = MockOutputLayerDefinition(sink=42)
        result = _resolve_output_layer_definition(defn)
        assert result is defn

    def test_int_passes_through(self):
        assert _resolve_output_layer_definition(42) == 42


# --- _strip_layername tests ---


class TestStripLayername:
    def test_plain_path(self):
        assert _strip_layername("/data/output.gpkg") == "/data/output.gpkg"

    def test_path_with_layername_suffix(self):
        assert _strip_layername("/data/output.gpkg|layername=points") == "/data/output.gpkg"

    def test_path_with_multiple_pipes(self):
        assert _strip_layername("/data/output.gpkg|layername=pts|subset=id>0") == "/data/output.gpkg"

    def test_empty_string(self):
        assert _strip_layername("") == ""


# --- _is_gpkg_path with |layername= suffix tests ---


class TestIsGpkgPathWithSuffix:
    def test_gpkg_with_layername_suffix(self):
        assert _is_gpkg_path("/data/output.gpkg|layername=points") is True

    def test_gpkg_with_multiple_pipe_params(self):
        assert _is_gpkg_path("/data/output.gpkg|layername=pts|subset=id>0") is True

    def test_non_gpkg_with_layername_suffix(self):
        assert _is_gpkg_path("/data/output.shp|layername=points") is False


# --- Nested params unwrapping tests ---


class TestNestedParamsUnwrapping:
    """Tests for the dialog hook's nested 'inputs' dict unwrapping in _record_processing_lineage."""

    def test_unwraps_nested_inputs_for_parent_extraction(self, tmp_path, monkeypatch):
        """Nested params from dialog hook produce correct parents list."""
        from GeoLineage.lineage_core import checksum, hooks, recorder

        # Create a real .gpkg file so _get_layer_source_path resolves it
        input_gpkg = tmp_path / "input.gpkg"
        input_gpkg.write_bytes(b"dummy")
        output_gpkg = tmp_path / "output.gpkg"
        output_gpkg.write_bytes(b"dummy")

        captured = {}

        def fake_record_processing(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(recorder, "record_processing", fake_record_processing)
        monkeypatch.setattr(checksum, "compute_checksum", lambda path: "fake")

        # Dialog-style nested params: algorithm inputs are under "inputs" key
        params = {
            "inputs": {
                "INPUT": str(input_gpkg),
                "DISTANCE": 10,
            },
            "area_units": "m2",
        }
        result = {"OUTPUT": str(output_gpkg)}

        hooks._record_processing_lineage("native:buffer", params, result)

        assert "parents" in captured
        assert str(input_gpkg) in captured["parents"]

    def test_flat_params_still_work(self, tmp_path, monkeypatch):
        """Flat params from processing.run() hook still produce correct parents."""
        from GeoLineage.lineage_core import checksum, hooks, recorder

        input_gpkg = tmp_path / "input.gpkg"
        input_gpkg.write_bytes(b"dummy")
        output_gpkg = tmp_path / "output.gpkg"
        output_gpkg.write_bytes(b"dummy")

        captured = {}

        def fake_record_processing(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(recorder, "record_processing", fake_record_processing)
        monkeypatch.setattr(checksum, "compute_checksum", lambda path: "fake")

        # Flat params (from processing.run hook) — no "inputs" nesting
        params = {
            "INPUT": str(input_gpkg),
            "DISTANCE": 10,
        }
        result = {"OUTPUT": str(output_gpkg)}

        hooks._record_processing_lineage("native:buffer", params, result)

        assert "parents" in captured
        assert str(input_gpkg) in captured["parents"]

    def test_no_inputs_key_passes_through(self, tmp_path, monkeypatch):
        """Params without 'inputs' key work without error."""
        from GeoLineage.lineage_core import checksum, hooks, recorder

        output_gpkg = tmp_path / "output.gpkg"
        output_gpkg.write_bytes(b"dummy")

        captured = {}

        def fake_record_processing(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(recorder, "record_processing", fake_record_processing)
        monkeypatch.setattr(checksum, "compute_checksum", lambda path: "fake")

        params = {"DISTANCE": 10}
        result = {"OUTPUT": str(output_gpkg)}

        hooks._record_processing_lineage("native:buffer", params, result)

        assert captured.get("parents") == []


# --- Step 12: dynamic input-key discovery ---


def test_get_input_keys_uses_algorithm_definitions():
    """_get_input_keys must return keys derived from parameterDefinitions, not a hardcoded list."""
    from unittest.mock import MagicMock, patch

    from GeoLineage.lineage_core.hooks import _get_input_keys

    mock_param = MagicMock()
    mock_param.name.return_value = "CUSTOM_INPUT"
    mock_param.__class__.__name__ = "QgsProcessingParameterVectorLayer"

    mock_alg = MagicMock()
    mock_alg.parameterDefinitions.return_value = [mock_param]

    with patch("GeoLineage.lineage_core.hooks.QgsApplication") as mock_app:
        mock_app.processingRegistry.return_value.algorithmById.return_value = mock_alg
        keys = _get_input_keys("some:algorithm")

    assert "CUSTOM_INPUT" in keys


# --- Step 11: log warning when history_details absent ---


def test_dialog_hook_warns_when_history_details_missing(caplog):
    """Missing history_details must emit a WARNING, not silently drop parents."""
    import logging

    from GeoLineage.lineage_core.hooks import _extract_dialog_parameters

    class FakeDialog:
        pass  # no history_details attribute

    with caplog.at_level(logging.WARNING, logger="GeoLineage"):
        params = _extract_dialog_parameters(FakeDialog())

    assert params == {}
    assert any("history_details" in r.message for r in caplog.records)


# --- Step 10: thread-safe _pending_edit_snapshots ---


def test_pending_edit_snapshots_thread_safe():
    """Concurrent writes/reads/pops on _pending_edit_snapshots must not raise."""
    import threading

    from GeoLineage.lineage_core import hooks

    errors: list[Exception] = []

    def writer(layer_id: str) -> None:
        try:
            for _ in range(1000):
                hooks._pending_edit_snapshots[layer_id] = {"col": 1}
                hooks._pending_edit_snapshots.get(layer_id)
                hooks._pending_edit_snapshots.pop(layer_id, None)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(f"layer_{i}",)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread safety errors: {errors}"


# --- Edit-signal lifecycle tests (issue 1.2) ---


class FakeSignal:
    """Minimal Qt-signal stand-in with connect/disconnect/emit semantics."""

    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self, slot) -> None:
        # Mimic Qt: disconnecting an unconnected slot raises.
        try:
            self._slots.remove(slot)
        except ValueError as exc:
            raise TypeError("slot not connected") from exc

    def emit(self) -> None:
        for slot in list(self._slots):
            slot()

    def slot_count(self) -> int:
        return len(self._slots)


class MockEditableLayer:
    """Duck-typed editable GeoPackage layer for lifecycle tests."""

    def __init__(self, layer_id="layer-1", source="/tmp/test.gpkg", *, with_before=True, with_will_delete=True):
        self._id = layer_id
        self._source = source
        self.afterCommitChanges = FakeSignal()
        if with_before:
            self.beforeCommitChanges = FakeSignal()
        if with_will_delete:
            self.willBeDeleted = FakeSignal()
        self.edit_buffer_error: Exception | None = None

    def id(self):
        return self._id

    def source(self):
        return self._source

    def name(self):
        return "rivers"

    def editBuffer(self):
        if self.edit_buffer_error is not None:
            raise self.edit_buffer_error
        return None


class TestEditSignalLifecycle:
    def setup_method(self):
        from GeoLineage.lineage_core import hooks

        hooks._hook_state["_layer_edit_connections"] = {}
        hooks._pending_edit_snapshots.clear()

    def teardown_method(self):
        from GeoLineage.lineage_core import hooks

        hooks._hook_state["_layer_edit_connections"] = {}
        hooks._pending_edit_snapshots.clear()

    def test_skip_without_before_commit(self):
        from GeoLineage.lineage_core import hooks

        layer = MockEditableLayer(with_before=False)
        hooks._connect_edit_signals(layer)

        assert "layer-1" not in hooks._hook_state["_layer_edit_connections"]

    def test_connect_registers_bookkeeping(self):
        from GeoLineage.lineage_core import hooks

        layer = MockEditableLayer()
        hooks._connect_edit_signals(layer)

        assert "layer-1" in hooks._hook_state["_layer_edit_connections"]
        assert layer.beforeCommitChanges.slot_count() == 1
        assert layer.afterCommitChanges.slot_count() == 1
        assert layer.willBeDeleted.slot_count() == 1

    def test_no_duplicate_connections(self):
        from GeoLineage.lineage_core import hooks

        layer = MockEditableLayer()
        hooks._connect_edit_signals(layer)
        hooks._connect_edit_signals(layer)  # re-fire of layersAdded

        assert layer.beforeCommitChanges.slot_count() == 1
        assert layer.afterCommitChanges.slot_count() == 1
        assert len(hooks._hook_state["_layer_edit_connections"]) == 1

    def test_will_be_deleted_cleans_bookkeeping_and_snapshots(self):
        from GeoLineage.lineage_core import hooks

        layer = MockEditableLayer()
        hooks._connect_edit_signals(layer)
        hooks._pending_edit_snapshots["layer-1"] = {"features_added": 3}

        layer.willBeDeleted.emit()

        assert "layer-1" not in hooks._hook_state["_layer_edit_connections"]
        assert "layer-1" not in hooks._pending_edit_snapshots

    def test_runtime_error_in_before_commit_cleans_up(self):
        from GeoLineage.lineage_core import hooks

        layer = MockEditableLayer()
        layer.edit_buffer_error = RuntimeError("wrapped C++ object deleted")
        hooks._connect_edit_signals(layer)

        # Emitting the snapshot handler must not raise, and must self-clean.
        layer.beforeCommitChanges.emit()

        assert "layer-1" not in hooks._hook_state["_layer_edit_connections"]
        assert "layer-1" not in hooks._pending_edit_snapshots

    def test_disconnect_helper_purges_snapshots(self):
        from GeoLineage.lineage_core import hooks

        layer = MockEditableLayer()
        hooks._connect_edit_signals(layer)
        hooks._pending_edit_snapshots["layer-1"] = {"features_added": 1}

        hooks._disconnect_layer_edit_signals("layer-1")

        assert "layer-1" not in hooks._hook_state["_layer_edit_connections"]
        assert "layer-1" not in hooks._pending_edit_snapshots
        assert layer.beforeCommitChanges.slot_count() == 0
        assert layer.afterCommitChanges.slot_count() == 0

    def test_disconnect_helper_idempotent(self):
        from GeoLineage.lineage_core import hooks

        # Calling for an unknown layer must be a safe no-op.
        hooks._disconnect_layer_edit_signals("ghost")
        hooks._disconnect_layer_edit_signals("ghost")


# --- Dynamic input-key discovery tests (issue 3.3) ---


class TestDynamicInputKeys:
    def test_uses_dynamic_keys_for_algorithm(self, monkeypatch):
        from unittest.mock import MagicMock

        from GeoLineage.lineage_core import hooks

        # A registry that reports a non-standard vector input parameter name.
        param_type = type("QgsProcessingParameterVectorLayer", (), {"name": lambda self: "CUSTOM_INPUT"})
        fake_alg = MagicMock()
        fake_alg.parameterDefinitions.return_value = [param_type()]
        fake_registry = MagicMock()
        fake_registry.algorithmById.return_value = fake_alg
        fake_app = MagicMock()
        fake_app.processingRegistry.return_value = fake_registry
        monkeypatch.setattr(hooks, "QgsApplication", fake_app)

        class FakeLayer:
            def id(self):
                return "layer-42"

        params = {"CUSTOM_INPUT": FakeLayer()}
        ids = hooks._extract_input_layer_ids(params, "custom:algo")
        assert ids == ["layer-42"]

    def test_without_algorithm_name_uses_fallback_only(self):
        from GeoLineage.lineage_core import hooks

        class FakeLayer:
            def id(self):
                return "layer-42"

        # CUSTOM_INPUT is not in the fallback keys, so it is ignored.
        params = {"CUSTOM_INPUT": FakeLayer()}
        assert hooks._extract_input_layer_ids(params) == []


# --- Tier 4: edit-summary and edit-lineage integration paths ---


class TestBuildEditSummary:
    def test_counts_from_edit_buffer(self):
        from GeoLineage.lineage_core import hooks

        class Buf:
            def addedFeatures(self):
                return {1: 0, 2: 0}

            def changedGeometries(self):
                return {1: 0}

            def deletedFeatureIds(self):
                return [9]

            def changedAttributeValues(self):
                return {1: 0, 2: 0, 3: 0}

        class Layer:
            def editBuffer(self):
                return Buf()

        summary = hooks._build_edit_summary(Layer())
        assert summary == {
            "features_added": 2,
            "features_modified": 1,
            "features_deleted": 1,
            "attributes_modified": 3,
        }

    def test_no_buffer_returns_zeros(self):
        from GeoLineage.lineage_core import hooks

        class Layer:
            def editBuffer(self):
                return None

        summary = hooks._build_edit_summary(Layer())
        assert summary == {
            "features_added": 0,
            "features_modified": 0,
            "features_deleted": 0,
            "attributes_modified": 0,
        }


class TestRecordEditLineage:
    def test_calls_record_edit_with_summary(self, monkeypatch):
        import GeoLineage.lineage_core.recorder as recorder
        from GeoLineage.lineage_core import hooks

        captured = {}
        monkeypatch.setattr(recorder, "record_edit", lambda **kw: captured.update(kw) or 1)
        monkeypatch.setattr(hooks, "_get_created_by", lambda: "tester")

        class Layer:
            def name(self):
                return "parcels"

        hooks._record_edit_lineage(Layer(), "/data/x.gpkg", {"features_added": 2})

        assert captured["gpkg_path"] == "/data/x.gpkg"
        assert captured["layer_name"] == "parcels"
        assert captured["edit_summary"] == {"features_added": 2}
        assert captured["created_by"] == "tester"


# --- Tier 4: processing.run() wrapper behavior ---


class TestProcessingHookWrapper:
    def setup_method(self):
        from GeoLineage.lineage_core import hooks

        hooks._local.depth = 0
        hooks._hook_state["processing_original"] = None
        hooks._hook_state["processing_wrapper"] = None

    def _install_fake_processing(self, monkeypatch, original_run):
        import sys
        import types

        fake_processing = types.ModuleType("processing")
        fake_processing.run = original_run
        monkeypatch.setitem(sys.modules, "processing", fake_processing)
        return fake_processing

    def test_wrapper_calls_original_and_records_at_depth_one(self, monkeypatch):
        from GeoLineage.lineage_core import hooks

        calls = {"run": 0}

        def original_run(name, params, **kw):
            calls["run"] += 1
            return {"OUTPUT": "/out.gpkg"}

        fake = self._install_fake_processing(monkeypatch, original_run)

        recorded = {}
        monkeypatch.setattr(
            hooks,
            "_record_processing_lineage",
            lambda alg, params, result: recorded.update(alg=alg, params=params, result=result),
        )

        hooks._install_processing_hook()
        assert fake.run is not original_run  # patched

        out = fake.run("native:buffer", {"DISTANCE": 5})
        assert out == {"OUTPUT": "/out.gpkg"}
        assert calls["run"] == 1
        assert recorded == {"alg": "native:buffer", "params": {"DISTANCE": 5}, "result": {"OUTPUT": "/out.gpkg"}}

        hooks._uninstall_processing_hook()
        assert fake.run is original_run  # restored via identity check

    def test_recording_exception_does_not_break_run(self, monkeypatch):
        from GeoLineage.lineage_core import hooks

        def original_run(name, params, **kw):
            return {"OUTPUT": "/out.gpkg"}

        fake = self._install_fake_processing(monkeypatch, original_run)

        def boom(*_args, **_kw):
            raise RuntimeError("recording blew up")

        monkeypatch.setattr(hooks, "_record_processing_lineage", boom)

        hooks._install_processing_hook()
        # The user's processing result must still come back despite the failure.
        out = fake.run("native:buffer", {"X": 1})
        assert out == {"OUTPUT": "/out.gpkg"}
        hooks._uninstall_processing_hook()

    def test_nested_run_records_once(self, monkeypatch):
        from GeoLineage.lineage_core import hooks

        record_count = {"n": 0}

        # original_run re-enters processing.run (a nested algorithm call).
        def original_run(name, params, **kw):
            if name == "outer":
                fake.run("inner", {})  # nested depth-2 call
            return {"OUTPUT": "/out.gpkg"}

        fake = self._install_fake_processing(monkeypatch, original_run)
        monkeypatch.setattr(
            hooks,
            "_record_processing_lineage",
            lambda *a, **k: record_count.__setitem__("n", record_count["n"] + 1),
        )

        hooks._install_processing_hook()
        fake.run("outer", {})
        hooks._uninstall_processing_hook()

        # Only the outermost (depth-1) call records.
        assert record_count["n"] == 1
