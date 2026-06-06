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
    from wrag.mcp_server import run_stdio

    console.print("[dim]Starting wRag MCP server (stdio)...[/dim]", err=True)
    run_stdio()


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


if __name__ == "__main__":
    main()
