# GeoLineage

A QGIS plugin that tracks data lineage in GeoPackage files. Every processing step, manual edit, and export is recorded directly inside the `.gpkg` file, creating a permanent chain of custody for your geospatial data.

## Features

- **Processing recording** — Automatically captures every `processing.run()` operation with full parameter details, input/output references, and checksums
- **Edit tracking** — Records manual edits (features added, modified, deleted) when you save changes to a GeoPackage layer
- **Export detection** — Logs exports via "Save Features As..." and `native:savefeatures`, linking the new file back to its source
- **Memory buffer with chain-of-custody** — Tracks lineage through temporary/memory layers across multi-step processing chains, flushing the complete history when the final result is saved to disk
- **Lineage graph viewer** — Visualizes the full DAG of file ancestry with color-coded node status (planned)
- **Lineage manager** — Inspect, edit, clean up, and relink lineage entries (planned)

## Requirements

- **QGIS 3.34 LTS** or later
- Python 3.10+

## Installation

1. Download the latest release ZIP from the [Releases](https://github.com/rafdouglas/GeoLineage/releases) page
2. In QGIS: **Plugins > Manage and Install Plugins > Install from ZIP**
3. Select the downloaded ZIP file and click **Install Plugin**
4. Enable GeoLineage in the plugin list

## Usage

1. Toggle the GeoLineage button in the toolbar to start recording
2. Run processing tools, edit layers, or export files as usual
3. Lineage entries are written automatically to `_lineage` tables inside each GeoPackage
4. Toggle off to pause recording

Lineage data is stored in non-standard tables (`_lineage`, `_lineage_meta`) that do not interfere with normal GeoPackage usage. Any GIS application can still read the file normally.

## How It Works

GeoLineage intercepts QGIS operations through three mechanisms:

1. **`processing.run()` wrapper** — A closure-based monkey-patch captures algorithm name, parameters, and input/output layers. Exception-isolated so hook failures never break QGIS operations.
2. **`QgsVectorFileWriter` wrapper** — Catches direct "Save Features As..." exports that bypass the processing framework.
3. **Edit signals** — Connects to `afterCommitChanges` on GeoPackage-backed layers to record manual edits.

All recording is non-destructive and additive (new rows only, never modifies existing data). A re-entrancy guard prevents duplicate entries from nested processing calls.

## Development

### Setup

```bash
git clone https://github.com/rafdouglas/GeoLineage.git
cd GeoLineage
python -m venv .venv
source .venv/bin/activate
pip install pytest pytest-cov
```

### Testing

The test suite is organized into tiers:

- **T1 (Pure Python)** — Tests core logic without QGIS. Run with plain pytest:

  ```bash
  pytest tests/ -v --cov=lineage_core --cov=lineage_retrieval --cov-report=term-missing
  ```

- **T2 (QGIS headless)** — Tests requiring QGIS runtime. Run with QGIS on `PYTHONPATH`:

  ```bash
  python -m pytest tests/ -v -m qgis
  ```

### Project Structure

```
GeoLineage/
├── __init__.py              # classFactory entry point
├── plugin.py                # QGIS plugin class (initGui, unload)
├── metadata.txt             # Plugin metadata
├── lineage_core/
│   ├── schema.py            # DDL, table creation, row reading
│   ├── checksum.py          # Data-only SHA-256 checksums
│   ├── recorder.py          # Write lineage entries
│   ├── memory_buffer.py     # Graph-based in-memory buffer
│   ├── hooks.py             # Monkey-patches and signal wiring
│   └── settings.py          # Constants and setting keys
├── lineage_retrieval/
│   ├── path_resolver.py     # Cross-platform path resolution
│   └── cache.py             # Lineage cache with mtime invalidation
└── tests/
    ├── conftest.py           # Shared fixtures (temp GeoPackages)
    └── test_*.py             # Test modules
```

## License

GPL-2.0-or-later (required for QGIS plugins)
