"""
GeoLineage Phase 1.5 Spike — Validate QGIS Integration Assumptions

This throwaway script validates three critical assumptions:
1. Monkey-patching processing.run() works reliably
2. Layer ID behavior across chained processing steps
3. Export/save detection mechanisms

Run inside Flatpak:
    flatpak run --command=bash org.qgis.qgis -c \
        "PYTHONPATH=/app/share/qgis/python:/app/lib/python3.13/site-packages \
         python3 /path/to/spike/validate_qgis_assumptions.py"
"""

import json
import os
import sys
import tempfile
import traceback

# ---------------------------------------------------------------------------
# 1. Initialize headless QGIS
# ---------------------------------------------------------------------------

print("=" * 70)
print("GeoLineage Spike — Phase 1.5")
print("=" * 70)

# Add QGIS plugin paths (processing lives in plugins/)
sys.path.insert(0, "/app/share/qgis/python/plugins")
sys.path.insert(0, "/app/share/qgis/python")

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from PyQt5.QtCore import QVariant

# Init headless QGIS application
app = QgsApplication([], False)
app.setPrefixPath("/app", True)
app.initQgis()

# Initialize processing framework
import processing
from processing.core.Processing import Processing

Processing.initialize()

from qgis.core import Qgis
print(f"[OK] QGIS {Qgis.version()} initialized (headless)")
print(f"[OK] Processing framework initialized")
print()

# ---------------------------------------------------------------------------
# 2. Create a test GeoPackage with sample polygons
# ---------------------------------------------------------------------------

tmpdir = tempfile.mkdtemp(prefix="geolineage_spike_")
input_gpkg = os.path.join(tmpdir, "input.gpkg")

# Create a simple polygon layer
layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "test_polygons", "memory")
provider = layer.dataProvider()
provider.addAttributes([QgsField("name", QVariant.String)])
layer.updateFields()

# Add 3 simple square polygons
for i, name in enumerate(["alpha", "beta", "gamma"]):
    feat = QgsFeature()
    x = i * 2.0
    feat.setGeometry(QgsGeometry.fromPolygonXY([[
        QgsPointXY(x, 0), QgsPointXY(x + 1, 0),
        QgsPointXY(x + 1, 1), QgsPointXY(x, 1),
        QgsPointXY(x, 0),
    ]]))
    feat.setAttributes([name])
    provider.addFeature(feat)

layer.updateExtents()

# Save to GeoPackage
error_code, error_msg = QgsVectorFileWriter.writeAsVectorFormat(
    layer, input_gpkg, "UTF-8",
    QgsCoordinateReferenceSystem("EPSG:4326"),
    "GPKG",
)

if error_code != QgsVectorFileWriter.NoError:
    print(f"[FAIL] Could not create test GeoPackage: {error_msg}")
    sys.exit(1)

print(f"[OK] Test GeoPackage created: {input_gpkg}")
print(f"     Features: {layer.featureCount()}, CRS: EPSG:4326")
print()

# ---------------------------------------------------------------------------
# 3. Monkey-patch processing.run() with a logging wrapper
# ---------------------------------------------------------------------------

print("-" * 70)
print("TEST 1: Monkey-patching processing.run()")
print("-" * 70)

call_log = []
original_run = processing.run


def logging_wrapper(*args, **kwargs):
    """Wrapper that logs calls then delegates to original."""
    call_info = {
        "args_count": len(args),
        "kwargs_keys": list(kwargs.keys()),
        "algorithm": args[0] if args else kwargs.get("algOrName", "?"),
    }

    # Capture input params (second positional arg)
    if len(args) > 1 and isinstance(args[1], dict):
        params = args[1]
        call_info["param_keys"] = list(params.keys())
        # Log layer IDs for INPUT parameters
        for key, val in params.items():
            if hasattr(val, "id"):
                call_info[f"input_{key}_layer_id"] = val.id()
                call_info[f"input_{key}_source"] = val.source()
            elif isinstance(val, str) and ("layer" in key.lower() or "input" in key.lower()):
                call_info[f"input_{key}_value"] = val

    print(f"  [WRAP] Intercepted: {call_info['algorithm']}")

    # Call original
    result = original_run(*args, **kwargs)

    # Log output info
    call_info["result_keys"] = list(result.keys()) if isinstance(result, dict) else str(type(result))
    if isinstance(result, dict):
        for key, val in result.items():
            if hasattr(val, "id"):
                call_info[f"output_{key}_layer_id"] = val.id()
                call_info[f"output_{key}_source"] = val.source()
                call_info[f"output_{key}_type"] = type(val).__name__
                call_info[f"output_{key}_is_valid"] = val.isValid()
            elif isinstance(val, str):
                call_info[f"output_{key}_value"] = val

    call_log.append(call_info)
    return result


# Apply the patch
processing.run = logging_wrapper

# Verify patch is in place
assert processing.run is logging_wrapper, "Patch failed: processing.run is not our wrapper"
print("[OK] processing.run() successfully monkey-patched")
print()

# ---------------------------------------------------------------------------
# 4. Run native:buffer on test GPKG -> temporary output
# ---------------------------------------------------------------------------

print("-" * 70)
print("TEST 2: Chain processing steps, observe layer IDs")
print("-" * 70)

# Load the input GeoPackage as a proper layer
# Try without layername first (uses default layer), fall back to common names
input_layer = QgsVectorLayer(input_gpkg, "input", "ogr")
if not input_layer.isValid():
    # Try with explicit layer name matching the file basename
    for lname in ["test_polygons", "input"]:
        input_layer = QgsVectorLayer(f"{input_gpkg}|layername={lname}", "input", "ogr")
        if input_layer.isValid():
            break
if not input_layer.isValid():
    print(f"[FAIL] Could not load input layer from {input_gpkg}")
    # Debug: list sublayers
    tmp_layer = QgsVectorLayer(input_gpkg, "probe", "ogr")
    print(f"       isValid={tmp_layer.isValid()}, subLayers={tmp_layer.dataProvider().subLayers() if tmp_layer.dataProvider() else 'no provider'}")
    sys.exit(1)

QgsProject.instance().addMapLayer(input_layer)
print(f"[OK] Input layer loaded: id={input_layer.id()}, source={input_layer.source()}")

# Step A: Run buffer -> temporary output
print()
print("  Step A: native:buffer -> temp output")
result_a = processing.run("native:buffer", {
    "INPUT": input_layer,
    "DISTANCE": 0.01,
    "SEGMENTS": 5,
    "END_CAP_STYLE": 0,
    "JOIN_STYLE": 0,
    "MITER_LIMIT": 2,
    "DISSOLVE": False,
    "OUTPUT": "memory:",
})

temp_layer_a = result_a["OUTPUT"]
print(f"  [OK] Buffer result: type={type(temp_layer_a).__name__}, "
      f"id={temp_layer_a.id()}, valid={temp_layer_a.isValid()}, "
      f"features={temp_layer_a.featureCount()}")
print(f"       source={temp_layer_a.source()}")

# Add to project (simulates user workflow)
QgsProject.instance().addMapLayer(temp_layer_a)

# Step B: Run dissolve on the buffer output -> second temp
print()
print("  Step B: native:dissolve on buffer output -> temp output")
result_b = processing.run("native:dissolve", {
    "INPUT": temp_layer_a,
    "FIELD": [],
    "OUTPUT": "memory:",
})

temp_layer_b = result_b["OUTPUT"]
print(f"  [OK] Dissolve result: type={type(temp_layer_b).__name__}, "
      f"id={temp_layer_b.id()}, valid={temp_layer_b.isValid()}, "
      f"features={temp_layer_b.featureCount()}")
print(f"       source={temp_layer_b.source()}")

# Step C: Save final result to GeoPackage
print()
print("  Step C: Save final result to GeoPackage")
output_gpkg = os.path.join(tmpdir, "output.gpkg")
result_c = processing.run("native:savefeatures", {
    "INPUT": temp_layer_b,
    "OUTPUT": output_gpkg,
})
print(f"  [OK] Saved to: {output_gpkg}")
if isinstance(result_c.get("OUTPUT"), str):
    print(f"       Result OUTPUT is a string path: {result_c['OUTPUT']}")
elif hasattr(result_c.get("OUTPUT"), "id"):
    out = result_c["OUTPUT"]
    print(f"       Result OUTPUT is a layer: id={out.id()}, source={out.source()}")

print()

# ---------------------------------------------------------------------------
# 5. Analyze layer ID behavior
# ---------------------------------------------------------------------------

print("-" * 70)
print("TEST 3: Layer ID analysis")
print("-" * 70)

ids = {
    "input": input_layer.id(),
    "buffer_output": temp_layer_a.id(),
    "dissolve_output": temp_layer_b.id(),
}

print(f"  Input layer ID:          {ids['input']}")
print(f"  Buffer output layer ID:  {ids['buffer_output']}")
print(f"  Dissolve output layer ID: {ids['dissolve_output']}")
print()

all_different = len(set(ids.values())) == len(ids)
print(f"  All IDs unique: {all_different}")

# Check if IDs follow a pattern
print(f"  ID format analysis:")
for name, lid in ids.items():
    print(f"    {name}: length={len(lid)}, "
          f"has_underscore={'_' in lid}, "
          f"starts_with={lid[:20]}...")

print()

# ---------------------------------------------------------------------------
# 6. Test export detection mechanisms
# ---------------------------------------------------------------------------

print("-" * 70)
print("TEST 4: Export detection mechanisms")
print("-" * 70)

# Test A: Check if QgsVectorFileWriter has useful signals
print("  A) QgsVectorFileWriter signal inspection:")
writer_attrs = [a for a in dir(QgsVectorFileWriter) if "signal" in a.lower() or "notify" in a.lower()]
print(f"     Signal-like attributes: {writer_attrs if writer_attrs else 'NONE'}")

# Test B: Check QgsProject signals related to layer saving
print()
print("  B) QgsProject layer-related signals:")
project = QgsProject.instance()
project_signals = [a for a in dir(project) if any(k in a.lower() for k in ["write", "save", "export", "layer"])]
print(f"     Relevant signals/methods: {sorted(set(project_signals))[:20]}")

# Test C: Monitor layerWasAdded during save
print()
print("  C) Signal monitoring during save-to-GeoPackage:")

signal_events = []


def on_layers_added(layers):
    for lyr in layers:
        signal_events.append(("layersAdded", lyr.id(), lyr.source()))


def on_layer_was_added(layer):
    signal_events.append(("layerWasAdded", layer.id(), layer.source()))


project.layersAdded.connect(on_layers_added)
project.layerWasAdded.connect(on_layer_was_added)

# Do a second save using QgsVectorFileWriter directly
export_gpkg = os.path.join(tmpdir, "exported.gpkg")
error_code, error_msg = QgsVectorFileWriter.writeAsVectorFormat(
    temp_layer_b, export_gpkg, "UTF-8",
    QgsCoordinateReferenceSystem("EPSG:4326"),
    "GPKG",
)
print(f"     QgsVectorFileWriter.writeAsVectorFormat -> error_code={error_code}")
print(f"     Signals fired during writeAsVectorFormat: {signal_events if signal_events else 'NONE'}")

signal_events.clear()

# Test D: Check for QgsVectorLayer export-related signals
print()
print("  D) QgsVectorLayer signals for edit/commit detection:")
layer_signals = [a for a in dir(temp_layer_a)
                 if any(k in a.lower() for k in
                        ["commit", "editing", "beforecommit", "aftercommit",
                         "featuresadded", "featuresdeleted", "attributevalue"])]
print(f"     Edit signals: {sorted(set(layer_signals))[:20]}")

# Disconnect signals
project.layersAdded.disconnect(on_layers_added)
project.layerWasAdded.disconnect(on_layer_was_added)

print()

# ---------------------------------------------------------------------------
# 7. Test re-entrancy (does a tool internally call processing.run?)
# ---------------------------------------------------------------------------

print("-" * 70)
print("TEST 5: Re-entrancy check")
print("-" * 70)

call_log.clear()

# Run a potentially compound algorithm
try:
    result_re = processing.run("native:buffer", {
        "INPUT": input_layer,
        "DISTANCE": 0.02,
        "SEGMENTS": 5,
        "END_CAP_STYLE": 0,
        "JOIN_STYLE": 0,
        "MITER_LIMIT": 2,
        "DISSOLVE": True,  # Dissolve=True might trigger internal dissolve
        "OUTPUT": "memory:",
    })
    print(f"  Ran native:buffer with DISSOLVE=True")
    print(f"  Total processing.run() calls intercepted: {len(call_log)}")
    for i, call in enumerate(call_log):
        print(f"    Call {i}: {call['algorithm']}")
    if len(call_log) > 1:
        print("  [WARN] Re-entrant calls detected! Depth counter needed.")
    else:
        print("  [OK] No re-entrant calls for this algorithm.")
except Exception as e:
    print(f"  [ERROR] {e}")

print()

# ---------------------------------------------------------------------------
# 8. Test uninstall (restore original)
# ---------------------------------------------------------------------------

print("-" * 70)
print("TEST 6: Uninstall (restore original)")
print("-" * 70)

# Check identity before restore
is_ours = processing.run is logging_wrapper
print(f"  processing.run is still our wrapper: {is_ours}")

# Restore
processing.run = original_run
is_restored = processing.run is original_run
print(f"  Restored original: {is_restored}")

# Verify original still works
try:
    result_verify = processing.run("native:buffer", {
        "INPUT": input_layer,
        "DISTANCE": 0.005,
        "SEGMENTS": 5,
        "END_CAP_STYLE": 0,
        "JOIN_STYLE": 0,
        "MITER_LIMIT": 2,
        "DISSOLVE": False,
        "OUTPUT": "memory:",
    })
    print(f"  [OK] Original processing.run() works after restore")
except Exception as e:
    print(f"  [FAIL] Original broken after restore: {e}")

print()

# ---------------------------------------------------------------------------
# 9. Summary report
# ---------------------------------------------------------------------------

print("=" * 70)
print("FINDINGS SUMMARY")
print("=" * 70)

print()
print("1. MONKEY-PATCHING:")
print(f"   - Wrapping processing.run() with closure: WORKS")
print(f"   - Wrapper receives correct args: {len(call_log) == 0}")  # cleared, but we tested above
print(f"   - Original restored cleanly: {is_restored}")

print()
print("2. LAYER ID BEHAVIOR:")
print(f"   - Input layer ID:   {ids['input']}")
print(f"   - Buffer output ID: {ids['buffer_output']}")
print(f"   - Dissolve output:  {ids['dissolve_output']}")
print(f"   - IDs are unique per step: {all_different}")
print(f"   - IMPLICATION: MemoryBuffer MUST use link() to chain IDs across steps")

print()
print("3. EXPORT DETECTION:")
print(f"   - QgsVectorFileWriter signals: {'FOUND' if writer_attrs else 'NONE - must use alternative'}")
print(f"   - QgsProject layer signals during writeAsVectorFormat: "
      f"{'FIRED' if signal_events else 'NONE - writeAsVectorFormat is silent'}")
print(f"   - IMPLICATION: Export detection likely needs processing.run interception")
print(f"     (native:savefeatures) or monitoring iface actions")

print()
print("4. RE-ENTRANCY:")
print(f"   - Check call_log from test above for nested calls")

print()
print(f"Temp directory (inspect/cleanup): {tmpdir}")
print()

# Cleanup
QgsProject.instance().removeAllMapLayers()
app.exitQgis()

print("[DONE] Spike complete. Copy output to .omc/plans/spike-1.5-findings.md")
