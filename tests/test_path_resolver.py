"""Tests for lineage_retrieval.path_resolver module."""

from GeoLineage.lineage_retrieval.path_resolver import extract_gpkg_path, resolve


def test_resolve_relative_found(tmp_path):
    """Relative ref that resolves to an existing file returns (resolved_path, 'found')."""
    project_dir = str(tmp_path)
    target = tmp_path / "data.gpkg"
    target.write_bytes(b"")

    resolved, status = resolve("data.gpkg", project_dir)

    assert status == "found"
    assert resolved == str(target.resolve())


def test_resolve_absolute_found(tmp_path):
    """Absolute path to an existing file returns (resolved_path, 'found')."""
    target = tmp_path / "data.gpkg"
    target.write_bytes(b"")
    absolute_ref = str(target)

    resolved, status = resolve(absolute_ref, "/nonexistent/project/dir")

    assert status == "found"
    assert resolved == str(target)


def test_resolve_not_found(tmp_path):
    """Non-existent ref returns (original_ref, 'not_found')."""
    ref = "missing.gpkg"

    resolved, status = resolve(ref, str(tmp_path))

    assert status == "not_found"
    assert resolved == ref


def test_resolve_relative_preferred_over_absolute(tmp_path):
    """When a relative resolution would find the file, it is returned before the absolute path is tried."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # File exists relative to project_dir
    relative_target = project_dir / "data.gpkg"
    relative_target.write_bytes(b"")

    # Construct a ref that is also a valid absolute path pointing elsewhere
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    absolute_target = other_dir / "data.gpkg"
    absolute_target.write_bytes(b"")

    # Use "data.gpkg" as the ref — relative resolution should win
    resolved, status = resolve("data.gpkg", str(project_dir))

    assert status == "found"
    assert resolved == str(relative_target)


def test_resolve_path_with_spaces(tmp_path):
    """Path containing spaces resolves correctly."""
    project_dir = tmp_path / "my project"
    project_dir.mkdir()
    target = project_dir / "my data.gpkg"
    target.write_bytes(b"")

    resolved, status = resolve("my data.gpkg", str(project_dir))

    assert status == "found"
    assert resolved == str(target)


def test_extract_gpkg_path_with_layername():
    assert extract_gpkg_path("/path/to/file.gpkg|layername=foo") == "/path/to/file.gpkg"


def test_extract_gpkg_path_plain():
    assert extract_gpkg_path("/path/to/file.gpkg") == "/path/to/file.gpkg"


def test_extract_gpkg_path_non_gpkg():
    assert extract_gpkg_path("/path/to/file.shp") is None


def test_extract_gpkg_path_empty():
    assert extract_gpkg_path("") is None


def test_extract_gpkg_path_with_multiple_pipes():
    result = extract_gpkg_path("/data/test.gpkg|layername=pts|subset=id>5")
    assert result == "/data/test.gpkg"


def test_resolve_rejects_traversal_via_relative_branch(tmp_path):
    """A '../'-escaping ref must not be reported 'found' via relative resolution.

    The relative candidate normalizes to a path outside project_dir, so the
    relative branch is skipped. The absolute branch then evaluates the raw ref
    (still relative, won't match the secret), so the result is 'not_found'.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # A secret file two levels up from the project dir.
    secret = tmp_path / "secret.gpkg"
    secret.write_bytes(b"")

    resolved, status = resolve("../secret.gpkg", str(project_dir))

    assert status == "not_found"
    assert resolved == "../secret.gpkg"


def test_resolve_windows_style_relative(tmp_path):
    """A backslash-style ref is treated as a single filename on POSIX.

    On POSIX, 'sub\\data.gpkg' has no path separator, so it resolves directly
    under project_dir (contained) — never escaping it.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    target = project_dir / "data.gpkg"
    target.write_bytes(b"")

    # A contained relative ref still resolves; traversal does not.
    resolved, status = resolve("data.gpkg", str(project_dir))
    assert status == "found"
    assert resolved == str(target)

    # Windows-style absolute drive ref does not escape via the relative branch.
    _resolved, status = resolve("C:\\Windows\\secret.gpkg", str(project_dir))
    assert status == "not_found"


def test_resolve_path_with_unicode(tmp_path):
    """Path containing unicode characters resolves correctly."""
    project_dir = tmp_path / "données"
    project_dir.mkdir()
    target = project_dir / "géo_données.gpkg"
    target.write_bytes(b"")

    resolved, status = resolve("géo_données.gpkg", str(project_dir))

    assert status == "found"
    assert resolved == str(target)
