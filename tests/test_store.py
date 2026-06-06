"""Tests for wrag.store — LanceDB vector store operations."""

import pytest
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from wrag import store


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path):
    """Use a temp directory for all store tests to avoid polluting real data."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    with patch.object(store, "VECTORS_DIR", vectors_dir):
        yield vectors_dir


def _make_chunks(app_name: str, n: int = 3) -> tuple[list[dict], list[list[float]]]:
    """Create sample chunks and vectors for testing."""
    chunks = []
    vectors = []
    for i in range(n):
        chunks.append({
            "id": f"{app_name}::file{i}.py::function::func_{i}",
            "text": f"def func_{i}():\n    pass",
            "path": f"file{i}.py",
            "app_name": app_name,
            "language": "python",
            "symbol_name": f"func_{i}",
            "symbol_type": "function",
            "start_line": 1,
            "end_line": 2,
            "source_type": "workspace",
        })
        vectors.append([float(i) / 10.0] * 384)
    return chunks, vectors


class TestUpsertChunks:
    def test_insert_new_chunks(self):
        chunks, vectors = _make_chunks("testapp", 3)
        count = store.upsert_chunks("testapp", chunks, vectors)
        assert count == 3

    def test_upsert_replaces_existing(self):
        chunks, vectors = _make_chunks("testapp", 2)
        store.upsert_chunks("testapp", chunks, vectors)

        # Modify and re-upsert
        chunks[0]["text"] = "def func_0():\n    return 'updated'"
        store.upsert_chunks("testapp", chunks, vectors)

        # Should still be 2 total, not 4
        assert store.total_chunks() == 2

    def test_empty_chunks_returns_zero(self):
        count = store.upsert_chunks("testapp", [], [])
        assert count == 0


class TestDeleteApp:
    def test_delete_existing_app(self):
        chunks, vectors = _make_chunks("app_to_delete", 5)
        store.upsert_chunks("app_to_delete", chunks, vectors)
        assert store.total_chunks() == 5

        deleted = store.delete_app("app_to_delete")
        assert deleted == 5
        assert store.total_chunks() == 0

    def test_delete_nonexistent_app(self):
        deleted = store.delete_app("no_such_app")
        assert deleted == 0


class TestDeleteByPath:
    def test_delete_specific_file(self):
        chunks, vectors = _make_chunks("testapp", 3)
        store.upsert_chunks("testapp", chunks, vectors)

        deleted = store.delete_by_path("testapp", "file0.py")
        assert deleted == 1
        assert store.total_chunks() == 2


class TestSearch:
    def test_search_returns_results(self):
        chunks, vectors = _make_chunks("testapp", 5)
        store.upsert_chunks("testapp", chunks, vectors)

        # Search with one of the vectors
        results = store.search(vectors[0], top_k=3)
        assert len(results) <= 3
        assert all("text" in r for r in results)
        assert all("score" in r for r in results)

    def test_search_empty_store(self):
        results = store.search([0.0] * 384, top_k=5)
        assert results == []

    def test_search_with_app_filter(self):
        chunks1, vectors1 = _make_chunks("app1", 3)
        chunks2, vectors2 = _make_chunks("app2", 3)
        store.upsert_chunks("app1", chunks1, vectors1)
        store.upsert_chunks("app2", chunks2, vectors2)

        results = store.search(vectors1[0], app_name="app1", top_k=10)
        assert all(r["app_name"] == "app1" for r in results)


class TestStats:
    def test_stats_empty(self):
        result = store.stats()
        assert result == {}

    def test_stats_with_data(self):
        chunks, vectors = _make_chunks("myapp", 4)
        store.upsert_chunks("myapp", chunks, vectors)

        result = store.stats()
        assert "myapp" in result
        assert result["myapp"]["chunk_count"] == 4
        assert result["myapp"]["source_type"] == "workspace"
        assert "python" in result["myapp"]["languages"]


class TestTotalChunks:
    def test_empty_store(self):
        assert store.total_chunks() == 0

    def test_after_inserts(self):
        chunks, vectors = _make_chunks("app", 7)
        store.upsert_chunks("app", chunks, vectors)
        assert store.total_chunks() == 7
