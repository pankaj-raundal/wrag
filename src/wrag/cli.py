"""wRag CLI — manage workspace sources and run indexing/search/serve."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from wrag.config import (
    ConfluenceSource,
    WorkspaceSource,
    load_config,
    save_config,
)

console = Console()


@click.group()
@click.version_option(package_name="wrag")
def main():
    """wRag — Local codebase RAG for GitHub Copilot."""
    pass


@main.command()
@click.argument("name")
@click.argument("path")
def add(name: str, path: str):
    """Register a local workspace for indexing.

    NAME: short identifier (e.g. devopsagent)
    PATH: absolute path to the workspace directory
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        console.print(f"[red]Error:[/red] Path does not exist: {resolved}")
        sys.exit(1)

    config = load_config()

    # Check for duplicate name
    if config.find_source(name):
        console.print(f"[red]Error:[/red] Source '{name}' already registered. Use `wrag remove {name}` first.")
        sys.exit(1)

    config.workspaces.append(WorkspaceSource(name=name, path=str(resolved)))
    save_config(config)
    console.print(f"[green]✓[/green] Registered workspace '{name}' → {resolved}")


@main.command("add-confluence")
@click.argument("name")
@click.option("--domain", required=True, help="Confluence domain (e.g. myorg.atlassian.net)")
@click.option("--space", required=True, help="Confluence space key")
@click.option("--email", default="", help="Email for API auth (or set CONFLUENCE_EMAIL env var)")
def add_confluence(name: str, domain: str, space: str, email: str):
    """Register a Confluence space for indexing.

    NAME: short identifier (e.g. lionbridge-docs)
    """
    config = load_config()

    if config.find_source(name):
        console.print(f"[red]Error:[/red] Source '{name}' already registered. Use `wrag remove {name}` first.")
        sys.exit(1)

    config.confluences.append(
        ConfluenceSource(name=name, domain=domain, space_key=space, email=email)
    )
    save_config(config)
    console.print(f"[green]✓[/green] Registered Confluence space '{name}' → {domain} (space: {space})")


@main.command()
@click.argument("name")
def remove(name: str):
    """Unregister a source (workspace or confluence)."""
    config = load_config()
    if config.remove_source(name):
        save_config(config)
        console.print(f"[green]✓[/green] Removed source '{name}'")
    else:
        console.print(f"[red]Error:[/red] Source '{name}' not found.")
        sys.exit(1)


@main.command("list")
def list_sources():
    """Show all registered sources."""
    config = load_config()

    if not config.workspaces and not config.confluences:
        console.print("[dim]No sources registered. Use `wrag add` or `wrag add-confluence`.[/dim]")
        return

    table = Table(title="Registered Sources")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Location")

    for w in config.workspaces:
        table.add_row(w.name, "workspace", w.path)
    for c in config.confluences:
        table.add_row(c.name, "confluence", f"{c.domain} (space: {c.space_key})")

    console.print(table)


@main.command()
def config():
    """Show current configuration."""
    cfg = load_config()
    console.print("[bold]Settings:[/bold]")
    console.print(f"  Embedding model: {cfg.settings.embedding_model}")
    console.print(f"  Chunk max lines: {cfg.settings.chunk_max_lines}")
    console.print(f"  Excluded dirs: {', '.join(cfg.settings.excluded_dirs)}")
    console.print(f"  Excluded extensions: {', '.join(cfg.settings.excluded_extensions[:10])}...")
    console.print()
    console.print(f"[bold]Workspaces:[/bold] {len(cfg.workspaces)}")
    for w in cfg.workspaces:
        console.print(f"  {w.name} → {w.path}")
    console.print(f"[bold]Confluence spaces:[/bold] {len(cfg.confluences)}")
    for c in cfg.confluences:
        console.print(f"  {c.name} → {c.domain} ({c.space_key})")


@main.command()
@click.argument("name", required=False)
@click.option("--force", is_flag=True, help="Re-index everything, ignoring hashes")
def index(name: str | None, force: bool):
    """Index one or all registered sources.

    NAME: optional source name to index (omit to index all)
    """
    from wrag.indexer import index_source

    index_source(name=name, force=force)


@main.command()
def status():
    """Show indexing stats per source."""
    from wrag import store as st

    stats = st.stats()
    if not stats:
        console.print("[dim]No indexed data. Run `wrag index` first.[/dim]")
        return

    table = Table(title="Index Status")
    table.add_column("Source", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Files", justify="right")
    table.add_column("Chunks", justify="right")
    table.add_column("Languages")
    table.add_column("Last Indexed")

    import time
    for app_name, info in stats.items():
        last = time.strftime("%Y-%m-%d %H:%M", time.localtime(info["last_indexed"]))
        table.add_row(
            app_name,
            info["source_type"],
            str(info["file_count"]),
            str(info["chunk_count"]),
            ", ".join(info["languages"]),
            last,
        )

    console.print(table)
    console.print(f"\n[dim]Total chunks: {st.total_chunks()}[/dim]")


@main.command()
@click.argument("query")
@click.option("--app", default=None, help="Filter by app name")
@click.option("--top-k", default=5, help="Number of results")
def search(query: str, app: str | None, top_k: int):
    """Search indexed codebase (for testing).

    QUERY: natural language search query
    """
    from wrag.config import load_config as _load_config
    from wrag.embedder import get_embedder
    from wrag import store as st

    cfg = _load_config()
    embedder = get_embedder(cfg.settings)

    console.print(f"[dim]Embedding query...[/dim]")
    query_vector = embedder.embed([query])[0]

    results = st.search(query_vector, app_name=app, top_k=top_k)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        console.print(f"\n[bold cyan]{i}.[/bold cyan] {r['path']}:{r['start_line']}-{r['end_line']}")
        console.print(f"   [dim]{r['app_name']} | {r['language']} | {r['symbol_type']}: {r['symbol_name']}[/dim]")
        console.print(f"   [dim]distance: {score:.4f}[/dim]")
        # Show first 3 lines of content
        preview = "\n".join(r["text"].split("\n")[:3])
        console.print(f"   {preview}")


@main.command()
def serve():
    """Start the MCP server (stdio mode) for VS Code / GitHub Copilot."""
    import sys
    from wrag.mcp_server import run_stdio

    print("Starting wRag MCP server (stdio)...", file=sys.stderr)
    run_stdio()


@main.command()
@click.option("--port", default=8787, help="Port to run the UI on (default 8787)")
def ui(port: int):
    """Start the web UI to preview search results and test queries."""
    from wrag.web_ui import run_ui

    console.print(f"[green]Starting wRag UI on http://localhost:{port}[/green]")
    run_ui(port=port)


@main.command()
@click.option("--debounce", default=2.0, help="Seconds to wait before re-indexing (default 2)")
def watch(debounce: float):
    """Watch registered workspaces and auto re-index on file changes."""
    from wrag.indexer import index_workspace
    from wrag.watcher import WorkspaceWatcher

    config = load_config()
    embedder_name = config.settings.embedding_model

    if not config.workspaces:
        console.print("[yellow]No workspaces registered. Use `wrag add` first.[/yellow]")
        return

    def on_change(app_name: str, changed_paths: set[str]):
        console.print(
            f"[cyan]⟳[/cyan] {len(changed_paths)} file(s) changed in [bold]{app_name}[/bold], re-indexing..."
        )
        from wrag.embedder import get_embedder

        source = config.find_source(app_name)
        if source and hasattr(source, "path"):
            embedder = get_embedder(embedder_name)
            result = index_workspace(source, config.settings, embedder, force=False)
            console.print(
                f"  [green]✓[/green] indexed {result.get('files_indexed', 0)} file(s), "
                f"{result.get('chunks_stored', 0)} chunk(s)"
            )

    workspaces = [(w.name, w.path) for w in config.workspaces]
    watcher = WorkspaceWatcher(
        workspaces=workspaces,
        settings=config.settings,
        on_change=on_change,
        debounce_seconds=debounce,
    )

    console.print(f"[green]Watching {len(workspaces)} workspace(s):[/green]")
    for name, path in workspaces:
        console.print(f"  • {name} → {path}")
    console.print("[dim]Press Ctrl+C to stop.[/dim]")

    watcher.start()
    watcher.wait()
    console.print("\n[dim]Watcher stopped.[/dim]")


@main.command()
@click.option("--reset", is_flag=True, help="Clear the request log")
def requests(reset: bool):
    """Show wRag request statistics — how many tool calls have been served."""
    from wrag.mcp_server import _STATS_FILE, get_request_stats

    if reset:
        if _STATS_FILE.exists():
            _STATS_FILE.unlink()
        console.print("[green]Request log cleared.[/green]")
        return

    stats = get_request_stats()

    if stats["total"] == 0:
        console.print("[yellow]No requests logged yet.[/yellow]")
        console.print("[dim]Start the MCP server (wrag serve) and use Copilot to generate logs.[/dim]")
        return

    console.print(f"\n[bold]wRag Request Stats[/bold]")
    console.print(f"  Total tool calls served:  [cyan]{stats['total']}[/cyan]")
    console.print(f"  Total results returned:   [cyan]{stats['total_results']}[/cyan]")
    console.print()

    console.print("[bold]By Tool:[/bold]")
    for tool, count in sorted(stats["by_tool"].items()):
        console.print(f"  {tool}: {count} calls")

    # Savings estimate
    estimated_native = stats["total"] * 4
    saved = estimated_native - stats["total"]
    pct = saved / max(estimated_native, 1) * 100
    console.print()
    console.print("[bold]Estimated Savings:[/bold]")
    console.print(f"  Without wRag: ~{estimated_native} requests (estimated)")
    console.print(f"  With wRag:     {stats['total']} requests (actual)")
    console.print(f"  [green bold]Saved: ~{saved} requests ({pct:.0f}%)[/green bold]")

    if stats["recent"]:
        console.print()
        console.print("[bold]Recent Queries:[/bold]")
        for r in stats["recent"][-10:]:
            console.print(f"  [{r['tool']}] \"{r['query'][:60]}\" → {r['results']} results")


@main.command()
@click.option("--record", is_flag=True, help="Record a new benchmark test interactively")
@click.option("--clear", is_flag=True, help="Clear all benchmark data")
def benchmark(record: bool, clear: bool):
    """View or record benchmark comparison data (with vs without wRag)."""
    from wrag.benchmark import get_benchmark_summary, record_test, _save_benchmark

    if clear:
        _save_benchmark({"tests": []})
        console.print("[green]Benchmark data cleared.[/green]")
        return

    if record:
        console.print("[bold]Record a benchmark test[/bold]")
        console.print("[dim]Run the same prompt with and without wRag, note the usage counter.[/dim]\n")
        prompt = click.prompt("Prompt tested")
        without_requests = click.prompt("Usage delta WITHOUT wRag (e.g. 186.1)", type=float)
        without_tool_calls = click.prompt("Tool calls visible WITHOUT wRag (count expandable items)", type=int)
        with_requests = click.prompt("Usage delta WITH wRag", type=float)
        with_tool_calls = click.prompt("Tool calls visible WITH wRag", type=int)
        notes = click.prompt("Notes (optional)", default="", show_default=False)

        record_test(
            prompt=prompt,
            without_wrag_requests=without_requests,
            with_wrag_requests=with_requests,
            without_wrag_tool_calls=without_tool_calls,
            with_wrag_tool_calls=with_tool_calls,
            notes=notes,
        )
        saved = without_requests - with_requests
        pct = (1 - with_requests / max(without_requests, 0.1)) * 100
        console.print(f"\n[green bold]✓ Recorded![/green bold] Saved {saved:.1f} requests ({pct:.0f}%)")
        return

    # Show summary
    summary = get_benchmark_summary()
    if summary["count"] == 0:
        console.print("[yellow]No benchmark data yet.[/yellow]")
        console.print("Run [bold]wrag benchmark --record[/bold] to add a test.")
        return

    console.print(f"\n[bold]Benchmark Results ({summary['count']} tests)[/bold]\n")

    table = Table(title="")
    table.add_column("#", style="dim")
    table.add_column("Prompt", max_width=40)
    table.add_column("Without wRag", style="red")
    table.add_column("With wRag", style="green")
    table.add_column("Saved", style="bold green")

    for i, t in enumerate(summary["tests"], 1):
        table.add_row(
            str(i),
            t["prompt"][:40],
            f"{t['without_wrag']['requests']:.1f} req ({t['without_wrag']['tool_calls']} calls)",
            f"{t['with_wrag']['requests']:.1f} req ({t['with_wrag']['tool_calls']} calls)",
            f"{t['savings']['requests_saved']:.1f} ({t['savings']['percentage']}%)",
        )

    console.print(table)
    totals = summary["totals"]
    console.print(f"\n[bold]Totals:[/bold]")
    console.print(f"  Without wRag: {totals['without_wrag_requests']:.1f} requests")
    console.print(f"  With wRag:    {totals['with_wrag_requests']:.1f} requests")
    console.print(f"  [green bold]Total saved: {totals['total_saved']:.1f} requests ({totals['average_savings_percent']}%)[/green bold]")


@main.command()
@click.option("--file", "otel_file", default=None, help="Path to OTel JSONL file (default: auto)")
@click.option("--reset", is_flag=True, help="Clear the OTel JSONL file")
def tokens(otel_file: str, reset: bool):
    """Show real token savings measured via OpenTelemetry.

    Requires OTel file export enabled in VS Code settings:
      "github.copilot.chat.otel.enabled": true
      "github.copilot.chat.otel.exporterType": "file"
      "github.copilot.chat.otel.outfile": "<wRag-dir>/.data/copilot-otel.jsonl"
    """
    from wrag.otel_analyzer import OTEL_FILE, get_token_summary, parse_otel_file

    path = otel_file or str(OTEL_FILE)

    if reset:
        import os
        if os.path.exists(path):
            os.remove(path)
            console.print("[green]OTel token log cleared.[/green]")
        else:
            console.print("[yellow]No OTel log file found.[/yellow]")
        return

    if not Path(path).exists():
        console.print(f"[yellow]OTel log not found:[/yellow] {path}")
        console.print("\nEnable OTel in dconnector933/.vscode/settings.json:")
        console.print('  "github.copilot.chat.otel.enabled": true')
        console.print('  "github.copilot.chat.otel.exporterType": "file"')
        console.print(f'  "github.copilot.chat.otel.outfile": "{path}"')
        console.print("\nThen reload VS Code and ask Copilot some questions.")
        return

    summary = get_token_summary()

    if not summary["has_data"]:
        console.print("[yellow]OTel file exists but no session data yet.[/yellow]")
        console.print("Ask Copilot questions in the dconnector933 workspace to generate data.")
        return

    savings = summary["savings"]
    console.print(f"\n[bold]Real Token Savings (OpenTelemetry data)[/bold]")
    console.print(f"[dim]Source: {path}[/dim]\n")

    # Summary cards
    console.print(f"  Sessions WITH wRag:     [bold green]{summary['wrag_session_count']}[/bold green]")
    console.print(f"  Sessions WITHOUT wRag:  [bold red]{summary['baseline_session_count']}[/bold red]")
    console.print()

    if savings["wrag_sessions"] > 0 and savings["baseline_sessions"] > 0:
        console.print(f"  Avg input tokens WITHOUT wRag:  [red]{savings['baseline_avg_input_tokens']:,}[/red]")
        console.print(f"  Avg input tokens WITH wRag:     [green]{savings['wrag_avg_input_tokens']:,}[/green]")
        console.print(f"  [bold green]Input token reduction:          {savings['input_token_reduction_pct']}%[/bold green]")
        console.print(f"  [bold green]Total input tokens saved:       {savings['total_input_tokens_saved']:,}[/bold green]")
    else:
        console.print("[dim]Need both wRag and non-wRag sessions to compare.[/dim]")
        console.print("[dim]Try asking questions with and without wRag MCP server running.[/dim]")

    # Per-session table
    sessions = summary["per_session"]
    if sessions:
        console.print()
        table = Table(title="Per-Session Breakdown")
        table.add_column("Session ID", style="dim", max_width=15)
        table.add_column("Used wRag")
        table.add_column("Input Tokens", justify="right")
        table.add_column("Output Tokens", justify="right")
        table.add_column("wRag Calls", justify="right", style="green")
        table.add_column("Native Calls", justify="right", style="red")

        for s in sessions[-20:]:  # last 20 sessions
            table.add_row(
                s["conversation_id"],
                "[green]✓ Yes[/green]" if s["used_wrag"] else "[red]✗ No[/red]",
                f"{s['input_tokens']:,}",
                f"{s['output_tokens']:,}",
                str(s["wrag_tool_calls"]),
                str(s["native_tool_calls"]),
            )

        console.print(table)


if __name__ == "__main__":
    main()
