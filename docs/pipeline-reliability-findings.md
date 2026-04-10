# GeoLineage Pipeline Reliability Findings

**Date:** 2026-04-10  
**Scope:** `lineage_core/` modules — `checksum.py`, `graph_builder.py`, `memory_buffer.py`, `hooks.py`, `graph_layout.py`, `cache.py`  
**Analysis method:** Code review + technical reference cross-check  

---

## Summary

17 issues identified across 6 modules. Grouped by severity. Issue 4a (alleged double-recording via dual hooks) was investigated and **retracted** — the two hooks target mutually exclusive execution paths (`processing.run()` vs. `AlgorithmDialog.finish()`). Issue 1c (non-registered table inclusion) was **dropped** by design decision: only `gpkg_contents`-registered tables are hashed.

| Severity | Count |
|----------|-------|
| HIGH     | 3     |
| MEDIUM   | 7     |
| LOW      | 7     |

---

## HIGH

### 1a — Checksum collision: no value-length delimiter
**Module:** `checksum.py`  
**Description:** Column values are concatenated without a length prefix or separator during row serialization. The strings `"ab"` + `"c"` and `"a"` + `"bc"` produce identical byte sequences. This can cause two genuinely different rows to hash identically.  
**Example:** `("ab", "c")` → same digest as `("a", "bc")`  
**Fix:** Prefix each serialized column value with its byte length (e.g. `len(value_bytes).to_bytes(4, "little")` before the value) so the boundary between adjacent columns is unambiguous.

---

### 2a — `expected_checksums` first-write-wins on shared parents
**Module:** `graph_builder.py`  
**Description:** When multiple child files share a parent, the first child's recorded `expected_checksums` entry for that parent wins; later children's records are silently ignored. A child recorded after the parent was modified will have the correct expectation; an earlier child's stale expectation will mask the modification.  
**Design resolution:** Flag a node as `modified` if **any** child's recorded expectation disagrees with the current checksum. The current first-write-wins merge should become a last-write-wins merge, or (better) a union check that triggers `modified` on any mismatch.  
**Fix:** When merging `expected_checksums` during BFS graph construction, treat any disagreement across children as a `modified` signal rather than silently overwriting.

---

### 3a — Flush atomicity: cleanup runs after partial failure
**Module:** `memory_buffer.py`  
**Description:** In `flush()`, `_cleanup_chain()` is called unconditionally after `record_processing()` even if `record_processing` raised or wrote only part of the chain. Temporary layers are discarded from the in-memory buffer whether or not their lineage was successfully persisted to disk.  
**Fix:** Wrap the flush body in a `try/except`. Call `_cleanup_chain()` only when `record_processing()` completes without error. On failure, leave the chain intact so the user can retry or inspect it.

---

## MEDIUM

### 1b — `rowid` ordering unstable after VACUUM
**Module:** `checksum.py`  
**Description:** Rows are fetched `ORDER BY rowid ASC`. SQLite `rowid` values are stable under normal operation but are reassigned after `VACUUM` (or `VACUUM INTO`). If a GeoPackage is vacuumed between two checksum computations, row order can change even if the data is logically identical, producing a different hash.  
**Breaking change:** Fixing this requires switching to `ORDER BY <primary_key_columns> ASC`. The existing stored checksums will differ from recomputed ones — a one-time migration is needed.  
**Fix:** Detect the table's primary key columns at runtime (via `PRAGMA table_info`) and order by those instead. Document the migration: stored checksums computed before this fix are incompatible with checksums computed after.

---

### 3b — `_cleanup_chain` leaves dangling back-references in `_links`
**Module:** `memory_buffer.py`  
**Description:** `_cleanup_chain` removes entries from `_layers` but does not remove the corresponding parent → child edges from `_links`. After a flush, stale references can remain, causing ghost chains or incorrect DFS traversals for any layer still referencing a flushed ancestor.  
**Fix:** When cleaning up a layer ID, also remove it from the values of `_links` (i.e. scan `_links` and drop any reference to the removed ID).

---

### 4b — Hardcoded input-key set duplicated across hooks
**Module:** `hooks.py`  
**Description:** The tuple `("INPUT", "INPUT_LAYER", "LAYERS", "INPUT1", "INPUT2", "OVERLAY", "LAYER", "SOURCE_LAYER")` appears at line 117 and again at line 265. These hard-coded keys miss algorithm-specific parameter names and must be maintained in two places.  
**Fix:** At hook time, call `QgsApplication.processingRegistry().algorithmById(algorithm_name).parameterDefinitions()` and filter for `QgsProcessingParameterVectorLayer` / `QgsProcessingParameterFeatureSource` / `QgsProcessingParameterMultipleLayers` types to discover actual input parameters dynamically. Extract the key set into a single `_get_input_keys(algorithm_name)` helper used in both places.

---

### 4c — `_pending_edit_snapshots` not thread-safe
**Module:** `hooks.py`  
**Description:** `_pending_edit_snapshots: dict[str, dict[str, int]] = {}` is a module-level mutable dict. QGIS may emit layer-edit signals from background threads (e.g. when saving via a worker task). Concurrent reads/writes to this dict without a lock can corrupt its state.  
**Fix:** Protect all access to `_pending_edit_snapshots` with a `threading.Lock()` (also module-level). Alternatively, use a `threading.local()` if edits are guaranteed to be per-thread.

---

### 5a — `_break_cycles` recursive DFS → `RecursionError` on large graphs
**Module:** `graph_layout.py`  
**Description:** The cycle-breaking step uses a recursive DFS with no depth guard. Python's default recursion limit is 1000. A DAG with more than ~900 ancestor levels will raise `RecursionError` before layout begins.  
**Fix:** Convert `_break_cycles` to an iterative DFS using an explicit stack.

---

### 5b — `sorted_ranks.index()` in nested loop → O(n³) crossing minimisation
**Module:** `graph_layout.py`  
**Description:** The barycenter crossing-minimisation step iterates over layers and, for each node, calls `sorted_ranks.index(node)` which is O(n) linear scan. This makes the inner loop O(n²) per layer, and with the outer sweep loop the overall complexity becomes O(n³). A 200-node graph already shows visible slowness; a 500-node graph is unusable.  
**Fix:** Pre-build a `rank_index: dict[node, int]` before the sweep so all position lookups are O(1). The crossing-minimisation step becomes O(n²) overall.

---

### 6a — Float mtime comparison misses sub-second changes
**Module:** `cache.py`  
**Description:** Cache validity is checked by comparing `os.path.getmtime()` floats. On most Linux filesystems the mtime resolution is 1 second (ext3) or 1 nanosecond (ext4, APFS), but when comparing a cached float to a fresh `getmtime()`, floating-point precision loss can cause a file modified within the same second to appear unchanged.  
**Fix:** Use `os.stat().st_mtime_ns` (integer nanoseconds, available since Python 3.3) for both the cached value and the comparison. This eliminates float rounding entirely.

---

## LOW

### 2b — `resolve()` called twice per parent reference
**Module:** `graph_builder.py`  
**Description:** For each parent path stored in a lineage record, `resolve()` is called to canonicalise the path — once when building the node key and once when looking it up in the node dict. Each call may trigger a filesystem stat.  
**Fix:** Call `resolve()` once per parent path, store the result in a local variable, and reuse it.

---

### 2c — Two SQLite connections per file read
**Module:** `graph_builder.py`  
**Description:** During BFS expansion, each file is opened with two separate `sqlite3.connect()` calls in quick succession (one for lineage records, one for checksums). Each connection incurs open/close overhead.  
**Fix:** Open a single connection per file and issue both queries within the same connection context.

---

### 3c — Two DFS traversals in flush
**Module:** `memory_buffer.py`  
**Description:** `flush()` performs a topological sort (one DFS) and then a cleanup traversal (second DFS) over the same chain. These can be unified into a single pass that collects the ordered IDs and the IDs to remove simultaneously.  
**Fix:** Merge the two traversals into one DFS that returns both the ordered list and the set of visited IDs for cleanup.

---

### 4a-new — Dialog hook `history_details` parameter recovery fragile
**Module:** `hooks.py`  
**Description:** The dialog hook recovers algorithm parameters via `getattr(dialog_self, "history_details", {}).get("parameters", {})`. If `history_details` is absent (e.g. the dialog was closed before finishing, or a future QGIS version renames the attribute), parent tracking silently produces an empty parent list. There is no warning logged.  
**Fix:** Log a `WARNING` when `history_details` is missing or empty so failures are observable, even if silent fallback is intentionally retained.

---

### 5c — X-coordinate centering uses left-edge mean, not visual-center mean
**Module:** `graph_layout.py`  
**Description:** When centering a rank's nodes over their children/parents, the centering formula averages `x` positions which represent left edges of variable-width nodes. This biases wider nodes toward the left.  
**Fix:** Use `x + width / 2` (visual center) for each node when computing the mean, then convert back to left-edge `x` for placement.

---

### 5d — Dummy node detection by string prefix, not set membership
**Module:** `graph_layout.py`  
**Description:** Dummy nodes introduced during edge routing are identified by checking whether a node ID starts with a string prefix (e.g. `"__dummy__"`). This is a fragile string convention; a real file path starting with that prefix would be misidentified.  
**Fix:** Maintain a `set` of dummy node IDs created during edge routing. Use `node_id in dummy_nodes` for all subsequent checks.

---

### 6b — Unbounded cache growth
**Module:** `cache.py`  
**Description:** `LineageCache` accumulates entries indefinitely. In a long QGIS session with many files opened, memory consumption grows without bound.  
**Fix:** Add an LRU eviction policy with a configurable maximum entry count (default: 256). Use `collections.OrderedDict` or `functools.lru_cache` semantics.

---

## Retracted / Dropped

| Issue | Reason |
|-------|--------|
| 4a (double-recording via dual hooks) | Retracted — `_install_dialog_hook` docstring explicitly states the QGIS toolbox does NOT call `processing.run()`; the two hooks are mutually exclusive execution paths. |
| 1c (non-registered table inclusion) | Dropped by design — only `gpkg_contents`-registered tables are intentionally hashed. |
