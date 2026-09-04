"""Indexer — orchestrates file walking, hash comparison, chunking, embedding, and storage."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

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


def _short_path(p: str, width: int = 48) -> str:
    """Truncate long paths from the left for progress-line display."""
    return p if len(p) <= width else "…" + p[-(width - 1):]


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


def _load_stat_manifest(app_name: str) -> dict[str, str]:
    """Load {rel_path: "size:mtime_ns"} sidecar cache."""
    p = MANIFESTS_DIR / f"{app_name}.stat.json"
    if p.exists():
        with open(p, "r") as f:
            return json.load(f)
    return {}


def _save_stat_manifest(app_name: str, stat_manifest: dict[str, str]) -> None:
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    p = MANIFESTS_DIR / f"{app_name}.stat.json"
    with open(p, "w") as f:
        json.dump(stat_manifest, f, indent=2)


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
    stat_cache = {} if force else _load_stat_manifest(app_name)
    new_manifest: dict[str, str] = {}
    new_stat_manifest: dict[str, str] = {}

    files_scanned = 0
    files_indexed = 0
    files_skipped = 0
    chunks_added = 0

    # Collect files that need indexing
    files_to_index: list[FileEntry] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]Scanning[/cyan] {task.description}"),
        console=console,
        transient=True,
    ) as scan_progress:
        scan_task = scan_progress.add_task(
            f"{workspace_path} — 0 files (0 to reindex)",
            total=None,
        )
        for file_entry in walk_workspace(
            workspace_path,
            settings,
            stat_cache=stat_cache,
            known_hashes=old_manifest,
        ):
            files_scanned += 1
            new_manifest[file_entry.path] = file_entry.content_hash
            new_stat_manifest[file_entry.path] = f"{file_entry.size}:{file_entry.mtime_ns}"

            if file_entry.path in old_manifest and old_manifest[file_entry.path] == file_entry.content_hash:
                files_skipped += 1
            else:
                files_to_index.append(file_entry)

            if files_scanned % 250 == 0:
                scan_progress.update(
                    scan_task,
                    description=f"{workspace_path} — {files_scanned} files ({len(files_to_index)} to reindex)",
                )

    scan_elapsed = time.time() - start_time
    console.print(
        f"[dim]Scan done in {scan_elapsed:.1f}s — "
        f"{files_scanned} files ({files_skipped} unchanged, "
        f"{len(files_to_index)} to reindex)[/dim]"
    )

    # Find deleted files (in old manifest but not in new)
    deleted_files = set(old_manifest.keys()) - set(new_manifest.keys())
    if deleted_files:
        console.print(f"[dim]Removing {len(deleted_files)} deleted files from index...[/dim]")
        store.delete_by_paths(app_name, list(deleted_files))

    if not files_to_index:
        console.print(f"[green]✓[/green] No changes detected. {files_skipped} files unchanged.")
        _save_manifest(app_name, new_manifest)
        _save_stat_manifest(app_name, new_stat_manifest)
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

    # Reuse a single LanceDB table handle across the whole run
    db = store.connect()
    table = store._get_or_create_table(db, embedder.dimension())

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.fields[phase]:<8}[/bold blue]"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TextColumn("• {task.fields[chunks]} chunks"),
        TextColumn("• [dim]{task.fields[detail]}[/dim]"),
        TextColumn("• elapsed"),
        TimeElapsedColumn(),
        TextColumn("• ETA"),
        TimeRemainingColumn(compact=True),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Indexing",
            total=len(files_to_index),
            phase="starting",
            chunks=0,
            detail="",
        )

        # Larger batches amortize embedding + DB overhead across more files
        batch_size = 100
        total_batches = (len(files_to_index) + batch_size - 1) // batch_size

        for i in range(0, len(files_to_index), batch_size):
            batch = files_to_index[i : i + batch_size]
            batch_num = i // batch_size + 1

            # Phase 1: delete old chunks for this batch's paths
            progress.update(
                task,
                phase="cleanup",
                detail=f"batch {batch_num}/{total_batches} · {len(batch)} files",
            )
            store.delete_by_paths(
                app_name,
                [fe.path for fe in batch],
                table=table,
            )

            # Phase 2: chunk each file
            progress.update(task, phase="chunking")
            batch_chunks = []
            for file_entry in batch:
                progress.update(
                    task,
                    detail=f"chunk · {_short_path(file_entry.path)}",
                )
                chunks = chunk_file(
                    content=file_entry.content,
                    file_path=file_entry.path,
                    app_name=app_name,
                    max_lines=settings.chunk_max_lines,
                )
                batch_chunks.extend(chunks)

            if batch_chunks:
                # Phase 3: embed all chunks in this batch
                progress.update(
                    task,
                    phase="embedding",
                    detail=f"batch {batch_num}/{total_batches} · {len(batch_chunks)} chunks",
                )
                texts = [c.text for c in batch_chunks]
                vectors = embedder.embed(texts)

                # Phase 4: write to LanceDB
                progress.update(task, phase="storing")
                chunk_dicts = [c.to_dict() for c in batch_chunks]
                count = store.upsert_chunks(
                    app_name=app_name,
                    chunks=chunk_dicts,
                    vectors=vectors,
                    dimension=embedder.dimension(),
                    table=table,
                    skip_delete=True,
                )
                chunks_added += count

            files_indexed += len(batch)
            progress.update(
                task,
                advance=len(batch),
                phase="done" if files_indexed >= len(files_to_index) else "next",
                chunks=chunks_added,
                detail=f"batch {batch_num}/{total_batches} complete",
            )

    # Save updated manifests
    _save_manifest(app_name, new_manifest)
    _save_stat_manifest(app_name, new_stat_manifest)

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
            index_confluence(source, config.settings, embedder, force=force)
        return

    # Index all sources
    if not config.workspaces and not config.confluences:
        console.print("[dim]No sources registered. Use `wrag add` or `wrag add-confluence`.[/dim]")
        return

    for ws in config.workspaces:
        console.print(f"\n[bold]Indexing workspace: {ws.name}[/bold]")
        index_workspace(ws, config.settings, embedder, force=force)

    for conf in config.confluences:
        console.print(f"\n[bold]Indexing confluence: {conf.name}[/bold]")
        index_confluence(conf, config.settings, embedder, force=force)


def index_confluence(
    source: ConfluenceSource,
    settings: Settings,
    embedder: Embedder,
    force: bool = False,
) -> dict:
    """Index a Confluence space source.

    Args:
        source: Confluence source config
        settings: Global settings
        embedder: Configured embedder instance
        force: If True, re-index everything ignoring page versions

    Returns:
        Stats dict: {pages_fetched, pages_indexed, pages_skipped, chunks_added, elapsed}
    """
    from wrag.sources.confluence import (
        ConfluenceClient,
        chunk_confluence_page,
        get_confluence_credentials,
    )

    start_time = time.time()
    app_name = source.name

    # Get credentials
    try:
        email, token = get_confluence_credentials(email_override=source.email)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        return {"error": str(e)}

    # Load existing manifest (page_id → version)
    old_manifest = {} if force else _load_manifest(app_name)
    new_manifest: dict[str, str] = {}

    # Fetch pages from Confluence
    console.print(f"[dim]Fetching pages from {source.domain} (space: {source.space_key})...[/dim]")

    client = ConfluenceClient(domain=source.domain, email=email, token=token)
    try:
        pages = client.fetch_pages(space_key=source.space_key)
    except (PermissionError, ValueError, httpx.HTTPError) as e:
        console.print(f"[red]Error:[/red] {e}")
        return {"error": str(e)}
    finally:
        client.close()

    console.print(f"[dim]Fetched {len(pages)} pages.[/dim]")

    pages_indexed = 0
    pages_skipped = 0
    chunks_added = 0

    # Determine which pages need re-indexing
    pages_to_index = []
    for page in pages:
        version_key = f"{page.page_id}:v{page.version}"
        new_manifest[page.page_id] = version_key

        if page.page_id in old_manifest and old_manifest[page.page_id] == version_key:
            pages_skipped += 1
        else:
            pages_to_index.append(page)

    # Find deleted pages
    deleted_pages = set(old_manifest.keys()) - set(new_manifest.keys())
    for deleted_id in deleted_pages:
        # Delete chunks for removed pages
        store.delete_by_path(app_name, f"page:{deleted_id}")

    if not pages_to_index:
        console.print(f"[green]✓[/green] No changes detected. {pages_skipped} pages unchanged.")
        _save_manifest(app_name, new_manifest)
        return {
            "pages_fetched": len(pages),
            "pages_indexed": 0,
            "pages_skipped": pages_skipped,
            "pages_deleted": len(deleted_pages),
            "chunks_added": 0,
            "elapsed": time.time() - start_time,
        }

    # Process pages: chunk → embed → store
    console.print(f"[dim]Indexing {len(pages_to_index)} changed pages...[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Indexing pages", total=len(pages_to_index))

        # Process in batches
        batch_size = 10
        for i in range(0, len(pages_to_index), batch_size):
            batch = pages_to_index[i : i + batch_size]
            batch_chunks = []

            for page in batch:
                # Chunk the page
                chunks = chunk_confluence_page(page, app_name)
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

            pages_indexed += len(batch)
            progress.update(task, advance=len(batch))

    # Save updated manifest
    _save_manifest(app_name, new_manifest)

    elapsed = time.time() - start_time
    console.print(
        f"[green]✓[/green] Indexed {pages_indexed} pages → {chunks_added} chunks "
        f"({pages_skipped} unchanged, {len(deleted_pages)} deleted) in {elapsed:.1f}s"
    )

    return {
        "pages_fetched": len(pages),
        "pages_indexed": pages_indexed,
        "pages_skipped": pages_skipped,
        "pages_deleted": len(deleted_pages),
        "chunks_added": chunks_added,
        "elapsed": elapsed,
    }
