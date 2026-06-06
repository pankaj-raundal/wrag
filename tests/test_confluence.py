"""Tests for wrag.sources.confluence — API client, HTML parsing, chunking."""

import pytest
from unittest.mock import patch, MagicMock

from wrag.sources.confluence import (
    ConfluenceClient,
    ConfluencePage,
    chunk_confluence_page,
    get_confluence_credentials,
    html_to_text,
)


class TestHtmlToText:
    def test_basic_paragraphs(self):
        html = "<p>Hello world.</p><p>Second paragraph.</p>"
        text = html_to_text(html)
        assert "Hello world." in text
        assert "Second paragraph." in text

    def test_headings_become_markdown(self):
        html = "<h1>Title</h1><p>Content</p><h2>Sub</h2><p>More</p>"
        text = html_to_text(html)
        assert "# Title" in text
        assert "## Sub" in text

    def test_lists(self):
        html = "<ul><li>Item one</li><li>Item two</li></ul>"
        text = html_to_text(html)
        assert "- Item one" in text
        assert "- Item two" in text

    def test_code_blocks(self):
        html = "<pre>def hello():\n    pass</pre>"
        text = html_to_text(html)
        assert "```" in text
        assert "def hello():" in text

    def test_scripts_stripped(self):
        html = "<p>Visible</p><script>alert('x')</script><p>Also visible</p>"
        text = html_to_text(html)
        assert "Visible" in text
        assert "Also visible" in text
        assert "alert" not in text

    def test_tables(self):
        html = "<table><tr><th>Name</th><th>Value</th></tr><tr><td>A</td><td>1</td></tr></table>"
        text = html_to_text(html)
        assert "Name" in text
        assert "Value" in text

    def test_empty_html(self):
        assert html_to_text("") == ""

    def test_nested_tags(self):
        html = "<p><strong>Bold</strong> and <em>italic</em></p>"
        text = html_to_text(html)
        assert "Bold" in text
        assert "italic" in text


class TestChunkConfluencePage:
    def test_page_with_headings(self):
        page = ConfluencePage(
            page_id="12345",
            title="Test Page",
            version=3,
            space_key="CONN",
            url="https://example.atlassian.net/wiki/spaces/CONN/pages/12345",
            body_text="# Introduction\n\nSome intro text.\n\n## Setup\n\nSetup steps here.\n\n## Usage\n\nUsage info.",
        )
        chunks = chunk_confluence_page(page, "myapp")
        assert len(chunks) >= 2
        assert all(c.source_type == "confluence" for c in chunks)
        assert all(c.app_name == "myapp" for c in chunks)
        # Check heading names are captured
        headings = [c.symbol_name for c in chunks]
        assert "Setup" in headings or "Introduction" in headings

    def test_page_without_headings(self):
        page = ConfluencePage(
            page_id="99999",
            title="Simple Page",
            version=1,
            space_key="TEST",
            url="https://example.atlassian.net/wiki/spaces/TEST/pages/99999",
            body_text="Just some plain text without any headings.",
        )
        chunks = chunk_confluence_page(page, "myapp")
        assert len(chunks) == 1
        assert chunks[0].symbol_name == "Simple Page"
        assert chunks[0].source_type == "confluence"

    def test_empty_page(self):
        page = ConfluencePage(
            page_id="00000",
            title="Empty",
            version=1,
            space_key="TEST",
            url="https://example.atlassian.net/wiki/spaces/TEST/pages/00000",
            body_text="",
        )
        chunks = chunk_confluence_page(page, "myapp")
        assert len(chunks) == 0

    def test_chunk_metadata(self):
        page = ConfluencePage(
            page_id="555",
            title="My Doc",
            version=2,
            space_key="DOC",
            url="https://org.atlassian.net/wiki/spaces/DOC/pages/555",
            body_text="# Section One\n\nContent here.",
        )
        chunks = chunk_confluence_page(page, "docs")
        assert len(chunks) >= 1
        chunk = chunks[0]
        assert chunk.path == "https://org.atlassian.net/wiki/spaces/DOC/pages/555"
        assert chunk.app_name == "docs"
        assert "555" in chunk.id


class TestGetConfluenceCredentials:
    def test_from_env_vars(self):
        with patch.dict(
            "os.environ",
            {"CONFLUENCE_EMAIL": "user@example.com", "CONFLUENCE_TOKEN": "secret123"},
        ):
            email, token = get_confluence_credentials()
            assert email == "user@example.com"
            assert token == "secret123"

    def test_email_override(self):
        with patch.dict(
            "os.environ",
            {"CONFLUENCE_EMAIL": "env@example.com", "CONFLUENCE_TOKEN": "tok"},
        ):
            email, token = get_confluence_credentials(email_override="override@x.com")
            assert email == "override@x.com"

    def test_missing_email_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("os.path.exists", return_value=False):
                with pytest.raises(ValueError, match="email not configured"):
                    get_confluence_credentials()

    def test_missing_token_raises(self):
        with patch.dict(
            "os.environ", {"CONFLUENCE_EMAIL": "user@x.com"}, clear=True
        ):
            with patch("os.path.exists", return_value=False):
                with pytest.raises(ValueError, match="token not configured"):
                    get_confluence_credentials()

    def test_reads_from_credentials_file(self, tmp_path):
        creds_file = tmp_path / "credentials.env"
        creds_file.write_text(
            "CONFLUENCE_EMAIL=file@example.com\nCONFLUENCE_TOKEN=filetoken\n"
        )
        with patch.dict("os.environ", {}, clear=True):
            with patch("os.path.expanduser", return_value=str(creds_file)):
                with patch("os.path.exists", return_value=True):
                    with patch("builtins.open", return_value=creds_file.open("r")):
                        email, token = get_confluence_credentials()
                        assert email == "file@example.com"
                        assert token == "filetoken"


class TestConfluenceClient:
    def test_fetch_pages_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "123",
                    "title": "Page One",
                    "version": {"number": 5},
                    "body": {
                        "storage": {
                            "value": "<h1>Hello</h1><p>World</p>"
                        }
                    },
                },
                {
                    "id": "456",
                    "title": "Page Two",
                    "version": {"number": 2},
                    "body": {"storage": {"value": "<p>Content</p>"}},
                },
            ],
            "_links": {},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            mock_client_instance.get.return_value = mock_response
            MockClient.return_value = mock_client_instance

            client = ConfluenceClient(
                domain="test.atlassian.net", email="a@b.com", token="tok"
            )
            pages = client.fetch_pages("SPACE")

            assert len(pages) == 2
            assert pages[0].title == "Page One"
            assert pages[0].version == 5
            assert pages[1].page_id == "456"
            client.close()

    def test_fetch_pages_auth_failure(self):
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            mock_client_instance.get.return_value = mock_response
            MockClient.return_value = mock_client_instance

            client = ConfluenceClient(
                domain="test.atlassian.net", email="a@b.com", token="bad"
            )
            with pytest.raises(PermissionError, match="authentication failed"):
                client.fetch_pages("SPACE")
            client.close()

    def test_fetch_pages_space_not_found(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            mock_client_instance.get.return_value = mock_response
            MockClient.return_value = mock_client_instance

            client = ConfluenceClient(
                domain="test.atlassian.net", email="a@b.com", token="tok"
            )
            with pytest.raises(ValueError, match="not found"):
                client.fetch_pages("NOPE")
            client.close()
