"""Regression tests for the fixes from docs/code-review-2026-09.md.

Each test class is named after the review finding it guards.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from GeoLineage.lineage_core import hooks
from GeoLineage.lineage_core.checksum import compute_checksum
from GeoLineage.lineage_core.db import connect
from GeoLineage.lineage_core.memory_buffer import MemoryBuffer
from GeoLineage.lineage_core.recorder import _tool_name, record_processing
from GeoLineage.lineage_core.schema import read_lineage_rows
from GeoLineage.lineage_retrieval.graph_builder import LineageEdge, LineageGraph, LineageNode, build_graph
from GeoLineage.lineage_retrieval.path_resolver import extract_gpkg_path, is_gpkg_filename
from GeoLineage.lineage_viewer.graph_layout import _break_cycles, compute_layout


def _node(path: str, depth: int = 0) -> LineageNode:
    return LineageNode(
        path=path, status="present", entries=(), filename=os.path.basename(path), depth=depth, truncated=False
    )


class _FakeSignal:
    def __init__(self) -> None:
        self.slots: list = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def disconnect(self, slot) -> None:
        self.slots.remove(slot)


# --- C1: checksum robustness -------------------------------------------------


class TestC1ChecksumRobustness:
    def test_table_name_with_double_quote(self, empty_gpkg):
        with sqlite3.connect(str(empty_gpkg)) as conn:
            conn.execute('CREATE TABLE "we""ird" (id INTEGER PRIMARY KEY, v TEXT)')
            conn.execute('INSERT INTO "we""ird" VALUES (1, \'x\')')
            conn.execute(
                "INSERT INTO gpkg_contents (table_name, data_type, srs_id) VALUES ('we\"ird', 'attributes', 4326)"
            )
        assert len(compute_checksum(str(empty_gpkg))) == 64

    def test_stale_gpkg_contents_row_is_skipped(self, tmp_gpkg):
        before = compute_checksum(str(tmp_gpkg))
        with sqlite3.connect(str(tmp_gpkg)) as conn:
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, srs_id) VALUES ('ghost', 'features', 4326)")
        assert compute_checksum(str(tmp_gpkg)) == before

    def test_lineage_rows_survive_checksum_failure(self, tmp_gpkg):
        """A table that makes the checksum fail must not hide the file's history."""
        record_processing(str(tmp_gpkg), "pts", "native:buffer", {}, [], [], {})
        with sqlite3.connect(str(tmp_gpkg)) as conn:
            # A view registered in gpkg_contents whose SELECT fails at query time.
            conn.execute("CREATE VIEW broken AS SELECT * FROM does_not_exist")
            conn.execute(
                "INSERT INTO gpkg_contents (table_name, data_type, srs_id) VALUES ('broken', 'features', 4326)"
            )
        graph = build_graph(str(tmp_gpkg), str(tmp_gpkg.parent))
        node = graph.nodes[os.path.abspath(str(tmp_gpkg))]
        assert node.status == "present"
        assert len(node.entries) == 1

    def test_non_sqlite_parent_is_raw_input(self, tmp_gpkg, tmp_path):
        shp = tmp_path / "roads.shp"
        shp.write_bytes(b"not a database at all")
        record_processing(str(tmp_gpkg), "pts", "native:buffer", {}, [str(shp)], [], {})
        graph = build_graph(str(tmp_gpkg), str(tmp_path))
        assert graph.nodes[str(shp)].status == "raw_input"


# --- C2: connections are closed ----------------------------------------------


class TestC2ConnectionsClosed:
    def test_connect_helper_closes(self, tmp_gpkg):
        with connect(str(tmp_gpkg)) as conn:
            conn.execute("SELECT 1")
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_connect_helper_commits(self, tmp_gpkg):
        with connect(str(tmp_gpkg)) as conn:
            conn.execute("INSERT INTO test_points (id, name) VALUES (4, 'Delta')")
        with sqlite3.connect(str(tmp_gpkg)) as check:
            assert check.execute("SELECT COUNT(*) FROM test_points").fetchone()[0] == 4

    def test_read_lineage_rows_does_not_leak_connection(self, tmp_gpkg):
        import gc

        record_processing(str(tmp_gpkg), "pts", "native:buffer", {}, [], [], {})
        gc.collect()
        before = sum(1 for o in gc.get_objects() if isinstance(o, sqlite3.Connection))
        read_lineage_rows(str(tmp_gpkg))
        after = sum(1 for o in gc.get_objects() if isinstance(o, sqlite3.Connection))
        assert after == before


# --- C4: case-insensitive GeoPackage detection --------------------------------


class TestC4CaseInsensitiveExtension:
    def test_uppercase_extension(self):
        assert extract_gpkg_path("/data/ROADS.GPKG|layername=roads") == "/data/ROADS.GPKG"
        assert is_gpkg_filename("x.Gpkg")
        assert not is_gpkg_filename("x.shp")
        assert not is_gpkg_filename(None)

    def test_list_gpkg_files_is_case_insensitive(self, tmp_path):
        from GeoLineage.lineage_manager.data_ops import list_gpkg_files

        (tmp_path / "a.gpkg").write_bytes(b"")
        (tmp_path / "B.GPKG").write_bytes(b"")
        (tmp_path / "c.shp").write_bytes(b"")
        assert [os.path.basename(p) for p in list_gpkg_files(str(tmp_path))] == ["B.GPKG", "a.gpkg"]


# --- C5: memory buffer bookkeeping --------------------------------------------


class TestC5MemoryBufferCleanup:
    def test_cleanup_chain_leaves_no_empty_links(self):
        mb = MemoryBuffer()
        mb.add("A", {"layer_name": "a"})
        mb.add("B", {"layer_name": "b"})
        mb.link("B", ["A"])
        mb.link("C", ["B"])
        mb._cleanup_chain("B")
        assert mb._links == {}
        assert mb._entries == {}
        assert mb.get_chain("C") == []


# --- H3: flush buffered chains when the output is a path string ---------------


class _MemoryLayer:
    def __init__(self, layer_id: str) -> None:
        self._id = layer_id

    def id(self) -> str:
        return self._id

    def source(self) -> str:
        return "memory?geometry=Point&crs=EPSG:4326"

    def name(self) -> str:
        return self._id


class TestH3FlushOnPathOutput:
    def test_chain_flushed_when_output_is_string_path(self, tmp_path, monkeypatch):
        from GeoLineage.lineage_core import checksum, memory_buffer, recorder

        calls: list[dict] = []
        monkeypatch.setattr(recorder, "record_processing", lambda **kw: calls.append(kw))
        # memory_buffer imported record_processing by name; patch it there too
        monkeypatch.setattr(memory_buffer, "record_processing", lambda **kw: calls.append(kw))
        monkeypatch.setattr(checksum, "compute_checksum", lambda path: "fake")

        buffer = hooks.get_memory_buffer()
        buffer.add("mem_buffer", {"layer_name": "buffered", "tool": "native:buffer", "parents": ["/raw.gpkg"]})

        output_gpkg = tmp_path / "final.gpkg"
        output_gpkg.write_bytes(b"dummy")
        result = {"OUTPUT": f"{output_gpkg}|layername=final"}
        params = {"INPUT": _MemoryLayer("mem_buffer"), "OUTPUT": str(output_gpkg)}

        hooks._record_processing_lineage("native:savefeatures", params, result)

        tools = [c["tool"] for c in calls]
        assert tools == ["native:savefeatures", "native:buffer"], tools
        assert calls[0]["layer_name"] == "final"  # H5: table name, not file name
        assert calls[1]["gpkg_path"] == str(output_gpkg)
        assert buffer.get_chain("mem_buffer") == []


# --- H5: layer name from the output URI ---------------------------------------


class TestH5LayerNameFromUri:
    def test_layername_parsed(self):
        assert hooks._layername_from_uri("/x/out.gpkg|layername=buffered") == "buffered"
        assert hooks._layername_from_uri("/x/out.gpkg|LAYERNAME=b|subset=id>1") == "b"
        assert hooks._layername_from_uri("/x/out.gpkg") is None
        assert hooks._layername_from_uri(None) is None

    def test_output_layer_info_prefers_layername(self):
        _, gpkg_path, layer_name = hooks._get_output_layer_info({"OUTPUT": "/x/out.gpkg|layername=buffered"}, {})
        assert gpkg_path == "/x/out.gpkg"
        assert layer_name == "buffered"

    def test_output_layer_info_falls_back_to_basename(self):
        _, _, layer_name = hooks._get_output_layer_info({"OUTPUT": "/x/out.gpkg"}, {})
        assert layer_name == "out"


# --- H6: feature source definitions -------------------------------------------


class _Property:
    def __init__(self, value: str) -> None:
        self._value = value

    def staticValue(self) -> str:  # noqa: N802 - mirrors QgsProperty
        return self._value


class _FeatureSourceDefinition:
    """Mimics QgsProcessingFeatureSourceDefinition: .source is a property, not a method."""

    def __init__(self, value: str) -> None:
        self.source = _Property(value)
        self.selectedFeaturesOnly = True


class TestH6FeatureSourceDefinition:
    def test_object_form(self):
        assert hooks._resolve_output_layer_definition(_FeatureSourceDefinition("/a.gpkg|layername=x")) == (
            "/a.gpkg|layername=x"
        )

    def test_dict_form(self):
        value = {"source": "/a.gpkg", "selectedFeaturesOnly": True}
        assert hooks._resolve_output_layer_definition(value) == "/a.gpkg"

    def test_layer_objects_untouched(self):
        layer = _MemoryLayer("mem")
        assert hooks._resolve_output_layer_definition(layer) is layer

    def test_parent_recorded_for_selected_features_input(self, tmp_path, monkeypatch):
        from GeoLineage.lineage_core import checksum, recorder

        captured: dict = {}
        monkeypatch.setattr(recorder, "record_processing", lambda **kw: captured.update(kw))
        monkeypatch.setattr(checksum, "compute_checksum", lambda path: "fake")

        input_gpkg = tmp_path / "input.gpkg"
        input_gpkg.write_bytes(b"dummy")
        output_gpkg = tmp_path / "output.gpkg"
        output_gpkg.write_bytes(b"dummy")
        params = {"INPUT": _FeatureSourceDefinition(f"{input_gpkg}|layername=pts")}
        hooks._record_processing_lineage("native:buffer", params, {"OUTPUT": str(output_gpkg)})
        assert captured["parents"] == [str(input_gpkg)]


# --- H4: registry keys are merged with the fallback list ----------------------


class TestH4InputKeys:
    def test_fallback_keys_always_present(self):
        keys = hooks._input_keys_for("native:buffer")
        for key in hooks._FALLBACK_INPUT_KEYS:
            assert key in keys

    def test_registry_keys_come_first(self, monkeypatch):
        monkeypatch.setattr(hooks, "_get_input_keys", lambda name: ("INPUT_2", "INPUT"))
        keys = hooks._input_keys_for("native:joinattributestable")
        assert keys[:2] == ("INPUT_2", "INPUT")
        assert keys.count("INPUT") == 1

    def test_non_string_algorithm_uses_fallback(self):
        assert hooks._input_keys_for(object()) == hooks._FALLBACK_INPUT_KEYS


# --- H7: algorithm objects ----------------------------------------------------


class _Algorithm:
    def id(self) -> str:
        return "native:buffer"


class TestH7AlgorithmObjects:
    def test_algorithm_id_helper(self):
        assert hooks._algorithm_id("native:buffer") == "native:buffer"
        assert hooks._algorithm_id(_Algorithm()) == "native:buffer"

    def test_recorder_accepts_algorithm_object(self, tmp_gpkg):
        assert _tool_name(_Algorithm()) == "native:buffer"
        row_id = record_processing(str(tmp_gpkg), "pts", _Algorithm(), {}, [], [], {})
        rows = read_lineage_rows(str(tmp_gpkg))
        assert rows[0]["id"] == row_id
        assert rows[0]["operation_tool"] == "native:buffer"
        assert rows[0]["operation_summary"] == "buffer"


# --- H1: GUI exports through layerSavedAs -------------------------------------


class _FileLayer:
    def __init__(self, path: str, name: str = "roads") -> None:
        self._path = path
        self._name = name

    def id(self) -> str:
        return "layer_id"

    def source(self) -> str:
        return f"{self._path}|layername={self._name}"

    def name(self) -> str:
        return self._name


class TestH1LayerSavedAs:
    def test_install_connects_and_uninstall_disconnects(self, monkeypatch):
        class _Iface:
            layerSavedAs = _FakeSignal()

        iface = _Iface()
        hooks._install_layer_saved_as_hook(iface)
        assert iface.layerSavedAs.slots == [hooks._on_layer_saved_as]
        hooks._uninstall_layer_saved_as_hook()
        assert iface.layerSavedAs.slots == []
        assert hooks._hook_state["iface"] is None

    def test_install_without_iface_is_safe(self):
        hooks._install_layer_saved_as_hook(None)
        hooks._uninstall_layer_saved_as_hook()

    def test_saved_as_records_export(self, tmp_gpkg, tmp_path, monkeypatch):
        from GeoLineage.lineage_core import recorder

        captured: dict = {}
        monkeypatch.setattr(recorder, "record_export", lambda **kw: captured.update(kw))

        target = tmp_path / "copy.gpkg"
        hooks._on_layer_saved_as(_FileLayer(str(tmp_gpkg)), str(target))

        assert captured["gpkg_path"] == str(target)
        assert captured["parent_path"] == str(tmp_gpkg)
        assert captured["layer_name"] == "roads"
        assert str(tmp_gpkg) in captured["parent_checksums"]

    def test_saved_as_ignores_non_gpkg_target(self, tmp_gpkg, tmp_path, monkeypatch):
        from GeoLineage.lineage_core import recorder

        called = []
        monkeypatch.setattr(recorder, "record_export", lambda **kw: called.append(kw))
        hooks._on_layer_saved_as(_FileLayer(str(tmp_gpkg)), str(tmp_path / "copy.shp"))
        assert called == []


# --- H8: edit-connection pruning -----------------------------------------------


class TestH8EditConnectionPruning:
    def test_layers_will_be_removed_prunes_state(self):
        calls = []
        hooks._hook_state["_layer_edit_connections"] = {"L1": lambda: calls.append("L1")}
        with hooks._edit_snapshots_lock:
            hooks._pending_edit_snapshots["L1"] = {"features_added": 1}

        hooks._on_layers_will_be_removed(["L1", "unknown"])

        assert calls == ["L1"]
        assert hooks._hook_state["_layer_edit_connections"] == {}
        assert "L1" not in hooks._pending_edit_snapshots


# --- V1: self-referential lineage --------------------------------------------


class TestV1SelfLoops:
    def test_build_graph_skips_self_edge(self, tmp_gpkg):
        path = str(tmp_gpkg)
        record_processing(path, "buffered", "native:buffer", {}, [path], [], {path: compute_checksum(path)})
        graph = build_graph(path, str(tmp_gpkg.parent))
        assert graph.edges == ()
        assert len(graph.nodes) == 1
        assert graph.nodes[os.path.abspath(path)].status == "present"

    def test_break_cycles_drops_self_loops(self):
        children = {"a": ["a", "b"], "b": []}
        parents = {"a": ["a"], "b": ["a"]}
        ac, ap, reversed_edges = _break_cycles(children, parents)
        assert ac == {"a": ["b"], "b": []}
        assert ap == {"a": [], "b": ["a"]}
        assert reversed_edges == set()

    def test_layout_ranks_with_self_loop_edge(self):
        graph = LineageGraph(
            nodes={
                "/raw.gpkg": _node("/raw.gpkg", 2),
                "/a.gpkg": _node("/a.gpkg", 1),
                "/child.gpkg": _node("/child.gpkg"),
            },
            edges=(
                LineageEdge("/a.gpkg", "/a.gpkg", 1),
                LineageEdge("/raw.gpkg", "/a.gpkg", 2),
                LineageEdge("/a.gpkg", "/child.gpkg", 3),
            ),
            root_path="/child.gpkg",
        )
        result = compute_layout(graph)
        ranks = {path: pos.layer for path, pos in result.node_positions.items()}
        assert ranks == {"/raw.gpkg": 0, "/a.gpkg": 1, "/child.gpkg": 2}
        assert [(e.source, e.target) for e in result.edge_paths] == [
            ("/raw.gpkg", "/a.gpkg"),
            ("/a.gpkg", "/child.gpkg"),
        ]
        assert [e.entry_id for e in result.edge_paths] == [2, 3]


# --- data_ops hardening --------------------------------------------------------


class TestDataOpsHardening:
    def test_batch_relink_prefix_tolerates_non_string_parents(self, tmp_gpkg):
        from GeoLineage.lineage_manager.data_ops import batch_relink_prefix

        record_processing(str(tmp_gpkg), "pts", "t", {}, ["/old/a.gpkg"], [], {})
        with sqlite3.connect(str(tmp_gpkg)) as conn:
            conn.execute("UPDATE _lineage SET parent_files = '[\"/old/a.gpkg\", 42, null]'")
        assert batch_relink_prefix(str(tmp_gpkg), "/old", "/new") == 1
        rows = read_lineage_rows(str(tmp_gpkg))
        assert rows[0]["parent_files"] == '["/new/a.gpkg", 42, null]'
