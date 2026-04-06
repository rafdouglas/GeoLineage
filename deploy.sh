#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="${GEOLINEAGE_PLUGIN_DIR:-${HOME}/.var/app/org.qgis.qgis/data/QGIS/QGIS3/profiles/default/python/plugins/GeoLineage/}"

echo "Deploying GeoLineage plugin"
echo "  Source : ${REPO_DIR}"
echo "  Target : ${PLUGIN_DIR}"
echo ""

mkdir -p "${PLUGIN_DIR}"

RSYNC_OPTS=(
    --archive
    --itemize-changes
    --exclude="__pycache__/"
    --exclude="*.pyc"
)

# Sync top-level files individually
for f in __init__.py plugin.py metadata.txt LICENSE README.md; do
    if [[ -f "${REPO_DIR}/${f}" ]]; then
        rsync "${RSYNC_OPTS[@]}" "${REPO_DIR}/${f}" "${PLUGIN_DIR}/"
    fi
done

# Sync directories (--delete removes files inside the dir that no longer exist in source)
for d in resources lineage_core lineage_retrieval lineage_viewer lineage_manager; do
    if [[ -d "${REPO_DIR}/${d}" ]]; then
        rsync "${RSYNC_OPTS[@]}" --delete "${REPO_DIR}/${d}/" "${PLUGIN_DIR}/${d}/"
    fi
done

echo ""
echo "Deploy complete."
