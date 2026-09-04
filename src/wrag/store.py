"""LanceDB vector store wrapper — upsert, delete, search, stats."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import pyarrow as pa

from wrag.config import _PROJECT_ROOT

DATA_DIR = _PROJECT_ROOT / ".data"
VECTORS_DIR = DATA_DIR / "vectors"


def _ensure_data_dir():
    """Create .data/vectors/ directory if it doesn't exist."""
    VECTORS_DIR.mkdir(parents=True, exist_ok=True)


def connect():
    """Open or create the LanceDB database."""
    import lancedb

    _ensure_data_dir()
    return lancedb.connect(str(VECTORS_DIR))


TABLE_NAME = "chunks"

# Schema for the chunks table
SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("path", pa.string()),
    pa.field("app_name", pa.string()),
    pa.field("language", pa.string()),
    pa.field("symbol_name", pa.string()),
    pa.field("symbol_type", pa.string()),
    pa.field("start_line", pa.int32()),
    pa.field("end_line", pa.int32()),
    pa.field("source_type", pa.string()),
    pa.field("indexed_at", pa.float64()),
    pa.field("vector", pa.list_(pa.float32(), 384)),
])


def _get_or_create_table(db, dimension: int = 384):
    """Get existing table or create empty one with correct schema."""
    schema = pa.schema([
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("path", pa.string()),
        pa.field("app_name", pa.string()),
        pa.field("language", pa.string()),
        pa.field("symbol_name", pa.string()),
        pa.field("symbol_type", pa.string()),
        pa.field("start_line", pa.int32()),
        pa.field("end_line", pa.int32()),
        pa.field("source_type", pa.string()),
        pa.field("indexed_at", pa.float64()),
        pa.field("vector", pa.list_(pa.float32(), dimension)),
    ])

    if TABLE_NAME in db.table_names():
        return db.open_table(TABLE_NAME)
    return db.create_table(TABLE_NAME, schema=schema)


def upsert_chunks(
    app_name: str,
    chunks: list[dict],
    vectors: list[list[float]],
    dimension: int = 384,
    table=None,
    skip_delete: bool = False,
) -> int:
    """Insert or update chunks in the store.

    Args:
        app_name: Source application name
        chunks: List of chunk dicts (from Chunk.to_dict())
        vectors: Corresponding embedding vectors
        dimension: Vector dimension (default 384 for MiniLM)
        table: Optional pre-opened LanceDB table handle (avoids reopen per batch)
        skip_delete: When True, skip the per-id predicate delete (caller
            already batch-deleted by path).

    Returns:
        Number of chunks upserted
    """
    if not chunks:
        return 0

    if table is None:
        db = connect()
        table = _get_or_create_table(db, dimension)

    now = time.time()
    records = []
    for chunk, vector in zip(chunks, vectors):
        records.append({
            "id": chunk["id"],
            "text": chunk["text"],
            "path": chunk["path"],
            "app_name": chunk["app_name"],
            "language": chunk["language"],
            "symbol_name": chunk["symbol_name"],
            "symbol_type": chunk["symbol_type"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "source_type": chunk.get("source_type", "workspace"),
            "indexed_at": now,
            "vector": vector,
        })

    if not skip_delete:
        ids_to_replace = [r["id"] for r in records]
        try:
            table.delete(
                f"id IN {tuple(ids_to_replace)}"
                if len(ids_to_replace) > 1
                else f"id = '{ids_to_replace[0]}'"
            )
        except Exception:
            pass

    table.add(records)
    return len(records)


def delete_app(app_name: str) -> int:
    """Delete all chunks for a given app. Returns count deleted."""
    db = connect()
    if TABLE_NAME not in db.table_names():
        return 0

    table = db.open_table(TABLE_NAME)
    # Count before
    try:
        before = table.count_rows(f"app_name = '{app_name}'")
    except Exception:
        before = 0

    if before > 0:
        table.delete(f"app_name = '{app_name}'")

    return before


def delete_by_path(app_name: str, file_path: str) -> int:
    """Delete all chunks for a specific file path within an app."""
    db = connect()
    if TABLE_NAME not in db.table_names():
        return 0

    table = db.open_table(TABLE_NAME)
    try:
        count = table.count_rows(f"app_name = '{app_name}' AND path = '{file_path}'")
    except Exception:
        count = 0

    if count > 0:
        table.delete(f"app_name = '{app_name}' AND path = '{file_path}'")

    return count


def _sql_quote(s: str) -> str:
    """Escape a value for embedding into a DataFusion SQL literal."""
    return s.replace("'", "''")


def delete_by_paths(app_name: str, file_paths: list[str], table=None) -> int:
    """Batched delete — one predicate scan per chunk of paths instead of per file.

    Args:
        app_name: source app scope
        file_paths: relative paths to delete
        table: optional pre-opened LanceDB table handle for reuse
    """
    if not file_paths:
        return 0

    if table is None:
        db = connect()
        if TABLE_NAME not in db.table_names():
            return 0
        table = db.open_table(TABLE_NAME)

    chunk = 400
    total = 0
    for i in range(0, len(file_paths), chunk):
        batch = file_paths[i : i + chunk]
        in_list = ", ".join(f"'{_sql_quote(p)}'" for p in batch)
        predicate = f"app_name = '{_sql_quote(app_name)}' AND path IN ({in_list})"
        try:
            table.delete(predicate)
            total += len(batch)
        except Exception:
            # Skip malformed batch; caller can retry per-file if needed
            continue
    return total


def search(
    query_vector: list[float],
    app_name: Optional[str] = None,
    top_k: int = 10,
    source_type: Optional[str] = None,
) -> list[dict]:
    """Semantic search using ANN.

    Args:
        query_vector: Query embedding vector
        app_name: Optional filter by app name
        top_k: Number of results
        source_type: Optional filter by source type ("workspace" or "confluence")

    Returns:
        List of result dicts with score
    """
    db = connect()
    if TABLE_NAME not in db.table_names():
        return []

    table = db.open_table(TABLE_NAME)

    query = table.search(query_vector).limit(top_k)

    # Apply filters
    filters = []
    if app_name:
        filters.append(f"app_name = '{app_name}'")
    if source_type:
        filters.append(f"source_type = '{source_type}'")

    if filters:
        query = query.where(" AND ".join(filters))

    results = query.to_list()

    return [
        {
            "id": r["id"],
            "text": r["text"],
            "path": r["path"],
            "app_name": r["app_name"],
            "language": r["language"],
            "symbol_name": r["symbol_name"],
            "symbol_type": r["symbol_type"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "source_type": r["source_type"],
            "score": r.get("_distance", 0.0),
        }
        for r in results
    ]


def search_symbol(
    name: str,
    app_name: Optional[str] = None,
) -> list[dict]:
    """Search by symbol name (metadata filter, not vector search)."""
    db = connect()
    if TABLE_NAME not in db.table_names():
        return []

    table = db.open_table(TABLE_NAME)

    filters = [f"symbol_name LIKE '%{name}%'"]
    if app_name:
        filters.append(f"app_name = '{app_name}'")

    try:
        results = table.search().where(" AND ".join(filters)).limit(20).to_list()
    except Exception:
        # Fallback: scan all and filter in Python
        all_rows = table.to_arrow().to_pydict()
        results = []
        for i in range(len(all_rows.get("id", []))):
            sym = all_rows["symbol_name"][i]
            app = all_rows["app_name"][i]
            if name.lower() in sym.lower():
                if app_name and app != app_name:
                    continue
                results.append({k: all_rows[k][i] for k in all_rows if k != "vector"})
                if len(results) >= 20:
                    break

    return [
        {
            "id": r["id"],
            "text": r["text"],
            "path": r["path"],
            "app_name": r["app_name"],
            "language": r["language"],
            "symbol_name": r["symbol_name"],
            "symbol_type": r["symbol_type"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "source_type": r["source_type"],
        }
        for r in results
    ]


def stats() -> dict[str, dict]:
    """Get per-app statistics.

    Returns:
        Dict of {app_name: {chunk_count, languages, last_indexed}}
    """
    db = connect()
    if TABLE_NAME not in db.table_names():
        return {}

    table = db.open_table(TABLE_NAME)

    # Use to_list() instead of to_pandas() to avoid pylance dependency
    try:
        rows = table.to_arrow().to_pydict()
    except Exception:
        return {}

    if not rows or not rows.get("app_name"):
        return {}

    # Build stats per app
    result = {}
    for i in range(len(rows["app_name"])):
        app = rows["app_name"][i]
        if app not in result:
            result[app] = {
                "chunk_count": 0,
                "paths": set(),
                "languages": set(),
                "source_type": rows["source_type"][i],
                "last_indexed": 0.0,
            }
        result[app]["chunk_count"] += 1
        result[app]["paths"].add(rows["path"][i])
        result[app]["languages"].add(rows["language"][i])
        indexed_at = rows["indexed_at"][i]
        if indexed_at > result[app]["last_indexed"]:
            result[app]["last_indexed"] = indexed_at

    # Convert sets to sorted lists and path count
    for app in result:
        result[app]["file_count"] = len(result[app]["paths"])
        result[app]["languages"] = sorted(result[app]["languages"])
        del result[app]["paths"]

    return result


def total_chunks() -> int:
    """Get total number of chunks in the store."""
    db = connect()
    if TABLE_NAME not in db.table_names():
        return 0
    table = db.open_table(TABLE_NAME)
    return table.count_rows()
