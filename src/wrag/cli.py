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


if __name__ == "__main__":
    main()
