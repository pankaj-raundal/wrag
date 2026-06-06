# wRag — Implementation Plan

## Phase 1: Project Skeleton + Config

1. Create project structure with `pyproject.toml`, `.gitignore`, src layout
2. Implement `config.py` — YAML-based registry:
   - `workspaces:` list with `{name, path}` entries
   - `confluences:` list with `{name, domain, space_key, email}` entries
   - `settings:` embedding_model, exclusions, chunk_max_lines
3. Implement `cli.py` basics:
   - `wrag add <name> <path>` — register workspace
   - `wrag add-confluence <name> --domain <x> --space <key>` — register Confluence space
   - `wrag remove <name>` — unregister (workspace or confluence)
   - `wrag list` — show all registered sources
   - `wrag config` — show current settings

## Phase 2: Chunker + Embedder

4. Implement `chunker.py` — tree-sitter AST chunking:
   - Python: function_definition, class_definition
   - PHP: function_declaration, method_declaration, class_declaration
   - YAML/JSON: top-level keys
   - Markdown: heading boundaries (##)
   - Shell/other: 60-line windows with 10-line overlap (fallback)
   - Output: `{id, text, path, app_name, language, symbol_name, symbol_type, start_line, end_line}`
5. Implement `embedder.py`:
   - `LocalEmbedder` — `all-MiniLM-L6-v2` via sentence-transformers, batch encode
   - `OpenAIEmbedder` — `text-embedding-3-small` API
   - Factory: `get_embedder(config)` returns configured embedder
   - Interface: `embed(texts: list[str]) -> list[list[float]]`

## Phase 3: Vector Store + Indexer

6. Implement `store.py` — LanceDB wrapper:
   - `connect()` → open/create `.data/vectors/` DB
   - `upsert_chunks(app_name, chunks_with_vectors)` — merge_insert by ID
   - `delete_app(app_name)` — remove all chunks for an app
   - `search(query_vector, app_name=None, top_k=10)` — ANN search with optional filter
   - `search_symbol(name, app_name=None)` — metadata filter on symbol_name
   - `stats()` — per-app chunk counts, last indexed time
7. Implement `indexer.py` — orchestration:
   - Walk workspace files (respecting exclusions)
   - Compute sha256 hashes per file
   - Compare with stored manifests → only re-process changed
   - chunk → embed → upsert changed; remove deleted
   - Save manifest: `.data/manifests/<app_name>.json`
8. CLI commands:
   - `wrag index [app_name]` — index one or all sources
   - `wrag index --force` — re-index everything
   - `wrag status` — per-source stats

## Phase 3.5: Confluence Source

9. Implement `sources/confluence.py`:
   - Auth via email + API token (from `~/.config/dai/credentials.env`)
   - Fetch pages: `GET /wiki/api/v2/pages?spaceKey=X&body-format=storage` (paginated)
   - HTML → text conversion (stdlib html.parser)
   - Chunk at `<h1>/<h2>/<h3>` heading boundaries
   - Output: `{id, text, app_name, source_type:"confluence", page_title, page_url, section_heading}`
   - Incremental: `page_id + version.number` as hash equivalent
10. Wire into indexer: detect source type from config, dispatch to handler

## Phase 4: MCP Server

11. Implement `mcp_server.py` with FastMCP:
    - `search_code(query, app_name?, top_k?)` — semantic search, returns code chunks
    - `search_docs(query, app_name?, top_k?)` — Confluence chunks only
    - `search_symbol(name, app_name?)` — find by symbol name
    - `list_apps()` — show sources with stats
    - `app_overview(app_name)` — structure summary
12. CLI: `wrag serve` (stdio mode)
13. VS Code integration: `.vscode/mcp.json`

## Phase 5: File Watcher

14. Implement `watcher.py`:
    - watchdog monitors registered workspace paths
    - Debounce 5s → batch re-index affected files
    - `wrag watch` (foreground) / `wrag watch --daemon`
    - Confluence: not watched (remote); re-index on demand

## Phase 6: Polish + GitHub

15. README with setup + usage guide
16. Push to GitHub
