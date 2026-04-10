# GeoLineage User Guide

GeoLineage is a QGIS plugin that automatically records the history of your GeoPackage files — every processing step, manual edit, and export is captured and stored directly inside the `.gpkg` file. At any time you can open the lineage viewer to see a visual graph showing exactly where your data came from and what was done to it.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Getting Started](#getting-started)
4. [Recording Lineage](#recording-lineage)
   - [Enabling Recording](#enabling-recording)
   - [Processing Tools](#processing-tools)
   - [Manual Edits](#manual-edits)
   - [Exporting Layers](#exporting-layers)
   - [Multi-Step Workflows](#multi-step-workflows)
5. [Viewing Lineage](#viewing-lineage)
   - [Opening the Graph Viewer](#opening-the-graph-viewer)
   - [Navigating the Graph](#navigating-the-graph)
   - [Node Colors and Status](#node-colors-and-status)
   - [Detail Panel](#detail-panel)
   - [Exporting the Graph](#exporting-the-graph)
6. [Managing Lineage Records](#managing-lineage-records)
   - [Inspect Dialog](#inspect-dialog)
   - [Settings Dialog](#settings-dialog)
   - [Cleanup Dialog](#cleanup-dialog)
   - [Relink Dialog](#relink-dialog)
7. [How Lineage is Stored](#how-lineage-is-stored)
8. [Frequently Asked Questions](#frequently-asked-questions)

---

## Requirements

| Requirement | Minimum Version |
|-------------|-----------------|
| QGIS | 3.34 LTS |
| Python | 3.10 |
| Operating System | Linux, macOS, Windows |

No additional Python packages are required beyond what ships with QGIS.

---

## Installation

### From the QGIS Plugin Manager (recommended)

1. Download the latest `GeoLineage.zip` from the [Releases page](https://github.com/rafdouglas/GeoLineage/releases).
2. In QGIS, open **Plugins → Manage and Install Plugins**.
3. Click **Install from ZIP** and select the downloaded file.
4. Click **Install Plugin**.
5. In the Installed tab, ensure **GeoLineage** is checked.

### Manual installation

1. Copy the `GeoLineage/` folder to your QGIS plugin directory:
   - **Linux / macOS:** `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - **Windows:** `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
2. Restart QGIS.
3. Enable the plugin via **Plugins → Manage and Install Plugins**.

After enabling, a **GeoLineage** menu appears in the QGIS menu bar and a toggle button appears in the toolbar.

---

## Getting Started

The quickest way to get going:

1. **Enable recording** — click the GeoLineage toolbar button (or **GeoLineage → Enable Recording**).
2. **Set your username** — open **GeoLineage → Settings** and enter your name. This is stored in every lineage entry for audit purposes.
3. **Work normally** — run processing tools, edit layer features, or export layers as you always have.
4. **View the history** — open **GeoLineage → Open Lineage Viewer** and select a GeoPackage to see its ancestry graph.

---

## Recording Lineage

### Enabling Recording

Lineage recording is **off by default**. Toggle it on and off using:

- The **GeoLineage toolbar button**, or
- **GeoLineage → Enable Recording** in the menu bar.

When recording is active the toolbar button appears pressed/highlighted. All operations performed while recording is active will be captured. Operations performed while recording is off are not recorded.

> **Tip:** Recording is remembered per QGIS project. If you save a project while recording is on, it will resume automatically when you reopen the project.

---

### Processing Tools

Any algorithm run through the QGIS Processing Toolbox is captured automatically when recording is enabled. This includes:

- Built-in QGIS algorithms (e.g., Buffer, Clip, Dissolve)
- GRASS and SAGA tools
- Custom Python scripts run via `processing.run()`

For each operation, GeoLineage records:
- The tool/algorithm name
- All input parameters
- The input layer(s) used
- The output GeoPackage file and layer
- Your username and a timestamp

You do not need to do anything special — just run the tool as normal.

---

### Manual Edits

If you open a GeoPackage layer in edit mode and commit changes (add, modify, or delete features), GeoLineage records an edit entry automatically when you save.

The edit entry captures:
- The layer name
- The type of edit (features added / modified / deleted)
- Your username and a timestamp
- A checksum of the data after the edit

---

### Exporting Layers

When you use **Layer → Save As...** (Save Features As) to export a layer to a new GeoPackage, GeoLineage records an export entry that links the new file back to its source.

The export entry captures:
- The source GeoPackage path
- The output GeoPackage path
- Your username and a timestamp

This ensures that derived datasets maintain a traceable link to their origin even when data is copied to a new file.

---

### Multi-Step Workflows

GeoLineage handles workflows that involve temporary or in-memory layers between steps. For example:

1. You buffer a layer → result goes to a memory layer
2. You clip the memory layer → result goes to another memory layer
3. You export the final result to a GeoPackage

In this case, GeoLineage's **memory buffer** tracks all three steps. When the final result is saved to disk, the complete chain of operations is flushed to the `_lineage` table of the output GeoPackage. The full lineage — including the intermediate memory steps — is preserved even though no intermediate files were saved.

---

## Viewing Lineage

### Opening the Graph Viewer

Open the lineage graph for any GeoPackage:

1. **GeoLineage → Open Lineage Viewer** in the menu bar, or
2. Right-click a GeoPackage layer in the Layers panel and choose **Show Lineage**.

The viewer opens as a dock panel on the right side of QGIS. Use the file picker at the top of the dock to select a different GeoPackage.

---

### Navigating the Graph

The graph shows all ancestor datasets as nodes connected by arrows. The queried file is shown at the bottom; its parents, grandparents, and so on are shown above it.

| Action | How |
|--------|-----|
| Pan | Click and drag on empty canvas |
| Zoom | Mouse wheel or pinch gesture |
| Select a node | Click on it |
| Move a node | Click and drag the node |
| Constrain to axis while dragging | Hold **Shift** while dragging |
| Reset layout | Click the **Reset Layout** button in the toolbar |

---

### Node Colors and Status

Each node is color-coded based on whether the file it represents can be found:

| Color | Status | Meaning |
|-------|--------|---------|
| Blue | `present` | File exists at the recorded path |
| Green | `raw_input` | Original source data (no recorded parent) |
| Yellow | `missing` | File cannot be found at the recorded path |
| Grey | `busy` | File is currently locked or being written |

If you see yellow nodes, use the [Relink Dialog](#relink-dialog) to update the path to the file's new location.

---

### Detail Panel

Clicking any node opens a detail panel on the right side of the viewer showing:

- **Filename** — the base name of the file
- **Full path** — absolute path on disk
- **Operation type** — processing / edit / export
- **Tool** — the algorithm or operation name
- **Timestamp** — when the operation was recorded
- **Username** — who performed the operation
- **Parameters** — full parameter list (for processing operations)
- **Checksum** — SHA-256 hash of the data at the time of recording

---

### Exporting the Graph

Use the **Export** button in the viewer toolbar to save the graph in one of three formats:

| Format | Use case |
|--------|----------|
| **PNG** | Screenshot for reports or presentations |
| **SVG** | Scalable vector graphic for publications |
| **DOT** | Graphviz format for further processing |

---

## Managing Lineage Records

### Inspect Dialog

**GeoLineage → Inspect Lineage**

Opens a table showing all `_lineage` entries for a GeoPackage. You can:

- Browse all recorded operations sorted by date
- Edit the **Operation Summary** field of any entry to add notes
- Delete individual entries or a batch of entries
- Remove all lineage data from the file (drop tables)

> **Note:** Deleting lineage entries is permanent. Use this only to clean up test records or errors, not routine auditing.

---

### Settings Dialog

**GeoLineage → Settings**

| Setting | Description |
|---------|-------------|
| **Username** | Your name or identifier. Stored in every lineage entry you create. |
| **Recording enabled** | Toggle recording on/off (same as toolbar button). |

---

### Cleanup Dialog

**GeoLineage → Cleanup Lineage**

Scans a GeoPackage for orphaned lineage entries — records that reference files or layers that no longer exist. You can review and bulk-delete orphaned entries to keep the `_lineage` table tidy.

---

### Relink Dialog

**GeoLineage → Relink Lineage**

If files have been moved or renamed, their lineage references become broken (yellow nodes in the viewer). The Relink Dialog lets you remap old paths to new locations without losing any recorded history.

Steps:
1. Open **GeoLineage → Relink Lineage** and select the affected GeoPackage.
2. The dialog lists all parent references that cannot be resolved.
3. For each broken reference, click **Browse** to select the new file location.
4. Click **Apply** to update all matching entries.

---

## How Lineage is Stored

Lineage data is stored inside the GeoPackage file itself in two additional tables:

| Table | Purpose |
|-------|---------|
| `_lineage` | One row per recorded operation |
| `_lineage_meta` | Schema version for forward compatibility |

These tables use the underscore prefix convention and do not interfere with the standard GeoPackage specification. Any GIS application — ESRI ArcGIS, MapInfo, GDAL/OGR — can still open and read the file normally; they simply ignore the `_lineage` tables.

Because lineage is embedded in the GeoPackage, it travels with the file automatically. When you share a `.gpkg` file with a colleague, its complete history is included.

---

## Frequently Asked Questions

**Does GeoLineage slow down processing operations?**

The overhead is negligible. Recording writes a single small row to a SQLite table after each operation. Processing runtimes are not affected.

**Will lineage data break my GeoPackage?**

No. The `_lineage` and `_lineage_meta` tables are non-standard extension tables that do not affect the GeoPackage data model. All standard GIS tools will continue to work normally.

**Can I use GeoLineage without QGIS?**

The plugin requires QGIS to record lineage (since it intercepts QGIS operations). However, the `_lineage` table is plain SQLite and can be queried by any SQLite client without QGIS.

**What happens if the plugin crashes during recording?**

GeoLineage uses re-entracy guards and exception isolation so that a hook failure never blocks or crashes the underlying QGIS operation. The worst case is that a single operation is not recorded.

**Can I record lineage for Shapefiles or other formats?**

Currently, lineage is stored in GeoPackage files only. Operations involving Shapefiles as inputs are tracked when the output is a GeoPackage; the Shapefile itself does not receive a `_lineage` table.

**How do I disable recording temporarily?**

Click the toolbar button to toggle recording off. You can also disable it permanently for a project via **GeoLineage → Settings**.
