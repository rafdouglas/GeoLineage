"""Source-level guards for Qt5/Qt6 dual compatibility.

The official QGIS migration script (run in CI, see .github/workflows/ci.yml)
catches ``Class.Member`` enum spellings and ``exec_``. These tests cover the
patterns it cannot see and the metadata rules from
docs/qgis4-migration-strategy.md.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).parent.parent
_PACKAGES = ("plugin.py", "lineage_core", "lineage_retrieval", "lineage_viewer", "lineage_manager")


def _plugin_sources() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for name in _PACKAGES:
        path = _ROOT / name
        if path.is_file():
            files.append(path)
        else:
            files.extend(sorted(path.rglob("*.py")))
    return files


def test_no_exec_underscore():
    offenders = [p for p in _plugin_sources() if re.search(r"\.exec_\(", p.read_text())]
    assert offenders == [], f"exec_() is not available on PyQt6: {offenders}"


def test_no_unscoped_graphics_item_enums_via_self():
    """``self.ItemIsSelectable`` etc. raise AttributeError on PyQt6; use QGraphicsItem.GraphicsItemFlag.*"""
    pattern = re.compile(r"\bself\.Item[A-Z]\w*")
    offenders = [(p.name, m.group(0)) for p in _plugin_sources() for m in pattern.finditer(p.read_text())]
    assert offenders == [], offenders


def test_no_direct_pyqt_imports():
    offenders = [p for p in _plugin_sources() if re.search(r"^\s*(from|import)\s+PyQt[56]\b", p.read_text(), re.M)]
    assert offenders == [], f"import Qt through qgis.PyQt only: {offenders}"


def test_no_unscoped_qgis_layer_type():
    source = (_ROOT / "plugin.py").read_text()
    assert "QgsMapLayer.VectorLayer" not in source
    assert "QgsMapLayer.LayerType.VectorLayer" in source


def test_metadata_declares_both_major_versions():
    metadata = (_ROOT / "metadata.txt").read_text()
    assert re.search(r"^qgisMinimumVersion=3\.", metadata, re.M)
    assert re.search(r"^qgisMaximumVersion=4\.99$", metadata, re.M), (
        "a plugin supporting QGIS 3 and 4 must set qgisMaximumVersion explicitly"
    )
    assert "supportsQt6" not in metadata, "supportsQt6 is obsolete since QGIS 4.0.0"
