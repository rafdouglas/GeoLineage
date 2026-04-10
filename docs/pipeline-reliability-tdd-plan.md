# GeoLineage Pipeline Reliability — TDD Implementation Plan

**Companion document:** `docs/pipeline-reliability-findings.md`  
**Execution:** Run this plan sequentially in a fresh session. Each step is self-contained.  
**Test runner:** `pytest tests/<file> -k <test_name> -v`  
**Full suite:** `pytest --cov=GeoLineage/lineage_core --cov-report=term-missing`

---

## How to use this plan

For each step:
1. Write the test listed under **RED** — run it and confirm it fails.
2. Apply the minimal code change described under **GREEN**.
3. Run the verification command — confirm it passes.
4. Move to the next step.

Do not skip ahead. Each step's GREEN change is sized to avoid breaking existing tests.

---

## Step 1 — Checksum: value-length delimiter (HIGH 1a)

**File:** `tests/test_checksum.py`  
**Existing helpers:** `_make_gpkg(path)`, `_register_table(conn, table_name)`

### RED — write this test

```python
def test_value_length_delimiter_prevents_collision(tmp_path):
    """("ab","c") and ("a","bc") must hash differently."""
    db1 = tmp_path / "a.gpkg"
    db2 = tmp_path / "b.gpkg"

    conn1 = _make_gpkg(db1)
    _register_table(conn1, "data")
    conn1.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, col1 TEXT, col2 TEXT)")
    conn1.execute("INSERT INTO data VALUES (1, 'ab', 'c')")
    conn1.commit(); conn1.close()

    conn2 = _make_gpkg(db2)
    _register_table(conn2, "data")
    conn2.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, col1 TEXT, col2 TEXT)")
    conn2.execute("INSERT INTO data VALUES (1, 'a', 'bc')")
    conn2.commit(); conn2.close()

    assert compute_checksum(db1) != compute_checksum(db2)
```

**Expected failure:** Both checksums are equal because column values are concatenated without a length prefix.

### GREEN — minimal code change in `lineage_core/checksum.py`

In the row-serialization loop, prefix each column value's byte representation with its 4-byte little-endian length before appending to the hash:

```python
# Before (approximate):
h.update(value_bytes)

# After:
h.update(len(value_bytes).to_bytes(4, "little"))
h.update(value_bytes)
```

Apply this to every column value in the serialization path, preserving the existing type-tag byte that precedes the value.

**Verify:** `pytest tests/test_checksum.py -v`  
All existing checksum tests must still pass (they test for consistency and inequality, not specific digest values — recomputed digests remain self-consistent after the fix).

---

## Step 2 — Checksum: primary-key row ordering (MEDIUM 1b)

**File:** `tests/test_checksum.py`

### RED — write this test

```python
def test_rowid_vacuum_stability(tmp_path):
    """Checksum must be identical before and after VACUUM."""
    db = tmp_path / "v.gpkg"
    conn = _make_gpkg(db)
    _register_table(conn, "data")
    conn.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO data VALUES (1, 'alpha')")
    conn.execute("INSERT INTO data VALUES (2, 'beta')")
    conn.commit()
    checksum_before = compute_checksum(db)
    conn.execute("VACUUM")
    conn.commit(); conn.close()
    assert compute_checksum(db) == checksum_before
```

**Expected failure (current behaviour):** Passes trivially today on most machines because `VACUUM` rarely reorders rowids in a fresh DB. To surface the bug reliably, also add:

```python
def test_row_order_by_pk_not_rowid(tmp_path):
    """Inserting rows out of PK order must hash the same as in-order insertion."""
    db1 = tmp_path / "ordered.gpkg"
    db2 = tmp_path / "unordered.gpkg"

    for db, rows in [(db1, [(1,'x'),(2,'y')]), (db2, [(2,'y'),(1,'x')])]:
        conn = _make_gpkg(db)
        _register_table(conn, "data")
        conn.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, val TEXT)")
        for row in rows:
            conn.execute("INSERT INTO data VALUES (?, ?)", row)
        conn.commit(); conn.close()

    assert compute_checksum(db1) == compute_checksum(db2)
```

**Expected failure:** The two checksums differ because rows are fetched `ORDER BY rowid` which preserves insertion order.

### GREEN — minimal code change in `lineage_core/checksum.py`

Replace the fixed `ORDER BY rowid ASC` with a dynamic primary-key query:

```python
pk_cols = [
    row[1]
    for row in conn.execute(f"PRAGMA table_info('{table}')")
    if row[5] > 0  # pk column index > 0 means it's part of the PK
]
order_clause = ", ".join(pk_cols) if pk_cols else "rowid"
cursor = conn.execute(f"SELECT * FROM \"{table}\" ORDER BY {order_clause} ASC")
```

**Migration note:** Add a comment in `checksum.py` that checksums computed before this change are incompatible. Existing stored checksums in GeoPackages will need to be recomputed (one-time migration).

**Verify:** `pytest tests/test_checksum.py -v`

---

## Step 3 — MemoryBuffer: flush atomicity (HIGH 3a)

**File:** `tests/test_memory_buffer.py`  
**Existing helpers:** `_make_gpkg(path)`, `_make_entry(layer_name, tool)`

### RED — write this test

```python
def test_flush_does_not_cleanup_on_record_failure(tmp_path):
    """If record_processing raises, the chain must survive in the buffer."""
    buf = MemoryBuffer()
    a_id = "layer_a"
    b_id = "layer_b"
    buf.add(a_id, _make_entry("a", "native:buffer"))
    buf.add(b_id, _make_entry("b", "native:clip"))
    buf.link(b_id, a_id)

    # Patch record_processing to simulate a write failure
    def failing_record(*args, **kwargs):
        raise IOError("simulated disk error")

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(buf, "record_processing", failing_record)
        with pytest.raises(IOError):
            buf.flush(b_id, output_path=tmp_path / "out.gpkg")

    # Chain must still be in the buffer
    assert buf.get(b_id) is not None
    assert buf.get(a_id) is not None
```

**Expected failure:** After the IOError, `b_id` and `a_id` are gone because `_cleanup_chain` ran unconditionally.

### GREEN — minimal code change in `lineage_core/memory_buffer.py`

Wrap the flush body:

```python
def flush(self, layer_id, output_path):
    try:
        self.record_processing(layer_id, output_path)
    except Exception:
        raise  # do NOT cleanup — leave chain intact for retry
    self._cleanup_chain(layer_id)
```

**Verify:** `pytest tests/test_memory_buffer.py -v`

---

## Step 4 — MemoryBuffer: dangling back-references after cleanup (MEDIUM 3b)

**File:** `tests/test_memory_buffer.py`

### RED — write this test

```python
def test_cleanup_removes_back_references_from_links(tmp_path):
    """After flushing child B, parent A must not appear as a dangling link target."""
    buf = MemoryBuffer()
    a_id = "layer_a"
    b_id = "layer_b"
    c_id = "layer_c"
    buf.add(a_id, _make_entry("a", "native:buffer"))
    buf.add(b_id, _make_entry("b", "native:clip"))
    buf.add(c_id, _make_entry("c", "native:dissolve"))
    buf.link(b_id, a_id)
    buf.link(c_id, b_id)

    # Flush c's chain (c -> b -> a)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(buf, "record_processing", lambda *a, **k: None)
        buf.flush(c_id, output_path=tmp_path / "out.gpkg")

    # _links must not contain references to cleaned-up IDs
    for parents in buf._links.values():
        assert a_id not in parents
        assert b_id not in parents
```

**Expected failure:** Stale references to `a_id` or `b_id` remain in `_links`.

### GREEN — minimal code change in `lineage_core/memory_buffer.py`

In `_cleanup_chain`, after removing a layer from `_layers`, also remove it from all value sets in `_links`:

```python
def _cleanup_chain(self, layer_id):
    for lid in self._collect_chain(layer_id):  # or however traversal is done
        self._layers.pop(lid, None)
        # Remove as a parent reference from any remaining links
        for parents in self._links.values():
            parents.discard(lid)  # assuming parents is a set; use .remove() with guard if list
        self._links.pop(lid, None)
```

**Verify:** `pytest tests/test_memory_buffer.py -v`

---

## Step 5 — GraphBuilder: `expected_checksums` any-mismatch flagging (HIGH 2a)

**File:** `tests/test_graph_builder.py`  
**Existing helpers:** `_init_gpkg`, `_make_gpkg`, `_link_parent(child_path, parent_path, tool)`

### RED — write this test

Add to `TestNodeStatus` (or a new `TestExpectedChecksums` class):

```python
def test_later_child_mismatch_flags_parent_modified(self, tmp_path):
    """
    parent.gpkg is recorded by child_a (correct expectation),
    then parent.gpkg is modified,
    then child_b records it (stale expectation pointing to old checksum).
    The graph must flag parent as modified because child_b's expectation disagrees.
    """
    parent = tmp_path / "parent.gpkg"
    child_a = tmp_path / "child_a.gpkg"
    child_b = tmp_path / "child_b.gpkg"

    _make_gpkg(parent)
    _link_parent(child_a, parent, "tool_a")  # records correct checksum of parent v1
    # Mutate parent (simulate data change)
    _modify_gpkg_data(parent)               # helper to change a row — add if not present
    _link_parent(child_b, parent, "tool_b") # records parent v2 checksum

    graph = build_graph(child_b)            # adjust to match actual API
    parent_node = graph.nodes[str(parent.resolve())]
    assert parent_node.status == "modified"
```

You will need a small `_modify_gpkg_data(path)` helper that opens the GeoPackage and updates a cell value to change its checksum.

**Expected failure:** The node is `ok` because the first child's expectation wins and matches the *original* checksum stored in child_a's lineage record.

### GREEN — minimal code change in `lineage_core/graph_builder.py`

When merging `expected_checksums` across children during BFS:

```python
# Instead of first-write-wins:
# if parent_path not in expected_checksums:
#     expected_checksums[parent_path] = child_expectation

# Use: flag modified if any child disagrees
if parent_path in expected_checksums:
    if expected_checksums[parent_path] != child_expectation:
        # Mark as modified regardless of which checksum is "current"
        force_modified.add(parent_path)
else:
    expected_checksums[parent_path] = child_expectation
```

Then when computing node status, `force_modified` membership takes precedence over the checksum comparison.

**Verify:** `pytest tests/test_graph_builder.py -v`

---

## Step 6 — GraphLayout: iterative cycle-breaking (MEDIUM 5a)

**File:** `tests/test_graph_layout.py`  
**Existing helpers:** `_make_node`, `_make_graph`

### RED — write this test

```python
def test_break_cycles_deep_chain_no_recursion_error(self):
    """A linear chain of 1100 nodes must not raise RecursionError."""
    import sys
    depth = sys.getrecursionlimit() + 100  # exceed default limit
    nodes = {str(i): _make_node(str(i), i, "ok", str(i)) for i in range(depth)}
    edges = [(str(i), str(i + 1)) for i in range(depth - 1)]
    graph = _make_graph(nodes, edges, root_path="0")
    # Must complete without RecursionError
    result = compute_layout(graph)
    assert result is not None
```

**Expected failure:** `RecursionError: maximum recursion depth exceeded`

### GREEN — minimal code change in `lineage_core/graph_layout.py`

Convert `_break_cycles` from recursive DFS to iterative DFS:

```python
def _break_cycles(graph):
    visited = set()
    in_stack = set()
    edges_to_remove = []

    for start in graph.nodes:
        if start in visited:
            continue
        stack = [(start, iter(graph.successors(start)))]
        in_stack.add(start)
        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
                if child in in_stack:
                    edges_to_remove.append((node, child))
                elif child not in visited:
                    in_stack.add(child)
                    stack.append((child, iter(graph.successors(child))))
            except StopIteration:
                in_stack.discard(node)
                visited.add(node)
                stack.pop()

    for u, v in edges_to_remove:
        graph.remove_edge(u, v)
```

**Verify:** `pytest tests/test_graph_layout.py -v`

---

## Step 7 — GraphLayout: O(n³) → O(n²) crossing minimisation (MEDIUM 5b)

**File:** `tests/test_graph_layout.py`

### RED — write this test

Add to `TestPerformance` (the existing `test_50_node_graph_under_one_second` already exists; add a larger-graph variant):

```python
def test_200_node_graph_under_two_seconds(self):
    """Crossing minimisation must complete in under 2 s for 200 nodes."""
    import time
    nodes = {str(i): _make_node(str(i), i % 10, "ok", str(i)) for i in range(200)}
    edges = [(str(i), str(i + 1)) for i in range(199)]
    graph = _make_graph(nodes, edges, root_path="0")
    start = time.monotonic()
    compute_layout(graph)
    assert time.monotonic() - start < 2.0
```

**Expected failure:** Times out (>2 s) due to O(n³) `sorted_ranks.index()` scan.

### GREEN — minimal code change in `lineage_core/graph_layout.py`

Before the barycenter sweep loop, pre-build a position index:

```python
# Before the sweep:
rank_index = {node: idx for idx, node in enumerate(sorted_ranks)}

# Inside the loop, replace:
#   pos = sorted_ranks.index(node)   ← O(n)
# with:
#   pos = rank_index[node]            ← O(1)
```

Update `rank_index` whenever `sorted_ranks` is mutated (reorder step).

**Verify:** `pytest tests/test_graph_layout.py::TestPerformance -v`

---

## Step 8 — Cache: sub-second mtime precision (MEDIUM 6a)

**File:** `tests/test_cache.py`

### RED — write this test

```python
def test_sub_second_mtime_change_detected(tmp_path):
    """A file modified within the same second must be detected as stale."""
    f = tmp_path / "layer.gpkg"
    f.write_bytes(b"v1")
    cache = LineageCache()
    cache.get(f)  # populate cache

    # Simulate sub-second modification by bumping mtime by 0.5 s
    stat = f.stat()
    new_ns = stat.st_mtime_ns + 500_000_000  # +0.5 s in nanoseconds
    os.utime(f, ns=(stat.st_atime_ns, new_ns))

    assert cache.is_stale(f)
```

**Expected failure:** `is_stale` returns `False` because float comparison loses the sub-second delta.

### GREEN — minimal code change in `lineage_core/cache.py`

Replace `os.path.getmtime()` with `os.stat().st_mtime_ns` everywhere in `LineageCache`:

```python
# Store:
self._cache[path] = (data, os.stat(path).st_mtime_ns)

# Check:
return os.stat(path).st_mtime_ns != cached_mtime_ns
```

**Verify:** `pytest tests/test_cache.py -v`

---

## Step 9 — Cache: LRU eviction (LOW 6b)

**File:** `tests/test_cache.py`

### RED — write this test

```python
def test_cache_evicts_oldest_entry_at_capacity(tmp_path):
    """Cache must not grow beyond its configured max size."""
    max_size = 4
    cache = LineageCache(max_size=max_size)
    files = []
    for i in range(max_size + 2):
        f = tmp_path / f"layer_{i}.gpkg"
        f.write_bytes(f"v{i}".encode())
        files.append(f)
        cache.get(f)

    assert len(cache) <= max_size
```

**Expected failure:** `len(cache)` is `max_size + 2` — no eviction.

### GREEN — minimal code change in `lineage_core/cache.py`

Replace the internal `dict` with `collections.OrderedDict` and add eviction on insert:

```python
from collections import OrderedDict

class LineageCache:
    def __init__(self, max_size=256):
        self._max_size = max_size
        self._cache = OrderedDict()

    def _insert(self, key, value):
        self._cache[key] = value
        self._cache.move_to_end(key)
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)  # evict LRU
```

**Verify:** `pytest tests/test_cache.py -v`

---

## Step 10 — Hooks: thread-safe `_pending_edit_snapshots` (MEDIUM 4c)

**File:** `tests/test_hooks.py` (create if it does not exist)

### RED — write this test

```python
import threading
from unittest.mock import patch
from GeoLineage.lineage_core import hooks

def test_pending_edit_snapshots_thread_safe():
    """Concurrent writes to _pending_edit_snapshots must not raise or corrupt state."""
    errors = []

    def writer(layer_id):
        try:
            for _ in range(1000):
                hooks._pending_edit_snapshots[layer_id] = {"col": 1}
                _ = hooks._pending_edit_snapshots.get(layer_id)
                hooks._pending_edit_snapshots.pop(layer_id, None)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(f"layer_{i}",)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread safety errors: {errors}"
```

**Expected failure:** May raise `RuntimeError: dictionary changed size during iteration` or silently corrupt state (non-deterministic — run multiple times).

### GREEN — minimal code change in `lineage_core/hooks.py`

Add a module-level lock and wrap all access:

```python
import threading
_pending_edit_snapshots: dict[str, dict[str, int]] = {}
_edit_snapshots_lock = threading.Lock()

# All reads/writes:
with _edit_snapshots_lock:
    _pending_edit_snapshots[layer_id] = snapshot
```

**Verify:** `pytest tests/test_hooks.py::test_pending_edit_snapshots_thread_safe -v`  
Run the test 10 times to confirm stability: `pytest tests/test_hooks.py::test_pending_edit_snapshots_thread_safe -v --count=10` (requires `pytest-repeat`).

---

## Step 11 — Hooks: log warning when `history_details` absent (LOW 4a-new)

**File:** `tests/test_hooks.py`

### RED — write this test

```python
import logging

def test_dialog_hook_warns_when_history_details_missing(caplog):
    """Missing history_details must emit a WARNING, not silently drop parents."""
    from GeoLineage.lineage_core.hooks import _extract_dialog_parameters

    class FakeDialog:
        pass  # no history_details attribute

    with caplog.at_level(logging.WARNING, logger="GeoLineage"):
        params = _extract_dialog_parameters(FakeDialog())

    assert params == {}
    assert any("history_details" in r.message for r in caplog.records)
```

Adjust the import path and function name to match the actual internal helper extracted from `_install_dialog_hook`.

**Expected failure:** No warning is emitted.

### GREEN — minimal code change in `lineage_core/hooks.py`

In the dialog hook where `history_details` is read, add:

```python
history_details = getattr(dialog_self, "history_details", None)
if not history_details:
    logger.warning(
        "GeoLineage dialog hook: history_details missing on %s — "
        "parent tracking will be empty for this algorithm run.",
        type(dialog_self).__name__,
    )
    return {}
params = history_details.get("parameters", {})
```

**Verify:** `pytest tests/test_hooks.py -v`

---

## Step 12 — Hooks: dynamic input-key discovery (MEDIUM 4b)

**Note:** This step requires a QGIS runtime. If running outside QGIS, mock `QgsApplication.processingRegistry()`.

**File:** `tests/test_hooks.py`

### RED — write this test

```python
def test_get_input_keys_uses_algorithm_definitions():
    """_get_input_keys must return keys derived from parameterDefinitions, not a hardcoded list."""
    # Mock an algorithm with one VectorLayer input named "CUSTOM_INPUT"
    from unittest.mock import MagicMock
    mock_param = MagicMock()
    mock_param.name.return_value = "CUSTOM_INPUT"
    mock_param.__class__.__name__ = "QgsProcessingParameterVectorLayer"

    mock_alg = MagicMock()
    mock_alg.parameterDefinitions.return_value = [mock_param]

    with patch("GeoLineage.lineage_core.hooks.QgsApplication") as mock_app:
        mock_app.processingRegistry.return_value.algorithmById.return_value = mock_alg
        from GeoLineage.lineage_core.hooks import _get_input_keys
        keys = _get_input_keys("some:algorithm")

    assert "CUSTOM_INPUT" in keys
```

**Expected failure:** `_get_input_keys` does not exist yet (hardcoded tuple is used inline).

### GREEN — minimal code change in `lineage_core/hooks.py`

1. Extract the hardcoded tuple into a fallback constant:
   ```python
   _FALLBACK_INPUT_KEYS = ("INPUT", "INPUT_LAYER", "LAYERS", "INPUT1", "INPUT2", "OVERLAY", "LAYER", "SOURCE_LAYER")
   ```

2. Add helper:
   ```python
   def _get_input_keys(algorithm_name: str) -> tuple[str, ...]:
       _VECTOR_PARAM_TYPES = (
           "QgsProcessingParameterVectorLayer",
           "QgsProcessingParameterFeatureSource",
           "QgsProcessingParameterMultipleLayers",
       )
       try:
           alg = QgsApplication.processingRegistry().algorithmById(algorithm_name)
           if alg is None:
               return _FALLBACK_INPUT_KEYS
           return tuple(
               p.name() for p in alg.parameterDefinitions()
               if type(p).__name__ in _VECTOR_PARAM_TYPES
           ) or _FALLBACK_INPUT_KEYS
       except Exception:
           return _FALLBACK_INPUT_KEYS
   ```

3. Replace both occurrences of the hardcoded tuple (lines 117 and 265) with `_get_input_keys(algorithm_name)`.

**Verify:** `pytest tests/test_hooks.py -v`

---

## Step 13 — GraphLayout: dummy node set (LOW 5d)

**File:** `tests/test_graph_layout.py`

### RED — write this test

```python
def test_dummy_node_not_confused_with_real_node(self):
    """A real file path that starts with the dummy prefix must not be treated as a dummy node."""
    # Create a node whose path starts with whatever prefix is used for dummy nodes
    # (inspect graph_layout.py to find the actual prefix string)
    dummy_prefix = "__dummy__"  # adjust if different
    suspicious_path = dummy_prefix + "/real/file.gpkg"
    nodes = {
        "root": _make_node("root", 0, "ok", "root"),
        suspicious_path: _make_node(suspicious_path, 1, "ok", suspicious_path),
    }
    edges = [("root", suspicious_path)]
    graph = _make_graph(nodes, edges, root_path="root")
    result = compute_layout(graph)
    # The suspicious node must appear in the output positions
    assert suspicious_path in result.positions
```

**Expected failure:** `suspicious_path` is filtered out of `result.positions` because it matches the dummy prefix.

### GREEN — minimal code change in `lineage_core/graph_layout.py`

Replace all `node_id.startswith("__dummy__")` guards with `node_id in _dummy_nodes` where `_dummy_nodes` is a `set` populated only during edge routing:

```python
_dummy_nodes: set[str] = set()

# When creating a dummy node:
dummy_id = f"__dummy__{u}__{v}__{rank}"
_dummy_nodes.add(dummy_id)

# When checking:
if node_id in _dummy_nodes:  # replaces startswith check
```

**Verify:** `pytest tests/test_graph_layout.py -v`

---

## Step 14 — GraphLayout: visual-center x-coordinate (LOW 5c)

**File:** `tests/test_graph_layout.py`

### RED — write this test

```python
def test_centering_uses_visual_center_not_left_edge(self):
    """Wide parent must be centered over narrow child using visual midpoints."""
    # Parent: width=200, child: width=50
    # If centered by visual midpoint: parent.x = child.x + child.w/2 - parent.w/2
    nodes = {
        "parent": _make_node("parent", 0, "ok", "parent"),
        "child":  _make_node("child",  1, "ok", "child"),
    }
    edges = [("parent", "child")]

    # Inject custom widths via config or by patching node width computation
    graph = _make_graph(nodes, edges, root_path="parent")
    # Patch widths: parent=200, child=50
    result = compute_layout(graph, node_widths={"parent": 200, "child": 50})

    parent_center = result.positions["parent"]["x"] + 200 / 2
    child_center  = result.positions["child"]["x"]  + 50  / 2
    assert abs(parent_center - child_center) < 1.0, (
        f"Expected visual centers aligned; got parent_center={parent_center}, child_center={child_center}"
    )
```

Adjust the `compute_layout` signature to accept `node_widths` if it does not already, or use the existing config object.

**Expected failure:** `parent_center != child_center` because left-edge `x` values are averaged, not visual-center `x` values.

### GREEN — minimal code change in `lineage_core/graph_layout.py`

In the centering step, replace the left-edge mean:

```python
# Before:
mean_x = sum(positions[n]["x"] for n in ref_nodes) / len(ref_nodes)

# After:
mean_x = sum(
    positions[n]["x"] + node_widths.get(n, DEFAULT_WIDTH) / 2
    for n in ref_nodes
) / len(ref_nodes)
# Convert back to left edge:
positions[node]["x"] = mean_x - node_widths.get(node, DEFAULT_WIDTH) / 2
```

**Verify:** `pytest tests/test_graph_layout.py -v`

---

## Step 15 — GraphBuilder: minor clean-ups (LOW 2b, 2c)

These are performance improvements with no observable correctness difference; a single test suffices.

**File:** `tests/test_graph_builder.py`

### RED — write this test (integration, not unit)

```python
def test_build_graph_opens_single_connection_per_file(tmp_path, mocker):
    """graph_builder must open at most one SQLite connection per file per BFS step."""
    connect_calls = []
    original_connect = sqlite3.connect

    def counting_connect(path, *args, **kwargs):
        connect_calls.append(str(path))
        return original_connect(path, *args, **kwargs)

    parent = tmp_path / "parent.gpkg"
    child  = tmp_path / "child.gpkg"
    _make_gpkg(parent); _make_gpkg(child)
    _link_parent(child, parent, "tool")

    with mocker.patch("GeoLineage.lineage_core.graph_builder.sqlite3.connect", side_effect=counting_connect):
        build_graph(child)

    parent_opens = connect_calls.count(str(parent))
    assert parent_opens <= 1, f"parent.gpkg was opened {parent_opens} times; expected ≤1"
```

Requires `pytest-mock`.

**Expected failure:** `parent_opens == 2`.

### GREEN — minimal code change in `lineage_core/graph_builder.py`

In the BFS expansion function, open a single connection and reuse it for both the lineage-records query and the checksum query:

```python
with sqlite3.connect(str(file_path)) as conn:
    records = _read_lineage_records(conn)
    checksum = _read_stored_checksum(conn)
```

Also fix `resolve()` double-call in the same function:

```python
parent_resolved = Path(raw_parent_path).resolve()
# Use parent_resolved everywhere — do not call .resolve() again
```

**Verify:** `pytest tests/test_graph_builder.py -v`

---

## Final verification

After all steps pass individually, run the full suite:

```bash
pytest --cov=GeoLineage/lineage_core --cov-report=term-missing -v
```

Target: all tests green, coverage ≥ 80% on each modified module.
