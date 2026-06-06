"""Indexer — orchestrates file walking, hash comparison, chunking, embedding, and storage."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from wrag.chunker import chunk_file
from wrag.config import (
    Config,
    ConfluenceSource,
    Settings,
    WorkspaceSource,
    _PROJECT_ROOT,
    load_config,
)
from wrag.embedder import Embedder, get_embedder
from wrag.sources.workspace import FileEntry, walk_workspace
from wrag import store

console = Console()

MANIFESTS_DIR = _PROJECT_ROOT / ".data" / "manifests"


def _load_manifest(app_name: str) -> dict[str, str]:
    """Load file hash manifest for an app. Returns {rel_path: content_hash}."""
    manifest_path = MANIFESTS_DIR / f"{app_name}.json"
    if manifest_path.exists():
        with open(manifest_path, "r") as f:
            return json.load(f)
    return {}


def _save_manifest(app_name: str, manifest: dict[str, str]) -> None:
    """Save file hash manifest for an app."""
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = MANIFESTS_DIR / f"{app_name}.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


def index_workspace(
    source: WorkspaceSource,
    settings: Settings,
    embedder: Embedder,
    force: bool = False,
) -> dict:
    """Index a local workspace source.

    Args:
        source: Workspace source config
        settings: Global settings
        embedder: Configured embedder instance
        force: If True, re-index everything ignoring hashes

    Returns:
        Stats dict: {files_scanned, files_indexed, files_skipped, chunks_added, elapsed}
    """
    start_time = time.time()
    app_name = source.name
    workspace_path = source.path

    if not Path(workspace_path).is_dir():
        console.print(f"[red]Error:[/red] Workspace path not found: {workspace_path}")
        return {"error": f"Path not found: {workspace_path}"}

    # Load existing manifest
    old_manifest = {} if force else _load_manifest(app_name)
    new_manifest: dict[str, str] = {}

    files_scanned = 0
    files_indexed = 0
    files_skipped = 0
    chunks_added = 0

    # Collect files that need indexing
    files_to_index: list[FileEntry] = []
    all_files: list[FileEntry] = []

    console.print(f"[dim]Scanning {workspace_path}...[/dim]")

    for file_entry in walk_workspace(workspace_path, settings):
        files_scanned += 1
        all_files.append(file_entry)
        new_manifest[file_entry.path] = file_entry.content_hash

        if file_entry.path in old_manifest and old_manifest[file_entry.path] == file_entry.content_hash:
            files_skipped += 1
        else:
            files_to_index.append(file_entry)

    # Find deleted files (in old manifest but not in new)
    deleted_files = set(old_manifest.keys()) - set(new_manifest.keys())
    for deleted_path in deleted_files:
        store.delete_by_path(app_name, deleted_path)

    if not files_to_index:
        console.print(f"[green]✓[/green] No changes detected. {files_skipped} files unchanged.")
        _save_manifest(app_name, new_manifest)
        return {
            "files_scanned": files_scanned,
            "files_indexed": 0,
            "files_skipped": files_skipped,
            "files_deleted": len(deleted_files),
            "chunks_added": 0,
            "elapsed": time.time() - start_time,
        }

    # Process files: chunk → embed → store
    console.print(f"[dim]Indexing {len(files_to_index)} changed files...[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Indexing", total=len(files_to_index))

        # Process in batches for efficient embedding
        batch_size = 20
        for i in range(0, len(files_to_index), batch_size):
            batch = files_to_index[i : i + batch_size]
            batch_chunks = []

            for file_entry in batch:
                # Delete old chunks for this file
                store.delete_by_path(app_name, file_entry.path)

                # Chunk the file
                chunks = chunk_file(
                    content=file_entry.content,
                    file_path=file_entry.path,
                    app_name=app_name,
                    max_lines=settings.chunk_max_lines,
                )
                batch_chunks.extend(chunks)

            if batch_chunks:
                # Embed all chunks in this batch
                texts = [c.text for c in batch_chunks]
                vectors = embedder.embed(texts)

                # Store
                chunk_dicts = [c.to_dict() for c in batch_chunks]
                count = store.upsert_chunks(
                    app_name=app_name,
                    chunks=chunk_dicts,
                    vectors=vectors,
                    dimension=embedder.dimension(),
                )
                chunks_added += count

            files_indexed += len(batch)
            progress.update(task, advance=len(batch))

    # Save updated manifest
    _save_manifest(app_name, new_manifest)

    elapsed = time.time() - start_time
    console.print(
        f"[green]✓[/green] Indexed {files_indexed} files → {chunks_added} chunks "
        f"({files_skipped} unchanged, {len(deleted_files)} deleted) in {elapsed:.1f}s"
    )

    return {
        "files_scanned": files_scanned,
        "files_indexed": files_indexed,
        "files_skipped": files_skipped,
        "files_deleted": len(deleted_files),
        "chunks_added": chunks_added,
        "elapsed": elapsed,
    }


def index_source(
    name: Optional[str] = None,
    force: bool = False,
) -> None:
    """Index one or all registered sources.

    Args:
        name: Source name to index (None = all sources)
        force: Re-index everything ignoring hashes
    """
    config = load_config()
    embedder = get_embedder(config.settings)

    if name:
        source = config.find_source(name)
        if source is None:
            console.print(f"[red]Error:[/red] Source '{name}' not found. Run `wrag list` to see registered sources.")
            return

        if isinstance(source, WorkspaceSource):
            index_workspace(source, config.settings, embedder, force=force)
        elif isinstance(source, ConfluenceSource):
            console.print(f"[yellow]Confluence indexing will be available in Sprint 4.[/yellow]")
        return

    # Index all sources
    if not config.workspaces and not config.confluences:
        console.print("[dim]No sources registered. Use `wrag add` or `wrag add-confluence`.[/dim]")
        return

    for ws in config.workspaces:
        console.print(f"\n[bold]Indexing workspace: {ws.name}[/bold]")
        index_workspace(ws, config.settings, embedder, force=force)

    for conf in config.confluences:
        console.print(f"\n[yellow]Skipping confluence '{conf.name}' (Sprint 4)[/yellow]")
