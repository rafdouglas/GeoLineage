#!/bin/bash
# Run the GeoLineage Phase 1.5 spike inside Flatpak QGIS
# Usage: ./spike/run_spike.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SPIKE_SCRIPT="$SCRIPT_DIR/validate_qgis_assumptions.py"

echo "Running spike inside Flatpak QGIS..."
echo "Script: $SPIKE_SCRIPT"
echo ""

flatpak run --command=bash org.qgis.qgis -c \
    "PYTHONPATH=/app/share/qgis/python:/app/lib/python3.13/site-packages \
     python3 '$SPIKE_SCRIPT'" 2>&1 | tee "$SCRIPT_DIR/spike_output.txt"

echo ""
echo "Output saved to: $SCRIPT_DIR/spike_output.txt"
