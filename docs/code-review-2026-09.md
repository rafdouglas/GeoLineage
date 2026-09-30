# GeoLineage code review (v0.7.0, September 2026)

This review covers the whole plugin as of commit `26980ec` on the `main` line: `plugin.py`, `lineage_core`, `lineage_retrieval`, `lineage_manager`, `lineage_viewer`, the test suite, CI, packaging scripts and the user-facing documentation. The T1 suite was run (313 tests pass, 65% line coverage on `lineage_core` and `lineage_retrieval`, `hooks.py` at 39%), ruff check and format are clean, and every finding marked "verified" below was reproduced with a small script against the real modules. Findings marked "source-verified" were confirmed by reading the relevant QGIS C++ or Python source on GitHub. Findings marked "probable" come from code reading only and should be confirmed inside a running QGIS before being fixed.

The plugin is in good shape overall. The pure-Python core is well factored, exception-isolated, and unusually well tested for a QGIS plugin. The problems concentrate in two places: the interception layer in `hooks.py`, which leans on private QGIS internals and on monkey-patching that the QGIS GUI never routes through, and a handful of edge cases in the file-level checksum and graph code. Several user-guide statements no longer match what the code does.

## Status

All findings below except T1 (the integration test tier) and the per-table checksum redesign in C3 were fixed on the `claude/wizardly-meitner-25rt7w` branch; `tests/test_review_fixes.py` holds one regression test per fix. H2 was addressed with the `AlgorithmWidget` fallback; the history-registry approach remains the recommended follow-up once a T2 harness exists to validate it.

## Summary

| ID | Area | Severity | Confidence | Finding |
|----|------|----------|------------|---------|
| H1 | hooks | High | source-verified | GUI "Save Features As" exports are never recorded; the monkey-patch only sees Python callers |
| H2 | hooks | High | source-verified | The toolbox hook depends on `processing.gui.AlgorithmDialog`, which no longer exists from QGIS 4.2 |
| H3 | hooks | High | verified | Memory-buffer chains are never flushed when the final output is a path string (for example `native:savefeatures`) |
| H4 | hooks | Medium | probable | Input parameters outside a hard-coded key list are ignored, so many algorithms lose their parents |
| H5 | hooks | Medium | probable | Output layer name is taken from the file name, not from the `layername=` part of the output URI |
| H6 | hooks | Medium | probable | "Selected features only" inputs lose their parent reference |
| H7 | hooks | Low | verified | Passing an algorithm object to `processing.run` drops the record with a `TypeError` |
| H8 | hooks | Low | probable | Per-layer edit connections are never pruned when layers are removed |
| C1 | core | High | verified | A stale `gpkg_contents` row or a quoted table name makes the whole file appear as `raw_input` with no history |
| C2 | core | Medium | verified | SQLite connections opened with `with sqlite3.connect(...)` are never closed |
| C3 | core | Medium | probable | Checksums are per file, computed after the algorithm ran, and recomputed on the GUI thread on every graph build |
| C4 | core | Low | verified | `extract_gpkg_path` is case sensitive while the hooks are not |
| C5 | core | Low | verified | `_cleanup_chain` leaves empty link lists behind |
| V1 | viewer | Medium | verified | Writing an output into the same GeoPackage as its input produces a self-loop that breaks the layout ranks |
| V2 | viewer | Medium | verified | The lineage cache exists and is tested but is never used by the dock widget |
| V3 | viewer | Low | probable | A locked file shows as `raw_input` instead of `busy` |
| V4 | viewer | Low | probable | PNG and SVG exports use `sceneRect()`, which never shrinks after a larger graph was shown |
| V5 | viewer | Low | probable | Edge items are matched to layout paths by index and by (source, target) only |
| P1 | plugin | Medium | probable | `unload()` never removes the toolbar from the main window |
| P2 | plugin | Medium | probable | Project state restore can switch recording on but never off, and dirties the project on load |
| P3 | plugin | Low | probable | `QgsMapLayer.VectorLayer` is wrapped in a blanket `suppress(Exception)`, so the context-menu entry vanishes silently on QGIS 4 |
| M1 | manager | Low | probable | Cell edits are keyed by row while sorting is enabled |
| M2 | manager | Low | probable | Batch cleanup on a missing directory raises an unhandled exception |
| D1 | docs | Medium | verified | The user guide describes colours, gestures, menus and dialogs that do not match the code |
| T1 | tests | Medium | verified | No T2 tests exist; `hooks.py` is the least covered and most fragile module |

## Recording hooks

### H1. GUI exports are not captured

`_install_filewriter_hook()` replaces `QgsVectorFileWriter.writeAsVectorFormatV3` on the Python side. That only affects Python code that calls the static method through the sip wrapper. The QGIS "Save Features As" dialog runs `QgsVectorFileWriterTask` in C++, whose `run()` calls the C++ `QgsVectorFileWriter::writeAsVectorFormatV2(PreparedWriterDetails, ...)` overload directly (`src/core/qgsvectorfilewritertask.cpp`). No Python wrapper is involved, so the plugin's hook never fires for the workflow the README and user guide advertise. The project's own spike (`spike/spike_output.txt`, test 4) already found "Signals fired during writeAsVectorFormat: NONE", which pointed in this direction.

The supported hook is the `QgisInterface.layerSavedAs(QgsMapLayer, str)` signal, present in 3.34 and in master, which is emitted exactly when the Save As dialog finishes. Connecting to `iface.layerSavedAs` from `install_hooks()` (the plugin already has `iface`) replaces the monkey-patch for the GUI path. The V3 wrapper can stay for scripts that call the writer directly.

### H2. The toolbox hook targets a class that QGIS removed

`_install_dialog_hook()` imports `processing.gui.AlgorithmDialog` and replaces its `finish` method. That file exists on `release-3_44` and `release-4_0`, but on `release-4_2` and master it is gone. The dialog logic now lives in `processing.gui.algorithm_widget.AlgorithmWidget`, a `QgsProcessingAlgorithmWidget` subclass with the same `finish(self, successful, result, context, feedback, in_place=False)` signature and the same `history_details` dictionary. On 4.2 (the first 4.x LTR) the plugin logs one warning and then silently records nothing for any algorithm run from the toolbox. Since 4.0 keeps the old file, the failure will appear only when users move to the LTR.

Beyond the version issue, this hook is a private-API dependency that QGIS has already changed once in a minor release, and it misses runs that go through `BatchAlgorithmDialog`, the model designer, or an algorithm's `createCustomParametersWidget()`. A supported alternative with the same information is the history registry: both the old dialog and the new widget write `history_details` (keys `algorithm_id`, `parameters`, later `results` and `log`) through `QgsGui.historyProviderRegistry().addEntry("processing", ...)` and `updateEntry(...)`, and the registry emits `entryAdded(id, QgsHistoryEntry, backend)` and `entryUpdated(id, dict, backend)`. Connecting to `entryUpdated` and filtering on the `processing` provider gives parameters and results for every GUI run on 3.24 through master without touching private classes. `processing.run()` from Python does not write history, so the existing `processing.run` wrapper must stay, with de-duplication between the two paths (the results dictionary and the algorithm id are enough to detect the same run).

### H3. Memory-buffer chains are not flushed for path-string outputs

In `_record_processing_lineage()` the flush of buffered ancestors runs only inside `if layer_id:`. When the final step returns a plain path string, which is what `native:savefeatures` does (see the spike output, step C) and what any `processing.run` call with `OUTPUT='/x.gpkg'` does when the result is not loaded as a layer, `layer_id` is `None` and the chain stays in memory forever. This is the exact "multi-step workflow" the user guide promises, and it also leaks buffered entries. The flush should be conditioned on `gpkg_path` alone. The `chain = get_chain(); if chain: flush()` pair can be reduced to a single `flush()` call, which already no-ops on an empty chain.

### H4. Input discovery uses a fixed key list

`_get_input_keys()` queries the processing registry for the algorithm's vector parameters, but nothing calls it. `_extract_input_layer_ids()` and the parent loop in `_record_processing_lineage()` use `_FALLBACK_INPUT_KEYS` only, so algorithms whose inputs are named `INPUT_2`, `INTERSECT`, `TARGET`, `REFERENCE`, `POINTS`, `POLYGONS`, `HUBS`, `SPOKES` and so on record no parents for those inputs. Using the registry keys unioned with the fallback list fixes the common cases (`native:joinattributestable`, `native:extractbylocation`, `native:joinbynearest`, most GRASS tools) without hard-coding more names. The same applies to outputs: only the `OUTPUT` key is examined, so algorithms with several sink outputs record at most one.

### H5. Wrong layer name for string outputs

When the result `OUTPUT` is a string, `_get_output_layer_info()` sets `layer_name` to the file's base name. Processing returns GeoPackage outputs as `path.gpkg|layername=table`, so any run that writes a new table into an existing GeoPackage records the file name (`data`) instead of the table (`buffered`). The `layername=` value should be parsed from the URI and used when present.

### H6. Feature source definitions are not unwrapped

A `QgsProcessingFeatureSourceDefinition` (the "selected features only" checkbox, or a script passing one) has a `source` attribute that is a `QgsProperty`, not a callable, so `_get_layer_source_path()` returns `None` and the parent is dropped. The dialog path serialises it through `asMap()` as a dictionary, which is also not handled. Both forms can be unwrapped in `_resolve_output_layer_definition()` style: read `.source.staticValue()` for the object and `["source"]` for the dictionary.

### H7. Algorithm objects as the first argument

`processing.run()` accepts either an id string or a `QgsProcessingAlgorithm`. The wrapper forwards `args[0]` as `algorithm_name`; `_build_processing_summary()` then does `":" in tool` and raises `TypeError`, which the wrapper catches and logs, so the record is lost. Call `.id()` when the object is not a string.

### H8. Edit connections are never pruned

`_layer_edit_connections` grows on every `layersAdded` and only shrinks on `uninstall_hooks()`. Layers removed from the project leave closures holding references to deleted C++ objects, and the later disconnect raises `RuntimeError` (suppressed). Connect to `QgsProject.layersWillBeRemoved` and pop the entries. While there, `layer_id = layer.id() if hasattr(layer, "id") else str(id(layer))` is fine, but the snapshot dictionary keyed by layer id is shared across all layers under one lock, which is correct but makes the per-layer closures redundant; a single pair of slots taking `layer` from `self.sender()` would be simpler.

Two smaller observations on this module. `_get_created_by()` is called twice per record and constructs a `QgsSettings` each time; read it once. And `_sanitize_params()` stringifies nested dictionaries with `str(v)`, which turns lists inside dictionaries into Python reprs rather than JSON.

## Core data layer

### C1. One bad table hides a file's entire history

`_read_file_data()` in `graph_builder.py` computes the checksum before reading the version and rows, inside one `try` that maps `sqlite3.OperationalError` to `("raw_input", [], None)`. Two realistic inputs make the checksum raise: a table name containing a double quote (`checksum.py` interpolates names into `"..."` without doubling the quote), and a `gpkg_contents` row whose table no longer exists (GDAL and other tools sometimes leave these behind). Both were reproduced. The consequence is severe for a lineage tool: a file with a full `_lineage` table is displayed as an original input with no entries, and nothing in the log points at the cause. The checksum should be computed in its own `try`, the failure should log a warning, and the rows should still be read. Quoting can use `name.replace('"', '""')`, and `PRAGMA table_info` needs the same treatment for single quotes.

`compute_checksum()` and `compute_checksum_via_conn()` are also duplicated line for line; the first should open a connection and delegate to the second. Each of them runs `PRAGMA table_info` twice per table.

### C2. Connections are not closed

Every `with sqlite3.connect(path) as conn:` block in `schema.py`, `recorder.py`, `checksum.py` and `data_ops.py` commits or rolls back on exit but does not close the connection (this is documented behaviour of the sqlite3 context manager). The connection lives until garbage collection. On Windows an open handle keeps the GeoPackage locked, which breaks the common "overwrite existing output" flow and can make QGIS report the file as in use. Wrap connections in `contextlib.closing()` or use a small helper that closes in `finally`, as `repair_lineage.py` and `data_ops.relink_parent()` already do. `record_processing()` also opens two connections per row (one in `ensure_lineage_table`, one for the insert); a single connection per write is cheaper and avoids a window where another writer can grab the lock.

### C3. Checksum design

Three related points. First, `parent_checksums` are computed after the algorithm has run. When the output is written into the same GeoPackage as an input (the most common GeoPackage workflow), the "input" checksum already includes the new table, so it does not describe the input state. Second, the checksum covers the whole file, while every lineage row is about one layer; adding any unrelated table to a parent later marks it "modified". Per-table checksums stored as `{path: {table: sha256}}` would make the "modified" status meaningful and would also make V1 solvable. Third, `compute_checksum()` reads every row of every table with `fetchall()` and runs on the GUI thread, once per parent on every processing run and once per node on every graph build or expand. On a multi-gigabyte GeoPackage this freezes QGIS. A `QgsTask` for the graph build, plus an mtime-keyed cache (see V2), removes most of the cost; incremental hashing with `fetchmany()` removes the memory spike.

### C4. Case sensitivity

`path_resolver.extract_gpkg_path()`, `data_ops.batch_drop_lineage()` and `cleanup_dialog._cleanup_batch()` test `endswith(".gpkg")` while `hooks._is_gpkg_path()` lowercases first. A `DATA.GPKG` layer records lineage but the viewer says it "is not backed by a GeoPackage". Normalise in one helper and use it everywhere.

### C5. Memory buffer bookkeeping

`_cleanup_chain()` removes flushed node ids from other nodes' parent lists but leaves the now-empty lists in `_links` (`discard()` handles this correctly). Harmless, but it makes `get_chain()` return non-empty for ids that have no entries and makes tests of `len(_links)` misleading. Also, `MemoryBuffer` is shared module state touched from `processing.run` wrappers that may execute on worker threads; a lock around `add`, `link`, `flush` and `discard` costs nothing.

Minor items in this layer: `SETTING_ENABLED`, `DEFAULT_USERNAME` and `layout_graph()` are unused; `parent_metadata` is always `[]` and could be dropped from the schema or actually populated (layer name, feature count, CRS of the parent would be useful); `created_at` is SQLite `CURRENT_TIMESTAMP` in UTC with no zone marker and is shown verbatim in the UI, so users will read it as local time; `output_crs_epsg` uses `postgisSrid()`, which is 0 for any non-EPSG CRS, so storing `authid()` as text would be more faithful.

## Retrieval and viewer

### V1. Self-loops break the layout

When a processing output lands in the same GeoPackage as its input, `build_graph()` emits an edge whose parent and child are the same path. `_break_cycles()` detects it as a back edge, removes it and then re-adds it in the reversed direction, which for a self-loop is the same edge. `_assign_ranks()` then never sees the node's in-degree reach zero, so the node and everything downstream of it fall back to rank 0, or in the single-node case the node ends up at rank 1 with no rank-0 row. Reproduced: a three-node graph with one self-loop placed the child at the same rank as its grandparent. Filter `parent_path == child_path` edges in `build_graph()` (an intra-file operation is better represented in the node's entry list than as an edge), and make `_break_cycles()` drop rather than reverse self-loops as a safety net.

### V2. The cache is never used

`LineageCache` has 133 lines of tests, and `build_graph()` accepts a `cache` argument, but `LineageDockWidget.show_lineage()` and `expand_node()` call `build_graph()` without one. Every reload, expand or "View in Graph" recomputes every checksum. Keep one `LineageCache` on the dock widget and pass it through.

### V3. Busy detection

`_read_file_data()` returns `busy` only when `sqlite3.connect()` itself raises. A locked database (`SQLITE_BUSY`) raises `OperationalError` from the first query, which lands in the generic handler and reports `raw_input`. Check `"locked" in str(exc)` or the extended error code and return `busy` there.

### V4. Export bounds

`export_png()` and `export_svg()` use `scene.sceneRect()`. When no explicit scene rect is set, Qt reports the union of every item rect the scene has ever contained, and it does not shrink after `clear()`. After viewing a large graph and then a small one, the export is mostly blank. Use `itemsBoundingRect()` with a margin, or call `setSceneRect(itemsBoundingRect())` at the end of `set_graph()`.

### V5. Edge matching

`set_graph()` pairs each `EdgePath` with the first `LineageEdge` having the same (source, target), so two entries linking the same files draw two curves that both reference the first entry, and the O(E²) `next()` search shows on large graphs. `reset_layout()` assumes `_edge_items[i]` corresponds to `result.edge_paths[i]`, which holds today only because both loops skip the same edges in the same order. Carrying `entry_id` in `EdgePath` and keying items by (source, target, entry_id) removes both assumptions.

Smaller viewer items: `_merge_graphs()` compares `depth` values that were measured from different roots; `export_dot()` does not escape backslashes and `_path_to_id()` maps `a-b.gpkg` and `a_b.gpkg` to the same id; `GraphNodeItem` measures text twice (once in `compute_node_display_width()` and again in `__init__`); the tooltip reads a `crs` key that no entry ever has (`output_crs_epsg` is the stored key).

## Plugin lifecycle

### P1. Toolbar is not removed on unload

`unload()` does `del self.toolbar`, which drops the Python reference only. The `QToolBar` was created by `iface.addToolBar()` and is owned by the main window, so it survives and reappears duplicated after every plugin reload. Call `self.iface.mainWindow().removeToolBar(self.toolbar)` and `self.toolbar.deleteLater()`.

### P2. Project state handling

`_restore_toggle_state()` only ever calls `setChecked(True)`. Opening a project that has recording off, after one that had it on, leaves recording on, which contradicts the "remembered per QGIS project" note in the user guide. It should set the checked state to the stored value in both directions and should also react to `QgsProject.cleared` or `iface.newProjectCreated` so a new project starts from the default. Because `setChecked()` triggers `_on_toggle()`, which calls `writeEntry()`, every project open immediately becomes dirty; guard the write with a flag while restoring. `readProject` also fires before layers are fully restored in some paths, so `_install_edit_signals()` may run before the layers exist; relying on `layersAdded` for later layers covers that, but it is worth a comment.

### P3. Silent failure of the layer context-menu entry

`addCustomActionForLayerType(..., QgsMapLayer.VectorLayer, True)` is wrapped in `contextlib.suppress(Exception)`. Under QGIS 4, `QgsMapLayer.VectorLayer` raises `AttributeError` (unscoped enum access is gone), and the suppression hides it, so the "Show Lineage" entry simply disappears. Use `QgsMapLayer.LayerType.VectorLayer`, which works on both, and narrow the suppression to the QGIS versions that lack the API.

## Manager dialogs

### M1. Edits keyed by row under sorting

`_on_cell_changed(row, col)` looks up the id and file items by `row` while `setSortingEnabled(True)` is active. Editing the Summary column can re-sort the table before or during the signal, the same class of problem already fixed in `_load_entries()`. Connect to `itemChanged(item)` instead and read `item.row()`, or store `entry_id` and `gpkg_path` as `UserRole` data on the editable item itself.

### M2. Unhandled errors in batch cleanup

`_cleanup_batch()` calls `os.listdir(directory)` before validating the path; a typo produces a Python traceback dialog. `batch_relink_prefix()` does `p.startswith()` on every element of `parent_files` and will raise if a stored element is not a string. Both should fail with a message box.

## Documentation

### D1. The user guide has drifted from the code

The colour legend in `docs/user-guide.md` (blue present, green raw input, yellow missing, grey busy) does not match `STATUS_COLORS` (green present, yellow modified, red missing, blue raw input, orange busy), and it omits the `modified` status entirely. Panning is described as left-drag on empty canvas; the view implements right-drag. The guide mentions a file picker at the top of the dock, a "Recording enabled" setting, a checksum recorded on manual edits, and an orphan-scanning cleanup dialog; none of these exist. Menu labels differ from the code ("Open Lineage Viewer" versus "Show Lineage Graph", "Inspect Lineage" versus "Manage Lineage..."). The README still marks the viewer and manager as "(planned)" and states that Save Features As exports are logged, which H1 shows is not the case. Since the plugin is now public, aligning the guide with the actual behaviour is worth doing before the next release.

## Tests and CI

### T1. No integration tier

`hooks.py` is the module most exposed to QGIS internals and the least covered (39%), and nothing exercises `plugin.py`, the dialogs or the scene against a real QGIS. A T2 job using the official `qgis/qgis` Docker images with `QT_QPA_PLATFORM=offscreen` and `pytest-qgis` would have caught H1 and H2 and is a prerequisite for the QGIS 4 migration (see `docs/qgis4-migration-strategy.md`). The T1 suite itself is solid; the only gap noticed is that `test_hooks.py` mocks `_FALLBACK_INPUT_KEYS` behaviour rather than `_get_input_keys()`, which is why the dead code went unnoticed. `--cov-fail-under=50` could be raised to the current 65 so coverage does not regress.

Packaging is fine. `scripts/release.sh` validates metadata and syntax and ships only the four packages plus resources; `deploy.sh` mirrors it. Bandit runs on the four packages. One small thing: the `ruff.toml` `target-version` is `py310` while QGIS 4 ships Python 3.12 on Windows, so `py311` or `py312` could be adopted once 3.34 support is dropped.

## Suggested order of work

The highest-value sequence is to fix the three recording bugs first, because they affect what gets written to files and cannot be repaired later: H3 (flush on path outputs), H1 (use `layerSavedAs`) and H2 (use the history registry, which also future-proofs the plugin). C1 and C2 come next because they affect every reader and every writer. V1, V2 and P1 are small and self-contained. H4, H5, H6 improve the completeness of what is recorded and should ship together with a `_lineage_meta` schema bump if the `parent_checksums` shape changes. D1 can be done at any time and should land before the next public release.

Two structural improvements would pay off over time. Moving all SQLite access behind one small connection helper (open, `closing`, timeout, `query_only` for readers) would resolve C2 and V3 in one place. And storing parent paths relative to the child GeoPackage when both share a directory tree would make lineage survive a folder move without the relink dialog, which is what a "permanent chain of custody" implies.
