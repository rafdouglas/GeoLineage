"""QGIS hook installation for lineage recording.

Monkey-patches processing.run() and QgsVectorFileWriter.writeAsVectorFormatV3()
to intercept operations and record lineage. Connects edit signals on GeoPackage
layers.

All lineage recording is exception-isolated: failures are logged but never
break QGIS operations.
"""

import contextlib
import logging
import os
import threading
from typing import Any

from .memory_buffer import MemoryBuffer
from .settings import LOGGER_NAME, SETTING_USERNAME

logger = logging.getLogger(f"{LOGGER_NAME}.hooks")

# Shared memory buffer for temporary layer lineage
_memory_buffer = MemoryBuffer()

# Thread-local storage for re-entrancy guard
_local = threading.local()

# Module-level state tracking for installed hooks
_hook_state: dict[str, Any] = {
    "processing_original": None,
    "processing_wrapper": None,
    "filewriter_original": None,
    "filewriter_wrapper": None,
    "signal_connections": [],
    "installed": False,
}

# Per-layer edit snapshots: captured in beforeCommitChanges (before buffer is cleared),
# consumed in afterCommitChanges (after commit succeeds).
_pending_edit_snapshots: dict[str, dict[str, int]] = {}


def _get_created_by() -> str | None:
    """Return username from settings if non-empty, else None."""
    try:
        from qgis.core import QgsSettings

        value = QgsSettings().value(SETTING_USERNAME, "", str)
        return value if value else None
    except ImportError:
        return None


def get_memory_buffer() -> MemoryBuffer:
    """Return the shared memory buffer instance."""
    return _memory_buffer


def _get_depth() -> int:
    """Get current re-entrancy depth (thread-local)."""
    return getattr(_local, "depth", 0)


def _increment_depth() -> int:
    """Increment and return re-entrancy depth."""
    depth = _get_depth() + 1
    _local.depth = depth
    return depth


def _decrement_depth() -> int:
    """Decrement and return re-entrancy depth."""
    depth = max(0, _get_depth() - 1)
    _local.depth = depth
    return depth


def _strip_layername(path: str) -> str:
    """Strip |layername=... suffix from a QGIS data source URI."""
    return path.split("|")[0]


def _is_gpkg_path(path: str | None) -> bool:
    """Check if a path refers to a GeoPackage file."""
    if not path or not isinstance(path, str):
        return False
    return _strip_layername(path).lower().endswith(".gpkg")


def _resolve_output_layer_definition(obj: Any) -> Any:
    """Unwrap QgsProcessingOutputLayerDefinition to a plain string path.

    If obj has a .sink attribute with a .staticValue() method, call it to
    extract the underlying string path. If .sink is itself a string, return
    it directly. Otherwise return obj unchanged.
    """
    if not hasattr(obj, "sink"):
        return obj
    sink = obj.sink
    if isinstance(sink, str):
        logger.debug("Resolved OutputLayerDefinition with string sink: %s", sink)
        return sink
    if hasattr(sink, "staticValue") and callable(sink.staticValue):
        value = sink.staticValue()
        logger.debug("Resolved OutputLayerDefinition via staticValue: %s", value)
        return value
    return obj


def _extract_input_layer_ids(params: dict) -> list[str]:
    """Extract layer IDs from processing parameters.

    Looks for common parameter names that reference input layers.
    Handles both single layer and list-of-layers parameters.
    Returns a list of layer ID strings.
    """
    input_keys = ("INPUT", "INPUT_LAYER", "LAYERS", "INPUT1", "INPUT2", "OVERLAY", "LAYER", "SOURCE_LAYER")
    ids: list[str] = []

    for key in input_keys:
        value = params.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            for item in value:
                layer_id = _get_layer_id(item)
                if layer_id:
                    ids.append(layer_id)
        else:
            layer_id = _get_layer_id(value)
            if layer_id:
                ids.append(layer_id)

    return ids


def _get_layer_id(obj: Any) -> str | None:
    """Extract layer ID from a layer object or string.

    Handles QgsMapLayer objects (have .id() method) and string references.
    For string references, attempts QgsProject lookup to resolve layer IDs.
    """
    if hasattr(obj, "id") and callable(obj.id):
        return obj.id()
    if isinstance(obj, str):
        try:
            from qgis.core import QgsProject

            layer = QgsProject.instance().mapLayer(obj)
            if layer is not None:
                return layer.id()
        except Exception:
            pass
    return None


def _get_layer_source_path(obj: Any) -> str | None:
    """Extract the file path from a layer object or string.

    Handles QgsMapLayer objects (have .source() method), direct file path
    strings (with optional |layername= suffix), and string layer IDs
    (resolved via QgsProject lookup).
    """
    if hasattr(obj, "source") and callable(obj.source):
        source = obj.source()
        if isinstance(source, str):
            # Source may include |layername=xxx suffix
            base = source.split("|")[0]
            if os.path.isfile(base):
                return base
    if isinstance(obj, str):
        # Try as direct file path (with optional |layername= suffix)
        base = obj.split("|")[0]
        if os.path.isfile(base):
            return base
        # Try as layer ID string — look up in QgsProject
        try:
            from qgis.core import QgsProject

            layer = QgsProject.instance().mapLayer(obj)
            if layer is not None:
                source = layer.source()
                if isinstance(source, str):
                    base = source.split("|")[0]
                    if os.path.isfile(base):
                        return base
        except Exception:
            pass
    return None


def _get_output_layer_info(result: dict, params: dict) -> tuple[str | None, str | None, str | None]:
    """Extract output layer ID, path, and name from processing result.

    Returns (layer_id, gpkg_path, layer_name).
    """
    output = result.get("OUTPUT")
    output = _resolve_output_layer_definition(output)
    if output is None:
        return None, None, None

    layer_id = None
    gpkg_path = None
    layer_name = None

    # Output can be a QgsMapLayer or a string path
    if hasattr(output, "id") and callable(output.id):
        layer_id = output.id()
        layer_name = output.name() if hasattr(output, "name") else None
        source_path = _get_layer_source_path(output)
        if source_path and _is_gpkg_path(source_path):
            gpkg_path = source_path
    elif isinstance(output, str) and _is_gpkg_path(output):
        gpkg_path = _strip_layername(output)
        layer_name = os.path.splitext(os.path.basename(gpkg_path))[0]

    # Check explicit output parameter for gpkg path
    if gpkg_path is None:
        output_param = params.get("OUTPUT", "")
        output_param = _resolve_output_layer_definition(output_param)
        if isinstance(output_param, str) and _is_gpkg_path(output_param):
            gpkg_path = _strip_layername(output_param)

    return layer_id, gpkg_path, layer_name


def _record_processing_lineage(
    algorithm_name: str,
    params: dict,
    result: dict,
) -> None:
    """Record lineage for a processing.run() call.

    Called inside exception isolation — any error here is caught by the wrapper.
    """
    from .checksum import compute_checksum
    from .recorder import record_processing

    # Dialog hook passes params with algorithm inputs nested under "inputs" key.
    # Unwrap so that INPUT, OVERLAY, etc. are at the top level.
    inner = params.get("inputs")
    if isinstance(inner, dict):
        params = {**params, **inner}

    input_layer_ids = _extract_input_layer_ids(params)
    layer_id, gpkg_path, layer_name = _get_output_layer_info(result, params)

    logger.info(
        "Lineage hook fired: algorithm=%s, gpkg_path=%s, layer_id=%s, result_OUTPUT=%r, params_OUTPUT=%r",
        algorithm_name,
        gpkg_path,
        layer_id,
        result.get("OUTPUT"),
        params.get("OUTPUT"),
    )

    if layer_name is None:
        layer_name = "unknown"

    # Gather parent info
    parents: list[str] = []
    parent_metadata: list[dict] = []
    parent_checksums: dict[str, str] = {}

    for key in ("INPUT", "INPUT_LAYER", "OVERLAY", "LAYER", "SOURCE_LAYER", "INPUT1", "INPUT2", "LAYERS"):
        value = params.get(key)
        if value is None:
            continue
        items = value if isinstance(value, list) else [value]
        for item in items:
            item = _resolve_output_layer_definition(item)
            source_path = _get_layer_source_path(item)
            if source_path and source_path not in parents:
                parents.append(source_path)
                try:
                    parent_checksums[source_path] = compute_checksum(source_path)
                except Exception:
                    logger.debug("Could not compute checksum for %s", source_path)

    # Get output CRS if available
    output_crs_epsg = None
    output_layer = result.get("OUTPUT")
    if hasattr(output_layer, "crs") and callable(output_layer.crs):
        crs = output_layer.crs()
        if hasattr(crs, "postgisSrid") and callable(crs.postgisSrid):
            output_crs_epsg = crs.postgisSrid()

    entry = {
        "layer_name": layer_name,
        "tool": algorithm_name,
        "params": _sanitize_params(params),
        "parents": parents,
        "parent_metadata": parent_metadata,
        "parent_checksums": parent_checksums,
        "output_crs_epsg": output_crs_epsg,
        "created_by": _get_created_by(),
    }

    if gpkg_path:
        # Output is a GeoPackage file — write directly
        record_processing(
            gpkg_path=gpkg_path,
            layer_name=layer_name,
            tool=algorithm_name,
            params=_sanitize_params(params),
            parents=parents,
            parent_metadata=parent_metadata,
            parent_checksums=parent_checksums,
            output_crs_epsg=output_crs_epsg,
            created_by=_get_created_by(),
        )
        # Also flush any buffered chain for input layers
        if layer_id:
            for input_id in input_layer_ids:
                chain = _memory_buffer.get_chain(input_id)
                if chain:
                    _memory_buffer.flush(input_id, gpkg_path)
        logger.debug("Recorded processing lineage to %s", gpkg_path)
    elif layer_id:
        # Output is a temporary/memory layer — buffer it
        _memory_buffer.add(layer_id, entry)
        _memory_buffer.link(layer_id, input_layer_ids)
        logger.debug("Buffered processing lineage for layer %s", layer_id)
    else:
        logger.warning(
            "Lineage NOT recorded: gpkg_path=%s, layer_id=%s for algorithm=%s",
            gpkg_path,
            layer_id,
            algorithm_name,
        )


def _sanitize_params(params: dict) -> dict:
    """Create a JSON-safe copy of processing parameters.

    Replaces non-serializable objects (layers, etc.) with string representations.
    """
    safe: dict[str, Any] = {}
    for key, value in params.items():
        if hasattr(value, "id") and callable(value.id):
            safe[key] = f"<layer:{value.id()}>"
        elif isinstance(value, (str, int, float, bool, type(None))):
            safe[key] = value
        elif isinstance(value, (list, tuple)):
            safe[key] = [
                f"<layer:{v.id()}>"
                if hasattr(v, "id") and callable(v.id)
                else v
                if isinstance(v, (str, int, float, bool, type(None)))
                else str(v)
                for v in value
            ]
        elif isinstance(value, dict):
            safe[key] = {str(k): str(v) for k, v in value.items()}
        else:
            safe[key] = str(value)
    return safe


def install_hooks() -> None:
    """Install all lineage recording hooks.

    - Monkey-patches processing.run() (Python API calls)
    - Monkey-patches AlgorithmDialog.finish() (GUI toolbox runs)
    - Monkey-patches QgsVectorFileWriter.writeAsVectorFormatV3()
    - Connects layersAdded signal for edit tracking

    Safe to call multiple times (idempotent).
    """
    if _hook_state["installed"]:
        logger.debug("Hooks already installed")
        return

    _install_processing_hook()
    _install_dialog_hook()
    _install_filewriter_hook()
    _install_edit_signals()
    _hook_state["installed"] = True
    logger.info("GeoLineage hooks installed")


def uninstall_hooks() -> None:
    """Remove all lineage recording hooks.

    - Restores original processing.run() (with identity check)
    - Restores original QgsVectorFileWriter.writeAsVectorFormatV3() (with identity check)
    - Disconnects all signal connections

    Safe to call multiple times (idempotent).
    """
    if not _hook_state["installed"]:
        logger.debug("Hooks not installed, nothing to uninstall")
        return

    _uninstall_processing_hook()
    _uninstall_dialog_hook()
    _uninstall_filewriter_hook()
    _uninstall_edit_signals()
    _hook_state["installed"] = False
    logger.info("GeoLineage hooks uninstalled")


def _install_processing_hook() -> None:
    """Monkey-patch processing.run() with lineage recording wrapper."""
    try:
        import processing
    except ImportError:
        logger.warning("processing module not available — skipping processing hook")
        return

    original = processing.run
    _hook_state["processing_original"] = original

    def _wrapped_run(*args: Any, **kwargs: Any) -> Any:
        depth = _increment_depth()
        try:
            result = original(*args, **kwargs)
        except Exception:
            _decrement_depth()
            raise

        try:
            if depth == 1 and result is not None:
                # Extract algorithm name from first positional arg
                algorithm_name = args[0] if args else kwargs.get("algOrName", "unknown")
                run_params = args[1] if len(args) > 1 else kwargs.get("parameters", {})
                if isinstance(run_params, dict) and isinstance(result, dict):
                    _record_processing_lineage(algorithm_name, run_params, result)
        except Exception:
            logger.exception("Lineage recording failed; QGIS operation unaffected")
        finally:
            _decrement_depth()

        return result

    processing.run = _wrapped_run
    _hook_state["processing_wrapper"] = _wrapped_run
    logger.debug("processing.run() monkey-patched")


def _uninstall_processing_hook() -> None:
    """Restore original processing.run() with identity check."""
    original = _hook_state.get("processing_original")
    wrapper = _hook_state.get("processing_wrapper")
    if original is None:
        return

    try:
        import processing
    except ImportError:
        return

    if processing.run is wrapper:
        processing.run = original
        logger.debug("processing.run() restored")
    else:
        logger.warning(
            "processing.run() identity mismatch — another plugin may have "
            "wrapped it after us. Skipping restoration to avoid breaking "
            "the other plugin's hook."
        )

    _hook_state["processing_original"] = None
    _hook_state["processing_wrapper"] = None


def _install_dialog_hook() -> None:
    """Monkey-patch AlgorithmDialog.finish() for GUI-initiated algorithm runs.

    The QGIS Processing toolbox dialog does NOT call processing.run().
    Instead it calls AlgorithmExecutor.execute() or QgsProcessingAlgRunnerTask
    directly, both of which converge in AlgorithmDialog.finish().
    """
    try:
        from processing.gui.AlgorithmDialog import AlgorithmDialog
    except ImportError:
        logger.warning("AlgorithmDialog not available — skipping dialog hook")
        return

    original_finish = AlgorithmDialog.finish
    _hook_state["dialog_original_finish"] = original_finish

    def _wrapped_finish(dialog_self, successful, result, context, feedback, in_place=False):
        original_finish(dialog_self, successful, result, context, feedback, in_place)

        try:
            if not successful or in_place or not isinstance(result, dict):
                return
            if "OUTPUT" not in result:
                return

            algorithm_name = dialog_self.algorithm().id()
            # Recover input parameters from the history details stored during runAlgorithm()
            params = getattr(dialog_self, "history_details", {}).get("parameters", {})

            logger.info("Dialog hook fired: algorithm=%s, result_OUTPUT=%r", algorithm_name, result.get("OUTPUT"))
            _record_processing_lineage(algorithm_name, params, result)
        except Exception:
            logger.exception("Dialog lineage recording failed; operation unaffected")

    AlgorithmDialog.finish = _wrapped_finish
    _hook_state["dialog_wrapper_finish"] = _wrapped_finish
    logger.debug("AlgorithmDialog.finish() monkey-patched")


def _uninstall_dialog_hook() -> None:
    """Restore original AlgorithmDialog.finish() with identity check."""
    original = _hook_state.get("dialog_original_finish")
    wrapper = _hook_state.get("dialog_wrapper_finish")
    if original is None:
        return

    try:
        from processing.gui.AlgorithmDialog import AlgorithmDialog
    except ImportError:
        return

    if AlgorithmDialog.finish is wrapper:
        AlgorithmDialog.finish = original
        logger.debug("AlgorithmDialog.finish() restored")
    else:
        logger.warning("AlgorithmDialog.finish() identity mismatch — skipping restoration")

    _hook_state["dialog_original_finish"] = None
    _hook_state["dialog_wrapper_finish"] = None


def _install_filewriter_hook() -> None:
    """Monkey-patch QgsVectorFileWriter.writeAsVectorFormatV3() for export detection."""
    try:
        from qgis.core import QgsVectorFileWriter
    except ImportError:
        logger.warning("qgis.core not available — skipping file writer hook")
        return

    if not hasattr(QgsVectorFileWriter, "writeAsVectorFormatV3"):
        logger.warning("QgsVectorFileWriter.writeAsVectorFormatV3 not found — skipping")
        return

    original = QgsVectorFileWriter.writeAsVectorFormatV3

    _hook_state["filewriter_original"] = original

    def _wrapped_write(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        try:
            _record_export_lineage(args, kwargs, result)
        except Exception:
            logger.exception("Export lineage recording failed; export unaffected")
        return result

    QgsVectorFileWriter.writeAsVectorFormatV3 = staticmethod(_wrapped_write)
    _hook_state["filewriter_wrapper"] = _wrapped_write
    logger.debug("QgsVectorFileWriter.writeAsVectorFormatV3() monkey-patched")


def _uninstall_filewriter_hook() -> None:
    """Restore original QgsVectorFileWriter.writeAsVectorFormatV3()."""
    original = _hook_state.get("filewriter_original")
    wrapper = _hook_state.get("filewriter_wrapper")
    if original is None:
        return

    try:
        from qgis.core import QgsVectorFileWriter
    except ImportError:
        return

    current = getattr(QgsVectorFileWriter, "writeAsVectorFormatV3", None)
    # For static methods, identity check may not work directly
    # Compare with our stored wrapper
    if current is wrapper or getattr(current, "__func__", current) is wrapper:
        QgsVectorFileWriter.writeAsVectorFormatV3 = original
        logger.debug("QgsVectorFileWriter.writeAsVectorFormatV3() restored")
    else:
        logger.warning("QgsVectorFileWriter.writeAsVectorFormatV3() identity mismatch — skipping restoration")

    _hook_state["filewriter_original"] = None
    _hook_state["filewriter_wrapper"] = None


def _record_export_lineage(args: tuple, kwargs: dict, result: Any) -> None:
    """Record lineage for a QgsVectorFileWriter export.

    writeAsVectorFormatV3(layer, fileName, transformContext, options, ...)
    """
    from .recorder import record_export

    # Check if export succeeded — result is a tuple (error_code, error_message)
    if isinstance(result, tuple) and len(result) >= 1:
        error_code = result[0]
        # QgsVectorFileWriter.WriterError.NoError == 0
        if hasattr(error_code, "value"):
            error_code = error_code.value
        if error_code != 0:
            return

    # Extract source layer (first arg)
    source_layer = args[0] if args else None
    if source_layer is None:
        return

    source_path = _get_layer_source_path(source_layer)
    if not source_path:
        return

    # Extract output file name (second arg)
    output_path = args[1] if len(args) > 1 else kwargs.get("fileName")
    if not output_path or not _is_gpkg_path(output_path):
        return

    output_path = _strip_layername(output_path)
    layer_name = source_layer.name() if hasattr(source_layer, "name") else "unknown"

    # Compute parent checksums
    parent_checksums: dict[str, str] = {}
    try:
        from .checksum import compute_checksum

        parent_checksums[source_path] = compute_checksum(source_path)
    except Exception:
        logger.debug("Could not compute checksum for %s", source_path)

    output_crs_epsg = None
    if hasattr(source_layer, "crs") and callable(source_layer.crs):
        crs = source_layer.crs()
        if hasattr(crs, "postgisSrid") and callable(crs.postgisSrid):
            output_crs_epsg = crs.postgisSrid()

    record_export(
        gpkg_path=output_path,
        layer_name=layer_name,
        parent_path=source_path,
        parent_metadata=[],
        parent_checksums=parent_checksums,
        output_crs_epsg=output_crs_epsg,
        created_by=_get_created_by(),
    )
    logger.debug("Recorded export lineage: %s -> %s", source_path, output_path)


def _install_edit_signals() -> None:
    """Connect signals for tracking manual edits on GeoPackage layers."""
    try:
        from qgis.core import QgsProject
    except ImportError:
        logger.warning("qgis.core not available — skipping edit signals")
        return

    project = QgsProject.instance()
    connection = project.layersAdded.connect(_on_layers_added)
    _hook_state["signal_connections"].append(("layersAdded", connection))

    # Connect to existing GeoPackage layers
    for _layer_id, layer in project.mapLayers().items():
        _connect_edit_signals(layer)

    logger.debug("Edit signals installed")


def _uninstall_edit_signals() -> None:
    """Disconnect all edit tracking signals."""
    try:
        from qgis.core import QgsProject
    except ImportError:
        return

    project = QgsProject.instance()
    with contextlib.suppress(TypeError, RuntimeError):
        project.layersAdded.disconnect(_on_layers_added)

    # Disconnect per-layer signals
    for _layer_id, handler in list(_hook_state.get("_layer_edit_connections", {}).items()):
        with contextlib.suppress(TypeError, RuntimeError):
            handler()  # Each handler is a disconnect callable

    _hook_state["signal_connections"] = []
    _hook_state["_layer_edit_connections"] = {}
    logger.debug("Edit signals disconnected")


def _on_layers_added(layers: list) -> None:
    """Handle layersAdded signal — connect edit tracking to GeoPackage layers."""
    for layer in layers:
        try:
            _connect_edit_signals(layer)
        except Exception:
            logger.exception("Failed to connect edit signals for layer")


def _connect_edit_signals(layer: Any) -> None:
    """Connect edit tracking signals for a single GeoPackage-backed layer.

    Uses beforeCommitChanges to snapshot the edit buffer (before it's cleared)
    and afterCommitChanges to record the lineage (after commit succeeds).
    """
    if not hasattr(layer, "source") or not callable(layer.source):
        return

    source = layer.source()
    if not isinstance(source, str):
        return

    base_path = source.split("|")[0]
    if not _is_gpkg_path(base_path):
        return

    if not hasattr(layer, "afterCommitChanges"):
        return

    layer_id = layer.id() if hasattr(layer, "id") else str(id(layer))

    def _on_before_commit() -> None:
        """Snapshot edit buffer counts before the commit clears them."""
        try:
            _pending_edit_snapshots[layer_id] = _build_edit_summary(layer)
        except Exception:
            logger.exception("Failed to snapshot edit buffer")

    def _on_after_commit() -> None:
        """Record lineage using the pre-commit snapshot."""
        try:
            snapshot = _pending_edit_snapshots.pop(layer_id, None)
            if snapshot and any(snapshot.values()):
                _record_edit_lineage(layer, base_path, snapshot)
        except Exception:
            logger.exception("Edit lineage recording failed; edit unaffected")

    layer.beforeCommitChanges.connect(_on_before_commit)
    layer.afterCommitChanges.connect(_on_after_commit)

    # Store disconnect callable
    edit_connections = _hook_state.setdefault("_layer_edit_connections", {})

    def _disconnect() -> None:
        with contextlib.suppress(TypeError, RuntimeError):
            layer.beforeCommitChanges.disconnect(_on_before_commit)
        with contextlib.suppress(TypeError, RuntimeError):
            layer.afterCommitChanges.disconnect(_on_after_commit)

    edit_connections[layer_id] = _disconnect
    logger.debug("Connected edit signals for layer %s (%s)", layer_id, base_path)


def _record_edit_lineage(layer: Any, gpkg_path: str, edit_summary: dict) -> None:
    """Record manual edit lineage after a commit on a GeoPackage layer.

    edit_summary is a pre-captured snapshot from beforeCommitChanges.
    """
    from .recorder import record_edit

    layer_name = layer.name() if hasattr(layer, "name") else "unknown"

    record_edit(
        gpkg_path=gpkg_path,
        layer_name=layer_name,
        edit_summary=edit_summary,
        created_by=_get_created_by(),
    )
    logger.debug("Recorded edit lineage for %s in %s", layer_name, gpkg_path)


def _build_edit_summary(layer: Any) -> dict:
    """Build edit summary dict from layer's edit buffer.

    Returns counts of features added, modified, deleted.
    """
    summary: dict[str, int] = {
        "features_added": 0,
        "features_modified": 0,
        "features_deleted": 0,
        "attributes_modified": 0,
    }

    edit_buffer = getattr(layer, "editBuffer", None)
    if edit_buffer is None or not callable(edit_buffer):
        return summary

    buf = edit_buffer()
    if buf is None:
        return summary

    if hasattr(buf, "addedFeatures"):
        summary["features_added"] = len(buf.addedFeatures())
    if hasattr(buf, "changedGeometries"):
        summary["features_modified"] = len(buf.changedGeometries())
    if hasattr(buf, "deletedFeatureIds"):
        summary["features_deleted"] = len(buf.deletedFeatureIds())
    if hasattr(buf, "changedAttributeValues"):
        summary["attributes_modified"] = len(buf.changedAttributeValues())

    return summary
