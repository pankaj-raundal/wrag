"""Tests for the wRag MCP server tools."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from wrag.mcp_server import (
    app_overview,
    list_apps,
    search_code,
    search_docs,
    search_symbol,
)


@pytest.fixture
def mock_embed():
    """Mock the embedder to return a fixed vector."""
    with patch("wrag.mcp_server._embed_query") as m:
        m.return_value = [0.1] * 384
        yield m


@pytest.fixture
def sample_search_results():
    return [
        {
            "id": "chunk1",
            "text": "def hello():\n    print('hi')",
            "path": "src/app.py",
            "app_name": "myapp",
            "language": "python",
            "symbol_name": "hello",
            "symbol_type": "function",
            "start_line": 1,
            "end_line": 2,
            "source_type": "workspace",
            "score": 0.15,
        },
        {
            "id": "chunk2",
            "text": "class Foo:\n    pass",
            "path": "src/models.py",
            "app_name": "myapp",
            "language": "python",
            "symbol_name": "Foo",
            "symbol_type": "class",
            "start_line": 10,
            "end_line": 11,
            "source_type": "workspace",
            "score": 0.25,
        },
    ]


class TestSearchCode:
    def test_returns_formatted_results(self, mock_embed, sample_search_results):
        with patch("wrag.mcp_server.store.search", return_value=sample_search_results):
            result = search_code("find hello function", app_name="myapp")

        assert "Result 1" in result
        assert "src/app.py:1-2" in result
        assert "def hello():" in result
        assert "Result 2" in result
        mock_embed.assert_called_once_with("find hello function")

    def test_no_results(self, mock_embed):
        with patch("wrag.mcp_server.store.search", return_value=[]):
            result = search_code("nonexistent")

        assert result == "No results found."

    def test_filters_workspace_source(self, mock_embed):
        with patch("wrag.mcp_server.store.search", return_value=[]) as mock_search:
            search_code("test", app_name="myapp", top_k=5)

        mock_search.assert_called_once_with(
            query_vector=[0.1] * 384,
            app_name="myapp",
            top_k=5,
            source_type="workspace",
        )

    def test_empty_app_name_passes_none(self, mock_embed):
        with patch("wrag.mcp_server.store.search", return_value=[]) as mock_search:
            search_code("test", app_name="")

        mock_search.assert_called_once_with(
            query_vector=[0.1] * 384,
            app_name=None,
            top_k=10,
            source_type="workspace",
        )


class TestSearchDocs:
    def test_returns_formatted_docs(self, mock_embed):
        doc_results = [
            {
                "id": "doc1",
                "text": "This is documentation about the API.",
                "path": "https://example.atlassian.net/wiki/spaces/DEV/pages/123",
                "app_name": "docs",
                "language": "markdown",
                "symbol_name": "API Overview",
                "symbol_type": "section",
                "start_line": 0,
                "end_line": 0,
                "source_type": "confluence",
                "score": 0.1,
            }
        ]
        with patch("wrag.mcp_server.store.search", return_value=doc_results):
            result = search_docs("API documentation")

        assert "API Overview" in result
        assert "This is documentation about the API." in result

    def test_no_results(self, mock_embed):
        with patch("wrag.mcp_server.store.search", return_value=[]):
            result = search_docs("nothing")

        assert result == "No documentation results found."

    def test_filters_confluence_source(self, mock_embed):
        with patch("wrag.mcp_server.store.search", return_value=[]) as mock_search:
            search_docs("test", app_name="mydocs")

        mock_search.assert_called_once_with(
            query_vector=[0.1] * 384,
            app_name="mydocs",
            top_k=10,
            source_type="confluence",
        )


class TestSearchSymbol:
    def test_returns_formatted_symbols(self):
        symbol_results = [
            {
                "id": "s1",
                "text": "def process_data():\n    ...",
                "path": "src/pipeline.py",
                "app_name": "myapp",
                "language": "python",
                "symbol_name": "process_data",
                "symbol_type": "function",
                "start_line": 50,
                "end_line": 65,
                "source_type": "workspace",
            }
        ]
        with patch("wrag.mcp_server.store.search_symbol", return_value=symbol_results):
            result = search_symbol("process_data")

        assert "`process_data`" in result
        assert "src/pipeline.py:50-65" in result
        assert "function" in result

    def test_no_results(self):
        with patch("wrag.mcp_server.store.search_symbol", return_value=[]):
            result = search_symbol("xyz_nonexist")

        assert "No symbols matching 'xyz_nonexist' found." in result


class TestListApps:
    def test_shows_app_stats(self):
        mock_stats = {
            "myapp": {
                "chunk_count": 100,
                "file_count": 20,
                "languages": ["python", "yaml"],
                "source_type": "workspace",
                "last_indexed": 1700000000.0,
            }
        }
        with patch("wrag.mcp_server.store.stats", return_value=mock_stats), \
             patch("wrag.mcp_server.store.total_chunks", return_value=100):
            result = list_apps()

        assert "myapp" in result
        assert "100 chunks" in result
        assert "20 files" in result
        assert "python" in result

    def test_no_apps(self):
        with patch("wrag.mcp_server.store.stats", return_value={}):
            result = list_apps()

        assert "No apps indexed yet" in result


class TestAppOverview:
    def test_shows_overview(self):
        mock_stats = {
            "myapp": {
                "chunk_count": 50,
                "file_count": 10,
                "languages": ["php", "yaml"],
                "source_type": "workspace",
                "last_indexed": 1700000000.0,
            }
        }
        from wrag.config import Config, WorkspaceSource

        cfg = Config(workspaces=[WorkspaceSource(name="myapp", path="/home/user/myapp")])
        with patch("wrag.mcp_server.store.stats", return_value=mock_stats), \
             patch("wrag.mcp_server.load_config", return_value=cfg):
            result = app_overview("myapp")

        assert "# myapp" in result
        assert "50" in result
        assert "/home/user/myapp" in result

    def test_app_not_found(self):
        with patch("wrag.mcp_server.store.stats", return_value={"other": {}}):
            result = app_overview("missing")

        assert "not found" in result
        assert "other" in result
