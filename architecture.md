# wRag — Architecture

## Overview

wRag is a local-first codebase RAG (Retrieval-Augmented Generation) tool that indexes registered workspaces and Confluence spaces into a vector database, then exposes an MCP server for GitHub Copilot to query. This reduces Copilot credit consumption by providing pre-indexed context in a single MCP call instead of multiple workspace explorations.

## System Diagram

```
┌──────────────────────────────────────────────────────────────┐
│  VS Code + GitHub Copilot                                    │
│    ↕ MCP (stdio transport)                                   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  wRag MCP Server (FastMCP)                             │  │
│  │   Tools: search_code, search_docs, search_symbol,      │  │
│  │          list_apps, app_overview                        │  │
│  └────────────────────────┬───────────────────────────────┘  │
│                           │                                   │
│  ┌────────────────────────▼───────────────────────────────┐  │
│  │  LanceDB (embedded vector DB)                          │  │
│  │   Storage: .data/vectors/                              │  │
│  │   Per-chunk: id, vector, text, path, app_name,         │  │
│  │             language, symbol_name, source_type          │  │
│  └────────────────────────┬───────────────────────────────┘  │
│                           │                                   │
│  ┌────────────────────────▼───────────────────────────────┐  │
│  │  Indexer                                               │  │
│  │   - Walks files / fetches Confluence pages             │  │
│  │   - Incremental: sha256 hash comparison                │  │
│  │   - Dispatches to source handlers                      │  │
│  └──────┬─────────────────────────────────┬───────────────┘  │
│         │                                 │                   │
│  ┌──────▼──────────┐           ┌──────────▼───────────────┐  │
│  │  Chunker         │           │  Embedder                │  │
│  │  (tree-sitter)   │           │  - Local: MiniLM-L6-v2   │  │
│  │  AST-aware       │           │  - Optional: OpenAI      │  │
│  └──────────────────┘           └──────────────────────────┘  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Sources                                               │  │
│  │   - workspace.py: local filesystem (tree-sitter)       │  │
│  │   - confluence.py: REST API → HTML→text → headings     │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Watcher (watchdog)                                    │  │
│  │   - Monitors registered workspace paths                │  │
│  │   - Debounces (5s) → triggers incremental re-index     │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| Vector DB | LanceDB | Embedded (directory-based), native upsert/delete by ID, zero server process |
| Embeddings (default) | all-MiniLM-L6-v2 (sentence-transformers) | 80MB model, 384-dim, fast on CPU |
| Embeddings (optional) | OpenAI text-embedding-3-small | Higher quality, requires API key |
| Code chunking | tree-sitter + tree-sitter-languages | AST-aware (function/class boundaries), Python+PHP+Bash+YAML+JSON |
| MCP server | FastMCP (mcp SDK) | Official Python SDK, stdio transport, decorator-based tools |
| CLI | Click | Lightweight, consistent with existing tooling |
| File watcher | watchdog | Lightweight filesystem event monitoring |
| HTTP client | httpx | For Confluence REST API calls |
| Config | PyYAML | Simple YAML workspace/source registry |
| Output | Rich | Progress bars, tables, formatted terminal output |

## Data Flow

### Indexing Flow

```
1. User runs: wrag index <app_name>
2. Config loaded → resolve source type (workspace or confluence)
3. Source handler:
   a. Workspace: walk files → filter exclusions → read content
   b. Confluence: paginated API fetch → HTML to text
4. Hash comparison: skip unchanged files/pages
5. Chunker: split into semantic chunks (AST nodes or heading sections)
6. Embedder: batch encode chunks → 384-dim vectors
7. Store: upsert chunks into LanceDB (merge_insert by ID)
8. Manifest: save file hashes to .data/manifests/<app>.json
```

### Query Flow (MCP)

```
1. Copilot sends MCP tool call: search_code("pipeline orchestrator", app_name="devopsagent")
2. MCP server receives → embeds query string → 384-dim vector
3. LanceDB ANN search with optional app_name filter → top_k results
4. Format results: file path, line numbers, code snippet, relevance score
5. Return to Copilot as tool response → Copilot uses as context
```

## Key Design Decisions

1. **Local-only storage**: Vector DB + manifests in `.data/` within project dir; never uploaded
2. **No LLM for indexing**: Embeddings are deterministic (sentence-transformers), zero AI cost
3. **MCP stdio transport**: Standard for VS Code Copilot; no HTTP server needed
4. **tree-sitter chunking**: Respects function/class/method boundaries; line-based fallback for unsupported languages
5. **Explicit registration**: User controls which workspaces/spaces via `wrag add`
6. **Incremental by default**: sha256 hashes (files) or version numbers (Confluence) skip unchanged content
7. **Confluence credentials**: Reuses `~/.config/dai/credentials.env` (CONFLUENCE_EMAIL + CONFLUENCE_TOKEN)
8. **Cross-workspace search**: Default searches ALL indexed sources; optional app_name filter scopes it

## Exclusions (not indexed)

- Directories: `vendor/`, `node_modules/`, `.git/`, `__pycache__/`, `.venv/`, `.data/`
- Extensions: `.lock`, `.min.js`, `.map`, `.sql`, `.patch`, `.gz`, `.zip`, `.png`, `.jpg`
- Binary files (detected by null byte check)

## MCP Tools Exposed to Copilot

| Tool | Purpose | Params |
|------|---------|--------|
| `search_code` | Semantic code search across indexed workspaces | `query`, `app_name?`, `top_k?` |
| `search_docs` | Search Confluence-sourced chunks only | `query`, `app_name?`, `top_k?` |
| `search_symbol` | Find function/class/method by name | `name`, `app_name?` |
| `list_apps` | Show all registered & indexed sources with stats | — |
| `app_overview` | High-level structure of a specific app | `app_name` |

## CLI Commands

| Command | Purpose |
|---------|---------|
| `wrag add <name> <path>` | Register a local workspace |
| `wrag add-confluence <name> --domain X --space Y` | Register a Confluence space |
| `wrag remove <name>` | Unregister a source |
| `wrag list` | Show all registered sources |
| `wrag index [name]` | Index one or all sources |
| `wrag index --force` | Re-index ignoring hashes |
| `wrag status` | Per-source stats (chunks, last indexed) |
| `wrag search <query>` | CLI search for testing |
| `wrag serve` | Start MCP server (stdio) |
| `wrag watch` | Start file watcher daemon |
| `wrag config` | Show current config |
