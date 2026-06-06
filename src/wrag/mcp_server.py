"""MCP server for wRag — exposes search tools to GitHub Copilot."""

from __future__ import annotations

import json
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from wrag import store
from wrag.config import load_config, _PROJECT_ROOT
from wrag.embedder import get_embedder

mcp = FastMCP("wrag", instructions="Local codebase RAG — search indexed code and docs")

# --- Request tracking ---
_STATS_FILE = _PROJECT_ROOT / ".data" / "request_log.jsonl"


def _log_request(tool_name: str, query: str, results_count: int):
    """Append a request record to the log file."""
    _STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.time(),
        "tool": tool_name,
        "query": query[:200],
        "results": results_count,
    }
    with open(_STATS_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def _embed_query(text: str) -> list[float]:
    """Embed a query string using the configured embedder."""
    cfg = load_config()
    embedder = get_embedder(cfg.settings.embedding_model)
    vectors = embedder.embed([text])
    return vectors[0]


@mcp.tool()
def search_code(query: str, app_name: str = "", top_k: int = 10) -> str:
    """Search indexed codebase for relevant code snippets.

    Args:
        query: Natural language query describing what you're looking for
        app_name: Optional app name to scope the search (leave empty for all apps)
        top_k: Number of results to return (default 10)
    """
    vector = _embed_query(query)
    results = store.search(
        query_vector=vector,
        app_name=app_name or None,
        top_k=top_k,
        source_type="workspace",
    )

    _log_request("search_code", query, len(results))

    if not results:
        return "No results found."

    parts = []
    for i, r in enumerate(results, 1):
        header = f"## Result {i}: {r['path']}:{r['start_line']}-{r['end_line']}"
        meta = f"App: {r['app_name']} | Lang: {r['language']} | {r['symbol_type']}: {r['symbol_name']}"
        parts.append(f"{header}\n{meta}\n```\n{r['text']}\n```")

    return "\n\n".join(parts)


@mcp.tool()
def search_docs(query: str, app_name: str = "", top_k: int = 10) -> str:
    """Search indexed Confluence documentation.

    Args:
        query: Natural language query for documentation search
        app_name: Optional app name to scope the search
        top_k: Number of results to return (default 10)
    """
    vector = _embed_query(query)
    results = store.search(
        query_vector=vector,
        app_name=app_name or None,
        top_k=top_k,
        source_type="confluence",
    )

    _log_request("search_docs", query, len(results))

    if not results:
        return "No documentation results found."

    parts = []
    for i, r in enumerate(results, 1):
        header = f"## Result {i}: {r['symbol_name']}"
        meta = f"App: {r['app_name']} | Page: {r['path']}"
        parts.append(f"{header}\n{meta}\n\n{r['text']}")

    return "\n\n".join(parts)


@mcp.tool()
def search_symbol(name: str, app_name: str = "") -> str:
    """Search for a code symbol (function, class, method) by name.

    Args:
        name: Symbol name or partial name to search for
        app_name: Optional app name to scope the search
    """
    results = store.search_symbol(name=name, app_name=app_name or None)

    _log_request("search_symbol", name, len(results))

    if not results:
        return f"No symbols matching '{name}' found."

    parts = []
    for r in results:
        loc = f"{r['path']}:{r['start_line']}-{r['end_line']}"
        parts.append(
            f"- **{r['symbol_type']} `{r['symbol_name']}`** in {loc} "
            f"({r['app_name']}, {r['language']})"
        )

    return "\n".join(parts)


@mcp.tool()
def list_apps() -> str:
    """List all indexed applications with their statistics."""
    app_stats = store.stats()

    if not app_stats:
        return "No apps indexed yet. Run `wrag index <app>` to index a source."

    parts = []
    for name, s in sorted(app_stats.items()):
        parts.append(
            f"- **{name}** ({s['source_type']}): "
            f"{s['chunk_count']} chunks, {s['file_count']} files, "
            f"languages: {', '.join(s['languages'])}"
        )

    total = store.total_chunks()
    parts.append(f"\n**Total**: {total} chunks across {len(app_stats)} apps")
    return "\n".join(parts)


@mcp.tool()
def app_overview(app_name: str) -> str:
    """Get an overview of a specific indexed application.

    Args:
        app_name: Name of the app to get overview for
    """
    app_stats = store.stats()

    if app_name not in app_stats:
        available = ", ".join(sorted(app_stats.keys())) if app_stats else "none"
        return f"App '{app_name}' not found. Available: {available}"

    s = app_stats[app_name]
    cfg = load_config()
    source = cfg.find_source(app_name)

    lines = [
        f"# {app_name}",
        f"- **Type**: {s['source_type']}",
        f"- **Chunks**: {s['chunk_count']}",
        f"- **Files**: {s['file_count']}",
        f"- **Languages**: {', '.join(s['languages'])}",
    ]

    if source:
        if hasattr(source, "path"):
            lines.append(f"- **Path**: {source.path}")
        elif hasattr(source, "domain"):
            lines.append(f"- **Domain**: {source.domain}")
            lines.append(f"- **Space**: {source.space_key}")

    return "\n".join(lines)


@mcp.tool()
def request_stats() -> str:
    """Show wRag request statistics — how many tool calls have been served.

    Use this to demonstrate request savings vs Copilot's native file scanning.
    """
    stats = get_request_stats()
    lines = [
        "# wRag Request Stats",
        f"- **Total tool calls served**: {stats['total']}",
        f"- **Total results returned**: {stats['total_results']}",
        "",
        "## By Tool:",
    ]
    for tool, count in sorted(stats["by_tool"].items()):
        lines.append(f"  - {tool}: {count} calls")

    lines.append("")
    lines.append("## Estimated Savings:")
    # Each wRag call replaces ~4 native Copilot operations (file reads + searches)
    estimated_native = stats["total"] * 4
    saved = estimated_native - stats["total"]
    lines.append(f"  - Without wRag (estimated): ~{estimated_native} requests")
    lines.append(f"  - With wRag (actual): {stats['total']} requests")
    lines.append(f"  - **Saved: ~{saved} requests ({(saved/max(estimated_native,1)*100):.0f}%)**")

    if stats["recent"]:
        lines.append("")
        lines.append("## Last 5 Queries:")
        for r in stats["recent"][-5:]:
            lines.append(f"  - [{r['tool']}] \"{r['query']}\" → {r['results']} results")

    return "\n".join(lines)


def get_request_stats() -> dict:
    """Read request log and compute stats. Also used by CLI."""
    stats = {"total": 0, "total_results": 0, "by_tool": {}, "recent": []}

    if not _STATS_FILE.exists():
        return stats

    with open(_STATS_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            stats["total"] += 1
            stats["total_results"] += record.get("results", 0)
            tool = record.get("tool", "unknown")
            stats["by_tool"][tool] = stats["by_tool"].get(tool, 0) + 1
            stats["recent"].append(record)

    # Keep only last 20 for recent
    stats["recent"] = stats["recent"][-20:]
    return stats


def run_stdio():
    """Run the MCP server in stdio mode."""
    mcp.run(transport="stdio")
