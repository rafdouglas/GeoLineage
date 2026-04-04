"""Tests for lineage_core.settings constants."""

import lineage_core.settings as settings


def test_schema_version_exists():
    assert hasattr(settings, "SCHEMA_VERSION")


def test_schema_version_value():
    assert settings.SCHEMA_VERSION == "1"


def test_lineage_table_exists():
    assert hasattr(settings, "LINEAGE_TABLE")


def test_lineage_table_value():
    assert settings.LINEAGE_TABLE == "_lineage"


def test_meta_table_exists():
    assert hasattr(settings, "META_TABLE")


def test_meta_table_value():
    assert settings.META_TABLE == "_lineage_meta"


def test_setting_enabled_exists():
    assert hasattr(settings, "SETTING_ENABLED")


def test_setting_enabled_value():
    assert settings.SETTING_ENABLED == "GeoLineage/enabled"


def test_setting_username_exists():
    assert hasattr(settings, "SETTING_USERNAME")


def test_setting_username_value():
    assert settings.SETTING_USERNAME == "GeoLineage/username"


def test_default_username_exists():
    assert hasattr(settings, "DEFAULT_USERNAME")


def test_default_username_is_none():
    assert settings.DEFAULT_USERNAME is None


def test_logger_name_exists():
    assert hasattr(settings, "LOGGER_NAME")


def test_logger_name_value():
    assert settings.LOGGER_NAME == "GeoLineage"


def test_all_constants_present():
    expected = {
        "SCHEMA_VERSION",
        "LINEAGE_TABLE",
        "META_TABLE",
        "SETTING_ENABLED",
        "SETTING_USERNAME",
        "DEFAULT_USERNAME",
        "LOGGER_NAME",
    }
    module_attrs = {name for name in dir(settings) if not name.startswith("_")}
    assert expected.issubset(module_attrs)
