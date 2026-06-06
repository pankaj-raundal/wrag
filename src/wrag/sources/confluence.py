"""Confluence source — fetches pages via REST API, converts HTML→text, chunks by headings."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional

import httpx

from wrag.chunker import Chunk


@dataclass
class ConfluencePage:
    """A page fetched from Confluence."""

    page_id: str
    title: str
    version: int
    space_key: str
    url: str
    body_text: str  # HTML converted to plain text


class _HTMLToText(HTMLParser):
    """Simple HTML→text converter preserving headings and structure."""

    def __init__(self):
        super().__init__()
        self._result: list[str] = []
        self._skip = False
        self._in_heading = False
        self._heading_level = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav"):
            self._skip = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._in_heading = True
            self._heading_level = int(tag[1])
            self._result.append("\n" + "#" * self._heading_level + " ")
        elif tag == "p":
            self._result.append("\n")
        elif tag == "br":
            self._result.append("\n")
        elif tag == "li":
            self._result.append("\n- ")
        elif tag in ("ul", "ol"):
            self._result.append("\n")
        elif tag == "tr":
            self._result.append("\n| ")
        elif tag == "td" or tag == "th":
            self._result.append(" | ")
        elif tag == "pre" or tag == "code":
            self._result.append("\n```\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav"):
            self._skip = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._in_heading = False
            self._result.append("\n")
        elif tag == "pre" or tag == "code":
            self._result.append("\n```\n")

    def handle_data(self, data):
        if not self._skip:
            self._result.append(data)

    def get_text(self) -> str:
        text = "".join(self._result)
        # Clean up excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_text(html: str) -> str:
    """Convert Confluence HTML storage format to readable text."""
    parser = _HTMLToText()
    parser.feed(html)
    return parser.get_text()


def chunk_confluence_page(page: ConfluencePage, app_name: str) -> list[Chunk]:
    """Chunk a Confluence page by heading boundaries.

    Similar to markdown heading chunking but works on converted text.
    """
    text = page.body_text
    lines = text.split("\n")
    chunks: list[Chunk] = []
    current_heading = page.title
    current_lines: list[str] = []
    current_start = 0

    for i, line in enumerate(lines):
        if re.match(r"^#{1,4}\s+", line):
            # Save previous section
            if current_lines:
                section_text = "\n".join(current_lines).strip()
                if section_text:
                    chunk_id = (
                        f"{app_name}::{page.page_id}::section::{current_heading}"
                    )
                    chunks.append(
                        Chunk(
                            id=chunk_id,
                            text=section_text,
                            path=page.url,
                            app_name=app_name,
                            language="markdown",
                            symbol_name=current_heading,
                            symbol_type="section",
                            start_line=current_start + 1,
                            end_line=i,
                            source_type="confluence",
                        )
                    )
            current_heading = re.sub(r"^#+\s+", "", line).strip()
            current_lines = [line]
            current_start = i
        else:
            current_lines.append(line)

    # Last section
    if current_lines:
        section_text = "\n".join(current_lines).strip()
        if section_text:
            chunk_id = f"{app_name}::{page.page_id}::section::{current_heading}"
            chunks.append(
                Chunk(
                    id=chunk_id,
                    text=section_text,
                    path=page.url,
                    app_name=app_name,
                    language="markdown",
                    symbol_name=current_heading,
                    symbol_type="section",
                    start_line=current_start + 1,
                    end_line=len(lines),
                    source_type="confluence",
                )
            )

    # If no headings found, treat entire page as one chunk
    if not chunks and text.strip():
        chunks.append(
            Chunk(
                id=f"{app_name}::{page.page_id}::page::{page.title}",
                text=text,
                path=page.url,
                app_name=app_name,
                language="markdown",
                symbol_name=page.title,
                symbol_type="page",
                start_line=1,
                end_line=len(lines),
                source_type="confluence",
            )
        )

    return chunks


class ConfluenceClient:
    """Confluence REST API v2 client."""

    def __init__(self, domain: str, email: str, token: str):
        self.base_url = f"https://{domain}"
        self.email = email
        self.token = token
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                auth=(self.email, self.token),
                timeout=30.0,
                headers={"Accept": "application/json"},
            )
        return self._client

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    def fetch_pages(
        self, space_key: str, limit: int = 50
    ) -> list[ConfluencePage]:
        """Fetch all pages from a Confluence space.

        Uses the v2 API with pagination.
        """
        client = self._get_client()
        pages: list[ConfluencePage] = []
        cursor: Optional[str] = None

        while True:
            # Use v1 API (more reliable across Confluence versions)
            params = {
                "spaceKey": space_key,
                "expand": "body.storage,version",
                "limit": limit,
            }
            if cursor:
                params["start"] = cursor

            response = client.get("/wiki/rest/api/content", params=params)

            if response.status_code == 401:
                raise PermissionError(
                    "Confluence authentication failed. Check CONFLUENCE_EMAIL and CONFLUENCE_TOKEN."
                )
            if response.status_code == 404:
                raise ValueError(
                    f"Space '{space_key}' not found or API endpoint unavailable."
                )
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])

            for page_data in results:
                body_html = (
                    page_data.get("body", {}).get("storage", {}).get("value", "")
                )
                body_text = html_to_text(body_html)

                # Skip empty pages
                if not body_text.strip():
                    continue

                page_id = str(page_data["id"])
                title = page_data.get("title", "")
                version = page_data.get("version", {}).get("number", 1)

                # Build page URL
                page_url = f"{self.base_url}/wiki/spaces/{space_key}/pages/{page_id}"

                pages.append(
                    ConfluencePage(
                        page_id=page_id,
                        title=title,
                        version=version,
                        space_key=space_key,
                        url=page_url,
                        body_text=body_text,
                    )
                )

            # Check for next page
            next_link = data.get("_links", {}).get("next")
            if not next_link or not results:
                break

            # Extract start parameter for next page
            cursor = str(int(cursor or "0") + limit)

            # Rate limit: small delay between requests
            time.sleep(0.2)

        return pages

    def fetch_page_by_id(self, page_id: str) -> Optional[ConfluencePage]:
        """Fetch a single page by ID."""
        client = self._get_client()
        response = client.get(
            f"/wiki/rest/api/content/{page_id}",
            params={"expand": "body.storage,version,space"},
        )

        if response.status_code != 200:
            return None

        page_data = response.json()
        body_html = page_data.get("body", {}).get("storage", {}).get("value", "")
        body_text = html_to_text(body_html)
        space_key = page_data.get("space", {}).get("key", "")

        return ConfluencePage(
            page_id=str(page_data["id"]),
            title=page_data.get("title", ""),
            version=page_data.get("version", {}).get("number", 1),
            space_key=space_key,
            url=f"{self.base_url}/wiki/spaces/{space_key}/pages/{page_id}",
            body_text=body_text,
        )


def get_confluence_credentials(
    email_override: str = "",
) -> tuple[str, str]:
    """Get Confluence credentials from environment or credentials file.

    Order of precedence:
    1. CONFLUENCE_EMAIL / CONFLUENCE_TOKEN env vars
    2. ~/.config/dai/credentials.env file

    Returns:
        Tuple of (email, token)
    """
    email = email_override or os.environ.get("CONFLUENCE_EMAIL", "")
    token = os.environ.get("CONFLUENCE_TOKEN", "")

    # Try loading from credentials.env if not in environment
    if not email or not token:
        creds_path = os.path.expanduser("~/.config/dai/credentials.env")
        if os.path.exists(creds_path):
            with open(creds_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key == "CONFLUENCE_EMAIL" and not email:
                        email = value
                    elif key == "CONFLUENCE_TOKEN" and not token:
                        token = value

    if not email:
        raise ValueError(
            "Confluence email not configured. Set CONFLUENCE_EMAIL env var "
            "or run credential setup."
        )
    if not token:
        raise ValueError(
            "Confluence token not configured. Set CONFLUENCE_TOKEN env var "
            "or run credential setup."
        )

    return email, token
