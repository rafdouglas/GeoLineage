"""GeoLineage — QGIS plugin for GeoPackage lineage tracking."""


def classFactory(iface):
    """QGIS plugin entry point. Called by QGIS Plugin Manager."""
    from .plugin import GeoLineagePlugin
    return GeoLineagePlugin(iface)
