# QGIS 4.x migration strategy for GeoLineage

Prepared September 2026 against GeoLineage v0.7.0. Facts about QGIS come from the QGIS wiki page "Plugin migration to be compatible with Qt5 and Qt6" (revision of 2 April 2026), the `scripts/pyqt5_to_pyqt6/pyqt5_to_pyqt6.py` script on QGIS master, the QGIS source tree on the `release-3_44`, `release-4_0`, `release-4_2` and `master` branches, and the QGIS.org blog posts of April and October 2025 on the 4.0 schedule. The dry-run numbers below come from running the official migration script against this repository.

## Status

Phases 0 and 1 below, and the hook fallback part of Phase 2, are implemented on the `claude/wizardly-meitner-25rt7w` branch (version 0.8.0): the migration script was applied, the patterns it cannot see were fixed by hand, `metadata.txt` declares `qgisMaximumVersion=4.99`, a `qt6-compat` CI job runs the script in dry-run mode as a guard, `tests/test_qt6_compat.py` covers the manual patterns, the toolbox hook falls back to `AlgorithmWidget` on QGIS 4.2+, and GUI exports use `iface.layerSavedAs`. Still open: the Docker-based T2 integration tier, the history-registry replacement for the dialog patch, and the manual verification matrix of Phase 3, none of which can be done without a QGIS runtime.

## Where QGIS stands

QGIS 4.0 "Norrköping" was released on 6 March 2026. It is built on Qt 6 only (minimum Qt 6.4 on master, which now reports itself as 4.3.0), and there is no Qt 5 build of the 4.x line. The first long-term release of the new series is 4.2, scheduled to enter the LTR repositories in October 2026, so most institutional users will move during the coming year rather than immediately. QGIS 3.44 is the last 3.x release and the last 3.x LTR; 3.40 LTR support was extended to May 2026 and has now ended. Qt 6 builds of the 3.x release branches exist for Windows through OSGeo4W and for Debian, which makes it possible to test dual-compatible code on a 3.x runtime with PyQt6.

The plugin repository rules changed just before the 4.0 release. The `supportsQt6=True` metadata key that earlier guidance recommended is now obsolete and can be removed. What matters is the version range: a plugin that targets both major versions must set `qgisMaximumVersion` explicitly (the wiki gives `qgisMaximumVersion=4.99`), otherwise QGIS 4 will refuse to load it. A plugin that targets only 4.x sets `qgisMinimumVersion=4.0` and omits the maximum.

QGIS 4.0 retained deprecated APIs, so the breaking surface for Python plugins is almost entirely PyQt6: scoped enums, the removal of `exec_`, `QAction` moving to `QtGui`, `QVariant` type constants, `QRegExp`, `QDesktopWidget`, compiled `pyrcc5` resources and a few signal overloads. The `qgis.PyQt` shim in QGIS 4 papers over some of these but not the enums: it re-exports `QAction`, `QActionGroup` and `QShortcut` from `qgis.PyQt.QtWidgets`, restores the removed flag-container constructors such as `Qt.ItemFlags(...)`, and maps `QVariant.String` and friends to `QMetaType.Type`, but it adds no unscoped enum members and no `exec_` alias. Code that writes `Qt.UserRole` or `dlg.exec_()` raises `AttributeError` on QGIS 4.

## What this means for GeoLineage

GeoLineage is a favourable case. It is pure Python, has no `.ui` files, no compiled resources, no `QRegExp`, no `QVariant` usage outside the throwaway spike, and imports every Qt symbol through `qgis.PyQt`. The core packages (`lineage_core`, `lineage_retrieval`) do not import Qt at all. The exposure is confined to the GUI modules and to two hooks that depend on QGIS internals.

The official migration script, run in dry-run mode without QGIS introspection (which limits it to Qt enums), reports 51 findings across seven files: 45 unscoped enum accesses and 6 `exec_()` calls. Per file: `dock_widget.py` 14, `inspect_dialog.py` 15, `cleanup_dialog.py` 9, `detail_panel.py` 3, `export.py` 3, `plugin.py` 3, `graph_node_item.py` 2, `graph_scene.py` 1, `relink_dialog.py` 1. The script misses three further categories that must be handled by hand:

| Category | Where | Dual-compatible form |
|----------|-------|----------------------|
| QGIS enums (needs QGIS introspection to detect) | `plugin.py:88` `QgsMapLayer.VectorLayer` | `QgsMapLayer.LayerType.VectorLayer` |
| Enum members read through `self` on a `QGraphicsItem` subclass | `graph_node_item.py:177-179, 217, 241` (`self.ItemIsSelectable`, `self.ItemPositionChange`, ...) | `QGraphicsItem.GraphicsItemFlag.ItemIsSelectable`, `QGraphicsItem.GraphicsItemChange.ItemPositionChange` |
| Private processing API | `hooks.py` `processing.gui.AlgorithmDialog` | Removed in 4.2; see below |

Every scoped spelling in the right-hand column already works on PyQt 5.15, which is what QGIS 3.34 through 3.44 ship, and `exec()` has been available alongside `exec_()` in PyQt5 for years. A single codebase can therefore serve 3.34 through 4.x with no runtime branching for the Qt layer.

The one structural problem is the toolbox hook. `hooks.py` monkey-patches `processing.gui.AlgorithmDialog.finish`. That class is present on `release-4_0` but absent on `release-4_2` and master, where it has been replaced by `processing.gui.algorithm_widget.AlgorithmWidget`, a `QgsProcessingAlgorithmWidget` subclass with the same `finish(self, successful, result, context, feedback, in_place=False)` signature and the same `history_details` dictionary. On 4.2 the plugin will import-fail the hook, log one warning, and record nothing for GUI runs. The `QgsVectorFileWriter` monkey-patch has a related problem that is independent of the QGIS version: the GUI's Save As path is C++ and never calls the Python wrapper (see H1 in `docs/code-review-2026-09.md`). Both hooks should move to supported signals as part of this migration rather than being patched to the new private class name.

The Python version is not a concern. Current QGIS builds already ship Python 3.12 or 3.13 (the project's own spike ran on 3.13 under the 3.44 Flatpak), and the code uses nothing beyond 3.10 syntax. The `ruff` target can stay at `py310` until 3.34 support is dropped.

## Strategy

The recommendation is a single dual-compatible codebase, released as GeoLineage 0.8, that declares `qgisMinimumVersion=3.34` and `qgisMaximumVersion=4.99`, and to keep that arrangement until 3.44 falls out of use, which realistically means until some months after 4.2 LTR lands in October 2026. A branch split (a `3.x` maintenance branch and a `4.x` main) would double the release work for a codebase whose Qt surface is under 300 lines, and the scoped-enum spelling is the only form that works on both, so there is nothing to gain from diverging. Once 3.x is dropped, a 1.0 release can raise the minimum to 4.2, remove the compatibility shims in `hooks.py`, and apply the script's `--qgis3-incompatible-changes` pass if anything remains.

Because the migration touches the recording layer, the plan below front-loads test infrastructure. The plugin currently has no test tier that runs inside QGIS, so there is no way to prove that a hook still fires on 4.2 except by hand. That gap is the real risk of this migration, more than the enum edits.

### Phase 0. Test harness and guard rails

Add a T2 job to CI that runs the plugin's integration tests inside the official `qgis/qgis` Docker images with `QT_QPA_PLATFORM=offscreen`. Use a matrix of at least `release-3_44` (the last 3.x LTR) and `latest` (4.x), and add `release-4_2` when that image appears. `pytest-qgis` provides the `qgis_app`, `qgis_iface` and `qgis_processing` fixtures; the tests should load the plugin through `classFactory`, enable recording, run `native:buffer` through `processing.run` and through `execAlgorithmDialog`, save a layer through the writer, commit an edit, and assert on the `_lineage` rows. This is also the moment to turn the `spike/` script into a proper test.

Add a lint guard so the Qt5-only spellings cannot come back: run `pyqt5_to_pyqt6.py --dry_run` in CI and fail the job when it prints any finding. The script needs PyQt6, `astpretty` and `tokenize-rt`; without `qgis` importable it still catches all Qt enums and `exec_`, which is enough for a guard. The `qgis/pyqgis4-checker` Docker image bundles QGIS on Qt 6 with the script and can be used for the full run that also sees QGIS enums.

### Phase 1. Mechanical port

Run the migration script for real, on the pyqgis4-checker image so that QGIS enums are included, then review the diff. Fix by hand the `self.Item*` accesses in `graph_node_item.py` (the script only rewrites `Class.Member` forms), the `QgsMapLayer.VectorLayer` in `plugin.py`, and the six `exec_()` calls. Replace `contextlib.suppress(Exception)` around `addCustomActionForLayerType` with a narrower guard so a future API change surfaces in the log. Leave the `from qgis.PyQt.QtWidgets import QAction` imports as they are; the shim handles them on 4.x and `QtGui` would break 3.x.

Update `metadata.txt`: add `qgisMaximumVersion=4.99`, bump `version` to 0.8.0, add a changelog line, and do not add `supportsQt6`. Update the README requirements table to "QGIS 3.34 LTR to 4.x".

Run the T1 suite, ruff and the new dry-run guard. Install the ZIP into a QGIS 3.34, a 3.44 and a 4.0 profile and click through every dialog and every viewer action once; the migration script's own caveat is that it "might not do all necessary changes".

### Phase 2. Move the hooks to supported APIs

Replace the `AlgorithmDialog.finish` patch with a connection to `QgsGui.historyProviderRegistry().entryUpdated`. Both the 3.x dialog and the 4.2 widget write `history_details` with `algorithm_id`, `parameters` (the `asMap()` form the plugin already unwraps through its `inputs` key) and, on completion, `results`, into the `processing` history provider. Filtering on `entry["algorithm_id"]` and reading `entry["results"]["OUTPUT"]` gives everything the current hook extracts, on every version from 3.24 upward, for the toolbox dialog and for custom parameter widgets alike. Keep the `processing.run` wrapper for scripted runs, which do not write history, and de-duplicate by remembering the last `(algorithm_id, results)` pair recorded from either path. As a short-term fallback while that lands, `_install_dialog_hook()` can try `processing.gui.algorithm_widget.AlgorithmWidget` when the `AlgorithmDialog` import fails; the `finish` signature is identical, so the existing wrapper works unchanged. That fallback is private API and should carry a comment saying so.

Replace the GUI export detection with `iface.layerSavedAs`, connected in `install_hooks()` (the function needs `iface`, which `plugin.py` can pass in). Keep the `writeAsVectorFormatV3` wrapper only for Python callers. Guard everything version-specific with `Qgis.QGIS_VERSION_INT` checks or `try/except ImportError` at the point of use, never at module import, so that a missing symbol on one version degrades to a logged warning plus a message-bar notice rather than a failed plugin load.

These changes should be covered by the Phase 0 T2 tests on both matrix entries before the release.

### Phase 3. Verification matrix and release

Test the ZIP by hand on the combinations users are likely to run: QGIS 3.34 LTR and 3.44 LTR on Qt 5 (Windows OSGeo4W, and the Flatpak that `deploy.sh` targets), QGIS 3.44 on Qt 6 (OSGeo4W "qt6" packages) to confirm the dual spelling on a 3.x runtime, and QGIS 4.0 plus the 4.2 pre-release on Windows and Linux. The checklist for each: plugin loads without console errors, toolbar toggle and project persistence, toolbox run recorded, `processing.run` recorded, Save As recorded, manual edit recorded, graph viewer opens and exports PNG/SVG/DOT, Manage Lineage edit/delete/relink/cleanup. Record the results in the release notes.

Publish 0.8.0 to plugins.qgis.org with the dual version range. Announce the QGIS 4 support and state explicitly which recording paths work on which version, since a lineage tool that silently records less on a new version is worse than one that says so.

### Phase 4. Drop 3.x

When 3.44 usage among the plugin's users has faded (a reasonable trigger is 4.2 LTR having been out for six months), release 1.0 with `qgisMinimumVersion=4.2` and no maximum. Remove the `AlgorithmDialog` fallback, the `writeAsVectorFormatV3` identity checks that exist for older versions, and any `QGIS_VERSION_INT` branches. Raise the ruff target to `py312`, and consider `Qgis.LayerType.Vector` and `QMetaType.Type` spellings where the 3.x forms are now merely deprecated.

## File-by-file change list for Phase 1

| File | Lines | Change |
|------|-------|--------|
| `plugin.py` | 88 | `QgsMapLayer.VectorLayer` to `QgsMapLayer.LayerType.VectorLayer`; narrow the `suppress` |
| `plugin.py` | 237 | `Qt.RightDockWidgetArea` to `Qt.DockWidgetArea.RightDockWidgetArea` |
| `plugin.py` | 256, 263 | `exec_()` to `exec()` |
| `lineage_viewer/dock_widget.py` | 47, 74, 168, 261-262, 270, 274, 293, 295 | `Qt.DockWidgetArea.*`, `Qt.Orientation.Horizontal`, `Qt.AspectRatioMode.KeepAspectRatio`, `QGraphicsView.DragMode.NoDrag`, `Qt.CursorShape.*`, `Qt.MouseButton.RightButton` |
| `lineage_viewer/graph_node_item.py` | 150, 177-179, 217, 228, 241 | `Qt.PenStyle.DashLine`; `QGraphicsItem.GraphicsItemFlag.*` and `QGraphicsItem.GraphicsItemChange.*` instead of `self.Item*`; `Qt.KeyboardModifier.ShiftModifier` |
| `lineage_viewer/graph_scene.py` | 220 | `menu.exec_()` to `menu.exec()` |
| `lineage_viewer/detail_panel.py` | 61, 95, 155 | `Qt.AlignmentFlag.AlignTop`, `QFrame.Shape.StyledPanel`, `Qt.TextInteractionFlag.TextSelectableByMouse` |
| `lineage_viewer/export.py` | 93, 94, 97 | `QImage.Format.Format_ARGB32_Premultiplied`, `Qt.GlobalColor.white`, `QPainter.RenderHint.Antialiasing` |
| `lineage_manager/inspect_dialog.py` | 82, 127-133, 179-180, 198, 211, 255-258, 268, 285, 312 | `Qt.WidgetAttribute.WA_DeleteOnClose`, `QAbstractItemView.SelectionBehavior.SelectRows`, `QAbstractItemView.SelectionMode.SingleSelection`, `QHeaderView.ResizeMode.ResizeToContents`, `Qt.ContextMenuPolicy.CustomContextMenu`, `Qt.ItemFlag.ItemIsEditable`, `Qt.ItemDataRole.UserRole`, `QMessageBox.StandardButton.*`, three `exec()` |
| `lineage_manager/cleanup_dialog.py` | 43, 115-118, 143-146 | `Qt.WidgetAttribute.WA_DeleteOnClose`, `QMessageBox.StandardButton.*` |
| `lineage_manager/relink_dialog.py` | 48 | `Qt.WidgetAttribute.WA_DeleteOnClose` |
| `metadata.txt` | | `qgisMaximumVersion=4.99`, version bump, changelog |
| `spike/validate_qgis_assumptions.py` | 33, 72 | Imports `PyQt5` directly and uses `QgsField(name, QVariant.String)`; either port or exclude from the guard (it is already excluded from packaging) |

The `flags() & ~Qt.ItemFlag.ItemIsEditable` and `queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier` expressions work unchanged on PyQt6 because these are `IntFlag` types; the QGIS shim's `Qt.CheckState` patch is not needed here since the plugin does not use check states.

## Risks and open points

The history-registry approach in Phase 2 should be validated on 3.34 before it replaces the dialog patch; the registry exists there, but the exact shape of the `parameters` map for feature-source inputs with selection enabled needs a test, since that is also where the current hook drops parents. The batch dialog does not write history on master, so batch runs stay unrecorded under both approaches; that is a documented limitation rather than a regression.

If the plugin repository's automated checks for QGIS 4 compatibility become stricter than the wiki describes, the dry-run guard in Phase 0 is the fastest way to find out, because it runs the same script the checker uses.

Finally, the `sqlite3` module, the checksum code and the graph layout are untouched by any of this. The core of the plugin is already QGIS-4 ready; the work is in the GUI spelling and in replacing two monkey-patches that were fragile on 3.x as well.
