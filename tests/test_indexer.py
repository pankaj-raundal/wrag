"""Tests for wrag.indexer — incremental indexing orchestration."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from wrag.config import Settings, WorkspaceSource
from wrag.indexer import index_workspace, _load_manifest, _save_manifest, MANIFESTS_DIR
from wrag import store


@pytest.fixture
def sample_workspace(tmp_path):
    """Create a temporary workspace with sample files."""
    # Create some Python files
    (tmp_path / "main.py").write_text("def hello():\n    print('hello')\n")
    (tmp_path / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    # Create a subdirectory
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "helper.py").write_text("class Helper:\n    pass\n")
    # Create a file that should be excluded
    (tmp_path / "data.sql").write_text("SELECT * FROM users;")
    # Create a vendor dir (should be excluded)
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "pkg.py").write_text("# vendor code")
    return tmp_path


@pytest.fixture
def mock_embedder():
    """Mock embedder that returns fixed-dimension vectors."""
    embedder = MagicMock()
    embedder.dimension.return_value = 384
    embedder.embed.side_effect = lambda texts: [[0.1] * 384 for _ in texts]
    return embedder


@pytest.fixture(autouse=True)
def temp_data_dirs(tmp_path):
    """Redirect store and manifests to temp dirs."""
    data_root = tmp_path / ".wrag_data"
    data_root.mkdir()
    vectors_dir = data_root / "vectors"
    vectors_dir.mkdir()
    manifests_dir = data_root / "manifests"
    manifests_dir.mkdir()

    with patch.object(store, "VECTORS_DIR", vectors_dir):
        import wrag.indexer as indexer_mod
        with patch.object(indexer_mod, "MANIFESTS_DIR", manifests_dir):
            yield {"vectors": vectors_dir, "manifests": manifests_dir}


class TestIndexWorkspace:
    def test_indexes_all_files(self, sample_workspace, mock_embedder, temp_data_dirs):
        source = WorkspaceSource(name="testapp", path=str(sample_workspace))
        settings = Settings()

        result = index_workspace(source, settings, mock_embedder)

        assert result["files_indexed"] == 3  # main.py, utils.py, lib/helper.py
        assert result["files_skipped"] == 0
        assert result["chunks_added"] > 0
        assert "error" not in result

    def test_skips_excluded_dirs(self, sample_workspace, mock_embedder, temp_data_dirs):
        source = WorkspaceSource(name="testapp", path=str(sample_workspace))
        settings = Settings()

        result = index_workspace(source, settings, mock_embedder)

        # vendor/ should be excluded
        assert result["files_scanned"] == 3  # no vendor/pkg.py

    def test_skips_excluded_extensions(self, sample_workspace, mock_embedder, temp_data_dirs):
        source = WorkspaceSource(name="testapp", path=str(sample_workspace))
        settings = Settings()

        result = index_workspace(source, settings, mock_embedder)

        # .sql should be excluded
        assert result["files_scanned"] == 3  # no data.sql

    def test_incremental_skips_unchanged(self, sample_workspace, mock_embedder, temp_data_dirs):
        source = WorkspaceSource(name="testapp", path=str(sample_workspace))
        settings = Settings()

        # First index
        result1 = index_workspace(source, settings, mock_embedder)
        assert result1["files_indexed"] == 3

        # Second index (no changes)
        result2 = index_workspace(source, settings, mock_embedder)
        assert result2["files_indexed"] == 0
        assert result2["files_skipped"] == 3

    def test_reindexes_changed_file(self, sample_workspace, mock_embedder, temp_data_dirs):
        source = WorkspaceSource(name="testapp", path=str(sample_workspace))
        settings = Settings()

        # First index
        index_workspace(source, settings, mock_embedder)

        # Modify a file
        (sample_workspace / "main.py").write_text("def hello():\n    print('updated')\n")

        # Second index
        result = index_workspace(source, settings, mock_embedder)
        assert result["files_indexed"] == 1  # only main.py re-indexed
        assert result["files_skipped"] == 2

    def test_force_reindexes_everything(self, sample_workspace, mock_embedder, temp_data_dirs):
        source = WorkspaceSource(name="testapp", path=str(sample_workspace))
        settings = Settings()

        # First index
        index_workspace(source, settings, mock_embedder)

        # Force re-index
        result = index_workspace(source, settings, mock_embedder, force=True)
        assert result["files_indexed"] == 3
        assert result["files_skipped"] == 0

    def test_handles_deleted_files(self, sample_workspace, mock_embedder, temp_data_dirs):
        source = WorkspaceSource(name="testapp", path=str(sample_workspace))
        settings = Settings()

        # First index
        index_workspace(source, settings, mock_embedder)

        # Delete a file
        (sample_workspace / "utils.py").unlink()

        # Re-index
        result = index_workspace(source, settings, mock_embedder)
        assert result["files_deleted"] == 1

    def test_invalid_path_returns_error(self, mock_embedder, temp_data_dirs):
        source = WorkspaceSource(name="testapp", path="/nonexistent/path")
        settings = Settings()

        result = index_workspace(source, settings, mock_embedder)
        assert "error" in result


class TestManifest:
    def test_save_and_load(self, temp_data_dirs):
        manifest = {"file1.py": "abc123", "file2.py": "def456"}
        _save_manifest("testapp", manifest)
        loaded = _load_manifest("testapp")
        assert loaded == manifest

    def test_load_nonexistent(self, temp_data_dirs):
        loaded = _load_manifest("no_such_app")
        assert loaded == {}
