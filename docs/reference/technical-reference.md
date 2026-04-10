# GeoLineage Technical Reference

This document covers the internal architecture, data model, APIs, and development practices for GeoLineage. It is intended for contributors and developers who need to understand or extend the plugin.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Repository Layout](#repository-layout)
3. [Architecture and Data Flow](#architecture-and-data-flow)
4. [Module Reference](#module-reference)
   - [lineage_core](#lineage_core)
   - [lineage_retrieval](#lineage_retrieval)
   - [lineage_viewer](#lineage_viewer)
   - [lineage_manager](#lineage_manager)
   - [plugin.py](#pluginpy)
5. [Data Model](#data-model)
6. [Hook System](#hook-system)
7. [Memory Buffer](#memory-buffer)
8. [Graph Layout Algorithm](#graph-layout-algorithm)
9. [Checksum Implementation](#checksum-implementation)
10. [Settings and Configuration](#settings-and-configuration)
11. [Testing](#testing)
12. [CI/CD Pipeline](#cicd-pipeline)
13. [Development Setup](#development-setup)

---

## Project Overview

| Property | Value |
|----------|-------|
| Version | 0.6.1 |
| Language | Python 3.10+ |
| GUI Framework | PyQt5 (via QGIS) |
| Storage Backend | SQLite (GeoPackage extension tables) |
| Minimum QGIS | 3.34 LTS |
| License | GPL-2.0-or-later |

GeoLineage tracks data provenance for GeoPackage files inside QGIS. It intercepts three categories of operation — processing algorithm execution, manual feature edits, and layer exports — and persists each as a row in a `_lineage` table inside the target GeoPackage. A separate retrieval layer reconstructs ancestor graphs via BFS traversal, and a Qt-based viewer renders those graphs using the Sugiyama layered layout algorithm.

---

## Repository Layout

```
GeoLineage/
├── __init__.py                 # classFactory entry point
├── plugin.py                   # QGIS plugin lifecycle (initGui / unload)
├── metadata.txt                # QGIS plugin metadata
├── pyproject.toml              # Pytest and coverage configuration
│
├── lineage_core/               # Recording and persistence
│   ├── __init__.py
│   ├── schema.py               # DDL, table creation, row reading
│   ├── hooks.py                # Monkey-patches and signal wiring
│   ├── recorder.py             # Write _lineage entries
│   ├── memory_buffer.py        # In-memory ancestry graph
│   ├── checksum.py             # Data-only SHA-256 hash
│   ├── settings.py             # Constants and QSettings keys
│   └── repair_lineage.py       # Reconstruct historical records
│
├── lineage_retrieval/          # Graph query layer
│   ├── __init__.py
│   ├── graph_builder.py        # BFS ancestor graph construction
│   ├── path_resolver.py        # Resolve QGIS layer sources to paths
│   └── cache.py                # Mtime-based lineage cache
│
├── lineage_viewer/             # Qt visualization layer
│   ├── __init__.py
│   ├── dock_widget.py          # Main dock widget
│   ├── graph_layout.py         # Sugiyama 7-phase layout
│   ├── graph_scene.py          # QGraphicsScene management
│   ├── graph_node_item.py      # Node QGraphicsItem with drag
│   ├── graph_edge_item.py      # Edge routing and rendering
│   ├── detail_panel.py         # Right-side metadata panel
│   ├── toolbar.py              # Export / search / reset toolbar
│   └── export.py               # DOT, SVG, PNG export
│
├── lineage_manager/            # Administrative dialogs
│   ├── __init__.py
│   ├── inspect_dialog.py       # Table view of _lineage rows
│   ├── data_ops.py             # CRUD on _lineage rows
│   ├── settings_dialog.py      # Username configuration dialog
│   ├── cleanup_dialog.py       # Remove orphaned entries
│   └── relink_dialog.py        # Remap broken parent paths
│
└── tests/
    ├── conftest.py             # Shared fixtures
    └── test_*.py               # 18 test modules
```

---

## Architecture and Data Flow

### Module Dependency Graph

```
plugin.py (QGIS entry point)
├── lineage_viewer/dock_widget.py
│   ├── lineage_retrieval/graph_builder.py
│   │   ├── lineage_core/schema.py
│   │   └── lineage_retrieval/cache.py
│   ├── lineage_viewer/graph_layout.py
│   └── lineage_viewer/graph_scene.py
│       ├── lineage_viewer/graph_node_item.py
│       └── lineage_viewer/graph_edge_item.py
├── lineage_manager/inspect_dialog.py
│   └── lineage_manager/data_ops.py
├── lineage_manager/settings_dialog.py
├── lineage_manager/cleanup_dialog.py
└── lineage_manager/relink_dialog.py

lineage_core/hooks.py (background, always-on when recording enabled)
├── lineage_core/recorder.py
│   ├── lineage_core/memory_buffer.py
│   ├── lineage_core/checksum.py
│   └── lineage_core/schema.py
└── lineage_core/repair_lineage.py
```

### Recording Data Flow

```
User action (processing / edit / export)
    │
    ▼
hooks.py  ←── monkey-patches processing.run() and QgsVectorFileWriter
              connects to afterCommitChanges signal
    │
    ▼
recorder.py
    ├── memory_buffer.py  (track in-memory intermediate layers)
    ├── checksum.py       (compute data-only SHA-256)
    └── schema.py         (ensure _lineage table; insert row)
```

### Retrieval Data Flow

```
User opens Lineage Viewer
    │
    ▼
dock_widget.py → graph_builder.py
                     ├── cache.py     (check mtime; return cached result if fresh)
                     ├── schema.py    (read _lineage rows)
                     └── path_resolver.py (resolve relative paths)
    │
    ▼ LineageGraph
graph_layout.py (Sugiyama 7-phase)
    │
    ▼ LayoutResult
graph_scene.py → graph_node_item.py + graph_edge_item.py
    │
    ▼ (rendered Qt scene in dock widget)
```

---

## Module Reference

### lineage_core

#### `schema.py`

Handles all DDL and data access for the `_lineage` and `_lineage_meta` tables.

```python
KNOWN_COLUMNS = [
    "id", "created_at", "data_filename", "operation_type",
    "tool", "operation_summary", "operation_params",
    "parent_files", "username", "checksum",
]

def ensure_lineage_table(gpkg_path: str) -> bool
```

Creates `_lineage` and `_lineage_meta` tables if they do not already exist. Returns `True` if tables were created, `False` if they were already present. Safe to call repeatedly (idempotent).

```python
def read_lineage_rows(gpkg_path: str) -> list[dict]
```

Returns all rows from `_lineage` as a list of dicts. Only columns present in `KNOWN_COLUMNS` are included, providing forward-compatibility when future schema versions add columns that older code should ignore.

---

#### `hooks.py`

Installs and removes the interception layer that ties QGIS operations to the recorder.

```python
def install_hooks() -> None
def uninstall_hooks() -> None
```

`install_hooks()` applies three monkey-patches and one signal connection:

| Target | Mechanism | What is captured |
|--------|-----------|-----------------|
| `processing.run()` | Closure-based wrapper | Algorithm name, parameters, input/output layers |
| `AlgorithmDialog.finish()` | Method replacement | Dialog-sourced algorithm parameters |
| `QgsVectorFileWriter.writeAsVectorFormatV3()` | Method replacement | Source layer, output path |
| `QgsProject.layersAdded` | Qt signal connection | New layer registrations (for memory buffer) |

All hooks are exception-isolated: a failure inside a hook is caught and logged, and the original QGIS operation proceeds unaffected.

A re-entrancy guard (`_recording_in_progress` flag) prevents duplicate entries from nested `processing.run()` calls.

---

#### `recorder.py`

Writes individual lineage entries to the `_lineage` table.

```python
def record_processing(
    gpkg_path: str,
    tool: str,
    params: dict,
    parent_files: list[str],
    username: str,
    operation_summary: str = "",
) -> bool
```

```python
def record_edit(
    gpkg_path: str,
    layer_name: str,
    operation_summary: str,
    username: str,
) -> bool
```

```python
def record_export(
    gpkg_path: str,
    parent_path: str,
    output_path: str,
    username: str,
) -> bool
```

All three functions:
1. Call `ensure_lineage_table()` to create tables if needed.
2. Compute a SHA-256 checksum of the target GeoPackage data.
3. Insert a row into `_lineage`.
4. Return `True` on success, `False` on any error (errors are logged, not raised).

---

#### `memory_buffer.py`

Tracks lineage through temporary in-memory layers that exist between processing steps but are never persisted to disk individually.

```python
class MemoryBuffer:
    def add(self, layer_id: str, layer_name: str) -> None
    def link(self, child_id: str, parent_id: str) -> None
    def get_chain(self, layer_id: str) -> list[str]
    def flush(self, gpkg_path: str, layer_name: str) -> None
    def clear(self) -> None
```

**Lifecycle:**

1. `add()` — called when a new memory layer appears (via `layersAdded` signal).
2. `link()` — called by the processing hook to establish parent→child relationships.
3. `flush()` — called when a memory layer is exported to a GeoPackage; writes the complete chain to `_lineage` in the output file.
4. `clear()` — called on `unload()` to free resources.

Internally, the buffer maintains a directed graph of `(parent_id → child_id)` pairs keyed by QGIS layer ID. `get_chain()` performs a DFS from the given layer ID to collect all ancestor layer IDs.

---

#### `checksum.py`

```python
def compute_checksum(gpkg_path: str) -> str
```

Computes a SHA-256 hash of the GeoPackage's data contents, excluding:
- `_lineage` and `_lineage_meta` tables
- `gpkg_geometry_columns`, `gpkg_contents`, `gpkg_spatial_ref_sys`, `gpkg_extensions` (metadata tables)
- SQLite internal tables (`sqlite_master`, `sqlite_sequence`, etc.)
- Spatial index tables (those beginning with `rtree_`)

For each included table, all rows are read in primary-key order. Each value is serialized with a type prefix tag (`INT:`, `REAL:`, `TEXT:`, `BLOB:`, `NULL:`) to distinguish values of different types that have the same string representation.

Returns a 64-character lowercase hex string.

---

#### `settings.py`

Defines constants shared across the codebase:

```python
SCHEMA_VERSION = "1.0"
LINEAGE_TABLE = "_lineage"
META_TABLE = "_lineage_meta"
SETTING_ENABLED = "lineage_recording_enabled"
SETTING_USERNAME = "lineage_username"
```

These are the only two QSettings keys GeoLineage writes to the QGIS project file.

---

#### `repair_lineage.py`

```python
def repair_lineage(gpkg_path: str, project_dir: str) -> int
```

Reconstructs lineage records for a GeoPackage that has a `_lineage` table but missing or incomplete entries. Scans the processing history available in the QGIS project and attempts to backfill missing links. Returns the number of rows inserted.

Used mainly for migration and forensic scenarios; not part of normal recording flow.

---

### lineage_retrieval

#### `graph_builder.py`

Constructs the ancestor graph for a given GeoPackage by performing a BFS traversal through all linked `_lineage` records.

```python
@dataclass
class LineageNode:
    id: str
    filename: str
    full_path: str
    operation_type: str        # "processing" | "edit" | "export" | "raw_input"
    tool: str
    timestamp: datetime | None
    checksum: str
    status: str                # "present" | "missing" | "raw_input" | "busy"
    depth: int

@dataclass
class LineageEdge:
    source_id: str
    target_id: str
    label: str

@dataclass
class LineageGraph:
    nodes: dict[str, LineageNode]
    edges: list[LineageEdge]
    root_id: str

def build_graph(
    gpkg_path: str,
    project_dir: str,
    max_depth: int = 10,
) -> LineageGraph
```

**BFS traversal:**

1. Start at `gpkg_path`; read its `_lineage` rows.
2. For each row, parse `parent_files` (JSON list); resolve each parent path using `path_resolver`.
3. If the parent is a GeoPackage that exists on disk, open it and read its `_lineage` rows.
4. Continue until no new parents are found or `max_depth` is reached.
5. Set `status` on each node:
   - `"present"` — file exists at resolved path
   - `"missing"` — path could not be resolved or file does not exist
   - `"raw_input"` — no `_lineage` table in the file (external source)
   - `"busy"` — file exists but is locked

Results are cached by `cache.py`; subsequent calls with the same `gpkg_path` return the cached graph until the GeoPackage's mtime changes.

---

#### `path_resolver.py`

```python
def resolve_source(source: str, project_dir: str) -> str | None
```

Resolves a QGIS layer source string (which may be an absolute path, a relative path, a URI with `|layername=` suffix, or a memory layer reference) to an absolute filesystem path. Returns `None` if the source cannot be resolved to a file.

```python
def make_relative(path: str, base_dir: str) -> str
```

Converts an absolute path to a path relative to `base_dir`. Used when storing `parent_files` references to keep them portable across machines.

---

#### `cache.py`

```python
class LineageCache:
    def get(self, gpkg_path: str) -> LineageGraph | None
    def put(self, gpkg_path: str, graph: LineageGraph) -> None
    def invalidate(self, gpkg_path: str) -> None
```

Mtime-based in-memory cache. `get()` checks the GeoPackage's modification time against the stored mtime; if the file has been modified since the last cache fill, the cached entry is discarded and `None` is returned. `put()` stores the graph along with the current mtime.

---

### lineage_viewer

#### `graph_layout.py`

Implements the Sugiyama layered graph layout algorithm.

```python
@dataclass
class LayoutConfig:
    node_width: float    # Dynamic: max(120, 10 * len(filename))
    node_height: float   # 40
    h_spacing: float     # 100
    v_spacing: float     # 60

@dataclass
class NodePosition:
    x: float
    y: float
    rank: int            # Layer index (0 = topmost ancestor)

@dataclass
class EdgePath:
    waypoints: list[tuple[float, float]]

@dataclass
class LayoutResult:
    positions: dict[str, NodePosition]
    edge_paths: dict[tuple[str, str], EdgePath]
    width: float
    height: float

class Sugiyama:
    def layout(
        self,
        graph: LineageGraph,
        config: LayoutConfig,
    ) -> LayoutResult
```

**The seven phases:**

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Cycle breaking | Reverses a minimal set of edges to guarantee a DAG |
| 2 | Rank assignment | Assigns each node a layer (rank) via longest-path layering |
| 3 | Dummy node insertion | Inserts virtual nodes on edges that span more than one layer |
| 4 | Crossing minimisation | Reorders nodes within each layer to reduce edge crossings (iterative barycentric heuristic) |
| 5 | X-coordinate assignment | Assigns horizontal positions using the Brandes–Köpf algorithm |
| 6 | Dummy node removal | Removes virtual nodes; records waypoints for spline routing |
| 7 | Edge routing | Generates cubic Bézier control points for each edge |

---

#### `dock_widget.py`

```python
class LineageDockWidget(QDockWidget):
    def show_lineage(self, gpkg_path: str, project_dir: str) -> None
    def _on_node_selected(self, node_id: str) -> None
    def _on_export_graph(self, fmt: str) -> None
    def _on_reset_layout(self) -> None
```

The dock is split 70/30 between the graph canvas (`QGraphicsView` containing `graph_scene`) and the detail panel. Node selection is communicated from `graph_node_item` to `dock_widget` via Qt signals; the widget then updates `detail_panel` with the selected node's metadata.

---

#### `graph_node_item.py`

```python
class GraphNodeItem(QGraphicsRectItem):
    node_selected = pyqtSignal(str)   # emits node_id on click

    def mousePressEvent(self, event) -> None
    def mouseMoveEvent(self, event) -> None   # drag with optional Shift-axis lock
    def mouseReleaseEvent(self, event) -> None
```

Drag behaviour: holding **Shift** while dragging constrains movement to the axis of greatest initial displacement (horizontal or vertical). Connected edges are updated in real time during drag via a callback registered with the parent scene.

---

#### `graph_edge_item.py`

```python
class GraphEdgeItem(QGraphicsPathItem):
    def update_path(
        self,
        source_pos: QPointF,
        target_pos: QPointF,
        waypoints: list[QPointF] | None = None,
    ) -> None
```

Draws an arrow from source to target using waypoints from the Sugiyama layout as cubic Bézier control points. The arrowhead is computed from the final tangent of the path.

---

#### `export.py`

```python
def export_dot(graph: LineageGraph, path: str) -> None
def export_svg(scene: QGraphicsScene, path: str) -> None
def export_png(scene: QGraphicsScene, path: str, dpi: int = 150) -> None
```

DOT export serialises `LineageGraph` directly. SVG and PNG export use `QPainter` with the appropriate backend device to render the live `QGraphicsScene`.

---

### lineage_manager

#### `data_ops.py`

All functions accept a `gpkg_path: str` and perform direct SQLite operations.

```python
def read_all_entries(gpkg_path: str) -> list[dict]
def update_entry_field(
    gpkg_path: str,
    entry_id: int,
    field: str,
    value: str,
) -> bool
def delete_entry(gpkg_path: str, entry_id: int) -> bool
def batch_delete(gpkg_path: str, entry_ids: list[int]) -> None
def drop_lineage_tables(gpkg_path: str) -> bool
```

`update_entry_field()` only accepts `field` values in an allowlist (`operation_summary`, `edit_summary`) to prevent modification of core provenance fields.

---

### `plugin.py`

```python
class GeoLineagePlugin:
    def __init__(self, iface: QgisInterface) -> None
    def initGui(self) -> None
    def unload(self) -> None
```

**`initGui()`** — called by QGIS when the plugin is activated:
- Creates the **GeoLineage** menu and toolbar button.
- Instantiates `LineageDockWidget` (hidden by default).
- Instantiates all manager dialogs.
- Calls `install_hooks()`.

**`unload()`** — called by QGIS on deactivation or shutdown:
- Calls `uninstall_hooks()`.
- Clears `MemoryBuffer`.
- Removes menu items and toolbar button.
- Deletes dock widget.

---

## Data Model

### GeoPackage Extension Tables

#### `_lineage`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | ISO 8601 UTC |
| `data_filename` | TEXT | NOT NULL | Relative path to the target file |
| `operation_type` | TEXT | NOT NULL | `"processing"` \| `"edit"` \| `"export"` |
| `tool` | TEXT | | Algorithm name (e.g. `"qgis:buffer"`) |
| `operation_summary` | TEXT | | Human-readable description |
| `operation_params` | TEXT | | JSON object of algorithm parameters |
| `parent_files` | TEXT | | JSON array of `{file, layer}` objects |
| `username` | TEXT | | Recorded from `SETTING_USERNAME` |
| `checksum` | TEXT | | 64-char hex SHA-256 of data-only content |

#### `_lineage_meta`

| Column | Type | Notes |
|--------|------|-------|
| `schema_version` | TEXT | Currently `"1.0"` |

### `parent_files` JSON Schema

```json
[
  { "file": "relative/path/to/parent.gpkg", "layer": "layer_name" },
  { "file": "relative/path/to/other.gpkg",  "layer": "other_layer" }
]
```

Paths are stored relative to the GeoPackage's own directory to remain portable. `path_resolver.py` converts them to absolute paths at query time using the QGIS project directory as the base.

### Example Row

```sql
INSERT INTO _lineage (
    data_filename, operation_type, tool, operation_summary,
    operation_params, parent_files, username, checksum
) VALUES (
    'results/buffered_roads.gpkg',
    'processing',
    'qgis:buffer',
    'Buffer roads by 100 m',
    '{"INPUT": "../source/roads.gpkg|layername=roads", "DISTANCE": 100, "SEGMENTS": 5}',
    '[{"file": "../source/roads.gpkg", "layer": "roads"}]',
    'analyst_01',
    'a3f5c2d1e4b7a6f9c0d3e2b1a4f7c6d5e8b3a2f1c4d7e6b5a8f3c2d1e4b7a6f9'
);
```

---

## Hook System

### Installation

`install_hooks()` in `hooks.py` replaces three callables and connects one signal:

```python
# 1. Wrap processing.run
import qgis.processing as _processing
_original_run = _processing.run
_processing.run = _make_run_wrapper(_original_run)

# 2. Wrap AlgorithmDialog.finish
from qgis.gui import QgsProcessingAlgorithmDialogBase
_original_finish = QgsProcessingAlgorithmDialogBase.finish
QgsProcessingAlgorithmDialogBase.finish = _make_finish_wrapper(_original_finish)

# 3. Wrap QgsVectorFileWriter
from qgis.core import QgsVectorFileWriter
_original_write = QgsVectorFileWriter.writeAsVectorFormatV3.__func__
QgsVectorFileWriter.writeAsVectorFormatV3 = _make_writer_wrapper(_original_write)

# 4. Connect signal
QgsProject.instance().layersAdded.connect(_on_layers_added)
```

### Re-entrancy Guard

Processing algorithms can call `processing.run()` internally (e.g., model algorithms). The guard prevents duplicate recording:

```python
_recording_in_progress = False

def _make_run_wrapper(original):
    def wrapper(algorithm, params, **kwargs):
        global _recording_in_progress
        if _recording_in_progress or not _is_recording_enabled():
            return original(algorithm, params, **kwargs)
        _recording_in_progress = True
        try:
            result = original(algorithm, params, **kwargs)
            _record_from_run(algorithm, params, result)
            return result
        except Exception:
            return original(algorithm, params, **kwargs)
        finally:
            _recording_in_progress = False
    return wrapper
```

### Exception Isolation

Every hook wraps its recording logic in a `try/except Exception` block. Hook failures are logged via `QgsMessageLog` at the `Qgis.Warning` level and never propagate to QGIS operations.

---

## Memory Buffer

The `MemoryBuffer` is a singleton instance held in `hooks.py`. Its graph is a `dict[str, list[str]]` mapping each `layer_id` to a list of its parent `layer_id`s.

### Flush Trigger

`flush()` is invoked by the export hook when it detects that the output destination is a GeoPackage:

```
export hook fires
    │
    ├── output is a GeoPackage file
    │       └── memory_buffer.flush(output_gpkg, output_layer)
    │               └── get_chain(source_layer_id)
    │                       └── DFS → [layer_id_A, layer_id_B, layer_id_C]
    │               └── for each chain entry → recorder.record_processing(...)
    │
    └── output is not a GeoPackage (e.g., Shapefile)
            └── register output as new memory layer in buffer
```

After flushing, the chain entries for the flushed layer are removed from the buffer to prevent double-recording.

---

## Graph Layout Algorithm

The Sugiyama algorithm in `graph_layout.py` produces a hierarchical layout that minimises edge crossings and maintains clear top-to-bottom data flow direction.

### Phase Details

**Phase 1 — Cycle breaking**

Identifies back-edges using DFS. Reverses the minimum set of edges required to make the graph a DAG. Reversed edges are tracked so their direction is restored in the final layout.

**Phase 2 — Rank assignment**

Uses longest-path layering: the root node is assigned rank 0; each node is assigned `max(parent_rank) + 1`. All nodes with no successors share the highest rank. This maximises the visual separation between input and output nodes.

**Phase 3 — Dummy node insertion**

For every edge `(u, v)` where `rank(v) - rank(u) > 1`, a chain of dummy nodes `d_1, d_2, ..., d_k` is inserted at the intermediate ranks. This ensures that all edges connect adjacent layers, which is required for the crossing-minimisation step.

**Phase 4 — Crossing minimisation**

Iterates over adjacent layer pairs (top-down then bottom-up) in a fixed number of sweeps (typically 4). Within each pass, nodes in the active layer are reordered by the barycentric median of their neighbours in the already-fixed layer. This is a classical O(n log n) heuristic that significantly reduces crossings with low computational cost.

**Phase 5 — X-coordinate assignment**

Implements a simplified version of the Brandes–Köpf algorithm:
1. Compute four layouts (two alignment directions × two traversal directions).
2. Average the x-coordinates of the four layouts.
3. Apply minimum separation constraints (based on `config.node_width + config.h_spacing`).

**Phase 6 — Dummy node removal**

Removes all dummy nodes added in Phase 3. For each edge `(u, v)` whose dummy chain is `u → d_1 → d_2 → ... → v`, the waypoints `[pos(d_1), pos(d_2), ...]` are recorded for use in Phase 7.

**Phase 7 — Edge routing**

Converts waypoint lists into cubic Bézier paths. For straight edges (no dummies), a single Bézier from the node midpoints is generated with control points offset to avoid overlapping node rectangles.

---

## Checksum Implementation

The checksum captures the data state of a GeoPackage at a point in time, so that future integrity checks can detect unexpected modifications.

### Excluded Tables

The following are excluded before hashing to ensure that adding lineage entries does not change the checksum of the data:

- `_lineage`, `_lineage_meta`
- `gpkg_contents`, `gpkg_geometry_columns`, `gpkg_spatial_ref_sys`, `gpkg_extensions`
- `gpkg_tile_matrix`, `gpkg_tile_matrix_set`
- `sqlite_master`, `sqlite_sequence`
- Any table whose name starts with `rtree_` (spatial indexes)

### Serialisation

For each included table, rows are read `ORDER BY rowid`. Each value is serialised as:

```
<type_tag>:<value>\n
```

Type tags: `INT`, `REAL`, `TEXT`, `BLOB`, `NULL`.

`BLOB` values are hex-encoded. `REAL` values are formatted with 17 significant digits to avoid floating-point ambiguity.

The entire serialised stream is fed to `hashlib.sha256`. This produces a deterministic hash regardless of SQLite internal page layout.

---

## Settings and Configuration

### QSettings Keys

Stored in the QGIS project file (`.qgs` / `.qgz`):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `lineage_recording_enabled` | bool | `False` | Whether recording is active |
| `lineage_username` | str | `""` | Username for lineage entries |

### Build-Time Constants (`settings.py`)

| Constant | Value | Description |
|----------|-------|-------------|
| `SCHEMA_VERSION` | `"1.0"` | Written to `_lineage_meta` on table creation |
| `LINEAGE_TABLE` | `"_lineage"` | Primary lineage table name |
| `META_TABLE` | `"_lineage_meta"` | Metadata table name |

### Graph Layout Defaults

| Parameter | Value | Location |
|-----------|-------|----------|
| Node height | 40 px | `graph_layout.py` |
| Horizontal spacing | 100 px | `graph_layout.py` |
| Vertical spacing | 60 px | `graph_layout.py` |
| Node width (minimum) | 120 px | `graph_layout.py` |
| Node width (dynamic) | `max(120, 10 * len(filename))` | `graph_layout.py` |
| Max BFS depth | 10 | `graph_builder.py` |

---

## Testing

### Framework

| Tool | Purpose |
|------|---------|
| `pytest` | Test runner |
| `pytest-cov` | Coverage measurement |
| `ruff` | Lint and format checking |
| `bandit` | Security scanning |

### Test Tiers

**T1 — Pure Python** (no QGIS runtime required)

Run with:
```bash
pytest tests/ -v --cov=lineage_core --cov=lineage_retrieval --cov-report=term-missing
```

Covers: `schema`, `checksum`, `recorder`, `memory_buffer`, `path_resolver`, `cache`, `graph_builder`, `graph_layout`, `data_ops`, `repair_lineage`.

**T2 — QGIS headless** (requires QGIS on `PYTHONPATH`)

Run with:
```bash
python -m pytest tests/ -v -m qgis
```

Covers: `hooks`, `dock_widget`, UI components.

### Coverage Configuration (`pyproject.toml`)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.coverage.run]
omit = [
    "lineage_viewer/*",   # Qt GUI — difficult to test headlessly
    "plugin.py",          # QGIS plugin lifecycle
    "spike/*",            # Experimental / scratch code
    "__init__.py",
]
```

Minimum enforced coverage: **50%** (`--cov-fail-under=50`).

### Fixtures (`conftest.py`)

```python
@pytest.fixture
def tmp_gpkg(tmp_path) -> Path
```

Creates a minimal but valid GeoPackage containing:
- `gpkg_spatial_ref_sys` with WGS84 entry
- `gpkg_contents`
- `gpkg_geometry_columns`
- One user feature table (`roads`) with two sample point features

```python
@pytest.fixture
def tmp_gpkg_factory(tmp_path)
```

Returns a factory function `make_gpkg(tables, srs=4326)` that creates GeoPackages with custom table schemas, allowing tests to construct complex multi-file lineage scenarios.

### Test File Index

| File | What it tests |
|------|--------------|
| `test_schema.py` | Table creation, idempotency, forward-compat column filtering |
| `test_recorder.py` | Recording processing, edit, and export entries |
| `test_memory_buffer.py` | Chain building, flush, clear |
| `test_checksum.py` | Determinism, exclusion of lineage tables, type serialisation |
| `test_path_resolver.py` | Absolute/relative path resolution, `\|layername=` stripping |
| `test_cache.py` | Cache hit, miss, mtime invalidation |
| `test_graph_builder.py` | BFS traversal, node status assignment, max_depth |
| `test_graph_layout.py` | All 7 Sugiyama phases, edge routing, node positioning |
| `test_hooks.py` | Hook install/uninstall, re-entrancy guard, exception isolation |
| `test_repair_lineage.py` | Missing entry backfill |
| `test_data_ops.py` | CRUD operations, field allowlist enforcement |
| `test_ui_enhancements.py` | Node drag, axis locking, edge update during drag |
| `test_export.py` | DOT/SVG/PNG output format validity |
| `test_detail_panel.py` | Panel population from `LineageNode` |
| `test_settings.py` | QSettings read/write round-trip |
| `test_cleanup_dialog.py` | Orphaned entry detection and deletion |

---

## CI/CD Pipeline

**File:** `.github/workflows/ci.yml`

### Trigger

- Push to `main`
- Pull request targeting `main`
- Push of a version tag (`v*.*.*`) — triggers release job

### Jobs

**`test` (matrix: Python 3.10, 3.12)**

```
ubuntu-latest
├── Checkout
├── Set up Python ${{ matrix.python-version }}
├── pip install pytest pytest-cov ruff bandit
├── ruff check .                          (lint)
├── ruff format --check .                 (format)
├── bandit -r lineage_core lineage_retrieval  (security)
└── pytest tests/ -v
      --cov=lineage_core
      --cov=lineage_retrieval
      --cov-report=term-missing
      --cov-fail-under=50
```

**`release` (on version tag)**

```
ubuntu-latest
├── Checkout
├── Create GitHub Release (tag as version)
└── Upload GeoLineage.zip artifact
```

### Quality Gates

| Gate | Tool | Failure Action |
|------|------|----------------|
| Lint | `ruff check` | Block merge |
| Format | `ruff format --check` | Block merge |
| Security | `bandit` | Block merge |
| Coverage | `pytest --cov-fail-under=50` | Block merge |
| Tests | `pytest` | Block merge |

### Release Process

```bash
# Tag and push to trigger the release job
git tag v0.7.0
git push origin v0.7.0
```

GitHub Actions creates a release page and attaches the plugin ZIP automatically.

---

## Development Setup

```bash
# Clone
git clone https://github.com/rafdouglas/GeoLineage.git
cd GeoLineage

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install development dependencies
pip install pytest pytest-cov ruff bandit

# Run T1 tests
pytest tests/ -v --cov=lineage_core --cov=lineage_retrieval --cov-report=term-missing

# Lint
ruff check .

# Format (in-place)
ruff format .

# Security scan
bandit -r lineage_core lineage_retrieval
```

### Installing into QGIS for manual testing

```bash
# Symlink the repo directly into the QGIS plugin directory (Linux/macOS)
PLUGIN_DIR=~/.local/share/QGIS/QGIS3/profiles/default/python/plugins
ln -s "$(pwd)" "$PLUGIN_DIR/GeoLineage"

# Then in QGIS: Plugins → Manage → enable GeoLineage
# After code changes, use Plugins → Reload Plugin (or restart QGIS)
```

### Adding a New Operation Type

1. Add a new `record_*` function in `lineage_core/recorder.py`.
2. Add the corresponding hook in `lineage_core/hooks.py` (wrapper function + installation/uninstallation in `install_hooks` / `uninstall_hooks`).
3. Update `operation_type` handling in `lineage_retrieval/graph_builder.py` (node status and display logic).
4. Add tests in `tests/test_recorder.py` and `tests/test_hooks.py`.

### Adding a New Schema Column

1. Add the column to the `CREATE TABLE` statement in `lineage_core/schema.py`.
2. Increment `SCHEMA_VERSION` in `lineage_core/settings.py`.
3. Add the column name to `KNOWN_COLUMNS` in `schema.py` so it is included in `read_lineage_rows()`.
4. Add a migration path in `repair_lineage.py` if back-population is required.
5. Update `conftest.py` fixtures if the column is `NOT NULL`.
