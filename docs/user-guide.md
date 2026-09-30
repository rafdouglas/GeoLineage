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

1. **Enable recording** — click the GeoLineage toolbar button (or the first entry of the **GeoLineage** plugin menu).
2. **Set your username** — open **GeoLineage → Settings** and enter your name. This is stored in every lineage entry for audit purposes.
3. **Work normally** — run processing tools, edit layer features, or export layers as you always have.
4. **View the history** — select a GeoPackage layer and open **GeoLineage → Show Lineage Graph** to see its ancestry graph.

---

## Recording Lineage

### Enabling Recording

Lineage recording is **off by default**. Toggle it on and off using:

- The **GeoLineage toolbar button**, or
- The first entry of the **GeoLineage** plugin menu (its label reflects the current state).

When recording is active the toolbar button appears pressed/highlighted. All operations performed while recording is active will be captured. Operations performed while recording is off are not recorded.

> **Tip:** Recording is remembered per QGIS project. If you save a project while recording is on, it will resume automatically when you reopen the project, and a project saved with recording off opens with recording off.

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
- The counts of features added, modified and deleted, and of attribute changes
- Your username and a timestamp

---

### Exporting Layers

When you use **Layer → Save As...** (Save Features As) to export a layer to a new GeoPackage, GeoLineage records an export entry that links the new file back to its source.

The export entry captures:
- The source GeoPackage path and a checksum of its data
- The output GeoPackage path
- Your username and a timestamp

Exports to formats other than GeoPackage are not recorded, because the lineage table lives inside the output file.

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

1. Select a GeoPackage layer and choose **GeoLineage → Show Lineage Graph** in the plugin menu, or
2. Right-click a GeoPackage layer in the Layers panel and choose **Show Lineage**, or
3. Select a row in **Manage Lineage...** and click **View in Graph**.

The viewer opens as a dock panel on the right side of QGIS. Use **Reload** in the viewer toolbar to refresh it after the file changes.

---

### Navigating the Graph

The graph shows all ancestor datasets as nodes connected by arrows. The queried file is shown at the bottom; its parents, grandparents, and so on are shown above it.

| Action | How |
|--------|-----|
| Pan | Right-click and drag on the canvas |
| Zoom | **Zoom In** / **Zoom Out** / **Fit to View** in the viewer toolbar |
| Select a node | Left-click on it |
| Node context menu | Right-click a node (copy path, open file location, load in QGIS, expand) |
| Load a node as a layer | Double-click it |
| Move a node | Left-click and drag the node |
| Constrain to axis while dragging | Hold **Shift** while dragging |
| Reset layout | Click the **Reset Layout** button in the toolbar |
| Find nodes | Type part of a filename in the search box |

---

### Node Colors and Status

Each node is color-coded based on whether the file it represents can be found and whether it still matches the data its children were built from:

| Color | Status | Meaning |
|-------|--------|---------|
| Green | `present` | File exists and has a `_lineage` table |
| Blue | `raw_input` | File exists but has no lineage (original source data) |
| Yellow | `modified` | File exists but its data changed since a child was derived from it |
| Red | `missing` | File cannot be found at the recorded path |
| Orange | `busy` | File is currently locked or being written |

The node you opened the viewer from has an amber outline; search matches get a yellow outline. A dashed border marks a node whose ancestry was truncated at the depth limit; right-click it and choose **Expand** to load more.

If you see red nodes, use the [Relink Dialog](#relink-dialog) to update the path to the file's new location.

---

### Detail Panel

Clicking any node opens a detail panel on the right side of the viewer showing:

- **Filename** — the base name of the file
- **Full path** — absolute path on disk
- **Status** — see the colour table above
- One block per lineage entry with its type (processing / manual_edit / export), tool, user, timestamp (UTC), clickable parent links and a collapsible parameter list

---

### Exporting the Graph

Use the **Export PNG**, **Export SVG** and **Export DOT** buttons in the viewer toolbar to save the graph:

| Format | Use case |
|--------|----------|
| **PNG** | Screenshot for reports or presentations |
| **SVG** | Scalable vector graphic for publications |
| **DOT** | Graphviz format for further processing |

---

## Managing Lineage Records

### Manage Lineage Dialog

**GeoLineage → Manage Lineage...**

Opens a table with the `_lineage` entries of every GeoPackage loaded in the current project. You can:

- Sort by any column
- Edit the **Summary** and **Edit Summary** cells to add notes
- Delete the selected entry (also from the right-click menu)
- Open the [Cleanup Dialog](#cleanup-dialog) or the [Relink Dialog](#relink-dialog)
- Jump to the selected file in the graph viewer with **View in Graph**

> **Note:** Deleting lineage entries is permanent. Use this only to clean up test records or errors, not routine auditing.

---

### Settings Dialog

**GeoLineage → Settings**

| Setting | Description |
|---------|-------------|
| **Record username in lineage entries** | When checked, the username below is stored in every lineage entry you create. |
| **Username** | Your name or identifier; defaults to your system user name when left empty. |

---

### Cleanup Dialog

Open it from **Manage Lineage... → Cleanup...**

Removes the `_lineage` and `_lineage_meta` tables from a single GeoPackage, or from every GeoPackage directly inside a directory. This deletes the recorded history and cannot be undone; the layer data itself is not touched.

---

### Relink Dialog

Open it from **Manage Lineage... → Relink...** with a row of the affected GeoPackage selected (the project must be saved so relative paths can be resolved).

If files have been moved or renamed, their lineage references become broken (red nodes in the viewer). The Relink Dialog lets you remap old paths to new locations without losing any recorded history.

Steps:
1. The dialog lists all parent references of the file that cannot be resolved.
2. Select a broken reference, click **Browse New Location** to pick the file's new path, then click **Relink Selected**.
3. For files that all moved together, use **Batch Prefix Replacement**: enter the old and new path prefix and click **Batch Relink**.

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

Click the toolbar button to toggle recording off. The state is saved with the project, so a project saved with recording off stays off when reopened.
